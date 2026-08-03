"""Unit tests for the delivery worker: one attempt per pass, and never a stuck queue.

The worker is where the durability guarantee is either honoured or quietly broken, so these tests
are about its decisions rather than its plumbing: when to retry, when to stop retrying, what to do
about a subscription that has been paused or deleted since the event was enqueued, and the absolute
rule that one poisoned row cannot stop a tenant's other events.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.outbox import InMemory_Webhook_Outbox, Outbox_Entry
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport
from agentforge.webhooks.worker import SETTLED_RETENTION, Webhook_Delivery_Worker

ORG = uuid.uuid4()

# Anchored to the REAL clock, not a fixed literal, and that is load-bearing rather than lazy.
# The worker's clock is injectable (so the retry schedule can be asserted without waiting), but
# the in-memory outbox stamps `updated_at` from the real clock when it settles a row. A fixed
# literal therefore made the retention test depend on the time of day it ran: with a base of
# 12:00, `clock.advance(7 days + 1h)` put the prune cutoff at 13:00, so a row stamped at 14:00
# real time was "not old enough" and the test failed every afternoon. Anchoring the fake clock to
# real time keeps every advance relative and the test deterministic.
NOW = datetime.now(timezone.utc)


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def wired():
    """Return ``(worker, outbox, subscriptions, transport, deliveries, clock)``."""
    outbox = InMemory_Webhook_Outbox()
    deliveries = InMemory_Webhook_Delivery_Store()
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    transport = Recording_Webhook_Transport()
    emitter = Webhook_Emitter(deliveries, transport)
    clock = _Clock()
    worker = Webhook_Delivery_Worker(
        outbox,
        subscriptions,
        emitter,
        batch_size=5,
        max_attempts=4,
        backoff_seconds=60.0,
        clock=clock,
    )
    return worker, outbox, subscriptions, transport, deliveries, clock


def _subscribe(subscriptions, *, active=True, org=ORG):
    return subscriptions.create(
        org,
        url="https://hooks.example.com/h",
        secret="signing-key",
        events=(Webhook_Event.RUN_COMPLETED,),
        active=active,
    )


def _enqueue(outbox, subscription, *, now=NOW, key="run.completed:r1"):
    return outbox.enqueue(
        Outbox_Entry.new(
            org_id=subscription.org_id,
            subscription_id=subscription.id,
            event=Webhook_Event.RUN_COMPLETED,
            payload={"run_id": "r1"},
            idempotency_key=key,
            now=now,
        )
    )


# --- the happy path ---------------------------------------------------------------


def test_a_pass_delivers_a_due_entry_and_settles_it(wired):
    worker, outbox, subscriptions, transport, deliveries, _clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)

    assert worker.run_once() == 1

    assert transport.attempts == 1
    settled = outbox.get(ORG, entry.id)
    assert settled.status == "delivered"
    assert settled.attempts == 1
    # And the attempt is in the delivery log under the outbox row's id.
    assert [d.id for d in deliveries.list_for_subscription(ORG, subscription.id)] == [
        entry.id
    ]


def test_a_pass_with_nothing_due_does_nothing(wired):
    worker, _outbox, _subscriptions, transport, _deliveries, _clock = wired
    assert worker.run_once() == 0
    assert transport.attempts == 0


def test_a_delivered_entry_is_never_attempted_again(wired):
    worker, outbox, subscriptions, transport, _deliveries, clock = wired
    _enqueue(outbox, _subscribe(subscriptions))

    worker.run_once()
    clock.advance(days=1)
    worker.run_once()

    assert transport.attempts == 1


def test_a_pass_is_bounded_by_the_batch_size(wired):
    worker, outbox, subscriptions, transport, _deliveries, _clock = wired
    subscription = _subscribe(subscriptions)
    for _ in range(8):
        _enqueue(outbox, subscription)

    assert worker.run_once() == 5  # batch_size
    assert transport.attempts == 5
    assert outbox.pending_count(ORG) == 3


# --- retries ----------------------------------------------------------------------


def test_a_failure_is_rescheduled_on_the_exponential_schedule(wired):
    """One attempt per pass: the row is the retry state, so a restart loses nothing."""
    worker, outbox, subscriptions, transport, _deliveries, clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)
    worker._emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    worker.run_once()

    pending = outbox.get(ORG, entry.id)
    assert pending.status == "pending"
    assert pending.attempts == 1
    assert pending.next_attempt_at == NOW + timedelta(seconds=60)
    assert pending.last_error is not None

    # Not due yet, so a pass in between does nothing.
    clock.advance(seconds=30)
    assert worker.run_once() == 0

    # Due: the second attempt happens and the schedule doubles.
    clock.advance(seconds=30)
    assert worker.run_once() == 1
    assert outbox.get(ORG, entry.id).next_attempt_at == clock.now + timedelta(seconds=120)


def test_a_recovered_endpoint_is_delivered_on_a_later_attempt(wired):
    worker, outbox, subscriptions, transport, _deliveries, clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)
    broken = Recording_Webhook_Transport(succeed_from_attempt=None)
    worker._emitter._transport = broken

    worker.run_once()
    clock.advance(seconds=60)

    # The consumer is fixed between attempts — the failure this design exists for.
    worker._emitter._transport = transport
    worker.run_once()

    assert outbox.get(ORG, entry.id).status == "delivered"
    assert outbox.get(ORG, entry.id).attempts == 2
    assert broken.attempts == 1
    assert transport.attempts == 1


def test_the_schedule_is_bounded_and_the_entry_is_abandoned(wired):
    """An endpoint refusing for hours will not accept on attempt fifty, and the queue is finite."""
    worker, outbox, subscriptions, _transport, _deliveries, clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)
    broken = Recording_Webhook_Transport(succeed_from_attempt=None)
    worker._emitter._transport = broken

    for _ in range(10):
        worker.run_once()
        clock.advance(hours=8)  # always past the next slot

    abandoned = outbox.get(ORG, entry.id)
    assert abandoned.status == "abandoned"
    assert abandoned.attempts == 4  # max_attempts, not one more
    assert broken.attempts == 4
    assert abandoned.last_error is not None


# --- the subscription changing underneath an entry --------------------------------


def test_an_entry_for_a_deleted_subscription_is_abandoned_not_retried(wired):
    """There is no endpoint and no secret to sign with; retrying would be noise forever."""
    worker, outbox, subscriptions, transport, _deliveries, _clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)
    subscriptions.delete(ORG, subscription.id)

    worker.run_once()

    abandoned = outbox.get(ORG, entry.id)
    assert abandoned.status == "abandoned"
    assert "deleted" in abandoned.last_error
    assert transport.attempts == 0


def test_an_entry_for_a_paused_subscription_is_held_not_dropped(wired):
    """Resuming a subscription should deliver what it missed, not discover it was discarded."""
    worker, outbox, subscriptions, transport, _deliveries, clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)
    subscriptions.update(ORG, subscription.id, active=False)

    worker.run_once()

    held = outbox.get(ORG, entry.id)
    assert held.status == "pending"
    assert held.attempts == 0  # a pause is not a delivery attempt
    assert held.next_attempt_at > NOW
    assert transport.attempts == 0

    # Resumed: the held event goes out.
    subscriptions.update(ORG, subscription.id, active=True)
    clock.advance(hours=1)
    worker.run_once()
    assert transport.attempts == 1
    assert outbox.get(ORG, entry.id).status == "delivered"


def test_an_unrenderable_payload_is_abandoned_rather_than_retried(wired):
    worker, outbox, subscriptions, transport, _deliveries, _clock = wired
    subscription = _subscribe(subscriptions)
    entry = outbox.enqueue(
        Outbox_Entry.new(
            org_id=ORG,
            subscription_id=subscription.id,
            event=Webhook_Event.RUN_COMPLETED,
            payload={"bad": object()},
            now=NOW,
        )
    )

    worker.run_once()

    abandoned = outbox.get(ORG, entry.id)
    assert abandoned.status == "abandoned"
    assert "render" in abandoned.last_error
    assert transport.attempts == 0


# --- containment ------------------------------------------------------------------


def test_one_poisoned_entry_does_not_stop_the_rest_of_the_batch(wired):
    worker, outbox, subscriptions, transport, _deliveries, _clock = wired
    subscription = _subscribe(subscriptions)
    good_before = _enqueue(outbox, subscription, now=NOW - timedelta(minutes=3))
    poisoned = _enqueue(outbox, subscription, now=NOW - timedelta(minutes=2))
    good_after = _enqueue(outbox, subscription, now=NOW - timedelta(minutes=1))

    real_get = subscriptions.get

    def _explode_for_one(org_id, subscription_id):
        # Simulates an unexpected failure while handling exactly one entry.
        if getattr(_explode_for_one, "calls", 0) == 1:
            _explode_for_one.calls += 1
            raise RuntimeError("store hiccup")
        _explode_for_one.calls = getattr(_explode_for_one, "calls", 0) + 1
        return real_get(org_id, subscription_id)

    subscriptions.get = _explode_for_one
    worker.run_once()
    subscriptions.get = real_get

    assert outbox.get(ORG, good_before.id).status == "delivered"
    assert outbox.get(ORG, good_after.id).status == "delivered"
    # The poisoned one keeps its lease and is retried once that expires — never lost.
    assert outbox.get(ORG, poisoned.id).status == "pending"


def test_a_failing_claim_does_not_raise_out_of_a_pass(wired):
    worker, _outbox, _subscriptions, _transport, _deliveries, _clock = wired

    class _BrokenOutbox:
        def claim_due(self, *, limit, now=None):
            raise RuntimeError("database down")

    worker._outbox = _BrokenOutbox()
    assert worker.run_once() == 0


# --- retention --------------------------------------------------------------------


def test_settled_entries_are_pruned_by_the_worker(wired):
    """A retention job nobody deploys is the same as no retention job."""
    worker, outbox, subscriptions, _transport, _deliveries, clock = wired
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)
    worker.run_once()
    assert outbox.get(ORG, entry.id).status == "delivered"

    # Past the retention window, and past the hourly sweep interval.
    clock.advance(seconds=SETTLED_RETENTION.total_seconds() + 3600)
    worker.run_once()

    assert outbox.get(ORG, entry.id) is None


def test_the_prune_sweep_is_rate_limited(wired):
    """Hourly, so a busy worker does not run a DELETE on every pass."""
    worker, outbox, subscriptions, _transport, _deliveries, clock = wired
    calls: list[datetime] = []
    real_prune = outbox.prune_settled

    def _counting(*, older_than):
        calls.append(older_than)
        return real_prune(older_than=older_than)

    outbox.prune_settled = _counting

    worker.run_once()
    clock.advance(minutes=5)
    worker.run_once()
    assert len(calls) == 1

    clock.advance(hours=2)
    worker.run_once()
    assert len(calls) == 2


# --- lifecycle --------------------------------------------------------------------


def test_start_and_stop_are_idempotent(wired):
    worker, _outbox, _subscriptions, _transport, _deliveries, _clock = wired

    worker.stop()  # unstarted
    worker.start()
    worker.start()  # already running
    worker.stop()
    worker.stop()


def test_the_running_worker_delivers_without_being_polled_by_hand(wired):
    """The loop is what makes this a background worker rather than a function somebody calls."""
    import time

    worker, outbox, subscriptions, transport, _deliveries, _clock = wired
    worker._poll_seconds = 0.05
    subscription = _subscribe(subscriptions)
    entry = _enqueue(outbox, subscription)

    worker.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if outbox.get(ORG, entry.id).status == "delivered":
                break
            time.sleep(0.02)
    finally:
        worker.stop()

    assert outbox.get(ORG, entry.id).status == "delivered"
    assert transport.attempts == 1
