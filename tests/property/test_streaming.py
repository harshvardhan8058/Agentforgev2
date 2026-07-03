"""Property-based test for streaming well-formedness (Property 17).

Runs fully keyless: the orchestrator is driven by the deterministic ``Fallback_Provider``
with injected selection strategies (including one that raises, to exercise the failure
path), so the streaming guarantees are verified in isolation — no network, no credentials.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.agent.selection import Decision, Selection_Strategy
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.streaming.base import (
    TERMINAL_EVENT_TYPES,
    AgentRunInput,
    StreamEvent,
    StreamEventType,
)
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.tools.base import Tool_Call, Tool_Interface, Tool_Result
from agentforge.tools.registry import Tool_Registry

_TOOL_NAME = "stream_tool"
_ALL_TYPES = set(StreamEventType)


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


class _RaisingStrategy(Selection_Strategy):
    """A strategy that raises mid-run to exercise the error terminal path (Req 9.8)."""

    def __init__(self, raise_after: int) -> None:
        self._raise_after = raise_after

    def select(self, state, specs) -> Decision:
        if state.iteration_count >= self._raise_after:
            raise RuntimeError("boom during reasoning")
        return Decision.tool(Tool_Call(tool_name=_TOOL_NAME, arguments={}))


def _registry() -> Tool_Registry:
    registry = Tool_Registry()
    registry.register(_EchoTool())
    return registry


def _service(strategy: Selection_Strategy) -> SSE_Streaming_Service:
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(),
        _registry(),
        iteration_limit=50,
        selection_strategy=strategy,
    )
    return SSE_Streaming_Service(orchestrator)


# Feature: agentforge-agentic-layer, Property 17: Streaming emits exactly one terminal
# event and preserves order.
@hyp_settings(max_examples=100, deadline=None)
@given(
    tool_steps=st.integers(min_value=0, max_value=8),
    should_fail=st.booleans(),
    raise_after=st.integers(min_value=0, max_value=4),
)
def test_streaming_single_terminal_event_and_order(tool_steps, should_fail, raise_after):
    """Feature: agentforge-agentic-layer, Property 17: For any Agent_Run (successful or
    failing), the streamed events each carry exactly one type from {step, tool_call,
    delta, completion, error}, are delivered in strictly increasing production order, and
    the stream ends with exactly one terminal event — completion on success or error on
    failure, never both — after which the stream closes.

    Validates: Requirements 9.3, 9.4, 9.5, 9.6, 9.8, 9.9
    """
    strategy: Selection_Strategy = (
        _RaisingStrategy(raise_after) if should_fail else _NToolsThenFinalStrategy(tool_steps)
    )
    events = list(_service(strategy).run_stream(AgentRunInput(message="hi")))

    # Non-empty and every event carries exactly one valid type (Req 9.3).
    assert events
    for event in events:
        assert isinstance(event, StreamEvent)
        assert event.type in _ALL_TYPES

    # Strictly increasing production order via the monotonic sequence (Req 9.4).
    sequences = [event.sequence for event in events]
    assert sequences == sorted(sequences)
    assert all(b - a == 1 for a, b in zip(sequences, sequences[1:]))
    assert sequences[0] == 0

    # Exactly one terminal event, and it is the last event; the stream closes after it
    # (Req 9.6, 9.9).
    terminals = [i for i, e in enumerate(events) if e.type in TERMINAL_EVENT_TYPES]
    assert len(terminals) == 1
    assert terminals[0] == len(events) - 1

    # Terminal is completion xor error, never both (Req 9.6, 9.8).
    terminal = events[-1]
    has_completion = any(e.type is StreamEventType.COMPLETION for e in events)
    has_error = any(e.type is StreamEventType.ERROR for e in events)
    assert has_completion != has_error
    if should_fail:
        assert terminal.type is StreamEventType.ERROR
        assert not has_completion
    else:
        assert terminal.type is StreamEventType.COMPLETION
