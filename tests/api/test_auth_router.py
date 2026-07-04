"""Unit tests for the auth router — register-self, login, refresh (Task 11.1).

These drive the real FastAPI app through ``TestClient`` with only a keyless in-memory
:class:`EnterpriseContext` wired on ``app.state`` (in-memory identity + api-key stores, a
``NoOp`` rate limiter, and a dev-generated ``jwt_secret``). No Postgres, Redis, or
external credential is required, so the module runs in the fast lane.

Covered branches (Req 1.1, 1.2, 1.3, 1.5):

* weak-password → 400 ``validation_error`` naming ``password``;
* duplicate-email → 400 ``validation_error`` naming ``email``;
* unknown-email / wrong-password login → 401 ``auth_failed``;
* register → login round trip yielding a token that resolves via ``get_current_principal``;
* refresh returns a new valid token from a still-valid bearer token.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import build_enterprise_context
from agentforge.config.settings import Settings
from agentforge.main import create_app


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture
def client() -> TestClient:
    """A TestClient with a clean keyless enterprise context (no pre-registered user)."""
    settings = _make_settings()
    app = create_app(settings)
    app.state.enterprise_context = build_enterprise_context(settings, redis=None)
    return TestClient(app, raise_server_exceptions=False)


def _register(client: TestClient, *, email: str, password: str, org_name: str = "Acme"):
    return client.post(
        "/auth/register-self",
        json={"email": email, "password": password, "org_name": org_name},
    )


def test_register_self_returns_bearer_token(client: TestClient):
    resp = _register(client, email="owner@ex.com", password="correct horse battery")
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_weak_password_is_rejected_400(client: TestClient):
    resp = _register(client, email="weak@ex.com", password="short")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["field"] == "password"


def test_duplicate_email_is_rejected_400(client: TestClient):
    assert _register(client, email="dup@ex.com", password="a-strong-password").status_code == 201
    resp = _register(client, email="dup@ex.com", password="another-strong-pass")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["field"] == "email"


def test_login_unknown_email_is_401(client: TestClient):
    resp = client.post(
        "/auth/login", json={"email": "nobody@ex.com", "password": "whatever-pass"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_failed"


def test_login_wrong_password_is_401(client: TestClient):
    _register(client, email="real@ex.com", password="the-right-password")
    resp = client.post(
        "/auth/login", json={"email": "real@ex.com", "password": "the-wrong-password"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_failed"


def test_register_then_login_token_resolves_via_get_current_principal(client: TestClient):
    """A registered user can log in and use the token against a protected endpoint."""
    _register(client, email="rt@ex.com", password="round-trip-password")
    login = client.post(
        "/auth/login", json={"email": "rt@ex.com", "password": "round-trip-password"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    # POST /orgs requires only an authenticated principal, so a 201 confirms the token
    # resolved through get_current_principal.
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/orgs", json={"name": "Second Org"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["org_id"]


def test_refresh_returns_a_new_valid_token(client: TestClient):
    token = _register(client, email="rf@ex.com", password="refresh-me-please").json()[
        "access_token"
    ]
    resp = client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]
    assert new_token
    # The refreshed token itself authenticates a protected request.
    ok = client.post(
        "/orgs", json={"name": "Refreshed Org"},
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert ok.status_code == 201


def test_refresh_without_token_is_401(client: TestClient):
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_refresh_with_garbage_token_is_401(client: TestClient):
    resp = client.post(
        "/auth/refresh", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
