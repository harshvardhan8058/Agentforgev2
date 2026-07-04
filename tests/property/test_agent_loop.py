"""Property-based tests for the bounded agent loop (Properties 1, 2, 3).

These run fully keyless: the orchestrator is driven by the deterministic
``Fallback_Provider`` and simple, injected selection strategies plus a fake tool, so the
loop's bound, counter monotonicity, and termination guarantees are exercised in isolation
— no network, no credentials.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.agent.selection import Decision, Selection_Strategy
from agentforge.agent.state import TerminationReason
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.tools.base import Tool_Call, Tool_Interface, Tool_Result
from agentforge.tools.registry import Tool_Registry
from agentforge.tracing.recorder import InMemory_Trace_Recorder

from agentforge.enterprise.tenancy import NIL_ORG_ID as ORG

_TOOL_NAME = "loop_tool"


class _EchoTool(Tool_Interface):
    """A permissive fake tool that always succeeds with a fixed result."""

    @property
    def name(self) -> str:
        return _TOOL_NAME

    @property
    def description(self) -> str:
        return "echo"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    def invoke(self, arguments: dict) -> Tool_Result:
        return Tool_Result(tool_name=self.name, ok=True, content="tool-result")


class _AlwaysToolStrategy(Selection_Strategy):
    """A strategy that never finalizes — it always requests the fake tool."""

    def select(self, state, specs) -> Decision:
        return Decision.tool(Tool_Call(tool_name=_TOOL_NAME, arguments={}))


class _NToolsThenFinalStrategy(Selection_Strategy):
    """Requests the tool for the first ``tool_steps`` cycles, then finalizes."""

    def __init__(self, tool_steps: int) -> None:
        self._tool_steps = tool_steps

    def select(self, state, specs) -> Decision:
        if state.iteration_count < self._tool_steps:
            return Decision.tool(Tool_Call(tool_name=_TOOL_NAME, arguments={}))
        return Decision.final("done")


def _registry() -> Tool_Registry:
    registry = Tool_Registry()
    registry.register(_EchoTool())
    return registry


# Feature: agentforge-agentic-layer, Property 1: Bounded loop never exceeds the
# Iteration_Limit.
@hyp_settings(max_examples=100, deadline=None)
@given(
    user_request=st.text(max_size=40),
    limit=st.integers(min_value=1, max_value=100),
)
def test_bounded_loop_never_exceeds_iteration_limit(user_request, limit):
    """Feature: agentforge-agentic-layer, Property 1: For any user request, any
    Iteration_Limit L in [1, 100], and any selection strategy (including one that always
    requests a tool), the number of completed reason-act-observe cycles at termination is
    at most L, and when the loop reaches L cycles the Agent_Run terminates with
    iteration-limit-reached and returns the most recent available answer.

    Validates: Requirements 1.1, 1.4, 11.1
    """
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(),
        _registry(),
        iteration_limit=limit,
        selection_strategy=_AlwaysToolStrategy(),
    )
    state = orchestrator.run(user_request)

    # The completed-cycle count never exceeds the limit.
    assert state.iteration_count <= limit
    # An always-requesting strategy forces the limit branch exactly at L cycles.
    assert state.iteration_count == limit
    assert state.termination_reason is TerminationReason.ITERATION_LIMIT_REACHED
    # The most recent available answer (the tool result) is returned.
    assert state.final_answer == "tool-result"


# Feature: agentforge-agentic-layer, Property 2: Iteration counter is monotonic and
# increments by exactly one.
@hyp_settings(max_examples=100, deadline=None)
@given(tool_steps=st.integers(min_value=0, max_value=15))
def test_iteration_counter_monotonic_increment_by_one(tool_steps):
    """Feature: agentforge-agentic-layer, Property 2: For any Agent_Run, the
    iteration_count begins at 0, is always a non-negative integer, and increases by
    exactly 1 after each completed reason-act-observe cycle (never skips, never
    decreases).

    Validates: Requirements 1.2
    """
    trace = InMemory_Trace_Recorder()
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(),
        _registry(),
        trace=trace,
        iteration_limit=100,  # large enough that the strategy controls termination
        selection_strategy=_NToolsThenFinalStrategy(tool_steps),
    )
    state = orchestrator.run("x")

    # The counter ends exactly at the number of completed cycles.
    assert state.iteration_count == tool_steps
    assert isinstance(state.iteration_count, int) and state.iteration_count >= 0

    # The post-increment count recorded at each observe step is 1, 2, ..., tool_steps —
    # contiguous, strictly increasing by exactly one, starting from 0 (the initial state).
    observed = [
        entry.detail["iteration_count"]
        for entry in trace.get_trace(ORG, state.run_id).entries
        if entry.step_type == "observe"
    ]
    assert observed == list(range(1, tool_steps + 1))


# Feature: agentforge-agentic-layer, Property 3: Every run terminates with exactly one
# termination reason.
@hyp_settings(max_examples=100, deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=30),
    tool_steps=st.integers(min_value=0, max_value=40),
    always_tool=st.booleans(),
)
def test_every_run_terminates_with_exactly_one_reason(limit, tool_steps, always_tool):
    """Feature: agentforge-agentic-layer, Property 3: For any Agent_Run, the run
    terminates with the termination_reason set to exactly one value from the set
    {final-answer, iteration-limit-reached} — never unset and never both.

    Validates: Requirements 1.3, 1.7
    """
    strategy: Selection_Strategy = (
        _AlwaysToolStrategy() if always_tool else _NToolsThenFinalStrategy(tool_steps)
    )
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(),
        _registry(),
        iteration_limit=limit,
        selection_strategy=strategy,
    )
    state = orchestrator.run("x")

    # Exactly one reason: the field is a single enum value, always set, from the set.
    assert state.termination_reason in {
        TerminationReason.FINAL_ANSWER,
        TerminationReason.ITERATION_LIMIT_REACHED,
    }
    # Consistency: the limit branch is taken only when the loop reached the bound.
    if state.termination_reason is TerminationReason.ITERATION_LIMIT_REACHED:
        assert state.iteration_count == limit
    else:
        assert state.iteration_count <= limit
