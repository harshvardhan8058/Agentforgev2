"""Unit tests for the Phase 6 composition-root wiring (Task 10.1).

Assert credential/profile-driven selection and the Instrumented_Provider re-wrap — all
keyless: no ``Tracing_Credential`` selects the ``NoOp_Tracing_Exporter`` and the in-memory
stores; a configured credential selects the ``LangSmith_Tracing_Exporter``; the app
context's provider is an ``Instrumented_Provider`` wrapping the ``Fallback_Provider``; and
only ``config/container.py`` names concrete observability implementations (Req 1.2, 1.4,
7.3, 9.7, 10.2).
"""

from __future__ import annotations

import inspect

from agentforge.config.container import (
    ObservabilityContext,
    build_app_context,
    build_observability_context,
)
from agentforge.config.settings import Settings
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.observability.evaluation.store import (
    InMemory_Evaluation_Store,
    Pg_Evaluation_Store,
)
from agentforge.observability.prompt_registry.store import (
    InMemory_Prompt_Store,
    Pg_Prompt_Store,
)
from agentforge.observability.tracing_exporter import (
    LangSmith_Tracing_Exporter,
    NoOp_Tracing_Exporter,
)
from agentforge.observability.usage.instrumented_provider import Instrumented_Provider
from agentforge.observability.usage.store import InMemory_Usage_Store, Pg_Usage_Store

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
}


def _settings(**overrides) -> Settings:
    return Settings(**{**_BASE, **overrides})


# --- Tracing_Exporter selection ---------------------------------------------------


def test_no_credential_selects_noop_exporter():
    """No Tracing_Credential -> the keyless NoOp exporter is wired (Req 1.2, 10.2)."""
    ctx = build_observability_context(_settings())
    assert isinstance(ctx, ObservabilityContext)
    assert isinstance(ctx.tracing_exporter, NoOp_Tracing_Exporter)


def test_credential_selects_langsmith_exporter():
    """A configured Tracing_Credential -> the LangSmith exporter (Req 1.4)."""
    ctx = build_observability_context(_settings(langsmith_api_key="ls-secret"))
    assert isinstance(ctx.tracing_exporter, LangSmith_Tracing_Exporter)


# --- store selection (in-memory keyless, Postgres production) ---------------------


def test_keyless_context_uses_in_memory_stores():
    """Local/keyless profile -> in-memory usage/prompt/evaluation stores (Req 10.2, 10.3)."""
    ctx = build_observability_context(_settings(profile="local"))
    assert isinstance(ctx.usage_store, InMemory_Usage_Store)
    assert isinstance(ctx.prompt_store, InMemory_Prompt_Store)
    assert isinstance(ctx.evaluation_store, InMemory_Evaluation_Store)


def test_production_context_uses_postgres_stores():
    """Production profile -> the Pg_* stores (constructed without connecting) (Req 10.3)."""
    ctx = build_observability_context(_settings(profile="production"))
    assert isinstance(ctx.usage_store, Pg_Usage_Store)
    assert isinstance(ctx.prompt_store, Pg_Prompt_Store)
    assert isinstance(ctx.evaluation_store, Pg_Evaluation_Store)


# --- Instrumented_Provider re-wrap ------------------------------------------------


def test_app_context_provider_is_instrumented_wrapping_fallback():
    """The app context's LLM_Provider is an Instrumented_Provider over Fallback (Req 7.1-7.3)."""
    app = build_app_context(_settings())
    assert isinstance(app.llm_provider, Instrumented_Provider)
    # The wrapped provider is the keyless Fallback_Provider; the wrapper is transparent.
    assert isinstance(app.llm_provider._wrapped, Fallback_Provider)
    assert app.llm_provider.name == "fallback"


def test_observability_context_shares_app_usage_store():
    """When given the app, analytics reads the SAME store the provider writes to (Req 3.3)."""
    app = build_app_context(_settings())
    obs = build_observability_context(_settings(), app=app)
    assert obs.usage_store is app.usage_store
    assert obs.usage_sink is app.usage_sink


# --- "only container.py names concretes" ------------------------------------------


def test_only_container_names_concrete_observability_impls():
    """The transport/deps layer references only abstract seams, never concretes (Req 7.3, 9.7)."""
    import agentforge.api.deps as deps_mod
    import agentforge.api.routers.analytics as analytics_mod
    import agentforge.api.routers.prompts as prompts_mod

    concretes = [
        "LangSmith_Tracing_Exporter",
        "NoOp_Tracing_Exporter",
        "Pg_Usage_Store",
        "InMemory_Usage_Store",
        "Pg_Prompt_Store",
        "InMemory_Prompt_Store",
        "Pg_Evaluation_Store",
        "InMemory_Evaluation_Store",
        "Default_Cost_Model",
        "Recording_Usage_Sink",
    ]
    for module in (deps_mod, analytics_mod, prompts_mod):
        source = inspect.getsource(module)
        for name in concretes:
            assert name not in source, f"{module.__name__} must not name {name}"



# --- webhook wiring ---------------------------------------------------------------


def test_the_keyless_webhook_stores_are_paired_so_a_delete_cascades():
    """The in-memory pair must behave like migration 0015's ON DELETE CASCADE.

    The composition root is the only place that can wire them together, so this is where the
    equivalence is asserted — otherwise a test using the keyless graph could assert the
    documented "deleting a webhook removes its delivery log" and pass for the wrong reason.
    """
    import uuid

    from agentforge.webhooks.base import Webhook_Delivery

    obs = build_observability_context(_settings())
    org_id = uuid.uuid4()
    subscription = obs.webhook_subscription_store.create(
        org_id, url="https://hooks.example.com/h", events=("run.completed",), secret="whsec_x"
    )
    obs.webhook_delivery_store.record(
        Webhook_Delivery(
            id=uuid.uuid4(),
            org_id=org_id,
            subscription_id=subscription.id,
            event_type="run.completed",
            status="delivered",
            attempts=1,
        )
    )
    assert obs.webhook_delivery_store.list_for_subscription(org_id, subscription.id)

    obs.webhook_subscription_store.delete(org_id, subscription.id)

    assert obs.webhook_delivery_store.list_for_subscription(org_id, subscription.id) == []


def test_the_emitter_is_built_from_the_configured_delivery_bounds():
    settings = _settings()
    obs = build_observability_context(settings)

    emitter = obs.webhook_emitter

    assert emitter._max_attempts == settings.webhook_max_attempts
    assert emitter._timeout_seconds == settings.webhook_timeout_seconds
    assert emitter._backoff_seconds == settings.webhook_backoff_seconds


def test_only_container_names_concrete_webhook_impls():
    """Same rule as the observability seams: the transport layer names no concrete."""
    import agentforge.api.deps as deps_mod
    import agentforge.api.routers.webhooks as webhooks_mod

    concretes = [
        "InMemory_Webhook_Subscription_Store",
        "Pg_Webhook_Subscription_Store",
        "InMemory_Webhook_Delivery_Store",
        "Pg_Webhook_Delivery_Store",
        "Httpx_Webhook_Transport",
        "Recording_Webhook_Transport",
    ]
    for module in (deps_mod, webhooks_mod):
        source = inspect.getsource(module)
        for name in concretes:
            assert name not in source, f"{module.__name__} must not name {name}"
