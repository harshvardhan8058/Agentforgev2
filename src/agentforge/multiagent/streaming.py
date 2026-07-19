"""Multi_Agent_Streaming_Service (Phase 4) — SSE-style streaming of a Multi_Agent_Run.

The service mirrors the Phase 3 SSE mechanics — monotonic sequence, production order, and
the **exactly-one-terminal-event guarantee** — and extends only the event vocabulary with
the multi-agent event types (``agent_started``, ``plan``, ``research``, ``draft``,
``critic_feedback``, ``approval_required``, ``completion``, ``error``).

Design notes
------------
Rather than driving the LangGraph ``StateGraph`` and translating per-node updates, this
service reuses the small typed helpers already exposed by
:class:`~agentforge.multiagent.orchestrator.Multi_Agent_Orchestrator`
(``initialize_state`` / ``act_role`` / ``route_after_review`` / ``final_output_for``) to
run the collaboration step-by-step in the same order the graph would, but from a plain
Python generator. This choice matches the task's guidance ("if that's easier than
graph.stream, do that — the exactly-one-terminal-event contract is what matters") and
keeps two important properties trivially provable:

* Every yielded event is produced from a single ``try``/``except`` wrapping the whole
  generator body, so any exception raised in the orchestrator, the role, or the gate is
  translated into **exactly one** terminal ``error`` event and no ``completion`` is
  emitted (Req 7.7, 7.8).
* Under the ``Fallback_Provider`` + ``Auto_Approve_Policy``, role behavior, node order,
  routing decisions, and the emitted event sequence are deterministic — identical input
  produces identical ordered event types + role identifiers, and identical per-event data
  for fields that are pure functions of the input (Req 7.9).

The initial ``agent_started`` event for the Planner is emitted **before** any role runs,
so the first event is produced immediately (Req 7.1). ``approval_required`` is a
**non-terminal** pause signal: when the injected :class:`Human_Approval_Gate` decides to
pause at a checkpoint, the service emits ``approval_required`` and stops — the run resumes
on a separate request and can be re-streamed by a fresh call (Req 7.5).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from agentforge.multiagent.approval import (
    CHECKPOINT_AFTER_PLAN,
    CHECKPOINT_BEFORE_FINALIZE,
    Human_Approval_Gate,
)
from agentforge.enterprise.tenancy import set_current_org
from agentforge.multiagent.graph import (
    ROUTE_APPROVE,
    ROUTE_REVISE,
    ROUTE_REVS,
    ROUTE_ROUNDS,
)
from agentforge.multiagent.models import Termination_Reason
from agentforge.multiagent.state import Blackboard_State

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agentforge.multiagent.orchestrator import Multi_Agent_Orchestrator


class MultiAgentStreamEventType(str, Enum):
    """The exactly-one type carried by each streamed multi-agent event (Req 7.3)."""

    AGENT_STARTED = "agent_started"
    PLAN = "plan"
    RESEARCH = "research"
    DRAFT = "draft"
    CRITIC_FEEDBACK = "critic_feedback"
    APPROVAL_REQUIRED = "approval_required"
    COMPLETION = "completion"  # terminal (success)
    ERROR = "error"  # terminal (failure)


# The terminal event types; a stream emits exactly one of these when it terminates
# normally or on error, then closes (Req 7.6, 7.7, 7.8).
MA_TERMINAL_EVENT_TYPES: frozenset[MultiAgentStreamEventType] = frozenset(
    {MultiAgentStreamEventType.COMPLETION, MultiAgentStreamEventType.ERROR}
)


@dataclass
class MultiAgentStreamEvent:
    """A single streamed multi-agent event with a monotonic sequence (Req 7.4)."""

    type: MultiAgentStreamEventType
    data: dict = field(default_factory=dict)
    sequence: int = 0

    @property
    def is_terminal(self) -> bool:
        """Whether this event is a terminal event (``completion`` or ``error``)."""
        return self.type in MA_TERMINAL_EVENT_TYPES


def multiagent_format_sse_frame(event: MultiAgentStreamEvent) -> str:
    """Render a :class:`MultiAgentStreamEvent` as a Server-Sent Events frame.

    Shape matches the Phase 3 ``format_sse_frame`` (``event: <type>\\ndata: <json>\\n\\n``)
    so clients can consume both streams identically. The JSON payload embeds the monotonic
    ``sequence`` so end-to-end production order is preserved (Req 7.4).
    """
    payload = {"sequence": event.sequence, **event.data}
    body = json.dumps(payload, sort_keys=True, default=str)
    return f"event: {event.type.value}\ndata: {body}\n\n"


class Multi_Agent_Streaming_Service:
    """Stream a Multi_Agent_Run over SSE with the single-terminal guarantee (Req 7)."""

    def __init__(
        self,
        orchestrator: "Multi_Agent_Orchestrator",
        *,
        gate: Human_Approval_Gate | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        # When a Human_Approval_Gate is injected, the service consults it at the two
        # named Approval_Checkpoints and emits ``approval_required`` on a pause (Req 7.5).
        # When absent, the run proceeds without pausing (auto-approve equivalent).
        self._gate = gate

    def run_stream(
        self,
        task: str,
        conversation_id: str | None = None,
        *,
        run_id: str | None = None,
        org_id=None,
    ) -> Iterator[MultiAgentStreamEvent]:
        """Drive a Multi_Agent_Run and yield events in production order (Req 7.2, 7.4).

        Emits an initial ``agent_started`` for the Planner immediately so the first event
        is produced before any slow work (Req 7.1). Forwards each role contribution as a
        separate event as it is produced (Req 7.2), identifies the acting ``role_id`` on
        every agent-produced event (Req 7.3), and guarantees **exactly one** terminal
        event — ``completion`` carrying the ``Final_Output`` on success (Req 7.6) xor a
        single ``error`` on failure (Req 7.7, 7.8) — then closes.

        A single ``try``/``except`` wraps the whole generator body so any exception raised
        anywhere in the run is translated into that one ``error`` event without also
        emitting a ``completion``.

        ``org_id`` publishes the acting tenant for the streamed run (set at the top of the
        generator body so it is in force while roles delegate to the reused
        ``Agent_Orchestrator`` and trace entries are written) (Req 4.2, 4.6).
        """
        if org_id is not None:
            set_current_org(org_id)
        sequence = 0

        # ------------------------------------------------------------------ helper
        def _emit(event_type: MultiAgentStreamEventType, data: dict) -> MultiAgentStreamEvent:
            """Build a sequenced event; the caller yields it (keeps flow linear)."""
            nonlocal sequence
            event = MultiAgentStreamEvent(type=event_type, data=dict(data), sequence=sequence)
            sequence += 1
            return event

        orch = self._orchestrator
        planner_id = orch.planner_id
        middle_ids = orch.middle_ids
        reviser_id = orch.reviser_id
        reviewer_id = orch.reviewer_id

        # First event: AGENT_STARTED for the Planner, emitted *before* the graph runs so
        # the first streamed event appears immediately (Req 7.1).
        yield _emit(
            MultiAgentStreamEventType.AGENT_STARTED, {"role_id": planner_id}
        )

        try:
            state: Blackboard_State = orch.initialize_state(
                task, conversation_id, run_id=run_id
            )

            # ---- Planner ----------------------------------------------------
            state = orch.act_role(planner_id, state)
            yield _emit(
                MultiAgentStreamEventType.PLAN,
                {
                    "role_id": planner_id,
                    "steps": list(state.plan.steps) if state.plan else [],
                },
            )

            # Approval checkpoint after the Plan (Req 5.1, 7.5).
            paused_event = self._maybe_pause(state, CHECKPOINT_AFTER_PLAN, _emit)
            if paused_event is not None:
                yield paused_event
                return  # non-terminal end-of-stream on pause

            # ---- Middle phases (Researcher, ...) — executed once per full round -----
            for role_id in middle_ids:
                yield _emit(
                    MultiAgentStreamEventType.AGENT_STARTED, {"role_id": role_id}
                )
                state = orch.act_role(role_id, state)
                yield _emit(*_typed_event_for(role_id, state))

            # ---- Reviser / Reviewer loop (Writer -> Critic, revise or finalize) -----
            while True:
                yield _emit(
                    MultiAgentStreamEventType.AGENT_STARTED, {"role_id": reviser_id}
                )
                state = orch.act_role(reviser_id, state)
                yield _emit(*_typed_event_for(reviser_id, state))

                yield _emit(
                    MultiAgentStreamEventType.AGENT_STARTED, {"role_id": reviewer_id}
                )
                state = orch.act_role(reviewer_id, state)
                yield _emit(*_typed_event_for(reviewer_id, state))

                # Structural bounded routing: same source of truth the graph uses.
                route = orch.route_after_review(state)
                if route == ROUTE_APPROVE:
                    # Approval checkpoint before finalize (Req 5.1, 7.5).
                    paused_event = self._maybe_pause(
                        state, CHECKPOINT_BEFORE_FINALIZE, _emit
                    )
                    if paused_event is not None:
                        yield paused_event
                        return
                    state.termination_reason = Termination_Reason.COMPLETED
                    state.final_output = orch.final_output_for(state)
                    yield _emit(
                        MultiAgentStreamEventType.COMPLETION,
                        _completion_data(state),
                    )
                    return
                if route == ROUTE_ROUNDS:
                    state.termination_reason = Termination_Reason.MAX_ROUNDS_REACHED
                    state.final_output = orch.final_output_for(state)
                    yield _emit(
                        MultiAgentStreamEventType.COMPLETION,
                        _completion_data(state),
                    )
                    return
                if route == ROUTE_REVS:
                    state.termination_reason = Termination_Reason.MAX_REVISIONS_REACHED
                    state.final_output = orch.final_output_for(state)
                    yield _emit(
                        MultiAgentStreamEventType.COMPLETION,
                        _completion_data(state),
                    )
                    return
                # ROUTE_REVISE: loop back to the reviser (revision_count increment is
                # applied by ``act_role`` on the next entry — same accounting the graph
                # uses, so the bound stays honored).
                assert route == ROUTE_REVISE
                continue

        except Exception as exc:  # noqa: BLE001 - any failure becomes one error event
            # Exactly one terminal error event; no completion is emitted for this stream
            # (Req 7.7, 7.8). ``sequence`` continues monotonically from the last event.
            yield _emit(
                MultiAgentStreamEventType.ERROR,
                {"message": str(exc), "error_type": type(exc).__name__},
            )
            return

    def iter_sse_frames(
        self,
        task: str,
        conversation_id: str | None = None,
        *,
        run_id: str | None = None,
        org_id=None,
    ) -> Iterator[str]:
        """Render :meth:`run_stream` events as SSE frames for a StreamingResponse.

        Starlette advances synchronous response iterators in an AnyIO worker context.
        Context-variable writes made while producing one frame do not flow back through
        the event loop into the worker context used for the next frame. Re-publish the
        explicit tenant before every nested-generator advance so delegated roles and
        trace writes remain scoped after each yield boundary.
        """
        events = self.run_stream(task, conversation_id, run_id=run_id, org_id=org_id)
        while True:
            if org_id is not None:
                set_current_org(org_id)
            try:
                event = next(events)
            except StopIteration:
                return
            yield multiagent_format_sse_frame(event)

    # ------------------------------------------------------------------ internal
    def _maybe_pause(
        self,
        state: Blackboard_State,
        checkpoint: str,
        emit,
    ) -> MultiAgentStreamEvent | None:
        """Consult the approval gate (if any); return an APPROVAL_REQUIRED event on pause.

        Returns ``None`` when the run should continue (auto-approve or no gate wired) and
        the built :class:`MultiAgentStreamEvent` on pause, so the caller can yield it and
        stop the stream (Req 7.5).
        """
        if self._gate is None:
            return None
        # Applying the gate mutates the passed state (sets awaiting flags and persists).
        self._gate.at_checkpoint(state, checkpoint)
        if not state.awaiting_approval:
            return None
        return emit(
            MultiAgentStreamEventType.APPROVAL_REQUIRED,
            {
                "run_id": state.run_id,
                "checkpoint": state.pending_checkpoint or checkpoint,
            },
        )


# --- typed-event mapping helpers --------------------------------------------------


def _typed_event_for(
    role_id: str, state: Blackboard_State
) -> tuple[MultiAgentStreamEventType, dict]:
    """Return the (event_type, data) for the just-completed role's contribution.

    The role identifier drives the mapping (rather than the role's Python class) so the
    streaming service depends only on the declarative pipeline names, not on any concrete
    role type. Data fields are pure functions of ``state`` so identical inputs produce
    identical event payloads (Req 7.9).
    """
    if role_id == "planner":
        return (
            MultiAgentStreamEventType.PLAN,
            {
                "role_id": role_id,
                "steps": list(state.plan.steps) if state.plan else [],
            },
        )
    if role_id == "researcher":
        findings = _serialize_findings(state)
        return (
            MultiAgentStreamEventType.RESEARCH,
            {"role_id": role_id, "findings": findings},
        )
    if role_id == "writer":
        draft = state.draft
        return (
            MultiAgentStreamEventType.DRAFT,
            {
                "role_id": role_id,
                "content": draft.content if draft else "",
                "citations": _serialize_citations(draft.citations if draft else []),
            },
        )
    if role_id == "critic":
        feedback = state.critic_feedback
        return (
            MultiAgentStreamEventType.CRITIC_FEEDBACK,
            {
                "role_id": role_id,
                "revision_required": bool(feedback.revision_required) if feedback else False,
                "comments": feedback.comments if feedback else "",
            },
        )
    # Any other role name is emitted as an AGENT_STARTED echo carrying its role id;
    # keeps the stream well-formed if the pipeline is extended with a custom phase.
    return (
        MultiAgentStreamEventType.AGENT_STARTED,
        {"role_id": role_id},
    )


def _serialize_findings(state: Blackboard_State) -> list[dict]:
    """Render Research_Findings for the ``research`` event payload."""
    findings = state.research_findings
    if findings is None:
        return []
    return [
        {
            "content": finding.content,
            "citations": _serialize_citations(finding.citations),
        }
        for finding in findings.findings
    ]


def _serialize_citations(citations) -> list[dict]:
    """Render Citations as plain dicts (pure function of input) for stable payloads."""
    return [asdict(c) for c in citations]


def _completion_data(state: Blackboard_State) -> dict:
    """Build the payload for the terminal ``completion`` event (Req 7.6)."""
    final = state.final_output
    return {
        "run_id": state.run_id,
        "termination_reason": (
            state.termination_reason.value if state.termination_reason else None
        ),
        "answer": final.content if final else "",
        "citations": _serialize_citations(final.citations if final else []),
    }
