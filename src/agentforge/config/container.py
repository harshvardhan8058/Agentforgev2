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

from agentforge.chunking.chunker import Chunker
from agentforge.config.settings import Settings
from agentforge.embeddings.base import Embedding_Provider
from agentforge.embeddings.sentence_transformer import SentenceTransformer_Embeddings
from agentforge.ingestion.service import Ingestion_Service
from agentforge.llm.base import LLM_Provider
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.rag.service import RAG_Service
from agentforge.retrieval.retriever import Retriever
from agentforge.storage.base import DocumentStore
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
