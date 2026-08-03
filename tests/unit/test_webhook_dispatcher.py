"""Unit tests for the dispatcher: fan-out into durable rows, and nothing dialled.

The dispatcher runs while a caller waits, so the properties that matter are what it *does not* do
(no DNS, no TLS, no retries, no work proportional to a consumer's latency) and that its outcome is
detailed enough for a caller to decide whether the event still needs enqueueing later.
"""

from __future__ import annotations

import uuid

import pytest

from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.dispatcher import (
    Webhook_Dispatcher,
    disabled_webhook_dispatcher,
)
from agentforge.webhooks.outbox import InMemory_Webhook_Outbox
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()


@pytest.fixture
def wired():
    """Return ``(dispatcher, subscriptions, outbox)``."""
    outbox = InMemory_Webhook_Outbox()
    subscriptions = InMemory_Webhook_Subscription_Store(
        InMemory_Webhook_Delivery_Store()
    )
    return Webhook_Dispatcher(subscriptions, outbox), subscriptions, outbox


def _subscribe(subscriptions, *, events=(Webhook_Event.RUN_COMPLETED,), active=True, org=ORG):
    return subscriptions.create(
        org,
        url="https://hooks.example.com/h",
        secret="k",
        events=tuple(events),
        active=active,
    )


# --- the common case: nobody is listening -----------------------------------------


def test_dispatching_with_no_subscriptions_enqueues_nothing(wired):
    dispatcher, _subscriptions, outbox = wired

    outcome = dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert outcome.enqueued == 0
    assert outcome.considered == 0
    assert outcome.lookup_failed is False
    assert outcome.failed_before_enqueue is False
    assert outbox.pending_count(ORG) == 0


def test_a_paused_subscription_is_not_enqueued_for(wired):
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions, active=False)

    assert dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {}).enqueued == 0
    assert outbox.pending_count(ORG) == 0


def test_a_subscription_for_another_event_is_not_enqueued_for(wired):
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions, events=(Webhook_Event.DOCUMENT_INGESTED,))

    assert dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {}).enqueued == 0
    assert outbox.pending_count(ORG) == 0


def test_another_organizations_subscription_never_receives_this_orgs_event(wired):
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions, org=OTHER_ORG)

    assert dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {}).enqueued == 0
    assert outbox.pending_count(OTHER_ORG) == 0


# --- fan-out ----------------------------------------------------------------------


def test_one_durable_row_is_written_per_interested_subscription(wired):
    dispatcher, subscriptions, outbox = wired
    first = _subscribe(subscriptions)
    second = _subscribe(subscriptions)

    outcome = dispatcher.dispatch(
        ORG, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}, idempotency_key="run.completed:r1"
    )

    assert outcome.enqueued == 2
    assert outcome.considered == 2
    rows = outbox.list_for_org(ORG)
    assert {r.subscription_id for r in rows} == {first.id, second.id}
    assert all(r.status == "pending" for r in rows)
    assert all(r.payload == {"run_id": "r1"} for r in rows)


def test_the_idempotency_key_is_scoped_per_subscription(wired):
    """Two endpoints on the same event are two independent deliveries.

    A shared key would let one consumer's deduplication be defeated by a sibling endpoint — and
    would make a redelivery to one endpoint look like a repeat to the other.
    """
    dispatcher, subscriptions, outbox = wired
    first = _subscribe(subscriptions)
    second = _subscribe(subscriptions)

    dispatcher.dispatch(
        ORG, Webhook_Event.RUN_COMPLETED, {}, idempotency_key="run.completed:r1"
    )

    keys = {r.subscription_id: r.idempotency_key for r in outbox.list_for_org(ORG)}
    assert keys[first.id] == f"run.completed:r1:{first.id}"
    assert keys[second.id] == f"run.completed:r1:{second.id}"
    assert keys[first.id] != keys[second.id]


def test_an_event_without_a_key_stores_none_rather_than_a_fabricated_one(wired):
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions, events=(Webhook_Event.GUARDRAIL_BLOCKED,))

    dispatcher.dispatch(ORG, Webhook_Event.GUARDRAIL_BLOCKED, {"surface": "query"})

    assert outbox.list_for_org(ORG)[0].idempotency_key is None


def test_each_row_gets_its_own_delivery_id(wired):
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions)
    _subscribe(subscriptions)

    dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {})

    rows = outbox.list_for_org(ORG)
    assert len({r.id for r in rows}) == 2


def test_dispatching_does_not_dial_anything(wired):
    """The point of the split: enqueueing is bounded work that cannot wait on a consumer."""
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions)

    # No transport is wired into the dispatcher at all — there is nothing it could call.
    assert not hasattr(dispatcher, "_transport")
    assert not hasattr(dispatcher, "_emitter")
    dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {})
    assert outbox.pending_count(ORG) == 1


# --- failure reporting ------------------------------------------------------------


def test_a_subscription_lookup_failure_is_reported_as_a_failure_not_an_absence(wired):
    """The distinction a caller needs: "nobody listening" vs "could not find out"."""
    dispatcher, _subscriptions, _outbox = wired

    class _Broken:
        def list_for_event(self, org_id, event):
            raise RuntimeError("store down")

    dispatcher._subscriptions = _Broken()
    outcome = dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {})

    assert outcome.lookup_failed is True
    assert outcome.failed_before_enqueue is True
    assert outcome.enqueued == 0


def test_one_failed_enqueue_does_not_cost_the_other_subscriptions_theirs(wired):
    dispatcher, subscriptions, outbox = wired
    _subscribe(subscriptions)
    _subscribe(subscriptions)
    real_enqueue = outbox.enqueue
    calls = {"n": 0}

    def _fail_first(entry):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("insert failed")
        return real_enqueue(entry)

    outbox.enqueue = _fail_first
    outcome = dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {})

    assert outcome.considered == 2
    assert outcome.enqueued == 1
    # Reported as retryable, because one subscription's event was genuinely not written.
    assert outcome.failed_before_enqueue is True


def test_dispatch_never_raises_even_when_everything_is_broken(wired):
    dispatcher, _subscriptions, _outbox = wired

    class _Broken:
        def list_for_event(self, org_id, event):
            raise RuntimeError("store down")

    dispatcher._subscriptions = _Broken()
    dispatcher._outbox = None  # would explode if it were reached
    assert dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {}).enqueued == 0


# --- the inert dispatcher ---------------------------------------------------------


def test_the_disabled_dispatcher_enqueues_nothing_and_is_shared():
    dispatcher = disabled_webhook_dispatcher()
    assert dispatcher is disabled_webhook_dispatcher()
    assert dispatcher.dispatch(ORG, Webhook_Event.RUN_COMPLETED, {"run_id": "r"}).enqueued == 0
