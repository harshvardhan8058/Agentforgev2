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

import uuid

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



# --- administrative member/team surface (v1.1 admin CRUD) -------------------------
#
# Covers the read/update/remove endpoints added on top of the Phase 5 create/add-only
# surface: GET/PATCH/DELETE members, GET/DELETE teams, and GET/DELETE team members.
# Every assertion below is about one of three contracts: the response shape, RBAC
# (``manage_members``), or tenancy (another tenant's resource is 404, never 403).


def _seed_member(ctx, client, headers, org_id, email: str, role: Role = Role.MEMBER):
    """Create a user and add them to ``org_id`` through the API; return their user_id."""
    ctx.identity_store.create_user(email, ctx.auth_service.hash_password("pw-" + email))
    resp = client.post(
        f"/orgs/{org_id}/members",
        json={"email": email, "role": role.value},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["user_id"]


def test_list_members_returns_roster_with_emails_oldest_first(wired):
    client, ctx, headers, org_id = wired
    member_id = _seed_member(ctx, client, headers, org_id, "member@ex.com")

    resp = client.get(f"/orgs/{org_id}/members", headers=headers)

    assert resp.status_code == 200
    rows = resp.json()
    assert [r["email"] for r in rows] == ["owner@ex.com", "member@ex.com"]
    assert [r["role"] for r in rows] == [Role.OWNER.value, Role.MEMBER.value]
    assert rows[1]["user_id"] == member_id
    assert set(rows[0]) == {"user_id", "email", "role", "created_at"}


def test_update_member_role(wired):
    client, ctx, headers, org_id = wired
    member_id = _seed_member(ctx, client, headers, org_id, "member@ex.com")

    resp = client.patch(
        f"/orgs/{org_id}/members/{member_id}",
        json={"role": Role.ADMIN.value},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json()["role"] == Role.ADMIN.value
    assert resp.json()["email"] == "member@ex.com"
    roles = {
        r["user_id"]: r["role"]
        for r in client.get(f"/orgs/{org_id}/members", headers=headers).json()
    }
    assert roles[member_id] == Role.ADMIN.value


def test_demoting_the_last_owner_is_400_last_owner(wired):
    client, _ctx, headers, org_id = wired
    owner_id = client.get(f"/orgs/{org_id}/members", headers=headers).json()[0]["user_id"]

    resp = client.patch(
        f"/orgs/{org_id}/members/{owner_id}",
        json={"role": Role.ADMIN.value},
        headers=headers,
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "last_owner"


def test_removing_the_last_owner_is_400_last_owner(wired):
    client, _ctx, headers, org_id = wired
    owner_id = client.get(f"/orgs/{org_id}/members", headers=headers).json()[0]["user_id"]

    resp = client.delete(f"/orgs/{org_id}/members/{owner_id}", headers=headers)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "last_owner"


def test_remove_member_also_drops_their_team_membership(wired):
    client, ctx, headers, org_id = wired
    member_id = _seed_member(ctx, client, headers, org_id, "member@ex.com")
    team_id = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers
    ).json()["team_id"]
    assert (
        client.post(
            f"/orgs/{org_id}/teams/{team_id}/members",
            json={"email": "member@ex.com"},
            headers=headers,
        ).status_code
        == 201
    )

    resp = client.delete(f"/orgs/{org_id}/members/{member_id}", headers=headers)

    assert resp.status_code == 204
    remaining = client.get(f"/orgs/{org_id}/members", headers=headers).json()
    assert member_id not in {r["user_id"] for r in remaining}
    assert client.get(
        f"/orgs/{org_id}/teams/{team_id}/members", headers=headers
    ).json() == []


def test_update_and_remove_unknown_member_are_404(wired):
    client, _ctx, headers, org_id = wired
    ghost = uuid.uuid4()

    patched = client.patch(
        f"/orgs/{org_id}/members/{ghost}",
        json={"role": Role.MEMBER.value},
        headers=headers,
    )
    deleted = client.delete(f"/orgs/{org_id}/members/{ghost}", headers=headers)

    assert patched.status_code == 404
    assert deleted.status_code == 404
    assert patched.json()["error"]["code"] == "not_found"


def test_cross_org_member_administration_is_404(wired):
    """Another tenant's roster is not readable and its members are not mutable."""
    client, ctx, headers, _org_id = wired
    other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    victim_id = client.get(f"/orgs/{other_org}/members", headers=other_headers).json()[0][
        "user_id"
    ]

    listing = client.get(f"/orgs/{other_org}/members", headers=headers)
    patched = client.patch(
        f"/orgs/{other_org}/members/{victim_id}",
        json={"role": Role.VIEWER.value},
        headers=headers,
    )
    deleted = client.delete(f"/orgs/{other_org}/members/{victim_id}", headers=headers)

    assert [listing.status_code, patched.status_code, deleted.status_code] == [404] * 3
    # The other tenant is untouched.
    assert (
        client.get(f"/orgs/{other_org}/members", headers=other_headers).json()[0]["role"]
        == Role.OWNER.value
    )


def test_member_administration_requires_manage_members(wired):
    """An ADMIN role lacks ``manage_members``, so every route here is 403 (Req 3.x)."""
    client, ctx, _headers, _org_id = wired
    admin_headers, admin_org = issue_principal_headers(
        ctx, role=Role.ADMIN, org_name="Admin Org", email="admin@ex.com"
    )

    responses = [
        client.get(f"/orgs/{admin_org}/members", headers=admin_headers),
        client.patch(
            f"/orgs/{admin_org}/members/{uuid.uuid4()}",
            json={"role": Role.VIEWER.value},
            headers=admin_headers,
        ),
        client.delete(f"/orgs/{admin_org}/members/{uuid.uuid4()}", headers=admin_headers),
        client.get(f"/orgs/{admin_org}/teams", headers=admin_headers),
        client.delete(f"/orgs/{admin_org}/teams/{uuid.uuid4()}", headers=admin_headers),
        client.get(
            f"/orgs/{admin_org}/teams/{uuid.uuid4()}/members", headers=admin_headers
        ),
        client.delete(
            f"/orgs/{admin_org}/teams/{uuid.uuid4()}/members/{uuid.uuid4()}",
            headers=admin_headers,
        ),
    ]

    assert [r.status_code for r in responses] == [403] * 7
    assert {r.json()["error"]["code"] for r in responses} == {"forbidden"}


def test_list_and_delete_teams(wired):
    client, _ctx, headers, org_id = wired
    team_id = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers
    ).json()["team_id"]

    listing = client.get(f"/orgs/{org_id}/teams", headers=headers)
    assert listing.status_code == 200
    assert [t["name"] for t in listing.json()] == ["Platform"]
    assert set(listing.json()[0]) == {"team_id", "name", "created_at"}

    deleted = client.delete(f"/orgs/{org_id}/teams/{team_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/orgs/{org_id}/teams", headers=headers).json() == []


def test_delete_unknown_team_is_404(wired):
    client, _ctx, headers, org_id = wired
    resp = client.delete(f"/orgs/{org_id}/teams/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_team_member_listing_and_removal(wired):
    client, ctx, headers, org_id = wired
    member_id = _seed_member(ctx, client, headers, org_id, "member@ex.com")
    team_id = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers
    ).json()["team_id"]
    client.post(
        f"/orgs/{org_id}/teams/{team_id}/members",
        json={"email": "member@ex.com"},
        headers=headers,
    )

    listing = client.get(f"/orgs/{org_id}/teams/{team_id}/members", headers=headers)
    assert listing.status_code == 200
    assert [m["email"] for m in listing.json()] == ["member@ex.com"]
    assert set(listing.json()[0]) == {"user_id", "email", "created_at"}

    removed = client.delete(
        f"/orgs/{org_id}/teams/{team_id}/members/{member_id}", headers=headers
    )
    assert removed.status_code == 204
    assert client.get(
        f"/orgs/{org_id}/teams/{team_id}/members", headers=headers
    ).json() == []
    # The member keeps their organization membership.
    assert member_id in {
        r["user_id"] for r in client.get(f"/orgs/{org_id}/members", headers=headers).json()
    }


def test_removing_a_non_team_member_is_404(wired):
    client, ctx, headers, org_id = wired
    member_id = _seed_member(ctx, client, headers, org_id, "member@ex.com")
    team_id = client.post(
        f"/orgs/{org_id}/teams", json={"name": "Platform"}, headers=headers
    ).json()["team_id"]

    resp = client.delete(
        f"/orgs/{org_id}/teams/{team_id}/members/{member_id}", headers=headers
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["details"] == {"user_id": member_id}


def test_cross_org_team_routes_are_404(wired):
    """A Team owned by another tenant is absent for reads AND for writes (Req 4.3, 5.7)."""
    client, ctx, headers, org_id = wired
    other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    foreign_team = client.post(
        f"/orgs/{other_org}/teams", json={"name": "Secret"}, headers=other_headers
    ).json()["team_id"]

    # The caller's own org is the path prefix, so `_ensure_same_org` passes and the
    # ONLY thing standing between the caller and a foreign team is the org-scoped
    # lookup inside each handler.
    responses = [
        client.get(f"/orgs/{org_id}/teams/{foreign_team}/members", headers=headers),
        client.delete(f"/orgs/{org_id}/teams/{foreign_team}", headers=headers),
        client.post(
            f"/orgs/{org_id}/teams/{foreign_team}/members",
            json={"email": "owner@ex.com"},
            headers=headers,
        ),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    # The foreign team still exists, unmodified, for its own tenant.
    assert [t["team_id"] for t in client.get(
        f"/orgs/{other_org}/teams", headers=other_headers
    ).json()] == [foreign_team]


def test_adding_a_dual_member_to_a_foreign_team_is_404(wired):
    """The store's cross-org guard alone would ACCEPT this; the org-scoped lookup rejects it.

    A user holding memberships in both organizations satisfies "is a member of the team's
    org", so before the team was resolved within the caller's own org this request would
    have written a Team_Membership into another tenant's team.
    """
    client, ctx, headers, org_id = wired
    other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    foreign_team = client.post(
        f"/orgs/{other_org}/teams", json={"name": "Secret"}, headers=other_headers
    ).json()["team_id"]

    ctx.identity_store.create_user(
        "dual@ex.com", ctx.auth_service.hash_password("dual-password")
    )
    client.post(
        f"/orgs/{org_id}/members",
        json={"email": "dual@ex.com", "role": Role.MEMBER.value},
        headers=headers,
    )
    client.post(
        f"/orgs/{other_org}/members",
        json={"email": "dual@ex.com", "role": Role.MEMBER.value},
        headers=other_headers,
    )

    resp = client.post(
        f"/orgs/{org_id}/teams/{foreign_team}/members",
        json={"email": "dual@ex.com"},
        headers=headers,
    )

    assert resp.status_code == 404
    assert ctx.identity_store.list_team_members(other_org, uuid.UUID(foreign_team)) == []
