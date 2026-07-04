"""Integration test: migration 0007 tenant columns + cascade delete (Task 9.1).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN).

Asserts the ``0007`` migration reaches ``schema_migrations``, adds ``org_id`` to all four
top-level tenant-owned tables with the composite ``(org_id, id)`` indexes, and that
``ON DELETE CASCADE`` from ``organizations(id)`` sweeps a seeded document / conversation /
agent_run / multi_agent_run in a single delete.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations

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


async def test_migration_0007_applied_with_columns_and_indexes(engine):
    """0007 reaches schema_migrations and adds org_id + composite indexes on all tables."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0007_add_org_id_to_tenant_resources"},
        )
        assert applied.scalar_one_or_none() == "0007_add_org_id_to_tenant_resources"

        for table in ("documents", "conversations", "agent_runs", "multi_agent_runs"):
            col = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = 'org_id'"
                ),
                {"t": table},
            )
            assert col.scalar_one_or_none() == 1, f"{table}.org_id missing"

        for index in (
            "documents_org_id_idx",
            "conversations_org_id_idx",
            "agent_runs_org_id_idx",
            "multi_agent_runs_org_id_idx",
        ):
            found = await conn.execute(
                text("SELECT to_regclass(:i)"), {"i": index}
            )
            assert found.scalar_one() is not None, f"{index} missing"


async def test_org_cascade_delete_sweeps_tenant_rows(engine):
    """Deleting an organization cascades to its documents/conversations/agent_runs/runs."""
    org_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    ma_id = str(uuid.uuid4())

    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'Cascade Org')"),
            {"id": org_id},
        )
        await conn.execute(
            text(
                "INSERT INTO documents (id, org_id, filename, content_type, size_bytes, status) "
                "VALUES (:id, :org, 'f.txt', 'text/plain', 1, 'ingested')"
            ),
            {"id": doc_id, "org": org_id},
        )
        await conn.execute(
            text("INSERT INTO conversations (id, org_id) VALUES (:id, :org)"),
            {"id": conv_id, "org": org_id},
        )
        await conn.execute(
            text("INSERT INTO agent_runs (id, org_id) VALUES (:id, :org)"),
            {"id": run_id, "org": org_id},
        )
        await conn.execute(
            text(
                "INSERT INTO multi_agent_runs (id, org_id, conversation_id, task, status) "
                "VALUES (:id, :org, :cid, 'task', 'running')"
            ),
            {"id": ma_id, "org": org_id, "cid": conv_id},
        )

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": org_id}
        )

    async with engine.connect() as conn:
        for table, row_id in (
            ("documents", doc_id),
            ("conversations", conv_id),
            ("agent_runs", run_id),
            ("multi_agent_runs", ma_id),
        ):
            remaining = await conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id}
            )
            assert remaining.scalar_one() == 0, f"{table} row survived org cascade"
