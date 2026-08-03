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

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from argon2 import PasswordHasher

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.chunking.chunker import Chunker
from agentforge.config.settings import ConfigError, Settings
from agentforge.enterprise.api_keys import API_Key_Service, InMemory_API_Key_Store
from agentforge.enterprise.auth import Auth_Service
from agentforge.enterprise.audit import (
    Audit_Service,
    InMemory_Audit_Log,
    Pg_Audit_Log,
)
from agentforge.enterprise.base import (
    API_Key_Store,
    Audit_Log,
    Identity_Store,
    Rate_Limiter,
)
from agentforge.enterprise.identity import InMemory_Identity_Store
from agentforge.enterprise.rate_limit import NoOp_Rate_Limiter, Redis_Rate_Limiter
from agentforge.enterprise.rbac import RBAC_Policy
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
from agentforge.multiagent.approval import (
    Approval_Policy,
    Auto_Approve_Policy,
    Checkpoint_Store,
    Human_Approval_Gate,
    Human_In_The_Loop_Policy,
)
from agentforge.multiagent.orchestrator import Multi_Agent_Orchestrator
from agentforge.multiagent.roles.base import DEFAULT_PIPELINE, Agent_Role_Registry
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.store import (
    InMemory_Multi_Agent_Run_Store,
    Multi_Agent_Run_Store,
)
from agentforge.multiagent.streaming import Multi_Agent_Streaming_Service
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.api.errors import AppError
from agentforge.integrations.base import Integration_Connector, Integration_Tool
from agentforge.integrations.connection import (
    InMemory_Integration_Connection_Store,
    Integration_Connection_Store,
    Pg_Integration_Connection_Store,
)
from agentforge.integrations.github import (
    Disabled_GitHub_Connector,
    GitHub_Connector,
    GitHub_Tool,
    Keyed_GitHub_Connector,
)
from agentforge.integrations.gmail import (
    Disabled_Gmail_Connector,
    Gmail_Connector,
    Gmail_Tool,
    Keyed_Gmail_Connector,
)
from agentforge.integrations.google_drive import (
    Disabled_Google_Drive_Connector,
    Google_Drive_Connector,
    Google_Drive_Tool,
    Keyed_Google_Drive_Connector,
)
from agentforge.integrations.slack import (
    Disabled_Slack_Connector,
    Keyed_Slack_Connector,
    Slack_Connector,
    Slack_Tool,
)
from agentforge.integrations.status import Integration_Status_Service
from agentforge.tools.base import Tool_Interface
from agentforge.tools.rag_tool import RAG_Tool
from agentforge.tools.registry import Tool_Registry
from agentforge.tools.search.base import Search_Provider
from agentforge.tools.search.disabled import Disabled_Search_Provider
from agentforge.tools.web_search_tool import Web_Search_Tool
from agentforge.tracing.base import Trace_Recorder
from agentforge.tracing.recorder import InMemory_Trace_Recorder, Pg_Trace_Recorder
from agentforge.observability.analytics import Analytics_Service
from agentforge.observability.cost import Cost_Model, build_default_cost_model
from agentforge.observability.evaluation.base import Evaluation_Store, Evaluator
from agentforge.observability.evaluation.evaluators import (
    Contains_Evaluator,
    Exact_Match_Evaluator,
    Heuristic_Evaluator,
)
from agentforge.observability.evaluation.framework import Evaluation_Framework
from agentforge.observability.evaluation.store import (
    InMemory_Evaluation_Store,
    Pg_Evaluation_Store,
)
from agentforge.observability.guardrails.base import Guardrail_Pipeline
from agentforge.observability.guardrails.defaults import build_default_pipeline
from agentforge.observability.prompt_registry.base import Prompt_Store
from agentforge.observability.prompt_registry.registry import Prompt_Registry
from agentforge.observability.prompt_registry.store import (
    InMemory_Prompt_Store,
    Pg_Prompt_Store,
)
from agentforge.observability.budget import (
    Budget_Guard,
    Budget_Store,
    InMemory_Budget_Store,
    Pg_Budget_Store,
)
from agentforge.observability.trace_export import Trace_Export_Service
from agentforge.observability.tracing_exporter import (
    Tracing_Exporter,
    build_tracing_exporter,
)
from agentforge.observability.usage.base import Usage_Sink, Usage_Store
from agentforge.observability.usage.instrumented_provider import Instrumented_Provider
from agentforge.observability.usage.recorder import Usage_Recorder
from agentforge.observability.usage.sink import Recording_Usage_Sink
from agentforge.observability.usage.store import (
    InMemory_Usage_Store,
    Pg_Usage_Store,
)
from agentforge.webhooks.base import Webhook_Transport
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
    Pg_Webhook_Delivery_Store,
    Pg_Webhook_Subscription_Store,
    Webhook_Delivery_Store,
    Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Httpx_Webhook_Transport
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
    # The model is passed only when configured, so an unset value keeps the provider's
    # own documented default rather than this module restating it.
    model = {"model": settings.groq_model} if settings.groq_model else {}
    return Groq_Provider(
        api_key=settings.groq_api_key.get_secret_value(),
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        rate_limit_max_wait_seconds=settings.llm_rate_limit_max_wait_seconds,
        **model,
    )


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
    # Phase 6: the Usage_Sink / Usage_Store the wrapping Instrumented_Provider emits
    # through. Exposed so ``build_observability_context`` can share the SAME store, so the
    # Analytics_Service reads exactly the usage the provider wrote (Req 2.3, 3.3, 7.3).
    usage_sink: Usage_Sink | None = None
    usage_store: Usage_Store | None = None


def build_app_context(
    settings: Settings,
    *,
    embedding_provider: Embedding_Provider | None = None,
    vector_store: Vector_Store | None = None,
    llm_provider: LLM_Provider | None = None,
    document_store: DocumentStore | None = None,
    usage_sink: Usage_Sink | None = None,
    usage_store: Usage_Store | None = None,
) -> AppContext:
    """Compose the full RAG object graph from settings.

    All collaborators may be injected (tests pass keyless in-memory doubles); anything
    not injected is built from the credential/profile-driven defaults. The service
    layer only ever sees the abstract seams, so provider swaps require no changes here
    beyond the builders above (Req 11.6).

    The active ``LLM_Provider`` is **re-wrapped** in an :class:`Instrumented_Provider`
    (Phase 6) so every downstream RAG / agent / multi-agent flow emits a usage record
    transparently, without any caller change (Req 2.1, 7.1, 7.2, 7.3). The
    ``usage_sink`` / ``usage_store`` may be injected so the composed graph shares one
    store with the :class:`ObservabilityContext`; anything not injected is built from the
    keyless defaults. An already-instrumented injected provider is not double-wrapped.
    """
    emb = embedding_provider or build_embedding_provider(settings)
    vstore = vector_store or build_vector_store(settings, emb)
    store = document_store if document_store is not None else build_document_store(settings)

    # Phase 6: build (or reuse) the usage store + sink, then re-wrap the base provider so
    # every generate() call emits usage transparently. Delegation happens inside the
    # decorator, so callers still see the plain LLM_Provider contract (Req 7.1, 7.2).
    u_store = usage_store if usage_store is not None else build_usage_store(settings)
    if usage_sink is not None:
        u_sink = usage_sink
    else:
        u_sink = Recording_Usage_Sink(
            build_usage_recorder(settings, u_store, build_cost_model(settings))
        )
    base_llm = llm_provider or build_llm_provider(settings)
    llm: LLM_Provider = (
        base_llm
        if isinstance(base_llm, Instrumented_Provider)
        else Instrumented_Provider(base_llm, u_sink)
    )

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
        allow_ungrounded=settings.allow_ungrounded_answers,
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
        usage_sink=u_sink,
        usage_store=u_store,
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
    if settings.persist_domain_stores():
        return PgConversation_Store(settings.database_url)
    return InMemory_Conversation_Store()


def build_trace_recorder(settings: Settings) -> Trace_Recorder:
    """Return the Trace_Recorder: Postgres-backed in production, in-memory otherwise."""
    if settings.persist_domain_stores():
        return Pg_Trace_Recorder(settings.database_url)
    return InMemory_Trace_Recorder()


def build_tool_registry(
    settings: Settings,
    app: AppContext,
    search_provider: Search_Provider | None = None,
    *,
    integration_connectors: dict[str, Integration_Connector] | None = None,
) -> Tool_Registry:
    """Build the Tool_Registry: RAG_Tool always; Web_Search_Tool only when keyed (Req 5.3).

    The ``RAG_Tool`` wraps the existing ``RAG_Service`` and is always available. The
    ``Web_Search_Tool`` is registered **only** when the selected search provider is
    available (a search credential is present); otherwise it is not registered, so it is
    never offered to the LLM and performs no network request (Req 5.3, 5.4).

    After the baseline tools, each Enabled Phase 8 Integration_Tool is registered (Req 2.2).
    A Disabled integration is never yielded, so it is never registered nor offered; a
    duplicate name surfaces the existing ``DuplicateToolNameError`` unchanged (Req 2.4).
    ``integration_connectors`` lets a caller/test inject connectors (e.g. mock connectors)
    keyed by integration name without naming a concrete connector outside this module.
    """
    registry = Tool_Registry()
    registry.register(RAG_Tool(app.rag_service))
    search = search_provider if search_provider is not None else build_search_provider(settings)
    if search.available:
        registry.register(Web_Search_Tool(search))
    for tool in build_integration_tools(settings, connectors=integration_connectors):
        registry.register(tool)
    return registry


# --- Integration_Layer composition (Phase 8) --------------------------------------
#
# ``config/container.py`` is the ONLY module that names concrete Connectors and registers
# Integration_Tools (Req 2.1). Each connector builder returns the keyless
# ``Disabled_<X>_Connector`` unless the integration is Enabled, in which case it constructs
# the ``Keyed_<X>_Connector`` from the ``SecretStr`` credential's plaintext — obtained here
# and nowhere else (Req 3.2, 5.2, 5.3).


def build_slack_connector(settings: Settings) -> Slack_Connector:
    """Return the Slack connector: Disabled unless Enabled, else Keyed from the token."""
    if not settings.integration_enabled("slack"):
        return Disabled_Slack_Connector()
    assert settings.slack_bot_token is not None
    return Keyed_Slack_Connector(
        settings.slack_bot_token.get_secret_value(),
        timeout_seconds=settings.integration_timeout_seconds,
    )


def build_gmail_connector(settings: Settings) -> Gmail_Connector:
    """Return the Gmail connector: Disabled unless Enabled, else Keyed from the token."""
    if not settings.integration_enabled("gmail"):
        return Disabled_Gmail_Connector()
    assert settings.gmail_token is not None
    return Keyed_Gmail_Connector(
        settings.gmail_token.get_secret_value(),
        timeout_seconds=settings.integration_timeout_seconds,
    )


def build_google_drive_connector(settings: Settings) -> Google_Drive_Connector:
    """Return the Google Drive connector: Disabled unless Enabled, else Keyed from the token."""
    if not settings.integration_enabled("google_drive"):
        return Disabled_Google_Drive_Connector()
    assert settings.google_drive_token is not None
    return Keyed_Google_Drive_Connector(
        settings.google_drive_token.get_secret_value(),
        timeout_seconds=settings.integration_timeout_seconds,
    )


def build_github_connector(settings: Settings) -> GitHub_Connector:
    """Return the GitHub connector: Disabled unless Enabled, else Keyed from the token."""
    if not settings.integration_enabled("github"):
        return Disabled_GitHub_Connector()
    assert settings.github_token is not None
    return Keyed_GitHub_Connector(
        settings.github_token.get_secret_value(),
        timeout_seconds=settings.integration_timeout_seconds,
    )


# Canonical (name, connector-builder, Tool class) triples, in the stable integration order.
_INTEGRATION_BUILDERS: tuple[
    tuple[str, Callable[[Settings], Integration_Connector], type[Integration_Tool]], ...
] = (
    ("slack", build_slack_connector, Slack_Tool),
    ("gmail", build_gmail_connector, Gmail_Tool),
    ("google_drive", build_google_drive_connector, Google_Drive_Tool),
    ("github", build_github_connector, GitHub_Tool),
)


def build_integration_tools(
    settings: Settings,
    *,
    connectors: dict[str, Integration_Connector] | None = None,
) -> list[Tool_Interface]:
    """Yield an Integration_Tool for each Enabled integration only (Req 2.2, 2.3, 2.5).

    For each integration, build (or accept an injected) connector and register its
    ``Integration_Tool`` — with the bounded ``timeout_seconds`` / ``max_results`` from
    settings — only when ``connector.available`` (Enabled ⇒ register; Disabled ⇒ skip, never
    offered, no network path). On any construction failure, raise an ``AppError``-shaped
    error naming the offending integration and abort — never a partially registered state
    (Req 2.6).
    """
    tools: list[Tool_Interface] = []
    injected = connectors or {}
    for name, build_connector, tool_cls in _INTEGRATION_BUILDERS:
        try:
            connector = injected.get(name) or build_connector(settings)
            if connector.available:
                tools.append(
                    tool_cls(
                        connector,
                        timeout_seconds=settings.integration_timeout_seconds,
                        max_results=settings.integration_max_results,
                    )
                )
        except AppError:
            raise
        except Exception:
            # Abort startup naming the offending integration; never leak internal detail.
            raise AppError(
                "integration_config_error",
                f"failed to construct integration {name!r}",
                500,
                {"integration": name},
            ) from None
    return tools


def build_integration_status_service(settings: Settings) -> Integration_Status_Service:
    """Return the org-scoped Integration_Status_Service (used by the task 6 router)."""
    return Integration_Status_Service(settings)


def build_integration_connection_store(
    settings: Settings,
) -> Integration_Connection_Store:
    """Return the Integration_Connection_Store: Postgres in production, in-memory otherwise.

    Mirrors :func:`build_conversation_store` / :func:`build_usage_store`: the in-memory
    default keeps standalone/keyless runs fully functional without a database, while the
    production profile persists non-secret per-org configuration to Postgres via
    ``Pg_Integration_Connection_Store`` over the ``integration_connections`` table
    (migration ``0011``). Enablement never depends on this store (Req 11.5).
    """
    if settings.persist_domain_stores():
        return Pg_Integration_Connection_Store(settings.database_url)
    return InMemory_Integration_Connection_Store()


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
    integration_connectors: dict[str, Integration_Connector] | None = None,
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

    registry = tool_registry or build_tool_registry(
        settings, app, search_provider, integration_connectors=integration_connectors
    )
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



# --- Multi-agent layer composition (Phase 4) --------------------------------------


def build_approval_policy(settings: Settings) -> Approval_Policy:
    """Return the configured Approval_Policy, defaulting to Auto_Approve_Policy (Req 5.7).

    ``settings.approval_policy == "human"`` selects the human-in-the-loop policy;
    everything else (``"auto"`` or an absent value) selects the keyless auto-approve
    default so runs complete end-to-end without external human input.
    """
    if getattr(settings, "approval_policy", "auto") == "human":
        return Human_In_The_Loop_Policy()
    return Auto_Approve_Policy()


def build_multi_agent_run_store(settings: Settings) -> Multi_Agent_Run_Store:
    """Return the Multi_Agent_Run_Store: Postgres in production, in-memory otherwise.

    Mirrors :func:`build_conversation_store` / :func:`build_trace_recorder`: the
    in-memory default keeps standalone/keyless runs fully functional without a database;
    the production profile persists to Postgres via ``Pg_Multi_Agent_Run_Store``.
    """
    if settings.persist_domain_stores():
        # Local import so the keyless in-memory path never depends on SQLAlchemy/psycopg.
        from agentforge.multiagent.store import Pg_Multi_Agent_Run_Store

        return Pg_Multi_Agent_Run_Store(settings.database_url)
    return InMemory_Multi_Agent_Run_Store()


@dataclass
class MultiAgentContext:
    """The wired multi-agent object graph the Phase 4 router depends on.

    Built once at startup (or injected in tests). Reuses the existing :class:`AgentContext`
    unchanged — the same wired ``Agent_Orchestrator`` powers every Agent_Role, so no new
    reasoning implementation is introduced (Req 11.1).
    """

    agent: AgentContext
    role_registry: Agent_Role_Registry
    approval_policy: Approval_Policy
    run_store: Multi_Agent_Run_Store
    gate: Human_Approval_Gate
    orchestrator: Multi_Agent_Orchestrator
    streaming_service: Multi_Agent_Streaming_Service


def build_multi_agent_context(
    settings: Settings,
    agent: AgentContext | None = None,
    **overrides,
) -> MultiAgentContext:
    """Compose the Phase 4 multi-agent object graph.

    Mirrors :func:`build_agent_context`: every collaborator may be injected via keyword
    ``overrides`` (tests pass keyless in-memory doubles), and anything not injected is
    built from the credential/profile-driven defaults. The four built-in roles are all
    registered against the **same** existing ``Agent_Orchestrator`` from the reused
    :class:`AgentContext` (Req 11.1), so no new reasoning loop is created here.

    Supported ``overrides`` keys (all optional):

    * ``role_registry`` — a pre-populated :class:`Agent_Role_Registry`.
    * ``approval_policy`` — an :class:`Approval_Policy` (overrides the setting).
    * ``run_store`` — a :class:`Multi_Agent_Run_Store` (typically the in-memory double).
    * ``checkpoint_store`` — a :class:`Checkpoint_Store` for the approval gate.
    * ``gate`` — a fully-built :class:`Human_Approval_Gate`.
    * ``orchestrator`` — a fully-built :class:`Multi_Agent_Orchestrator`.
    * ``streaming_service`` — a fully-built :class:`Multi_Agent_Streaming_Service`.
    """
    agent = agent or build_agent_context(settings)

    registry: Agent_Role_Registry = overrides.get("role_registry") or _default_role_registry(
        agent.orchestrator
    )

    policy: Approval_Policy = (
        overrides.get("approval_policy") or build_approval_policy(settings)
    )
    run_store: Multi_Agent_Run_Store = (
        overrides.get("run_store") or build_multi_agent_run_store(settings)
    )

    # The gate coordinates the in-process pause/resume via an in-memory Checkpoint_Store
    # (Task 7 seam). The run_store's ``save_checkpoint`` records the durable audit trail
    # separately per Task 10 — both are retained since they serve different concerns.
    checkpoint_store: Checkpoint_Store = (
        overrides.get("checkpoint_store") or Checkpoint_Store()
    )
    gate: Human_Approval_Gate = overrides.get("gate") or Human_Approval_Gate(
        policy=policy,
        store=checkpoint_store,
        trace=agent.trace_recorder,
    )

    orchestrator: Multi_Agent_Orchestrator = overrides.get(
        "orchestrator"
    ) or Multi_Agent_Orchestrator(
        registry=registry,
        pipeline=DEFAULT_PIPELINE,
        max_rounds=settings.max_rounds,
        max_revisions=settings.max_revisions,
        trace=agent.trace_recorder,
        gate=gate,
    )

    streaming_service: Multi_Agent_Streaming_Service = overrides.get(
        "streaming_service"
    ) or Multi_Agent_Streaming_Service(orchestrator, gate=gate if _policy_is_human(policy) else None)

    return MultiAgentContext(
        agent=agent,
        role_registry=registry,
        approval_policy=policy,
        run_store=run_store,
        gate=gate,
        orchestrator=orchestrator,
        streaming_service=streaming_service,
    )


def _default_role_registry(agent_orchestrator: Agent_Orchestrator) -> Agent_Role_Registry:
    """Register the four built-in roles against the SAME single-agent orchestrator (Req 11.1)."""
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent_orchestrator))
    registry.register(Researcher_Agent(agent_orchestrator))
    registry.register(Writer_Agent(agent_orchestrator))
    registry.register(Critic_Agent(agent_orchestrator))
    return registry


def _policy_is_human(policy: Approval_Policy) -> bool:
    """Return whether the approval policy requires pausing (needs a gate on the stream)."""
    return isinstance(policy, Human_In_The_Loop_Policy)



# --- Enterprise layer composition (Phase 5) ---------------------------------------


def build_rbac_policy() -> RBAC_Policy:
    """Return the RBAC_Policy (a stateless singleton over the static role map).

    A single instance is sufficient — :class:`RBAC_Policy` is a pure function of
    ``ROLE_PERMISSIONS`` and holds no per-request state (Req 3.6, 9.5).
    """
    return RBAC_Policy()


def build_identity_store(settings: Settings) -> Identity_Store:
    """Return the Identity_Store: Postgres in production, in-memory otherwise.

    Mirrors :func:`build_conversation_store`: the in-memory default keeps
    standalone/keyless runs fully functional without a database, while the production
    profile persists to Postgres via ``Pg_Identity_Store`` (Req 9.3, 9.5, 10.1). The
    Postgres adapter is imported lazily so the keyless path never depends on it.
    """
    if settings.persist_domain_stores():
        from agentforge.enterprise.identity import Pg_Identity_Store  # local import

        return Pg_Identity_Store(settings.database_url)
    return InMemory_Identity_Store()


def _build_password_hasher(settings: Settings) -> PasswordHasher:
    """Build the argon2id hasher from settings; shared by auth + API-key services."""
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )


def build_auth_service(settings: Settings, identity: Identity_Store) -> Auth_Service:
    """Build the Auth_Service, resolving the Token_Signing_Secret (Req 1.7, 1.8).

    Secret resolution:

    * ``settings.jwt_secret`` is used when present.
    * Otherwise, in the ``local`` profile a per-boot ``secrets.token_urlsafe(64)`` is
      generated so keyless dev boot and testing succeed (nothing is written to disk, so
      every restart naturally invalidates outstanding dev tokens — Req 1.7, 10.1).
    * Otherwise (production without a secret) a :class:`ConfigError` is raised
      defensively; ``load_settings`` already guards this before startup (Req 1.8).

    The argon2 ``PasswordHasher`` built here is exposed as ``auth._hasher`` and reused by
    the API_Key_Service, so there is exactly one hashing seam with two consumers.
    """
    if settings.jwt_secret is not None:
        jwt_secret = settings.jwt_secret.get_secret_value()
    elif settings.profile == "local":
        jwt_secret = secrets.token_urlsafe(64)  # per-boot dev secret (Req 1.7)
    else:  # pragma: no cover - load_settings already guards this path (Req 1.8)
        raise ConfigError(["jwt_secret"], detail="required in production profile")

    return Auth_Service(
        identity,
        jwt_secret=jwt_secret,
        jwt_algorithm=settings.jwt_algorithm,
        jwt_expiry_seconds=settings.jwt_expiry_seconds,
        password_hasher=_build_password_hasher(settings),
    )


def build_api_key_store(settings: Settings) -> API_Key_Store:
    """Return the API_Key_Store: Postgres in production, in-memory otherwise."""
    if settings.persist_domain_stores():
        from agentforge.enterprise.api_keys import Pg_API_Key_Store  # local import

        return Pg_API_Key_Store(settings.database_url)
    return InMemory_API_Key_Store()


def build_api_key_service(
    settings: Settings,
    store: API_Key_Store | None,
    rbac: RBAC_Policy,
    hasher: PasswordHasher,
) -> API_Key_Service:
    """Build the API_Key_Service over the given (or profile-selected) store.

    ``hasher`` is the **same** argon2 ``PasswordHasher`` used by the Auth_Service, so
    passwords and API-key secrets share one constant-time verifier (Req 5.1, 5.2).
    """
    key_store = store if store is not None else build_api_key_store(settings)
    return API_Key_Service(key_store, rbac, hasher)


def build_rate_limiter(
    settings: Settings,
    redis,
    *,
    clock: Callable[[], float] | None = None,
) -> Rate_Limiter:
    """Return the Rate_Limiter: Redis-backed when enabled + available, else NoOp.

    ``NoOp_Rate_Limiter`` is the keyless default (Req 6.5): when
    ``rate_limit_enabled`` is ``False`` or no Redis client is supplied, no counting
    occurs. Tests may inject a ``Fake_Clock_Rate_Limiter`` via ``build_enterprise_context``
    overrides instead.
    """
    if settings.rate_limit_enabled and redis is not None:
        kwargs: dict = {
            "max_requests": settings.rate_limit_max,
            "window_seconds": settings.rate_limit_window_seconds,
        }
        if clock is not None:
            kwargs["clock"] = clock
        # Redis_Rate_Limiter.check() is synchronous — it runs inside the sync
        # get_current_principal dependency (executed in a threadpool). The application's
        # shared redis.asyncio client CANNOT be driven from sync code: its
        # pipeline().execute() returns a coroutine, which made the limiter raise on every
        # authenticated request. Build a dedicated SYNCHRONOUS client from the same DSN
        # for the limiter's blocking INCR/EXPIRE. The passed ``redis`` (async client)
        # stays the "Redis is configured" gate; from_url() is lazy (no connection here),
        # so unit tests passing a sentinel still select the Redis limiter.
        import redis as _redis_sync

        sync_client = _redis_sync.Redis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        return Redis_Rate_Limiter(sync_client, **kwargs)
    return NoOp_Rate_Limiter()


@dataclass
class EnterpriseContext:
    """The wired enterprise object graph the Phase 5 dependencies depend on.

    Built once at startup (or injected in tests) and stored on
    ``app.state.enterprise_context``. The FastAPI dependencies in ``api/deps.py`` read
    the auth service, RBAC policy, API-key service, and rate limiter from here so the
    transport layer never constructs the enterprise graph itself (Req 9.5).
    """

    settings: Settings
    rbac: RBAC_Policy
    identity_store: Identity_Store
    auth_service: Auth_Service
    api_key_store: API_Key_Store
    api_key_service: API_Key_Service
    rate_limiter: Rate_Limiter
    audit_log: Audit_Log
    audit_service: Audit_Service


def build_enterprise_context(
    settings: Settings,
    *,
    redis=None,
    **overrides,
) -> EnterpriseContext:
    """Compose the Phase 5 enterprise object graph from settings.

    Every collaborator may be injected via keyword ``overrides`` (tests pass keyless
    in-memory doubles + a ``Fake_Clock_Rate_Limiter``); anything not injected is built
    from the credential/profile-driven defaults. The argon2 hasher built by the
    Auth_Service is shared with the API_Key_Service so both use one constant-time
    verifier (Req 1.6, 5.2, 9.5).

    Supported ``overrides`` keys (all optional): ``rbac``, ``identity_store``,
    ``auth_service``, ``api_key_store``, ``api_key_service``, ``rate_limiter``,
    ``audit_log``, ``audit_service``, and ``clock`` (forwarded to
    :func:`build_rate_limiter`).
    """
    rbac: RBAC_Policy = overrides.get("rbac") or build_rbac_policy()
    identity_store: Identity_Store = (
        overrides.get("identity_store") or build_identity_store(settings)
    )
    auth_service: Auth_Service = (
        overrides.get("auth_service") or build_auth_service(settings, identity_store)
    )
    api_key_store: API_Key_Store = (
        overrides.get("api_key_store") or build_api_key_store(settings)
    )
    # Reuse the SAME argon2 hasher the Auth_Service built (one hashing seam).
    api_key_service: API_Key_Service = overrides.get(
        "api_key_service"
    ) or build_api_key_service(settings, api_key_store, rbac, auth_service._hasher)
    rate_limiter: Rate_Limiter = overrides.get("rate_limiter") or build_rate_limiter(
        settings, redis, clock=overrides.get("clock")
    )

    audit_log: Audit_Log = overrides.get("audit_log") or build_audit_log(settings)
    audit_service: Audit_Service = overrides.get("audit_service") or Audit_Service(
        audit_log, required=settings.audit_log_required
    )

    return EnterpriseContext(
        settings=settings,
        rbac=rbac,
        identity_store=identity_store,
        auth_service=auth_service,
        api_key_store=api_key_store,
        api_key_service=api_key_service,
        rate_limiter=rate_limiter,
        audit_log=audit_log,
        audit_service=audit_service,
    )


def build_budget_store(settings: Settings) -> Budget_Store:
    """Return the Budget_Store: Postgres when the domain stores persist, in-memory otherwise.

    A budget that vanished on restart would be a cost control in name only, so it follows the
    same persistence predicate as every other domain store.
    """
    if settings.persist_domain_stores():
        return Pg_Budget_Store(settings.database_url)
    return InMemory_Budget_Store()


def build_webhook_delivery_store(settings: Settings) -> Webhook_Delivery_Store:
    """Return the Webhook_Delivery_Store: Postgres when the domain stores persist, else memory."""
    if settings.persist_domain_stores():
        return Pg_Webhook_Delivery_Store(settings.database_url)
    return InMemory_Webhook_Delivery_Store()


def build_webhook_subscription_store(
    settings: Settings, deliveries: Webhook_Delivery_Store | None = None
) -> Webhook_Subscription_Store:
    """Return the Webhook_Subscription_Store, paired with the delivery log it cascades into.

    ``deliveries`` is threaded through so the in-memory pair behaves like the Postgres pair,
    where ``ON DELETE CASCADE`` removes a subscription's delivery log with the subscription.
    Building the two independently would leave the keyless path with orphaned log rows and a
    behavioural difference from production that no test could observe.
    """
    if settings.persist_domain_stores():
        return Pg_Webhook_Subscription_Store(settings.database_url)
    return InMemory_Webhook_Subscription_Store(deliveries)


def build_webhook_transport(settings: Settings) -> Webhook_Transport:
    """Return the HTTP webhook transport, told whether loopback destinations are admissible."""
    return Httpx_Webhook_Transport(
        allow_loopback=settings.allow_loopback_webhooks()
    )


def build_audit_log(settings: Settings) -> Audit_Log:
    """Return the Audit_Log: Postgres when the domain stores persist, in-memory otherwise.

    Same predicate as every other domain store (``persist_domain_stores()``), so an audit
    trail is durable exactly when the data it describes is. The keyless unit lane keeps an
    in-memory trail, which is what makes auditing testable without infrastructure.
    """
    if settings.persist_domain_stores():
        return Pg_Audit_Log(settings.database_url)
    return InMemory_Audit_Log()



# --- Observability layer composition (Phase 6) ------------------------------------
#
# ``config/container.py`` remains the ONLY module that names concrete observability
# implementations. Each per-seam builder selects the Postgres-backed store in the
# production profile and the keyless in-memory double in local/keyless, mirroring the
# Phase 5 enterprise builders (Req 7.3, 9.7, 10.2).


def build_cost_model(settings: Settings) -> Cost_Model:
    """Return the active Cost_Model, parsing the rate table + defaults from Settings.

    Delegates to :func:`~agentforge.observability.cost.build_default_cost_model`; on the
    keyless path both default per-1K rates are ``"0.0"``, so every cost is a deterministic
    ``Decimal("0")`` (Req 2.4, 2.5, 2.6, 10.2).
    """
    return build_default_cost_model(settings)


def build_usage_store(settings: Settings) -> Usage_Store:
    """Return the Usage_Store: Postgres in production, in-memory otherwise (Req 10.3)."""
    if settings.persist_domain_stores():
        return Pg_Usage_Store(settings.database_url)
    return InMemory_Usage_Store()


def build_usage_recorder(
    settings: Settings, store: Usage_Store, cost_model: Cost_Model
) -> Usage_Recorder:
    """Return a Usage_Recorder that builds + persists Usage_Records via the Cost_Model."""
    return Usage_Recorder(store, cost_model)


def build_prompt_store(settings: Settings) -> Prompt_Store:
    """Return the Prompt_Store: Postgres in production, in-memory otherwise (Req 10.3)."""
    if settings.persist_domain_stores():
        return Pg_Prompt_Store(settings.database_url)
    return InMemory_Prompt_Store()


def build_prompt_registry(settings: Settings, store: Prompt_Store) -> Prompt_Registry:
    """Return the Prompt_Registry over the given (profile-selected) Prompt_Store."""
    return Prompt_Registry(store)


def _parse_blocklist(blocklist_json: str | None) -> tuple[str, ...]:
    """Parse ``guardrail_blocklist_json`` into a tuple of blocklist terms.

    Accepts a JSON array of strings (e.g. ``["term-a", "term-b"]``); ``None`` or an empty
    string yields an empty tuple so no blocklist term is configured on the keyless path.
    """
    if not blocklist_json:
        return ()
    import json

    raw = json.loads(blocklist_json)
    return tuple(str(term) for term in raw)


def build_guardrail_pipeline(settings: Settings) -> Guardrail_Pipeline:
    """Return the default deterministic Guardrail_Pipeline built from Settings.

    Supplies ``guardrail_max_input_chars`` and the parsed ``guardrail_blocklist_json`` to
    the default pipeline factory; the resulting pipeline is a pure function of its content
    on the keyless path (Req 5.7, 5.8, 10.2).
    """
    return build_default_pipeline(
        max_input_chars=settings.guardrail_max_input_chars,
        blocklist=_parse_blocklist(settings.guardrail_blocklist_json),
    )


def build_evaluation_store(settings: Settings) -> Evaluation_Store:
    """Return the Evaluation_Store: Postgres in production, in-memory otherwise (Req 10.3)."""
    if settings.persist_domain_stores():
        return Pg_Evaluation_Store(settings.database_url)
    return InMemory_Evaluation_Store()


def build_default_evaluators() -> dict[str, Evaluator]:
    """Return the built-in deterministic evaluators keyed by their stable names (Req 6.7)."""
    evaluators: list[Evaluator] = [
        Exact_Match_Evaluator(),
        Contains_Evaluator(),
        Heuristic_Evaluator(),
    ]
    return {evaluator.name: evaluator for evaluator in evaluators}


def build_evaluation_framework(
    settings: Settings,
    store: Evaluation_Store,
    pipeline_runner: Callable[[str, UUID], str],
    evaluators: dict[str, Evaluator],
) -> Evaluation_Framework:
    """Return the Evaluation_Framework over the store, runner, and evaluator map."""
    return Evaluation_Framework(store, pipeline_runner, evaluators)


def _default_pipeline_runner(app: AppContext | None) -> Callable[[str, UUID], str]:
    """Build the keyless evaluation pipeline runner from the RAG object graph.

    On the keyless path the wired provider is the deterministic ``Fallback_Provider``
    (re-wrapped by the ``Instrumented_Provider``), so the produced actual output is a pure
    function of the item input (Req 6.2, 6.6). When no AppContext is available (e.g. a
    seam-level unit test), a trivial runner returning an empty string is used.
    """
    if app is None:
        def _empty_runner(text: str, org_id: UUID) -> str:
            return ""

        return _empty_runner

    rag = app.rag_service

    def _runner(text: str, org_id: UUID) -> str:
        return rag.answer(text, org_id=org_id).text

    return _runner


@dataclass
class ObservabilityContext:
    """The wired observability object graph the Phase 6 routers depend on.

    Built once at startup (or injected in tests) and stored on
    ``app.state.observability_context``. The FastAPI dependencies in ``api/deps.py`` read
    each seam from here so the transport layer never constructs the observability graph
    itself (Req 7.3, 9.7).
    """

    settings: Settings
    tracing_exporter: Tracing_Exporter
    trace_export_service: Trace_Export_Service
    budget_store: Budget_Store
    budget_guard: Budget_Guard
    webhook_subscription_store: Webhook_Subscription_Store
    webhook_delivery_store: Webhook_Delivery_Store
    webhook_transport: Webhook_Transport
    webhook_emitter: Webhook_Emitter
    usage_store: Usage_Store
    cost_model: Cost_Model
    usage_recorder: Usage_Recorder
    usage_sink: Usage_Sink
    analytics_service: Analytics_Service
    prompt_store: Prompt_Store
    prompt_registry: Prompt_Registry
    guardrail_pipeline: Guardrail_Pipeline
    evaluation_store: Evaluation_Store
    evaluators: dict[str, Evaluator]
    evaluation_framework: Evaluation_Framework


def build_observability_context(
    settings: Settings,
    *,
    app: AppContext | None = None,
    trace_recorder: Trace_Recorder | None = None,
    **overrides,
) -> ObservabilityContext:
    """Compose the Phase 6 observability object graph from settings.

    Every collaborator may be injected via keyword ``overrides`` (tests pass keyless
    in-memory doubles / capturing fakes); anything not injected is built from the
    credential/profile-driven defaults. When an ``app`` :class:`AppContext` is supplied,
    its ``usage_store`` / ``usage_sink`` are reused so the ``Instrumented_Provider`` and
    the ``Analytics_Service`` share exactly one store (a usage record emitted by the
    provider is visible to the analytics report — Req 2.3, 3.3), and its ``rag_service``
    backs the keyless evaluation pipeline runner (Req 6.2).

    ``config/container.py`` is the only module naming the concrete exporter, stores, cost
    model, registry, pipeline, and framework, so a new implementation is a builder edit
    here — never a router or core-flow change (Req 7.3, 9.7).

    ``trace_recorder`` is the recorder the export service reads completed traces back
    from; the composition root passes the agentic context's instance so both read one
    store. Omitting it leaves trace export unavailable (reported as such rather than
    silently exporting nothing), which is only correct for the keyless NoOp exporter.

    Supported ``overrides`` keys (all optional): ``tracing_exporter``,
    ``trace_export_service``, ``budget_store``, ``budget_guard``, ``usage_store``,
    ``cost_model``, ``usage_recorder``, ``usage_sink``, ``analytics_service``,
    ``prompt_store``, ``prompt_registry``, ``guardrail_pipeline``, ``evaluation_store``,
    ``evaluators``, ``pipeline_runner``, ``evaluation_framework``,
    ``webhook_subscription_store``, ``webhook_delivery_store``, ``webhook_transport``, and
    ``webhook_emitter``.
    """
    tracing_exporter: Tracing_Exporter = (
        overrides.get("tracing_exporter") or build_tracing_exporter(settings)
    )
    # The export service bridges the exporter to the Trace_Recorder that OWNS the traces.
    # The recorder is passed in rather than built here because the agentic context already
    # holds the one instance (and, on the Postgres path, its engine) — building a second
    # would open a second connection pool to read the same rows.
    trace_export_service: Trace_Export_Service = overrides.get(
        "trace_export_service"
    ) or Trace_Export_Service(tracing_exporter, trace_recorder)

    # Reuse the app's usage store/sink when available so the provider and analytics share
    # one store; otherwise build the profile-selected defaults.
    usage_store: Usage_Store = overrides.get("usage_store") or (
        app.usage_store
        if app is not None and app.usage_store is not None
        else build_usage_store(settings)
    )
    cost_model: Cost_Model = overrides.get("cost_model") or build_cost_model(settings)
    usage_recorder: Usage_Recorder = overrides.get(
        "usage_recorder"
    ) or build_usage_recorder(settings, usage_store, cost_model)
    usage_sink: Usage_Sink = overrides.get("usage_sink") or (
        app.usage_sink
        if app is not None and app.usage_sink is not None
        else Recording_Usage_Sink(usage_recorder)
    )
    analytics_service: Analytics_Service = (
        overrides.get("analytics_service") or Analytics_Service(usage_store)
    )

    prompt_store: Prompt_Store = overrides.get("prompt_store") or build_prompt_store(
        settings
    )
    prompt_registry: Prompt_Registry = overrides.get(
        "prompt_registry"
    ) or build_prompt_registry(settings, prompt_store)

    guardrail_pipeline: Guardrail_Pipeline = (
        overrides.get("guardrail_pipeline") or build_guardrail_pipeline(settings)
    )

    evaluation_store: Evaluation_Store = overrides.get(
        "evaluation_store"
    ) or build_evaluation_store(settings)
    evaluators: dict[str, Evaluator] = (
        overrides.get("evaluators") or build_default_evaluators()
    )
    pipeline_runner = overrides.get("pipeline_runner") or _default_pipeline_runner(app)
    evaluation_framework: Evaluation_Framework = overrides.get(
        "evaluation_framework"
    ) or build_evaluation_framework(
        settings, evaluation_store, pipeline_runner, evaluators
    )

    budget_store: Budget_Store = overrides.get("budget_store") or build_budget_store(
        settings
    )
    budget_guard: Budget_Guard = overrides.get("budget_guard") or Budget_Guard(
        budget_store, analytics_service, cache_seconds=settings.budget_cache_seconds
    )

    webhook_delivery_store: Webhook_Delivery_Store = overrides.get(
        "webhook_delivery_store"
    ) or build_webhook_delivery_store(settings)
    webhook_subscription_store: Webhook_Subscription_Store = overrides.get(
        "webhook_subscription_store"
    ) or build_webhook_subscription_store(settings, webhook_delivery_store)
    webhook_transport: Webhook_Transport = overrides.get(
        "webhook_transport"
    ) or build_webhook_transport(settings)
    webhook_emitter: Webhook_Emitter = overrides.get("webhook_emitter") or Webhook_Emitter(
        webhook_subscription_store,
        webhook_delivery_store,
        webhook_transport,
        max_attempts=settings.webhook_max_attempts,
        timeout_seconds=settings.webhook_timeout_seconds,
        backoff_seconds=settings.webhook_backoff_seconds,
    )

    return ObservabilityContext(
        settings=settings,
        tracing_exporter=tracing_exporter,
        trace_export_service=trace_export_service,
        budget_store=budget_store,
        budget_guard=budget_guard,
        webhook_subscription_store=webhook_subscription_store,
        webhook_delivery_store=webhook_delivery_store,
        webhook_transport=webhook_transport,
        webhook_emitter=webhook_emitter,
        usage_store=usage_store,
        cost_model=cost_model,
        usage_recorder=usage_recorder,
        usage_sink=usage_sink,
        analytics_service=analytics_service,
        prompt_store=prompt_store,
        prompt_registry=prompt_registry,
        guardrail_pipeline=guardrail_pipeline,
        evaluation_store=evaluation_store,
        evaluators=evaluators,
        evaluation_framework=evaluation_framework,
    )
