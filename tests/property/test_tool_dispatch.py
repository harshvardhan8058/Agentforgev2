"""Property-based tests for in-loop tool dispatch and containment (Properties 7-10).

These run fully keyless: the orchestrator is driven by the ``Fallback_Provider`` and
injected selection strategies plus instrumented fake tools, so successful dispatch,
unregistered-tool containment, schema-gated invocation, and execution-error containment
are exercised without a network or credentials.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.graph import (
    OBS_TOOL_EXECUTION_ERROR,
    OBS_TOOL_NOT_FOUND,
    OBS_TOOL_RESULT,
    OBS_VALIDATION_ERROR,
)
from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.agent.selection import Decision, Selection_Strategy
from agentforge.agent.state import TerminationReason
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.tools.base import Tool_Call, Tool_Interface, Tool_Result, ToolError
from agentforge.tools.registry import Tool_Registry

_MISSING = object()


class _CallOnceThenFinalStrategy(Selection_Strategy):
    """Requests a single (configurable) Tool_Call on the first step, then finalizes."""

    def __init__(self, tool_call: Tool_Call) -> None:
        self._tool_call = tool_call

    def select(self, state, specs) -> Decision:
        if state.iteration_count == 0 and not state.observations:
            return Decision.tool(self._tool_call)
        return Decision.final("done")


class _RecordingTool(Tool_Interface):
    """A tool that records how many times it is invoked and returns a fixed result."""

    def __init__(self, name: str = "dispatch_tool", schema: dict | None = None) -> None:
        self._name = name
        self._schema = schema or {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
        self.invoke_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "dispatch"

    @property
    def input_schema(self) -> dict:
        return self._schema

    def invoke(self, arguments: dict) -> Tool_Result:
        self.invoke_count += 1
        return Tool_Result(tool_name=self._name, ok=True, content="ok")


class _RaisingTool(_RecordingTool):
    """A tool whose invoke always raises ToolError (execution failure)."""

    def invoke(self, arguments: dict) -> Tool_Result:
        self.invoke_count += 1
        raise ToolError("boom")


def _orchestrator(registry: Tool_Registry, tool_call: Tool_Call) -> Agent_Orchestrator:
    return Agent_Orchestrator(
        Fallback_Provider(),
        registry,
        iteration_limit=10,
        selection_strategy=_CallOnceThenFinalStrategy(tool_call),
    )


# Feature: agentforge-agentic-layer, Property 7: Successful tool dispatch records an
# observation and continues.
@hyp_settings(max_examples=100, deadline=None)
@given(query=st.text(max_size=30))
def test_successful_tool_dispatch_records_observation_and_continues(query):
    """Feature: agentforge-agentic-layer, Property 7: For any reasoning step that produces
    a Tool_Call naming a registered tool with valid arguments, the orchestrator resolves
    and invokes that tool and records its Tool_Result as an observation, and the loop
    continues rather than terminating on that step.

    Validates: Requirements 3.2, 3.3
    """
    tool = _RecordingTool()
    registry = Tool_Registry()
    registry.register(tool)
    orchestrator = _orchestrator(registry, Tool_Call(tool.name, {"anything": query}))

    state = orchestrator.run("please use the tool")

    # The tool was invoked and its result recorded as an observation.
    assert tool.invoke_count == 1
    assert any(o.kind == OBS_TOOL_RESULT and o.tool_name == tool.name for o in state.observations)
    # The loop continued past the tool step to a normal final-answer termination.
    assert state.termination_reason is TerminationReason.FINAL_ANSWER
    assert state.iteration_count == 1


# Feature: agentforge-agentic-layer, Property 8: Unregistered tool calls are contained.
@hyp_settings(max_examples=100, deadline=None)
@given(unknown_name=st.text(min_size=1, max_size=20))
def test_unregistered_tool_call_is_contained(unknown_name):
    """Feature: agentforge-agentic-layer, Property 8: For any Tool_Call naming a tool that
    is not registered, the orchestrator records a tool-not-found observation and continues
    the Agent_Run without terminating on that step.

    Validates: Requirements 3.4
    """
    registry = Tool_Registry()  # empty: no tool is registered under any name
    orchestrator = _orchestrator(registry, Tool_Call(unknown_name, {}))

    state = orchestrator.run("call a missing tool")

    assert any(
        o.kind == OBS_TOOL_NOT_FOUND and o.tool_name == unknown_name
        for o in state.observations
    )
    # The run continued to a normal termination rather than aborting.
    assert state.termination_reason is TerminationReason.FINAL_ANSWER
    assert state.iteration_count == 1


_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["query"],
    "additionalProperties": False,
}


@st.composite
def _args_and_conformance(draw):
    """Build tool arguments spanning conforming and violating cases, with an oracle."""
    args: dict = {}
    if draw(st.booleans()):
        args["query"] = draw(
            st.one_of(st.text(), st.integers(), st.none(), st.text(min_size=1))
        )
    if draw(st.booleans()):
        args["top_k"] = draw(
            st.one_of(
                st.integers(min_value=-5, max_value=20),
                st.booleans(),
                st.text(max_size=3),
            )
        )
    if draw(st.booleans()):
        args["extra"] = draw(st.integers())

    # Oracle mirroring the schema semantics enforced by validate_arguments.
    conforms = True
    if "extra" in args:
        conforms = False
    q = args.get("query", _MISSING)
    if q is _MISSING or not isinstance(q, str) or len(q) < 1:
        conforms = False
    if "top_k" in args:
        tk = args["top_k"]
        if not isinstance(tk, int) or isinstance(tk, bool) or not (1 <= tk <= 10):
            conforms = False
    return args, conforms


# Feature: agentforge-agentic-layer, Property 9: A tool is invoked if and only if its
# arguments conform to the schema.
@hyp_settings(max_examples=200, deadline=None)
@given(payload=_args_and_conformance())
def test_tool_invoked_iff_arguments_conform(payload):
    """Feature: agentforge-agentic-layer, Property 9: For any Tool_Call, the named tool's
    invoke is called exactly when the provided arguments conform to the tool's input
    schema; when they do not conform, invoke is never called, a validation-error
    observation is recorded, and the loop continues.

    Validates: Requirements 11.2, 11.4
    """
    args, conforms = payload
    tool = _RecordingTool(schema=_SCHEMA)
    registry = Tool_Registry()
    registry.register(tool)
    orchestrator = _orchestrator(registry, Tool_Call(tool.name, args))

    state = orchestrator.run("dispatch with generated args")

    if conforms:
        assert tool.invoke_count == 1
        assert any(o.kind == OBS_TOOL_RESULT for o in state.observations)
    else:
        # Invalid arguments: the tool is never invoked (Req 11.2, 11.4).
        assert tool.invoke_count == 0
        assert any(o.kind == OBS_VALIDATION_ERROR for o in state.observations)
    # Either way the loop continues to a normal termination.
    assert state.termination_reason is TerminationReason.FINAL_ANSWER


# Feature: agentforge-agentic-layer, Property 10: Tool execution errors are contained.
@hyp_settings(max_examples=100, deadline=None)
@given(user_request=st.text(max_size=30))
def test_tool_execution_error_is_contained(user_request):
    """Feature: agentforge-agentic-layer, Property 10: For any tool whose invoke raises an
    error during a run, the orchestrator records a tool-execution-error observation and
    continues the Agent_Run to a normal termination without crashing the process.

    Validates: Requirements 11.3
    """
    tool = _RaisingTool(name="boom_tool")
    registry = Tool_Registry()
    registry.register(tool)
    orchestrator = _orchestrator(registry, Tool_Call(tool.name, {"x": 1}))

    state = orchestrator.run(user_request)

    assert tool.invoke_count == 1  # invoke was attempted
    assert any(
        o.kind == OBS_TOOL_EXECUTION_ERROR and o.tool_name == tool.name
        for o in state.observations
    )
    # The run continues to a normal (non-crashing) termination.
    assert state.termination_reason is TerminationReason.FINAL_ANSWER
    assert state.iteration_count == 1
