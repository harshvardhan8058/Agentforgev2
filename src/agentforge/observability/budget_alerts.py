"""Budget threshold notifications: telling an owner *before* the invoice does.

Spend budgets could measure and refuse, and could not warn. An owner learned they were at 95%
by looking, or learned they were at 100% because their traffic started failing — which is the
same problem the budget feature was built to solve, one level up.

The hard part is not the notification; it is that a threshold is **not an event**. Every other
webhook in this platform corresponds to one occurrence, so it fires once by construction.
"Spend is past 80%" is a *condition*: once true, it stays true for every request until the
month rolls over. Emitting on the condition would send one webhook per request for weeks.

So this module is mostly about claiming:

* :class:`Budget_Notification_Store` records, per ``(org, period, threshold)``, that the
  notification has been sent. Claiming is one atomic ``INSERT ... ON CONFLICT DO NOTHING``, so
  two concurrent requests that both observe a crossing cannot both notify.
* :class:`Budget_Alert_Service` decides cheaply (no I/O) whether anything is worth announcing,
  and only then claims and emits. It **releases** the claim when every delivery failed, so a
  delivery outage does not silently consume the one notification the organization was going to
  get, and it reconciles claims when the ceiling itself moves.

Thresholds are a module constant rather than a setting. Making them configurable means parsing
and validating a list, and every value an operator might want (80 and 100) is already here;
adding a third is a one-line change to :data:`BUDGET_THRESHOLDS` with no migration. That
trade-off is recorded in docs/KNOWN_LIMITATIONS.md rather than left implicit.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.observability.budget import (
    Budget_Status,
    Budget_Store,
    format_percent,
)
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.events import emit_budget_threshold_crossed

logger = logging.getLogger(__name__)

#: The thresholds an organization is notified at, as whole percentages of its ceiling.
#:
#: 80 is "you are going to run out"; 100 is "you have". Ascending, and each is claimed
#: separately, so an organization that jumps from 40% to 120% in one request is told about both
#: rather than only the last one — the 80% notification is what a consumer's runbook keys on.
BUDGET_THRESHOLDS: Final[tuple[int, ...]] = (80, 100)


def crossed_thresholds(percent_used: Decimal | None) -> tuple[int, ...]:
    """Return every threshold that ``percent_used`` has reached, ascending.

    ``None`` (no budget set) crosses nothing: an unlimited organization has no threshold to
    pass. A pure function, so the request path can ask "is there anything to announce" without
    touching a store.
    """
    if percent_used is None:
        return ()
    return tuple(t for t in BUDGET_THRESHOLDS if percent_used >= Decimal(t))


@dataclass(frozen=True)
class Budget_Notification:
    """The record that one threshold has been announced for one org-period."""

    org_id: UUID
    period_start: datetime
    threshold_percent: int
    notified_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Budget_Notification_Store:
    """Claim-based persistence seam, org-scoped on every call.

    ``claim`` is deliberately not ``exists`` + ``record``: the whole point is that two
    concurrent requests observing the same crossing must produce exactly one notification, and
    only an atomic claim can promise that.
    """

    def claim(
        self, org_id: UUID, period_start: datetime, threshold_percent: int
    ) -> bool:  # pragma: no cover - interface
        """Record the notification; return True iff THIS call was the one that recorded it."""
        raise NotImplementedError

    def release(
        self, org_id: UUID, period_start: datetime, threshold_percent: int
    ) -> bool:  # pragma: no cover - interface
        """Undo a claim so the threshold can be announced again. True iff a row was removed."""
        raise NotImplementedError

    def claimed(
        self, org_id: UUID, period_start: datetime
    ) -> tuple[int, ...]:  # pragma: no cover - interface
        """Return the thresholds already announced for this org-period, ascending."""
        raise NotImplementedError

    def release_except(
        self, org_id: UUID, period_start: datetime, keep: tuple[int, ...]
    ) -> int:  # pragma: no cover - interface
        """Drop every claim for this org-period except ``keep``; return how many were dropped."""
        raise NotImplementedError


class InMemory_Budget_Notification_Store(Budget_Notification_Store):
    """Keyless/test store keyed by ``(org_id, period_start, threshold_percent)``.

    Every method holds a lock. That is not defensive habit: announcements run from worker
    threads, so an unlocked ``in``-then-assign is a genuine check-then-set race that produces two
    notifications — measurably, in tens of trials out of hundreds — and iterating the dict while
    another worker inserts raises ``RuntimeError: dictionary changed size during iteration``. The
    interface promises that only an atomic claim can make "once" true; this implementation has to
    honour that promise, not merely restate it.
    """

    def __init__(self) -> None:
        self._claims: dict[tuple[UUID, datetime, int], Budget_Notification] = {}
        self._lock = threading.Lock()

    def claim(self, org_id: UUID, period_start: datetime, threshold_percent: int) -> bool:
        key = (org_id, period_start, threshold_percent)
        with self._lock:
            if key in self._claims:
                return False
            self._claims[key] = Budget_Notification(
                org_id=org_id,
                period_start=period_start,
                threshold_percent=threshold_percent,
                notified_at=_utcnow(),
            )
            return True

    def release(self, org_id: UUID, period_start: datetime, threshold_percent: int) -> bool:
        with self._lock:
            return (
                self._claims.pop((org_id, period_start, threshold_percent), None) is not None
            )

    def claimed(self, org_id: UUID, period_start: datetime) -> tuple[int, ...]:
        with self._lock:
            return tuple(
                sorted(
                    threshold
                    for (org, period, threshold) in list(self._claims)
                    if org == org_id and period == period_start
                )
            )

    def release_except(
        self, org_id: UUID, period_start: datetime, keep: tuple[int, ...]
    ) -> int:
        with self._lock:
            doomed = [
                key
                for key in list(self._claims)
                if key[0] == org_id and key[1] == period_start and key[2] not in keep
            ]
            for key in doomed:
                del self._claims[key]
            return len(doomed)


class Pg_Budget_Notification_Store(Budget_Notification_Store):
    """Postgres-backed store over ``budget_notifications`` (migration 0016)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def claim(self, org_id: UUID, period_start: datetime, threshold_percent: int) -> bool:
        """One statement, so concurrent requests cannot both win the claim."""
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO budget_notifications
                        (org_id, period_start, threshold_percent, notified_at)
                    VALUES (:org_id, :period_start, :threshold, :notified_at)
                    ON CONFLICT (org_id, period_start, threshold_percent) DO NOTHING
                    """
                ),
                {
                    "org_id": str(org_id),
                    "period_start": period_start,
                    "threshold": threshold_percent,
                    "notified_at": _utcnow(),
                },
            )
        return result.rowcount > 0

    def release(self, org_id: UUID, period_start: datetime, threshold_percent: int) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM budget_notifications WHERE org_id = :org_id "
                    "AND period_start = :period_start AND threshold_percent = :threshold"
                ),
                {
                    "org_id": str(org_id),
                    "period_start": period_start,
                    "threshold": threshold_percent,
                },
            )
        return result.rowcount > 0

    def claimed(self, org_id: UUID, period_start: datetime) -> tuple[int, ...]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT threshold_percent FROM budget_notifications "
                    "WHERE org_id = :org_id AND period_start = :period_start "
                    "ORDER BY threshold_percent"
                ),
                {"org_id": str(org_id), "period_start": period_start},
            ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def release_except(
        self, org_id: UUID, period_start: datetime, keep: tuple[int, ...]
    ) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM budget_notifications WHERE org_id = :org_id "
                    "AND period_start = :period_start "
                    "AND NOT (threshold_percent = ANY(CAST(:keep AS integer[])))"
                ),
                {
                    "org_id": str(org_id),
                    "period_start": period_start,
                    # An empty array is valid and drops everything, which is what "no threshold
                    # is crossed any more" must mean.
                    "keep": list(keep),
                },
            )
        return int(result.rowcount)


#: How long a failed announcement waits before it may be retried. Without a cooldown, an
#: organization over 80% with a broken endpoint would re-claim and re-emit the whole delivery
#: budget on *every* request for the rest of the month — turning the emitter's careful per-event
#: bound into an unbounded one, and pointing it at a URL the tenant chose.
RETRY_COOLDOWN_SECONDS: Final[float] = 300.0

#: How many times one threshold may be announced in a period before the platform gives up.
#: A consumer that has been unreachable five times over 25 minutes is not going to be reached by
#: a sixth attempt on the next request.
MAX_ANNOUNCE_ATTEMPTS: Final[int] = 5

#: Bounded queue for off-band announcements. One worker, because announcements are rare and
#: strictly ordered work is easier to reason about; a small backlog, so a burst is absorbed and
#: an unbounded one is dropped rather than queued forever.
_DISPATCH_WORKERS: Final[int] = 1
_MAX_QUEUED_ANNOUNCEMENTS: Final[int] = 32


class Budget_Alert_Service:
    """Announces a budget threshold crossing at most once per organization per period.

    Three entry points, split by cost on purpose:

    * :meth:`pending` is pure and free, so the request path can decide whether any store or
      network work is worth doing at all. For the overwhelming majority of requests — an
      organization nowhere near its ceiling, or with no ceiling — the answer is no.
    * :meth:`dispatch` hands the work to this service's **own** small thread pool and returns
      immediately. It deliberately does *not* use the request's ``BackgroundTasks``: those are
      shared with the routers, so an announcement would queue ahead of trace export and the
      ``run.completed`` webhook, and on a streamed response they are attached to the response,
      which would hold the client's connection open for a subscriber's timeout. Off-band
      dispatch also caps the damage a slow endpoint can do: one dedicated worker rather than a
      share of the pool every store call in the platform uses.
    * :meth:`announce` is the work itself — claim, emit, and release on failure — and is what
      the pool runs.

    :meth:`reconcile` handles the ceiling *changing*, which is the one case where a claim that
    was correct becomes wrong.
    """

    def __init__(
        self,
        store: Budget_Notification_Store,
        emitter: Webhook_Emitter,
        budgets: Budget_Store | None = None,
        *,
        executor: Executor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._emitter = emitter
        # Optional: when present, `announce` re-reads the ceiling it is about to warn about, so a
        # snapshot taken before an owner raised their budget cannot send a warning citing the old
        # limit (and, worse, claim the threshold the raise just un-crossed).
        self._budgets = budgets
        self._executor = executor or ThreadPoolExecutor(
            max_workers=_DISPATCH_WORKERS, thread_name_prefix="budget-alerts"
        )
        self._clock = clock
        self._pending: set[Future] = set()
        # (org, period, threshold) -> monotonic time of the last attempt, plus a count. An
        # in-process memo, so the steady state — an org that has been over 80% for a fortnight —
        # costs nothing: no claim round trip, no emission, on either the pass or the 402 path.
        self._attempts: dict[tuple[UUID, datetime, int], tuple[float, int]] = {}
        self._lock = threading.Lock()

    # --- request path -------------------------------------------------------------

    def pending(self, status: Budget_Status) -> tuple[int, ...]:
        """Return the thresholds worth announcing for ``status``. Pure; performs no I/O.

        Excludes thresholds this process has already announced (or has recently failed to
        announce, or has given up on), so a request from an organization that crossed 80% last
        week schedules nothing at all.

        Returns nothing when the spend figure is not authoritative: the guard reports zero when
        metering is unavailable, and "spend is unknown" must not be read as a crossing — nor,
        below in :meth:`reconcile`, as the absence of one.
        """
        if not status.spend_is_authoritative:
            return ()
        crossed = crossed_thresholds(status.percent_used)
        if not crossed:
            return ()
        now = self._clock()
        with self._lock:
            return tuple(
                threshold
                for threshold in crossed
                if self._is_announceable(status, threshold, now)
            )

    def dispatch(self, status: Budget_Status) -> bool:
        """Schedule :meth:`announce` off-band. Returns whether it was accepted. Never raises.

        Non-blocking: the caller is a request that has not been answered yet.
        """
        with self._lock:
            self._pending = {f for f in self._pending if not f.done()}
            if len(self._pending) >= _MAX_QUEUED_ANNOUNCEMENTS:
                # Dropped rather than queued: a backlog this deep means deliveries are not
                # completing, and an unbounded queue of stale notifications helps nobody.
                logger.warning(
                    "Dropping a budget notification for org %s: the announcement queue is full.",
                    status.org_id,
                )
                return False
        try:
            future = self._executor.submit(self.announce, status)
        except RuntimeError:
            # The executor is shut down (interpreter teardown). Not worth a stack trace.
            logger.warning("Could not dispatch a budget notification: executor is closed.")
            return False
        with self._lock:
            self._pending.add(future)
        return True

    def drain(self, timeout: float = 5.0) -> None:
        """Wait for dispatched announcements to finish. For shutdown and for tests.

        Tests need this because the whole point of :meth:`dispatch` is that the response does
        not wait for the delivery; without a way to join, a test would either race or sleep.
        """
        with self._lock:
            outstanding = list(self._pending)
        for future in outstanding:
            try:
                future.result(timeout=timeout)
            except Exception:  # noqa: BLE001 - announce already absorbs its own failures
                pass

    # --- the work -----------------------------------------------------------------

    def announce(self, status: Budget_Status) -> None:
        """Emit a webhook for each newly-crossed threshold. Never raises.

        Claim first, then emit: the alternative order would let two concurrent announcements both
        emit before either recorded it. The claim is released — so a later request tries again —
        when the announcement demonstrably did not reach anybody: the subscription lookup failed,
        the payload could not be rendered, or every attempted delivery failed. It is *kept* when
        there was simply nobody subscribed, because nothing failed and there is nothing to retry.
        """
        thresholds = self.pending(status)
        if not thresholds:
            return
        if not self._ceiling_is_current(status):
            # The snapshot is stale: an owner changed the ceiling after this status was computed,
            # so warning about the old one would be wrong, and claiming against it would silence
            # the genuine crossing of the new one.
            logger.info(
                "Skipping a budget notification for org %s: the ceiling changed since the "
                "request was measured.",
                status.org_id,
            )
            return

        for threshold in thresholds:
            self._record_attempt(status, threshold)
            try:
                if not self._store.claim(status.org_id, status.period_start, threshold):
                    continue  # already announced this period (or another worker just won)
            except Exception:  # noqa: BLE001 - a notification must not affect the caller
                logger.warning(
                    "Could not claim the %d%% budget notification for org %s.",
                    threshold,
                    status.org_id,
                    exc_info=True,
                )
                continue

            outcome = emit_budget_threshold_crossed(
                self._emitter,
                status.org_id,
                threshold_percent=threshold,
                # Exact decimal strings, as everywhere else money crosses this API.
                spent=str(status.spent),
                limit_amount=str(status.limit_amount),
                # Rounded by the same formatter ``GET /budget`` uses, so the console and the
                # notification about the same state cannot disagree.
                percent_used=format_percent(status.percent_used) or "0",
                period_start=status.period_start.isoformat(),
                period_end=status.period_end.isoformat(),
                # So a consumer can tell "you are being warned" from "your runs are refused".
                blocked=status.blocked,
            )
            if outcome.failed_before_delivery or outcome.attempted_and_failed:
                self._release(status, threshold)
            else:
                self._clear_attempts(status, threshold)

    def reconcile(self, status: Budget_Status) -> int:
        """Drop claims for thresholds ``status`` no longer crosses; return how many.

        Called when the ceiling itself changes. Raising a budget from 100 to 1000 puts an
        organization back under 80%, and without this the next genuine crossing would be
        silent — the claim from the old ceiling would still be standing. Lowering a ceiling
        needs no special handling: the newly-crossed thresholds are simply unclaimed.

        Refuses to act on a non-authoritative spend figure. This is the destructive operation in
        the design, and the guard's fail-open zero would otherwise read as "no threshold is
        crossed", i.e. "delete every claim for this period" — so a metering blip during a budget
        edit would re-notify everything.

        Never raises: a failure here loses a future notification, which must not fail the budget
        change the operator actually asked for.
        """
        if not status.spend_is_authoritative:
            logger.warning(
                "Not reconciling budget notifications for org %s: month-to-date spend is "
                "unavailable, so which thresholds are crossed is unknown.",
                status.org_id,
            )
            return 0
        keep = crossed_thresholds(status.percent_used)
        try:
            dropped = self._store.release_except(status.org_id, status.period_start, keep)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not reconcile budget notifications for org %s.",
                status.org_id,
                exc_info=True,
            )
            return 0
        # The memo mirrors the store, or a dropped claim would still look announced in-process.
        with self._lock:
            for key in [
                k
                for k in list(self._attempts)
                if k[0] == status.org_id and k[1] == status.period_start and k[2] not in keep
            ]:
                del self._attempts[key]
        return dropped

    # --- internals ----------------------------------------------------------------

    def _is_announceable(
        self, status: Budget_Status, threshold: int, now: float
    ) -> bool:
        """Whether this process should try this threshold now. Caller holds the lock."""
        record = self._attempts.get((status.org_id, status.period_start, threshold))
        if record is None:
            return True
        last_attempt, attempts = record
        if attempts >= MAX_ANNOUNCE_ATTEMPTS:
            return False
        return (now - last_attempt) >= RETRY_COOLDOWN_SECONDS

    def _record_attempt(self, status: Budget_Status, threshold: int) -> None:
        key = (status.org_id, status.period_start, threshold)
        with self._lock:
            _last, attempts = self._attempts.get(key, (0.0, 0))
            self._attempts[key] = (self._clock(), attempts + 1)

    def _clear_attempts(self, status: Budget_Status, threshold: int) -> None:
        """Mark the threshold as settled: announced, and never to be retried this period.

        The attempt count is set beyond the cap rather than deleted, so the memo keeps answering
        "nothing to do here" without a store round trip for the rest of the period.
        """
        key = (status.org_id, status.period_start, threshold)
        with self._lock:
            self._attempts[key] = (self._clock(), MAX_ANNOUNCE_ATTEMPTS)

    def _release(self, status: Budget_Status, threshold: int) -> None:
        """Undo a claim whose announcement did not reach anybody, so it can be retried."""
        try:
            self._store.release(status.org_id, status.period_start, threshold)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not release the unsent %d%% budget notification for org %s.",
                threshold,
                status.org_id,
                exc_info=True,
            )

    def _ceiling_is_current(self, status: Budget_Status) -> bool:
        """Whether the ceiling in ``status`` is still the organization's ceiling.

        ``True`` when no budget store was wired (nothing to check against) or the store cannot be
        read: failing closed here would mean a metering-adjacent outage silences notifications,
        which is the opposite of what this feature is for.
        """
        if self._budgets is None:
            return True
        try:
            budget = self._budgets.get(status.org_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not re-read the budget for org %s while announcing.",
                status.org_id,
                exc_info=True,
            )
            return True
        current = budget.limit_amount if budget is not None else None
        return current == status.limit_amount
