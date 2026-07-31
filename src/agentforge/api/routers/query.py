"""Query router: ``POST /query`` — Task 13.2.

Delegates to the RAG_Service and returns a grounded, cited answer (``200``). The
no-context case is also ``200`` with ``grounded=false`` and an empty citation list (no
fabrication — Req 12.5). If the active ``LLM_Provider`` (e.g. Groq) fails, the error is
surfaced as ``502 llm_provider_error`` identifying the provider (Req 11.5).

The RAG pipeline (embedding + generation) is synchronous, so it runs in a worker thread
to avoid blocking the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    enforce_budget,
    get_optional_guardrail_pipeline,
    get_rag_service,
    get_webhook_emitter,
    require_permission,
)
from agentforge.api.errors import AppError, defer_after_error
from agentforge.api.schemas import CitationModel, QueryRequest, QueryResponse
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.llm.base import LLMProviderError
from agentforge.observability.guardrails.base import (
    Guardrail_Pipeline,
    apply_input_guardrail,
)
from agentforge.rag.service import RAG_Service
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.events import emit_guardrail_blocked

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    request: Request,
    service: RAG_Service = Depends(get_rag_service),
    pipeline: Guardrail_Pipeline | None = Depends(get_optional_guardrail_pipeline),
    emitter: Webhook_Emitter = Depends(get_webhook_emitter),
    principal: Principal = Depends(require_permission(Permission.RUN_AGENTS)),
    _budget: Principal = Depends(enforce_budget),
) -> QueryResponse:
    """Answer a query with grounding and citations, scoped to the caller's org.

    The input guardrail pipeline runs **before** the RAG_Service is invoked: a blocking
    guardrail raises ``AppError("guardrail_blocked", 400)`` and the downstream generation
    is never reached (Req 5.4). The output pipeline then runs on the produced answer and
    its flags are attached to the response without blocking (Req 5.5, 5.6). A block also
    emits the ``guardrail.blocked`` webhook, deferred onto the error response so a refused
    input still reaches the subscribers who need to know about it.
    """

    def _downstream():
        return service.answer(payload.query, payload.top_k, org_id=principal.org_id)

    def _report_block(reason: str | None) -> None:
        defer_after_error(
            request,
            lambda: emit_guardrail_blocked(
                emitter, principal.org_id, surface="query", reason=reason
            ),
        )

    try:
        if pipeline is not None:
            answer = await run_in_threadpool(
                lambda: apply_input_guardrail(
                    pipeline, payload.query, _downstream, on_block=_report_block
                )
            )
        else:
            answer = await run_in_threadpool(_downstream)
    except LLMProviderError as exc:
        # The provider failure message already identifies the provider (Req 11.5).
        raise AppError(
            "llm_provider_error", str(exc), status.HTTP_502_BAD_GATEWAY
        ) from exc

    flags: list[str] = []
    if pipeline is not None:
        flags = list(pipeline.evaluate(answer.text).flags)

    return QueryResponse(
        answer=answer.text,
        grounded=answer.grounded,
        provider=answer.provider,
        citations=[
            CitationModel(document_id=c.document_id, chunk_id=c.chunk_id)
            for c in answer.citations
        ],
        flags=flags,
    )
