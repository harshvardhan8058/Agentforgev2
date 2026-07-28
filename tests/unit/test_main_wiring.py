"""Wiring unit test for the Phase 6 app factory + lifespan (Task 16.1).

Asserts (Req 7.3, 7.5, 9.3, 9.4, 10.2):

* all four Phase 6 routers (analytics, prompts, guardrails, evaluations) are registered;
* the startup lifespan populates ``app.state.observability_context`` and honors a
  pre-injected override;
* every Phase 6 route declares ``get_current_principal`` + ``require_permission``;
* the keyless boot wires the ``NoOp_Tracing_Exporter``.

Runs fully keyless: real infra (Postgres/Redis/migrations) is replaced by inert fakes and
disabled, so the lifespan executes without any external connection.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentforge.api.deps import get_current_principal
from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
    build_observability_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.multiagent.approval import Auto_Approve_Policy
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.observability.tracing_exporter import NoOp_Tracing_Exporter
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings
from tests.route_helpers import api_route_paths, iter_api_routes

_DIM = 8

# The Phase 6 route path prefixes that must carry auth + permission dependencies.
_PHASE6_PREFIXES = ("/analytics", "/prompts", "/guardrails", "/evaluations")


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


class _FakeEngine:
    async def dispose(self) -> None:  # matches lifespan teardown
        return None


class _FakeRedis:
    async def aclose(self) -> None:  # matches lifespan teardown
        return None


def _wire_keyless(app, settings) -> None:
    """Pre-inject keyless contexts + inert infra so the lifespan connects to nothing."""
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    app.state.app_context = app_ctx
    app.state.agent_context = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    app.state.multi_agent_context = build_multi_agent_context(
        settings,
        agent=app.state.agent_context,
        run_store=InMemory_Multi_Agent_Run_Store(),
        approval_policy=Auto_Approve_Policy(),
    )
    install_enterprise_auth(app, settings)
    app.state.db_engine = _FakeEngine()
    app.state.redis = _FakeRedis()
    app.state.run_migrations_on_startup = False


# --- router registration ----------------------------------------------------------


def test_all_four_phase6_routers_registered():
    app = create_app(_make_settings())
    paths = api_route_paths(app)
    assert "/analytics/usage" in paths
    assert "/prompts" in paths
    assert "/guardrails/config" in paths
    assert "/guardrails/evaluate" in paths
    assert "/evaluations/datasets" in paths
    assert "/evaluations/runs" in paths


# --- auth surface on every Phase 6 route ------------------------------------------


def _flatten_calls(dependant) -> list:
    calls = [dependant.call]
    for sub in dependant.dependencies:
        calls.extend(_flatten_calls(sub))
    return calls


def test_every_phase6_route_declares_principal_and_permission():
    app = create_app(_make_settings())
    phase6_routes = [
        r for r in iter_api_routes(app) if r.path.startswith(_PHASE6_PREFIXES)
    ]
    assert phase6_routes, "expected Phase 6 routes to be registered"
    for route in phase6_routes:
        calls = _flatten_calls(route.dependant)
        # get_current_principal is present (reused authentication dependency).
        assert get_current_principal in calls, route.path
        # require_permission(...) wraps it — its inner closure is in the dependency tree.
        assert any(
            "require_permission" in getattr(c, "__qualname__", "") for c in calls
        ), route.path


# --- lifespan populates + honors the observability context ------------------------


def test_lifespan_populates_observability_context():
    settings = _make_settings()
    app = create_app(settings)
    _wire_keyless(app, settings)
    # No override pre-injected: the lifespan must build and assign one.
    with TestClient(app, raise_server_exceptions=False):
        ctx = app.state.observability_context
    assert ctx is not None
    # Keyless boot wires the NoOp tracing exporter (Req 10.2).
    assert isinstance(ctx.tracing_exporter, NoOp_Tracing_Exporter)


def test_lifespan_honors_preinjected_observability_context():
    settings = _make_settings()
    app = create_app(settings)
    _wire_keyless(app, settings)
    sentinel = build_observability_context(settings, app=app.state.app_context)
    app.state.observability_context = sentinel
    with TestClient(app, raise_server_exceptions=False):
        assert app.state.observability_context is sentinel


# --- keyless boot uses the NoOp exporter ------------------------------------------


def test_keyless_build_uses_noop_exporter():
    settings = _make_settings()
    ctx = build_observability_context(settings)
    assert settings.active_tracing_exporter() == "noop"
    assert isinstance(ctx.tracing_exporter, NoOp_Tracing_Exporter)
