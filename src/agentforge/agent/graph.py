"""LangGraph node functions and conditional edge routing for the Agent_Orchestrator.

This module holds the three agent node types — **reason**, **act**, and **observe** —
and the conditional edges that turn them into a bounded reason -> act -> observe loop
(Req 1.1). The bound is enforced **structurally**: the observe node increments
``iteration_count`` by exactly one, and the conditional edge out of observe routes to the
``finalize_limit`` terminal the instant ``iteration_count`` reaches ``iteration_limit``,
so a new cycle can never push the count past the limit (Req 1.4, 11.1).

In-loop failures are **contained as observations** rather than terminating the run
(Req 3.4, 11.2, 11.3): an unregistered tool yields a ``tool_not_found`` observation,
arguments that violate the tool's input schema yield a ``validation_error`` observation
(the tool is **not** invoked, Req 11.2, 11.4), and a tool that raises ``ToolError``
yields a ``tool_execution_error`` observation. Each case continues the loop.

The node functions are plain callables over the typed :class:`AgentState`; they depend
only on the abstract ``Tool_Registry``, ``Selection_Strategy``, and (optionally)
``Trace_Recorder`` seams, so new node types or tools are added without editing the core.
"""

from __future__ import annotations

from agentforge.agent.selection import Selection_Strategy
from agentforge.agent.state import AgentState, Observation, TerminationReason
from agentforge.enterprise.tenancy import current_org
from agentforge.tools.base import ToolError
from agentforge.tools.registry import Tool_Registry
from agentforge.tracing.base import Trace_Recorder

# --- Graph node names -------------------------------------------------------------
NODE_REASON = "reason"
NODE_ACT = "act"
NODE_OBSERVE = "observe"
NODE_FINALIZE = "finalize"
NODE_FINALIZE_LIMIT = "finalize_limit"

# --- Observation kinds (the agent scratchpad vocabulary) --------------------------
OBS_TOOL_RESULT = "tool_result"
OBS_TOOL_NOT_FOUND = "tool_not_found"
OBS_VALIDATION_ERROR = "validation_error"
OBS_TOOL_EXECUTION_ERROR = "tool_execution_error"

# --- Trace step types -------------------------------------------------------------
STEP_REASON = "reason"
STEP_TOOL_CALL = "tool_call"
STEP_OBSERVE = "observe"


def validate_arguments(arguments: object, schema: dict) -> tuple[bool, str]:
    """Validate ``arguments`` against a (JSON-Schema-shaped) ``schema`` (Req 11.2, 11.4).

    Supports the schema features the built-in tools use: an object schema with typed
    ``properties``, a ``required`` list, ``additionalProperties`` control, and per-field
    ``minLength`` (strings) and ``minimum``/``maximum`` (numbers). Booleans are never
    accepted where an ``integer``/``number`` is required, mirroring JSON-Schema intent.

    Returns:
        ``(True, "")`` when the arguments conform, else ``(False, <reason>)``.
    """
    if not isinstance(arguments, dict):
        return False, "arguments must be an object"
    if schema.get("type") == "object" or "properties" in schema:
        properties: dict = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in arguments:
                return False, f"missing required argument {key!r}"
        if schema.get("additionalProperties") is False:
            for key in arguments:
                if key not in properties:
                    return False, f"unexpected argument {key!r}"
        for key, value in arguments.items():
            subschema = properties.get(key)
            if subschema is None:
                continue
            ok, error = _validate_value(value, subschema, key)
            if not ok:
                return False, error
    return True, ""


def _validate_value(value: object, subschema: dict, key: str) -> tuple[bool, str]:
    """Validate a single property ``value`` against its ``subschema``."""
    expected = subschema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            return False, f"{key!r} must be a string"
        if len(value) < subschema.get("minLength", 0):
            return False, f"{key!r} is shorter than the minimum length"
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return False, f"{key!r} must be an integer"
        ok, error = _check_bounds(value, subschema, key)
        if not ok:
            return False, error
    elif expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False, f"{key!r} must be a number"
        ok, error = _check_bounds(value, subschema, key)
        if not ok:
            return False, error
    elif expected == "boolean":
        if not isinstance(value, bool):
            return False, f"{key!r} must be a boolean"
    elif expected == "array":
        if not isinstance(value, list):
            return False, f"{key!r} must be an array"
    elif expected == "object":
        if not isinstance(value, dict):
            return False, f"{key!r} must be an object"
    return True, ""


def _check_bounds(value: float, subschema: dict, key: str) -> tuple[bool, str]:
    """Enforce ``minimum``/``maximum`` bounds for numeric values."""
    minimum = subschema.get("minimum")
    maximum = subschema.get("maximum")
    if minimum is not None and value < minimum:
        return False, f"{key!r} is below the minimum"
    if maximum is not None and value > maximum:
        return False, f"{key!r} is above the maximum"
    return True, ""


def most_recent_answer(state: AgentState) -> str:
    """Return the most recent available answer for a run (Req 1.4).

    Prefers an already-produced ``final_answer``; otherwise falls back to the most recent
    non-empty observation content, and finally to the user request so a run always
    terminates with a concrete answer even on the iteration-limit branch.
    """
    if state.final_answer:
        return state.final_answer
    for obs in reversed(state.observations):
        if obs.content:
            return obs.content
    return state.user_request


class Agent_Graph_Nodes:
    """The reason / act / observe node implementations bound to their seams.

    Depends only on the abstract ``Tool_Registry``, ``Selection_Strategy``, and optional
    ``Trace_Recorder`` — never on a concrete tool or provider (Req 12.1).
    """

    def __init__(
        self,
        registry: Tool_Registry,
        selection_strategy: Selection_Strategy,
        trace: Trace_Recorder | None = None,
    ) -> None:
        self._registry = registry
        self._selection = selection_strategy
        self._trace = trace

    # --- nodes --------------------------------------------------------------------
    def reason(self, state: AgentState) -> dict:
        """Reasoning step: choose a final answer or a Tool_Call (Req 1.3, 3.1).

        Presents the available tool specs and the current state to the
        ``Selection_Strategy`` (which drives the ``LLM_Provider``), then records the step.
        A final decision sets ``final_answer`` + ``termination_reason``; a tool decision
        stages a ``pending_tool_call`` for the act node.
        """
        specs = self._registry.list_specs()
        decision = self._selection.select(state, specs)
        self._record(state, STEP_REASON)
        if decision.is_final:
            return {
                "final_answer": decision.answer,
                "termination_reason": TerminationReason.FINAL_ANSWER,
                "pending_tool_call": None,
            }
        return {"pending_tool_call": decision.tool_call}

    def act(self, state: AgentState) -> dict:
        """Act step: validate the Tool_Call and invoke the tool if valid (Req 3.2, 11.2).

        Produces a ``pending_observation`` capturing the outcome (tool result or a
        contained error) and records the tool-call step with its tool name and outcome
        (Req 10.2). The observation is committed to the scratchpad by the observe node.
        """
        call = state.pending_tool_call
        observation = self._dispatch(state)
        self._record(
            state,
            STEP_TOOL_CALL,
            tool_name=call.tool_name if call else None,
            outcome=observation.kind,
        )
        return {"pending_observation": observation}

    def observe(self, state: AgentState) -> dict:
        """Observe step: record the observation and increment the counter (Req 1.2, 3.3).

        Appends the staged observation to ``observations`` and increments
        ``iteration_count`` by **exactly one**, completing one reason -> act -> observe
        cycle. The post-increment count is recorded in the trace detail so the monotonic
        progression is observable.
        """
        observations = list(state.observations)
        if state.pending_observation is not None:
            observations.append(state.pending_observation)
        count = state.iteration_count + 1
        self._record(state, STEP_OBSERVE, detail={"iteration_count": count})
        return {
            "observations": observations,
            "iteration_count": count,
            "pending_observation": None,
            "pending_tool_call": None,
        }

    # --- dispatch helper ----------------------------------------------------------
    def _dispatch(self, state: AgentState) -> Observation:
        """Resolve, validate, and invoke the pending Tool_Call, containing failures."""
        call = state.pending_tool_call
        if call is None:  # defensive: reason routed here without staging a call.
            return Observation(
                kind=OBS_VALIDATION_ERROR,
                tool_name=None,
                content="no tool call was staged",
            )
        tool = self._registry.resolve(call.tool_name)
        if tool is None:
            # Unregistered tool: contained, loop continues (Req 3.4).
            return Observation(
                kind=OBS_TOOL_NOT_FOUND,
                tool_name=call.tool_name,
                content=f"tool {call.tool_name!r} is not registered",
            )
        ok, error = validate_arguments(call.arguments, tool.input_schema)
        if not ok:
            # Invalid arguments: the tool is NOT invoked (Req 11.2, 11.4).
            return Observation(
                kind=OBS_VALIDATION_ERROR,
                tool_name=call.tool_name,
                content=error,
            )
        try:
            result = tool.invoke(call.arguments)
        except ToolError as exc:
            # Tool execution error: contained, loop continues (Req 11.3).
            return Observation(
                kind=OBS_TOOL_EXECUTION_ERROR,
                tool_name=call.tool_name,
                content=str(exc),
            )
        return Observation(
            kind=OBS_TOOL_RESULT,
            tool_name=call.tool_name,
            content=result.content,
            # Carry the tool's structured payload (e.g. RAG citations) so the final
            # answer can surface it without re-invoking the tool.
            data=dict(result.data),
        )

    def _record(
        self,
        state: AgentState,
        step_type: str,
        *,
        tool_name: str | None = None,
        outcome: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Record an Agent_Step in the Trace when a recorder is configured (Req 10.1).

        The trace entry is scoped to the tenant in force for the run (Req 4.6); its parent
        Agent_Run inherits that ``org_id`` when the recorder auto-creates the run row.
        """
        if self._trace is not None:
            self._trace.record(
                current_org(),
                state.run_id,
                step_type,
                tool_name=tool_name,
                outcome=outcome,
                detail=detail,
            )


# --- conditional edge routing -----------------------------------------------------
def route_after_reason(state: AgentState) -> str:
    """Route reason -> finalize on a final answer, else reason -> act (Req 1.3, 3.2)."""
    if state.termination_reason is not None:
        return NODE_FINALIZE
    return NODE_ACT


def route_after_observe(state: AgentState) -> str:
    """Route observe -> finalize_limit at the bound, else observe -> reason (Req 1.4).

    The comparison uses ``>=`` defensively; because the counter increments by exactly one
    and is checked immediately, it equals the limit here and never exceeds it (Req 11.1).
    """
    if state.iteration_count >= state.iteration_limit:
        return NODE_FINALIZE_LIMIT
    return NODE_REASON


def finalize(state: AgentState) -> dict:
    """Terminal node for the final-answer branch (Req 1.3, 1.7).

    ``reason`` has already set ``final_answer`` and ``termination_reason``; this guards
    the invariants defensively so the run always ends with a concrete answer and exactly
    one termination reason.
    """
    updates: dict = {}
    if state.termination_reason is None:
        updates["termination_reason"] = TerminationReason.FINAL_ANSWER
    if state.final_answer is None:
        updates["final_answer"] = most_recent_answer(state)
    return updates


def finalize_limit(state: AgentState) -> dict:
    """Terminal node for the iteration-limit branch (Req 1.4, 1.7).

    Sets ``termination_reason`` to ``iteration-limit-reached`` and returns the most recent
    available answer.
    """
    return {
        "termination_reason": TerminationReason.ITERATION_LIMIT_REACHED,
        "final_answer": most_recent_answer(state),
    }


def build_agent_graph(nodes: Agent_Graph_Nodes):
    """Assemble and compile the LangGraph ``StateGraph`` over :class:`AgentState`.

    The graph wires ``START -> reason``, the conditional ``reason -> {act, finalize}``,
    ``act -> observe``, the conditional ``observe -> {reason, finalize_limit}``, and both
    terminal nodes to ``END``. The compiled graph is returned for the orchestrator to run.
    """
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(AgentState)
    graph.add_node(NODE_REASON, nodes.reason)
    graph.add_node(NODE_ACT, nodes.act)
    graph.add_node(NODE_OBSERVE, nodes.observe)
    graph.add_node(NODE_FINALIZE, finalize)
    graph.add_node(NODE_FINALIZE_LIMIT, finalize_limit)

    graph.add_edge(START, NODE_REASON)
    graph.add_conditional_edges(
        NODE_REASON,
        route_after_reason,
        {NODE_ACT: NODE_ACT, NODE_FINALIZE: NODE_FINALIZE},
    )
    graph.add_edge(NODE_ACT, NODE_OBSERVE)
    graph.add_conditional_edges(
        NODE_OBSERVE,
        route_after_observe,
        {NODE_REASON: NODE_REASON, NODE_FINALIZE_LIMIT: NODE_FINALIZE_LIMIT},
    )
    graph.add_edge(NODE_FINALIZE, END)
    graph.add_edge(NODE_FINALIZE_LIMIT, END)
    return graph.compile()
