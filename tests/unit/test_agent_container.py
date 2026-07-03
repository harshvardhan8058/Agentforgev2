"""Unit tests for the Phase 3 composition root (Task 15.2).

Assert the search registration policy — the ``Web_Search_Tool`` is registered only when
a search credential is present (Req 5.2, 5.3) — and that the ``Agent_Orchestrator``
depends solely on the abstract seams, never on concrete providers (Req 12.1, 12.3). All
tests run keyless with in-memory doubles.
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_search_provider,
    build_tool_registry,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.llm.base import LLM_Provider
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.memory.base import Memory_Manager
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tools.registry import Tool_Registry
from agentforge.tools.search.disabled import Disabled_Search_Provider
from agentforge.tools.web_search_tool import WEB_SEARCH_TOOL_NAME
from agentforge.tracing.base import Trace_Recorder
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _settings(**overrides) -> Settings:
    base = {
        "profile": "local",
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "embedding_dimension": _DIM,
    }
    return Settings(**{**base, **overrides})


def _app_context(settings: Settings):
    return build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )


# --- search registration policy ---------------------------------------------------


def test_build_search_provider_disabled_by_default():
    """No search credential -> the Disabled_Search_Provider (Req 5.4)."""
    provider = build_search_provider(_settings())
    assert isinstance(provider, Disabled_Search_Provider)
    assert provider.available is False


def test_web_search_tool_not_registered_when_keyless():
    """Keyless -> only the RAG_Tool is registered/offered (Req 5.3, 5.4)."""
    settings = _settings()
    registry = build_tool_registry(settings, _app_context(settings))
    names = {spec.name for spec in registry.list_specs()}
    assert "rag_search" in names
    assert WEB_SEARCH_TOOL_NAME not in names
    assert registry.resolve(WEB_SEARCH_TOOL_NAME) is None


def test_web_search_tool_registered_only_when_keyed():
    """A search credential -> the Web_Search_Tool is registered and offered (Req 5.2, 5.3)."""
    settings = _settings(search_provider="tavily", search_api_key="secret-search-key")
    assert settings.active_search() == "tavily"
    registry = build_tool_registry(settings, _app_context(settings))
    names = {spec.name for spec in registry.list_specs()}
    assert WEB_SEARCH_TOOL_NAME in names
    assert registry.resolve(WEB_SEARCH_TOOL_NAME) is not None


# --- orchestrator depends only on abstract seams ----------------------------------


def test_orchestrator_depends_only_on_abstract_seams():
    """The orchestrator is built from abstract seams, not concrete providers (Req 12.1)."""
    settings = _settings()
    ctx = build_agent_context(
        settings,
        app=_app_context(settings),
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    orchestrator = ctx.orchestrator
    assert isinstance(orchestrator, Agent_Orchestrator)
    # The collaborators it holds are instances of the abstract seams.
    assert isinstance(orchestrator._llm, LLM_Provider)
    assert isinstance(orchestrator._registry, Tool_Registry)
    assert isinstance(orchestrator._memory, Memory_Manager)
    assert isinstance(orchestrator._trace, Trace_Recorder)


def test_build_agent_context_reuses_injected_app_context():
    """build_agent_context reuses the provided AppContext rather than rebuilding it."""
    settings = _settings()
    app = _app_context(settings)
    ctx = build_agent_context(
        settings,
        app=app,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    assert ctx.app is app
    # The RAG_Tool wraps the reused RAG_Service (no reimplementation).
    assert "rag_search" in {spec.name for spec in ctx.tool_registry.list_specs()}
