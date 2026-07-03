"""Composition root: builds pluggable providers from settings.

This is the ONLY module that references concrete provider implementations. Selection is
driven by *credential presence* and *profile* (Req 10.2, 10.3, 11.2, 11.3) and never
requires a paid key to boot: the keyless defaults are ``Fallback_Provider``,
``SentenceTransformer_Embeddings``, and ``Chroma_Store``.

Each builder consults a small registry keyed by the active selection name. A new
provider can be slotted in by adding a builder to the registry (or passing an override)
**without modifying the RAG_Service** (Req 11.6): the service layer only ever sees the
abstract interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.chunking.chunker import Chunker
from agentforge.config.settings import Settings
from agentforge.conversation.base import Conversation_Store
from agentforge.conversation.store import (
    InMemory_Conversation_Store,
    PgConversation_Store,
)
from agentforge.embeddings.base import Embedding_Provider
from agentforge.embeddings.sentence_transformer import SentenceTransformer_Embeddings
from agentforge.ingestion.service import Ingestion_Service
from agentforge.llm.base import LLM_Provider
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.memory.base import Memory_Manager
from agentforge.memory.manager import Composite_Memory_Manager
from agentforge.rag.service import RAG_Service
from agentforge.retrieval.retriever import Retriever
from agentforge.storage.base import DocumentStore
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.tools.rag_tool import RAG_Tool
from agentforge.tools.registry import Tool_Registry
from agentforge.tools.search.base import Search_Provider
from agentforge.tools.search.disabled import Disabled_Search_Provider
from agentforge.tools.web_search_tool import Web_Search_Tool
from agentforge.tracing.base import Trace_Recorder
from agentforge.tracing.recorder import InMemory_Trace_Recorder, Pg_Trace_Recorder
from agentforge.vectorstore.base import Vector_Store
from agentforge.vectorstore.chroma_store import Chroma_Store

# --- LLM_Provider selection -------------------------------------------------------


def _build_groq(settings: Settings) -> LLM_Provider:
    """Lazily construct the Groq_Provider (implemented in a later task).

    Kept behind a lazy import so the default keyless path never depends on the Groq
    implementation being present.
    """
    from agentforge.llm.groq_provider import Groq_Provider  # local import by design

    assert settings.groq_api_key is not None
    return Groq_Provider(api_key=settings.groq_api_key.get_secret_value())


_DEFAULT_LLM_BUILDERS: dict[str, Callable[[Settings], LLM_Provider]] = {
    "fallback": lambda _s: Fallback_Provider(),
    "groq": _build_groq,
}


def build_llm_provider(
    settings: Settings,
    llm_registry: dict[str, Callable[[Settings], LLM_Provider]] | None = None,
) -> LLM_Provider:
    """Return the active LLM_Provider (Groq if a key is set, else Fallback).

    ``llm_registry`` allows callers/tests to register additional providers without
    changing this module or the RAG_Service (Req 11.6).
    """
    registry = {**_DEFAULT_LLM_BUILDERS, **(llm_registry or {})}
    name = settings.active_llm()  # "groq" when a credential is present, else "fallback"
    builder = registry.get(name, registry["fallback"])
    return builder(settings)


# --- Embedding_Provider selection -------------------------------------------------


def _build_hosted_embeddings(settings: Settings) -> Embedding_Provider:
    """Lazily construct the optional Hosted_Embeddings provider."""
    from agentforge.embeddings.hosted import Hosted_Embeddings  # local import by design

    assert settings.hosted_embedding_api_key is not None
    return Hosted_Embeddings(
        api_key=settings.hosted_embedding_api_key.get_secret_value(),
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )


def build_embedding_provider(
    settings: Settings,
    embedding_registry: dict[str, Callable[[Settings], Embedding_Provider]] | None = None,
) -> Embedding_Provider:
    """Return the active Embedding_Provider (hosted iff configured + keyed, else local)."""
    registry = embedding_registry or {}
    if (
        settings.embedding_provider == "hosted"
        and settings.hosted_embedding_api_key is not None
    ):
        builder = registry.get("hosted", _build_hosted_embeddings)
        return builder(settings)
    # Default keyless local embedder (no download until first use).
    default = registry.get(
        "sentence_transformer",
        lambda s: SentenceTransformer_Embeddings(
            model=s.embedding_model, dimension=s.embedding_dimension
        ),
    )
    return default(settings)


# --- Vector_Store selection -------------------------------------------------------


def _build_pgvector(settings: Settings, emb: Embedding_Provider) -> Vector_Store:
    """Lazily construct the Pgvector_Store (implemented in a later task)."""
    from agentforge.vectorstore.pgvector_store import Pgvector_Store  # local import

    return Pgvector_Store(dim=emb.dimension, dsn=settings.database_url)


def build_vector_store(
    settings: Settings,
    emb: Embedding_Provider,
    vector_store_registry: dict[str, Callable[[Settings, Embedding_Provider], Vector_Store]]
    | None = None,
) -> Vector_Store:
    """Return the active Vector_Store (pgvector in production, else Chroma locally)."""
    registry = vector_store_registry or {}
    name = settings.active_vector_store()  # "pgvector" in production, else "chroma"
    if name == "pgvector":
        builder = registry.get("pgvector", _build_pgvector)
        return builder(settings, emb)
    default = registry.get("chroma", lambda _s, e: Chroma_Store(dim=e.dimension))
    return default(settings, emb)


# --- DocumentStore selection ------------------------------------------------------


def build_document_store(settings: Settings) -> DocumentStore:
    """Return the relational document store.

    Production and local-with-Docker both use the DB-backed adapter (the compose stack
    provides Postgres). Keyless standalone runs and tests inject an in-memory store
    directly via ``build_app_context``.
    """
    from agentforge.db.store import DBDocumentStore  # local import: keeps memory path free

    return DBDocumentStore(settings.database_url)


# --- Full application composition -------------------------------------------------


@dataclass
class AppContext:
    """The wired object graph the API routers depend on.

    Built once at startup (or injected in tests) so every request reuses the same
    providers, vector store, and services.
    """

    settings: Settings
    embedding_provider: Embedding_Provider
    vector_store: Vector_Store
    llm_provider: LLM_Provider
    chunker: Chunker
    document_store: DocumentStore
    ingestion_service: Ingestion_Service
    retriever: Retriever
    rag_service: RAG_Service


def build_app_context(
    settings: Settings,
    *,
    embedding_provider: Embedding_Provider | None = None,
    vector_store: Vector_Store | None = None,
    llm_provider: LLM_Provider | None = None,
    document_store: DocumentStore | None = None,
) -> AppContext:
    """Compose the full RAG object graph from settings.

    All collaborators may be injected (tests pass keyless in-memory doubles); anything
    not injected is built from the credential/profile-driven defaults. The service
    layer only ever sees the abstract seams, so provider swaps require no changes here
    beyond the builders above (Req 11.6).
    """
    emb = embedding_provider or build_embedding_provider(settings)
    vstore = vector_store or build_vector_store(settings, emb)
    llm = llm_provider or build_llm_provider(settings)
    store = document_store if document_store is not None else build_document_store(settings)

    # The extractor applies markdown normalization, so the chunker runs in identity
    # (preserve) mode to avoid double-normalization.
    chunker = Chunker(
        chunk_max_chars=settings.chunk_max_chars,
        chunk_overlap_chars=settings.chunk_overlap_chars,
        markdown_mode="preserve",
    )

    ingestion = Ingestion_Service(
        chunker=chunker,
        embedding_provider=emb,
        vector_store=vstore,
        sink=store,
        max_document_bytes=settings.max_document_bytes,
        extraction_timeout_seconds=settings.extraction_timeout_seconds,
        markdown_mode=settings.markdown_mode,
    )

    retriever = Retriever(
        embedding_provider=emb,
        vector_store=vstore,
        chunk_text_source=store,
        k_min=settings.top_k_min,
        k_max=settings.top_k_max,
    )

    rag = RAG_Service(
        retriever=retriever,
        llm_provider=llm,
        top_k_default=settings.top_k_default,
        top_k_min=settings.top_k_min,
        top_k_max=settings.top_k_max,
    )

    return AppContext(
        settings=settings,
        embedding_provider=emb,
        vector_store=vstore,
        llm_provider=llm,
        chunker=chunker,
        document_store=store,
        ingestion_service=ingestion,
        retriever=retriever,
        rag_service=rag,
    )



# --- Search_Provider selection (Phase 3) ------------------------------------------


def _build_keyed_search(settings: Settings) -> Search_Provider:
    """Construct the credentialed search provider (only reached when a key is present)."""
    from agentforge.tools.search.keyed import Keyed_Search_Provider  # local import

    assert settings.search_api_key is not None
    return Keyed_Search_Provider(
        api_key=settings.search_api_key.get_secret_value(),
        provider_name=settings.search_provider,
    )


def build_search_provider(
    settings: Settings,
    search_registry: dict[str, Callable[[Settings], Search_Provider]] | None = None,
) -> Search_Provider:
    """Return the active Search_Provider.

    Returns the keyless ``Disabled_Search_Provider`` by default; a real (keyed) provider
    is built **only** when a search credential is configured and a provider is selected
    (``settings.active_search()`` is not ``"disabled"``), so no network-capable provider
    is ever constructed on the keyless path (Req 5.2, 5.4).
    """
    registry = search_registry or {}
    name = settings.active_search()  # "disabled" whenever no key is present (Req 5.4)
    if name == "disabled":
        return Disabled_Search_Provider()
    builder = registry.get(name, _build_keyed_search)
    return builder(settings)


# --- Conversation_Store / Trace_Recorder selection (Phase 3) ----------------------


def build_conversation_store(settings: Settings) -> Conversation_Store:
    """Return the Conversation_Store: Postgres in production, in-memory otherwise.

    The in-memory default keeps standalone/keyless runs fully functional without a
    database; the production profile persists to Postgres. Tests inject an in-memory
    double directly via ``build_agent_context`` overrides.
    """
    if settings.profile == "production":
        return PgConversation_Store(settings.database_url)
    return InMemory_Conversation_Store()


def build_trace_recorder(settings: Settings) -> Trace_Recorder:
    """Return the Trace_Recorder: Postgres-backed in production, in-memory otherwise."""
    if settings.profile == "production":
        return Pg_Trace_Recorder(settings.database_url)
    return InMemory_Trace_Recorder()


def build_tool_registry(
    settings: Settings,
    app: AppContext,
    search_provider: Search_Provider | None = None,
) -> Tool_Registry:
    """Build the Tool_Registry: RAG_Tool always; Web_Search_Tool only when keyed (Req 5.3).

    The ``RAG_Tool`` wraps the existing ``RAG_Service`` and is always available. The
    ``Web_Search_Tool`` is registered **only** when the selected search provider is
    available (a search credential is present); otherwise it is not registered, so it is
    never offered to the LLM and performs no network request (Req 5.3, 5.4).
    """
    registry = Tool_Registry()
    registry.register(RAG_Tool(app.rag_service))
    search = search_provider if search_provider is not None else build_search_provider(settings)
    if search.available:
        registry.register(Web_Search_Tool(search))
    return registry


# --- Agentic layer composition ----------------------------------------------------


@dataclass
class AgentContext:
    """The wired agentic object graph the Phase 3 routers depend on.

    Reuses the existing :class:`AppContext` (RAG_Service, providers, vector store) and
    adds the tool registry, memory manager, conversation store, trace recorder, streaming
    service, and orchestrator. Built once at startup (or injected in tests).
    """

    app: AppContext
    tool_registry: Tool_Registry
    memory_manager: Memory_Manager
    conversation_store: Conversation_Store
    trace_recorder: Trace_Recorder
    streaming_service: SSE_Streaming_Service
    orchestrator: Agent_Orchestrator


def build_agent_context(
    settings: Settings,
    app: AppContext | None = None,
    *,
    tool_registry: Tool_Registry | None = None,
    search_provider: Search_Provider | None = None,
    memory_manager: Memory_Manager | None = None,
    conversation_store: Conversation_Store | None = None,
    trace_recorder: Trace_Recorder | None = None,
    streaming_service: SSE_Streaming_Service | None = None,
    orchestrator: Agent_Orchestrator | None = None,
) -> AgentContext:
    """Compose the Phase 3 agentic object graph, reusing the existing AppContext.

    Mirrors :func:`build_app_context`: every collaborator may be injected (tests pass
    keyless in-memory doubles) and anything not injected is built from the
    credential/profile-driven defaults. The orchestrator depends only on the abstract
    ``LLM_Provider``, ``Tool_Registry``, ``Memory_Manager``, and ``Trace_Recorder`` seams
    (Req 12.1); the composition root is the only place concrete collaborators are named.
    """
    app = app or build_app_context(settings)

    registry = tool_registry or build_tool_registry(settings, app, search_provider)
    memory = memory_manager or Composite_Memory_Manager(
        app.embedding_provider,
        app.vector_store,
        size_budget=settings.memory_size_budget,
    )
    conversation = (
        conversation_store
        if conversation_store is not None
        else build_conversation_store(settings)
    )
    trace = trace_recorder if trace_recorder is not None else build_trace_recorder(settings)

    orch = orchestrator or Agent_Orchestrator(
        llm=app.llm_provider,
        registry=registry,
        memory=memory,
        trace=trace,
        iteration_limit=settings.iteration_limit,
    )
    streaming = streaming_service or SSE_Streaming_Service(orch, conversation)

    return AgentContext(
        app=app,
        tool_registry=registry,
        memory_manager=memory,
        conversation_store=conversation,
        trace_recorder=trace,
        streaming_service=streaming,
        orchestrator=orch,
    )
