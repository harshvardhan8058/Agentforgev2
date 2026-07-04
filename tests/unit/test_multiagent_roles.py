"""Unit tests for the four built-in Agent_Roles (Task 4.5).

Verify each role delegates to the injected existing ``Agent_Orchestrator`` (and the
Researcher surfaces the RAG pipeline's citations via ``extract_citations``) rather than
generating text itself, that the four roles expose distinct ``role_id``s and distinct
``instructions``, and that citations are preserved from research through the draft
(Req 1.2, 1.3, 3.2, 8.2, 8.4, 11.1).
"""

from __future__ import annotations

from agentforge.agent.state import AgentState, Observation
from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Critic_Feedback,
    Draft,
    Plan,
    Research_Finding,
    Research_Findings,
)
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.state import Blackboard_State


class _FakeOrchestrator:
    """Records every ``run`` call and returns a canned AgentState (test double).

    Standing in for the reused single-agent orchestrator lets us assert a role delegates
    to it (rather than generating text itself) and never re-implements reasoning.
    """

    def __init__(self, answer: str = "generated answer", citations=None) -> None:
        self.calls: list[str] = []
        self._answer = answer
        self._citations = citations or []

    def run(self, user_request, conversation_context=None, *, conversation_id=None):
        self.calls.append(user_request)
        observation = Observation(
            kind="tool_result",
            tool_name="rag_search",
            content=self._answer,
            data={"citations": [dict(c) for c in self._citations]},
        )
        return AgentState(
            run_id="run",
            conversation_id=conversation_id or "conv",
            user_request=user_request,
            observations=[observation],
            final_answer=self._answer,
        )


def _state() -> Blackboard_State:
    return Blackboard_State(run_id="run", conversation_id="conv", task="explain caching")


def test_planner_delegates_and_populates_plan():
    orch = _FakeOrchestrator(answer="Step one\nStep two")
    planner = Planner_Agent(orch)

    result = planner.act(_state())

    assert len(orch.calls) == 1  # delegated to the injected orchestrator
    assert planner.instructions in orch.calls[0]  # role-scoped request
    assert isinstance(result.plan, Plan)
    assert result.plan.steps == ["Step one", "Step two"]


def test_researcher_delegates_and_surfaces_citations():
    citations = [{"document_id": "d1", "chunk_id": "c1"}]
    orch = _FakeOrchestrator(answer="grounded finding", citations=citations)
    researcher = Researcher_Agent(orch)

    result = researcher.act(_state())

    assert len(orch.calls) == 1
    assert isinstance(result.research_findings, Research_Findings)
    finding = result.research_findings.findings[0]
    assert finding.content == "grounded finding"
    assert finding.citations == [Citation(document_id="d1", chunk_id="c1")]


def test_writer_delegates_and_preserves_citations():
    orch = _FakeOrchestrator(answer="the draft body")
    writer = Writer_Agent(orch)
    state = _state()
    citation = Citation(document_id="d1", chunk_id="c1")
    state.research_findings = Research_Findings(
        findings=[Research_Finding(content="finding", citations=[citation, citation])]
    )

    result = writer.act(state)

    assert len(orch.calls) == 1
    assert isinstance(result.draft, Draft)
    assert result.draft.content == "the draft body"
    # Citations preserved (de-duplicated union of used findings' citations) (Req 8.2).
    assert result.draft.citations == [citation]


def test_writer_incorporates_feedback_on_revision():
    orch = _FakeOrchestrator(answer="revised draft")
    writer = Writer_Agent(orch)
    state = _state()
    state.critic_feedback = Critic_Feedback(revision_required=True, comments="add detail")

    writer.act(state)

    assert "add detail" in orch.calls[0]  # feedback fed into the revision request


def test_critic_delegates_and_defaults_to_approve():
    orch = _FakeOrchestrator(answer="the draft looks good")
    critic = Critic_Agent(orch)
    state = _state()
    state.draft = Draft(content="draft")

    result = critic.act(state)

    assert len(orch.calls) == 1
    assert isinstance(result.critic_feedback, Critic_Feedback)
    # The default keyless Critic approves deterministically (Req 3.7).
    assert result.critic_feedback.revision_required is False


def test_critic_requests_revision_on_explicit_directive():
    orch = _FakeOrchestrator(answer="Needs work. DECISION: revise the intro.")
    critic = Critic_Agent(orch)
    state = _state()
    state.draft = Draft(content="draft")

    result = critic.act(state)

    assert result.critic_feedback.revision_required is True


def test_roles_expose_distinct_ids_and_instructions():
    orch = _FakeOrchestrator()
    roles = [
        Planner_Agent(orch),
        Researcher_Agent(orch),
        Writer_Agent(orch),
        Critic_Agent(orch),
    ]

    ids = [r.role_id for r in roles]
    instructions = [r.instructions for r in roles]

    assert ids == ["planner", "researcher", "writer", "critic"]
    assert len(set(ids)) == 4  # distinct role ids (Req 1.3)
    assert len(set(instructions)) == 4  # distinct instructions (Req 1.3)
