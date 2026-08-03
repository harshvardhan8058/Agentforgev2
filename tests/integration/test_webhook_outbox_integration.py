"""Integration test: migration 0017 + Pg_Webhook_Outbox against a live PostgreSQL.

Requires a live PostgreSQL instance (excluded from the default suite; run with
``pytest -m integration`` while the stack is up).

This is the suite that matters most in the whole webhook feature, because the property the durable
design rests on is a property of one SQL statement, not of Python: ``UPDATE … WHERE id IN (SELECT …
FOR UPDATE SKIP LOCKED)`` must select *and* lease atomically, so two workers draining one queue
never take the same row. The in-memory outbox can imitate that; only Postgres can prove it.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.outbox import (
    LEASE_SECONDS,
    Outbox_Entry,
    Pg_Webhook_Outbox,
)
from agentforge.webhooks.store import Pg_Webhook_Subscription_Store

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
def outbox():
    return Pg_Webhook_Outbox(_dsn())


@pytest.fixture(autouse=True)
async def _own_the_queue(engine):
    """Empty ``webhook_outbox`` before each test in this module.

    Every other integration suite isolates itself by creating a fresh organization, because
    every query it makes is org-scoped. The outbox is the one store whose central queries —
    ``claim_due`` and ``prune_settled`` — are deliberately **global**: a delivery worker drains
    the whole queue, not one tenant's slice, and scoping them by org would defeat the purpose.

    A test about queue mechanics therefore has to own the queue, or a row left behind by an
    earlier test is indistinguishable from one this test enqueued. Depends on ``engine`` so the
    migration that creates the table has run first.
    """
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM webhook_outbox"))
    yield


def _org(name: str = "Outbox Org"):
    return Pg_Identity_Store(_dsn()).create_organization(name).id


def _subscription(org_id):
    return Pg_Webhook_Subscription_Store(_dsn()).create(
        org_id,
        url="https://hooks.example.com/agentforge",
        secret="signing-key",
        events=(Webhook_Event.RUN_COMPLETED,),
    )


def _entry(org_id, subscription_id, *, now=None, key="run.completed:r1") -> Outbox_Entry:
    return Outbox_Entry.new(
        org_id=org_id,
        subscription_id=subscription_id,
        event=Webhook_Event.RUN_COMPLETED,
        payload={"run_id": "r1", "kind": "agent", "citation_count": 3},
        idempotency_key=key,
        now=now or datetime.now(timezone.utc),
    )


async def test_migration_0017_applied(engine):
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0017_create_webhook_outbox"},
        )
        assert applied.scalar_one_or_none() == "0017_create_webhook_outbox"
        exists = await conn.execute(text("SELECT to_regclass('webhook_outbox')"))
        assert exists.scalar_one() is not None


async def test_an_entry_round_trips_with_its_jsonb_payload(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    entry = outbox.enqueue(_entry(org_id, subscription.id))

    stored = outbox.get(org_id, entry.id)
    assert stored.payload == {"run_id": "r1", "kind": "agent", "citation_count": 3}
    assert stored.idempotency_key == "run.completed:r1"
    assert stored.event is Webhook_Event.RUN_COMPLETED
    assert stored.status == "pending"
    assert stored.attempts == 0
    assert stored.leased_until is None


async def test_two_workers_never_claim_the_same_row(engine, outbox):
    """The load-bearing property: FOR UPDATE SKIP LOCKED, proven against the real planner."""
    org_id = _org()
    subscription = _subscription(org_id)
    for _ in range(6):
        outbox.enqueue(_entry(org_id, subscription.id))

    second_worker = Pg_Webhook_Outbox(_dsn())
    first_batch = outbox.claim_due(limit=4)
    second_batch = second_worker.claim_due(limit=4)

    assert len(first_batch) == 4
    assert len(second_batch) == 2  # the remainder, not a re-read of the leased four
    assert {e.id for e in first_batch}.isdisjoint({e.id for e in second_batch})


async def test_a_leased_row_is_invisible_until_the_lease_expires(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    entry = outbox.enqueue(_entry(org_id, subscription.id))

    assert len(outbox.claim_due(limit=10)) == 1
    assert outbox.claim_due(limit=10) == []

    # A crashed worker leaves the lease behind; time makes the row deliverable again rather than
    # stranding the event.
    later = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS + 5)
    assert [e.id for e in outbox.claim_due(limit=10, now=later)] == [entry.id]


async def test_a_future_scheduled_row_is_not_claimed(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    entry = outbox.enqueue(_entry(org_id, subscription.id))
    outbox.claim_due(limit=1)
    outbox.reschedule(
        entry.id,
        attempts=1,
        next_attempt_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        error="endpoint returned HTTP 503",
    )

    assert outbox.claim_due(limit=10) == []
    later = datetime.now(timezone.utc) + timedelta(minutes=11)
    assert len(outbox.claim_due(limit=10, now=later)) == 1
    assert outbox.get(org_id, entry.id).last_error.endswith("503")


async def test_claiming_is_oldest_due_first(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    base = datetime.now(timezone.utc)
    oldest = outbox.enqueue(
        _entry(org_id, subscription.id, now=base - timedelta(minutes=10))
    )
    middle = outbox.enqueue(
        _entry(org_id, subscription.id, now=base - timedelta(minutes=5))
    )
    outbox.enqueue(_entry(org_id, subscription.id, now=base))

    claimed = outbox.claim_due(limit=2)
    assert [e.id for e in claimed] == [oldest.id, middle.id]


async def test_settling_and_requeueing(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    delivered = outbox.enqueue(_entry(org_id, subscription.id))
    abandoned = outbox.enqueue(_entry(org_id, subscription.id))

    outbox.mark_delivered(delivered.id, attempts=2)
    outbox.abandon(abandoned.id, attempts=8, error="endpoint returned HTTP 500")

    assert outbox.get(org_id, delivered.id).status == "delivered"
    assert outbox.get(org_id, delivered.id).attempts == 2
    assert outbox.get(org_id, abandoned.id).status == "abandoned"
    assert outbox.claim_due(limit=10) == []

    requeued = outbox.requeue(org_id, abandoned.id)
    assert requeued is not None
    assert requeued.attempts == 0
    assert len(outbox.claim_due(limit=10)) == 1

    # Only abandoned rows are requeueable: requeueing a pending one would duplicate a delivery.
    assert outbox.requeue(org_id, delivered.id) is None


async def test_another_org_cannot_read_or_requeue_an_entry(engine, outbox):
    org_id = _org("Outbox owner")
    other_id = _org("Outbox other")
    subscription = _subscription(org_id)
    entry = outbox.enqueue(_entry(org_id, subscription.id))
    outbox.abandon(entry.id, attempts=8, error="gone")

    assert outbox.get(other_id, entry.id) is None
    assert outbox.list_for_org(other_id) == []
    assert outbox.pending_count(other_id) == 0
    assert outbox.requeue(other_id, entry.id) is None


async def test_listing_filters_by_status_and_counts_pending(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    pending = outbox.enqueue(_entry(org_id, subscription.id))
    gone = outbox.enqueue(_entry(org_id, subscription.id))
    outbox.abandon(gone.id, attempts=8, error="gone")

    assert [e.id for e in outbox.list_for_org(org_id, status="pending")] == [pending.id]
    assert [e.id for e in outbox.list_for_org(org_id, status="abandoned")] == [gone.id]
    assert outbox.pending_count(org_id) == 1


async def test_pruning_removes_delivered_rows_only(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    delivered = outbox.enqueue(_entry(org_id, subscription.id))
    abandoned = outbox.enqueue(_entry(org_id, subscription.id))
    outbox.mark_delivered(delivered.id, attempts=1)
    outbox.abandon(abandoned.id, attempts=8, error="gone")

    removed = outbox.prune_settled(
        older_than=datetime.now(timezone.utc) + timedelta(minutes=1)
    )

    assert removed == 1
    assert outbox.get(org_id, delivered.id) is None
    # Abandoned rows survive: they are the ones a human still has to look at.
    assert outbox.get(org_id, abandoned.id) is not None


async def test_the_status_check_constraint_holds(engine, outbox):
    org_id = _org()
    subscription = _subscription(org_id)
    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO webhook_outbox (id, org_id, subscription_id, event, payload, "
                    "status) VALUES (:id, :org, :sub, 'run.completed', '{}'::jsonb, 'sending')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org_id),
                    "sub": str(subscription.id),
                },
            )


async def test_deleting_a_subscription_cascades_its_queued_events(engine, outbox):
    """An undelivered event for a deleted subscription has nowhere to go."""
    org_id = _org()
    subscription = _subscription(org_id)
    entry = outbox.enqueue(_entry(org_id, subscription.id))

    Pg_Webhook_Subscription_Store(_dsn()).delete(org_id, subscription.id)

    assert outbox.get(org_id, entry.id) is None


async def test_deleting_the_organization_cascades_the_queue(engine, outbox):
    org_id = _org("Doomed outbox org")
    subscription = _subscription(org_id)
    entry = outbox.enqueue(_entry(org_id, subscription.id))

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)}
        )

    assert outbox.get(org_id, entry.id) is None
