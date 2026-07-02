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
from agentforge.api.routers import health as health_router
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

    # Register component routers before serving (Req 2.4).
    app.include_router(health_router.router)

    return app


# Module-level ASGI app for `uvicorn agentforge.main:app`.
app = create_app()
