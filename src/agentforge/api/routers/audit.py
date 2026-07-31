"""Audit router: ``GET /audit-events`` — who changed what, and when.

The question no existing surface answered. Usage records say what a run cost, traces say
what an agent did, and until now nothing said who removed a member, who issued an API key,
or when an integration's configuration changed. That is the first question of every
compliance review, every access-related support ticket, and every incident postmortem.

Contract shape:

* **Org-scoped by construction.** The store takes ``principal.org_id`` as a query parameter,
  so another tenant's trail is unreachable rather than filtered afterwards — a caller cannot
  even name it, because there is no org parameter on the endpoint (Req 4.3, 4.4).
* **``read_audit_log``**, granted from ``admin`` upwards. The trail names who added and
  removed whom; that is an administrator's business, not every member's.
* **Newest first, bounded, filterable** by action, actor and time window. The action filter
  is typed against the server's own vocabulary, so the console's filter options come from
  the generated contract instead of a hardcoded list that can drift.
* **Actor labels are resolved here**, in one batched lookup, because the audit row stores an
  id. An actor that cannot be resolved (a deleted user, or an API key, which has no display
  name) is reported as ``null`` rather than dropped or guessed — the event still happened.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_audit_log, get_identity_store, require_permission
from agentforge.api.schemas import AuditEventResponse
from agentforge.enterprise.audit import Audit_Action
from agentforge.enterprise.base import Audit_Log, Identity_Store
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission

router = APIRouter(tags=["audit"])

# Bounded like the other listing endpoints: an audit trail grows without limit, so an
# unbounded page would eventually be a way to ask the database for everything.
_MAX_LIMIT = 200


def _ensure_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC, mirroring the analytics router's handling."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@router.get("/audit-events", response_model=list[AuditEventResponse])
async def list_audit_events(
    action: list[Audit_Action] | None = Query(
        default=None,
        description="Restrict to these actions. Repeat the parameter to pass several.",
    ),
    actor_id: UUID | None = Query(
        default=None, description="Restrict to events performed by this user."
    ),
    start: datetime | None = Query(
        default=None, description="Only events at or after this instant (inclusive)."
    ),
    end: datetime | None = Query(
        default=None, description="Only events at or before this instant (inclusive)."
    ),
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    audit: Audit_Log = Depends(get_audit_log),
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.READ_AUDIT_LOG)),
) -> list[AuditEventResponse]:
    """Return the caller org's audit events, newest first (Req 4.3, 4.4)."""
    events = await run_in_threadpool(
        lambda: audit.list_for_org(
            principal.org_id,
            actions=[a.value for a in action] if action else None,
            actor_user_id=actor_id,
            start=_ensure_aware(start) if start else None,
            end=_ensure_aware(end) if end else None,
            limit=limit,
        )
    )

    # One batched lookup for the whole page rather than one per row. Only user actors have a
    # label to resolve; a key actor is identified by its id.
    user_ids = [e.actor_user_id for e in events if e.actor_user_id is not None]
    emails: dict[UUID, str] = {}
    if user_ids:
        users = await run_in_threadpool(identity.list_users_by_ids, user_ids)
        emails = {user.id: user.email for user in users}

    return [
        AuditEventResponse(
            id=event.id,
            action=Audit_Action(event.action),
            actor_kind=event.actor_kind,
            actor_id=event.actor_user_id or event.actor_key_id,
            actor_email=(
                emails.get(event.actor_user_id)
                if event.actor_user_id is not None
                else None
            ),
            target_type=event.target_type,
            target_id=event.target_id,
            metadata=event.metadata,
            created_at=event.created_at,
        )
        for event in events
    ]
