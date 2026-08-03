"""FastAPI dependency wiring for the Phase 2 routers.

The composition root (``config/container.py``) builds a single :class:`AppContext`
holding the wired object graph (providers, vector store, and services). It is stored on
``app.state.app_context`` at startup (or injected directly by tests). These dependency
callables surface that graph — and its individual collaborators — to the routers so the
transport layer never constructs providers itself and stays trivially testable with
injected fakes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, Request, status
from fastapi.concurrency import run_in_threadpool

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.api.errors import AppError
from agentforge.config.container import (
    AgentContext,
    AppContext,
    EnterpriseContext,
    MultiAgentContext,
    ObservabilityContext,
    build_integration_connection_store,
    build_integration_status_service,
)
from agentforge.config.settings import Settings
from agentforge.conversation.base import Conversation_Store
from agentforge.enterprise.api_keys import API_Key_Service
from agentforge.enterprise.auth import Auth_Service
from agentforge.enterprise.audit import Audit_Service
from agentforge.enterprise.base import Audit_Log, Identity_Store, Rate_Limiter
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind, principal_key
from agentforge.enterprise.rbac import Permission, RBAC_Policy
from agentforge.enterprise.tenancy import set_current_org, set_current_user
from agentforge.ingestion.service import Ingestion_Service
from agentforge.integrations.connection import Integration_Connection_Store
from agentforge.integrations.status import Integration_Status_Service
from agentforge.observability.analytics import Analytics_Service
from agentforge.observability.evaluation.base import Evaluation_Store
from agentforge.observability.evaluation.framework import Evaluation_Framework
from agentforge.observability.guardrails.base import Guardrail_Pipeline
from agentforge.observability.prompt_registry.registry import Prompt_Registry
from agentforge.observability.budget import Budget_Guard, Budget_Store
from agentforge.observability.budget_alerts import Budget_Alert_Service
from agentforge.observability.trace_export import (
    Trace_Export_Service,
    disabled_trace_export_service,
)
from agentforge.observability.tracing_exporter import Tracing_Exporter
from agentforge.rag.service import RAG_Service
from agentforge.storage.base import DocumentStore
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.tracing.base import Trace_Recorder
from agentforge.vectorstore.base import Vector_Store
from agentforge.webhooks.emitter import Webhook_Emitter, disabled_webhook_emitter
from agentforge.webhooks.store import (
    Webhook_Delivery_Store,
    Webhook_Subscription_Store,
)


logger = logging.getLogger(__name__)


def get_app_context(request: Request) -> AppContext:
    """Return the wired application context from ``app.state``.

    Raises:
        RuntimeError: if the context was never initialized (misconfiguration).
    """
    ctx = getattr(request.app.state, "app_context", None)
    if ctx is None:  # pragma: no cover - defensive; startup always sets this
        raise RuntimeError("Application context is not initialized")
    return ctx


def get_ingestion_service(request: Request) -> Ingestion_Service:
    """Return the wired Ingestion_Service."""
    return get_app_context(request).ingestion_service


def get_rag_service(request: Request) -> RAG_Service:
    """Return the wired RAG_Service."""
    return get_app_context(request).rag_service


def get_document_store(request: Request) -> DocumentStore:
    """Return the wired relational DocumentStore."""
    return get_app_context(request).document_store


def get_vector_store(request: Request) -> Vector_Store:
    """Return the wired Vector_Store."""
    return get_app_context(request).vector_store


# --- Phase 3 agentic-layer accessors ----------------------------------------------


def get_agent_context(request: Request) -> AgentContext:
    """Return the wired agentic context from ``app.state``.

    Raises:
        RuntimeError: if the context was never initialized (misconfiguration).
    """
    ctx = getattr(request.app.state, "agent_context", None)
    if ctx is None:  # pragma: no cover - defensive; startup always sets this
        raise RuntimeError("Agent context is not initialized")
    return ctx


def get_conversation_store(request: Request) -> Conversation_Store:
    """Return the wired Conversation_Store."""
    return get_agent_context(request).conversation_store


def get_orchestrator(request: Request) -> Agent_Orchestrator:
    """Return the wired Agent_Orchestrator."""
    return get_agent_context(request).orchestrator


def get_trace_recorder(request: Request) -> Trace_Recorder:
    """Return the wired Trace_Recorder."""
    return get_agent_context(request).trace_recorder


def get_streaming_service(request: Request) -> SSE_Streaming_Service:
    """Return the wired Streaming_Service."""
    return get_agent_context(request).streaming_service



# --- Phase 4 multi-agent accessors ------------------------------------------------


def get_multi_agent_context(request: Request) -> MultiAgentContext:
    """Return the wired multi-agent context from ``app.state``.

    Mirrors :func:`get_agent_context`: the composition root stores the wired
    :class:`MultiAgentContext` on ``app.state.multi_agent_context`` at startup (or a test
    pre-injects one). Routers depend on this accessor so the transport layer never
    constructs the multi-agent object graph itself.
    """
    ctx = getattr(request.app.state, "multi_agent_context", None)
    if ctx is None:  # pragma: no cover - defensive; startup always sets this
        raise RuntimeError("Multi-agent context is not initialized")
    return ctx



# --- Phase 5 enterprise accessors -------------------------------------------------


def get_settings(request: Request) -> Settings:
    """Return the active :class:`Settings` from ``app.state``.

    Raises:
        RuntimeError: if configuration was never initialized (misconfiguration).
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:  # pragma: no cover - defensive; startup always sets this
        raise RuntimeError("Settings are not initialized")
    return settings


def get_enterprise_context(request: Request) -> EnterpriseContext:
    """Return the wired :class:`EnterpriseContext` from ``app.state``.

    Mirrors :func:`get_agent_context`: the composition root stores the wired enterprise
    object graph (auth service, identity store, RBAC policy, API-key service, and rate
    limiter) on ``app.state.enterprise_context`` at startup (or a test pre-injects one).

    Raises:
        RuntimeError: if the context was never initialized (misconfiguration).
    """
    ctx = getattr(request.app.state, "enterprise_context", None)
    if ctx is None:  # pragma: no cover - defensive; startup always sets this
        raise RuntimeError("Enterprise context is not initialized")
    return ctx


def get_auth_service(request: Request) -> Auth_Service:
    """Return the wired Auth_Service."""
    return get_enterprise_context(request).auth_service


def get_identity_store(request: Request) -> Identity_Store:
    """Return the wired Identity_Store."""
    return get_enterprise_context(request).identity_store


def get_api_key_service(request: Request) -> API_Key_Service:
    """Return the wired API_Key_Service."""
    return get_enterprise_context(request).api_key_service


def get_rbac_policy(request: Request) -> RBAC_Policy:
    """Return the wired RBAC_Policy."""
    return get_enterprise_context(request).rbac


def get_audit_log(request: Request) -> Audit_Log:
    """Return the wired Audit_Log (the append-only administrative trail)."""
    return get_enterprise_context(request).audit_log


def get_audit_service(request: Request) -> Audit_Service:
    """Return the wired Audit_Service, which records events for the acting Principal."""
    return get_enterprise_context(request).audit_service


def get_rate_limiter(request: Request) -> Rate_Limiter:
    """Return the wired Rate_Limiter."""
    return get_enterprise_context(request).rate_limiter


def _extract_bearer_token(request: Request) -> str | None:
    """Return the token from an ``Authorization: Bearer <jwt>`` header, else ``None``.

    A missing header, a non-Bearer scheme, or an empty token all yield ``None`` so the
    caller falls through to the ``X-API-Key`` path uniformly.
    """
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _unauthorized() -> AppError:
    """Build the uniform 401 for a missing/invalid credential (Req 1.5, 5.6, 7.1)."""
    return AppError(
        "unauthorized",
        "Authentication is required.",
        status.HTTP_401_UNAUTHORIZED,
    )


def get_current_principal(
    request: Request,
    auth: Auth_Service = Depends(get_auth_service),
    keys: API_Key_Service = Depends(get_api_key_service),
    rbac: RBAC_Policy = Depends(get_rbac_policy),
    rate_limiter: Rate_Limiter = Depends(get_rate_limiter),
) -> Principal:
    """Resolve the current :class:`Principal` from a Bearer token or an ``X-API-Key``.

    Resolution order (Req 1.4, 1.5, 5.3, 7.1):

    * An ``Authorization: Bearer <jwt>`` header is tried first. Valid claims yield a User
      Principal; a present-but-invalid token (bad signature, wrong secret, expired,
      malformed) raises ``AppError("unauthorized", 401)`` — it does **not** fall through.
    * Otherwise an ``X-API-Key`` header is resolved to an API-key Principal; an
      unknown or revoked key raises 401.
    * No credential at all raises 401.

    After a Principal is resolved, the Rate_Limiter is consulted (Req 6.1); it may raise
    ``AppError("rate_limited", 429)``.
    """
    token = _extract_bearer_token(request)
    if token is not None:
        claims = auth.verify(token)
        if claims is None:
            raise _unauthorized()
        principal = Principal(
            kind=PrincipalKind.USER.value,
            user_id=claims.sub,
            key_id=None,
            org_id=claims.org_id,
            role=claims.role,
            permissions=rbac.permissions_for(claims.role),
        )
    else:
        secret = request.headers.get("X-API-Key")
        if not secret:
            raise _unauthorized()
        api_key = keys.resolve_key(secret)
        if api_key is None:
            raise _unauthorized()
        principal = Principal(
            kind=PrincipalKind.API_KEY.value,
            user_id=None,
            key_id=api_key.id,
            org_id=api_key.org_id,
            role=api_key.role,
            permissions=rbac.permissions_for(api_key.role),
        )

    # Per-principal rate limiting (no-op in the keyless default; Req 6.1, 6.5).
    rate_limiter.check(principal_key(principal))
    return principal


async def bind_request_tenancy(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Publish the acting tenant and user for the rest of the request.

    ``enterprise/tenancy`` exists so cross-cutting consumers that cannot widen their
    contract — the ``RAG_Tool``, trace writes, and the ``Instrumented_Provider`` that
    emits usage records — can still attribute work to the right principal. The
    orchestrator entry points published the *org*, but nothing ever published the
    *user*, so every usage record was written with ``user_id=None`` and the analytics
    "by user" breakdown collapsed into a single blank key. Endpoints that never enter an
    orchestrator (notably ``POST /query``) published neither, so their usage was
    attributed to ``NIL_ORG_ID`` and never appeared in the caller's analytics at all.

    Binding both here fixes every endpoint at once, because every authorized route
    resolves its principal through :func:`require_permission`.

    This is deliberately ``async``: FastAPI runs *synchronous* dependencies in a worker
    thread, and a ``ContextVar`` set on a worker thread is not visible to the request
    that spawned it. Declared ``async`` it runs on the request's own task, so the values
    are in force for the handler and for anything it later hands to
    ``run_in_threadpool`` (which copies the current context).
    """
    set_current_org(principal.org_id)
    # ``None`` for an API-key principal, which is an unattributed caller by construction.
    set_current_user(principal.user_id)
    return principal


def require_permission(permission: Permission) -> Callable[..., Principal]:
    """Return a dependency enforcing ``permission`` on the current Principal (Req 7.7).

    The returned callable resolves the Principal through :func:`bind_request_tenancy`
    (which publishes the request-scoped org and user) and raises
    ``AppError("forbidden", 403, {"required": permission})`` when the Principal's Role
    does not grant ``permission``; otherwise it returns the Principal so the handler can
    thread ``principal.org_id`` into an org-scoped store call. Adding a new endpoint
    adopts authorization by declaration alone — no bespoke logic in the handler (Req 3.6).
    """

    def _dep(principal: Principal = Depends(bind_request_tenancy)) -> Principal:
        if permission not in principal.permissions:
            raise AppError(
                "forbidden",
                "Missing required permission.",
                status.HTTP_403_FORBIDDEN,
                {"required": permission.value},
            )
        return principal

    return _dep


def get_org_id(principal: Principal = Depends(get_current_principal)) -> UUID:
    """Return ``principal.org_id`` for stores that only need the tenant key (Req 4.4)."""
    return principal.org_id


# --- Phase 6 observability accessors ----------------------------------------------


def get_observability_context(request: Request) -> ObservabilityContext:
    """Return the wired :class:`ObservabilityContext` from ``app.state``.

    Mirrors :func:`get_enterprise_context`: the composition root stores the wired
    observability object graph (tracing exporter, usage store/recorder/sink, cost model,
    analytics service, prompt registry, guardrail pipeline, evaluation framework) on
    ``app.state.observability_context`` at startup (or a test pre-injects one). The Phase
    6 routers depend on the per-seam accessors below so the transport layer never
    constructs the observability graph itself (Req 7.3, 9.7).

    Raises:
        RuntimeError: if the context was never initialized (misconfiguration).
    """
    ctx = getattr(request.app.state, "observability_context", None)
    if ctx is None:  # pragma: no cover - defensive; startup always sets this
        raise RuntimeError("Observability context is not initialized")
    return ctx


def get_tracing_exporter(request: Request) -> Tracing_Exporter:
    """Return the wired Tracing_Exporter."""
    return get_observability_context(request).tracing_exporter


def get_trace_export_service(request: Request) -> Trace_Export_Service:
    """Return the wired Trace_Export_Service, or a disabled one if none is wired.

    Unlike every other observability accessor, this one does **not** raise when the context
    is missing. It is consumed by the *run* endpoints, and the whole point of the export
    path is that it can never affect a run: turning a missing observability context into a
    500 on ``POST /agent/run`` would make an observability concern fail the very work it is
    supposed to be observing. A partially-wired app (a focused test, or a future entry
    point that composes only the agentic graph) therefore runs agents normally with export
    reported as unavailable.

    The observability *routers* keep using :func:`get_observability_context`, where a
    missing context is a genuine misconfiguration and must still fail loudly.
    """
    ctx = getattr(request.app.state, "observability_context", None)
    if ctx is None:
        return disabled_trace_export_service()
    return ctx.trace_export_service


async def enforce_budget(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Refuse new work when the org is over a **blocking** spend budget (Req 3.x, 8.x).

    Applied to the endpoints that *spend* — RAG query, agent run/stream, multi-agent run/stream
    — and to nothing else: reading a trace or listing documents costs nothing, and blocking
    those would punish an over-budget tenant by hiding the very data that explains the
    overage.

    Returns the Principal so an endpoint can depend on this *instead of* re-declaring the
    principal, keeping the dependency list honest about what it enforces.

    Deliberately not enforced here:

    * a ``warn`` budget never refuses anything — it is a reporting posture, and turning it
      into enforcement would make an operator's monitoring choice break their traffic;
    * if spend cannot be computed the guard reports zero and this passes, because a metering
      outage must not become a platform outage (the guard logs it).

    The refusal is ``402 Payment Required`` with ``budget_exceeded``: the request was
    well-formed and authorized, and what stands in its way is a spending limit — which is
    precisely what 402 means. A 429 would claim a rate problem that retrying could solve.
    """
    ctx = getattr(request.app.state, "observability_context", None)
    if ctx is None:
        # No governance graph wired (a focused test, or an entry point that composes only the
        # agentic graph). Enforcing nothing is the correct fail-open: a *missing* budget is an
        # unlimited one, and a governance concern must never be the reason work cannot run.
        return principal
    status_ = await run_in_threadpool(ctx.budget_guard.status, principal.org_id)

    # Threshold notifications ride the status this dependency already computed, so warning an
    # owner costs no extra aggregation. `pending` is pure and consults an in-process memo, so the
    # overwhelming majority of requests — no ceiling, nowhere near it, or already notified —
    # schedule nothing at all.
    #
    # `dispatch` hands the work to the alert service's own small pool rather than to this
    # request's `BackgroundTasks`. Those are shared with the routers, so an announcement would
    # queue ahead of trace export and the `run.completed` webhook; and on a streamed response
    # they are attached to the response, which would hold the client's connection open for a
    # subscriber's timeout. It also bounds the blast radius: a slow endpoint occupies one
    # dedicated worker instead of a share of the pool every store call in the platform uses.
    alerts = ctx.budget_alert_service
    if alerts.pending(status_):
        alerts.dispatch(status_)

    if status_.blocked:
        logger.warning(
            "Refusing work for org %s: spend %s has reached the budget of %s.",
            principal.org_id,
            status_.spent,
            status_.limit_amount,
        )
        raise AppError(
            "budget_exceeded",
            "This organization has reached its spend budget for the current period. "
            "New runs are blocked until the period resets or the budget is raised.",
            status.HTTP_402_PAYMENT_REQUIRED,
            {
                "spent": str(status_.spent),
                "limit_amount": str(status_.limit_amount),
                "period_end": status_.period_end.isoformat(),
            },
        )
    return principal


def get_budget_store(request: Request) -> Budget_Store:
    """Return the wired Budget_Store (the org's spend ceiling)."""
    return get_observability_context(request).budget_store


def get_budget_alert_service(request: Request) -> Budget_Alert_Service:
    """Return the wired Budget_Alert_Service (threshold notifications, claimed once)."""
    return get_observability_context(request).budget_alert_service


def get_budget_guard(request: Request) -> Budget_Guard:
    """Return the wired Budget_Guard (spend status + the enforcement decision)."""
    return get_observability_context(request).budget_guard


def get_webhook_subscription_store(request: Request) -> Webhook_Subscription_Store:
    """Return the wired Webhook_Subscription_Store (the org's webhook endpoints)."""
    return get_observability_context(request).webhook_subscription_store


def get_webhook_delivery_store(request: Request) -> Webhook_Delivery_Store:
    """Return the wired Webhook_Delivery_Store (what was sent, and what happened)."""
    return get_observability_context(request).webhook_delivery_store


def get_webhook_emitter(request: Request) -> Webhook_Emitter:
    """Return the wired Webhook_Emitter, or an inert one if no context is wired.

    Deliberately non-raising, exactly like :func:`get_trace_export_service` and for the same
    reason: the emitter is consumed by the *run* endpoints, so turning a missing observability
    context into a 500 on ``POST /agent/run`` would let a notification concern fail the work it
    is supposed to be reporting on. A partially-wired app runs agents normally and notifies
    nobody.

    The webhook *management* router keeps using the raising accessors above, where a missing
    context is a genuine misconfiguration and must fail loudly rather than silently accept
    subscriptions into a store nothing reads.
    """
    ctx = getattr(request.app.state, "observability_context", None)
    if ctx is None:
        return disabled_webhook_emitter()
    return ctx.webhook_emitter


def get_analytics_service(request: Request) -> Analytics_Service:
    """Return the wired Analytics_Service."""
    return get_observability_context(request).analytics_service


def get_prompt_registry(request: Request) -> Prompt_Registry:
    """Return the wired Prompt_Registry."""
    return get_observability_context(request).prompt_registry


def get_guardrail_pipeline(request: Request) -> Guardrail_Pipeline:
    """Return the wired Guardrail_Pipeline."""
    return get_observability_context(request).guardrail_pipeline


def get_optional_guardrail_pipeline(request: Request) -> Guardrail_Pipeline | None:
    """Return the wired Guardrail_Pipeline, or ``None`` when observability is unwired.

    The query / agent / multi-agent entry points wrap their downstream invocation with
    the input/output guardrail pipeline (Req 5.4, 5.6). Guarding is a cross-cutting layer:
    when the ``ObservabilityContext`` has not been wired onto ``app.state`` (e.g. a test
    that bypasses the startup lifespan and injects only the RAG/agent contexts), guarding
    is skipped rather than failing the request. In the real application the composition
    root always builds the observability context at startup, so the pipeline is always
    present and the guardrails always run.
    """
    ctx = getattr(request.app.state, "observability_context", None)
    if ctx is None:
        return None
    return ctx.guardrail_pipeline


def get_evaluation_framework(request: Request) -> Evaluation_Framework:
    """Return the wired Evaluation_Framework."""
    return get_observability_context(request).evaluation_framework


def get_evaluation_store(request: Request) -> Evaluation_Store:
    """Return the wired Evaluation_Store (org-scoped dataset/run persistence)."""
    return get_observability_context(request).evaluation_store


# --- Phase 8 integration accessors ------------------------------------------------


def get_integration_status_service(request: Request) -> Integration_Status_Service:
    """Return the Integration_Status_Service (used by the ``/integrations/status`` router).

    Reads a pre-wired service from ``app.state`` when present (e.g. injected by a test or
    the composition root); otherwise builds the stateless service from the active Settings.
    """
    service = getattr(request.app.state, "integration_status_service", None)
    if service is not None:
        return service
    return build_integration_status_service(get_settings(request))


def get_integration_connection_store(request: Request) -> Integration_Connection_Store:
    """Return the org-scoped Integration_Connection_Store (used by the task 7 surfaces).

    Reads a pre-wired store from ``app.state`` when present; otherwise builds the in-memory
    default once and caches it on ``app.state`` so its persistence survives across requests.
    """
    store = getattr(request.app.state, "integration_connection_store", None)
    if store is not None:
        return store
    store = build_integration_connection_store(get_settings(request))
    request.app.state.integration_connection_store = store
    return store
