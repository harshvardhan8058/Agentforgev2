"""No decision envelope may ever reach the user as prose.

Regression tests for two *observed* production failures that
``test_decision_parsing_multiline`` did not cover. Both were reproduced against the
real ``parse_decision`` before the fix and both surfaced raw JSON in the UI.

**Failure 1 — an unrecognized ``action``.** The Planner emitted a wrapper the contract
never mentions, holding a list of tool calls, with stray commas that make the wrapper
itself invalid JSON::

    {"action": "order", "steps": [, {"action": "tool", ...},, {"action": "tool", ...}

``parse_decision`` only recognized ``action == "tool"`` and ``action == "final"``, so
this fell through to the "nothing parseable" branch and the whole envelope became the
Planner's answer. The Planner splits its answer into steps per line, so the raw JSON
became the plan, which was then shown in the live workflow and the event log.

**Failure 2 — half-escaped line breaks.** The Writer emitted a ``final`` envelope whose
answer mixed escaped ``\\n`` with real newlines *and* stray trailing backslashes. A
backslash followed by a real newline is not a valid escape, so the value cannot be
parsed even with ``strict=False``, and the envelope again leaked verbatim as the
run's Final output.

The invariant under test is stronger than "parse these two payloads": whatever the
provider returns, the text handed to the user must not be a decision envelope.
"""

from __future__ import annotations

import pytest

from agentforge.agent.selection import looks_like_decision_envelope, parse_decision

# The exact Planner payload observed in the UI (truncated mid-wrapper, as it arrived).
OBSERVED_PLANNER_PAYLOAD = (
    '{"action": "order", "steps": [, '
    '{"action": "tool", "tool": "rag_search", "arguments": '
    '{"query": "Design process for creating a car \\n", "top_k": "1"}},, '
    '{"action": "tool", "tool": "rag_search", "arguments": '
    '{"query": "Car design specifications \\n", "top_k": "1"}},, '
    '{"action": "tool", "tool": "rag_search", "arguments": '
    '{"query": "Materials for car body \\n", "top_k": "1"}}'
)

# The exact Writer payload observed in the UI: escaped \n, real newlines, stray "\".
OBSERVED_WRITER_PAYLOAD = (
    '{ "action": "final", "answer": "To create a car, follow these steps:\\n'
    "\n\\n\\\n"
    "\nPlan the car's basic requirements: purpose, target market, and budget\\n"
    "\nThis will determine the overall design and production costs.\\n"
    "\n\\n\\\n"
    "\nDetermine the car's design: number of doors, engine type, and interior space\\n"
    '\nThe engine type will depend on the purpose and target market." }'
)


def _user_visible_text(payload: str) -> str:
    """Return the text a decision would put in front of the user."""
    decision = parse_decision(payload)
    return decision.answer or ""


class TestObservedPlannerEnvelope:
    """Failure 1: an ``action`` outside the contract must not become the answer."""

    def test_does_not_leak_the_envelope_as_an_answer(self) -> None:
        assert '"action"' not in _user_visible_text(OBSERVED_PLANNER_PAYLOAD)

    def test_recovers_the_first_nested_tool_call(self) -> None:
        # The nested tool objects are individually well-formed; the wrapper is not.
        # Recovering the first one keeps the run useful instead of discarding it.
        decision = parse_decision(OBSERVED_PLANNER_PAYLOAD)

        assert decision.is_final is False
        assert decision.tool_call is not None
        assert decision.tool_call.tool_name == "rag_search"
        assert "Design process" in decision.tool_call.arguments["query"]


class TestObservedWriterEnvelope:
    """Failure 2: half-escaped line breaks must not defeat unwrapping."""

    def test_does_not_leak_the_envelope_as_an_answer(self) -> None:
        answer = _user_visible_text(OBSERVED_WRITER_PAYLOAD)

        assert '"action"' not in answer
        assert '"answer"' not in answer
        assert not answer.lstrip().startswith("{")

    def test_recovers_the_readable_prose(self) -> None:
        answer = _user_visible_text(OBSERVED_WRITER_PAYLOAD)

        assert answer.startswith("To create a car, follow these steps:")
        assert "target market, and budget" in answer
        assert answer.endswith("depend on the purpose and target market.")

    def test_does_not_leave_stray_escape_artefacts(self) -> None:
        answer = _user_visible_text(OBSERVED_WRITER_PAYLOAD)

        assert "\\n" not in answer
        assert "\\" not in answer
        # Runs of blank lines left by resolving the escapes are collapsed.
        assert "\n\n\n" not in answer


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(OBSERVED_PLANNER_PAYLOAD, id="observed-planner"),
        pytest.param(OBSERVED_WRITER_PAYLOAD, id="observed-writer"),
        pytest.param('{"action": "order", "steps": ["a", "b"]}', id="unknown-action"),
        pytest.param('{"action": "plan", "plan": [,]}', id="unknown-action-malformed"),
        pytest.param('{"action": "final"}', id="final-without-answer"),
        pytest.param('{"action": "final", "answer": 42}', id="final-non-string-answer"),
        pytest.param('{"action": "tool", "arguments": {}}', id="tool-without-name"),
        pytest.param('{"action": "tool", "tool": ""}', id="tool-with-empty-name"),
        pytest.param('{"action": "final", "answer": "unterminated', id="truncated"),
        pytest.param(
            '```json\n{"action": "order", "steps": [,]}\n```', id="fenced-unknown"
        ),
    ],
)
def test_no_envelope_is_ever_surfaced_as_prose(payload: str) -> None:
    """Whatever the shape, the user-visible text is never a decision envelope."""
    visible = _user_visible_text(payload)

    assert not looks_like_decision_envelope(visible)
    assert '"action"' not in visible


class TestUnaffectedBehaviour:
    """The fix must not disturb the paths that already worked."""

    def test_plain_prose_passes_through_untouched(self) -> None:
        prose = "Cars are assembled on a production line.\n\nThat is the summary."

        assert parse_decision(prose).answer == prose

    def test_prose_mentioning_braces_is_not_treated_as_an_envelope(self) -> None:
        prose = 'Use {"key": "value"} as the request body for the action endpoint.'

        assert parse_decision(prose).answer == prose

    def test_well_formed_final_is_unwrapped(self) -> None:
        decision = parse_decision('{"action": "final", "answer": "All good."}')

        assert decision.is_final is True
        assert decision.answer == "All good."

    def test_well_formed_tool_call_is_unwrapped(self) -> None:
        decision = parse_decision(
            '{"action": "tool", "tool": "rag_search", "arguments": {"query": "q"}}'
        )

        assert decision.is_final is False
        assert decision.tool_call is not None
        assert decision.tool_call.tool_name == "rag_search"
        assert decision.tool_call.arguments == {"query": "q"}

    def test_a_valid_tool_call_still_wins_over_later_objects(self) -> None:
        raw = (
            '{"action": "tool", "tool": "rag_search", "arguments": {"query": "first"}}\n'
            '{"action": "final", "answer": "second"}'
        )
        decision = parse_decision(raw)

        assert decision.is_final is False
        assert decision.tool_call is not None
        assert decision.tool_call.arguments == {"query": "first"}

    def test_empty_input_stays_empty(self) -> None:
        assert parse_decision("").answer == ""


def test_recursion_is_bounded_for_deeply_nested_text() -> None:
    """A pathological wrapper must not blow the stack (depth budget)."""
    payload = "{" * 500 + '"action": "final", "answer": "deep"' + "}" * 500

    decision = parse_decision(payload)

    assert decision.is_final is True
    assert not looks_like_decision_envelope(decision.answer or "")
