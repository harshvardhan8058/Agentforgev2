"""Unit tests for decision parsing and deterministic fallback selection (Req 3.1, 3.5)."""

from __future__ import annotations

from agentforge.agent.selection import (
    Deterministic_Fallback_Strategy,
    build_selection_prompt,
    parse_decision,
)
from agentforge.agent.state import AgentState, Observation
from agentforge.tools.base import Tool_Spec


def _rag_spec() -> Tool_Spec:
    return Tool_Spec(
        name="rag_search",
        description="grounded answers",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )


def test_parse_tool_decision():
    """A well-formed tool decision becomes a Tool_Call."""
    text = '{"action": "tool", "tool": "rag_search", "arguments": {"query": "x"}}'
    decision = parse_decision(text)

    assert decision.is_final is False
    assert decision.tool_call is not None
    assert decision.tool_call.tool_name == "rag_search"
    assert decision.tool_call.arguments == {"query": "x"}


def test_parse_final_decision():
    """A well-formed final decision becomes a final answer."""
    decision = parse_decision('{"action": "final", "answer": "done"}')

    assert decision.is_final is True
    assert decision.answer == "done"
    assert decision.tool_call is None


def test_parse_decision_embedded_in_surrounding_text():
    """The first well-formed decision object is extracted from surrounding prose."""
    text = 'Thinking... {"action": "final", "answer": "a"} trailing noise'
    decision = parse_decision(text)

    assert decision.is_final is True
    assert decision.answer == "a"


def test_parse_unparseable_text_falls_back_to_final():
    """Plain text with no decision object defaults to a final answer using the raw text."""
    text = "just a plain answer with no json"
    decision = parse_decision(text)

    assert decision.is_final is True
    assert decision.answer == text


def test_tool_decision_missing_arguments_defaults_to_empty():
    """A tool decision without an arguments object defaults to empty arguments."""
    decision = parse_decision('{"action": "tool", "tool": "web_search"}')

    assert decision.is_final is False
    assert decision.tool_call is not None
    assert decision.tool_call.arguments == {}


def test_fallback_selects_rag_first_step():
    """On the first step the fallback selects the RAG_Tool with the user request query."""
    state = AgentState(run_id="r", conversation_id="c", user_request="hello")
    strategy = Deterministic_Fallback_Strategy()

    decision = strategy.select(state, [_rag_spec()])

    assert decision.is_final is False
    assert decision.tool_call is not None
    assert decision.tool_call.tool_name == "rag_search"
    assert decision.tool_call.arguments == {"query": "hello"}


def test_fallback_finalizes_after_rag_observation():
    """After a RAG observation, the fallback selects a final answer from observations."""
    state = AgentState(run_id="r", conversation_id="c", user_request="hello")
    state.observations.append(
        Observation(kind="tool_result", tool_name="rag_search", content="grounded answer")
    )
    strategy = Deterministic_Fallback_Strategy()

    decision = strategy.select(state, [_rag_spec()])

    assert decision.is_final is True
    assert decision.answer == "grounded answer"


def test_fallback_finalizes_immediately_without_tools():
    """With no tools available, the fallback selects a final answer immediately."""
    state = AgentState(run_id="r", conversation_id="c", user_request="hello")
    strategy = Deterministic_Fallback_Strategy()

    decision = strategy.select(state, [])

    assert decision.is_final is True


def test_fallback_selection_is_deterministic():
    """Identical run state yields an identical decision (Req 3.5, 1.8)."""
    strategy = Deterministic_Fallback_Strategy()
    state_a = AgentState(run_id="r1", conversation_id="c", user_request="same")
    state_b = AgentState(run_id="r2", conversation_id="c", user_request="same")

    d_a = strategy.select(state_a, [_rag_spec()])
    d_b = strategy.select(state_b, [_rag_spec()])

    assert d_a.tool_call == d_b.tool_call


def test_selection_prompt_includes_tool_specs_and_instruction():
    """The reasoning prompt serializes the available tool specs and the decision shape."""
    prompt = build_selection_prompt("what is x?", [], [_rag_spec()])

    assert "rag_search" in prompt
    assert "what is x?" in prompt
    assert '"action"' in prompt  # the fixed decision-shape instruction is present
