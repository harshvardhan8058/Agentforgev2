"""Integration test: migration 0015 + the Postgres webhook stores.

Requires a live PostgreSQL instance. Excluded from the default keyless suite; run with
`pytest -m integration` while the Docker stack is up.

The in-memory stores are tested everywhere else, which proves the *interface* and nothing about
the SQL. These assert the parts only a real database can:

* migration 0015 reaches ``schema_migrations`` and creates both tables;
* the ``TEXT[]`` event column round-trips, and ``:event = ANY(events)`` selects on it — the
  emission path's only query, and the one that would silently return nothing if the cast were
  wrong;
* ``COALESCE``-based partial update leaves unsupplied columns alone;
* the ``(created_at, id)`` keyset page is correct across rows sharing a timestamp, which is the
  case the cursor exists for and the one an in-memory list cannot exercise faithfully;
* the ``status`` and ``attempts`` CHECK constraints actually refuse bad rows;
* ``ON DELETE CASCADE`` sweeps a deleted subscription's deliveries, and a deleted org's rows;
* cross-org reads return nothing, because every statement carries ``org_id``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.webhooks.base import Webhook_Delivery
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


async def _make_org(engine, name: str) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": str(org_id), "name": name},
        )
    return org_id


def _subscriptions() -> Pg_Webhook_Subscription_Store:
    return Pg_Webhook_Subscription_Store(_dsn())


def _deliveries() -> Pg_Webhook_Delivery_Store:
    return Pg_Webhook_Delivery_Store(_dsn())


# --- schema ------------------------------------------------------------------------


async def test_migration_0015_is_applied_and_creates_both_tables(engine):
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0015_create_webhooks"},
        )
        assert applied.scalar_one_or_none() == "0015_create_webhooks"

        for table in ("webhook_subscriptions", "webhook_deliveries"):
            exists = await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})
            assert exists.scalar_one() is not None, table


async def test_the_delivery_status_and_attempt_constraints_refuse_bad_rows(engine):
    """The CHECKs are the last line of defence if application code ever regresses."""
    org_id = await _make_org(engine, f"Constraints {uuid.uuid4()}")
    subscription = _subscriptions().create(
        org_id, url="https://hooks.example.com/hook", events=("run.completed",), secret="whsec_x"
    )

    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO webhook_deliveries "
                    "(id, org_id, subscription_id, event_type, status, attempts) VALUES "
                    "(:id, :org, :sub, 'run.completed', 'maybe', 1)"
                ),
                {"id": str(uuid.uuid4()), "org": str(org_id), "sub": str(subscription.id)},
            )

    async with engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO webhook_deliveries "
                    "(id, org_id, subscription_id, event_type, status, attempts) VALUES "
                    "(:id, :org, :sub, 'run.completed', 'delivered', 0)"
                ),
                {"id": str(uuid.uuid4()), "org": str(org_id), "sub": str(subscription.id)},
            )


# --- subscriptions -----------------------------------------------------------------


async def test_a_subscription_round_trips_with_its_event_array(engine):
    org_id = await _make_org(engine, f"Roundtrip {uuid.uuid4()}")
    store = _subscriptions()

    created = store.create(
        org_id,
        url="https://hooks.example.com/agentforge",
        events=("run.completed", "document.ingested"),
        secret="whsec_roundtrip",
        description="Ops channel",
    )
    fetched = store.get(org_id, created.id)

    assert fetched is not None
    assert fetched.url == "https://hooks.example.com/agentforge"
    assert fetched.events == ("run.completed", "document.ingested")
    assert fetched.secret == "whsec_roundtrip"
    assert fetched.description == "Ops channel"
    assert fetched.active is True
    assert fetched.created_at.tzinfo is not None


async def test_the_emission_query_selects_on_the_event_array(engine):
    """`:event = ANY(events)` is the only query the emission path runs."""
    org_id = await _make_org(engine, f"AnyEvents {uuid.uuid4()}")
    store = _subscriptions()
    wanted = store.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_a"
    )
    store.create(
        org_id, url="https://b.example.com/h", events=("document.ingested",), secret="whsec_b"
    )

    matched = store.list_for_event(org_id, "run.completed")

    assert [s.id for s in matched] == [wanted.id]
    assert store.list_for_event(org_id, "guardrail.blocked") == []


async def test_a_paused_subscription_is_excluded_from_the_emission_query(engine):
    org_id = await _make_org(engine, f"Paused {uuid.uuid4()}")
    store = _subscriptions()
    subscription = store.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_a"
    )

    store.update(org_id, subscription.id, active=False)

    assert store.list_for_event(org_id, "run.completed") == []
    # But it is still listed for management, with its history intact.
    assert [s.id for s in store.list_for_org(org_id)] == [subscription.id]


async def test_a_partial_update_leaves_unsupplied_columns_alone(engine):
    """The COALESCE-per-parameter form: constant statement text, no dynamic SET list."""
    org_id = await _make_org(engine, f"Partial {uuid.uuid4()}")
    store = _subscriptions()
    created = store.create(
        org_id,
        url="https://a.example.com/h",
        events=("run.completed",),
        secret="whsec_partial",
        description="Original",
    )

    updated = store.update(org_id, created.id, active=False)

    assert updated is not None
    assert updated.active is False
    assert updated.url == "https://a.example.com/h"
    assert updated.events == ("run.completed",)
    assert updated.description == "Original"
    assert updated.secret == "whsec_partial"  # never rotated by an update
    assert updated.updated_at >= created.updated_at


async def test_an_update_can_replace_the_event_array(engine):
    org_id = await _make_org(engine, f"Replace {uuid.uuid4()}")
    store = _subscriptions()
    created = store.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_r"
    )

    updated = store.update(org_id, created.id, events=("run.failed", "guardrail.blocked"))

    assert updated is not None
    assert updated.events == ("run.failed", "guardrail.blocked")


async def test_another_org_cannot_read_update_or_delete_a_subscription(engine):
    org_id = await _make_org(engine, f"Owner {uuid.uuid4()}")
    other_org = await _make_org(engine, f"Other {uuid.uuid4()}")
    store = _subscriptions()
    created = store.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_t"
    )

    assert store.get(other_org, created.id) is None
    assert store.list_for_org(other_org) == []
    assert store.list_for_event(other_org, "run.completed") == []
    assert store.update(other_org, created.id, active=False) is None
    assert store.delete(other_org, created.id) is False
    # Untouched.
    assert store.get(org_id, created.id).active is True


async def test_deleting_a_subscription_reports_whether_it_existed(engine):
    org_id = await _make_org(engine, f"Delete {uuid.uuid4()}")
    store = _subscriptions()
    created = store.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_d"
    )

    assert store.delete(org_id, created.id) is True
    assert store.delete(org_id, created.id) is False
    assert store.get(org_id, created.id) is None


# --- deliveries --------------------------------------------------------------------


def _delivery(org_id, subscription_id, *, created_at, status="delivered") -> Webhook_Delivery:
    return Webhook_Delivery(
        id=uuid.uuid4(),
        org_id=org_id,
        subscription_id=subscription_id,
        event_type="run.completed",
        status=status,
        attempts=1,
        response_status=200 if status == "delivered" else 503,
        error=None if status == "delivered" else "endpoint refused",
        duration_ms=12,
        created_at=created_at,
    )


async def test_a_delivery_round_trips(engine):
    org_id = await _make_org(engine, f"Deliv {uuid.uuid4()}")
    subscription = _subscriptions().create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_dl"
    )
    store = _deliveries()
    written = _delivery(
        org_id, subscription.id, created_at=datetime.now(timezone.utc), status="failed"
    )

    store.record(written)
    (fetched,) = store.list_for_subscription(org_id, subscription.id)

    assert fetched.id == written.id
    assert fetched.status == "failed"
    assert fetched.response_status == 503
    assert fetched.error == "endpoint refused"
    assert fetched.attempts == 1
    assert fetched.duration_ms == 12


async def test_the_keyset_page_is_correct_across_rows_sharing_a_timestamp(engine):
    """The case the cursor exists for: one event fanned out in one burst."""
    org_id = await _make_org(engine, f"Keyset {uuid.uuid4()}")
    subscription = _subscriptions().create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_ks"
    )
    store = _deliveries()
    same_instant = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    written = [_delivery(org_id, subscription.id, created_at=same_instant) for _ in range(5)]
    for delivery in written:
        store.record(delivery)
    # The store's order for a shared timestamp is by id descending.
    expected = [d.id for d in sorted(written, key=lambda d: str(d.id), reverse=True)]

    page_one = store.list_for_subscription(org_id, subscription.id, limit=2)
    cursor = (page_one[-1].created_at, page_one[-1].id)
    page_two = store.list_for_subscription(
        org_id, subscription.id, before=cursor, limit=2
    )
    page_three = store.list_for_subscription(
        org_id, subscription.id, before=(page_two[-1].created_at, page_two[-1].id), limit=2
    )

    assert [d.id for d in page_one] == expected[:2]
    assert [d.id for d in page_two] == expected[2:4]
    assert [d.id for d in page_three] == expected[4:]
    # No row is repeated or skipped across the pages.
    seen = [d.id for d in page_one + page_two + page_three]
    assert len(set(seen)) == 5


async def test_deliveries_are_newest_first(engine):
    org_id = await _make_org(engine, f"Order {uuid.uuid4()}")
    subscription = _subscriptions().create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_o"
    )
    store = _deliveries()
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    written = [
        _delivery(org_id, subscription.id, created_at=base + timedelta(minutes=index))
        for index in range(3)
    ]
    for delivery in written:
        store.record(delivery)

    listed = store.list_for_subscription(org_id, subscription.id)

    assert [d.id for d in listed] == [d.id for d in reversed(written)]


async def test_another_org_cannot_read_a_delivery_log(engine):
    org_id = await _make_org(engine, f"LogOwner {uuid.uuid4()}")
    other_org = await _make_org(engine, f"LogOther {uuid.uuid4()}")
    subscription = _subscriptions().create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_l"
    )
    store = _deliveries()
    store.record(_delivery(org_id, subscription.id, created_at=datetime.now(timezone.utc)))

    assert store.list_for_subscription(other_org, subscription.id) == []


async def test_a_delivery_cannot_reference_a_subscription_that_does_not_exist(engine):
    org_id = await _make_org(engine, f"FK {uuid.uuid4()}")
    store = _deliveries()

    with pytest.raises(IntegrityError):
        store.record(
            _delivery(org_id, uuid.uuid4(), created_at=datetime.now(timezone.utc))
        )


# --- cascades ----------------------------------------------------------------------


async def test_deleting_a_subscription_sweeps_its_delivery_log(engine):
    """A log for a subscription that no longer exists has no reader."""
    org_id = await _make_org(engine, f"Cascade {uuid.uuid4()}")
    subscriptions = _subscriptions()
    subscription = subscriptions.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_c"
    )
    deliveries = _deliveries()
    deliveries.record(
        _delivery(org_id, subscription.id, created_at=datetime.now(timezone.utc))
    )

    subscriptions.delete(org_id, subscription.id)

    assert deliveries.list_for_subscription(org_id, subscription.id) == []


async def test_deleting_an_org_sweeps_its_webhooks_and_deliveries(engine):
    org_id = await _make_org(engine, f"OrgCascade {uuid.uuid4()}")
    subscriptions = _subscriptions()
    subscription = subscriptions.create(
        org_id, url="https://a.example.com/h", events=("run.completed",), secret="whsec_oc"
    )
    _deliveries().record(
        _delivery(org_id, subscription.id, created_at=datetime.now(timezone.utc))
    )

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_id)}
        )

    async with engine.connect() as conn:
        subs = await conn.execute(
            text("SELECT count(*) FROM webhook_subscriptions WHERE org_id = :id"),
            {"id": str(org_id)},
        )
        logs = await conn.execute(
            text("SELECT count(*) FROM webhook_deliveries WHERE org_id = :id"),
            {"id": str(org_id)},
        )
    assert subs.scalar_one() == 0
    assert logs.scalar_one() == 0
