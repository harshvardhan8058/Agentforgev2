"""Agent_Orchestrator — builds and runs the bounded LangGraph state graph.

The orchestrator constructs a LangGraph ``StateGraph`` over :class:`AgentState` (via
:func:`agentforge.agent.graph.build_agent_graph`) and runs the bounded
reason -> act -> observe loop for a single Agent_Run. It depends only on the abstract
seams — the ``LLM_Provider`` (reused for reasoning/tool selection, Req 12.1), the
``Tool_Registry``, and the optional ``Memory_Manager`` and ``Trace_Recorder`` — so it is
fully testable keyless with in-memory doubles and never constructs its own providers.

The configured Iteration_Limit is normalized with
:func:`agentforge.agent.state.resolve_iteration_limit` (Req 1.5, 1.6); the resolved limit
is the structural upper bound on completed cycles, and LangGraph's ``recursion_limit`` is
set as a defensive backstop derived from it. Every run terminates with exactly one
``termination_reason`` (Req 1.7).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import fields

from agentforge.agent.graph import (
    NODE_ACT,
    NODE_OBSERVE,
    NODE_REASON,
    Agent_Graph_Nodes,
    build_agent_graph,
)
from agentforge.agent.selection import (
    Deterministic_Fallback_Strategy,
    LLM_Selection_Strategy,
    Selection_Strategy,
)
from agentforge.agent.state import (
    AgentState,
    TerminationReason,
    resolve_iteration_limit,
)
from agentforge.conversation.base import Message
from agentforge.llm.base import LLM_Provider
from agentforge.streaming.base import StreamEvent, StreamEventType
from agentforge.tools.registry import Tool_Registry
from agentforge.tracing.base import Trace_Recorder

# The name reported by the keyless Fallback_Provider; when active, deterministic
# fallback tool selection is used so a run is fully reproducible (Req 3.5, 1.8).
_FALLBACK_PROVIDER_NAME = "fallback"

# Nodes executed per completed cycle (reason + act + observe); used to derive the
# defensive LangGraph recursion backstop from the iteration limit.
_NODES_PER_CYCLE = 3
_RECURSION_BUFFER = 10

# Field names of AgentState, used to reconstruct the dataclass from the graph's output.
_STATE_FIELDS = frozenset(f.name for f in fields(AgentState))


class Agent_Orchestrator:
    """Runs the bounded agent loop as a LangGraph state graph (Req 1.1)."""

    def __init__(
        self,
        llm: LLM_Provider,
        registry: Tool_Registry,
        *,
        memory=None,
        trace: Trace_Recorder | None = None,
        iteration_limit: object | None = None,
        selection_strategy: Selection_Strategy | None = None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        # Memory and trace are optional/injected so the orchestrator is testable without
        # them (Req 12.1); memory is not consumed until short-term memory lands.
        self._memory = memory
        self._trace = trace

        # Resolve the configured Iteration_Limit once; the invalid flag is surfaced on
        # every run's state (Req 1.5, 1.6).
        self._iteration_limit, self._invalid_limit_flagged = resolve_iteration_limit(
            iteration_limit
        )

        # Choose the selection strategy: the deterministic fallback under the keyless
        # Fallback_Provider, otherwise the LLM-driven strategy (Req 3.5).
        self._selection = selection_strategy or self._default_strategy(llm)

        nodes = Agent_Graph_Nodes(registry, self._selection, trace)
        self._graph = build_agent_graph(nodes)

    @staticmethod
    def _default_strategy(llm: LLM_Provider) -> Selection_Strategy:
        """Pick the selection strategy based on the active provider (Req 3.5)."""
        if getattr(llm, "name", None) == _FALLBACK_PROVIDER_NAME:
            return Deterministic_Fallback_Strategy()
        return LLM_Selection_Strategy(llm)

    @property
    def iteration_limit(self) -> int:
        """The resolved Iteration_Limit applied to every run (Req 1.5)."""
        return self._iteration_limit

    def run(
        self,
        user_request: str,
        conversation_context: list[Message] | None = None,
        *,
        conversation_id: str | None = None,
    ) -> AgentState:
        """Execute a single bounded Agent_Run and return the final state (Req 1.1, 1.7).

        Builds the initial :class:`AgentState`, runs the compiled graph with a defensive
        ``recursion_limit`` backstop, and reconstructs the final state — including
        ``final_answer``, ``termination_reason``, ``observations``, and
        ``iteration_count``.
        """
        initial = AgentState(
            run_id=str(uuid.uuid4()),
            conversation_id=conversation_id or str(uuid.uuid4()),
            user_request=user_request,
            conversation_context=list(conversation_context or []),
            iteration_limit=self._iteration_limit,
            invalid_limit_flagged=self._invalid_limit_flagged,
        )

        recursion_limit = _NODES_PER_CYCLE * self._iteration_limit + _RECURSION_BUFFER
        raw = self._graph.invoke(initial, {"recursion_limit": recursion_limit})
        final = self._to_state(raw)

        # Defensive invariant guard: a run must always end with exactly one reason.
        if final.termination_reason is None:
            final.termination_reason = TerminationReason.FINAL_ANSWER
            if final.final_answer is None:
                final.final_answer = final.user_request
        return final

    def stream_run(
        self,
        user_request: str,
        conversation_context: list[Message] | None = None,
        *,
        conversation_id: str | None = None,
    ) -> Iterator[StreamEvent]:
        """Drive a bounded Agent_Run, yielding intermediate events in production order.

        This is a generator: it yields the intermediate :class:`StreamEvent`s produced as
        the graph executes — an initial ``step`` immediately, then one event per node
        (``step`` for reason/observe, ``tool_call`` for act) — and **returns** the final
        :class:`AgentState` (available via ``StopIteration.value``). It does **not** emit a
        terminal ``completion``/``error`` event; the ``Streaming_Service`` owns the
        exactly-one-terminal-event guarantee (Req 9.2, 9.4, 9.5).

        The events carry no ``sequence`` here; the ``Streaming_Service`` assigns the
        monotonic sequence as it forwards them, so ordering is preserved end-to-end.
        """
        initial = AgentState(
            run_id=str(uuid.uuid4()),
            conversation_id=conversation_id or str(uuid.uuid4()),
            user_request=user_request,
            conversation_context=list(conversation_context or []),
            iteration_limit=self._iteration_limit,
            invalid_limit_flagged=self._invalid_limit_flagged,
        )
        recursion_limit = _NODES_PER_CYCLE * self._iteration_limit + _RECURSION_BUFFER

        # Emit an initial step immediately so the first event is produced before any slow
        # work begins (Req 9.1).
        yield StreamEvent(
            type=StreamEventType.STEP,
            data={"step_type": "start", "run_id": initial.run_id},
        )

        base = {f.name: getattr(initial, f.name) for f in fields(AgentState)}
        overrides: dict = {}
        pending_call = None
        for chunk in self._graph.stream(
            initial, {"recursion_limit": recursion_limit}, stream_mode="updates"
        ):
            for node_name, update in chunk.items():
                if update:
                    overrides.update(
                        {k: v for k, v in update.items() if k in _STATE_FIELDS}
                    )
                event, pending_call = self._event_for_node(
                    node_name, update, pending_call
                )
                if event is not None:
                    yield event

        final = AgentState(**{**base, **overrides})
        if final.termination_reason is None:
            final.termination_reason = TerminationReason.FINAL_ANSWER
            if final.final_answer is None:
                final.final_answer = final.user_request
        return final

    @staticmethod
    def _event_for_node(
        node_name: str, update: dict | None, pending_call
    ) -> tuple[StreamEvent | None, object]:
        """Map a single graph node update to a StreamEvent (Req 9.4, 9.5)."""
        if node_name == NODE_REASON:
            call = (update or {}).get("pending_tool_call")
            if call is not None:
                return (
                    StreamEvent(
                        type=StreamEventType.STEP,
                        data={"step_type": "reason", "decision": "tool"},
                    ),
                    call,
                )
            return (
                StreamEvent(
                    type=StreamEventType.STEP,
                    data={"step_type": "reason", "decision": "final"},
                ),
                pending_call,
            )
        if node_name == NODE_ACT:
            observation = (update or {}).get("pending_observation")
            data = {
                "tool": pending_call.tool_name if pending_call else None,
                "arguments": dict(pending_call.arguments) if pending_call else {},
                "outcome": observation.kind if observation is not None else None,
            }
            return StreamEvent(type=StreamEventType.TOOL_CALL, data=data), None
        if node_name == NODE_OBSERVE:
            return (
                StreamEvent(
                    type=StreamEventType.STEP,
                    data={
                        "step_type": "observe",
                        "iteration_count": (update or {}).get("iteration_count"),
                    },
                ),
                pending_call,
            )
        # finalize / finalize_limit produce no intermediate event (the terminal event is
        # emitted by the Streaming_Service).
        return None, pending_call

    @staticmethod
    def _to_state(raw: object) -> AgentState:
        """Reconstruct an :class:`AgentState` from the graph's output mapping."""
        if isinstance(raw, AgentState):
            return raw
        data = {k: v for k, v in dict(raw).items() if k in _STATE_FIELDS}
        return AgentState(**data)


def extract_citations(state: AgentState) -> list[dict]:
    """Return the citations from the most recent RAG tool-result observation.

    Surfaces the citations produced by the ``RAG_Tool`` for the run result and the
    streaming ``completion`` event; returns an empty list when the run produced no
    grounded tool result.
    """
    for obs in reversed(state.observations):
        citations = obs.data.get("citations") if obs.data else None
        if citations:
            return list(citations)
    return []
