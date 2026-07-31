"""Critic_Agent: grounding review, and the keyless determinism it must not break.

Observed failure this covers: a real multi-agent run produced a draft carrying invented
academic references ("(Marketing Management, Philip Kotler)") that appeared nowhere in
the retrieved findings, and the Critic *praised* it for "the use of citations from
relevant academic sources". It could not have done otherwise — ``_critic_context`` passed
only the task and the draft, so the evidence needed to verify any claim was never in the
Critic's context at all.

Two properties are asserted here:

* The Critic receives the plan and the research findings, so grounding is checkable.
* The keyless Fallback_Provider still APPROVES. That provider answers by echoing the
  prompt, so if the literal revise directive ever appeared in the instructions the default
  Critic would demand a revision of every draft and the reproducible keyless termination
  guarantee (Req 3.7) would be lost.
"""

from __future__ import annotations

from uuid import uuid4

from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Critic_Feedback,
    Draft,
    Research_Finding,
    Plan,
    Research_Findings,
)
from agentforge.multiagent.roles.critic import _REVISE_DIRECTIVE, Critic_Agent
from agentforge.multiagent.state import Blackboard_State


class _FakeOrchestrator:
    """Records the request it is given and returns a fixed answer."""

    def __init__(self, answer: str = "looks good") -> None:
        self._answer = answer
        self.calls: list[str] = []

    def run(self, request: str, conversation_id=None):  # noqa: ANN001, ARG002
        self.calls.append(request)

        class _Result:
            final_answer = self._answer

        return _Result()


def _state_with_findings() -> Blackboard_State:
    state = Blackboard_State(
        run_id="run", conversation_id="conv", task="Outline a launch plan"
    )
    state.plan = Plan(steps=["Research the market", "Draft the plan"])
    state.research_findings = Research_Findings(
        findings=[
            Research_Finding(
                content="Internal corpus: the launch checkpoint is Harbor Seven.",
                citations=[Citation(document_id=uuid4(), chunk_id=uuid4())],
            )
        ]
    )
    state.draft = Draft(content="A launch plan (Marketing Management, Philip Kotler).")
    return state


def test_critic_receives_the_plan_and_the_findings() -> None:
    orch = _FakeOrchestrator()
    Critic_Agent(orch).act(_state_with_findings())

    request = orch.calls[0]
    # The evidence must be in the Critic's context, or grounding is unverifiable.
    assert "Harbor Seven" in request
    assert "Research the market" in request
    assert "A launch plan" in request


def test_critic_is_told_to_treat_unsupported_citations_as_fabricated() -> None:
    instructions = Critic_Agent(_FakeOrchestrator()).instructions.lower()
    assert "fabricated" in instructions
    # It must look for invented attributions specifically, not just structure.
    for term in ("citation", "author", "url"):
        assert term in instructions


def test_critic_notes_absent_findings_rather_than_staying_silent() -> None:
    orch = _FakeOrchestrator()
    state = Blackboard_State(run_id="run", conversation_id="conv", task="t")
    state.draft = Draft(content="Claim with a source (Some Book, Some Author).")

    Critic_Agent(orch).act(state)

    # With no findings, the context must say so explicitly so the reviewer cannot
    # assume evidence exists that was never retrieved.
    assert "none were retrieved" in orch.calls[0]


def test_instructions_never_contain_the_literal_revise_directive() -> None:
    """Guard on the keyless determinism (Req 3.7).

    The Fallback_Provider echoes the prompt, so the literal directive appearing in the
    instructions would make the default Critic request a revision every time.
    """
    instructions = Critic_Agent(_FakeOrchestrator()).instructions.lower()
    assert _REVISE_DIRECTIVE not in instructions


def test_keyless_fallback_critic_still_approves() -> None:
    """End-to-end guard: run the REAL Fallback_Provider over the real prompt."""

    class _FallbackOrchestrator:
        def __init__(self) -> None:
            self._llm = Fallback_Provider()

        def run(self, request: str, conversation_id=None):  # noqa: ANN001, ARG002
            result = self._llm.generate(request)

            class _Result:
                final_answer = result.text

            return _Result()

    state = _state_with_findings()
    result = Critic_Agent(_FallbackOrchestrator()).act(state)

    assert isinstance(result.critic_feedback, Critic_Feedback)
    # Deterministic approval preserved.
    assert result.critic_feedback.revision_required is False


def test_explicit_directive_still_requests_a_revision() -> None:
    orch = _FakeOrchestrator(answer="Unsupported source. Decision: REVISE the claims.")
    result = Critic_Agent(orch).act(_state_with_findings())

    assert result.critic_feedback.revision_required is True
