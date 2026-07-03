"""FastAPI dependency wiring for the Phase 2 routers.

The composition root (``config/container.py``) builds a single :class:`AppContext`
holding the wired object graph (providers, vector store, and services). It is stored on
``app.state.app_context`` at startup (or injected directly by tests). These dependency
callables surface that graph — and its individual collaborators — to the routers so the
transport layer never constructs providers itself and stays trivially testable with
injected fakes.
"""

from __future__ import annotations

from fastapi import Request

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.config.container import AgentContext, AppContext
from agentforge.conversation.base import Conversation_Store
from agentforge.ingestion.service import Ingestion_Service
from agentforge.rag.service import RAG_Service
from agentforge.storage.base import DocumentStore
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.tracing.base import Trace_Recorder
from agentforge.vectorstore.base import Vector_Store


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
