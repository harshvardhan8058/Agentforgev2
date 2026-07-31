"""Spend budgets: a monthly cost ceiling per organization, and its enforcement.

The platform could already *measure* spend (usage records, a Decimal cost model, an analytics
report) and could do nothing whatsoever about it. That is the gap between an observability
feature and a cost-control one: every comparable product — OpenAI Platform, Azure AI Foundry,
Vertex — lets an owner say "stop at this number", because the alternative is discovering an
overrun in the invoice.

Three pieces here, deliberately separated:

* :class:`Spend_Budget` — the domain record: a ceiling, and what to do at it.
* :class:`Budget_Store` — persistence, one row per org, org-scoped like every other store.
* :class:`Budget_Guard` — the decision. Given an org, it answers "may this run proceed, and
  where does the org stand", by reading month-to-date spend through the existing
  ``Analytics_Service``. No new aggregation SQL exists: the number enforced is exactly the
  number the dashboard shows, which is what makes the enforcement explicable to whoever hit
  it.

The two engineering trade-offs worth stating plainly:

**Period boundaries are calendar months in UTC.** Anything else (rolling 30 days, per-tenant
billing anchors, local timezones) needs a billing model the platform does not have. A
calendar month is what an operator reads on an invoice, and the boundary is computed, never
stored, so no scheduled job exists to roll a period over — the single most common source of
bugs in this kind of feature.

**Enforcement is eventually consistent, by design.** A budget check on the request path that
aggregated usage every time would put a `SUM` over the tenant's month in front of every run.
The guard therefore caches the computed spend per org for a few seconds
(``budget_cache_seconds``). A burst inside that window can overshoot the ceiling slightly;
the alternative — an exact ledger with a lock per run — buys precision nobody is asking for
at a cost everybody would feel. The window is configurable, the overshoot is bounded by it,
and this is documented rather than discovered.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.observability.analytics import Analytics_Service

logger = logging.getLogger(__name__)

BudgetAction = Literal["warn", "block"]


@dataclass(frozen=True)
class Spend_Budget:
    """An organization's monthly spend ceiling and what happens when it is reached."""

    org_id: UUID
    limit_amount: Decimal
    action: BudgetAction
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Budget_Status:
    """Where an organization stands against its budget, for a client or a guard.

    ``spent`` and ``remaining`` are exact ``Decimal``s: they cross the API as strings and are
    rendered verbatim, like every other monetary value in this codebase.
    """

    org_id: UUID
    period_start: datetime
    period_end: datetime
    spent: Decimal
    limit_amount: Decimal | None
    action: BudgetAction | None
    # True only when a budget exists, is exceeded, AND its action is "block". A client can
    # therefore distinguish "over budget" from "blocked", which are different conversations.
    exceeded: bool
    blocked: bool

    @property
    def remaining(self) -> Decimal | None:
        """Headroom left, floored at zero, or ``None`` when no budget is set."""
        if self.limit_amount is None:
            return None
        remaining = self.limit_amount - self.spent
        return remaining if remaining > 0 else Decimal(0)

    @property
    def percent_used(self) -> Decimal | None:
        """Share of the budget consumed, or ``None`` when no budget is set.

        A zero ceiling is reported as fully used rather than as a division error: a budget of
        zero is a deliberate "spend nothing", and 100% is the truthful rendering of it.
        """
        if self.limit_amount is None:
            return None
        if self.limit_amount == 0:
            return Decimal(100)
        return (self.spent / self.limit_amount) * 100


def current_period(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` of the calendar month containing ``now``, in UTC.

    Computed, never stored, so there is no scheduled rollover to get wrong: the period a
    request falls into is a pure function of its own timestamp.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # First day of the next month: add enough days to leave the current one, then truncate.
    end = (start + timedelta(days=31)).replace(day=1)
    return start, end


class Budget_Store:
    """Postgres/in-memory seam for the per-org budget row.

    Not an ABC with two subclasses like the older stores: the surface is three methods over a
    single row, and the in-memory implementation below is the whole of the keyless behaviour.
    Both implementations take ``org_id`` on every call, so a cross-tenant read or write is
    structurally impossible (Req 4.3, 4.4).
    """

    def get(self, org_id: UUID) -> Spend_Budget | None:  # pragma: no cover - interface
        raise NotImplementedError

    def upsert(
        self, org_id: UUID, *, limit_amount: Decimal, action: BudgetAction
    ) -> Spend_Budget:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, org_id: UUID) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemory_Budget_Store(Budget_Store):
    """Keyless/test Budget_Store keyed by ``org_id``."""

    def __init__(self) -> None:
        self._budgets: dict[UUID, Spend_Budget] = {}

    def get(self, org_id: UUID) -> Spend_Budget | None:
        return self._budgets.get(org_id)

    def upsert(
        self, org_id: UUID, *, limit_amount: Decimal, action: BudgetAction
    ) -> Spend_Budget:
        existing = self._budgets.get(org_id)
        budget = Spend_Budget(
            org_id=org_id,
            limit_amount=limit_amount,
            action=action,
            # `created_at` survives an update: it is when the org started budgeting.
            created_at=existing.created_at if existing else _utcnow(),
            updated_at=_utcnow(),
        )
        self._budgets[org_id] = budget
        return budget

    def delete(self, org_id: UUID) -> bool:
        return self._budgets.pop(org_id, None) is not None


class Pg_Budget_Store(Budget_Store):
    """Postgres-backed Budget_Store over ``spend_budgets`` (migration 0014)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def get(self, org_id: UUID) -> Spend_Budget | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT org_id, limit_amount, action, created_at, updated_at "
                    "FROM spend_budgets WHERE org_id = :org_id"
                ),
                {"org_id": str(org_id)},
            ).first()
        return self._row_to_budget(row) if row is not None else None

    def upsert(
        self, org_id: UUID, *, limit_amount: Decimal, action: BudgetAction
    ) -> Spend_Budget:
        """Insert or replace the org's budget in one statement.

        ``ON CONFLICT`` rather than select-then-write: two owners saving a budget
        simultaneously would otherwise race, and the loser's value could be silently lost.
        ``created_at`` is preserved on update — it records when the org started budgeting,
        not when the ceiling last moved.
        """
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO spend_budgets (org_id, limit_amount, action, updated_at)
                    VALUES (:org_id, :limit_amount, :action, :updated_at)
                    ON CONFLICT (org_id) DO UPDATE
                        SET limit_amount = EXCLUDED.limit_amount,
                            action = EXCLUDED.action,
                            updated_at = EXCLUDED.updated_at
                    RETURNING org_id, limit_amount, action, created_at, updated_at
                    """
                ),
                {
                    "org_id": str(org_id),
                    "limit_amount": limit_amount,
                    "action": action,
                    "updated_at": _utcnow(),
                },
            ).first()
        return self._row_to_budget(row)

    def delete(self, org_id: UUID) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM spend_budgets WHERE org_id = :org_id"),
                {"org_id": str(org_id)},
            )
        return result.rowcount > 0

    @staticmethod
    def _row_to_budget(row) -> Spend_Budget:
        amount = row[1]
        return Spend_Budget(
            org_id=UUID(str(row[0])),
            limit_amount=amount if isinstance(amount, Decimal) else Decimal(str(amount)),
            action=row[2],
            created_at=row[3],
            updated_at=row[4],
        )


class Budget_Guard:
    """Decides whether an organization may start new work, and reports where it stands.

    Reads month-to-date spend through the ``Analytics_Service`` — the same aggregation the
    dashboard shows — so an enforced number is always a number the owner can look up. The
    result is cached per org for ``cache_seconds`` to keep a ``SUM`` off the request path;
    see the module docstring for why bounded overshoot is the right trade here.
    """

    def __init__(
        self,
        store: Budget_Store,
        analytics: Analytics_Service,
        *,
        cache_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._analytics = analytics
        self._cache_seconds = cache_seconds
        # org_id -> (computed_at, spend). Guarded by a lock: the guard is called from worker
        # threads, and a dict mutation racing a read is not worth debugging later.
        self._cache: dict[UUID, tuple[datetime, Decimal]] = {}
        self._lock = threading.Lock()

    def status(self, org_id: UUID, *, now: datetime | None = None) -> Budget_Status:
        """Return the org's standing for the current period. Never raises."""
        moment = now or _utcnow()
        period_start, period_end = current_period(moment)
        budget = self._store.get(org_id)
        spent = self._spend_for_period(org_id, period_start, moment)

        limit_amount = budget.limit_amount if budget else None
        action: BudgetAction | None = budget.action if budget else None
        exceeded = limit_amount is not None and spent >= limit_amount
        return Budget_Status(
            org_id=org_id,
            period_start=period_start,
            period_end=period_end,
            spent=spent,
            limit_amount=limit_amount,
            action=action,
            exceeded=exceeded,
            blocked=exceeded and action == "block",
        )

    def invalidate(self, org_id: UUID) -> None:
        """Drop the cached spend for ``org_id``.

        Called when the budget itself changes, so raising a ceiling takes effect immediately
        rather than after the cache window — an operator unblocking their own org should not
        have to wait, and that is the one case where the delay would be actively confusing.
        """
        with self._lock:
            self._cache.pop(org_id, None)

    def _spend_for_period(
        self, org_id: UUID, period_start: datetime, moment: datetime
    ) -> Decimal:
        with self._lock:
            cached = self._cache.get(org_id)
            if cached is not None and (moment - cached[0]).total_seconds() < self._cache_seconds:
                return cached[1]
        try:
            report = self._analytics.usage_report(org_id, start=period_start, end=moment)
            spent = report.total_cost
        except Exception:  # noqa: BLE001 - a metering failure must not block the platform
            # Fail OPEN: if spend cannot be computed, work continues. The alternative is an
            # analytics outage becoming a total outage for every tenant with a budget.
            logger.warning(
                "Could not compute month-to-date spend for org %s; treating as unbudgeted.",
                org_id,
                exc_info=True,
            )
            return Decimal(0)
        with self._lock:
            self._cache[org_id] = (moment, spent)
        return spent
