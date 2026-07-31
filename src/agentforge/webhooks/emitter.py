"""Webhook_Emitter — match subscriptions, sign, deliver with bounded retries, record.

The application service every emission point calls. Its contract is short and absolute:

* **It never raises.** An emission point is a *finished* piece of work (a run that completed, a
  document that was ingested), so a webhook problem cannot be allowed to turn a success into a
  failure. Every failure is recorded in the delivery log and logged, never propagated.
* **It costs nothing when nobody is listening.** With no matching subscription it returns after
  one indexed store read, so the overwhelming common case — no webhooks configured — adds no
  work per run.
* **It is called off the request path.** The routers attach it as a FastAPI background task or
  after a stream's terminal frame, exactly as trace export is attached. Nothing here is safe to
  run inline: a delivery involves the open internet.
* **Every attempt is accounted for.** One delivery row per (event, subscription), carrying the
  attempt count, the endpoint's status, a bounded diagnostic and the duration — which is what
  an operator debugging a flaky consumer actually reads.

Retry policy: up to ``max_attempts`` attempts with exponential backoff, all bounded so a
pathological endpoint cannot hold a worker thread indefinitely. Retries happen **in process**;
there is no durable queue, so a process restart mid-delivery loses that attempt (the delivery
log records what was attempted). That bound is documented rather than disguised — a durable
queue is a different piece of infrastructure, and pretending to have one would be worse than
saying so.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from agentforge.webhooks.base import (
    Webhook_Delivery,
    Webhook_Delivery_Store,
    Webhook_Event,
    Webhook_Subscription,
    Webhook_Subscription_Store,
    Webhook_Transport,
)
from agentforge.webhooks.security import sign_payload

logger = logging.getLogger(__name__)

#: Header names, fixed here so the docs, the tests and the wire agree.
SIGNATURE_HEADER = "X-AgentForge-Signature"
EVENT_HEADER = "X-AgentForge-Event"
DELIVERY_HEADER = "X-AgentForge-Delivery"
SUBSCRIPTION_HEADER = "X-AgentForge-Webhook-Id"

USER_AGENT = "AgentForge-Webhooks/1"


class Webhook_Emitter:
    """Delivers org-scoped events to the subscriptions that asked for them."""

    def __init__(
        self,
        subscriptions: Webhook_Subscription_Store,
        deliveries: Webhook_Delivery_Store,
        transport: Webhook_Transport,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 4.0,
        backoff_seconds: float = 0.5,
        sleep=time.sleep,
    ) -> None:
        self._subscriptions = subscriptions
        self._deliveries = deliveries
        self._transport = transport
        self._max_attempts = max(1, max_attempts)
        self._timeout_seconds = timeout_seconds
        self._backoff_seconds = backoff_seconds
        # Injectable so retry behaviour is testable without spending real seconds.
        self._sleep = sleep

    # --- emission ------------------------------------------------------------------
    def emit(
        self, org_id: UUID, event: Webhook_Event, data: dict[str, Any]
    ) -> list[Webhook_Delivery]:
        """Deliver ``event`` to every active subscription of ``org_id`` that wants it.

        Returns the recorded deliveries (empty when nobody subscribed), so a caller or a test
        can assert on the outcome without catching anything. Never raises.
        """
        try:
            matching = self._subscriptions.list_for_event(org_id, event.value)
        except Exception:  # noqa: BLE001 - a webhook lookup must not fail finished work
            logger.warning(
                "Could not load webhook subscriptions for org %s; skipping %s.",
                org_id,
                event.value,
                exc_info=True,
            )
            return []

        recorded: list[Webhook_Delivery] = []
        for subscription in matching:
            delivery = self._deliver(subscription, event, data)
            if delivery is not None:
                recorded.append(delivery)
        return recorded

    def send_to(
        self,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, Any],
        *,
        max_attempts: int | None = None,
    ) -> Webhook_Delivery | None:
        """Deliver one event to one subscription, bypassing matching.

        Used by ``POST /webhooks/{id}/test``: a consumer needs to verify signature handling
        before real traffic arrives, and making them wait for a real event to occur is a poor
        way to find out their verification is wrong. Ignores ``active`` and the event list for
        the same reason — it is an explicit, addressed request.

        ``max_attempts`` overrides the retry budget. The test endpoint passes ``1``: it is
        synchronous, so the response time must be bounded by one timeout rather than by the
        whole backoff schedule, and retrying would only paper over the very failure the caller
        asked to see.
        """
        return self._deliver(subscription, event, data, max_attempts=max_attempts)

    # --- one subscription ----------------------------------------------------------
    def _deliver(
        self,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, Any],
        *,
        max_attempts: int | None = None,
    ) -> Webhook_Delivery | None:
        budget = self._max_attempts if max_attempts is None else max(1, max_attempts)
        delivery_id = uuid.uuid4()
        try:
            body = self._render(delivery_id, subscription, event, data)
        except (TypeError, ValueError):
            # A non-serialisable payload is a programming error at the emission point, not a
            # delivery failure. Logged loudly; nothing is sent, and no misleading "failed"
            # delivery row is written for the consumer to chase.
            logger.error(
                "Webhook payload for %s is not JSON-serialisable; nothing was sent.",
                event.value,
                exc_info=True,
            )
            return None

        started = time.monotonic()
        result = None
        attempts = 0
        for attempt in range(1, budget + 1):
            attempts = attempt
            timestamp = int(datetime.now(timezone.utc).timestamp())
            headers = {
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                EVENT_HEADER: event.value,
                DELIVERY_HEADER: str(delivery_id),
                SUBSCRIPTION_HEADER: str(subscription.id),
                SIGNATURE_HEADER: sign_payload(subscription.secret, body, timestamp),
            }
            try:
                result = self._transport.post(
                    subscription.url,
                    body=body,
                    headers=headers,
                    timeout_seconds=self._timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - a transport must not raise; belt and braces
                result = None
                logger.warning(
                    "Webhook transport raised for subscription %s: %s",
                    subscription.id,
                    exc,
                    exc_info=True,
                )
            if result is not None and result.ok:
                break
            if attempt < budget:
                # Exponential, bounded: 0.5s, 1.0s with the defaults. Long enough to ride out a
                # restart on the consumer's side, short enough not to occupy a worker.
                self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))

        duration_ms = int((time.monotonic() - started) * 1000)
        delivered = result is not None and result.ok
        delivery = Webhook_Delivery(
            id=delivery_id,
            org_id=subscription.org_id,
            subscription_id=subscription.id,
            event_type=event.value,
            status="delivered" if delivered else "failed",
            attempts=attempts,
            response_status=result.status if result is not None else None,
            error=None if delivered else (result.error if result is not None else "transport error"),
            duration_ms=duration_ms,
        )
        if not delivered:
            logger.warning(
                "Webhook delivery to subscription %s failed after %d attempt(s): status=%s %s",
                subscription.id,
                attempts,
                delivery.response_status,
                delivery.error or "",
            )
        try:
            return self._deliveries.record(delivery)
        except Exception:  # noqa: BLE001 - losing the log entry must not fail the emission
            logger.warning(
                "Could not record webhook delivery %s for subscription %s.",
                delivery_id,
                subscription.id,
                exc_info=True,
            )
            return delivery

    @staticmethod
    def _render(
        delivery_id: UUID,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, Any],
    ) -> bytes:
        """Serialise the delivery envelope.

        ``separators`` and ``sort_keys`` are fixed so the bytes are deterministic: the signature
        covers exactly these bytes, and a consumer that re-serialises the parsed JSON to verify
        would otherwise get a different MAC. The documented recipe is to sign the **raw body**,
        and determinism here means a consumer who does it the other way still succeeds.
        """
        envelope = {
            "id": str(delivery_id),
            "event": event.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "org_id": str(subscription.org_id),
            "webhook_id": str(subscription.id),
            "data": data,
        }
        return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
