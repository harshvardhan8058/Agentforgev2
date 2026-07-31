"""Integration test: migration 0014 + Pg_Budget_Store.

Requires a live PostgreSQL instance. Excluded from the default keyless suite; run with
`pytest -m integration` while the Docker stack is up.

Written because ``Pg_Budget_Store`` shipped without one — the in-memory store proved the
interface, and the SQL that actually holds a customer's spend ceiling had no test at all. What
only a real database can establish:

* migration 0014 reaches ``schema_migrations`` and creates ``spend_budgets``;
* ``NUMERIC`` money survives the round trip **exactly** — the reason this column is not a
  float, and the reason a budget of ``0.000001`` must not become ``1e-06``;
* the ``ON CONFLICT (org_id)`` upsert replaces rather than duplicates, and preserves
  ``created_at`` (when the org started budgeting) while moving ``updated_at``;
* the ``action`` CHECK refuses a value outside the vocabulary, and the ``limit_amount``
  CHECK refuses a negative ceiling;
* one budget per org is enforced by the primary key, not by application convention;
* another org's budget is unreachable, and deleting an org sweeps it.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
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


async def _make_org(engine, name: str) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": str(org_id), "name": name},
        )
    return org_id


def _store() -> Pg_Budget_Store:
    return Pg_Budget_Store(_dsn())


# --- schema ------------------------------------------------------------------------


async def test_migration_0014_is_applied_and_creates_the_table(engine):
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0014_create_spend_budgets"},
        )
        assert applied.scalar_one_or_none() == "0014_create_spend_budgets"

        exists = await conn.execute(text("SELECT to_regclass(:t)"), {"t": "spend_budgets"})
        assert exists.scalar_one() is not None


async def test_the_limit_is_numeric_not_a_float(engine):
    """Money in a float column is a defect waiting for the first invoice dispute."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'spend_budgets' AND column_name = 'limit_amount'"
            )
        )
        assert result.scalar_one() == "numeric"


async def test_the_action_and_limit_constraints_refuse_bad_rows(engine):
    org_id = await _make_org(engine, f"BudgetChecks {uuid.uuid4()}")

    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO spend_budgets (org_id, limit_amount, action) "
                    "VALUES (:org, 10, 'explode')"
                ),
                {"org": str(org_id)},
            )

    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO spend_budgets (org_id, limit_amount, action) "
                    "VALUES (:org, -1, 'block')"
                ),
                {"org": str(org_id)},
            )


# --- round trip --------------------------------------------------------------------


async def test_an_absent_budget_reads_as_none(engine):
    """The unlimited default, distinguishable from a budget of zero."""
    org_id = await _make_org(engine, f"NoBudget {uuid.uuid4()}")

    assert _store().get(org_id) is None


@pytest.mark.parametrize(
    "amount",
    # Every value fits NUMERIC(20, 8): at most 12 integer digits and 8 decimal places.
    ["0", "0.00000001", "12.34", "1000000.99", "999999999999.99999999"],
)
async def test_money_round_trips_exactly(engine, amount: str):
    """Verbatim decimals: 12.34 must not drift, and a tiny ceiling must not vanish."""
    org_id = await _make_org(engine, f"Money {uuid.uuid4()}")
    store = _store()

    store.upsert(org_id, limit_amount=Decimal(amount), action="block")
    fetched = store.get(org_id)

    assert fetched is not None
    assert isinstance(fetched.limit_amount, Decimal)
    assert fetched.limit_amount == Decimal(amount)
    # The API renders this with ``str()``, so it must never come back in scientific
    # notation — "1E-8" is not a number a billing client can parse.
    assert "E" not in str(fetched.limit_amount).upper()


@pytest.mark.parametrize("action", ["warn", "block"])
async def test_both_actions_round_trip(engine, action: str):
    org_id = await _make_org(engine, f"Action {uuid.uuid4()}")
    store = _store()

    store.upsert(org_id, limit_amount=Decimal("10"), action=action)

    assert store.get(org_id).action == action


# --- upsert ------------------------------------------------------------------------


async def test_the_upsert_replaces_rather_than_duplicating(engine):
    """`ON CONFLICT` rather than select-then-write: two owners saving at once must not race."""
    org_id = await _make_org(engine, f"Upsert {uuid.uuid4()}")
    store = _store()

    store.upsert(org_id, limit_amount=Decimal("10"), action="warn")
    second = store.upsert(org_id, limit_amount=Decimal("20"), action="block")

    assert second.limit_amount == Decimal("20")
    assert second.action == "block"
    async with engine.connect() as conn:
        count = await conn.execute(
            text("SELECT count(*) FROM spend_budgets WHERE org_id = :id"),
            {"id": str(org_id)},
        )
    assert count.scalar_one() == 1


async def test_the_upsert_preserves_when_budgeting_started(engine):
    """`created_at` records when the org started budgeting, not when the ceiling last moved."""
    org_id = await _make_org(engine, f"Created {uuid.uuid4()}")
    store = _store()

    first = store.upsert(org_id, limit_amount=Decimal("10"), action="warn")
    second = store.upsert(org_id, limit_amount=Decimal("20"), action="warn")

    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at


async def test_one_budget_per_org_is_enforced_by_the_schema(engine):
    """Not by application convention: a second row must be impossible."""
    org_id = await _make_org(engine, f"Unique {uuid.uuid4()}")
    _store().upsert(org_id, limit_amount=Decimal("10"), action="warn")

    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO spend_budgets (org_id, limit_amount, action) "
                    "VALUES (:org, 5, 'warn')"
                ),
                {"org": str(org_id)},
            )


# --- delete and isolation ----------------------------------------------------------


async def test_delete_reports_whether_a_budget_existed(engine):
    org_id = await _make_org(engine, f"DeleteBudget {uuid.uuid4()}")
    store = _store()
    store.upsert(org_id, limit_amount=Decimal("10"), action="warn")

    assert store.delete(org_id) is True
    assert store.delete(org_id) is False
    assert store.get(org_id) is None


async def test_another_org_cannot_read_or_delete_a_budget(engine):
    org_id = await _make_org(engine, f"BudgetOwner {uuid.uuid4()}")
    other_org = await _make_org(engine, f"BudgetOther {uuid.uuid4()}")
    store = _store()
    store.upsert(org_id, limit_amount=Decimal("10"), action="block")

    assert store.get(other_org) is None
    assert store.delete(other_org) is False
    assert store.get(org_id) is not None  # untouched


async def test_deleting_an_org_sweeps_its_budget(engine):
    org_id = await _make_org(engine, f"BudgetCascade {uuid.uuid4()}")
    _store().upsert(org_id, limit_amount=Decimal("10"), action="block")

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)}
        )

    async with engine.connect() as conn:
        count = await conn.execute(
            text("SELECT count(*) FROM spend_budgets WHERE org_id = :id"),
            {"id": str(org_id)},
        )
    assert count.scalar_one() == 0
