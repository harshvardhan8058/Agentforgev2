"""Query router: ``POST /query`` — Task 13.2.

Delegates to the RAG_Service and returns a grounded, cited answer (``200``). The
no-context case is also ``200`` with ``grounded=false`` and an empty citation list (no
fabrication — Req 12.5). If the active ``LLM_Provider`` (e.g. Groq) fails, the error is
surfaced as ``502 llm_provider_error`` identifying the provider (Req 11.5).

The RAG pipeline (embedding + generation) is synchronous, so it runs in a worker thread
to avoid blocking the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_rag_service
from agentforge.api.errors import AppError
from agentforge.api.schemas import CitationModel, QueryRequest, QueryResponse
from agentforge.llm.base import LLMProviderError
from agentforge.rag.service import RAG_Service

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    service: RAG_Service = Depends(get_rag_service),
) -> QueryResponse:
    """Answer a query with grounding and citations."""
    try:
        answer = await run_in_threadpool(service.answer, payload.query, payload.top_k)
    except LLMProviderError as exc:
        # The provider failure message already identifies the provider (Req 11.5).
        raise AppError(
            "llm_provider_error", str(exc), status.HTTP_502_BAD_GATEWAY
        ) from exc

    return QueryResponse(
        answer=answer.text,
        grounded=answer.grounded,
        provider=answer.provider,
        citations=[
            CitationModel(document_id=c.document_id, chunk_id=c.chunk_id)
            for c in answer.citations
        ],
    )
