"""Integration test: pgvector extension + schema migrations (Req 4.1-4.4).

Requires a live PostgreSQL (pgvector) instance. Excluded from the default suite;
run with `pytest -m integration` while the Docker stack is up. Uses the
``DATABASE_URL`` environment variable (async DSN).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import (
    MigrationError,
    render_migration,
    run_migrations,
)

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384


@pytest.fixture
def engine():
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge",
    )
    return create_engine(dsn)


async def test_extension_enabled_and_tables_created(engine):
    await run_migrations(engine, EMBEDDING_DIMENSION)

    async with engine.connect() as conn:
        ext = await conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        assert ext.scalar_one_or_none() == 1

        for table in ("documents", "chunks", "chunk_embeddings"):
            exists = await conn.execute(
                text("SELECT to_regclass(:t)"), {"t": table}
            )
            assert exists.scalar_one() is not None


async def test_vector_column_matches_configured_dimension(engine):
    await run_migrations(engine, EMBEDDING_DIMENSION)

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'chunk_embeddings'
                  AND a.attname = 'embedding'
                """
            )
        )
        column_type = result.scalar_one()
        assert column_type == f"vector({EMBEDDING_DIMENSION})"


async def test_failed_migration_reports_identifier(engine, tmp_path):
    # A migration directory containing an intentionally broken statement.
    bad = tmp_path / "9999_broken.sql"
    bad.write_text("CREATE TABLE ( this is not valid sql );", encoding="utf-8")

    with pytest.raises(MigrationError) as excinfo:
        await run_migrations(engine, EMBEDDING_DIMENSION, migrations_dir=tmp_path)

    assert excinfo.value.migration_id == "9999_broken"


def test_render_migration_templates_dimension():
    rendered = render_migration("vector(${EMBEDDING_DIMENSION})", 768)
    assert "vector(768)" in rendered
