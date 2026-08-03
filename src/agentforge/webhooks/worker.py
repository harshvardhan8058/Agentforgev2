"""Webhook_Delivery_Worker: drains the outbox, one attempt per entry per pass.

The half of delivery that dials. It claims a lease on due entries, makes **one** HTTP attempt
each, and either settles the row or pushes it out to the next slot in the exponential schedule.

One attempt per pass, rather than a retry loop inside the worker, is the design decision that
makes the whole thing durable: the row is the retry state, so nothing is lost when the process
stops between attempts, and a consumer that is down for an hour costs a handful of cheap failures
spread over that hour instead of one worker blocked in a sleep. It also means the worker's
worst-case pass duration is `batch_size x timeout`, which is a number an operator can reason
about.

Failure handling worth stating:

* **Fail-forward, never fail-fast.** Every per-entry failure — a subscription that vanished, an
  unserialisable payload, a transport that broke its contract, a store that refused a write — is
  contained to that entry. A pass never aborts, because one poisoned row must not stop a tenant's
  other events from moving.
* **The schedule is bounded.** After ``max_attempts`` the entry is *abandoned* rather than
  retried forever: an endpoint that has refused for hours is not going to accept on attempt fifty,
  and an unbounded queue is an outage waiting to happen. Abandoned rows are visible over the API
  and can be redelivered explicitly.
* **Delivery is at-least-once.** A worker that delivers and then dies before recording the success
  will deliver again when the lease expires. Exactly-once would require a distributed transaction
  with an endpoint the platform does not control, so the honest guarantee is at-least-once plus an
  ``idempotency_key`` in the envelope — see docs/WEBHOOKS.md.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Final

from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.outbox import (
    Outbox_Entry,
    Webhook_Outbox,
    next_attempt_delay,
)
from agentforge.webhooks.store import Webhook_Subscription_Store

logger = logging.getLogger(__name__)

#: How long delivered rows are kept before the prune sweep removes them. Long enough that the
#: delivery log and the outbox agree while an operator is investigating; short enough that the
#: table does not become a second, unbounded copy of the delivery log.
SETTLED_RETENTION: Final[timedelta] = timedelta(days=7)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Webhook_Delivery_Worker:
    """Polls the outbox and performs one delivery attempt per due entry.

    Runs as a daemon thread started by the application lifespan. A thread rather than an asyncio
    task because every store call and the HTTP client here are synchronous, and wrapping them to
    live on the event loop would buy nothing but a way to block it.
    """

    def __init__(
        self,
        outbox: Webhook_Outbox,
        subscriptions: Webhook_Subscription_Store,
        emitter: Webhook_Emitter,
        *,
        batch_size: int = 20,
        poll_seconds: float = 2.0,
        max_attempts: int = 8,
        backoff_seconds: float = 60.0,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._outbox = outbox
        self._subscriptions = subscriptions
        self._emitter = emitter
        self._batch_size = max(1, int(batch_size))
        self._poll_seconds = max(0.1, float(poll_seconds))
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_seconds = max(1.0, float(backoff_seconds))
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_prune: datetime | None = None

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        """Begin polling in a daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="webhook-delivery-worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "Webhook delivery worker started (batch=%d, poll=%.1fs, max_attempts=%d).",
            self._batch_size,
            self._poll_seconds,
            self._max_attempts,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the worker to finish its current pass and exit. Safe to call unstarted."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                delivered = self.run_once()
            except Exception:  # noqa: BLE001 - the loop must outlive any single pass
                logger.exception("Webhook delivery pass failed; the worker continues.")
                delivered = 0
            # A pass that emptied its batch probably has more waiting, so poll again at once
            # rather than sleeping through a backlog.
            if delivered < self._batch_size:
                self._stop.wait(self._poll_seconds)

    # --- the work -----------------------------------------------------------------

    def run_once(self) -> int:
        """Claim and attempt one batch. Returns how many entries were attempted.

        Public and synchronous on purpose: it is what the loop calls, what a test calls instead of
        waiting on a thread, and what an operator-triggered redelivery can call to flush
        immediately.
        """
        now = self._clock()
        try:
            batch = self._outbox.claim_due(limit=self._batch_size, now=now)
        except Exception:  # noqa: BLE001
            logger.warning("Could not claim webhook outbox entries.", exc_info=True)
            return 0

        for entry in batch:
            try:
                self._attempt(entry, now=now)
            except Exception:  # noqa: BLE001 - one poisoned row must not stop the batch
                logger.exception(
                    "Unexpected failure while delivering outbox entry %s.", entry.id
                )
        self._maybe_prune(now)
        return len(batch)

    def _attempt(self, entry: Outbox_Entry, *, now: datetime) -> None:
        """Make one delivery attempt for ``entry`` and settle or reschedule it."""
        attempts = entry.attempts + 1

        subscription = self._subscriptions.get(entry.org_id, entry.subscription_id)
        if subscription is None:
            # Deleted between enqueue and delivery. Not a failure to retry: there is no endpoint
            # and no secret to sign with any more.
            self._outbox.abandon(
                entry.id,
                attempts=entry.attempts,
                error="the subscription was deleted before delivery",
            )
            return
        if not subscription.active:
            # Paused. Held rather than dropped, so resuming a subscription delivers what it
            # missed instead of silently discarding it — and rescheduled, so a subscription
            # paused for a week does not spin.
            self._outbox.reschedule(
                entry.id,
                attempts=entry.attempts,
                next_attempt_at=now + next_attempt_delay(
                    attempts, base_seconds=self._backoff_seconds
                ),
                error="the subscription is paused",
            )
            return

        delivery = self._emitter.deliver_once(
            subscription,
            entry.event,
            entry.payload,
            delivery_id=entry.id,
            idempotency_key=entry.idempotency_key,
            attempt=attempts,
        )
        if delivery is None:
            # The payload could not be rendered: a programming error at the call site, not a
            # transient fault, so retrying it forever would be noise in the logs.
            self._outbox.abandon(
                entry.id, attempts=attempts, error="the payload could not be rendered"
            )
            return

        if delivery.status == "delivered":
            self._outbox.mark_delivered(entry.id, attempts=attempts)
            return

        if attempts >= self._max_attempts:
            logger.warning(
                "Abandoning webhook %s to subscription %s after %d attempts: %s",
                entry.event.value,
                entry.subscription_id,
                attempts,
                delivery.error,
            )
            self._outbox.abandon(entry.id, attempts=attempts, error=delivery.error)
            return

        self._outbox.reschedule(
            entry.id,
            attempts=attempts,
            next_attempt_at=now
            + next_attempt_delay(attempts, base_seconds=self._backoff_seconds),
            error=delivery.error,
        )

    def _maybe_prune(self, now: datetime) -> None:
        """Sweep settled rows at most hourly, so the outbox does not grow without bound.

        Here rather than in a separate cron because the worker is already the one process
        guaranteed to be running wherever the outbox is, and a retention job nobody deploys is
        the same as no retention job.
        """
        if self._last_prune is not None and (now - self._last_prune) < timedelta(hours=1):
            return
        self._last_prune = now
        try:
            removed = self._outbox.prune_settled(older_than=now - SETTLED_RETENTION)
            if removed:
                logger.info("Pruned %d settled webhook outbox entries.", removed)
        except Exception:  # noqa: BLE001
            logger.warning("Could not prune settled webhook outbox entries.", exc_info=True)
