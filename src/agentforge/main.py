"""FastAPI application factory and lifespan wiring.

On startup the lifespan (Req 2.4):
1. Loads and validates configuration (aborting on missing required settings).
2. Creates the async DB engine and Redis client.
3. Runs schema migrations (halting on failure, reporting the failing id).

Exception handlers and routers are registered on the app *before* it serves, so all
routes are registered before requests are accepted (Req 2.1, 2.4).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentforge.api.errors import register_exception_handlers
from agentforge.api.routers import agent as agent_router
from agentforge.api.routers import analytics as analytics_router
from agentforge.api.routers import audit as audit_router
from agentforge.api.routers import auth as auth_router
from agentforge.api.routers import budget as budget_router
from agentforge.api.routers import conversations as conversations_router
from agentforge.api.routers import documents as documents_router
from agentforge.api.routers import evaluations as evaluations_router
from agentforge.api.routers import guardrails as guardrails_router
from agentforge.api.routers import health as health_router
from agentforge.api.routers import ingest as ingest_router
from agentforge.api.routers import integrations as integrations_router
from agentforge.api.routers import multi_agent as multi_agent_router
from agentforge.api.routers import observability as observability_router
from agentforge.api.routers import orgs as orgs_router
from agentforge.api.routers import prompts as prompts_router
from agentforge.api.routers import query as query_router
from agentforge.api.routers import webhooks as webhooks_router
from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_enterprise_context,
    build_multi_agent_context,
    build_observability_context,
)
from agentforge.config.settings import Settings, load_settings
from agentforge.db.engine import create_engine, create_session_factory
from agentforge.db.migrations import run_migrations

logger = logging.getLogger("agentforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle: config load, infra wiring, migrations."""
    # 1. Configuration (aborts with the offending key name if invalid).
    settings: Settings = getattr(app.state, "settings", None) or load_settings()
    app.state.settings = settings
    logger.info("Configuration loaded (profile=%s)", settings.profile)

    # 2. Database engine + session factory (respect pre-injected engine).
    engine = getattr(app.state, "db_engine", None)
    if engine is None:
        engine = create_engine(settings.database_url)
        app.state.db_engine = engine
        app.state.session_factory = create_session_factory(engine)

    # 3. Redis client (respect pre-injected client; lazy import otherwise).
    if getattr(app.state, "redis", None) is None:
        import redis.asyncio as redis_asyncio

        app.state.redis = redis_asyncio.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )

    # 4. Migrations run on startup; a failure halts boot naming the migration id.
    if getattr(app.state, "run_migrations_on_startup", True):
        applied = await run_migrations(engine, settings.embedding_dimension)
        if applied:
            logger.info("Applied migrations: %s", ", ".join(applied))

    # 5. Compose the RAG object graph (providers, vector store, services) once and
    #    share it with every request via app.state. Tests may pre-inject a context
    #    built from keyless in-memory doubles, which is respected here.
    if getattr(app.state, "app_context", None) is None:
        app.state.app_context = build_app_context(settings)
        logger.info(
            "Application context ready (llm=%s, vector_store=%s)",
            settings.active_llm(),
            settings.active_vector_store(),
        )

    # 6. Compose the Phase 3 agentic object graph (orchestrator, tools, memory,
    #    conversation store, trace recorder, streaming service), reusing the RAG
    #    AppContext. Tests may pre-inject a keyless context, which is respected here.
    if getattr(app.state, "agent_context", None) is None:
        app.state.agent_context = build_agent_context(
            settings, app=app.state.app_context
        )
        logger.info(
            "Agent context ready (search=%s, iteration_limit=%s)",
            settings.active_search(),
            app.state.agent_context.orchestrator.iteration_limit,
        )

    # 7. Compose the Phase 4 multi-agent object graph (registry with the four roles bound
    #    to the same existing Agent_Orchestrator, approval policy + gate, run store, and
    #    streaming service). Tests may pre-inject a keyless context, which is respected.
    if getattr(app.state, "multi_agent_context", None) is None:
        app.state.multi_agent_context = build_multi_agent_context(
            settings, agent=app.state.agent_context
        )
        logger.info(
            "Multi-agent context ready (approval_policy=%s, max_rounds=%s, max_revisions=%s)",
            settings.approval_policy,
            app.state.multi_agent_context.orchestrator.max_rounds,
            app.state.multi_agent_context.orchestrator.max_revisions,
        )

    # 8. Compose the Phase 5 enterprise object graph (auth service, identity store, RBAC
    #    policy, API-key service, and rate limiter) so the reusable Principal +
    #    Authorization dependencies can resolve credentials on every request. Built once
    #    at startup, backed by the existing Redis for rate limiting; tests may pre-inject
    #    a keyless context (in-memory identity/api-key stores + Fake_Clock/NoOp limiter),
    #    which is respected here (Req 9.5, 10.1).
    if getattr(app.state, "enterprise_context", None) is None:
        app.state.enterprise_context = build_enterprise_context(
            settings, redis=app.state.redis
        )
        logger.info(
            "Enterprise context ready (auth_enabled=%s, rate_limit_enabled=%s)",
            settings.auth_enabled,
            settings.rate_limit_enabled,
        )

    # 9. Compose the Phase 6 observability object graph (tracing exporter, usage store/
    #    recorder/sink, cost model, analytics service, prompt registry, guardrail
    #    pipeline, evaluation framework), sharing the RAG AppContext's usage store/sink so
    #    the Instrumented_Provider and the Analytics_Service read one store. Tests may
    #    pre-inject a keyless context, which is respected here (Req 7.3, 9.7, 10.2). The
    #    guardrail pipeline it holds also backs the query/agent/multi-agent entry-point
    #    wrapping, and the downstream LLM provider is the Instrumented_Provider wired by
    #    build_app_context, so every downstream flow emits usage transparently.
    if getattr(app.state, "observability_context", None) is None:
        # The agentic context's Trace_Recorder is handed over so the export service reads
        # completed traces from the same store the API serves them from.
        app.state.observability_context = build_observability_context(
            settings,
            app=app.state.app_context,
            trace_recorder=app.state.agent_context.trace_recorder,
        )
        logger.info(
            "Observability context ready (tracing_exporter=%s, trace_export_enabled=%s)",
            settings.active_tracing_exporter(),
            app.state.observability_context.trace_export_service.enabled,
        )

    try:
        yield
    finally:
        await engine.dispose()
        redis_client = getattr(app.state, "redis", None)
        if redis_client is not None:
            await redis_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory.

    Registers exception handlers and routers before the app serves requests.
    An optional pre-built ``settings`` can be injected (useful for tests).
    """
    app = FastAPI(
        title="AgentForge",
        version="0.1.0",
        lifespan=lifespan,
    )
    if settings is not None:
        app.state.settings = settings

    # Register error envelope handlers (404 / 500 / validation) before serving.
    register_exception_handlers(app)

    # Register component routers before serving (Req 2.1, 2.4). All Phase 1 + Phase 2
    # routes are registered here, before the app accepts any request.
    app.include_router(health_router.router)
    app.include_router(ingest_router.router)
    app.include_router(query_router.router)
    app.include_router(documents_router.router)
    # Phase 3 agentic-layer routers.
    app.include_router(conversations_router.router)
    app.include_router(agent_router.router)
    # Phase 4 multi-agent router.
    app.include_router(multi_agent_router.router)
    # Phase 5 enterprise routers (auth + orgs/members/teams/api-keys).
    app.include_router(auth_router.router)
    app.include_router(orgs_router.router)
    # Append-only administrative audit trail (who changed what, when).
    app.include_router(audit_router.router)
    # Phase 6 observability routers (analytics + prompts + guardrails + evaluations).
    app.include_router(analytics_router.router)
    # Spend budget: read the org's standing, set or clear its monthly ceiling.
    app.include_router(budget_router.router)
    # Reports how the deployment handles run telemetry (is trace export on, and where to).
    app.include_router(observability_router.router)
    app.include_router(prompts_router.router)
    app.include_router(guardrails_router.router)
    app.include_router(evaluations_router.router)
    # Phase 8 integrations router (status introspection).
    app.include_router(integrations_router.router)
    # Outbound webhooks: register endpoints, test them, read the delivery log.
    app.include_router(webhooks_router.router)

    return app


# Module-level ASGI app for `uvicorn agentforge.main:app`.
app = create_app()
