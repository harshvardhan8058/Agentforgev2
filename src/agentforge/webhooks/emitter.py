"""Webhook_Emitter: renders, signs, performs **one** HTTP attempt, and records it.

Deliberately small, and deliberately not in charge of *when*. It knows how to turn an event into
a signed request, make a single bounded attempt, and write the result to the delivery log. What it
does not know is whether to retry, when, or how many times — that is the outbox's job
(:mod:`agentforge.webhooks.outbox`), because retry state that lives in a process is retry state
that a deploy erases.

That split is the whole point of the durable-delivery design:

* the **dispatcher** decides *who* (one durable row per interested subscription),
* the **outbox** decides *when* (an exponential schedule spanning hours, survives restarts),
* the **emitter** decides *how* (render, sign, one attempt, log it).

Two callers: the delivery worker, and the test-send endpoint — which wants exactly one attempt in
front of a human waiting on an HTTP response, and so needs nothing else this module used to do.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from agentforge.webhooks.base import (
    DeliveryStatus,
    Transport_Result,
    Webhook_Delivery,
    Webhook_Event,
    Webhook_Subscription,
    Webhook_Transport,
)
from agentforge.webhooks.security import (
    ATTEMPT_HEADER,
    DELIVERY_HEADER,
    EVENT_HEADER,
    IDEMPOTENCY_HEADER,
    SIGNATURE_HEADER,
    SUBSCRIPTION_HEADER,
    sign_payload,
)
from agentforge.webhooks.store import Webhook_Delivery_Store

logger = logging.getLogger(__name__)

USER_AGENT: Final[str] = "AgentForge-Webhooks/1.0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Webhook_Emitter:
    """Performs single, signed, logged delivery attempts. Never raises."""

    def __init__(
        self,
        deliveries: Webhook_Delivery_Store,
        transport: Webhook_Transport,
        *,
        timeout_seconds: float = 4.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._deliveries = deliveries
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)
        self._clock = clock

    # --- public API ---------------------------------------------------------------

    def deliver_once(
        self,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, object],
        *,
        delivery_id: UUID,
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> Webhook_Delivery | None:
        """Make one attempt and record it. Returns ``None`` only if the payload cannot render.

        ``delivery_id`` comes from the outbox row, so every attempt at the same event carries the
        same ``X-AgentForge-Delivery`` value and an operator reading the outbox, the delivery log,
        and the consumer's own logs is looking at one identifier.
        """
        try:
            body, headers = self._render(
                subscription,
                event,
                data,
                delivery_id=delivery_id,
                idempotency_key=idempotency_key,
                attempt=attempt,
            )
        except Exception:  # noqa: BLE001 - a bad payload must not reach the caller
            logger.error(
                "Could not render webhook payload for %s (subscription %s); not delivered.",
                event.value,
                subscription.id,
                exc_info=True,
            )
            return None

        started = self._clock()
        result = self._post_once(subscription.url, body, headers)
        elapsed = max(0.0, self._clock() - started)

        status: DeliveryStatus = "delivered" if result.delivered else "failed"
        delivery = Webhook_Delivery(
            id=delivery_id,
            org_id=subscription.org_id,
            subscription_id=subscription.id,
            event=event,
            status=status,
            attempts=attempt,
            response_status=result.response_status,
            error=result.error,
            duration_ms=int(elapsed * 1000),
            created_at=_utcnow(),
        )
        if not result.delivered:
            # WARNING, not ERROR: an unreachable customer endpoint is their operational problem,
            # but it must be visible in the platform's logs when they ask why nothing arrived. The
            # URL is deliberately absent — its path can carry a token — and the subscription id
            # identifies it precisely.
            logger.warning(
                "Webhook %s to subscription %s failed on attempt %d: %s",
                event.value,
                subscription.id,
                attempt,
                result.error,
            )
        try:
            return self._deliveries.record(delivery)
        except Exception:  # noqa: BLE001 - the log is observability, not the delivery
            logger.warning(
                "Could not record webhook delivery %s for subscription %s.",
                delivery_id,
                subscription.id,
                exc_info=True,
            )
            return delivery

    def send_test(
        self, subscription: Webhook_Subscription, data: dict[str, object]
    ) -> Webhook_Delivery | None:
        """Deliver a ``webhook.ping`` immediately, once, and report the result.

        The one delivery that is not queued, because its whole purpose is to answer an operator
        who has just pasted a URL and is waiting. Bounded to a single attempt so the response time
        is one endpoint timeout rather than a retry schedule.
        """
        return self.deliver_once(
            subscription,
            Webhook_Event.PING,
            data,
            delivery_id=uuid.uuid4(),
            idempotency_key=None,
            attempt=1,
        )

    # --- internals ----------------------------------------------------------------

    def _post_once(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> Transport_Result:
        """One transport call, defended against a transport that breaks its no-raise contract."""
        try:
            return self._transport.post(
                url, body, headers, timeout_seconds=self._timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - see Webhook_Transport's contract
            logger.warning(
                "Webhook transport raised; treated as a failed attempt.", exc_info=True
            )
            return Transport_Result(
                delivered=False,
                response_status=None,
                error=f"transport error: {type(exc).__name__}",
            )

    def _render(
        self,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, object],
        *,
        delivery_id: UUID,
        idempotency_key: str | None,
        attempt: int,
    ) -> tuple[bytes, dict[str, str]]:
        """Build the signed request body and headers for one attempt.

        The body is serialised with sorted keys and no whitespace, so it is byte-identical for
        identical input. That matters for more than tidiness: the signature is over these exact
        bytes, so a consumer must verify against the raw body it received, and a deterministic
        renderer is what makes the documented recipe reproducible in a test.

        Note that the body does **not** vary with the attempt number — a retry is byte-identical
        to its first attempt, so a consumer comparing payloads sees a repeat rather than a change.
        The attempt is carried in a header instead.
        """
        envelope = {
            "id": str(delivery_id),
            "event": event.value,
            # The moment the attempt was rendered. Inside the signature, and therefore also the
            # freshness bound a consumer checks.
            "created_at": _utcnow().isoformat(),
            "org_id": str(subscription.org_id),
            # The logical identity of the occurrence, stable across retries AND across a repeated
            # occurrence that means the same thing. `null` for events with no natural identity.
            "idempotency_key": idempotency_key,
            "data": data,
        }
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            EVENT_HEADER: event.value,
            DELIVERY_HEADER: str(delivery_id),
            SUBSCRIPTION_HEADER: str(subscription.id),
            ATTEMPT_HEADER: str(attempt),
            SIGNATURE_HEADER: sign_payload(subscription.secret, body),
        }
        if idempotency_key is not None:
            headers[IDEMPOTENCY_HEADER] = idempotency_key
        return body, headers
