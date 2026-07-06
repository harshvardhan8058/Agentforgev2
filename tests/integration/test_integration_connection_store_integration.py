"""Integration test: migration 0011 + Pg_Integration_Connection_Store (Task 7.5).

Requires a live PostgreSQL instance. Excluded from the default keyless suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the store converts it to a sync libpq DSN internally.

Asserts (Req 11.1, 11.3, 11.4):

* migration 0011 reaches ``schema_migrations`` and creates ``integration_connections``;
* the table has **no** secret/token column (structurally cannot hold credential material);
* ``Pg_Integration_Connection_Store`` round-trips under ``org_id`` scoping with cross-org
  isolation (a cross-tenant get returns ``None`` and list returns ``[]``);
* ``ON DELETE CASCADE`` sweeps an org's connection rows when the org is deleted.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.integrations.connection import Pg_Integration_Connection_Store

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


async def _make_org(engine, name: str) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": str(org_id), "name": name},
        )
    return org_id


async def test_migration_0011_applied_and_no_secret_column(engine):
    """0011 reaches schema_migrations, creates the table, and has no secret column."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0011_create_integration_connections"},
        )
        assert applied.scalar_one_or_none() == "0011_create_integration_connections"

        exists = await conn.execute(
            text("SELECT to_regclass(:t)"), {"t": "integration_connections"}
        )
        assert exists.scalar_one() is not None

        cols = await conn.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'integration_connections'
                """
            )
        )
        column_names = {row[0] for row in cols}
        assert column_names == {"id", "org_id", "integration", "config", "created_at"}
        # Structurally no credential material can be stored.
        for forbidden in ("token", "secret", "credential", "password"):
            assert not any(forbidden in c for c in column_names)


async def test_pg_store_round_trip_isolation_and_cascade(engine):
    """Round-trip under org scoping, cross-org isolation, and ON DELETE CASCADE."""
    org_a = await _make_org(engine, f"org-a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"org-b-{uuid.uuid4().hex}")
    store = Pg_Integration_Connection_Store(_dsn())

    created = store.create(org_a, "slack", {"default_channel": "#general"})

    # Owner round-trips the row.
    got = store.get(org_a, created.id)
    assert got is not None
    assert got.integration == "slack"
    assert got.config == {"default_channel": "#general"}
    assert [c.id for c in store.list_for_org(org_a)] == [created.id]

    # Cross-org read returns nothing (Req 11.2).
    assert store.get(org_b, created.id) is None
    assert store.list_for_org(org_b) == []

    # Deleting org A cascades to its connection rows (Req 11.1).
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_a)}
        )
    assert store.list_for_org(org_a) == []

    # Cleanup org B.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_b)}
        )
