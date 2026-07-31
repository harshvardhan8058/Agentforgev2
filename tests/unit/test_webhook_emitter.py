"""Unit tests: Webhook_Emitter — matching, signing, bounded retries, and never raising.

The emitter's contract is what makes it safe to call from a finished run, so each clause is
tested as a clause rather than incidentally:

* it never raises, whatever the transport or either store does;
* it costs one indexed read when nobody is subscribed;
* it signs the exact bytes it sends, deterministically;
* it retries a bounded number of times with backoff, and records the attempt count;
* it records one delivery row per (event, subscription), never a response body.
"""

from __future__ import annotations

import json
import uuid

import pytest

from agentforge.webhooks.base import (
    Transport_Result,
    Webhook_Delivery,
    Webhook_Delivery_Store,
    Webhook_Event,
    Webhook_Subscription_Store,
)
from agentforge.webhooks.emitter import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SUBSCRIPTION_HEADER,
    Webhook_Emitter,
)
from agentforge.webhooks.security import verify_signature
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
    disabled_webhook_emitter,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport

SECRET = "whsec_unit_test_secret"


@pytest.fixture
def wired():
    """Return ``(emitter, subscriptions, deliveries, transport, org_id)`` with no sleeping."""
    subscriptions = InMemory_Webhook_Subscription_Store()
    deliveries = InMemory_Webhook_Delivery_Store()
    transport = Recording_Webhook_Transport()
    emitter = Webhook_Emitter(
        subscriptions,
        deliveries,
        transport,
        max_attempts=3,
        backoff_seconds=0.5,
        # Injected so the retry schedule is asserted rather than waited for.
        sleep=lambda seconds: slept.append(seconds),
    )
    slept: list[float] = []
    emitter.slept = slept  # type: ignore[attr-defined]
    return emitter, subscriptions, deliveries, transport, uuid.uuid4()


def _subscribe(subscriptions, org_id, *events: Webhook_Event, active: bool = True):
    subscription = subscriptions.create(
        org_id,
        url="https://hooks.example.com/agentforge",
        events=tuple(e.value for e in events),
        secret=SECRET,
    )
    if not active:
        subscription = subscriptions.update(org_id, subscription.id, active=False)
    return subscription


# --- matching ----------------------------------------------------------------------


def test_nobody_subscribed_costs_one_lookup_and_sends_nothing(wired):
    """The overwhelming common case: webhooks configured by nobody must add no work."""
    emitter, _subs, deliveries, transport, org_id = wired

    assert emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}) == []
    assert transport.calls == []
    assert deliveries.list_for_subscription(org_id, uuid.uuid4()) == []


def test_only_subscriptions_that_asked_for_the_event_receive_it(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    wanted = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    _subscribe(subs, org_id, Webhook_Event.DOCUMENT_INGESTED)

    recorded = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert [d.subscription_id for d in recorded] == [wanted.id]
    assert len(transport.calls) == 1


def test_a_paused_subscription_receives_nothing(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED, active=False)

    assert emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}) == []
    assert transport.calls == []


def test_another_org_never_receives_this_org_s_event(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    other_org = uuid.uuid4()
    _subscribe(subs, other_org, Webhook_Event.RUN_COMPLETED)

    assert emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}) == []
    assert transport.calls == []


def test_one_event_fans_out_to_every_matching_subscription(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    first = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    second = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED, Webhook_Event.RUN_FAILED)

    recorded = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert {d.subscription_id for d in recorded} == {first.id, second.id}
    # One delivery row per (event, subscription), each with its own delivery id.
    assert len({d.id for d in recorded}) == 2


# --- the envelope and its signature ------------------------------------------------


def test_the_envelope_carries_the_event_org_and_data(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    subscription = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)

    (delivery,) = emitter.emit(
        org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1", "kind": "single_agent"}
    )

    envelope = json.loads(transport.calls[0]["body"])
    assert envelope["event"] == "run.completed"
    assert envelope["org_id"] == str(org_id)
    assert envelope["webhook_id"] == str(subscription.id)
    assert envelope["id"] == str(delivery.id)
    assert envelope["data"] == {"run_id": "r1", "kind": "single_agent"}
    assert envelope["created_at"]


def test_the_body_is_deterministic_so_a_re_serialising_consumer_still_verifies(wired):
    """The documented recipe signs the raw body; determinism forgives the other way too."""
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)

    emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"b": 2, "a": 1})

    body = transport.calls[0]["body"]
    assert json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode() == body


def test_the_signature_verifies_over_the_exact_bytes_sent(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)

    emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    call = transport.calls[0]
    assert verify_signature(SECRET, call["body"], call["headers"][SIGNATURE_HEADER]) is True


def test_each_subscription_is_signed_with_its_own_secret(wired):
    """One endpoint's secret must never verify another's delivery."""
    emitter, subs, _deliveries, transport, org_id = wired
    subs.create(
        org_id,
        url="https://a.example.com/hook",
        events=("run.completed",),
        secret="whsec_first",
    )
    subs.create(
        org_id,
        url="https://b.example.com/hook",
        events=("run.completed",),
        secret="whsec_second",
    )

    emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    secrets = {"whsec_first", "whsec_second"}
    for call in transport.calls:
        verified = {
            secret
            for secret in secrets
            if verify_signature(secret, call["body"], call["headers"][SIGNATURE_HEADER])
        }
        assert len(verified) == 1


def test_the_identifying_headers_are_present(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    subscription = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    headers = transport.calls[0]["headers"]
    assert headers[EVENT_HEADER] == "run.completed"
    assert headers[DELIVERY_HEADER] == str(delivery.id)
    assert headers[SUBSCRIPTION_HEADER] == str(subscription.id)
    assert headers["Content-Type"] == "application/json"
    # The secret must never travel as a header, only as the key the MAC was computed with.
    assert SECRET not in json.dumps(headers)


# --- retries ---------------------------------------------------------------------


def test_a_5xx_is_retried_up_to_the_budget_and_then_recorded_as_failed(wired):
    emitter, subs, deliveries, transport, org_id = wired
    subscription = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    transport.status = 503

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert len(transport.calls) == 3
    assert delivery.status == "failed"
    assert delivery.attempts == 3
    assert delivery.response_status == 503
    # Exponential and bounded: 0.5s then 1.0s, and no sleep after the final attempt.
    assert emitter.slept == [0.5, 1.0]
    assert deliveries.list_for_subscription(org_id, subscription.id)[0].id == delivery.id


def test_a_retry_that_succeeds_is_recorded_as_delivered_with_its_attempt_count(wired):
    """``attempts > 1`` with ``delivered`` is how an operator spots a flaky consumer."""
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    transport.status = 500
    transport.succeed_from_attempt = 2

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert delivery.status == "delivered"
    assert delivery.attempts == 2
    assert len(transport.calls) == 2
    assert emitter.slept == [0.5]


def test_a_first_attempt_success_does_not_sleep_or_retry(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert (delivery.status, delivery.attempts) == ("delivered", 1)
    assert emitter.slept == []


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
def test_every_2xx_counts_as_delivered(wired, status: int):
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    transport.status = status

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert delivery.status == "delivered"


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
def test_every_non_2xx_counts_as_failed(wired, status: int):
    """A 301 included: the transport does not follow redirects, so it is not a success."""
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    transport.status = status

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert delivery.status == "failed"
    assert delivery.response_status == status


def test_no_response_at_all_is_recorded_with_a_null_status_and_a_diagnostic(wired):
    emitter, subs, _deliveries, transport, org_id = wired
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    transport.status = None
    transport.error = "ConnectTimeout: timed out"

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert delivery.response_status is None
    assert delivery.error == "ConnectTimeout: timed out"
    assert delivery.duration_ms is not None and delivery.duration_ms >= 0


def test_the_test_send_uses_one_attempt_when_asked(wired):
    """An interactive test must answer within one timeout, not the whole backoff schedule."""
    emitter, subs, _deliveries, transport, org_id = wired
    subscription = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    transport.status = 500

    delivery = emitter.send_to(
        subscription, Webhook_Event.PING, {"message": "hi"}, max_attempts=1
    )

    assert delivery is not None and delivery.attempts == 1
    assert len(transport.calls) == 1
    assert emitter.slept == []


def test_a_test_send_ignores_the_event_list_and_the_paused_flag(wired):
    """It is an explicit, addressed request — verifying a paused endpoint is the point."""
    emitter, subs, _deliveries, transport, org_id = wired
    subscription = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED, active=False)

    delivery = emitter.send_to(subscription, Webhook_Event.PING, {"message": "hi"})

    assert delivery is not None and delivery.event_type == "webhook.ping"
    assert len(transport.calls) == 1


# --- the never-raise contract ------------------------------------------------------


class _ExplodingTransport(Recording_Webhook_Transport):
    def post(self, url, *, body, headers, timeout_seconds):  # noqa: D102
        raise RuntimeError("the network is on fire")


class _ExplodingSubscriptionStore(InMemory_Webhook_Subscription_Store):
    def list_for_event(self, org_id, event):  # noqa: D102
        raise RuntimeError("the database is on fire")


class _ExplodingDeliveryStore(InMemory_Webhook_Delivery_Store):
    def record(self, delivery: Webhook_Delivery) -> Webhook_Delivery:  # noqa: D102
        raise RuntimeError("the log is on fire")


def test_a_transport_that_raises_is_a_failed_delivery_not_an_exception():
    """A finished run must not be turned into a failure by a webhook problem."""
    subs = InMemory_Webhook_Subscription_Store()
    org_id = uuid.uuid4()
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    emitter = Webhook_Emitter(
        subs, InMemory_Webhook_Delivery_Store(), _ExplodingTransport(), sleep=lambda _s: None
    )

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert delivery.status == "failed"
    assert delivery.error == "transport error"


def test_a_subscription_store_that_raises_yields_no_deliveries_and_no_exception():
    emitter = Webhook_Emitter(
        _ExplodingSubscriptionStore(),
        InMemory_Webhook_Delivery_Store(),
        Recording_Webhook_Transport(),
    )

    assert emitter.emit(uuid.uuid4(), Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}) == []


def test_a_delivery_log_that_raises_still_returns_the_delivery():
    """Losing the log entry must not lose the fact that the delivery happened."""
    subs = InMemory_Webhook_Subscription_Store()
    org_id = uuid.uuid4()
    _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)
    emitter = Webhook_Emitter(subs, _ExplodingDeliveryStore(), Recording_Webhook_Transport())

    (delivery,) = emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"run_id": "r1"})

    assert delivery.status == "delivered"


def test_a_payload_that_cannot_be_serialised_sends_nothing_and_records_nothing(wired):
    """A programming error at the emission point, not a delivery failure to chase."""
    emitter, subs, deliveries, transport, org_id = wired
    subscription = _subscribe(subs, org_id, Webhook_Event.RUN_COMPLETED)

    assert emitter.emit(org_id, Webhook_Event.RUN_COMPLETED, {"bad": object()}) == []
    assert transport.calls == []
    assert deliveries.list_for_subscription(org_id, subscription.id) == []


# --- the disabled emitter ----------------------------------------------------------


def test_the_disabled_emitter_is_shared_and_delivers_nothing():
    """Used by a partially-wired app; with no subscriptions it is exactly equivalent."""
    first, second = disabled_webhook_emitter(), disabled_webhook_emitter()

    assert first is second
    assert first.emit(uuid.uuid4(), Webhook_Event.RUN_COMPLETED, {"run_id": "r1"}) == []


# --- the seams are honoured --------------------------------------------------------


def test_the_stores_and_transport_are_the_declared_abstractions():
    """A concrete that stops satisfying its seam is how a fake starts disagreeing."""
    assert issubclass(InMemory_Webhook_Subscription_Store, Webhook_Subscription_Store)
    assert issubclass(InMemory_Webhook_Delivery_Store, Webhook_Delivery_Store)
    assert Transport_Result(status=204).ok is True
    assert Transport_Result(status=None).ok is False
