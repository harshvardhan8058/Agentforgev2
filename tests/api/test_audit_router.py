"""API tests: the audit trail records real administrative actions and is org-scoped.

Unit tests on the store and the service cannot show that anything is *recorded* — that was
the defect class this codebase has produced twice (a store with no router, a seam with no
caller). So these drive the real app: perform an administrative action through its endpoint,
then read ``GET /audit-events`` and assert the trail describes it.

Also covered: RBAC (``read_audit_log`` from admin upwards), cross-tenant isolation, the
filters, and the two properties that make the trail trustworthy — a failed action is not
recorded, and no credential ever appears in it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from agentforge.api.deps import get_current_principal
from agentforge.config.settings import Settings
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Permission, Role
from agentforge.main import create_app

from tests.enterprise_helpers import install_enterprise_auth


def _make_settings(**overrides) -> Settings:
    base = dict(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def wired():
    """Return ``(app, client, headers, org_id, ctx)`` for an OWNER principal."""
    settings = _make_settings()
    app = create_app(settings)
    app.state.settings = settings
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    return app, TestClient(app, raise_server_exceptions=False), headers, org_id, ctx


def _events(client: TestClient, headers, **params) -> list[dict]:
    resp = client.get("/audit-events", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_user(ctx, email: str) -> None:
    ctx.identity_store.create_user(email, ctx.auth_service.hash_password("pw-" + email))


# --- the trail records what happened ----------------------------------------------


def test_member_lifecycle_is_recorded_end_to_end(wired):
    app, client, headers, org_id, ctx = wired
    _seed_user(ctx, "member@ex.com")

    user_id = client.post(
        f"/orgs/{org_id}/members",
        json={"email": "member@ex.com", "role": Role.MEMBER.value},
        headers=headers,
    ).json()["user_id"]
    client.patch(
        f"/orgs/{org_id}/members/{user_id}",
        json={"role": Role.ADMIN.value},
        headers=headers,
    )
    client.delete(f"/orgs/{org_id}/members/{user_id}", headers=headers)

    events = _events(client, headers)
    # Newest first: the removal is the most recent thing that happened.
    assert [e["action"] for e in events] == [
        "member.removed",
        "member.role_changed",
        "member.added",
    ]
    added = events[-1]
    assert added["target_type"] == "member"
    assert added["target_id"] == user_id
    assert added["metadata"] == {"email": "member@ex.com", "role": "member"}
    assert added["actor_kind"] == "user"
    # The actor is resolved to a readable label for the page, in one batched lookup.
    assert added["actor_email"] == "owner@ex.com"
    assert added["created_at"]
    # The role change records what it became, so a reader need not diff two rows.
    assert events[1]["metadata"]["role"] == "admin"


def test_team_and_api_key_actions_are_recorded(wired):
    _app, client, headers, org_id, ctx = wired
    _seed_user(ctx, "member@ex.com")
    client.post(
        f"/orgs/{org_id}/members",
        json={"email": "member@ex.com", "role": Role.MEMBER.value},
        headers=headers,
    )

    team_id = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers
    ).json()["team_id"]
    client.post(
        f"/orgs/{org_id}/teams/{team_id}/members",
        json={"email": "member@ex.com"},
        headers=headers,
    )
    key = client.post(
        f"/orgs/{org_id}/api-keys", json={"role": Role.VIEWER.value}, headers=headers
    ).json()
    client.delete(f"/orgs/{org_id}/api-keys/{key['api_key_id']}", headers=headers)
    client.delete(f"/orgs/{org_id}/teams/{team_id}", headers=headers)

    by_action = {e["action"]: e for e in _events(client, headers)}
    assert {
        "team.created",
        "team_member.added",
        "api_key.created",
        "api_key.revoked",
        "team.deleted",
    } <= set(by_action)
    assert by_action["team.created"]["metadata"] == {"name": "Platform"}
    # A deletion records the name it had, which no longer exists to look up.
    assert by_action["team.deleted"]["metadata"] == {"name": "Platform"}
    assert by_action["api_key.created"]["metadata"]["role"] == "viewer"
    # The prefix identifies WHICH key; the secret is not in the trail (asserted below too).
    assert by_action["api_key.created"]["metadata"]["key_prefix"] == key["key_prefix"]


def test_the_api_key_secret_never_reaches_the_audit_trail(wired):
    """The one thing an audit row must never contain."""
    _app, client, headers, org_id, _ctx = wired

    created = client.post(
        f"/orgs/{org_id}/api-keys", json={"role": Role.VIEWER.value}, headers=headers
    ).json()

    body = client.get("/audit-events", headers=headers).text
    assert created["secret"] not in body
    # Nor the hash, nor anything else beyond the recorded fields.
    for event in _events(client, headers):
        assert set(event["metadata"]) <= {"role", "key_prefix"}


def test_integration_connection_changes_are_recorded_without_their_values(wired):
    _app, client, headers, _org_id, _ctx = wired

    connection = client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"default_channel": "#ops"}},
        headers=headers,
    ).json()
    client.patch(
        f"/integrations/connections/{connection['connection_id']}",
        json={"config": {"default_channel": "#platform", "notify": True}},
        headers=headers,
    )
    client.delete(
        f"/integrations/connections/{connection['connection_id']}", headers=headers
    )

    events = _events(client, headers, action="integration_connection.created")
    assert len(events) == 1
    created = events[0]
    assert created["target_id"] == connection["connection_id"]
    assert created["metadata"]["integration"] == "slack"
    # Which settings were configured is auditable; their values are not recorded.
    assert created["metadata"]["settings"] == "default_channel"
    assert "#ops" not in client.get("/audit-events", headers=headers).text

    all_actions = {e["action"] for e in _events(client, headers)}
    assert {
        "integration_connection.created",
        "integration_connection.updated",
        "integration_connection.deleted",
    } <= all_actions


def test_a_failed_action_is_not_recorded(wired):
    """The trail must never claim something happened that did not."""
    _app, client, headers, org_id, _ctx = wired

    # Unknown member -> 404, and nothing to record.
    assert (
        client.delete(f"/orgs/{org_id}/members/{uuid.uuid4()}", headers=headers).status_code
        == 404
    )
    # Refused by the last-owner invariant -> 400, and nothing to record.
    owner_id = client.get(f"/orgs/{org_id}/members", headers=headers).json()[0]["user_id"]
    assert (
        client.delete(f"/orgs/{org_id}/members/{owner_id}", headers=headers).status_code
        == 400
    )

    assert _events(client, headers) == []


def test_an_api_key_actor_is_reported_without_an_email(wired):
    app, client, headers, org_id, _ctx = wired
    key_id = uuid.uuid4()

    def _key_principal() -> Principal:
        return Principal(
            kind=PrincipalKind.API_KEY.value,
            user_id=None,
            key_id=key_id,
            org_id=org_id,
            role=Role.OWNER,
            permissions=frozenset(Permission),
        )

    app.dependency_overrides[get_current_principal] = _key_principal
    try:
        client.post(f"/orgs/{org_id}/teams", json={"name": "Bots"}, headers=headers)
        events = _events(client, headers, action="team.created")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert len(events) == 1
    assert events[0]["actor_kind"] == "api_key"
    assert events[0]["actor_id"] == str(key_id)
    # A key has no display name; the API says so rather than inventing one.
    assert events[0]["actor_email"] is None


# --- reading it: RBAC, tenancy, filters -------------------------------------------


def test_requires_authentication(wired):
    _app, client, _headers, _org, _ctx = wired
    resp = client.get("/audit-events")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("role", [Role.VIEWER, Role.MEMBER])
def test_a_member_cannot_read_the_audit_trail(wired, role: Role):
    """The trail names who removed whom; that is administrative, not general, information."""
    app, client, headers, org_id, ctx = wired
    from tests.enterprise_helpers import issue_principal_headers

    other_headers, _other_org = issue_principal_headers(
        ctx, role=role, org_name=f"Org {role.value}", email=f"{role.value}@ex.com"
    )

    resp = client.get("/audit-events", headers=other_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["required"] == "read_audit_log"


def test_an_admin_can_read_the_audit_trail(wired):
    _app, client, _headers, _org_id, ctx = wired
    from tests.enterprise_helpers import issue_principal_headers

    admin_headers, _admin_org = issue_principal_headers(
        ctx, role=Role.ADMIN, org_name="Admin Org", email="admin@ex.com"
    )

    assert client.get("/audit-events", headers=admin_headers).status_code == 200


def test_another_orgs_trail_is_never_returned(wired):
    """No org parameter exists, and the store filters by the caller's own tenant."""
    _app, client, headers, org_id, ctx = wired
    from tests.enterprise_helpers import issue_principal_headers

    other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    client.post(f"/orgs/{other_org}/teams", json={"name": "Secret"}, headers=other_headers)

    assert _events(client, headers) == []
    assert [e["action"] for e in _events(client, other_headers)] == ["team.created"]
    assert "Secret" not in client.get("/audit-events", headers=headers).text


def test_filters_and_limit(wired):
    _app, client, headers, org_id, _ctx = wired
    for name in ("A", "B", "C"):
        client.post(f"/orgs/{org_id}/teams", json={"name": name}, headers=headers)
    client.post(
        f"/orgs/{org_id}/api-keys", json={"role": Role.VIEWER.value}, headers=headers
    )

    assert len(_events(client, headers)) == 4
    assert len(_events(client, headers, limit=2)) == 2
    assert len(_events(client, headers, action="team.created")) == 3
    # Several actions can be requested at once.
    multi = client.get(
        "/audit-events",
        headers=headers,
        params=[("action", "team.created"), ("action", "api_key.created")],
    )
    assert len(multi.json()) == 4
    # An unknown action is a contract violation, not an empty page.
    assert client.get(
        "/audit-events", headers=headers, params={"action": "not.an.action"}
    ).status_code == 422


def test_limit_is_bounded(wired):
    _app, client, headers, _org_id, _ctx = wired
    assert client.get("/audit-events", headers=headers, params={"limit": 0}).status_code == 422
    assert (
        client.get("/audit-events", headers=headers, params={"limit": 201}).status_code
        == 422
    )


def test_the_time_window_filters(wired):
    _app, client, headers, org_id, _ctx = wired
    client.post(f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers)
    created_at = _events(client, headers)[0]["created_at"]

    assert _events(client, headers, start=created_at, end=created_at)
    assert _events(client, headers, start="2999-01-01T00:00:00Z") == []
    assert _events(client, headers, end="2000-01-01T00:00:00Z") == []


def test_fail_closed_makes_an_unrecordable_action_fail():
    """With ``audit_log_required``, an action that cannot be recorded must not appear to work."""
    from agentforge.enterprise.base import Audit_Log

    class _BrokenLog(Audit_Log):
        def record(self, event):
            raise RuntimeError("audit store is down")

        def list_for_org(self, org_id, **kwargs):
            return []

    settings = _make_settings(audit_log_required=True)
    app = create_app(settings)
    app.state.settings = settings
    headers, org_id, _ctx = install_enterprise_auth(
        app, settings, email="owner@ex.com", audit_log=_BrokenLog()
    )
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers)

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
