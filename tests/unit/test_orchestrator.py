"""Unit tests for the Agent_Orchestrator and graph argument validation.

Covers the keyless end-to-end orchestrator run with a real RAG_Tool wrapping a fake
RAG_Service (the Task 8 checkpoint scenario), invalid-limit resolution surfacing on the
run state, and the JSON-schema argument validator used by the act node.
"""

from __future__ import annotations

from agentforge.agent.graph import validate_arguments
from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.agent.state import TerminationReason
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.models.domain import Citation, Grounded_Answer
from agentforge.tools.rag_tool import RAG_TOOL_NAME, RAG_Tool
from agentforge.tools.registry import Tool_Registry
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.enterprise.tenancy import NIL_ORG_ID as ORG


class _FakeRAGService:
    """A keyless, deterministic RAG_Service double exposing ``answer``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def answer(self, query: str, top_k: int | None = None) -> Grounded_Answer:
        self.calls.append((query, top_k))
        return Grounded_Answer(
            text=f"grounded answer for: {query}",
            citations=[Citation(document_id="doc-1", chunk_id="chunk-1")],
            provider="fallback",
            grounded=True,
        )


def test_orchestrator_runs_end_to_end_keyless_with_rag_tool():
    """The orchestrator grounds an answer via the RAG_Tool under the Fallback_Provider."""
    rag = _FakeRAGService()
    registry = Tool_Registry()
    registry.register(RAG_Tool(rag))
    trace = InMemory_Trace_Recorder()

    orchestrator = Agent_Orchestrator(
        Fallback_Provider(), registry, trace=trace, iteration_limit=None
    )
    state = orchestrator.run("what is agentforge?")

    # The RAG_Service was consulted and its grounded answer became the final answer.
    assert rag.calls == [("what is agentforge?", None)]
    assert state.final_answer == "grounded answer for: what is agentforge?"
    assert state.termination_reason is TerminationReason.FINAL_ANSWER
    assert state.iteration_count == 1
    assert orchestrator.iteration_limit == 10  # default applied when unconfigured

    # A tool-call trace entry records the RAG tool name and a successful outcome.
    entries = trace.get_trace(ORG, state.run_id).entries
    tool_calls = [e for e in entries if e.step_type == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == RAG_TOOL_NAME
    assert tool_calls[0].outcome == "tool_result"


def test_orchestrator_flags_invalid_iteration_limit_on_state():
    """An invalid configured limit resolves to the default and is flagged (Req 1.6)."""
    registry = Tool_Registry()
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(), registry, iteration_limit=999
    )
    state = orchestrator.run("hello")

    assert orchestrator.iteration_limit == 10
    assert state.invalid_limit_flagged is True
    assert state.termination_reason is TerminationReason.FINAL_ANSWER


def test_validate_arguments_accepts_conforming_object():
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    ok, error = validate_arguments({"query": "hi", "top_k": 3}, schema)
    assert ok is True and error == ""


def test_validate_arguments_rejects_missing_required():
    schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    ok, _ = validate_arguments({}, schema)
    assert ok is False


def test_validate_arguments_rejects_additional_properties():
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    ok, _ = validate_arguments({"query": "hi", "extra": 1}, schema)
    assert ok is False


def test_validate_arguments_rejects_wrong_type_and_bool_as_integer():
    schema = {
        "type": "object",
        "properties": {"top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
    }
    # A bool must not be accepted where an integer is required.
    assert validate_arguments({"top_k": True}, schema)[0] is False
    # Out-of-range integer is rejected.
    assert validate_arguments({"top_k": 99}, schema)[0] is False
    # Empty string below minLength is rejected.
    str_schema = {"type": "object", "properties": {"q": {"type": "string", "minLength": 1}}}
    assert validate_arguments({"q": ""}, str_schema)[0] is False
