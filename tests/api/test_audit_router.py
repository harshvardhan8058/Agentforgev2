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


@pytest.mark.parametrize("role", [Role.VIEWER, Role.MEMBER, Role.ADMIN])
def test_only_an_owner_can_read_the_audit_trail(wired, role: Role):
    """Owner-only, deliberately matching the roster the trail exposes.

    The trail's member events carry emails and role assignments, and
    ``GET /orgs/{id}/members`` is gated on ``manage_members`` — owner-only. Granting trail
    access to an admin would hand over, through a side door, exactly the roster the direct
    endpoint withholds.
    """
    app, client, headers, org_id, ctx = wired
    from tests.enterprise_helpers import issue_principal_headers

    other_headers, _other_org = issue_principal_headers(
        ctx, role=role, org_name=f"Org {role.value}", email=f"{role.value}@ex.com"
    )

    resp = client.get("/audit-events", headers=other_headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["required"] == "read_audit_log"


def test_an_owner_can_read_the_audit_trail(wired):
    _app, client, _headers, _org_id, ctx = wired
    from tests.enterprise_helpers import issue_principal_headers

    owner_headers, _owner_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Second Org", email="second@ex.com"
    )

    assert client.get("/audit-events", headers=owner_headers).status_code == 200


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


def test_fail_closed_reports_an_applied_but_unrecorded_change():
    """``audit_log_required`` refuses to acknowledge a change it could not record.

    It is not a rollback, and the response says so: the audited mutation is applied by a
    different store in a different transaction and nothing spans the two. A generic 500 would
    invite a retry that duplicates the change, so the envelope carries its own code and
    ``applied: true``.
    """
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

    assert resp.status_code == 503
    body = resp.json()["error"]
    assert body["code"] == "audit_unavailable"
    assert body["details"] == {"action": "team.created", "applied": True}
    assert "Do not retry" in body["message"]
    # The action WAS applied — the honest fact the response reports rather than hides.
    teams = client.get(f"/orgs/{org_id}/teams", headers=headers)
    assert [t["name"] for t in teams.json()] == ["Platform"]


# --- keyset pagination ------------------------------------------------------------


def test_the_cursor_walks_the_whole_trail_without_repeats(wired):
    """Events written in one burst share timestamps, which is exactly where offsets fail."""
    _app, client, headers, org_id, _ctx = wired
    for index in range(7):
        client.post(f"/orgs/{org_id}/teams", json={"name": f"T{index}"}, headers=headers)

    walked: list[dict] = []
    params: dict[str, object] = {"limit": 3}
    while True:
        page = _events(client, headers, **params)
        if not page:
            break
        walked.extend(page)
        params = {"limit": 3, "before": page[-1]["created_at"], "before_id": page[-1]["id"]}

    ids = [event["id"] for event in walked]
    assert len(ids) == 7
    assert len(set(ids)) == 7
    # Same order as one big page would have produced.
    assert ids == [event["id"] for event in _events(client, headers, limit=50)]


def test_a_half_supplied_cursor_is_refused(wired):
    _app, client, headers, _org_id, _ctx = wired

    resp = client.get(
        "/audit-events", headers=headers, params={"before": "2026-08-01T00:00:00Z"}
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["details"]["field"] == "before_id"


def test_the_actor_filter_accepts_the_actor_id_it_reported(wired):
    """A filter that silently returned nothing for a key actor would be a trap."""
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
        reported = _events(client, headers, action="team.created")[0]
        filtered = _events(client, headers, actor_id=reported["actor_id"])
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert [e["id"] for e in filtered] == [reported["id"]]


def test_creating_an_org_is_recorded_in_both_the_new_and_the_acting_trail(wired):
    """An org created with org A's credential is a fact org A's owners must be able to see."""
    _app, client, headers, _org_id, _ctx = wired

    created = client.post("/orgs", json={"name": "Subsidiary"}, headers=headers)
    assert created.status_code == 201

    # The acting org's trail records it, even though the new org is a different tenant.
    acting = _events(client, headers, action="org.created")
    assert len(acting) == 1
    assert acting[0]["target_id"] == created.json()["org_id"]
    assert acting[0]["metadata"] == {"name": "Subsidiary"}


def test_a_long_value_is_truncated_rather_than_failing_the_action(wired):
    """An over-long value must not turn a successful mutation into a 500 with no audit row.

    Reachable through the documented surface: an address may be up to 320 characters (RFC
    5321), which is longer than an audit metadata value. Before this, admission raised
    *outside* the failure-posture guard, so the membership was created and the caller got a
    500 with nothing in the trail — the exact combination the trail exists to prevent.
    """
    _app, client, headers, org_id, ctx = wired
    long_email = "l" * 300 + "@ex.com"  # within the schema bound, beyond the audit bound
    _seed_user(ctx, long_email)

    resp = client.post(
        f"/orgs/{org_id}/members",
        json={"email": long_email, "role": Role.MEMBER.value},
        headers=headers,
    )

    assert resp.status_code == 201
    events = _events(client, headers, action="member.added")
    assert len(events) == 1
    recorded = events[0]["metadata"]["email"]
    # Visibly truncated, so a reader can tell the value was longer than the row records.
    assert recorded.endswith("\u2026")
    assert long_email.startswith(recorded[:-1])
