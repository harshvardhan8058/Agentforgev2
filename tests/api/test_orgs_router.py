"""Unit tests for the orgs router — members, teams, API keys (Task 12.1).

These drive the real FastAPI app through ``TestClient`` with only a keyless in-memory
:class:`EnterpriseContext` wired on ``app.state`` (in-memory identity + api-key stores, a
``NoOp`` rate limiter, and a dev-generated ``jwt_secret``). No Postgres, Redis, or
external credential is required.

Covered (Req 2.2, 2.3, 2.4, 2.5, 5.1, 5.4, 5.5, 5.6, 5.7):

* create org, add member, create team;
* cross-org add-member → 404 (never leak existence);
* add team-member for a non-member of the org → 400 ``org_mismatch``;
* api-key create returns the secret exactly once; list returns metadata only (no hash /
  no secret); revoke marks the key revoked; cross-org revoke → 404;
* presenting a revoked ``X-API-Key`` on a protected endpoint → 401.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
    """Return ``(client, ctx, headers, org_id)`` for an OWNER principal in one org."""
    settings = _make_settings()
    app = create_app(settings)
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    client = TestClient(app, raise_server_exceptions=False)
    return client, ctx, headers, org_id


def test_create_org(wired):
    client, _ctx, headers, _org_id = wired
    resp = client.post("/orgs", json={"name": "Fresh Org"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["org_id"]


def test_add_member(wired):
    client, ctx, headers, org_id = wired
    # Seed an existing user with no membership in the owner's org yet.
    ctx.identity_store.create_user(
        "member@ex.com", ctx.auth_service.hash_password("member-password")
    )
    resp = client.post(
        f"/orgs/{org_id}/members",
        json={"email": "member@ex.com", "role": Role.MEMBER.value},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["org_id"] == str(org_id)
    assert body["role"] == Role.MEMBER.value


def test_add_member_unknown_user_is_404(wired):
    client, _ctx, headers, org_id = wired
    resp = client.post(
        f"/orgs/{org_id}/members",
        json={"email": "ghost@ex.com", "role": Role.MEMBER.value},
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_create_team(wired):
    client, _ctx, headers, org_id = wired
    resp = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Platform"


def test_cross_org_add_member_is_404(wired):
    client, ctx, headers, _org_id = wired
    # A second org the caller is NOT a member of.
    _other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other-owner@ex.com"
    )
    ctx.identity_store.create_user(
        "victim@ex.com", ctx.auth_service.hash_password("victim-password")
    )
    resp = client.post(
        f"/orgs/{other_org}/members",
        json={"email": "victim@ex.com", "role": Role.MEMBER.value},
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_add_team_member_for_non_member_is_400_org_mismatch(wired):
    client, ctx, headers, org_id = wired
    team_id = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Secret"}, headers=headers
    ).json()["team_id"]
    # A user who holds no membership in the org cannot be added to its team.
    ctx.identity_store.create_user(
        "outsider@ex.com", ctx.auth_service.hash_password("outsider-password")
    )
    resp = client.post(
        f"/orgs/{org_id}/teams/{team_id}/members",
        json={"email": "outsider@ex.com"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "org_mismatch"


def test_api_key_create_returns_secret_once_and_list_is_metadata_only(wired):
    client, _ctx, headers, org_id = wired
    created = client.post(
        f"/orgs/{org_id}/api-keys",
        json={"role": Role.MEMBER.value},
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["secret"].startswith("af_")
    assert body["api_key_id"]
    assert body["key_prefix"] == body["secret"][:8]

    listing = client.get(f"/orgs/{org_id}/api-keys", headers=headers)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    item = items[0]
    # Metadata only — never the hash or the plaintext secret (Req 5.4).
    assert "key_hash" not in item
    assert "secret" not in item
    assert set(item) == {
        "id",
        "org_id",
        "role",
        "key_prefix",
        "revoked_at",
        "created_at",
    }


def test_revoke_marks_key_revoked(wired):
    client, _ctx, headers, org_id = wired
    key_id = client.post(
        f"/orgs/{org_id}/api-keys", json={"role": Role.MEMBER.value}, headers=headers
    ).json()["api_key_id"]

    revoked = client.delete(f"/orgs/{org_id}/api-keys/{key_id}", headers=headers)
    assert revoked.status_code == 204

    item = client.get(f"/orgs/{org_id}/api-keys", headers=headers).json()[0]
    assert item["revoked_at"] is not None


def test_revoke_cross_org_is_404(wired):
    client, ctx, headers, _org_id = wired
    _other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Cross Org", email="cross-owner@ex.com"
    )
    # A key that lives in the OTHER org.
    key, _secret = ctx.api_key_service.create(other_org, Role.MEMBER)
    resp = client.delete(f"/orgs/{other_org}/api-keys/{key.id}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_revoke_unknown_key_is_404(wired):
    client, _ctx, headers, org_id = wired
    import uuid

    resp = client.delete(f"/orgs/{org_id}/api-keys/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_revoked_api_key_presented_is_401(wired):
    client, _ctx, headers, org_id = wired
    # An ADMIN-scoped key can itself call the manage_api_keys endpoints while active.
    created = client.post(
        f"/orgs/{org_id}/api-keys", json={"role": Role.ADMIN.value}, headers=headers
    ).json()
    secret = created["secret"]
    key_id = created["api_key_id"]

    active = client.get(f"/orgs/{org_id}/api-keys", headers={"X-API-Key": secret})
    assert active.status_code == 200

    client.delete(f"/orgs/{org_id}/api-keys/{key_id}", headers=headers)
    revoked = client.get(f"/orgs/{org_id}/api-keys", headers={"X-API-Key": secret})
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "unauthorized"
