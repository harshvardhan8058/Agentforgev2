"""Budget router: read the organization's spend standing, and set or clear its ceiling.

The platform measured cost and could not limit it. These three endpoints close that:

* ``GET /budget`` — where the org stands this period (spent, limit, remaining, blocked).
  Requires only ``read``: a member about to be refused should be able to see why, and the
  numbers are the same ones ``/analytics/usage`` already shows them.
* ``PUT /budget`` — set the ceiling and what happens at it. ``manage_budget``, owner-only:
  a spend limit is a financial control, and the role that owns the organization owns it.
* ``DELETE /budget`` — remove the ceiling (spend becomes unlimited again).

Both mutations are recorded in the audit trail, so "who raised the limit, and when" is
answerable — that question is why the audit trail was built first.

Singular ``/budget``, not ``/budgets``: there is exactly one per organization, and the path
should not imply a collection that does not exist.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Response, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_audit_service,
    get_budget_alert_service,
    get_budget_guard,
    get_budget_store,
    require_permission,
)
from agentforge.api.schemas import BudgetStatusResponse, SetBudgetRequest
from agentforge.enterprise.audit import Audit_Action, Audit_Service
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.budget import Budget_Guard, Budget_Status, Budget_Store
from agentforge.observability.budget_alerts import Budget_Alert_Service

router = APIRouter(tags=["budget"])


def _to_response(status_: Budget_Status) -> BudgetStatusResponse:
    """Render a Budget_Status, keeping every monetary value an exact decimal string."""
    remaining = status_.remaining
    percent = status_.percent_used
    return BudgetStatusResponse(
        period_start=status_.period_start,
        period_end=status_.period_end,
        spent=str(status_.spent),
        limit_amount=str(status_.limit_amount) if status_.limit_amount is not None else None,
        remaining=str(remaining) if remaining is not None else None,
        # Rounded for display only, and only here: a percentage is a presentation artefact,
        # unlike `spent`/`limit_amount`/`remaining`, which cross verbatim.
        percent_used=(
            str(percent.quantize(Decimal("0.01"))) if percent is not None else None
        ),
        action=status_.action,
        exceeded=status_.exceeded,
        blocked=status_.blocked,
    )


@router.get("/budget", response_model=BudgetStatusResponse)
async def get_budget(
    guard: Budget_Guard = Depends(get_budget_guard),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> BudgetStatusResponse:
    """Return this organization's spend standing for the current calendar month (UTC).

    ``limit_amount`` is ``null`` when no budget is set, which is the unlimited default —
    distinguishable from a budget of ``"0"``, which means "spend nothing" and is reported as
    fully used.
    """
    status_ = await run_in_threadpool(guard.status, principal.org_id)
    return _to_response(status_)


@router.put("/budget", response_model=BudgetStatusResponse)
async def set_budget(
    payload: SetBudgetRequest,
    store: Budget_Store = Depends(get_budget_store),
    guard: Budget_Guard = Depends(get_budget_guard),
    alerts: Budget_Alert_Service = Depends(get_budget_alert_service),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_BUDGET)),
) -> BudgetStatusResponse:
    """Set (or replace) the monthly ceiling and its action. Idempotent — hence ``PUT``."""
    budget = await run_in_threadpool(
        store.upsert,
        principal.org_id,
        limit_amount=payload.limit_amount,
        action=payload.action,
    )
    # Raising a ceiling must take effect now, not after the cache window: an owner unblocking
    # their own organization should not have to wait, and waiting would look like a bug.
    guard.invalidate(principal.org_id)
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.BUDGET_SET,
        target_type="budget",
        target_id=str(principal.org_id),
        metadata={"limit_amount": str(budget.limit_amount), "action": budget.action},
    )
    status_ = await run_in_threadpool(guard.status, principal.org_id)
    # Threshold notifications are claimed once per period, so a ceiling change has to reconcile
    # them: raising a budget from 100 to 1000 puts the org back under 80%, and without this the
    # next genuine crossing would be silent because the old ceiling's claim still stood.
    await run_in_threadpool(alerts.reconcile, status_)
    return _to_response(status_)


@router.delete("/budget", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    store: Budget_Store = Depends(get_budget_store),
    guard: Budget_Guard = Depends(get_budget_guard),
    alerts: Budget_Alert_Service = Depends(get_budget_alert_service),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_BUDGET)),
) -> Response:
    """Remove the ceiling, returning the organization to unlimited spend.

    Idempotent: removing an absent budget is a 204, not a 404. The desired end state — no
    ceiling — is what the caller asked for, and it holds either way.
    """
    removed = await run_in_threadpool(store.delete, principal.org_id)
    guard.invalidate(principal.org_id)
    # No ceiling means no threshold is crossed, so every claim for this period goes: setting a
    # budget again later should notify from scratch rather than inherit the old one's history.
    status_ = await run_in_threadpool(guard.status, principal.org_id)
    await run_in_threadpool(alerts.reconcile, status_)
    if removed:
        await run_in_threadpool(
            audit.record,
            principal,
            Audit_Action.BUDGET_REMOVED,
            target_type="budget",
            target_id=str(principal.org_id),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
