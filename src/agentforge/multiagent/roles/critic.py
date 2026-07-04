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
        return (
            "You are the Critic. Review the draft against the task and plan. Approve it, "
            "or request a revision describing the specific changes required."
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
    """Build the Critic's role-scoped context from the task and the current Draft."""
    draft_content = state.draft.content if state.draft else "(no draft produced)"
    return f"Task:\n{state.task}\n\nDraft under review:\n{draft_content}"
