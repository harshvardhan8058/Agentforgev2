"""Property test: migration runner idempotence (Phase 9, Property 3).

Feature: agentforge-deployment, Property 3: Migration runner is idempotent
Validates: Requirements 13.2, 18.3

For any database state produced by applying some prefix of the migration set, applying
the full ``run_migrations`` and then applying it a SECOND time results in no further
migrations (the second run returns ``[]``) and leaves the ``schema_migrations`` row set
unchanged. This is what makes rolling back to an earlier image safe: migrations are
additive and re-running the runner is a no-op.

This test needs a live PostgreSQL (pgvector) instance, so it is marked
``@pytest.mark.integration`` and runs ONLY in the integration lane
(``pytest -m integration``) — it is deselected from the default keyless lane
(``pytest -m 'not integration'``), which never requires a database. The engine is
managed inside the test (via ``asyncio.run``) so Hypothesis can drive it without a
function-scoped async fixture.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import (
    DEFAULT_MIGRATIONS_DIR,
    discover_migrations,
    run_migrations,
)

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384
DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge",
)

_ALL_MIGRATIONS = discover_migrations()
_NUM_MIGRATIONS = len(_ALL_MIGRATIONS)


async def _reset_schema(engine) -> None:
    """Drop and recreate the public schema so each example starts from a clean DB."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def _applied_ids(engine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT id FROM schema_migrations ORDER BY id"))
        return [r[0] for r in rows]


def _subset_dir(prefix: int) -> Path:
    """Materialize a temp migrations dir holding only the first ``prefix`` migrations."""
    tmp = Path(tempfile.mkdtemp(prefix="af_migsubset_"))
    for path in _ALL_MIGRATIONS[:prefix]:
        shutil.copy2(path, tmp / path.name)
    return tmp


async def _run_scenario(prefix: int) -> tuple[list[str], list[str], list[str]]:
    engine = create_engine(DSN)
    subset = _subset_dir(prefix)
    try:
        await _reset_schema(engine)
        # Simulate an already-partially-migrated DB: pre-apply the first `prefix`
        # migrations, so the "already applied" set varies across examples.
        await run_migrations(engine, EMBEDDING_DIMENSION, migrations_dir=subset)
        # First full run applies whatever remains.
        await run_migrations(engine, EMBEDDING_DIMENSION, migrations_dir=DEFAULT_MIGRATIONS_DIR)
        ids_after_first = await _applied_ids(engine)
        # Second full run MUST be a complete no-op (idempotence).
        second = await run_migrations(
            engine, EMBEDDING_DIMENSION, migrations_dir=DEFAULT_MIGRATIONS_DIR
        )
        ids_after_second = await _applied_ids(engine)
        return second, ids_after_first, ids_after_second
    finally:
        await engine.dispose()
        shutil.rmtree(subset, ignore_errors=True)


@hyp_settings(max_examples=100, deadline=None)
@given(prefix=st.integers(min_value=0, max_value=max(_NUM_MIGRATIONS, 1)))
def test_migration_runner_is_idempotent(prefix: int) -> None:
    prefix = min(prefix, _NUM_MIGRATIONS)
    second, ids_first, ids_second = asyncio.run(_run_scenario(prefix))

    # The second full run applies nothing.
    assert second == [], f"second run unexpectedly applied migrations: {second}"
    # The tracked migration set is unchanged between the two runs.
    assert ids_first == ids_second
    # And the full set is recorded exactly once.
    assert len(ids_first) == _NUM_MIGRATIONS
    assert len(set(ids_first)) == _NUM_MIGRATIONS
