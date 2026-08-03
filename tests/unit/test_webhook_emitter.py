"""Unit tests for the Webhook_Emitter: bounds, retries, logging, and the no-raise contract.

The invariant under test throughout is that emitting can never affect the caller. Every failure
mode a tenant's endpoint can produce — 500s, a transport that raises, a store that is down, a
payload that cannot be serialised — must end as a logged row, not an exception.
"""

from __future__ import annotations

import json
import uuid

import pytest

from agentforge.webhooks.base import (
    Transport_Result,
    Webhook_Event,
    Webhook_Transport,
)
from agentforge.webhooks.emitter import Webhook_Emitter, disabled_webhook_emitter
from agentforge.webhooks.security import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SUBSCRIPTION_HEADER,
    verify_signature,
)
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()


@pytest.fixture
def wired():
    """Return ``(emitter, subscriptions, deliveries, transport, slept)``.

    ``slept`` records every backoff duration, so retry timing is asserted rather than waited
    for; ``clock`` is a monotonic counter so ``duration_ms`` is deterministic.
    """
    deliveries = InMemory_Webhook_Delivery_Store()
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    transport = Recording_Webhook_Transport()
    slept: list[float] = []
    ticks = iter(range(0, 10_000))
    emitter = Webhook_Emitter(
        subscriptions,
        deliveries,
        transport,
        max_attempts=3,
        timeout_seconds=4.0,
        backoff_seconds=0.5,
        sleep=slept.append,
        clock=lambda: float(next(ticks)),
    )
    return emitter, subscriptions, deliveries, transport, slept


def _subscribe(subscriptions, *, events=(Webhook_Event.RUN_COMPLETED,), active=True, org=ORG):
    return subscriptions.create(
        org,
        url="https://hooks.example.com/h",
        secret="s3cret-signing-key",
        events=tuple(events),
        description=None,
        active=active,
    )


# --- the common case: nobody is listening -----------------------------------------


def test_emitting_with_no_subscriptions_is_a_no_op(wired):
    emitter, _subs, deliveries, transport, _slept = wired
    assert emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}) == []
    assert transport.attempts == 0
    assert deliveries.list_for_subscription(ORG, uuid.uuid4()) == []


def test_a_paused_subscription_receives_nothing(wired):
    emitter, subs, _deliveries, transport, _slept = wired
    _subscribe(subs, active=False)
    assert emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {}) == []
    assert transport.attempts == 0


def test_a_subscription_for_another_event_receives_nothing(wired):
    emitter, subs, _deliveries, transport, _slept = wired
    _subscribe(subs, events=(Webhook_Event.DOCUMENT_INGESTED,))
    assert emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {}) == []
    assert transport.attempts == 0


def test_another_organizations_subscription_never_receives_this_orgs_event(wired):
    emitter, subs, _deliveries, transport, _slept = wired
    _subscribe(subs, org=OTHER_ORG)
    assert emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {}) == []
    assert transport.attempts == 0


# --- delivery, signing, and the envelope ------------------------------------------


def test_a_delivered_event_is_signed_and_logged(wired):
    emitter, subs, deliveries, transport, _slept = wired
    subscription = _subscribe(subs)

    recorded = emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert len(recorded) == 1
    assert recorded[0].status == "delivered"
    assert recorded[0].attempts == 1
    assert recorded[0].response_status == 200
    assert recorded[0].error is None

    url, body, headers = transport.calls[0]
    assert url == subscription.url
    assert headers[EVENT_HEADER] == "run.completed"
    assert headers[SUBSCRIPTION_HEADER] == str(subscription.id)
    assert headers[DELIVERY_HEADER] == str(recorded[0].id)
    assert verify_signature(subscription.secret, body, headers[SIGNATURE_HEADER])

    envelope = json.loads(body)
    assert envelope["event"] == "run.completed"
    assert envelope["org_id"] == str(ORG)
    assert envelope["data"] == {"run_id": "r1"}
    # The delivery id doubles as the consumer's idempotency key.
    assert envelope["id"] == str(recorded[0].id)

    logged = deliveries.list_for_subscription(ORG, subscription.id)
    assert [d.id for d in logged] == [recorded[0].id]


def test_the_rendered_body_is_deterministic_for_identical_input(wired):
    """Byte-identical bodies matter: the signature is over these exact bytes."""
    emitter, subs, _deliveries, transport, _slept = wired
    _subscribe(subs)
    data = {"b": 2, "a": 1, "nested": {"z": 1, "y": 2}}
    emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, data)
    emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, dict(reversed(list(data.items()))))
    first = json.loads(transport.calls[0][1])
    second = json.loads(transport.calls[1][1])
    first.pop("id"), second.pop("id")
    first.pop("created_at"), second.pop("created_at")
    assert first == second
    # And the serialisation itself is canonical (sorted, no whitespace).
    assert transport.calls[0][1].startswith(b'{"created_at":')


def test_every_matching_subscription_receives_the_event(wired):
    emitter, subs, _deliveries, transport, _slept = wired
    _subscribe(subs)
    _subscribe(subs)
    recorded = emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {})
    assert len(recorded) == 2
    assert transport.attempts == 2
    # Each subscription gets its own delivery id, so a consumer can dedupe per endpoint.
    assert len({d.id for d in recorded}) == 2


# --- retries and bounds -----------------------------------------------------------


def test_a_transient_failure_is_retried_and_then_succeeds(wired):
    emitter, subs, _deliveries, _transport, slept = wired
    subscription = _subscribe(subs)
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=2)

    delivery = emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})

    assert delivery.status == "delivered"
    assert delivery.attempts == 2
    assert slept == [0.5]


def test_retries_are_bounded_and_the_failure_is_recorded(wired):
    emitter, subs, deliveries, _transport, slept = wired
    subscription = _subscribe(subs)
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    delivery = emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})

    assert delivery.status == "failed"
    assert delivery.attempts == 3  # the configured max, not one more
    assert delivery.response_status == 500
    assert "500" in delivery.error
    # Exponential from the configured base: 0.5 then 1.0.
    assert slept == [0.5, 1.0]
    assert len(deliveries.list_for_subscription(ORG, subscription.id)) == 1


def test_a_retried_delivery_reuses_one_delivery_id(wired):
    """Retries of the same event carry one id, which is what makes it an idempotency key."""
    emitter, subs, _deliveries, _transport, _slept = wired
    subscription = _subscribe(subs)
    transport = Recording_Webhook_Transport(succeed_from_attempt=3)
    emitter._transport = transport

    delivery = emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})

    ids = {headers[DELIVERY_HEADER] for _url, _body, headers in transport.calls}
    assert ids == {str(delivery.id)}


def test_max_attempts_can_be_overridden_for_a_single_send(wired):
    """The test-send endpoint's single attempt: a human is waiting on the response."""
    emitter, subs, _deliveries, _slept_transport, slept = wired
    subscription = _subscribe(subs)
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    delivery = emitter.send_to(
        subscription, Webhook_Event.PING, {}, max_attempts=1
    )

    assert delivery.attempts == 1
    assert delivery.status == "failed"
    assert slept == []  # no backoff was waited out


def test_the_recorded_duration_excludes_the_backoff_sleeps(wired):
    """``duration_ms`` answers "how slow is this endpoint", not "how patient were we"."""
    emitter, subs, _deliveries, _transport, slept = wired
    subscription = _subscribe(subs)
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)
    # The injected clock ticks once per call; three attempts cost 3 ticks of HTTP time even
    # though 1.5s of backoff was "slept".
    delivery = emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})
    assert sum(slept) == 1.5
    assert delivery.duration_ms == 3_000


def test_a_transport_that_raises_is_treated_as_a_failed_attempt(wired):
    """The seam's contract says never raise; the emitter does not rely on that."""
    emitter, subs, _deliveries, _transport, _slept = wired
    subscription = _subscribe(subs)

    class _Exploding(Webhook_Transport):
        def post(self, url, body, headers, *, timeout_seconds):
            raise RuntimeError("boom")

    emitter._transport = _Exploding()
    delivery = emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})

    assert delivery.status == "failed"
    assert "RuntimeError" in delivery.error


def test_a_subscription_store_failure_does_not_reach_the_caller(wired, caplog):
    emitter, _subs, _deliveries, _transport, _slept = wired

    class _BrokenStore:
        def list_for_event(self, org_id, event):
            raise RuntimeError("store down")

    emitter._subscriptions = _BrokenStore()
    assert emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {}) == []


def test_a_delivery_log_failure_does_not_reach_the_caller(wired):
    """The subscription was deleted mid-flight: the event was sent, the record is lost."""
    emitter, subs, _deliveries, _transport, _slept = wired
    subscription = _subscribe(subs)

    class _BrokenLog:
        def record(self, delivery):
            raise RuntimeError("foreign key violated")

    emitter._deliveries = _BrokenLog()
    delivery = emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})
    assert delivery.status == "delivered"


def test_an_unserialisable_payload_is_reported_as_no_delivery(wired, caplog):
    emitter, subs, _deliveries, transport, _slept = wired
    subscription = _subscribe(subs)

    assert (
        emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {"bad": object()})
        is None
    )
    assert transport.attempts == 0


def test_a_failed_delivery_is_logged_without_the_url(wired, caplog):
    """A URL's path can be the credential, so the log names the subscription id instead."""
    import logging

    emitter, subs, _deliveries, _transport, _slept = wired
    subscription = _subscribe(subs)
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)
    with caplog.at_level(logging.WARNING, logger="agentforge.webhooks.emitter"):
        emitter.send_to(subscription, Webhook_Event.RUN_COMPLETED, {})
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert str(subscription.id) in messages
    assert subscription.url not in messages


# --- the inert emitter ------------------------------------------------------------


def test_the_disabled_emitter_delivers_nothing_and_is_shared():
    emitter = disabled_webhook_emitter()
    assert emitter is disabled_webhook_emitter()
    assert emitter.emit(ORG, Webhook_Event.RUN_COMPLETED, {"run_id": "r"}) == []
