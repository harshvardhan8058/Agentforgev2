"""Researcher_Agent — gathers grounded information with Citations.

The Researcher reuses the existing Phase 3 ``Agent_Orchestrator`` (injected), which already
has the ``RAG_Tool`` registered and — under the keyless fallback selection strategy —
prefers ``rag_search`` first, so grounding happens keylessly (Req 1.2, 8.1, 8.4, 11.1,
11.3). It does **not** reimplement retrieval or citation generation: it maps the
orchestrator's grounded answer and ``extract_citations`` output into
:class:`Research_Findings`. The ``Web_Search_Tool`` is used only when configured (keyed);
when unavailable it is simply never offered by the registry (Req 11.3).
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator, extract_citations
from agentforge.models.domain import Citation
from agentforge.multiagent.models import Research_Finding, Research_Findings
from agentforge.multiagent.roles.base import Agent_Role_Interface
from agentforge.multiagent.state import Blackboard_State


class Researcher_Agent(Agent_Role_Interface):
    """The Agent_Role that gathers grounded information for the task (Req 1.3, 4.4, 8.1)."""

    def __init__(self, orchestrator: Agent_Orchestrator) -> None:
        # The SAME existing single-agent orchestrator (with RAG_Tool) is reused (Req 11.1).
        self._orchestrator = orchestrator

    @property
    def role_id(self) -> str:
        return "researcher"

    @property
    def instructions(self) -> str:
        return (
            "You are the Researcher. Gather grounded information for the plan using the "
            "knowledge base only. Report what the knowledge base actually supports and "
            "say so explicitly when it contains nothing relevant. Never invent a source, "
            "citation, book, author or URL — the platform attaches the real citations for "
            "the material you retrieve."
        )

    def act(self, state: Blackboard_State) -> Blackboard_State:
        """Produce Research_Findings with their Citations on the Blackboard (Req 4.4, 8.1)."""
        request = f"{self.instructions}\n\n{_research_context(state)}"
        result = self._orchestrator.run(
            request, conversation_id=state.conversation_id
        )
        # Citations come from the existing RAG pipeline via extract_citations — never
        # reimplemented here (Req 8.4). extract_citations returns plain dicts.
        citations = [Citation(**dict(c)) for c in extract_citations(result)]
        finding = Research_Finding(
            content=result.final_answer or "",
            citations=citations,
        )
        state.research_findings = Research_Findings(findings=[finding])
        return state


def _research_context(state: Blackboard_State) -> str:
    """Build the role-scoped research context from the task and the Plan."""
    lines = [f"Task:\n{state.task}"]
    if state.plan and state.plan.steps:
        joined = "\n".join(f"- {step}" for step in state.plan.steps)
        lines.append(f"Plan steps:\n{joined}")
    return "\n\n".join(lines)
