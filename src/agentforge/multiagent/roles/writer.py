"""Writer_Agent — produces or revises the Draft, preserving Citations.

The Writer reuses the existing Phase 3 ``Agent_Orchestrator`` (injected) for its reasoning
(Req 1.2, 11.1). ``act`` produces the Draft from the Plan and the Research_Findings and,
on a revision cycle, incorporates the current ``Critic_Feedback`` into the request. It
**preserves the Citations** associated with the content it uses: ``Draft.citations`` is
the de-duplicated union of the Citations of the findings it drew on, carried forward
unchanged across revisions (Req 3.2, 8.2).
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.models.domain import Citation
from agentforge.multiagent.models import Draft, Research_Findings
from agentforge.multiagent.roles.base import Agent_Role_Interface
from agentforge.multiagent.state import Blackboard_State


class Writer_Agent(Agent_Role_Interface):
    """The Agent_Role that produces or revises the Draft (Req 1.3, 4.5, 8.2)."""

    def __init__(self, orchestrator: Agent_Orchestrator) -> None:
        # The SAME existing single-agent orchestrator is reused (Req 11.1).
        self._orchestrator = orchestrator

    @property
    def role_id(self) -> str:
        return "writer"

    @property
    def instructions(self) -> str:
        return (
            "You are the Writer. Produce or revise a clear, well-structured draft that "
            "fulfills the plan using the research findings. On a revision, address the "
            "critic's feedback. Use only the research findings supplied to you: never "
            "invent a source, citation, book, author or URL, and do not add "
            "reference-style attributions of your own — the platform attaches the real "
            "citations for the findings you use. If a point has no supporting finding, "
            "state it plainly without attribution or leave it out."
        )

    def act(self, state: Blackboard_State) -> Blackboard_State:
        """Produce or revise the Draft, preserving its Citations (Req 4.5, 3.2, 8.2)."""
        request = f"{self.instructions}\n\n{_writer_context(state)}"
        result = self._orchestrator.run(
            request, conversation_id=state.conversation_id
        )
        # Preserve the citations of the research content used, carried unchanged across
        # revisions (Req 3.2, 8.2).
        citations = _preserved_citations(state)
        state.draft = Draft(content=result.final_answer or "", citations=citations)
        return state


def _preserved_citations(state: Blackboard_State) -> list[Citation]:
    """Return the de-duplicated union of the Citations the Writer draws on (Req 8.2)."""
    findings: Research_Findings | None = state.research_findings
    ordered: list[Citation] = []
    if findings is not None:
        for citation in findings.all_citations():
            if citation not in ordered:
                ordered.append(citation)
    return ordered


def _writer_context(state: Blackboard_State) -> str:
    """Build the Writer's role-scoped context from the plan, findings, and feedback."""
    lines = [f"Task:\n{state.task}"]
    if state.plan and state.plan.steps:
        joined = "\n".join(f"- {step}" for step in state.plan.steps)
        lines.append(f"Plan steps:\n{joined}")
    if state.research_findings and state.research_findings.findings:
        joined = "\n".join(f"- {f.content}" for f in state.research_findings.findings)
        lines.append(f"Research findings:\n{joined}")
    # On a revision, incorporate the critic's requested changes (Req 3.2).
    if state.critic_feedback and state.critic_feedback.revision_required:
        lines.append(f"Critic feedback to address:\n{state.critic_feedback.comments}")
    return "\n\n".join(lines)
