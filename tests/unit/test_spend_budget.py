"""Unit tests for spend budgets: the period, the arithmetic, the cache, and the postures.

The platform could measure cost and not limit it. These tests pin the parts of closing that
gap which are easy to get subtly wrong:

* **The period is computed, not stored**, so there is no rollover job to fail. Month
  boundaries (including December→January and a 31-day month) are asserted directly.
* **Money stays exact.** Spend, limit and remaining are `Decimal` throughout; a float would
  drift on the values this platform actually produces (`0.00005` per 1K tokens).
* **`warn` never refuses**, `block` refuses only at or over the ceiling, and no budget at all
  means unlimited — three distinct states, because conflating any two of them either breaks a
  customer's traffic or fails to protect them.
* **The cache bounds the cost of enforcement, and its staleness is bounded too** — including
  that raising a ceiling takes effect immediately rather than after the window.
* **A metering failure fails open.** An analytics outage must not become a total outage.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentforge.observability.analytics import Analytics_Service
from agentforge.observability.budget import (
    Budget_Guard,
    InMemory_Budget_Store,
    current_period,
)
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.store import InMemory_Usage_Store

ORG = uuid.uuid4()


def _usage(org_id, cost: str, when: datetime) -> Usage_Record:
    return Usage_Record(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=None,
        provider="groq",
        model="llama-3.1-8b-instant",
        prompt_tokens=1000,
        completion_tokens=1000,
        total_tokens=2000,
        cost=Decimal(cost),
        created_at=when,
    )


def _guard(*, cache_seconds: float = 0.0) -> tuple[Budget_Guard, InMemory_Budget_Store, InMemory_Usage_Store]:
    budgets = InMemory_Budget_Store()
    usage = InMemory_Usage_Store()
    guard = Budget_Guard(budgets, Analytics_Service(usage), cache_seconds=cache_seconds)
    return guard, budgets, usage


# --- the period -------------------------------------------------------------------


@pytest.mark.parametrize(
    "moment,expected_start,expected_end",
    [
        ("2026-08-15T13:45:00+00:00", "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
        # A 31-day month must not roll into the month after next.
        ("2026-01-31T23:59:59+00:00", "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
        # Year boundary.
        ("2026-12-02T00:00:00+00:00", "2026-12-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00"),
        # February in a leap year.
        ("2028-02-29T12:00:00+00:00", "2028-02-01T00:00:00+00:00", "2028-03-01T00:00:00+00:00"),
        # The first instant of a month belongs to that month.
        ("2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
    ],
)
def test_the_period_is_the_calendar_month_in_utc(moment, expected_start, expected_end):
    start, end = current_period(datetime.fromisoformat(moment))
    assert start.isoformat() == expected_start
    assert end.isoformat() == expected_end


def test_a_non_utc_moment_is_converted_before_the_period_is_computed():
    """The period must not depend on the caller's timezone."""
    tokyo = timezone(timedelta(hours=9))
    # 2026-09-01 08:00 in Tokyo is still 2026-08-31 23:00 UTC — the AUGUST period.
    start, _end = current_period(datetime(2026, 9, 1, 8, 0, tzinfo=tokyo))
    assert start.isoformat() == "2026-08-01T00:00:00+00:00"


# --- the arithmetic ---------------------------------------------------------------


def test_no_budget_means_unlimited():
    guard, _budgets, usage = _guard()
    usage.add(_usage(ORG, "12.50", datetime.now(timezone.utc)))

    status = guard.status(ORG)

    assert status.spent == Decimal("12.50")
    assert status.limit_amount is None
    assert status.remaining is None
    assert status.percent_used is None
    assert status.action is None
    assert status.exceeded is False
    assert status.blocked is False


def test_spend_and_remaining_are_exact_decimals():
    guard, budgets, usage = _guard()
    budgets.upsert(ORG, limit_amount=Decimal("1.00"), action="block")
    # Three costs a float would not sum exactly.
    for cost in ("0.00005", "0.00008", "0.10000"):
        usage.add(_usage(ORG, cost, datetime.now(timezone.utc)))

    status = guard.status(ORG)

    assert status.spent == Decimal("0.10013")
    assert status.remaining == Decimal("0.89987")
    assert status.exceeded is False
    assert status.blocked is False


def test_only_this_period_and_this_org_count():
    guard, budgets, usage = _guard()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")
    now = datetime.now(timezone.utc)
    period_start, _end = current_period(now)

    usage.add(_usage(ORG, "5", now))
    # Last period's spend must not consume this period's budget.
    usage.add(_usage(ORG, "100", period_start - timedelta(seconds=1)))
    # Another tenant's spend is never counted.
    usage.add(_usage(uuid.uuid4(), "100", now))

    status = guard.status(ORG)

    assert status.spent == Decimal("5")
    assert status.blocked is False


def test_reaching_the_ceiling_exactly_counts_as_exceeded():
    """`>=`, not `>`: a limit is a ceiling, and spending exactly it has consumed it."""
    guard, budgets, usage = _guard()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")
    usage.add(_usage(ORG, "10", datetime.now(timezone.utc)))

    status = guard.status(ORG)

    assert status.exceeded is True
    assert status.blocked is True
    assert status.remaining == Decimal(0)
    assert status.percent_used == Decimal(100)


def test_remaining_never_goes_negative():
    guard, budgets, usage = _guard()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="warn")
    usage.add(_usage(ORG, "25", datetime.now(timezone.utc)))

    status = guard.status(ORG)

    assert status.remaining == Decimal(0)
    assert status.percent_used == Decimal(250)


def test_a_zero_budget_means_spend_nothing_and_is_not_the_same_as_no_budget():
    guard, budgets, _usage = _guard()
    budgets.upsert(ORG, limit_amount=Decimal("0"), action="block")

    status = guard.status(ORG)

    # Distinguishable from `limit_amount is None`, and reported as fully used rather than
    # raising on a division by zero.
    assert status.limit_amount == Decimal("0")
    assert status.percent_used == Decimal(100)
    assert status.exceeded is True
    assert status.blocked is True


# --- the postures -----------------------------------------------------------------


def test_warn_reports_the_overage_without_blocking():
    """A reporting posture must never break a customer's traffic."""
    guard, budgets, usage = _guard()
    budgets.upsert(ORG, limit_amount=Decimal("1"), action="warn")
    usage.add(_usage(ORG, "5", datetime.now(timezone.utc)))

    status = guard.status(ORG)

    assert status.exceeded is True
    assert status.blocked is False
    assert status.action == "warn"


def test_a_metering_failure_fails_open():
    """An analytics outage must not become a platform outage for every budgeted tenant."""

    class _BrokenAnalytics:
        def usage_report(self, *_args, **_kwargs):
            raise RuntimeError("usage store is down")

    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("1"), action="block")
    guard = Budget_Guard(budgets, _BrokenAnalytics(), cache_seconds=0.0)

    status = guard.status(ORG)

    assert status.spent == Decimal(0)
    assert status.blocked is False


# --- the cache --------------------------------------------------------------------


def test_spend_is_cached_so_enforcement_does_not_aggregate_per_request():
    calls = {"n": 0}

    class _CountingAnalytics:
        def __init__(self, inner):
            self._inner = inner

        def usage_report(self, org_id, *, start, end):
            calls["n"] += 1
            return self._inner.usage_report(org_id, start=start, end=end)

    usage = InMemory_Usage_Store()
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")
    guard = Budget_Guard(
        budgets, _CountingAnalytics(Analytics_Service(usage)), cache_seconds=60.0
    )

    for _ in range(5):
        guard.status(ORG)

    assert calls["n"] == 1, "the month's spend must not be re-aggregated on every request"


def test_the_cache_window_bounds_staleness():
    usage = InMemory_Usage_Store()
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")
    guard = Budget_Guard(budgets, Analytics_Service(usage), cache_seconds=30.0)
    now = datetime.now(timezone.utc)

    assert guard.status(ORG, now=now).spent == Decimal(0)
    usage.add(_usage(ORG, "50", now))

    # Inside the window the stale value is reused: the documented, bounded overshoot.
    assert guard.status(ORG, now=now + timedelta(seconds=10)).blocked is False
    # Past it, the ceiling bites.
    assert guard.status(ORG, now=now + timedelta(seconds=31)).blocked is True


def test_changing_the_budget_takes_effect_immediately():
    """An owner raising their own ceiling must not have to wait out the cache window."""
    usage = InMemory_Usage_Store()
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("1"), action="block")
    guard = Budget_Guard(budgets, Analytics_Service(usage), cache_seconds=300.0)
    usage.add(_usage(ORG, "5", datetime.now(timezone.utc)))

    assert guard.status(ORG).blocked is True

    budgets.upsert(ORG, limit_amount=Decimal("100"), action="block")
    guard.invalidate(ORG)

    assert guard.status(ORG).blocked is False


def test_the_cache_is_per_org():
    usage = InMemory_Usage_Store()
    budgets = InMemory_Budget_Store()
    other = uuid.uuid4()
    budgets.upsert(ORG, limit_amount=Decimal("1"), action="block")
    budgets.upsert(other, limit_amount=Decimal("1000"), action="block")
    guard = Budget_Guard(budgets, Analytics_Service(usage), cache_seconds=300.0)
    now = datetime.now(timezone.utc)
    usage.add(_usage(ORG, "5", now))
    usage.add(_usage(other, "5", now))

    assert guard.status(ORG).blocked is True
    assert guard.status(other).blocked is False


def test_the_cache_is_per_period_so_a_new_month_is_not_answered_with_the_old_one():
    """Keyed on the org alone, the first seconds of a new month reported last month's total.

    That is not a rounding nuisance: an organization that ended the month over a *blocking*
    budget would start the next one still refused, for the length of the cache window, with a
    number no dashboard agreed with.
    """
    usage = InMemory_Usage_Store()
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")
    guard = Budget_Guard(budgets, Analytics_Service(usage), cache_seconds=300.0)

    july_end = datetime(2026, 7, 31, 23, 59, 30, tzinfo=timezone.utc)
    usage.add(_usage(ORG, "50", july_end))

    # July: over the ceiling, and cached for five minutes.
    assert guard.status(ORG, now=july_end).blocked is True

    # Thirty seconds later it is August. The cached July figure must not answer for it.
    august = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    august_status = guard.status(ORG, now=august)
    assert august_status.period_start == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert august_status.spent == Decimal("0")
    assert august_status.blocked is False


def test_invalidating_drops_every_period_held_for_the_org():
    """"Forget what you know about this tenant" cannot leave a neighbouring period behind."""
    usage = InMemory_Usage_Store()
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")
    guard = Budget_Guard(budgets, Analytics_Service(usage), cache_seconds=300.0)

    july = datetime(2026, 7, 15, tzinfo=timezone.utc)
    august = datetime(2026, 8, 15, tzinfo=timezone.utc)
    guard.status(ORG, now=july)
    guard.status(ORG, now=august)

    usage.add(_usage(ORG, "50", july))
    usage.add(_usage(ORG, "50", august))
    guard.invalidate(ORG)

    assert guard.status(ORG, now=july).spent == Decimal("50")
    assert guard.status(ORG, now=august).spent == Decimal("50")


# --- the store --------------------------------------------------------------------


def test_upsert_replaces_the_budget_and_preserves_when_budgeting_started():
    budgets = InMemory_Budget_Store()

    first = budgets.upsert(ORG, limit_amount=Decimal("10"), action="warn")
    second = budgets.upsert(ORG, limit_amount=Decimal("20"), action="block")

    assert second.limit_amount == Decimal("20")
    assert second.action == "block"
    # `created_at` records when the org started budgeting, not when the ceiling last moved.
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert budgets.get(ORG) == second


def test_the_store_is_org_scoped():
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")

    assert budgets.get(uuid.uuid4()) is None
    assert budgets.delete(uuid.uuid4()) is False
    assert budgets.get(ORG) is not None


def test_delete_is_idempotent():
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("10"), action="block")

    assert budgets.delete(ORG) is True
    assert budgets.delete(ORG) is False
    assert budgets.get(ORG) is None
