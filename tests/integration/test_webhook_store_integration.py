"""Integration test: migration 0015 + the Pg webhook stores against a live PostgreSQL.

Requires a live PostgreSQL instance (excluded from the default suite; run with
``pytest -m integration`` while the stack is up). Asserts the half the keyless lane structurally
cannot: the real table and its CHECK constraints, ``TEXT[]`` event round-tripping, the
``:event = ANY(events)`` matching the emitter relies on, the partial-``UPDATE`` that can set a
column to NULL, the keyset cursor over ``(created_at, id)``, and the two cascades — a deleted
subscription taking its delivery log, and a deleted organization taking both.
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
from agentforge.webhooks.base import Webhook_Delivery, Webhook_Event
from agentforge.webhooks.store import (
    Pg_Webhook_Delivery_Store,
    Pg_Webhook_Subscription_Store,
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


@pytest.fixture
def stores():
    return (
        Pg_Webhook_Subscription_Store(_dsn()),
        Pg_Webhook_Delivery_Store(_dsn()),
    )


def _org(name: str = "Webhook Org"):
    """Create a real organization row: both tables reference ``organizations(id)``."""
    return Pg_Identity_Store(_dsn()).create_organization(name).id


def _delivery(org_id, subscription_id, *, when=None, status="delivered") -> Webhook_Delivery:
    return Webhook_Delivery(
        id=uuid.uuid4(),
        org_id=org_id,
        subscription_id=subscription_id,
        event=Webhook_Event.RUN_COMPLETED,
        status=status,
        attempts=2,
        response_status=200 if status == "delivered" else None,
        error=None if status == "delivered" else "ConnectTimeout: too slow",
        duration_ms=41,
        created_at=when or datetime.now(timezone.utc),
    )


async def test_migration_0015_applied(engine):
    """0015 reaches schema_migrations and creates both tables."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0015_create_webhooks"},
        )
        assert applied.scalar_one_or_none() == "0015_create_webhooks"
        for table in ("webhook_subscriptions", "webhook_deliveries"):
            exists = await conn.execute(
                text("SELECT to_regclass(:name)"), {"name": table}
            )
            assert exists.scalar_one() is not None


async def test_a_subscription_round_trips_with_its_event_array(engine, stores):
    subscriptions, _deliveries = stores
    org_id = _org()
    created = subscriptions.create(
        org_id,
        url="https://hooks.example.com/agentforge",
        secret="signing-key",
        events=(Webhook_Event.RUN_COMPLETED, Webhook_Event.GUARDRAIL_BLOCKED),
        description="Ops channel",
        active=True,
    )
    fetched = subscriptions.get(org_id, created.id)
    assert fetched == created
    assert fetched.events == (
        Webhook_Event.RUN_COMPLETED,
        Webhook_Event.GUARDRAIL_BLOCKED,
    )
    assert subscriptions.count_for_org(org_id) == 1


async def test_list_for_event_matches_in_sql(engine, stores):
    """``:event = ANY(events)`` is what keeps the emitter from reading every subscription."""
    subscriptions, _deliveries = stores
    org_id = _org()
    wanted = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    subscriptions.create(
        org_id,
        url="https://hooks.example.com/b",
        secret="k",
        events=(Webhook_Event.RUN_FAILED,),
    )
    subscriptions.create(
        org_id,
        url="https://hooks.example.com/c",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
        active=False,
    )
    matched = subscriptions.list_for_event(org_id, Webhook_Event.RUN_COMPLETED)
    assert [s.id for s in matched] == [wanted.id]


async def test_a_partial_update_can_clear_the_description(engine, stores):
    """The SET list is built from supplied fields, so NULL is expressible."""
    subscriptions, _deliveries = stores
    org_id = _org()
    created = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
        description="Ops",
    )
    paused = subscriptions.update(org_id, created.id, active=False)
    assert paused.active is False
    assert paused.description == "Ops"

    cleared = subscriptions.update(org_id, created.id, description=None)
    assert cleared.description is None
    assert cleared.active is False
    assert cleared.secret == created.secret
    assert cleared.created_at == created.created_at


async def test_another_org_can_neither_read_nor_write_a_subscription(engine, stores):
    subscriptions, _deliveries = stores
    org_id = _org("Owner org")
    other_id = _org("Other org")
    created = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    assert subscriptions.get(other_id, created.id) is None
    assert subscriptions.update(other_id, created.id, active=False) is None
    assert subscriptions.delete(other_id, created.id) is False
    assert subscriptions.get(org_id, created.id).active is True


async def test_the_delivery_log_pages_by_keyset_with_an_id_tie_break(engine, stores):
    subscriptions, deliveries = stores
    org_id = _org()
    subscription = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    when = datetime.now(timezone.utc)
    # Two share a timestamp exactly, which is what a fan-out produces.
    made = [
        deliveries.record(_delivery(org_id, subscription.id, when=when)),
        deliveries.record(_delivery(org_id, subscription.id, when=when)),
        deliveries.record(
            _delivery(org_id, subscription.id, when=when - timedelta(minutes=1))
        ),
    ]

    seen = []
    cursor = None
    for _ in range(3):
        page = deliveries.list_for_subscription(
            org_id, subscription.id, before=cursor, limit=1
        )
        assert len(page) == 1
        seen.append(page[0].id)
        cursor = (page[0].created_at, page[0].id)

    assert len(set(seen)) == 3
    assert set(seen) == {d.id for d in made}


async def test_a_failed_delivery_round_trips_with_a_null_response_status(engine, stores):
    subscriptions, deliveries = stores
    org_id = _org()
    subscription = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    recorded = deliveries.record(_delivery(org_id, subscription.id, status="failed"))
    fetched = deliveries.list_for_subscription(org_id, subscription.id)[0]
    assert fetched == recorded
    assert fetched.response_status is None
    assert fetched.error.startswith("ConnectTimeout")


async def test_deleting_a_subscription_cascades_its_delivery_log(engine, stores):
    subscriptions, deliveries = stores
    org_id = _org()
    subscription = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    deliveries.record(_delivery(org_id, subscription.id))

    assert subscriptions.delete(org_id, subscription.id) is True
    assert deliveries.list_for_subscription(org_id, subscription.id) == []


async def test_deleting_the_organization_cascades_both_tables(engine, stores):
    subscriptions, deliveries = stores
    org_id = _org("Doomed org")
    subscription = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    deliveries.record(_delivery(org_id, subscription.id))

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)}
        )

    assert subscriptions.list_for_org(org_id) == []
    assert deliveries.list_for_subscription(org_id, subscription.id) == []


async def test_the_status_check_constraint_refuses_an_unknown_status(engine, stores):
    """The schema, not just the application, restricts the delivery status vocabulary."""
    subscriptions, _deliveries = stores
    org_id = _org()
    subscription = subscriptions.create(
        org_id,
        url="https://hooks.example.com/a",
        secret="k",
        events=(Webhook_Event.RUN_COMPLETED,),
    )
    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries
                        (id, org_id, subscription_id, event, status, attempts, duration_ms)
                    VALUES (:id, :org_id, :sub, 'run.completed', 'pending', 1, 5)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org_id": str(org_id),
                    "sub": str(subscription.id),
                },
            )
