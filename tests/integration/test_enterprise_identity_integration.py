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
