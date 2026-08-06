"""Webhook_Dispatcher: fans an event out into durable rows, and dials nothing.

The half of delivery that runs on the request path. It resolves which subscriptions want the
event and writes one outbox row per subscription — no DNS, no TLS, no retries, no waiting on a
tenant's endpoint. The :class:`~agentforge.webhooks.worker.Webhook_Delivery_Worker` does the
dialling, later and elsewhere.

Splitting it here is what makes the guarantees available at all. Enqueueing is bounded work whose
cost does not depend on a consumer, so it is safe to do while a caller waits; delivery is
unbounded work that depends entirely on a consumer, so it must not be. Everything that used to be
uncomfortable about the emission points — a streamed connection held open for a subscriber's
timeout, a background task competing with trace export, a fan-out multiplying a request's
worst-case latency by the number of subscriptions — is a consequence of having conflated the two.

Like the emitter it replaced, this never raises. A caller is a finished run, not a client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.outbox import (
    InMemory_Webhook_Outbox,
    Outbox_Entry,
    Webhook_Outbox,
)
from agentforge.webhooks.store import (
    InMemory_Webhook_Subscription_Store,
    Webhook_Subscription_Store,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Dispatch_Outcome:
    """What happened when an event was enqueued, in enough detail to act on.

    The row list alone is not actionable, because an empty one means two opposite things: nobody
    was subscribed, or we could not find out who was. A caller that must decide whether to *try
    again later* — the budget-threshold notifier, which claims a threshold once per period — needs
    those separated. Collapsing them once silently consumed an organization's one notification.
    """

    entries: tuple[Outbox_Entry, ...]
    #: Subscriptions that matched the event.
    considered: int
    #: True when the subscription lookup itself failed, so nothing was enqueued.
    lookup_failed: bool

    @property
    def enqueued(self) -> int:
        return len(self.entries)

    @property
    def failed_before_enqueue(self) -> bool:
        """True when the fan-out could not be performed at all — always worth retrying."""
        return self.lookup_failed or self.considered > self.enqueued


class Webhook_Dispatcher:
    """Turns "this happened" into durable delivery intent, one row per interested subscription."""

    def __init__(
        self,
        subscriptions: Webhook_Subscription_Store,
        outbox: Webhook_Outbox,
    ) -> None:
        self._subscriptions = subscriptions
        self._outbox = outbox

    def dispatch(
        self,
        org_id: UUID,
        event: Webhook_Event,
        data: dict[str, object],
        *,
        idempotency_key: str | None = None,
    ) -> Dispatch_Outcome:
        """Enqueue ``event`` for every active subscription of ``org_id`` that wants it.

        Nothing is enqueued when nothing is subscribed, which is the overwhelmingly common case and
        costs exactly one indexed read. Never raises.

        ``idempotency_key`` is the *logical* identity of the occurrence, and it is the caller's to
        supply because only the caller knows it. It is stable across retries **and** across a
        repeated occurrence that means the same thing: a re-streamed multi-agent run, or a budget
        threshold re-announced after a delivery outage. A consumer that must act exactly once
        keys on this, not on the delivery id — which only ever identifies one attempt sequence.
        """
        try:
            subscriptions = self._subscriptions.list_for_event(org_id, event)
        except Exception:  # noqa: BLE001 - dispatching must not fail the caller
            logger.warning(
                "Could not load webhook subscriptions for org %s; %s was not enqueued.",
                org_id,
                event.value,
                exc_info=True,
            )
            return Dispatch_Outcome(entries=(), considered=0, lookup_failed=True)

        enqueued: list[Outbox_Entry] = []
        for subscription in subscriptions:
            entry = Outbox_Entry.new(
                org_id=org_id,
                subscription_id=subscription.id,
                event=event,
                payload=data,
                # Scoped per subscription: two endpoints subscribed to the same event are two
                # independent deliveries, and a consumer's deduplication must not be defeated by
                # a *sibling* endpoint's key colliding with its own.
                idempotency_key=(
                    f"{idempotency_key}:{subscription.id}"
                    if idempotency_key is not None
                    else None
                ),
            )
            try:
                enqueued.append(self._outbox.enqueue(entry))
            except Exception:  # noqa: BLE001
                # One subscription's row failing must not cost the others theirs.
                logger.warning(
                    "Could not enqueue %s for subscription %s.",
                    event.value,
                    subscription.id,
                    exc_info=True,
                )
        return Dispatch_Outcome(
            entries=tuple(enqueued),
            considered=len(subscriptions),
            lookup_failed=False,
        )


def disabled_webhook_dispatcher() -> Webhook_Dispatcher:
    """Return a permanently inert dispatcher over empty in-memory stores.

    Used by the transport layer when no observability graph is wired, so a run endpoint can depend
    on a dispatcher unconditionally without a missing context becoming a failed run. It lives here
    rather than in ``api/deps.py`` because naming concrete implementations is this layer's job.

    Shared and stateless in effect: its subscription store is permanently empty, so every
    ``dispatch`` is a no-op returning ``[]``.
    """
    return _DISABLED


_DISABLED = Webhook_Dispatcher(
    InMemory_Webhook_Subscription_Store(), InMemory_Webhook_Outbox()
)
