"""Webhook_Emitter: turns a platform event into signed, logged, bounded HTTP deliveries.

The one invariant everything else here serves: **emitting can never affect the work that
triggered it.** A tenant's broken endpoint must not fail a run, slow a response, or raise
anything into a request handler. So :meth:`Webhook_Emitter.emit` never raises, every failure
becomes a row in the delivery log, and the call sites schedule it *after* the response (a
FastAPI background task, a post-stream hook, or the deferred-work seam in
``api/errors.py`` for the error paths).

The bounds, and why each one exists:

* **Attempts are bounded** (``webhook_max_attempts``, default 3) with a short exponential
  backoff. Retries exist because a consumer restart is the common failure; unbounded retries
  would turn one event into an indefinite obligation.
* **Every attempt is bounded** (``webhook_timeout_seconds``, default 4s), and the whole
  sequence is bounded again by a wall-clock deadline, so a transport that overshoots its own
  timeout cannot hold a worker past the budget.
* **One row per (event, subscription)**, recording the attempt count — not one row per HTTP
  attempt. "Did event X reach endpoint Y, and if not why" is the question; the retry count is
  a field of that answer.
* **``duration_ms`` excludes the backoff sleeps.** An operator reading it wants to know how
  slow the endpoint is, not how patient the platform was.

What this is *not*: a durable queue. Deliveries are in-process and best-effort, so a process
restart mid-delivery loses that delivery, and the retry budget is exhausted within one
request's lifetime rather than over hours. That is a deliberate scope decision — a durable
queue is different infrastructure, not a bigger loop — and it is documented in
docs/KNOWN_LIMITATIONS.md rather than implied away.
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
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SUBSCRIPTION_HEADER,
    sign_payload,
)
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
    Webhook_Delivery_Store,
    Webhook_Subscription_Store,
)

logger = logging.getLogger(__name__)

USER_AGENT: Final[str] = "AgentForge-Webhooks/1.0"

#: Wall-clock slack added to the computed budget so a transport that returns right at its
#: timeout is not cut off by the deadline check on the attempt it was allowed to make.
_DEADLINE_SLACK_SECONDS: Final[float] = 1.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Webhook_Emitter:
    """Fans one event out to an organization's matching subscriptions.

    ``sleep`` and ``clock`` are injectable so the retry behaviour is testable without waiting
    for real backoff — the alternative is a test suite that either sleeps or patches
    ``time``, and both are worse than naming the seam.
    """

    def __init__(
        self,
        subscriptions: Webhook_Subscription_Store,
        deliveries: Webhook_Delivery_Store,
        transport: Webhook_Transport,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 4.0,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._subscriptions = subscriptions
        self._deliveries = deliveries
        self._transport = transport
        self._max_attempts = max(1, int(max_attempts))
        self._timeout_seconds = float(timeout_seconds)
        self._backoff_seconds = max(0.0, float(backoff_seconds))
        self._sleep = sleep
        self._clock = clock

    # --- public API ---------------------------------------------------------------

    def emit(
        self, org_id: UUID, event: Webhook_Event, data: dict[str, object]
    ) -> list[Webhook_Delivery]:
        """Deliver ``event`` to every active subscription of ``org_id`` that wants it.

        Returns the recorded deliveries (empty when nothing is subscribed, which is the
        overwhelmingly common case and costs exactly one store read). Never raises: every
        failure — a store that is down, an unserialisable payload, a transport that misbehaves
        — is logged and swallowed, because the caller is a finished run, not a client.
        """
        try:
            subscriptions = self._subscriptions.list_for_event(org_id, event)
        except Exception:  # noqa: BLE001 - emitting must not fail the caller
            logger.warning(
                "Could not load webhook subscriptions for org %s; %s was not delivered.",
                org_id,
                event.value,
                exc_info=True,
            )
            return []

        recorded: list[Webhook_Delivery] = []
        for subscription in subscriptions:
            delivery = self.send_to(subscription, event, data)
            if delivery is not None:
                recorded.append(delivery)
        return recorded

    def send_to(
        self,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, object],
        *,
        max_attempts: int | None = None,
    ) -> Webhook_Delivery | None:
        """Deliver one event to one subscription, retrying within bounds; never raises.

        ``max_attempts`` overrides the configured budget for this call. Its one caller is the
        test-send endpoint, which answers a human waiting on an HTTP response and so makes a
        single attempt: retrying would make the caller wait out a backoff to learn something
        the first attempt already told them.

        Returns the recorded :class:`Webhook_Delivery`, or ``None`` when the attempt sequence
        could not even be constructed (an unserialisable payload — a programming error at the
        call site, logged loudly).
        """
        try:
            body, headers, delivery_id = self._render(subscription, event, data)
        except Exception:  # noqa: BLE001 - a bad payload must not reach the caller
            logger.error(
                "Could not render webhook payload for %s (subscription %s); not delivered.",
                event.value,
                subscription.id,
                exc_info=True,
            )
            return None

        attempts_allowed = self._max_attempts if max_attempts is None else max(1, max_attempts)
        result, attempts, http_seconds = self._attempt_sequence(
            subscription.url, body, headers, attempts_allowed
        )

        status: DeliveryStatus = "delivered" if result.delivered else "failed"
        delivery = Webhook_Delivery(
            id=delivery_id,
            org_id=subscription.org_id,
            subscription_id=subscription.id,
            event=event,
            status=status,
            attempts=attempts,
            response_status=result.response_status,
            error=result.error,
            duration_ms=int(http_seconds * 1000),
            created_at=_utcnow(),
        )
        if not result.delivered:
            # WARNING, not ERROR: an unreachable customer endpoint is their operational
            # problem, not the platform's fault, but it must be visible in the platform's logs
            # when they ask why nothing arrived. The URL is deliberately absent — it can carry
            # a token in its path — and the subscription id identifies it precisely.
            logger.warning(
                "Webhook %s to subscription %s failed after %d attempt(s): %s",
                event.value,
                subscription.id,
                attempts,
                result.error,
            )
        try:
            return self._deliveries.record(delivery)
        except Exception:  # noqa: BLE001 - the log is observability, not the delivery
            # Reachable in one real case: the subscription was deleted while its event was in
            # flight, so the delivery row's foreign key no longer resolves. The event was
            # still sent; only the record of it is lost, for a subscription that no longer
            # exists.
            logger.warning(
                "Could not record webhook delivery %s for subscription %s.",
                delivery_id,
                subscription.id,
                exc_info=True,
            )
            return delivery

    # --- internals ---------------------------------------------------------------

    def _attempt_sequence(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        attempts_allowed: int,
    ) -> tuple[Transport_Result, int, float]:
        """Post until delivered or out of budget; return the last result, count, HTTP time.

        The returned duration covers HTTP work only. Backoff sleeps happen between attempts
        and are excluded on purpose — see the module docstring.
        """
        budget = (
            attempts_allowed * self._timeout_seconds
            + self._total_backoff(attempts_allowed)
            + _DEADLINE_SLACK_SECONDS
        )
        started = self._clock()
        deadline = started + budget

        http_seconds = 0.0
        attempts = 0
        result = Transport_Result(
            delivered=False, response_status=None, error="no attempt was made"
        )
        for attempt in range(1, attempts_allowed + 1):
            if attempt > 1:
                if self._clock() >= deadline:
                    # A transport that overran its own timeout has consumed the budget. Stop
                    # rather than start an attempt that would push a worker past it.
                    result = Transport_Result(
                        delivered=False,
                        response_status=result.response_status,
                        error=(
                            "delivery budget exhausted after "
                            f"{attempts} attempt(s): {result.error}"
                        ),
                    )
                    break
                self._sleep(self._backoff_for(attempt))
            attempt_started = self._clock()
            result = self._post_once(url, body, headers)
            http_seconds += max(0.0, self._clock() - attempt_started)
            attempts = attempt
            if result.delivered:
                break
        return result, attempts, http_seconds

    def _post_once(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> Transport_Result:
        """One transport call, defended against a transport that breaks its no-raise contract."""
        try:
            return self._transport.post(
                url, body, headers, timeout_seconds=self._timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - see Webhook_Transport's contract
            logger.warning("Webhook transport raised; treated as a failed attempt.", exc_info=True)
            return Transport_Result(
                delivered=False,
                response_status=None,
                error=f"transport error: {type(exc).__name__}",
            )

    def _backoff_for(self, attempt: int) -> float:
        """Delay before ``attempt`` (2-based): exponential from ``backoff_seconds``."""
        return self._backoff_seconds * (2 ** (attempt - 2))

    def _total_backoff(self, attempts_allowed: int) -> float:
        return sum(self._backoff_for(a) for a in range(2, attempts_allowed + 1))

    def _render(
        self,
        subscription: Webhook_Subscription,
        event: Webhook_Event,
        data: dict[str, object],
    ) -> tuple[bytes, dict[str, str], UUID]:
        """Build the signed request body and headers for one delivery.

        The body is serialised with sorted keys and no whitespace, so it is byte-identical for
        identical input. That matters for more than tidiness: the signature is over these exact
        bytes, so a consumer must verify against the raw body it received, and a deterministic
        renderer is what makes the documented recipe reproducible in a test.
        """
        delivery_id = uuid.uuid4()
        created_at = _utcnow()
        envelope = {
            # The delivery id doubles as the idempotency key a consumer deduplicates on: every
            # retry of this event to this endpoint carries the same value.
            "id": str(delivery_id),
            "event": event.value,
            "created_at": created_at.isoformat(),
            "org_id": str(subscription.org_id),
            "data": data,
        }
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            EVENT_HEADER: event.value,
            DELIVERY_HEADER: str(delivery_id),
            SUBSCRIPTION_HEADER: str(subscription.id),
            SIGNATURE_HEADER: sign_payload(subscription.secret, body),
        }
        return body, headers, delivery_id


class _Disabled_Transport(Webhook_Transport):
    """Never dials anything; the transport of an emitter that must not deliver."""

    def post(
        self, url: str, body: bytes, headers: dict[str, str], *, timeout_seconds: float
    ) -> Transport_Result:  # pragma: no cover - never reached (no subscriptions exist)
        return Transport_Result(
            delivered=False, response_status=None, error="webhook delivery is not configured"
        )


def disabled_webhook_emitter() -> Webhook_Emitter:
    """Return a permanently inert emitter over empty in-memory stores.

    Used by the transport layer when no observability graph is wired, so a run endpoint can
    depend on an emitter unconditionally without a missing context becoming a failed run. It
    lives here rather than in ``api/deps.py`` because naming concrete implementations is this
    layer's job, not the transport layer's.

    The instance is shared and holds nothing: its subscription store is permanently empty, so
    every ``emit`` is a no-op that returns ``[]``.
    """
    return _DISABLED


_DISABLED_DELIVERIES = InMemory_Webhook_Delivery_Store()
_DISABLED = Webhook_Emitter(
    InMemory_Webhook_Subscription_Store(_DISABLED_DELIVERIES),
    _DISABLED_DELIVERIES,
    _Disabled_Transport(),
    max_attempts=1,
)
