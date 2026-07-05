"""Unit tests for the prompts router (Task 13.1).

Drive the real FastAPI app through ``TestClient`` with only keyless in-memory contexts
wired on ``app.state`` (an ``EnterpriseContext`` for auth + an ``ObservabilityContext``
holding an in-memory ``Prompt_Store``). No Postgres, Redis, or external credential is
required.

Covered (Req 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8):

* create-then-get-latest;
* get a specific version;
* the ascending version list;
* render success;
* render with a missing variable -> 400 ``missing_variable``;
* a cross-org get -> 404 ``not_found``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import build_observability_context
from agentforge.config.settings import Settings
from agentforge.enterprise.rbac import Role
from agentforge.main import create_app

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture
def wired():
    """Return ``(client, headers, org_id, ctx)`` for an OWNER principal (ingest + read)."""
    settings = _make_settings()
    app = create_app(settings)
    app.state.observability_context = build_observability_context(settings)
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    client = TestClient(app, raise_server_exceptions=False)
    return client, headers, org_id, ctx


def _create(client, headers, name, body, variables):
    return client.post(
        "/prompts",
        json={"name": name, "body": body, "variables": variables},
        headers=headers,
    )


def test_create_then_get_latest(wired):
    client, headers, _org_id, _ctx = wired
    first = _create(client, headers, "greeting", "Hello v1", [])
    assert first.status_code == 201
    assert first.json()["version"] == 1

    second = _create(client, headers, "greeting", "Hello v2", [])
    assert second.status_code == 201
    assert second.json()["version"] == 2

    latest = client.get("/prompts/greeting", headers=headers)
    assert latest.status_code == 200
    body = latest.json()
    assert body["version"] == 2
    assert body["body"] == "Hello v2"
    assert body["name"] == "greeting"


def test_get_specific_version(wired):
    client, headers, _org_id, _ctx = wired
    _create(client, headers, "summary", "S v1", [])
    _create(client, headers, "summary", "S v2", [])

    resp = client.get("/prompts/summary", params={"version": 1}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["version"] == 1
    assert resp.json()["body"] == "S v1"


def test_ascending_version_list(wired):
    client, headers, _org_id, _ctx = wired
    for _ in range(3):
        _create(client, headers, "qa", "body", [])

    resp = client.get("/prompts/qa/versions", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == [1, 2, 3]


def test_render_success(wired):
    client, headers, _org_id, _ctx = wired
    _create(client, headers, "welcome", "Hello {name}!", ["name"])

    resp = client.post(
        "/prompts/welcome/render",
        json={"variables": {"name": "World"}},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rendered"] == "Hello World!"
    assert body["name"] == "welcome"
    assert body["version"] == 1


def test_render_missing_variable_is_400(wired):
    client, headers, _org_id, _ctx = wired
    _create(client, headers, "welcome", "Hello {name}!", ["name"])

    resp = client.post(
        "/prompts/welcome/render",
        json={"variables": {}},
        headers=headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "missing_variable"
    assert body["error"]["details"]["missing"] == ["name"]


def test_cross_org_get_is_404(wired):
    client, headers, _org_id, ctx = wired
    # Create a prompt under the owner's org.
    _create(client, headers, "secret", "Only for org A", [])

    # A principal in a DIFFERENT org must not see it — a cross-tenant get is a 404.
    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    resp = client.get("/prompts/secret", headers=other_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
