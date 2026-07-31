"""Critic_Agent — reviews the Draft and emits structured Critic_Feedback.

The Critic reuses the existing Phase 3 ``Agent_Orchestrator`` (injected) for its reasoning
(Req 1.2, 11.1). ``act`` emits structured :class:`Critic_Feedback` with an explicit
``revision_required`` flag plus comments (Req 1.3, 4.6). Under the keyless
``Fallback_Provider`` the decision is deterministic — the default fallback Critic
**approves** the draft (``revision_required=False``) — so a run with identical input
terminates after an identical number of revision cycles (Req 3.7). A revision is requested
only when the reviewed answer contains an explicit, structured revise directive that the
deterministic fallback never produces, so termination stays reproducible.
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.multiagent.models import Critic_Feedback
from agentforge.multiagent.roles.base import Agent_Role_Interface
from agentforge.multiagent.state import Blackboard_State

# An explicit structured directive the deterministic Fallback_Provider never emits, so the
# default keyless Critic approves and the run terminates reproducibly (Req 3.7).
_REVISE_DIRECTIVE = "decision: revise"


class Critic_Agent(Agent_Role_Interface):
    """The Agent_Role that reviews the Draft and approves or requests a revision (Req 4.6)."""

    def __init__(self, orchestrator: Agent_Orchestrator) -> None:
        # The SAME existing single-agent orchestrator is reused (Req 11.1).
        self._orchestrator = orchestrator

    @property
    def role_id(self) -> str:
        return "critic"

    @property
    def instructions(self) -> str:
        # NOTE ON WORDING: the literal directive phrase (see ``_REVISE_DIRECTIVE``) must
        # never appear contiguously in these instructions. The keyless Fallback_Provider
        # answers by echoing the prompt, so embedding the phrase here would make the
        # default Critic request a revision of every draft and destroy the reproducible
        # keyless termination guarantee (Req 3.7). The label and the verdict words are
        # therefore described separately rather than shown as one string.
        return (
            "You are the Critic. Review the draft against the task, the plan, and the "
            "research findings supplied below.\n"
            "\n"
            "Check, in this order:\n"
            "1. Grounding — every factual claim, figure and attribution in the draft must "
            "be supported by the research findings. Treat any source, citation, book, "
            "author or URL that does not appear in the findings as FABRICATED, and require "
            "a revision that removes it. Plausible-looking references are the most "
            "important defect to catch, not a sign of quality.\n"
            "2. Completeness — does the draft actually fulfil the task and the plan?\n"
            "3. Clarity — is it well organised and unambiguous?\n"
            "\n"
            "Then end your reply with a final line consisting of the label 'Decision:' "
            "followed by exactly one verdict word: APPROVE when the draft is fully "
            "grounded and complete, or the word REVISE when it is not. When asking for "
            "changes, list them specifically."
        )

    def act(self, state: Blackboard_State) -> Blackboard_State:
        """Emit structured Critic_Feedback on the Blackboard_State (Req 4.6, 3.7)."""
        request = f"{self.instructions}\n\n{_critic_context(state)}"
        result = self._orchestrator.run(
            request, conversation_id=state.conversation_id
        )
        answer = result.final_answer or ""
        revision_required = _REVISE_DIRECTIVE in answer.lower()
        state.critic_feedback = Critic_Feedback(
            revision_required=revision_required,
            comments=answer,
        )
        return state


def _critic_context(state: Blackboard_State) -> str:
    """Build the Critic's role-scoped context: task, plan, findings, and the Draft.

    The plan and the Research_Findings are included because the Critic's first duty is to
    verify the draft's claims against the evidence actually retrieved. Reviewing a draft
    without the findings alongside it makes grounding unverifiable, which is how a draft
    carrying invented references can be approved as well sourced.
    """
    lines = [f"Task:\n{state.task}"]

    if state.plan and state.plan.steps:
        joined = "\n".join(f"- {step}" for step in state.plan.steps)
        lines.append(f"Plan steps:\n{joined}")

    if state.research_findings and state.research_findings.findings:
        joined = "\n".join(f"- {f.content}" for f in state.research_findings.findings)
        lines.append(f"Research findings (the ONLY admissible evidence):\n{joined}")
    else:
        lines.append(
            "Research findings (the ONLY admissible evidence):\n"
            "(none were retrieved — any specific source cited in the draft is therefore "
            "unsupported)"
        )

    draft_content = state.draft.content if state.draft else "(no draft produced)"
    lines.append(f"Draft under review:\n{draft_content}")

    return "\n\n".join(lines)
