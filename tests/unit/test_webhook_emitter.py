"""Unit tests for the Webhook_Emitter: render, sign, one attempt, log it.

The emitter is deliberately small since delivery became durable — it no longer decides *when*, so
there is no retry loop, backoff, or deadline here to test. What it must get exactly right is the
signed request: byte-identical bodies for identical input, a signature a consumer can verify, the
headers the contract promises, and the absolute rule that nothing it does can raise into a caller.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from agentforge.webhooks.base import (
    Transport_Result,
    Webhook_Event,
    Webhook_Subscription,
    Webhook_Transport,
)
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.security import (
    ATTEMPT_HEADER,
    DELIVERY_HEADER,
    EVENT_HEADER,
    IDEMPOTENCY_HEADER,
    SIGNATURE_HEADER,
    SUBSCRIPTION_HEADER,
    verify_signature,
)
from agentforge.webhooks.store import InMemory_Webhook_Delivery_Store
from agentforge.webhooks.transport import Recording_Webhook_Transport

ORG = uuid.uuid4()


def _subscription(**overrides) -> Webhook_Subscription:
    now = datetime.now(timezone.utc)
    return Webhook_Subscription(
        id=overrides.get("id", uuid.uuid4()),
        org_id=overrides.get("org_id", ORG),
        url=overrides.get("url", "https://hooks.example.com/h"),
        secret=overrides.get("secret", "s3cret-signing-key"),
        events=overrides.get("events", (Webhook_Event.RUN_COMPLETED,)),
        description=None,
        active=overrides.get("active", True),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def wired():
    """Return ``(emitter, deliveries, transport)``."""
    deliveries = InMemory_Webhook_Delivery_Store()
    transport = Recording_Webhook_Transport()
    ticks = iter(range(0, 10_000))
    emitter = Webhook_Emitter(
        deliveries, transport, timeout_seconds=4.0, clock=lambda: float(next(ticks))
    )
    return emitter, deliveries, transport


# --- a delivered attempt ----------------------------------------------------------


def test_a_delivered_attempt_is_signed_logged_and_reported(wired):
    emitter, deliveries, transport = wired
    subscription = _subscription()
    delivery_id = uuid.uuid4()

    delivery = emitter.deliver_once(
        subscription,
        Webhook_Event.RUN_COMPLETED,
        {"run_id": "r1"},
        delivery_id=delivery_id,
        idempotency_key="run.completed:r1",
        attempt=1,
    )

    assert delivery.status == "delivered"
    assert delivery.id == delivery_id
    assert delivery.attempts == 1
    assert delivery.response_status == 200
    assert delivery.error is None

    url, body, headers = transport.calls[0]
    assert url == subscription.url
    assert headers[EVENT_HEADER] == "run.completed"
    assert headers[DELIVERY_HEADER] == str(delivery_id)
    assert headers[SUBSCRIPTION_HEADER] == str(subscription.id)
    assert headers[ATTEMPT_HEADER] == "1"
    assert headers[IDEMPOTENCY_HEADER] == "run.completed:r1"
    assert verify_signature(subscription.secret, body, headers[SIGNATURE_HEADER])

    envelope = json.loads(body)
    assert envelope["id"] == str(delivery_id)
    assert envelope["event"] == "run.completed"
    assert envelope["org_id"] == str(ORG)
    assert envelope["idempotency_key"] == "run.completed:r1"
    assert envelope["data"] == {"run_id": "r1"}

    # The attempt is in the delivery log, keyed to the same id the consumer saw.
    assert [d.id for d in deliveries.list_for_subscription(ORG, subscription.id)] == [
        delivery_id
    ]


def test_the_delivery_id_is_the_outbox_row_id_not_a_fresh_one(wired):
    """One identifier across the outbox, the delivery log, and the consumer's own records."""
    emitter, _deliveries, transport = wired
    subscription = _subscription()
    row_id = uuid.uuid4()

    for attempt in (1, 2, 3):
        emitter.deliver_once(
            subscription,
            Webhook_Event.RUN_FAILED,
            {},
            delivery_id=row_id,
            attempt=attempt,
        )

    assert {h[DELIVERY_HEADER] for _u, _b, h in transport.calls} == {str(row_id)}
    assert [h[ATTEMPT_HEADER] for _u, _b, h in transport.calls] == ["1", "2", "3"]


def test_a_retry_is_byte_identical_to_its_first_attempt(wired):
    """So a consumer comparing payloads sees a repeat, not a change. The attempt is a header."""
    emitter, _deliveries, transport = wired
    subscription = _subscription()
    row_id = uuid.uuid4()

    emitter.deliver_once(
        subscription, Webhook_Event.RUN_COMPLETED, {"a": 1}, delivery_id=row_id, attempt=1
    )
    emitter.deliver_once(
        subscription, Webhook_Event.RUN_COMPLETED, {"a": 1}, delivery_id=row_id, attempt=2
    )

    first, second = json.loads(transport.calls[0][1]), json.loads(transport.calls[1][1])
    # `created_at` is per-attempt (it is inside the signature's freshness window), so compare the
    # parts a consumer would treat as the payload's identity.
    for envelope in (first, second):
        envelope.pop("created_at")
    assert first == second


def test_the_body_is_canonical_so_the_signature_is_reproducible(wired):
    emitter, _deliveries, transport = wired
    subscription = _subscription()

    emitter.deliver_once(
        subscription,
        Webhook_Event.RUN_COMPLETED,
        {"b": 2, "a": 1},
        delivery_id=uuid.uuid4(),
    )

    body = transport.calls[0][1]
    assert body.startswith(b'{"created_at":')  # sorted keys, no whitespace
    assert b'"data":{"a":1,"b":2}' in body


def test_an_event_without_a_natural_identity_omits_the_idempotency_header(wired):
    """A guardrail block is a fact about a moment; a fabricated key would invite bad dedup."""
    emitter, _deliveries, transport = wired

    emitter.deliver_once(
        _subscription(),
        Webhook_Event.GUARDRAIL_BLOCKED,
        {"surface": "query", "reason": "blocked term"},
        delivery_id=uuid.uuid4(),
        idempotency_key=None,
    )

    _url, body, headers = transport.calls[0]
    assert IDEMPOTENCY_HEADER not in headers
    assert json.loads(body)["idempotency_key"] is None


# --- a failed attempt -------------------------------------------------------------


def test_a_non_2xx_is_recorded_as_a_failed_attempt(wired):
    emitter, deliveries, _transport = wired
    subscription = _subscription()
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    delivery = emitter.deliver_once(
        subscription, Webhook_Event.RUN_COMPLETED, {}, delivery_id=uuid.uuid4(), attempt=2
    )

    assert delivery.status == "failed"
    assert delivery.attempts == 2
    assert delivery.response_status == 500
    assert "500" in delivery.error
    assert len(deliveries.list_for_subscription(ORG, subscription.id)) == 1


def test_a_transport_that_raises_is_treated_as_a_failed_attempt(wired):
    """The seam's contract says never raise; the emitter does not rely on that."""
    emitter, _deliveries, _transport = wired

    class _Exploding(Webhook_Transport):
        def post(self, url, body, headers, *, timeout_seconds):
            raise RuntimeError("boom")

    emitter._transport = _Exploding()
    delivery = emitter.deliver_once(
        _subscription(), Webhook_Event.RUN_COMPLETED, {}, delivery_id=uuid.uuid4()
    )

    assert delivery.status == "failed"
    assert "RuntimeError" in delivery.error


def test_a_failed_attempt_is_logged_without_the_url(wired, caplog):
    """A URL's path can be the credential, so the log names the subscription id instead."""
    import logging

    emitter, _deliveries, _transport = wired
    subscription = _subscription()
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    with caplog.at_level(logging.WARNING, logger="agentforge.webhooks.emitter"):
        emitter.deliver_once(
            subscription, Webhook_Event.RUN_COMPLETED, {}, delivery_id=uuid.uuid4()
        )

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert str(subscription.id) in messages
    assert subscription.url not in messages


def test_an_unserialisable_payload_reports_no_delivery(wired):
    emitter, _deliveries, transport = wired

    assert (
        emitter.deliver_once(
            _subscription(),
            Webhook_Event.RUN_COMPLETED,
            {"bad": object()},
            delivery_id=uuid.uuid4(),
        )
        is None
    )
    assert transport.attempts == 0


def test_a_delivery_log_failure_does_not_reach_the_caller(wired):
    """The subscription was deleted mid-flight: the event was sent, the record is lost."""
    emitter, _deliveries, _transport = wired

    class _BrokenLog:
        def record(self, delivery):
            raise RuntimeError("foreign key violated")

    emitter._deliveries = _BrokenLog()
    delivery = emitter.deliver_once(
        _subscription(), Webhook_Event.RUN_COMPLETED, {}, delivery_id=uuid.uuid4()
    )
    assert delivery.status == "delivered"


def test_the_recorded_duration_is_the_attempt_not_the_schedule(wired):
    """One attempt, one duration: the waiting between attempts is the outbox's business now."""
    emitter, _deliveries, _transport = wired
    delivery = emitter.deliver_once(
        _subscription(), Webhook_Event.RUN_COMPLETED, {}, delivery_id=uuid.uuid4()
    )
    assert delivery.duration_ms == 1_000  # the injected clock ticks once per call


# --- test sends -------------------------------------------------------------------


def test_send_test_delivers_a_ping_once_with_a_fresh_id(wired):
    emitter, _deliveries, transport = wired
    subscription = _subscription()

    delivery = emitter.send_test(subscription, {"message": "hello"})

    assert delivery.event is Webhook_Event.PING
    assert delivery.attempts == 1
    assert transport.attempts == 1
    envelope = json.loads(transport.calls[0][1])
    assert envelope["event"] == "webhook.ping"
    assert envelope["id"] == str(delivery.id)
    # Not a queued event, so it has no logical identity to deduplicate on.
    assert envelope["idempotency_key"] is None


def test_send_test_reports_a_failure_as_data(wired):
    emitter, _deliveries, _transport = wired
    emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    delivery = emitter.send_test(_subscription(), {})

    assert delivery.status == "failed"
    assert delivery.attempts == 1
