"""Integration test: migration 0006 + Pg_Identity_Store round-trip (Task 4.6).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the store converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.api.errors import AppError
from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.enterprise.rbac import Role

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge",
    )


@pytest.fixture
async def engine():
    eng = create_engine(_dsn())
    await run_migrations(eng, EMBEDDING_DIMENSION)
    yield eng
    await eng.dispose()


async def test_migration_0006_applied(engine):
    """The 0006 migration reaches schema_migrations and creates its tables."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0006_create_enterprise_identity"},
        )
        assert applied.scalar_one_or_none() == "0006_create_enterprise_identity"

        for table in (
            "organizations",
            "users",
            "memberships",
            "teams",
            "team_memberships",
            "api_keys",
        ):
            exists = await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})
            assert exists.scalar_one() is not None


async def test_pg_identity_round_trip(engine):
    """create_organization -> create_user -> add_membership -> create_team -> add_team_member."""
    store = Pg_Identity_Store(_dsn())

    org = store.create_organization("Acme")
    email = f"user-{uuid.uuid4().hex}@example.com"
    user = store.create_user(email, "argon2-hash")
    membership = store.add_membership(user.id, org.id, Role.OWNER)
    team = store.create_team(org.id, f"eng-{uuid.uuid4().hex}")
    tm = store.add_team_member(team.id, user.id)

    assert store.get_organization(org.id).id == org.id
    assert store.get_user_by_email(email).id == user.id
    assert store.get_membership(user.id, org.id).role == Role.OWNER
    assert membership.org_id == org.id
    assert tm.team_id == team.id

    memberships = store.list_memberships_for_user(user.id)
    assert any(m.org_id == org.id for m in memberships)

    # Cleanup: deleting the org cascades to memberships/teams/team_memberships.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org.id)}
        )
        await conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user.id)})



async def test_pg_admin_crud_parity(engine):
    """The administrative surface behaves identically to InMemory_Identity_Store.

    Exercises the v1.1 read/update/remove methods against real SQL: batched user lookup,
    role reassignment, the last-owner refusal (evaluated over a ``SELECT ... FOR UPDATE``
    roster inside the writing transaction), member removal cascading to that org's team
    memberships only, and the org-scoped team reads/writes.
    """
    store = Pg_Identity_Store(_dsn())

    org = store.create_organization("Acme")
    other_org = store.create_organization("Beta")
    owner = store.create_user(f"owner-{uuid.uuid4().hex}@example.com", "hash")
    member = store.create_user(f"member-{uuid.uuid4().hex}@example.com", "hash")
    store.add_membership(owner.id, org.id, Role.OWNER)
    store.add_membership(member.id, org.id, Role.MEMBER)
    # The same user also belongs to the other tenant, so "removed from org" must not
    # mean "removed everywhere".
    store.add_membership(member.id, other_org.id, Role.OWNER)

    team = store.create_team(org.id, f"eng-{uuid.uuid4().hex}")
    other_team = store.create_team(other_org.id, f"eng-{uuid.uuid4().hex}")
    store.add_team_member(team.id, member.id)
    store.add_team_member(other_team.id, member.id)

    # --- batched user lookup: deduplicated, unknown ids skipped ---
    found = store.list_users_by_ids([owner.id, member.id, owner.id, uuid.uuid4()])
    assert {u.id for u in found} == {owner.id, member.id}
    assert store.list_users_by_ids([]) == []

    # --- rosters are ordered oldest-first ---
    assert [m.user_id for m in store.list_org_members(org.id)] == [owner.id, member.id]

    # --- role reassignment ---
    updated = store.update_membership_role(member.id, org.id, Role.ADMIN)
    assert updated is not None and updated.role is Role.ADMIN
    assert store.get_membership(member.id, org.id).role is Role.ADMIN
    # Unknown / cross-tenant membership is None, never an error.
    assert store.update_membership_role(uuid.uuid4(), org.id, Role.ADMIN) is None
    assert store.update_membership_role(owner.id, other_org.id, Role.ADMIN) is None

    # --- last-owner invariant, enforced in SQL ---
    with pytest.raises(AppError) as excinfo:
        store.update_membership_role(owner.id, org.id, Role.ADMIN)
    assert excinfo.value.code == "last_owner"
    with pytest.raises(AppError):
        store.remove_membership(owner.id, org.id)
    assert store.get_membership(owner.id, org.id).role is Role.OWNER

    # --- org-scoped team reads ---
    assert store.get_team(org.id, team.id).id == team.id
    assert store.get_team(org.id, other_team.id) is None
    assert [t.id for t in store.list_teams(org.id)] == [team.id]
    assert [m.user_id for m in store.list_team_members(org.id, team.id)] == [member.id]
    assert store.list_team_members(org.id, other_team.id) == []

    # --- add_team_member is idempotent and preserves the original created_at ---
    first = store.list_team_members(org.id, team.id)[0]
    assert store.add_team_member(team.id, member.id).created_at == first.created_at

    # --- member removal drops team memberships in THIS org only ---
    assert store.remove_membership(member.id, org.id) is True
    assert store.get_membership(member.id, org.id) is None
    assert store.list_team_members(org.id, team.id) == []
    assert store.get_membership(member.id, other_org.id) is not None
    assert [m.user_id for m in store.list_team_members(other_org.id, other_team.id)] == [
        member.id
    ]
    assert store.remove_membership(member.id, org.id) is False

    # --- team member removal keeps the org membership; team deletion cascades ---
    store.add_membership(member.id, org.id, Role.MEMBER)
    store.add_team_member(team.id, member.id)
    assert store.remove_team_member(org.id, team.id, member.id) is True
    assert store.remove_team_member(org.id, team.id, member.id) is False
    assert store.get_membership(member.id, org.id) is not None
    assert store.remove_team_member(other_org.id, team.id, member.id) is False

    store.add_team_member(team.id, member.id)
    assert store.delete_team(other_org.id, team.id) is False  # cross-tenant: absent
    assert store.delete_team(org.id, team.id) is True
    assert store.list_teams(org.id) == []
    assert store.list_team_members(org.id, team.id) == []
    assert store.delete_team(org.id, team.id) is False

    # Cleanup: deleting the orgs cascades memberships/teams/team_memberships.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(org.id), str(other_org.id)]},
        )
        await conn.execute(
            text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(owner.id), str(member.id)]},
        )
