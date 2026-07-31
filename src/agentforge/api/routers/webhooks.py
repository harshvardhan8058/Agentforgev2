"""Webhooks router: register outbound endpoints, test them, and read their delivery log.

Six endpoints, all ``manage_webhooks`` (granted from ``admin`` upwards), all org-scoped by
construction — the store takes ``principal.org_id`` on every call, so another tenant's
subscription is unreachable rather than filtered afterwards, and there is no org parameter for a
caller to tamper with (Req 4.3, 4.4).

* ``GET /webhooks`` — the org's subscriptions, newest first.
* ``POST /webhooks`` — register one. **The only response that carries the signing secret.**
* ``PATCH /webhooks/{id}`` — change URL, events, description, or pause it.
* ``DELETE /webhooks/{id}`` — remove it, and its delivery log with it.
* ``POST /webhooks/{id}/test`` — send a ``webhook.ping`` now and return the delivery outcome,
  so a consumer can verify their signature handling before real traffic depends on it.
* ``GET /webhooks/{id}/deliveries`` — that endpoint's delivery log, newest first, keyset
  paginated on ``(created_at, id)`` exactly like ``/audit-events``.

Two things this router is careful about:

**URL admission runs here, on every write.** ``validate_webhook_url`` resolves the host and
refuses anything internal (see ``webhooks/security.py``); a refusal is a 400, because the URL
came from the caller and they can fix it. It resolves DNS, so it goes through the threadpool
like every other blocking call in this codebase.

**The three mutations are audited.** "Who pointed a webhook at that host, and when" is the same
question the audit trail was built to answer for members, keys and budgets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_audit_service,
    get_settings,
    get_webhook_delivery_store,
    get_webhook_emitter,
    get_webhook_subscription_store,
    require_permission,
)
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    CreateWebhookRequest,
    CreateWebhookResponse,
    UpdateWebhookRequest,
    WebhookDeliveryResponse,
    WebhookSubscriptionResponse,
)
from agentforge.config.settings import Settings
from agentforge.enterprise.audit import Audit_Action, Audit_Service
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.webhooks.base import (
    Webhook_Delivery,
    Webhook_Delivery_Store,
    Webhook_Event,
    Webhook_Subscription,
    Webhook_Subscription_Store,
)
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.security import WebhookUrlRejected, generate_secret, validate_webhook_url

router = APIRouter(tags=["webhooks"])

# Bounded like every other listing endpoint: a delivery log grows without limit.
_MAX_DELIVERY_LIMIT = 200

# A test send is synchronous — the caller is waiting for the outcome — so it gets one attempt.
# Retrying would only delay the answer and hide the failure they asked to see.
_TEST_SEND_ATTEMPTS = 1


def _to_response(subscription: Webhook_Subscription) -> WebhookSubscriptionResponse:
    """Render a subscription without its secret (the model has no such field)."""
    return WebhookSubscriptionResponse(
        webhook_id=subscription.id,
        url=subscription.url,
        # Stored as plain strings; re-typed here so an event that somehow left the vocabulary
        # would be caught by the response model rather than shipped to a client.
        events=list(subscription.events),  # type: ignore[arg-type]
        description=subscription.description,
        active=subscription.active,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def _to_delivery_response(delivery: Webhook_Delivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        delivery_id=delivery.id,
        webhook_id=delivery.subscription_id,
        event=Webhook_Event(delivery.event_type),
        status=delivery.status,
        attempts=delivery.attempts,
        response_status=delivery.response_status,
        error=delivery.error,
        duration_ms=delivery.duration_ms,
        created_at=delivery.created_at,
    )


def _not_found(webhook_id: UUID) -> AppError:
    """The uniform 404 for an unknown **or** cross-tenant subscription.

    Identical in both cases on purpose: a distinguishable "exists but is not yours" would let a
    caller enumerate other tenants' webhook ids (Req 11.2).
    """
    return AppError(
        "not_found",
        "Webhook subscription not found.",
        status.HTTP_404_NOT_FOUND,
        {"webhook_id": str(webhook_id)},
    )


async def _admitted_url(url: str, settings: Settings) -> str:
    """Apply the SSRF admission policy, mapping a refusal onto a 400.

    Threadpooled because admission resolves the host: DNS is a blocking network call, and this
    runs on the event loop's thread otherwise.
    """
    try:
        return await run_in_threadpool(
            validate_webhook_url, url, allow_loopback=settings.allow_loopback_webhooks()
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
    """Return this organization's webhook subscriptions, newest first.

    Unpaginated: an organization has a handful of endpoints, not a feed of them, and the row
    count is bounded by how many integrations a team actually runs.
    """
    subscriptions = await run_in_threadpool(store.list_for_org, principal.org_id)
    return [_to_response(subscription) for subscription in subscriptions]


@router.post(
    "/webhooks",
    response_model=CreateWebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    payload: CreateWebhookRequest,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    settings: Settings = Depends(get_settings),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> CreateWebhookResponse:
    """Register an endpoint and return its signing secret **once**.

    The secret is generated here and appears in this response only; no other endpoint returns
    it. Deliveries start immediately — a new subscription is active.
    """
    url = await _admitted_url(payload.url, settings)
    events = tuple(event.value for event in payload.events)
    subscription = await run_in_threadpool(
        lambda: store.create(
            principal.org_id,
            url=url,
            events=events,
            secret=generate_secret(),
            description=payload.description,
        )
    )
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.WEBHOOK_CREATED,
        target_type="webhook",
        target_id=str(subscription.id),
        # The URL is recorded because "who pointed a webhook where" is the question. The secret
        # is not, and could not be: `admit_metadata` refuses credential-named keys outright.
        metadata={"url": url, "events": ", ".join(events)},
    )
    base = _to_response(subscription)
    return CreateWebhookResponse(**base.model_dump(), secret=subscription.secret)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookSubscriptionResponse)
async def update_webhook(
    webhook_id: UUID,
    payload: UpdateWebhookRequest,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    settings: Settings = Depends(get_settings),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookSubscriptionResponse:
    """Apply the supplied fields to a subscription. Omitted fields are left alone."""
    changed = payload.model_dump(exclude_unset=True)
    if not changed:
        raise AppError(
            "validation_error",
            "Supply at least one field to change.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    # Existence is checked before the URL is admitted, so a caller cannot use a 400-vs-404
    # difference to learn whether another tenant's webhook id exists.
    if await run_in_threadpool(store.get, principal.org_id, webhook_id) is None:
        raise _not_found(webhook_id)

    url = await _admitted_url(payload.url, settings) if payload.url is not None else None
    events = (
        tuple(event.value for event in payload.events) if payload.events is not None else None
    )
    updated = await run_in_threadpool(
        lambda: store.update(
            principal.org_id,
            webhook_id,
            url=url,
            events=events,
            description=payload.description,
            active=payload.active,
        )
    )
    if updated is None:
        # Deleted between the existence check and the update. The end state the caller wanted
        # does not exist, so the honest answer is the same 404 they would have got a moment ago.
        raise _not_found(webhook_id)

    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.WEBHOOK_UPDATED,
        target_type="webhook",
        target_id=str(webhook_id),
        # Which fields were touched, plus the resulting URL and active flag — the two whose
        # values an auditor cares about. `fields` is what distinguishes "paused" from "re-pointed"
        # when both were sent in one request.
        metadata={
            "fields": ", ".join(sorted(changed)),
            "url": updated.url,
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
    """Delete a subscription and its delivery log (the log has no reader without it).

    404 rather than a silent 204 for an unknown id: unlike ``DELETE /budget``, this names a
    specific resource, and reporting success for an id the caller made up would hide a typo.
    """
    existing = await run_in_threadpool(store.get, principal.org_id, webhook_id)
    if existing is None:
        raise _not_found(webhook_id)
    await run_in_threadpool(store.delete, principal.org_id, webhook_id)
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.WEBHOOK_DELETED,
        target_type="webhook",
        target_id=str(webhook_id),
        metadata={"url": existing.url},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookDeliveryResponse)
async def test_webhook(
    webhook_id: UUID,
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    emitter: Webhook_Emitter = Depends(get_webhook_emitter),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> WebhookDeliveryResponse:
    """Send a signed ``webhook.ping`` now and return what happened.

    Returns **200 with the delivery outcome** even when the endpoint refused or timed out: the
    request to this platform succeeded, and the consumer's failure is the payload, not an error.
    A 502 here would be indistinguishable from this API being broken.

    Ignores ``active`` and the subscription's event list — it is an explicit, addressed request,
    and verifying a paused endpoint before resuming it is exactly when this is useful. Not
    audited: it changes nothing.
    """
    subscription = await run_in_threadpool(store.get, principal.org_id, webhook_id)
    if subscription is None:
        raise _not_found(webhook_id)

    delivery = await run_in_threadpool(
        lambda: emitter.send_to(
            subscription,
            Webhook_Event.PING,
            {
                "message": "This is a test delivery from AgentForge.",
                "webhook_id": str(subscription.id),
            },
            max_attempts=_TEST_SEND_ATTEMPTS,
        )
    )
    if delivery is None:
        # The emitter declines to send only when the envelope will not serialise, which for this
        # fixed payload means the envelope shape itself is broken — a server fault, not the
        # consumer's, and not something to report as a failed delivery they should investigate.
        raise AppError(
            "internal_error",
            "The test delivery could not be prepared.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return _to_delivery_response(delivery)


@router.get(
    "/webhooks/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse]
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
            "Paired with `before`, because one event fanned out in one burst produces "
            "deliveries a timestamp alone cannot separate."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=_MAX_DELIVERY_LIMIT),
    store: Webhook_Subscription_Store = Depends(get_webhook_subscription_store),
    deliveries: Webhook_Delivery_Store = Depends(get_webhook_delivery_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_WEBHOOKS)),
) -> list[WebhookDeliveryResponse]:
    """Return this subscription's deliveries, newest first.

    The subscription is resolved first so an unknown or cross-tenant id is a 404 rather than an
    empty page — an empty page would read as "delivered nothing", which is a different fact.
    """
    if (before is None) != (before_id is None):
        raise AppError(
            "validation_error",
            "`before` and `before_id` must be supplied together: a timestamp alone cannot "
            "separate deliveries that share it.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"field": "before" if before is None else "before_id"},
        )
    if await run_in_threadpool(store.get, principal.org_id, webhook_id) is None:
        raise _not_found(webhook_id)

    cursor = (
        (_ensure_aware(before), before_id)
        if before is not None and before_id is not None
        else None
    )
    records = await run_in_threadpool(
        lambda: deliveries.list_for_subscription(
            principal.org_id, webhook_id, before=cursor, limit=limit
        )
    )
    return [_to_delivery_response(record) for record in records]
