"""Unit tests for the webhook outbox: the retry schedule and the lease.

Two properties carry the durability guarantee, and both live here rather than in the worker:

* **The schedule** — exponential, capped, and derivable from ``attempts`` alone, so an operator can
  predict when a stuck row moves next.
* **The lease** — a claimed row is invisible to other claimers until its lease expires, which is
  what lets several application instances drain one queue without double-delivering, and what makes
  a crashed worker's backlog deliverable again instead of stranded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.outbox import (
    LEASE_SECONDS,
    MAX_ATTEMPT_DELAY_SECONDS,
    InMemory_Webhook_Outbox,
    Outbox_Entry,
    next_attempt_delay,
)

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
SUB = uuid.uuid4()
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _entry(*, org=ORG, subscription=SUB, key="run.completed:r1", now=NOW) -> Outbox_Entry:
    return Outbox_Entry.new(
        org_id=org,
        subscription_id=subscription,
        event=Webhook_Event.RUN_COMPLETED,
        payload={"run_id": "r1"},
        idempotency_key=key,
        now=now,
    )


# --- the schedule -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempts", "expected_seconds"),
    [
        (1, 60),
        (2, 120),
        (3, 240),
        (4, 480),
        (5, 960),
        (6, 1_920),
    ],
)
def test_the_schedule_is_exponential_from_the_base(attempts, expected_seconds):
    assert next_attempt_delay(attempts, base_seconds=60.0) == timedelta(
        seconds=expected_seconds
    )


def test_the_schedule_is_capped():
    """An unbounded schedule would push a row years out and look identical to a lost event."""
    assert next_attempt_delay(50, base_seconds=60.0) == timedelta(
        seconds=MAX_ATTEMPT_DELAY_SECONDS
    )


def test_the_first_retry_is_one_base_interval_away():
    """attempts=0 cannot happen (a delay is only computed after an attempt), but stays sane."""
    assert next_attempt_delay(0, base_seconds=60.0) == timedelta(seconds=60)


# --- enqueue and claim ------------------------------------------------------------


def test_a_new_entry_is_pending_and_due_immediately():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())

    assert entry.status == "pending"
    assert entry.attempts == 0
    assert entry.next_attempt_at == NOW
    assert entry.leased_until is None

    claimed = outbox.claim_due(limit=10, now=NOW)
    assert [c.id for c in claimed] == [entry.id]


def test_claiming_takes_a_lease_so_a_second_claimer_sees_nothing():
    """The property that makes several application instances safe against one queue."""
    outbox = InMemory_Webhook_Outbox()
    outbox.enqueue(_entry())

    first = outbox.claim_due(limit=10, now=NOW)
    second = outbox.claim_due(limit=10, now=NOW)

    assert len(first) == 1
    assert second == []
    assert first[0].leased_until == NOW + timedelta(seconds=LEASE_SECONDS)


def test_an_expired_lease_makes_the_entry_claimable_again():
    """A worker that crashed mid-attempt must not strand the event forever."""
    outbox = InMemory_Webhook_Outbox()
    outbox.enqueue(_entry())
    outbox.claim_due(limit=10, now=NOW)

    later = NOW + timedelta(seconds=LEASE_SECONDS + 1)
    assert len(outbox.claim_due(limit=10, now=later)) == 1


def test_an_entry_scheduled_for_later_is_not_claimed_yet():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())
    outbox.reschedule(
        entry.id,
        attempts=1,
        next_attempt_at=NOW + timedelta(minutes=5),
        error="endpoint returned HTTP 503",
    )

    assert outbox.claim_due(limit=10, now=NOW + timedelta(minutes=1)) == []
    assert len(outbox.claim_due(limit=10, now=NOW + timedelta(minutes=5))) == 1


def test_claiming_is_oldest_due_first_and_bounded_by_the_limit():
    """Fair ordering, so a burst cannot starve an event that has been waiting."""
    outbox = InMemory_Webhook_Outbox()
    entries = [
        outbox.enqueue(_entry(now=NOW - timedelta(minutes=offset))) for offset in (3, 2, 1)
    ]

    claimed = outbox.claim_due(limit=2, now=NOW)

    assert [c.id for c in claimed] == [entries[0].id, entries[1].id]


# --- settling ---------------------------------------------------------------------


def test_marking_delivered_settles_the_entry_and_clears_its_lease():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())
    outbox.claim_due(limit=1, now=NOW)

    outbox.mark_delivered(entry.id, attempts=2)

    settled = outbox.get(ORG, entry.id)
    assert settled.status == "delivered"
    assert settled.attempts == 2
    assert settled.leased_until is None
    assert settled.last_error is None
    # And it is never claimed again.
    assert outbox.claim_due(limit=10, now=NOW + timedelta(days=1)) == []


def test_rescheduling_records_the_error_and_returns_the_entry_to_pending():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())
    outbox.claim_due(limit=1, now=NOW)

    outbox.reschedule(
        entry.id,
        attempts=1,
        next_attempt_at=NOW + timedelta(minutes=1),
        error="ConnectTimeout: too slow",
    )

    pending = outbox.get(ORG, entry.id)
    assert pending.status == "pending"
    assert pending.attempts == 1
    assert pending.leased_until is None
    assert pending.last_error.startswith("ConnectTimeout")


def test_abandoning_settles_the_entry_with_its_last_error():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())

    outbox.abandon(entry.id, attempts=8, error="endpoint returned HTTP 500")

    abandoned = outbox.get(ORG, entry.id)
    assert abandoned.status == "abandoned"
    assert abandoned.attempts == 8
    assert abandoned.last_error == "endpoint returned HTTP 500"
    assert outbox.claim_due(limit=10, now=NOW + timedelta(days=1)) == []


def test_settling_an_unknown_entry_is_a_no_op_rather_than_an_error():
    """A worker whose row was deleted underneath it (org cascade) must not crash a pass."""
    outbox = InMemory_Webhook_Outbox()
    outbox.mark_delivered(uuid.uuid4(), attempts=1)
    outbox.abandon(uuid.uuid4(), attempts=1, error="x")
    outbox.reschedule(uuid.uuid4(), attempts=1, next_attempt_at=NOW, error="x")


# --- requeue (operator-driven redelivery) -----------------------------------------


def test_an_abandoned_entry_can_be_requeued_and_is_due_at_once():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())
    outbox.abandon(entry.id, attempts=8, error="endpoint returned HTTP 500")

    requeued = outbox.requeue(ORG, entry.id, now=NOW)

    assert requeued.status == "pending"
    assert requeued.attempts == 0  # a fresh schedule, not a continuation of the old one
    assert len(outbox.claim_due(limit=10, now=NOW)) == 1


def test_only_an_abandoned_entry_can_be_requeued():
    """Requeueing a pending row would duplicate an in-flight delivery."""
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())
    assert outbox.requeue(ORG, entry.id, now=NOW) is None

    outbox.mark_delivered(entry.id, attempts=1)
    assert outbox.requeue(ORG, entry.id, now=NOW) is None


# --- tenancy and inspection -------------------------------------------------------


def test_an_entry_is_invisible_to_another_org():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())

    assert outbox.get(OTHER_ORG, entry.id) is None
    assert outbox.list_for_org(OTHER_ORG) == []
    assert outbox.pending_count(OTHER_ORG) == 0
    assert outbox.requeue(OTHER_ORG, entry.id, now=NOW) is None


def test_listing_is_newest_first_and_filterable_by_status():
    outbox = InMemory_Webhook_Outbox()
    older = outbox.enqueue(_entry(now=NOW - timedelta(minutes=5)))
    newer = outbox.enqueue(_entry(now=NOW))
    outbox.abandon(older.id, attempts=8, error="gone")

    assert [e.id for e in outbox.list_for_org(ORG)] == [newer.id, older.id]
    assert [e.id for e in outbox.list_for_org(ORG, status="abandoned")] == [older.id]
    assert [e.id for e in outbox.list_for_org(ORG, status="pending")] == [newer.id]
    assert outbox.pending_count(ORG) == 1


def test_the_payload_and_key_survive_the_round_trip():
    """The consumer receives what the platform decided to send, not a re-derivation."""
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry(key="budget.threshold_crossed:o:p:80"))

    stored = outbox.get(ORG, entry.id)
    assert stored.payload == {"run_id": "r1"}
    assert stored.idempotency_key == "budget.threshold_crossed:o:p:80"
    assert stored.event is Webhook_Event.RUN_COMPLETED


# --- retention --------------------------------------------------------------------


def test_pruning_removes_settled_entries_only():
    outbox = InMemory_Webhook_Outbox()
    delivered = outbox.enqueue(_entry())
    abandoned = outbox.enqueue(_entry())
    pending = outbox.enqueue(_entry())
    outbox.mark_delivered(delivered.id, attempts=1)
    outbox.abandon(abandoned.id, attempts=8, error="gone")

    removed = outbox.prune_settled(older_than=datetime.now(timezone.utc) + timedelta(days=1))

    assert removed == 1
    assert outbox.get(ORG, delivered.id) is None
    # Abandoned rows are kept: they are the ones a human still has to look at.
    assert outbox.get(ORG, abandoned.id) is not None
    assert outbox.get(ORG, pending.id) is not None


def test_pruning_respects_the_cutoff():
    outbox = InMemory_Webhook_Outbox()
    entry = outbox.enqueue(_entry())
    outbox.mark_delivered(entry.id, attempts=1)

    assert outbox.prune_settled(older_than=NOW - timedelta(days=30)) == 0
    assert outbox.get(ORG, entry.id) is not None
