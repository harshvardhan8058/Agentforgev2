"""Analytics router: ``GET /analytics/usage`` (Task 12).

Returns the aggregated :class:`~agentforge.observability.models.Usage_Report` for the
caller's org over an optional ``[start, end]`` range. The endpoint declares only
``Depends(require_permission(Permission.READ))`` and threads ``principal.org_id`` into
the :class:`Analytics_Service` — no bespoke authorization logic lives here (Req 3.1, 3.5,
3.6, 7.6). A missing/invalid credential surfaces as 401 and a principal lacking ``read``
as 403 via the reused dependencies; the report is computed **only** from the caller's org
records, so no other tenant's usage can appear (Req 3.3, 10.5).

The Analytics_Service / Usage_Store are synchronous, so the query runs in a worker thread
to avoid blocking the event loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_analytics_service,
    get_settings,
    require_permission,
)
from agentforge.api.schemas import UsageBreakdownEntry, UsageReportResponse
from agentforge.config.settings import Settings
from agentforge.observability.cost import parse_rate_table
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.analytics import Analytics_Service
from agentforge.observability.models import Breakdown_Entry, Usage_Report

router = APIRouter(tags=["analytics"])

# The lower bound used when no ``start`` is supplied — the Unix epoch (tz-aware) so every
# stored record falls within the default range.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    """Return ``dt`` as a timezone-aware UTC datetime (naive inputs assumed UTC).

    Stored ``Usage_Record.created_at`` values are timezone-aware, so a naive query bound
    must be normalized before comparison to avoid a naive/aware comparison error.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_entries(entries: list[Breakdown_Entry]) -> list[UsageBreakdownEntry]:
    """Map domain breakdown entries to their response schema (cost as an exact string)."""
    return [
        UsageBreakdownEntry(
            key=entry.key,
            total_tokens=entry.total_tokens,
            total_cost=str(entry.total_cost),
        )
        for entry in entries
    ]


def _rates_configured(settings: Settings) -> bool:
    """Return True iff this deployment can produce a non-zero cost.

    True when a per-model rate table is supplied, or when either default per-1K rate is
    non-zero. Parsed rather than merely checked for presence so an empty or all-zero
    table is reported honestly as "not priced".
    """
    for rate in parse_rate_table(settings.cost_rate_table_json).values():
        if rate.prompt_per_1k != 0 or rate.completion_per_1k != 0:
            return True
    return (
        Decimal(str(settings.cost_default_prompt_per_1k)) != 0
        or Decimal(str(settings.cost_default_completion_per_1k)) != 0
    )


def _to_response(report: Usage_Report, *, rates_configured: bool) -> UsageReportResponse:
    """Render a :class:`Usage_Report` as its API response envelope."""
    return UsageReportResponse(
        org_id=report.org_id,
        start=report.start,
        end=report.end,
        total_tokens=report.total_tokens,
        total_cost=str(report.total_cost),
        by_provider=_to_entries(report.by_provider),
        by_model=_to_entries(report.by_model),
        by_user=_to_entries(report.by_user),
        cost_rates_configured=rates_configured,
    )


@router.get("/analytics/usage", response_model=UsageReportResponse)
async def get_usage(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    service: Analytics_Service = Depends(get_analytics_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> UsageReportResponse:
    """Return the usage report for the caller's org over ``[start, end]`` (Req 3.1, 3.4).

    ``start`` defaults to the epoch and ``end`` to now, so an unbounded query returns the
    org's entire history. The report is scoped to ``principal.org_id`` at the data-access
    layer, so no other tenant's usage can contribute (Req 3.3, 10.5).

    ``cost_rates_configured`` reports whether this deployment prices tokens at all, so a
    client can distinguish "nothing spent" from "nothing priced" — both of which render
    as a zero total.
    """
    resolved_start = _ensure_aware(start) if start is not None else _EPOCH
    resolved_end = _ensure_aware(end) if end is not None else datetime.now(timezone.utc)
    report = await run_in_threadpool(
        lambda: service.usage_report(
            principal.org_id, start=resolved_start, end=resolved_end
        )
    )
    return _to_response(report, rates_configured=_rates_configured(settings))
