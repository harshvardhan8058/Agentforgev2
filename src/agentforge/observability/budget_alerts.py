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
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.observability.budget import Budget_Status
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
    """Keyless/test store keyed by ``(org_id, period_start, threshold_percent)``."""

    def __init__(self) -> None:
        self._claims: dict[tuple[UUID, datetime, int], Budget_Notification] = {}

    def claim(self, org_id: UUID, period_start: datetime, threshold_percent: int) -> bool:
        key = (org_id, period_start, threshold_percent)
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
        return self._claims.pop((org_id, period_start, threshold_percent), None) is not None

    def claimed(self, org_id: UUID, period_start: datetime) -> tuple[int, ...]:
        return tuple(
            sorted(
                threshold
                for (org, period, threshold) in self._claims
                if org == org_id and period == period_start
            )
        )

    def release_except(
        self, org_id: UUID, period_start: datetime, keep: tuple[int, ...]
    ) -> int:
        doomed = [
            key
            for key in self._claims
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


class Budget_Alert_Service:
    """Announces a budget threshold crossing at most once per organization per period.

    Two entry points, split by cost on purpose:

    * :meth:`pending` is pure and free, so the request path can decide whether any store or
      network work is worth scheduling at all. For the overwhelming majority of requests — an
      organization nowhere near its ceiling, or with no ceiling — the answer is no and nothing
      further happens.
    * :meth:`announce` claims and emits, and is only ever called *after* the response, from a
      background task or the deferred-work seam.
    """

    def __init__(self, store: Budget_Notification_Store, emitter: Webhook_Emitter) -> None:
        self._store = store
        self._emitter = emitter

    def pending(self, status: Budget_Status) -> tuple[int, ...]:
        """Return the thresholds ``status`` has crossed. Pure; performs no I/O."""
        return crossed_thresholds(status.percent_used)

    def announce(self, status: Budget_Status) -> None:
        """Emit a webhook for each newly-crossed threshold. Never raises.

        Claim first, then emit: the alternative order would let two concurrent requests both
        emit before either recorded it. If nothing was delivered *and something was tried*, the
        claim is released so a later request re-announces — a delivery outage must not consume
        the one notification the organization was going to get. When there are no subscriptions
        at all, the claim stands: the threshold really did pass, and there was nobody to tell.
        """
        for threshold in self.pending(status):
            try:
                if not self._store.claim(status.org_id, status.period_start, threshold):
                    continue  # already announced this period (or another request just won)
            except Exception:  # noqa: BLE001 - a notification must not affect the caller
                logger.warning(
                    "Could not claim the %d%% budget notification for org %s.",
                    threshold,
                    status.org_id,
                    exc_info=True,
                )
                continue

            deliveries = emit_budget_threshold_crossed(
                self._emitter,
                status.org_id,
                threshold_percent=threshold,
                # Exact decimal strings, as everywhere else money crosses this API.
                spent=str(status.spent),
                limit_amount=str(status.limit_amount),
                percent_used=str(status.percent_used),
                period_start=status.period_start.isoformat(),
                period_end=status.period_end.isoformat(),
                # So a consumer can tell "you are being warned" from "your runs are refused".
                blocked=status.blocked,
            )
            if deliveries and not any(d.status == "delivered" for d in deliveries):
                try:
                    self._store.release(status.org_id, status.period_start, threshold)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Could not release the unsent %d%% budget notification for org %s.",
                        threshold,
                        status.org_id,
                        exc_info=True,
                    )

    def reconcile(self, status: Budget_Status) -> int:
        """Drop claims for thresholds ``status`` no longer crosses; return how many.

        Called when the ceiling itself changes. Raising a budget from 100 to 1000 puts an
        organization back under 80%, and without this the next genuine crossing would be
        silent — the claim from the old ceiling would still be standing. Lowering a ceiling
        needs no special handling: the newly-crossed thresholds are simply unclaimed.

        Never raises: a failure here loses a future notification, which must not fail the
        budget change the operator actually asked for.
        """
        try:
            return self._store.release_except(
                status.org_id, status.period_start, self.pending(status)
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not reconcile budget notifications for org %s.",
                status.org_id,
                exc_info=True,
            )
            return 0
