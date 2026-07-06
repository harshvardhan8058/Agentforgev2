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
