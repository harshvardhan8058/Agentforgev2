"""Property-based test for backward compatibility with zero integration credentials (Property 10)."""

from __future__ import annotations

from functools import lru_cache

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.config.container import build_app_context, build_tool_registry
from agentforge.config.settings import Settings
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tools.rag_tool import RAG_TOOL_NAME, RAG_Tool
from agentforge.tools.registry import Tool_Registry
from agentforge.tools.web_search_tool import WEB_SEARCH_TOOL_NAME
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


@lru_cache(maxsize=1)
def _app_context():
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )  # type: ignore[call-arg]
    return build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )


def _keyless_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )  # type: ignore[call-arg]


# Feature: agentforge-integrations, Property 10: Backward compatibility with zero integration
# credentials.
@hyp_settings(max_examples=100, deadline=None)
@given(message=st.text(min_size=1, max_size=60))
def test_zero_credentials_registry_and_run_unchanged(message):
    """Feature: agentforge-integrations, Property 10: For any Settings configuration with no
    integration Credential configured, the Tool_Registry's tool-name set equals the
    pre-Phase-8 baseline set (rag_search, plus web_search iff its own search credential is
    present), and an agent run over identical inputs on the deterministic keyless path
    produces the same result it produced before Phase 8.

    Validates: Requirements 17.1, 17.2, 3.8, 3.1
    """
    settings = _keyless_settings()
    app = _app_context()

    # The Phase 8 wiring registers no integration tool when no credential is configured.
    phase8_registry = build_tool_registry(settings, app)
    names = {spec.name for spec in phase8_registry.list_specs()}
    assert names == {RAG_TOOL_NAME}
    assert WEB_SEARCH_TOOL_NAME not in names

    # A pre-Phase-8 baseline registry contains exactly the RAG_Tool over the same service.
    baseline_registry = Tool_Registry()
    baseline_registry.register(RAG_Tool(app.rag_service))
    assert {s.name for s in baseline_registry.list_specs()} == names

    # A deterministic keyless run produces the identical result with the Phase 8 registry
    # and the pre-Phase-8 baseline registry (integration wiring changes nothing).
    phase8_state = Agent_Orchestrator(
        Fallback_Provider(), phase8_registry, iteration_limit=10
    ).run(message, conversation_id="fixed")
    baseline_state = Agent_Orchestrator(
        Fallback_Provider(), baseline_registry, iteration_limit=10
    ).run(message, conversation_id="fixed")

    assert phase8_state.final_answer == baseline_state.final_answer
    assert [o.tool_name for o in phase8_state.observations] == [
        o.tool_name for o in baseline_state.observations
    ]
