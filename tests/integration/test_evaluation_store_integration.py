"""Integration test: migration 0010 + Pg_Evaluation_Store round-trip (Task 8.7).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the store converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.observability.evaluation.store import Pg_Evaluation_Store
from agentforge.observability.models import (
    Evaluation_Dataset,
    Evaluation_Item,
    Evaluation_Result,
    Evaluation_Run,
)

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


async def test_migration_0010_applied(engine):
    """The 0010 migration reaches schema_migrations and creates its tables."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0010_create_evaluations"},
        )
        assert applied.scalar_one_or_none() == "0010_create_evaluations"
        for table in (
            "evaluation_datasets",
            "evaluation_items",
            "evaluation_runs",
            "evaluation_results",
        ):
            exists = await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})
            assert exists.scalar_one() is not None


async def test_pg_evaluation_store_round_trip_and_isolation(engine):
    """Pg_Evaluation_Store round-trips (dataset/items/run/results) under org_id scoping."""
    org_a = await _make_org(engine, f"org-a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"org-b-{uuid.uuid4().hex}")
    store = Pg_Evaluation_Store(_dsn())

    now = datetime.now(timezone.utc)
    dataset_id = uuid.uuid4()
    store.add_dataset(
        Evaluation_Dataset(id=dataset_id, org_id=org_a, name="ds", created_at=now)
    )
    item_id = uuid.uuid4()
    store.add_item(
        Evaluation_Item(
            id=item_id, dataset_id=dataset_id, org_id=org_a, input="q", expected="a"
        )
    )

    run_id = uuid.uuid4()
    store.add_run(
        Evaluation_Run(
            id=run_id,
            org_id=org_a,
            dataset_id=dataset_id,
            aggregate_score=1.0,
            results=[Evaluation_Result(item_id=item_id, evaluator="exact_match", score=1.0)],
            created_at=now,
        )
    )

    # Owner reads back the dataset, items, and run with its results.
    assert store.get_dataset(org_a, dataset_id) is not None
    assert [d.id for d in store.list_datasets(org_a)] == [dataset_id]
    assert [i.id for i in store.list_items(org_a, dataset_id)] == [item_id]
    fetched = store.get_run(org_a, run_id)
    assert fetched is not None
    assert fetched.aggregate_score == 1.0
    assert len(fetched.results) == 1
    assert fetched.results[0].evaluator == "exact_match"

    # Cross-org isolation: org B sees nothing.
    assert store.get_dataset(org_b, dataset_id) is None
    assert store.list_datasets(org_b) == []
    assert store.list_items(org_b, dataset_id) == []
    assert store.get_run(org_b, run_id) is None

    # ON DELETE CASCADE from the dataset sweeps items/runs/results.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM evaluation_datasets WHERE id = :id"),
            {"id": str(dataset_id)},
        )
        remaining_items = await conn.execute(
            text("SELECT count(*) FROM evaluation_items WHERE dataset_id = :id"),
            {"id": str(dataset_id)},
        )
        assert remaining_items.scalar_one() == 0
        remaining_results = await conn.execute(
            text("SELECT count(*) FROM evaluation_results WHERE run_id = :id"),
            {"id": str(run_id)},
        )
        assert remaining_results.scalar_one() == 0

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(:ids)"),
            {"ids": [str(org_a), str(org_b)]},
        )
