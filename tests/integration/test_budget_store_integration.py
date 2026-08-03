"""Integration test: migration 0014 + Pg_Budget_Store against a live PostgreSQL.

Requires a live PostgreSQL instance (excluded from the default suite; run with
``pytest -m integration`` while the stack is up).

This store shipped without one, which was a real gap rather than a documentation nit: its whole
job is to hold an exact monetary value, and ``NUMERIC(20, 8)`` round-tripping as a ``Decimal``
(not a float), the ``ON CONFLICT`` upsert that preserves ``created_at``, and the ``CHECK``
constraints are all things only the real database can be asked about.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.observability.budget import Pg_Budget_Store

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


@pytest.fixture
def store():
    return Pg_Budget_Store(_dsn())


def _org(name: str = "Budget Org"):
    return Pg_Identity_Store(_dsn()).create_organization(name).id


async def test_migration_0014_applied(engine):
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0014_create_spend_budgets"},
        )
        assert applied.scalar_one_or_none() == "0014_create_spend_budgets"


async def test_no_budget_reads_as_none(engine, store):
    assert store.get(_org()) is None


async def test_a_budget_round_trips_as_an_exact_decimal(engine, store):
    """The value is money: it must come back as a Decimal, not as a float."""
    org_id = _org()
    saved = store.upsert(org_id, limit_amount=Decimal("12.34567890"), action="block")
    fetched = store.get(org_id)

    assert isinstance(fetched.limit_amount, Decimal)
    assert fetched.limit_amount == Decimal("12.34567890")
    assert fetched.action == "block"
    assert fetched == saved


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),  # "spend nothing" is a valid ceiling, distinct from no budget
        Decimal("0.00000001"),  # the full scale the column offers
        Decimal("999999999999.99999999"),  # 12 integer digits, 8 fractional: the column's max
    ],
)
async def test_the_full_representable_range_round_trips(engine, store, amount):
    org_id = _org(f"Budget {amount}")
    store.upsert(org_id, limit_amount=amount, action="warn")
    assert store.get(org_id).limit_amount == amount


async def test_upsert_replaces_the_ceiling_and_preserves_created_at(engine, store):
    """``created_at`` records when the org started budgeting, not when the ceiling last moved."""
    org_id = _org()
    first = store.upsert(org_id, limit_amount=Decimal("10"), action="warn")
    second = store.upsert(org_id, limit_amount=Decimal("20"), action="block")

    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert store.get(org_id).limit_amount == Decimal("20")
    assert store.get(org_id).action == "block"


async def test_one_row_per_organization(engine, store):
    org_id = _org()
    store.upsert(org_id, limit_amount=Decimal("10"), action="warn")
    store.upsert(org_id, limit_amount=Decimal("11"), action="warn")
    async with engine.connect() as conn:
        count = await conn.execute(
            text("SELECT COUNT(*) FROM spend_budgets WHERE org_id = :id"),
            {"id": str(org_id)},
        )
        assert count.scalar_one() == 1


async def test_delete_removes_the_budget_and_reports_whether_it_existed(engine, store):
    org_id = _org()
    store.upsert(org_id, limit_amount=Decimal("10"), action="warn")
    assert store.delete(org_id) is True
    assert store.get(org_id) is None
    assert store.delete(org_id) is False


async def test_another_orgs_budget_is_unreachable(engine, store):
    org_id = _org("Owner org")
    other_id = _org("Other org")
    store.upsert(org_id, limit_amount=Decimal("10"), action="block")

    assert store.get(other_id) is None
    assert store.delete(other_id) is False
    assert store.get(org_id).limit_amount == Decimal("10")


async def test_the_negative_amount_check_constraint_holds(engine):
    """The schema refuses a negative ceiling, not only the request schema."""
    org_id = _org()
    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO spend_budgets (org_id, limit_amount, action) "
                    "VALUES (:id, -1, 'warn')"
                ),
                {"id": str(org_id)},
            )


async def test_the_action_check_constraint_holds(engine):
    org_id = _org()
    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO spend_budgets (org_id, limit_amount, action) "
                    "VALUES (:id, 10, 'explode')"
                ),
                {"id": str(org_id)},
            )


async def test_deleting_the_organization_cascades_the_budget(engine, store):
    org_id = _org("Doomed org")
    store.upsert(org_id, limit_amount=Decimal("10"), action="warn")

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)}
        )

    assert store.get(org_id) is None
