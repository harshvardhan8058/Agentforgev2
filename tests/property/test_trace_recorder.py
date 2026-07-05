"""Property-based test for trace completeness and ordering (Property 18).

Runs keyless: the ``InMemory_Trace_Recorder`` is driven by a real ``Agent_Orchestrator``
run under the ``Fallback_Provider`` with injected selection strategies and a fake tool, so
the recorded trace reflects genuine execution — no network, no credentials.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.agent.selection import Decision, Selection_Strategy
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.tools.base import Tool_Call, Tool_Interface, Tool_Result
from agentforge.tools.registry import Tool_Registry
from agentforge.enterprise.tenancy import NIL_ORG_ID as ORG
from agentforge.tracing.recorder import InMemory_Trace_Recorder

_TOOL_NAME = "trace_tool"
_STEP_TOOL_CALL = "tool_call"


class _EchoTool(Tool_Interface):
    """A permissive fake tool that always succeeds."""

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


class _NToolsThenFinalStrategy(Selection_Strategy):
    """Requests the tool for the first ``tool_steps`` cycles, then finalizes."""

    def __init__(self, tool_steps: int) -> None:
        self._tool_steps = tool_steps

    def select(self, state, specs) -> Decision:
        if state.iteration_count < self._tool_steps:
            return Decision.tool(Tool_Call(tool_name=_TOOL_NAME, arguments={}))
        return Decision.final("done")


# Feature: agentforge-agentic-layer, Property 18: Trace is complete and ordered by
# ordinal.
@hyp_settings(max_examples=100, deadline=None)
@given(tool_steps=st.integers(min_value=0, max_value=12))
def test_trace_is_complete_and_ordered_by_ordinal(tool_steps):
    """Feature: agentforge-agentic-layer, Property 18: For any Agent_Run, the recorded
    Trace contains one entry per executed Agent_Step with contiguous ascending ordinals
    matching execution order, each tool-call entry carries its tool name and invocation
    outcome, and get_trace returns the entries ordered by ordinal.

    Validates: Requirements 10.1, 10.2, 10.3
    """
    registry = Tool_Registry()
    registry.register(_EchoTool())
    trace = InMemory_Trace_Recorder()
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(),
        registry,
        trace=trace,
        iteration_limit=100,  # large enough that the strategy controls termination
        selection_strategy=_NToolsThenFinalStrategy(tool_steps),
    )

    state = orchestrator.run("trace me")
    entries = trace.get_trace(ORG, state.run_id).entries

    # get_trace returns entries ordered by ordinal, contiguous from 0 (Req 10.3).
    assert [e.ordinal for e in entries] == list(range(len(entries)))

    # Completeness: each tool cycle records reason + tool_call + observe (3 steps), plus
    # a single final reasoning step -> 3 * tool_steps + 1 entries.
    assert len(entries) == 3 * tool_steps + 1

    # Each tool-call entry carries its tool name and invocation outcome (Req 10.2).
    tool_calls = [e for e in entries if e.step_type == _STEP_TOOL_CALL]
    assert len(tool_calls) == tool_steps
    for entry in tool_calls:
        assert entry.tool_name == _TOOL_NAME
        assert entry.outcome == "tool_result"
