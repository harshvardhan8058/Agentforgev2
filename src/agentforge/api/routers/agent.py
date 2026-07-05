"""Agent router: bounded run, streaming run, and trace retrieval (Req 1.7, 8.5, 9, 10).

* ``POST /agent/run`` appends the user message, executes a bounded Agent_Run, persists the
  final assistant message (Req 8.5), and returns the run id, conversation id, answer, the
  single termination reason (Req 1.7), and any citations.
* ``POST /agent/stream`` streams the run over Server-Sent Events via the
  ``SSE_Streaming_Service`` (``text/event-stream``), ending in exactly one terminal event
  (Req 9.1, 9.3, 9.6, 9.9).
* ``GET /agent/runs/{run_id}/trace`` returns the ordered trace entries, or ``404`` via the
  existing envelope for an unknown run (Req 10.3, 10.4).

The orchestrator and store calls are synchronous, so they run in a worker thread to avoid
blocking the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from agentforge.agent.orchestrator import Agent_Orchestrator, extract_citations
from agentforge.api.deps import (
    get_conversation_store,
    get_optional_guardrail_pipeline,
    get_orchestrator,
    get_streaming_service,
    get_trace_recorder,
    require_permission,
)
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    CitationModel,
    TraceEntryModel,
    TraceResponse,
)
from agentforge.conversation.base import Conversation_Store
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.guardrails.base import (
    Guardrail_Pipeline,
    apply_input_guardrail,
)
from agentforge.streaming.base import AgentRunInput
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.tracing.base import Trace_Recorder

router = APIRouter(tags=["agent"])


def _resolve_conversation(
    store: Conversation_Store, org_id, conversation_id: str | None
) -> str:
    """Return the target conversation id, creating one in ``org_id`` when none is supplied."""
    return conversation_id or store.create(org_id)


@router.post("/agent/run", response_model=AgentRunResponse)
async def run_agent(
    payload: AgentRunRequest,
    orchestrator: Agent_Orchestrator = Depends(get_orchestrator),
    store: Conversation_Store = Depends(get_conversation_store),
    pipeline: Guardrail_Pipeline | None = Depends(get_optional_guardrail_pipeline),
    principal: Principal = Depends(require_permission(Permission.RUN_AGENTS)),
) -> AgentRunResponse:
    """Run the bounded agent loop and return its grounded result (Req 1.7, 8.5).

    The input guardrail pipeline runs **before** the orchestrator is invoked: a blocking
    guardrail raises ``AppError("guardrail_blocked", 400)`` and the agent loop is never
    reached (Req 5.4). The output pipeline runs on the final answer and its flags are
    attached to the response without blocking (Req 5.5, 5.6).
    """

    org_id = principal.org_id

    def _run() -> AgentRunResponse:
        conversation_id = _resolve_conversation(store, org_id, payload.conversation_id)
        store.append(org_id, conversation_id, "user", payload.message)
        context = store.history(org_id, conversation_id)

        def _invoke():
            return orchestrator.run(
                payload.message,
                context,
                conversation_id=conversation_id,
                org_id=org_id,
            )

        # Input guardrail: a block prevents the orchestrator invocation entirely (Req 5.4).
        if pipeline is not None:
            state = apply_input_guardrail(pipeline, payload.message, _invoke)
        else:
            state = _invoke()

        answer = state.final_answer or ""
        # Persist the final assistant message on completion (Req 8.5).
        store.append(org_id, conversation_id, "assistant", answer)

        flags: list[str] = []
        if pipeline is not None:
            flags = list(pipeline.evaluate(answer).flags)

        return AgentRunResponse(
            run_id=state.run_id,
            conversation_id=conversation_id,
            answer=answer,
            termination_reason=state.termination_reason.value,
            citations=[
                CitationModel(
                    document_id=c.get("document_id", ""),
                    chunk_id=c.get("chunk_id", ""),
                )
                for c in extract_citations(state)
            ],
            flags=flags,
        )

    return await run_in_threadpool(_run)


@router.post("/agent/stream")
async def stream_agent(
    payload: AgentRunRequest,
    streaming: SSE_Streaming_Service = Depends(get_streaming_service),
    store: Conversation_Store = Depends(get_conversation_store),
    principal: Principal = Depends(require_permission(Permission.RUN_AGENTS)),
) -> StreamingResponse:
    """Stream the agent run over Server-Sent Events, scoped to the caller's org (Req 9.1-9.9)."""
    org_id = principal.org_id
    conversation_id = await run_in_threadpool(
        _resolve_conversation, store, org_id, payload.conversation_id
    )
    await run_in_threadpool(store.append, org_id, conversation_id, "user", payload.message)
    context = await run_in_threadpool(store.history, org_id, conversation_id)

    run_input = AgentRunInput(
        message=payload.message,
        conversation_id=conversation_id,
        conversation_context=context,
        org_id=org_id,
    )
    return StreamingResponse(
        streaming.iter_sse_frames(run_input),
        media_type="text/event-stream",
    )


@router.get("/agent/runs/{run_id}/trace", response_model=TraceResponse)
async def get_run_trace(
    run_id: str,
    recorder: Trace_Recorder = Depends(get_trace_recorder),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> TraceResponse:
    """Return the ordered trace for the caller's org run; 404 when unknown/cross-tenant (Req 10.3, 4.3)."""
    trace = await run_in_threadpool(recorder.get_trace, principal.org_id, run_id)
    if not trace.entries:
        raise AppError(
            "not_found",
            f"agent run {run_id!r} was not found",
            status.HTTP_404_NOT_FOUND,
        )
    return TraceResponse(
        run_id=run_id,
        entries=[
            TraceEntryModel(
                ordinal=e.ordinal,
                step_type=e.step_type,
                tool_name=e.tool_name,
                outcome=e.outcome,
            )
            for e in trace.entries
        ],
    )
