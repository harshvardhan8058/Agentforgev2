"""Webhooks router: register endpoints, test them, and read what was delivered.

The management surface for the notification seam. Contract decisions worth stating, because
each is a trade-off rather than an obvious default:

* **Org-scoped by construction.** Every store call takes ``principal.org_id``, so another
  tenant's subscription is unreachable rather than filtered afterwards — a caller cannot even
  name it, because no endpoint has an org parameter (Req 4.3, 4.4).
* **``manage_webhooks``, granted from ``admin`` upwards**, on reads as well as writes.
  Registering an endpoint is deployment-shaped configuration, like an API key or an
  integration connection; and a delivery-log row can quote a TLS error or an internal
  hostname from the tenant's own infrastructure, so it is not ordinary member reading.
* **The secret is returned once.** ``POST`` answers with it; nothing else can produce it. See
  :mod:`agentforge.api.schemas` for why that is structural rather than a discipline.
* **The URL is admitted, not pattern-matched.** :func:`validate_webhook_url` resolves the host
  and refuses anything that is not publicly routable, which is the actual defence; a regex
  would only restate the easy half of it.
* **Test sends make exactly one attempt.** A human is waiting on the response, so retrying
  would make them sit through a backoff to learn what the first attempt already told them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_audit_service,
    get_settings,
    get_webhook_delivery_store,
    get_webhook_emitter,
    get_webhook_outbox,
    get_webhook_subscription_store,
    require_permission,
)
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    CreateWebhookRequest,
    CreateWebhookResponse,
    UpdateWebhookRequest,
    WebhookDeliveryResponse,
    WebhookQueueEntryResponse,
    WebhookQueueSummaryResponse,
    WebhookSubscriptionResponse,
)
from agentforge.config.settings import Settings
from agentforge.enterprise.audit import (
    Audit_Action,
    Audit_Service,
    AuditUnavailableError,
)
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.webhooks.base import (
    Webhook_Delivery,
    Webhook_Event,
    Webhook_Subscription,
)
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.outbox import Outbox_Entry, Webhook_Outbox
from agentforge.webhooks.security import (
    WebhookUrlRejected,
    generate_webhook_secret,
    validate_webhook_url,
)
from agentforge.webhooks.store import (
    UNSET,
    Webhook_Delivery_Store,
    Webhook_Subscription_Store,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

#: Bounded like every other listing endpoint: the delivery log grows with traffic, so an
#: unbounded page would be a way to ask the database for everything.
_MAX_DELIVERY_LIMIT = 100

#: Bounded like every other listing endpoint.
_MAX_QUEUE_LIMIT = 100

#: How many event names an audit row spells out. The count is always exact; the list is what
#: fits inside the audit metadata value bound.
_MAX_AUDITED_EVENTS = 8


def _to_response(subscription: Webhook_Subscription) -> WebhookSubscriptionResponse:
    """Render a subscription for the API. Structurally cannot carry the secret."""
    return WebhookSubscriptionResponse(
        webhook_id=subscription.id,
        url=subscription.url,
        events=[event.value for event in subscription.events],
        description=subscription.description,
        active=subscription.active,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def _to_delivery_response(delivery: Webhook_Delivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        delivery_id=delivery.id,
        webhook_id=delivery.subscription_id,
        event=delivery.event,
        status=delivery.status,
        attempts=delivery.attempts,
        response_status=delivery.response_status,
        error=delivery.error,
        duration_ms=delivery.duration_ms,
        created_at=delivery.created_at,
    )


def _audited_destination(url: str) -> str:
    """Return the origin of ``url`` — scheme, host, and port — for an audit row.

    Deliberately NOT the whole URL. A webhook URL's path and query routinely *are* the
    credential (a Slack incoming hook, a ``?token=`` handler), and an audit row is read by more
    people than any other record in the system. The origin is the auditable fact — which
    endpoint this organization pointed at — and the part that cannot be a secret.
    """
    parts = urlsplit(url)
    host = parts.hostname or "?"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


def _events_metadata(subscription: Webhook_Subscription) -> dict[str, object]:
    """Audit metadata describing which events a subscription carries."""
    names = [event.value for event in subscription.events]
    shown = names[:_MAX_AUDITED_EVENTS]
    return {
        "event_count": len(names),
        "events": ", ".join(shown) + (", \u2026" if len(names) > len(shown) else ""),
    }


def _not_found(webhook_id: UUID) -> AppError:
    """Build the uniform 404 for an unknown or cross-tenant subscription.

    404 rather than 403 on purpose: a 403 would confirm that the id exists in *some*
    organization, which is a cross-tenant disclosure through the status code alone.
    """
    return AppError(
        "not_found",
        "Webhook subscription not found.",
        status.HTTP_404_NOT_FOUND,
        {"webhook_id": str(webhook_id)},
    )


def _admitted_url(url: str, settings: Settings) -> str:
    """Apply the SSRF admission policy, mapping a refusal onto a 400 naming the field.

    Only :class:`WebhookUrlRejected` is caught because the validator is written to raise
    nothing else: a malformed port and an unresolvable IDN label are both mapped onto a
    refusal inside it, precisely so they surface here as 400s rather than as 500s on a field
    the API is supposed to be validating.
    """
    try:
        return validate_webhook_url(
            url, allow_loopback=settings.allow_loopback_webhooks()
        )
    except WebhookUrlRejected as exc:
        raise AppError(
            "invalid_webhook_url",
            str(exc),
            status.HTTP_400_BAD_REQUEST,
            {"field": "url"},
        ) from exc


def _ensure_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC, mirroring the audit and analytics routers."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@router.get("/webhooks", response_model=list[WebhookSubscriptionResponse])
async def list_webhooks(
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> list[WebhookSubscriptionResponse]:
    """Return the caller org's webhook subscriptions, oldest first. Never includes secrets."""
    subscriptions = await run_in_threadpool(store.list_for_org, principal.org_id)
    return [_to_response(s) for s in subscriptions]


@router.post(
    "/webhooks",
    response_model=CreateWebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    payload: CreateWebhookRequest,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    audit: Audit_Service = Depends(get_audit_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> CreateWebhookResponse:
    """Register a webhook endpoint and return its signing secret — once (Req 4.3, 4.4).

    The per-org cap is enforced here rather than left to the database, because the reason for
    it is behavioural: every subscription multiplies the work one emitted event performs, and
    an org with hundreds of endpoints would turn a single run into minutes of outbound HTTP.

    If the audit write fails in a deployment configured to require it, the subscription is
    **deleted again** before the error is returned. Ordinarily an unrecorded-but-applied change
    is reported as exactly that (the 503 ``audit_unavailable`` contract), but this one mutation
    cannot be left standing: the caller never received the secret, no read path can produce it,
    and there is no rotation endpoint — so the row would be a live endpoint nobody could ever
    verify a signature against.
    """
    # DNS resolution inside the validator is blocking, so admission runs in a worker thread
    # like every other synchronous call on this path.
    url = await run_in_threadpool(_admitted_url, payload.url, settings)

    existing = await run_in_threadpool(store.count_for_org, principal.org_id)
    if existing >= settings.webhook_max_per_org:
        raise AppError(
            "webhook_limit_reached",
            "This organization already has the maximum number of webhook subscriptions. "
            "Delete one before registering another.",
            status.HTTP_409_CONFLICT,
            {"limit": settings.webhook_max_per_org},
        )

    secret = generate_webhook_secret()
    subscription = await run_in_threadpool(
        lambda: store.create(
            principal.org_id,
            url=url,
            secret=secret,
            events=tuple(Webhook_Event(e.value) for e in payload.events),
            description=payload.description,
            active=payload.active,
        )
    )

    try:
        await run_in_threadpool(
            audit.record,
            principal,
            Audit_Action.WEBHOOK_CREATED,
            target_type="webhook",
            target_id=str(subscription.id),
            metadata={
                # The ORIGIN, never the full URL — see _audited_destination.
                "destination": _audited_destination(url),
                "active": subscription.active,
                **_events_metadata(subscription),
            },
        )
    except AuditUnavailableError:
        await run_in_threadpool(store.delete, principal.org_id, subscription.id)
        logger.warning(
            "Rolled back webhook subscription %s: its creation could not be audited.",
            subscription.id,
        )
        raise

    return CreateWebhookResponse(webhook=_to_response(subscription), secret=secret)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookSubscriptionResponse)
async def update_webhook(
    webhook_id: UUID,
    payload: UpdateWebhookRequest,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    audit: Audit_Service = Depends(get_audit_service),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookSubscriptionResponse:
    """Apply a partial update; unknown or cross-tenant is 404, a rejected URL is 400.

    Only the fields present in the request body are touched, so ``{"active": false}`` pauses a
    subscription without disturbing anything else, and ``{"description": null}`` clears the
    description rather than being silently ignored. The secret is never changed here: rotation
    is a different operation with a different response shape (it would have to return the new
    secret), and pretending an update could do it would be the worst of both.
    """
    supplied = payload.model_fields_set
    if not supplied:
        raise AppError(
            "validation_error",
            "A webhook update must change at least one field.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            # Same shape as the framework's own validation errors, so a client has one parser.
            {"errors": [{"loc": ["body"], "msg": "no fields supplied", "type": "value_error"}]},
        )

    url = UNSET
    if "url" in supplied and payload.url is not None:
        url = await run_in_threadpool(_admitted_url, payload.url, settings)

    events = UNSET
    if "events" in supplied and payload.events is not None:
        events = tuple(Webhook_Event(e.value) for e in payload.events)

    description = payload.description if "description" in supplied else UNSET
    active = payload.active if "active" in supplied and payload.active is not None else UNSET

    updated = await run_in_threadpool(
        lambda: store.update(
            principal.org_id,
            webhook_id,
            url=url,
            events=events,
            description=description,
            active=active,
        )
    )
    if updated is None:
        raise _not_found(webhook_id)

    # Which fields changed is the auditable fact; the values are recorded only where they are
    # safe and useful (the destination origin, and the active flag, which is the one an
    # operator asks about after "why did notifications stop").
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.WEBHOOK_UPDATED,
        target_type="webhook",
        target_id=str(webhook_id),
        metadata={
            "fields": ", ".join(sorted(supplied)),
            "destination": _audited_destination(updated.url),
            "active": updated.active,
        },
    )
    return _to_response(updated)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> Response:
    """Delete a subscription and its delivery log; unknown or cross-tenant is 404.

    The log goes with it (``ON DELETE CASCADE``, mirrored by the in-memory store). That is
    deliberate: a delivery record describes a subscription and is meaningless without it, and
    deleting the subscription is the tenant's only way to remove that history.
    """
    doomed = await run_in_threadpool(store.get, principal.org_id, webhook_id)
    deleted = await run_in_threadpool(store.delete, principal.org_id, webhook_id)
    if not deleted:
        raise _not_found(webhook_id)
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.WEBHOOK_DELETED,
        target_type="webhook",
        target_id=str(webhook_id),
        metadata={
            "destination": (
                _audited_destination(doomed.url) if doomed is not None else None
            )
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=WebhookDeliveryResponse,
)
async def test_webhook(
    webhook_id: UUID,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    emitter: Webhook_Emitter = Depends(get_webhook_emitter),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookDeliveryResponse:
    """Send a ``webhook.ping`` to one subscription and report the result synchronously.

    The one delivery that is **not** queued, and the only one that should not be: an operator who
    has just pasted a URL needs to know *now* whether it works, and the whole point is to find out
    before real events depend on it. Bounded to a single attempt so the response time is one
    endpoint timeout rather than a retry schedule that now spans hours.

    Works on a paused subscription too — verifying an endpoint before activating it is exactly
    the workflow, and refusing would make ``active: false`` mean "untestable".
    """
    subscription = await run_in_threadpool(store.get, principal.org_id, webhook_id)
    if subscription is None:
        raise _not_found(webhook_id)

    delivery = await run_in_threadpool(
        lambda: emitter.send_test(
            subscription,
            {
                "message": "This is a test delivery from AgentForge.",
                "webhook_id": str(subscription.id),
            },
        )
    )
    if delivery is None:
        # Unreachable with the payload above (it is plainly serialisable); reported rather than
        # asserted because the emitter's contract permits it and a silent None would surface as
        # a confusing validation error instead of an honest 500.
        raise AppError(
            "internal_error",
            "The test delivery could not be prepared.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return _to_delivery_response(delivery)


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
)
async def list_webhook_deliveries(
    webhook_id: UUID,
    before: datetime | None = Query(
        default=None,
        description=(
            "Keyset cursor: the `created_at` of the last delivery of the previous page. "
            "Must be sent together with `before_id`."
        ),
    ),
    before_id: UUID | None = Query(
        default=None,
        description=(
            "Keyset cursor: the `delivery_id` of the last delivery of the previous page. "
            "Paired with `before` so a page boundary cannot repeat or skip deliveries that "
            "share a timestamp — one fan-out writes several in the same millisecond."
        ),
    ),
    limit: int = Query(default=25, ge=1, le=_MAX_DELIVERY_LIMIT),
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    deliveries: Webhook_Delivery_Store = Depends(get_webhook_delivery_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> list[WebhookDeliveryResponse]:
    """Return one subscription's deliveries, newest first, keyset-paginated.

    The subscription is looked up first so an unknown or cross-tenant id is a 404 rather than
    an empty list: "no deliveries yet" and "not your webhook" are different answers, and
    conflating them would make a broken integration indistinguishable from a typo.
    """
    if (before is None) != (before_id is None):
        raise AppError(
            "validation_error",
            "`before` and `before_id` must be supplied together: a timestamp alone cannot "
            "separate deliveries that share it.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"field": "before" if before is None else "before_id"},
        )

    subscription = await run_in_threadpool(store.get, principal.org_id, webhook_id)
    if subscription is None:
        raise _not_found(webhook_id)

    rows = await run_in_threadpool(
        lambda: deliveries.list_for_subscription(
            principal.org_id,
            webhook_id,
            before=(
                (_ensure_aware(before), before_id)
                if before is not None and before_id is not None
                else None
            ),
            limit=limit,
        )
    )
    return [_to_delivery_response(row) for row in rows]



# --- the delivery queue -----------------------------------------------------------
#
# Durable delivery is only half a feature without a way to see it. These two endpoints are what
# turn "your webhook did not arrive" from a support conversation into something an operator can
# answer, and act on, themselves.


def _to_queue_entry(entry: Outbox_Entry) -> WebhookQueueEntryResponse:
    return WebhookQueueEntryResponse(
        entry_id=entry.id,
        webhook_id=entry.subscription_id,
        event=entry.event,
        # `delivered` is filtered out before this point; the narrower response type says so.
        status="abandoned" if entry.status == "abandoned" else "pending",
        attempts=entry.attempts,
        next_attempt_at=entry.next_attempt_at,
        last_error=entry.last_error,
        idempotency_key=entry.idempotency_key,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.get("/webhooks/queue", response_model=WebhookQueueSummaryResponse)
async def list_webhook_queue(
    status_filter: Literal["pending", "abandoned"] | None = Query(
        default=None,
        alias="status",
        description=(
            "Restrict to `pending` (still scheduled) or `abandoned` (gave up). Omit for both."
        ),
    ),
    limit: int = Query(default=25, ge=1, le=_MAX_QUEUE_LIMIT),
    outbox: Webhook_Outbox = Depends(get_webhook_outbox),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookQueueSummaryResponse:
    """Return this organization's outstanding webhook deliveries, newest first.

    Org-scoped rather than per-subscription because the question an operator arrives with is "is
    anything stuck?", not "is anything stuck for endpoint 3 of 4" — and an event can outlive the
    subscription page it was created from.

    Delivered entries are deliberately excluded: what arrived is the delivery log's job to report,
    and answering it in two places invites the two answers to disagree.
    """
    counts = await run_in_threadpool(outbox.status_counts, principal.org_id)
    entries = await run_in_threadpool(
        lambda: outbox.list_outstanding(
            principal.org_id, status=status_filter, limit=limit
        )
    )
    return WebhookQueueSummaryResponse(
        pending=counts.get("pending", 0),
        abandoned=counts.get("abandoned", 0),
        entries=[_to_queue_entry(entry) for entry in entries],
    )


@router.post(
    "/webhooks/queue/{entry_id}/redeliver",
    response_model=WebhookQueueEntryResponse,
)
async def redeliver_webhook_queue_entry(
    entry_id: UUID,
    outbox: Webhook_Outbox = Depends(get_webhook_outbox),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookQueueEntryResponse:
    """Put an abandoned entry back in the queue, due immediately, with a fresh attempt schedule.

    Only **abandoned** entries can be redelivered, and the restriction is not bureaucracy: a
    pending entry is already scheduled, so requeueing it would be asking for the same event to be
    delivered twice. A ``409`` says which case the caller hit rather than silently doing nothing.

    The redelivery is audited, because it is a human choosing to re-send something the platform had
    given up on — exactly the kind of action somebody asks about afterwards.
    """
    requeued = await run_in_threadpool(outbox.requeue, principal.org_id, entry_id)
    if requeued is None:
        existing = await run_in_threadpool(outbox.get, principal.org_id, entry_id)
        if existing is None:
            raise AppError(
                "not_found",
                "Queued webhook delivery not found.",
                status.HTTP_404_NOT_FOUND,
                {"entry_id": str(entry_id)},
            )
        raise AppError(
            "not_redeliverable",
            "Only an abandoned delivery can be redelivered; this one is "
            f"{existing.status}.",
            status.HTTP_409_CONFLICT,
            {"entry_id": str(entry_id), "status": existing.status},
        )

    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.WEBHOOK_REDELIVERED,
        target_type="webhook",
        target_id=str(requeued.subscription_id),
        metadata={"entry_id": str(entry_id), "event": requeued.event.value},
    )
    return _to_queue_entry(requeued)
