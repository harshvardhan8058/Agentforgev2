"""Integration test: migration 0016 + Pg_Budget_Notification_Store against a live PostgreSQL.

Requires a live PostgreSQL instance (excluded from the default suite; run with
``pytest -m integration`` while the stack is up).

The one behaviour this store exists for cannot be tested without a real database: the claim is
an ``INSERT ... ON CONFLICT DO NOTHING`` against a composite primary key, and "two concurrent
requests observing the same crossing produce exactly one notification" is a property of that
statement, not of Python. So this asserts the constraint, the atomicity from separate
connections, the array-based reconcile, and the organization cascade.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.observability.budget_alerts import Pg_Budget_Notification_Store

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384

JULY = datetime(2026, 7, 1, tzinfo=timezone.utc)
AUGUST = datetime(2026, 8, 1, tzinfo=timezone.utc)


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
    return Pg_Budget_Notification_Store(_dsn())


def _org(name: str = "Budget Alert Org"):
    return Pg_Identity_Store(_dsn()).create_organization(name).id


async def test_migration_0016_applied(engine):
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0016_create_budget_notifications"},
        )
        assert applied.scalar_one_or_none() == "0016_create_budget_notifications"
        exists = await conn.execute(
            text("SELECT to_regclass('budget_notifications')")
        )
        assert exists.scalar_one() is not None


async def test_only_the_first_claim_wins(engine, store):
    org_id = _org()
    assert store.claim(org_id, JULY, 80) is True
    assert store.claim(org_id, JULY, 80) is False
    assert store.claimed(org_id, JULY) == (80,)


async def test_a_second_connection_cannot_also_win_the_claim(engine, store):
    """The atomicity that makes "exactly one notification" true rather than likely."""
    org_id = _org()
    other_connection = Pg_Budget_Notification_Store(_dsn())

    assert store.claim(org_id, JULY, 100) is True
    assert other_connection.claim(org_id, JULY, 100) is False
    assert store.claimed(org_id, JULY) == (100,)


async def test_thresholds_and_periods_are_independent_claims(engine, store):
    org_id = _org()
    store.claim(org_id, JULY, 80)
    store.claim(org_id, JULY, 100)
    store.claim(org_id, AUGUST, 80)

    assert store.claimed(org_id, JULY) == (80, 100)
    assert store.claimed(org_id, AUGUST) == (80,)


async def test_another_org_has_its_own_claims(engine, store):
    org_id = _org("Alert org A")
    other_id = _org("Alert org B")
    store.claim(org_id, JULY, 80)

    assert store.claimed(other_id, JULY) == ()
    assert store.claim(other_id, JULY, 80) is True


async def test_release_makes_the_threshold_claimable_again(engine, store):
    org_id = _org()
    store.claim(org_id, JULY, 80)

    assert store.release(org_id, JULY, 80) is True
    assert store.release(org_id, JULY, 80) is False
    assert store.claim(org_id, JULY, 80) is True


async def test_release_except_keeps_only_the_named_thresholds(engine, store):
    org_id = _org()
    store.claim(org_id, JULY, 80)
    store.claim(org_id, JULY, 100)
    store.claim(org_id, AUGUST, 80)

    assert store.release_except(org_id, JULY, (100,)) == 1

    assert store.claimed(org_id, JULY) == (100,)
    # Scoped to the period as well as the org.
    assert store.claimed(org_id, AUGUST) == (80,)


async def test_release_except_with_an_empty_keep_list_drops_everything(engine, store):
    """What "no threshold is crossed any more" has to mean, e.g. after the budget is removed."""
    org_id = _org()
    store.claim(org_id, JULY, 80)
    store.claim(org_id, JULY, 100)

    assert store.release_except(org_id, JULY, ()) == 2
    assert store.claimed(org_id, JULY) == ()


async def test_the_threshold_check_constraint_holds(engine):
    org_id = _org()
    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO budget_notifications "
                    "(org_id, period_start, threshold_percent) "
                    "VALUES (:id, :period, 0)"
                ),
                {"id": str(org_id), "period": JULY},
            )


async def test_deleting_the_organization_cascades_its_claims(engine, store):
    org_id = _org("Doomed alert org")
    store.claim(org_id, JULY, 80)

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)}
        )

    assert store.claimed(org_id, JULY) == ()
