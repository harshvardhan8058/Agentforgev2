"""Decision parsing must survive unescaped newlines inside the JSON answer.

Regression test for an observed production failure. A real model answered a
multi-agent writer step with:

    {"action": "final", "answer": "A comprehensive plan involves:
    1. Market Research: ...
    2. Product Planning: ..."}

That is *invalid* strict JSON — a literal newline inside a string value. `json.loads`
defaulted to ``strict=True``, raised, and `parse_decision` fell through to its
"nothing parseable" branch, which returns the raw text as the answer. The result was
that the entire `{"action": "final", "answer": ...}` envelope was surfaced to the
operator as the draft and the final output.

Models emit unescaped newlines routinely, so this has to be tolerated rather than
merely instructed against.
"""

from __future__ import annotations

from agentforge.agent.selection import parse_decision


def test_multiline_answer_with_literal_newlines_is_parsed() -> None:
    raw = (
        '{"action": "final", "answer": "A comprehensive product launch plan:\n'
        "1. Market Research: understand the audience.\n"
        '2. Product Planning: define features and pricing."}'
    )

    decision = parse_decision(raw)

    assert decision.is_final is True
    # The envelope must be unwrapped, not leaked.
    assert decision.answer is not None
    assert decision.answer.startswith("A comprehensive product launch plan:")
    assert "Market Research" in decision.answer
    assert '"action"' not in decision.answer
    assert not decision.answer.lstrip().startswith("{")


def test_escaped_newlines_still_parse() -> None:
    decision = parse_decision('{"action": "final", "answer": "line one\\nline two"}')

    assert decision.is_final is True
    assert decision.answer == "line one\nline two"


def test_multiline_tool_arguments_are_parsed() -> None:
    raw = '{"action": "tool", "tool": "rag_search", "arguments": {"query": "a\nb"}}'

    decision = parse_decision(raw)

    assert decision.is_final is False
    assert decision.tool_call is not None
    assert decision.tool_call.tool_name == "rag_search"
    assert decision.tool_call.arguments == {"query": "a\nb"}


def test_json_wrapped_in_a_markdown_fence_is_parsed() -> None:
    raw = '```json\n{"action": "final", "answer": "fenced answer"}\n```'

    decision = parse_decision(raw)

    assert decision.is_final is True
    assert decision.answer == "fenced answer"


def test_plain_prose_still_terminates_as_a_final_answer() -> None:
    # A provider that ignores the JSON contract must still terminate cleanly.
    decision = parse_decision("Just a sentence.")

    assert decision.is_final is True
    assert decision.answer == "Just a sentence."
