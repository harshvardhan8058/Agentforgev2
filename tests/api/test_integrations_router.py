"""Unit tests for the integrations status router auth surface + shape (Task 6.3).

Drive the real FastAPI app through ``TestClient`` with only a keyless in-memory
``EnterpriseContext`` wired on ``app.state`` for auth. No Postgres, Redis, or external
credential is required; the Integration_Status_Service is stateless and built from the
active Settings by the dependency.

Covered (Req 9.2, 9.3, 9.4, 9.5):

* no credential -> 401 ``unauthorized``;
* authenticated but lacking ``read`` -> 403 ``forbidden``;
* a ``read`` principal receives one ``{name, enabled}`` entry per integration reflecting
  the current config;
* no credential/secret-derived field appears anywhere in the response.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentforge.api.deps import get_current_principal
from agentforge.config.settings import Settings
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Role
from agentforge.integrations import INTEGRATION_NAMES
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
    """Return ``(app, client, headers, org_id)`` for a READ-capable owner (keyless)."""
    settings = _make_settings()
    app = create_app(settings)
    app.state.settings = settings
    headers, org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, raise_server_exceptions=False)
    return app, client, headers, org_id


def test_no_credential_is_401(wired):
    _app, client, _headers, _org_id = wired
    resp = client.get("/integrations/status")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_authenticated_without_read_is_403(wired):
    app, client, headers, org_id = wired

    def _no_read_principal() -> Principal:
        return Principal(
            kind=PrincipalKind.USER.value,
            user_id=uuid4(),
            key_id=None,
            org_id=org_id,
            role=Role.VIEWER,
            permissions=frozenset(),
        )

    app.dependency_overrides[get_current_principal] = _no_read_principal
    try:
        resp = client.get("/integrations/status", headers=headers)
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    assert resp.json()["error"]["details"]["required"] == "read"


def test_read_principal_gets_one_entry_per_integration_keyless(wired):
    _app, client, headers, _org_id = wired
    resp = client.get("/integrations/status", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    entries = body["integrations"]
    # One entry per integration, in the canonical order, all Disabled on the keyless path.
    assert [e["name"] for e in entries] == list(INTEGRATION_NAMES)
    assert all(e["enabled"] is False for e in entries)
    # Each entry has exactly {name, enabled} — no credential/secret-derived field.
    for entry in entries:
        assert set(entry.keys()) == {"name", "enabled"}


def test_status_reflects_enabled_config_and_never_leaks_secret():
    # Enable Slack + GitHub with a credential + toggle; leave Gmail/Drive Disabled.
    secret = "xoxb-super-secret-token-value"
    settings = _make_settings(
        slack_bot_token=SecretStr(secret),
        slack_enabled=True,
        github_token=SecretStr("ghp-another-secret"),
        github_enabled=True,
    )
    app = create_app(settings)
    app.state.settings = settings
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/integrations/status", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    enabled = {e["name"]: e["enabled"] for e in body["integrations"]}
    assert enabled == {
        "slack": True,
        "gmail": False,
        "google_drive": False,
        "github": True,
    }
    # The credential value never appears anywhere in the serialized response (Req 9.2).
    assert secret not in resp.text
    assert "ghp-another-secret" not in resp.text



# --- /integrations/connections (per-org, non-secret connection config) -------------
#
# The Integration_Connection store, its Postgres implementation and migration 0011 all
# shipped in Phase 8 with no HTTP surface at all, so per-org connection config was
# unreachable. These tests cover the surface that closes that: RBAC (read to look,
# manage_integrations to change), tenancy (another org's connection is 404, never 403),
# and the admission policy that keeps credentials out of a free-form JSON column.

from agentforge.enterprise.rbac import Permission, ROLE_PERMISSIONS  # noqa: E402


def _principal_with(org_id, *permissions: Permission) -> Principal:
    """A principal holding exactly ``permissions`` (used to isolate one RBAC edge)."""
    return Principal(
        kind=PrincipalKind.USER.value,
        user_id=uuid4(),
        key_id=None,
        org_id=org_id,
        role=Role.VIEWER,
        permissions=frozenset(permissions),
    )


def test_manage_integrations_is_granted_from_admin_upwards():
    """The permission is administrative, and the map must still nest (Property 4)."""
    assert Permission.MANAGE_INTEGRATIONS not in ROLE_PERMISSIONS[Role.VIEWER]
    assert Permission.MANAGE_INTEGRATIONS not in ROLE_PERMISSIONS[Role.MEMBER]
    assert Permission.MANAGE_INTEGRATIONS in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.MANAGE_INTEGRATIONS in ROLE_PERMISSIONS[Role.OWNER]


def test_connection_crud_round_trip(wired):
    _app, client, headers, _org_id = wired

    assert client.get("/integrations/connections", headers=headers).json() == []

    created = client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"default_channel": "#ops"}},
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["integration"] == "slack"
    assert body["config"] == {"default_channel": "#ops"}
    assert set(body) == {"connection_id", "integration", "config", "created_at"}
    connection_id = body["connection_id"]

    listed = client.get("/integrations/connections", headers=headers)
    assert [c["connection_id"] for c in listed.json()] == [connection_id]

    fetched = client.get(f"/integrations/connections/{connection_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["config"] == {"default_channel": "#ops"}

    # PATCH replaces rather than merges, so a setting can be removed.
    patched = client.patch(
        f"/integrations/connections/{connection_id}",
        json={"config": {"notify": False}},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["config"] == {"notify": False}
    assert patched.json()["created_at"] == body["created_at"]

    deleted = client.delete(f"/integrations/connections/{connection_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/integrations/connections", headers=headers).json() == []
    # A second delete is a 404, not a silent success.
    assert (
        client.delete(
            f"/integrations/connections/{connection_id}", headers=headers
        ).status_code
        == 404
    )


def test_writing_config_does_not_enable_the_integration(wired):
    """Enablement stays a pure function of Settings (Req 11.5), never of stored config."""
    _app, client, headers, _org_id = wired
    client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"default_channel": "#ops"}},
        headers=headers,
    )

    statuses = client.get("/integrations/status", headers=headers).json()["integrations"]

    assert {entry["name"] for entry in statuses} == set(INTEGRATION_NAMES)
    assert all(entry["enabled"] is False for entry in statuses)


def test_unknown_integration_is_400(wired):
    _app, client, headers, _org_id = wired
    resp = client.post(
        "/integrations/connections",
        json={"integration": "not-an-integration", "config": {}},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_integration"
    assert resp.json()["error"]["details"]["known"] == list(INTEGRATION_NAMES)


def test_credential_shaped_config_is_refused_and_never_stored(wired):
    """The whole point of the surface: a token pasted into config must not persist."""
    _app, client, headers, _org_id = wired
    secret = "xoxb-1111-2222-do-not-store"

    by_key = client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"bot_token": "placeholder"}},
        headers=headers,
    )
    by_value = client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"default_channel": secret}},
        headers=headers,
    )
    for resp in (by_key, by_value):
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_config"
        assert resp.json()["error"]["details"]["field"] == "config"
    # The refusal must not echo the credential back to the caller.
    assert secret not in by_value.text

    # A nested object never reaches the policy: the contract declares config values as
    # JSON scalars, so the transport layer rejects it first with the uniform 422. Either
    # way the one thing that matters holds - it is not stored.
    nested = client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"auth": {"token": "x"}}},
        headers=headers,
    )
    assert nested.status_code == 422
    assert nested.json()["error"]["code"] == "validation_error"

    # Nothing was persisted by any of the three attempts.
    assert client.get("/integrations/connections", headers=headers).json() == []


def test_patch_applies_the_same_admission_policy(wired):
    _app, client, headers, _org_id = wired
    connection_id = client.post(
        "/integrations/connections",
        json={"integration": "github", "config": {"repo": "acme/platform"}},
        headers=headers,
    ).json()["connection_id"]

    resp = client.patch(
        f"/integrations/connections/{connection_id}",
        json={"config": {"api_key": "placeholder"}},
        headers=headers,
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_config"
    # The stored config is untouched.
    assert client.get(
        f"/integrations/connections/{connection_id}", headers=headers
    ).json()["config"] == {"repo": "acme/platform"}


def test_unknown_connection_is_404(wired):
    _app, client, headers, _org_id = wired
    ghost = uuid4()

    for resp in (
        client.get(f"/integrations/connections/{ghost}", headers=headers),
        client.patch(
            f"/integrations/connections/{ghost}", json={"config": {}}, headers=headers
        ),
        client.delete(f"/integrations/connections/{ghost}", headers=headers),
    ):
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"


def test_another_orgs_connection_is_404_for_read_and_write(wired):
    """Cross-tenant access resolves to not_found — never 403, never the other org's data."""
    app, client, headers, org_id = wired
    created_id = client.post(
        "/integrations/connections",
        json={"integration": "slack", "config": {"default_channel": "#private"}},
        headers=headers,
    ).json()["connection_id"]

    other_org = uuid4()

    def _other_org_principal() -> Principal:
        return _principal_with(
            other_org, Permission.READ, Permission.MANAGE_INTEGRATIONS
        )

    app.dependency_overrides[get_current_principal] = _other_org_principal
    try:
        listed = client.get("/integrations/connections", headers=headers)
        fetched = client.get(f"/integrations/connections/{created_id}", headers=headers)
        patched = client.patch(
            f"/integrations/connections/{created_id}",
            json={"config": {"default_channel": "#hijacked"}},
            headers=headers,
        )
        deleted = client.delete(
            f"/integrations/connections/{created_id}", headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert listed.json() == []
    assert [fetched.status_code, patched.status_code, deleted.status_code] == [404] * 3
    assert "#private" not in fetched.text
    # The owner's record is untouched.
    assert client.get(
        f"/integrations/connections/{created_id}", headers=headers
    ).json()["config"] == {"default_channel": "#private"}


def test_mutations_require_manage_integrations_but_reads_need_only_read(wired):
    app, client, headers, org_id = wired

    def _read_only_principal() -> Principal:
        return _principal_with(org_id, Permission.READ)

    app.dependency_overrides[get_current_principal] = _read_only_principal
    try:
        listed = client.get("/integrations/connections", headers=headers)
        created = client.post(
            "/integrations/connections",
            json={"integration": "slack", "config": {}},
            headers=headers,
        )
        patched = client.patch(
            f"/integrations/connections/{uuid4()}",
            json={"config": {}},
            headers=headers,
        )
        deleted = client.delete(
            f"/integrations/connections/{uuid4()}", headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert listed.status_code == 200
    for resp in (created, patched, deleted):
        assert resp.status_code == 403
        assert resp.json()["error"]["details"]["required"] == "manage_integrations"


def test_connection_endpoints_require_authentication(wired):
    _app, client, _headers, _org_id = wired
    assert client.get("/integrations/connections").status_code == 401
    assert (
        client.post(
            "/integrations/connections", json={"integration": "slack", "config": {}}
        ).status_code
        == 401
    )
