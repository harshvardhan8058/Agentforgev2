"""Multi-agent router — start / stream / approval / result endpoints (Phase 4).

All endpoints share the existing FastAPI application and render errors through the
existing uniform error envelope (Req 9.7). Synchronous orchestrator/store/gate calls run
in a worker thread via ``run_in_threadpool`` to avoid blocking the event loop, mirroring
the Phase 3 agent router.

Endpoints:

* ``POST /multi-agent/runs`` — create + persist a Multi_Agent_Run, run the orchestrator
  synchronously to completion (streaming is a separate endpoint), and return the id
  (Req 9.1, 10.1, 10.5).
* ``POST /multi-agent/runs/{id}/stream`` — resolve the run's task from the store and
  stream a fresh :class:`Multi_Agent_Streaming_Service` run over SSE (Req 9.2). Unknown
  id -> 404 via the envelope (Req 9.6).
* ``POST /multi-agent/runs/{id}/approval`` — forward the ``Approval_Decision`` to the
  ``Human_Approval_Gate`` (Req 9.3). A decision to a non-paused run is rejected with a
  ``run-not-awaiting-approval`` error (Req 5.5). Unknown id -> 404 (Req 9.6).
* ``GET /multi-agent/runs/{id}`` — return the run's status, termination reason, final
  output (when terminated), and the ordered role-attributed trace (Req 9.4). Unknown
  id -> 404 (Req 9.6); terminated-but-unavailable data -> ``unavailable`` (Req 9.5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from agentforge.api.deps import get_multi_agent_context
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    CitationModel,
    FinalOutputModel,
    MultiAgentRunResult,
    StartMultiAgentRunRequest,
    StartMultiAgentRunResponse,
    TraceEntryModel,
)
from agentforge.config.container import MultiAgentContext
from agentforge.multiagent.approval import RunNotAwaitingApprovalError
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Multi_Agent_Run,
    Termination_Reason,
)

router = APIRouter(tags=["multi-agent"])


# --- helpers ----------------------------------------------------------------------


def _run_status_name(run: Multi_Agent_Run) -> str:
    """Return the run's status literal for the response schema."""
    # Multi_Agent_Run.status is a plain str set by the store ("running",
    # "awaiting_approval", or "terminated"); the domain type already matches the schema.
    return run.status


def _lookup_run(ctx: MultiAgentContext, run_id: str) -> Multi_Agent_Run:
    """Fetch the run or raise a 404 AppError via the uniform envelope (Req 9.6)."""
    run = ctx.run_store.get(run_id)
    if run is None:
        raise AppError(
            "not_found",
            f"multi-agent run {run_id!r} was not found",
            status.HTTP_404_NOT_FOUND,
        )
    return run


def _final_output_model(run: Multi_Agent_Run) -> FinalOutputModel | None:
    """Render the run's Final_Output as a pydantic model, or ``None`` when absent."""
    if run.final_output is None:
        return None
    return FinalOutputModel(
        content=run.final_output.content,
        citations=[
            CitationModel(document_id=c.document_id, chunk_id=c.chunk_id)
            for c in run.final_output.citations
        ],
    )


def _termination_reason_name(run: Multi_Agent_Run) -> str | None:
    """Return the run's Termination_Reason as its wire value, or ``None`` if unset."""
    return run.termination_reason.value if run.termination_reason else None


# --- POST /multi-agent/runs -------------------------------------------------------


@router.post(
    "/multi-agent/runs",
    response_model=StartMultiAgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_multi_agent_run(
    payload: StartMultiAgentRunRequest,
    ctx: MultiAgentContext = Depends(get_multi_agent_context),
) -> StartMultiAgentRunResponse:
    """Start a Multi_Agent_Run, persist it, and run it synchronously to completion.

    Under the keyless auto-approve default the orchestrator terminates on the same
    request; streaming is exposed separately by :func:`stream_multi_agent_run`. The run
    is persisted before the orchestrator runs (Req 10.1), the terminal ``Final_Output``
    and ``Termination_Reason`` are persisted on completion (Req 10.5), and a start-time
    failure surfaces through the existing uniform error envelope (Req 9.1).
    """

    def _start() -> StartMultiAgentRunResponse:
        conversation_id = payload.conversation_id or ctx.agent.conversation_store.create()

        try:
            run = ctx.run_store.create(conversation_id, payload.task)
            # Reuse the run_store-assigned id so the orchestrator, the trace, and the
            # store record all key off the same run_id.
            final_state = ctx.orchestrator.run(
                payload.task,
                conversation_id=conversation_id,
                run_id=run.id,
            )
            ctx.run_store.terminate(
                run.id,
                final_state.final_output,
                final_state.termination_reason or Termination_Reason.ABORTED,
            )
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 - render through the uniform envelope
            raise AppError(
                "run_start_failed",
                f"failed to start multi-agent run: {exc}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc

        # After ``terminate`` the persisted run has status = "terminated".
        persisted = ctx.run_store.get(run.id) or run
        return StartMultiAgentRunResponse(
            run_id=persisted.id,
            conversation_id=persisted.conversation_id,
            status=_run_status_name(persisted),
        )

    return await run_in_threadpool(_start)


# --- POST /multi-agent/runs/{id}/stream -------------------------------------------


@router.post("/multi-agent/runs/{run_id}/stream")
async def stream_multi_agent_run(
    run_id: str,
    ctx: MultiAgentContext = Depends(get_multi_agent_context),
) -> StreamingResponse:
    """Stream a fresh multi-agent run for ``run_id`` over Server-Sent Events (Req 9.2).

    The run's ``task`` is resolved from the run store; unknown id -> 404 via the
    envelope. The stream ends in exactly one terminal event (``completion`` or ``error``)
    as guaranteed by :class:`Multi_Agent_Streaming_Service`.
    """
    run = await run_in_threadpool(_lookup_run, ctx, run_id)

    def _iter():
        # The streaming service assigns its own event ids; using ``run.id`` here aligns
        # the streamed run with the persisted record and its trace entries.
        yield from ctx.streaming_service.iter_sse_frames(
            run.task,
            conversation_id=run.conversation_id,
            run_id=run.id,
        )

    return StreamingResponse(_iter(), media_type="text/event-stream")


# --- POST /multi-agent/runs/{id}/approval -----------------------------------------


@router.post(
    "/multi-agent/runs/{run_id}/approval",
    response_model=ApprovalDecisionResponse,
)
async def submit_approval(
    run_id: str,
    payload: ApprovalDecisionRequest,
    ctx: MultiAgentContext = Depends(get_multi_agent_context),
) -> ApprovalDecisionResponse:
    """Forward an ``Approval_Decision`` to the ``Human_Approval_Gate`` (Req 9.3).

    * Unknown ``run_id`` -> ``404 not_found`` via the envelope (Req 9.6).
    * A decision to a run that is not currently awaiting approval is rejected with a
      ``409 run-not-awaiting-approval`` error via the envelope, and the rejected attempt
      has already been recorded in the trace by the gate (Req 5.5).
    """
    run = await run_in_threadpool(_lookup_run, ctx, run_id)

    decision = Approval_Decision(
        type=ApprovalDecisionType(payload.type),
        feedback=payload.feedback,
        edited_content=payload.edited_content,
    )

    def _submit() -> ApprovalDecisionResponse:
        try:
            resumed_state = ctx.gate.submit(run_id, decision)
        except RunNotAwaitingApprovalError as exc:
            raise AppError(
                "run-not-awaiting-approval",
                str(exc),
                status.HTTP_409_CONFLICT,
            ) from exc

        # Persist the decision on the run_store audit trail (Req 10.3).
        try:
            ctx.run_store.record_decision(run_id, decision)
        except Exception:  # noqa: BLE001 - audit is best-effort; the gate has resumed
            pass

        # If the resume terminated the run (e.g. rejected past the revision bound),
        # persist the terminal outcome and reflect it in the response.
        if resumed_state.termination_reason is not None:
            ctx.run_store.terminate(
                run_id,
                resumed_state.final_output,
                resumed_state.termination_reason,
            )
            return ApprovalDecisionResponse(
                run_id=run_id,
                status="terminated",
                termination_reason=resumed_state.termination_reason.value,
            )

        # Otherwise the run has resumed and is running (or awaiting a next checkpoint).
        current = ctx.run_store.get(run_id) or run
        return ApprovalDecisionResponse(
            run_id=run_id,
            status=_run_status_name(current),
            termination_reason=_termination_reason_name(current),
        )

    return await run_in_threadpool(_submit)


# --- GET /multi-agent/runs/{id} ---------------------------------------------------


@router.get(
    "/multi-agent/runs/{run_id}",
    response_model=MultiAgentRunResult,
)
async def get_multi_agent_run(
    run_id: str,
    ctx: MultiAgentContext = Depends(get_multi_agent_context),
) -> MultiAgentRunResult:
    """Return the ordered trace + result for a Multi_Agent_Run (Req 9.4).

    Unknown ``run_id`` -> 404 via the envelope (Req 9.6). When the run has terminated but
    its ``Final_Output`` and ``Termination_Reason`` cannot be retrieved together, a
    ``unavailable`` error is returned via the envelope (Req 9.5).
    """
    run = await run_in_threadpool(_lookup_run, ctx, run_id)
    trace = await run_in_threadpool(ctx.agent.trace_recorder.get_trace, run_id)

    if run.status == "terminated" and (
        run.termination_reason is None or run.final_output is None
    ):
        # A completed run must carry both its Final_Output and Termination_Reason;
        # missing either indicates an unavailable-data condition (Req 9.5).
        raise AppError(
            "unavailable",
            f"result data for run {run_id!r} is unavailable",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return MultiAgentRunResult(
        run_id=run.id,
        status=_run_status_name(run),
        termination_reason=_termination_reason_name(run),
        final_output=_final_output_model(run),
        trace=[
            TraceEntryModel(
                ordinal=e.ordinal,
                step_type=e.step_type,
                role_id=(e.detail or {}).get("role_id"),
                tool_name=e.tool_name,
                outcome=e.outcome,
            )
            for e in trace.entries
        ],
    )
