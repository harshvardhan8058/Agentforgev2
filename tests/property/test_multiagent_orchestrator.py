"""Property tests for the Multi_Agent_Orchestrator graph (Properties 1, 2, 3, 4, 7, 8).

These run fully **keyless**: the graph is driven by injected deterministic roles/critics
(and, for the citation property, the real ``Writer_Agent`` over a fake single-agent
orchestrator), so the two structural bounds, the exactly-one-termination guarantee, the
approval→completion path, the blackboard accumulation/order, and citation preservation are
exercised in isolation — no network, no credentials.

The always-revise Critic used to force the revision/round bounds is itself an
``Agent_Role_Interface`` implementation registered under ``"critic"``, which also
demonstrates the "add/replace a role without touching the core" seam (Req 1.4).
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.state import AgentState, Observation
from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Critic_Feedback,
    Draft,
    Plan,
    Research_Finding,
    Research_Findings,
    Termination_Reason,
)
from agentforge.multiagent.orchestrator import Multi_Agent_Orchestrator
from agentforge.multiagent.roles.base import Agent_Role_Interface, Agent_Role_Registry
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.state import Blackboard_State

_PIPELINE = ["planner", "researcher", "writer", "critic"]

_TERMINATION_REASONS = {
    Termination_Reason.COMPLETED,
    Termination_Reason.MAX_ROUNDS_REACHED,
    Termination_Reason.MAX_REVISIONS_REACHED,
    Termination_Reason.REJECTED,
    Termination_Reason.ABORTED,
}


# --- injectable deterministic roles -----------------------------------------------


class _FnRole(Agent_Role_Interface):
    """A deterministic role whose ``act`` is supplied as a plain function."""

    def __init__(self, role_id: str, act_fn) -> None:
        self._role_id = role_id
        self._act_fn = act_fn

    @property
    def role_id(self) -> str:
        return self._role_id

    @property
    def instructions(self) -> str:
        return f"instructions for {self._role_id}"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        return self._act_fn(state)


def _planner(state: Blackboard_State) -> Blackboard_State:
    state.plan = Plan(steps=[f"plan-for:{state.task}"])
    return state


def _researcher(state: Blackboard_State) -> Blackboard_State:
    state.research_findings = Research_Findings(
        findings=[Research_Finding(content="finding", citations=[])]
    )
    return state


def _writer(state: Blackboard_State) -> Blackboard_State:
    # Content encodes the counters so revised drafts differ from the initial draft.
    state.draft = Draft(
        content=f"draft@round{state.round_count},rev{state.revision_count}"
    )
    return state


class _ApproveCritic(Agent_Role_Interface):
    """A deterministic Critic that always approves (Req 2.3)."""

    @property
    def role_id(self) -> str:
        return "critic"

    @property
    def instructions(self) -> str:
        return "approve the draft"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        state.critic_feedback = Critic_Feedback(revision_required=False, comments="ok")
        return state


class _AlwaysReviseCritic(Agent_Role_Interface):
    """A deterministic Critic that always requests a revision (forces the bounds)."""

    @property
    def role_id(self) -> str:
        return "critic"

    @property
    def instructions(self) -> str:
        return "always request a revision"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        state.critic_feedback = Critic_Feedback(
            revision_required=True, comments="needs work"
        )
        return state


def _build_orchestrator(
    critic: Agent_Role_Interface,
    *,
    max_rounds,
    max_revisions,
    planner_fn=_planner,
    researcher_fn=_researcher,
    writer_role: Agent_Role_Interface | None = None,
    trace=None,
) -> Multi_Agent_Orchestrator:
    """Wire a registry from injected roles and build the orchestrator."""
    registry = Agent_Role_Registry()
    registry.register(_FnRole("planner", planner_fn))
    registry.register(_FnRole("researcher", researcher_fn))
    registry.register(writer_role or _FnRole("writer", _writer))
    registry.register(critic)
    return Multi_Agent_Orchestrator(
        registry,
        _PIPELINE,
        max_rounds=max_rounds,
        max_revisions=max_revisions,
        trace=trace,
    )


# Feature: agentforge-multi-agent, Property 1: Round count is bounded by Max_Rounds and
# increments by exactly one.
@hyp_settings(max_examples=100, deadline=None)
@given(task=st.text(max_size=40), max_rounds=st.integers(min_value=1, max_value=12))
def test_round_count_bounded_by_max_rounds(task, max_rounds):
    """Feature: agentforge-multi-agent, Property 1: Round count is bounded by Max_Rounds
    and increments by exactly one — for any task, any Max_Rounds, and an always-revise
    Critic, round_count never exceeds Max_Rounds and, when it reaches Max_Rounds, the run
    terminates max-rounds-reached returning the most recent Draft.

    Max_Revisions is set to 20 (its ceiling) so the revision bound never intervenes; the
    always-revise Critic therefore forces the round bound.

    Validates: Requirements 2.2, 2.4, 12.4
    """
    orchestrator = _build_orchestrator(
        _AlwaysReviseCritic(), max_rounds=max_rounds, max_revisions=20
    )
    state = orchestrator.run(task)

    assert state.round_count <= max_rounds  # never exceeds the bound (Req 2.4)
    assert state.round_count == max_rounds  # always-revise forces the round bound
    assert state.termination_reason is Termination_Reason.MAX_ROUNDS_REACHED
    # The most recent available Draft is returned as the Final_Output.
    assert state.final_output is not None
    assert state.final_output.content == state.draft.content


# Feature: agentforge-multi-agent, Property 2: Revision count is bounded by Max_Revisions
# with the exact boundary.
@hyp_settings(max_examples=100, deadline=None)
@given(task=st.text(max_size=40), max_revisions=st.integers(min_value=1, max_value=15))
def test_revision_count_bounded_by_max_revisions(task, max_revisions):
    """Feature: agentforge-multi-agent, Property 2: Revision count is bounded by
    Max_Revisions with the exact boundary — for any task, any Max_Revisions, and an
    always-revise Critic, revision_count increases by exactly 1 per revision, a revision
    is still permitted when revision_count == Max_Revisions - 1, revision_count never
    exceeds Max_Revisions, and at Max_Revisions the run terminates max-revisions-reached
    returning the most recent Draft.

    Max_Rounds is set to Max_Revisions + 2 so the round bound never intervenes first.

    Validates: Requirements 3.1, 3.3, 3.4, 12.4
    """
    writer_calls: list[int] = []

    def counting_writer(state: Blackboard_State) -> Blackboard_State:
        # Record revision_count at entry (the node applies the +1 after this returns).
        writer_calls.append(state.revision_count)
        return _writer(state)

    orchestrator = _build_orchestrator(
        _AlwaysReviseCritic(),
        max_rounds=max_revisions + 2,
        max_revisions=max_revisions,
        writer_role=_FnRole("writer", counting_writer),
    )
    state = orchestrator.run(task)

    assert state.revision_count <= max_revisions  # never exceeds the bound (Req 3.4)
    assert state.revision_count == max_revisions  # always-revise forces the bound
    assert state.termination_reason is Termination_Reason.MAX_REVISIONS_REACHED
    # Exactly one initial draft plus Max_Revisions revisions. Each revision entry records
    # revision_count *before* the node's +1, so the entry values are the initial 0 then
    # 0, 1, ..., Max_Revisions - 1 — the last revision was permitted exactly at the
    # boundary revision_count == Max_Revisions - 1 (Req 3.3).
    assert len(writer_calls) == max_revisions + 1
    assert writer_calls == [0, *range(max_revisions)]
    assert writer_calls[-1] == max_revisions - 1  # the boundary revision was permitted
    assert state.final_output is not None
    assert state.final_output.content == state.draft.content


# Feature: agentforge-multi-agent, Property 3: Every run terminates with exactly one
# Termination_Reason.
@hyp_settings(max_examples=100, deadline=None)
@given(
    task=st.text(max_size=40),
    always_revise=st.booleans(),
    max_rounds=st.one_of(
        st.integers(min_value=1, max_value=12),
        st.integers(min_value=-5, max_value=0),  # invalid -> default 6
        st.none(),
    ),
    max_revisions=st.one_of(
        st.integers(min_value=1, max_value=10),
        st.integers(min_value=100, max_value=200),  # invalid -> default 3
        st.none(),
    ),
)
def test_every_run_terminates_with_exactly_one_reason(
    task, always_revise, max_rounds, max_revisions
):
    """Feature: agentforge-multi-agent, Property 3: Every run terminates with exactly one
    Termination_Reason — across approving and always-revise Critics and valid/invalid
    bounds, the run terminates with termination_reason set to exactly one value from the
    allowed set, never unset.

    Validates: Requirements 2.7
    """
    critic: Agent_Role_Interface = (
        _AlwaysReviseCritic() if always_revise else _ApproveCritic()
    )
    orchestrator = _build_orchestrator(
        critic, max_rounds=max_rounds, max_revisions=max_revisions
    )
    state = orchestrator.run(task)

    # Exactly one reason: a single enum value, always set, drawn from the allowed set.
    assert isinstance(state.termination_reason, Termination_Reason)
    assert state.termination_reason in _TERMINATION_REASONS
    if not always_revise:
        assert state.termination_reason is Termination_Reason.COMPLETED
    else:
        assert state.termination_reason in {
            Termination_Reason.MAX_ROUNDS_REACHED,
            Termination_Reason.MAX_REVISIONS_REACHED,
        }


# Feature: agentforge-multi-agent, Property 4: Critic approval completes the run and emits
# the Draft as Final_Output.
@hyp_settings(max_examples=100, deadline=None)
@given(
    task=st.text(max_size=40),
    draft_body=st.text(max_size=60),
    max_rounds=st.integers(min_value=1, max_value=12),
    max_revisions=st.integers(min_value=1, max_value=10),
)
def test_critic_approval_completes_and_emits_draft(
    task, draft_body, max_rounds, max_revisions
):
    """Feature: agentforge-multi-agent, Property 4: Critic approval completes the run and
    emits the Draft as Final_Output — when the Critic approves, the run terminates
    completed and the Final_Output content equals the approved Draft content.

    Validates: Requirements 2.3
    """

    def fixed_writer(state: Blackboard_State) -> Blackboard_State:
        state.draft = Draft(content=draft_body)
        return state

    orchestrator = _build_orchestrator(
        _ApproveCritic(),
        max_rounds=max_rounds,
        max_revisions=max_revisions,
        writer_role=_FnRole("writer", fixed_writer),
    )
    state = orchestrator.run(task)

    assert state.termination_reason is Termination_Reason.COMPLETED
    assert state.final_output is not None
    assert state.final_output.content == draft_body  # Final_Output == approved Draft
    assert state.final_output.content == state.draft.content


# Feature: agentforge-multi-agent, Property 7: Blackboard accumulation and role activation
# order.
@hyp_settings(max_examples=100, deadline=None)
@given(task=st.text(max_size=40))
def test_blackboard_accumulation_and_role_order(task):
    """Feature: agentforge-multi-agent, Property 7: Blackboard accumulation and role
    activation order — the roles activate in pipeline order beginning at the Planner, and
    after each role's node the Blackboard_State carries that role's contribution with each
    prior contribution still present.

    Each role asserts (at entry) that exactly its expected prior contributions are
    present, and records its activation; a single approving round yields the
    Planner→Researcher→Writer→Critic order.

    Validates: Requirements 2.1, 4.2, 4.3, 4.4, 4.5, 4.6
    """
    activations: list[str] = []

    def planner(state: Blackboard_State) -> Blackboard_State:
        # Planner activates first: no prior contributions exist yet (Req 2.1).
        assert state.plan is None
        assert state.research_findings is None
        assert state.draft is None
        assert state.critic_feedback is None
        activations.append("planner")
        return _planner(state)

    def researcher(state: Blackboard_State) -> Blackboard_State:
        # The Plan produced by the Planner is present (Req 4.3, 4.2).
        assert state.plan is not None
        assert state.research_findings is None
        activations.append("researcher")
        return _researcher(state)

    def writer(state: Blackboard_State) -> Blackboard_State:
        # Plan + Research_Findings retained from prior nodes (Req 4.4, 4.2).
        assert state.plan is not None
        assert state.research_findings is not None
        activations.append("writer")
        return _writer(state)

    class _RecordingApproveCritic(_ApproveCritic):
        def act(self, state: Blackboard_State) -> Blackboard_State:
            # Plan + Research_Findings + Draft retained from prior nodes (Req 4.5, 4.2).
            assert state.plan is not None
            assert state.research_findings is not None
            assert state.draft is not None
            activations.append("critic")
            return super().act(state)

    orchestrator = _build_orchestrator(
        _RecordingApproveCritic(),
        max_rounds=6,
        max_revisions=3,
        planner_fn=planner,
        researcher_fn=researcher,
        writer_role=_FnRole("writer", writer),
    )
    state = orchestrator.run(task)

    # Roles activated in pipeline order, starting at the Planner (Req 2.1).
    assert activations == ["planner", "researcher", "writer", "critic"]
    # After the run every role's contribution is present on the blackboard (Req 4.3-4.6).
    assert state.plan is not None
    assert state.research_findings is not None
    assert state.draft is not None
    assert state.critic_feedback is not None


# --- fake single-agent orchestrator for the real Writer_Agent ---------------------


class _FakeAgentOrchestrator:
    """Stand-in for the reused single-agent orchestrator: returns a canned AgentState."""

    def __init__(self, answer: str = "the draft body") -> None:
        self._answer = answer

    def run(self, user_request, conversation_context=None, *, conversation_id=None):
        return AgentState(
            run_id="run",
            conversation_id=conversation_id or "conv",
            user_request=user_request,
            observations=[
                Observation(
                    kind="tool_result", tool_name="rag_search", content=self._answer
                )
            ],
            final_answer=self._answer,
        )


_citations = st.lists(
    st.builds(
        Citation,
        document_id=st.text(min_size=1, max_size=6),
        chunk_id=st.text(min_size=1, max_size=6),
    ),
    max_size=6,
)


# Feature: agentforge-multi-agent, Property 8: Citation preservation from research through
# draft to final output.
@hyp_settings(max_examples=100, deadline=None)
@given(
    task=st.text(max_size=40),
    citations=_citations,
    always_revise=st.booleans(),
    max_revisions=st.integers(min_value=1, max_value=6),
)
def test_citation_preservation_research_to_final(
    task, citations, always_revise, max_revisions
):
    """Feature: agentforge-multi-agent, Property 8: Citation preservation from research
    through draft to final output — every Citation of the Research_Findings the Writer
    uses is retained in the Draft (including across revision cycles), and the Final_Output
    includes exactly the Citations retained in the Draft: none invented, none dropped.

    The real ``Writer_Agent`` (over a fake single-agent orchestrator) computes the Draft's
    citations, so its preservation logic is exercised through the real graph.

    Validates: Requirements 3.2, 8.1, 8.2, 8.3
    """
    # The de-duplicated union of the used findings' citations, in first-seen order.
    expected: list[Citation] = []
    for citation in citations:
        if citation not in expected:
            expected.append(citation)

    def researcher(state: Blackboard_State) -> Blackboard_State:
        state.research_findings = Research_Findings(
            findings=[Research_Finding(content="finding", citations=list(citations))]
        )
        return state

    critic: Agent_Role_Interface = (
        _AlwaysReviseCritic() if always_revise else _ApproveCritic()
    )
    orchestrator = _build_orchestrator(
        critic,
        max_rounds=max_revisions + 2,
        max_revisions=max_revisions,
        researcher_fn=researcher,
        writer_role=Writer_Agent(_FakeAgentOrchestrator()),
    )
    state = orchestrator.run(task)

    # Citations preserved onto the Draft (union of used findings' citations) (Req 8.2).
    assert state.draft is not None
    assert state.draft.citations == expected
    # Final_Output includes exactly the Draft's retained citations (Req 8.3).
    assert state.final_output is not None
    assert state.final_output.citations == expected
