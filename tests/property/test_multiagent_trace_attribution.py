"""Property test for per-agent tracing attribution (Task 9.1, Property 15).

The multi-agent layer reuses (and does not replace) the existing ``Trace_Recorder`` for
per-agent attribution (Req 6.4): each executed role step is recorded through the same
recorder as a ``role:{role_id}`` entry whose ``detail`` carries the ``role_id`` (Req
6.1). Because ``Trace_Recorder.record`` already assigns a contiguous ascending
``ordinal`` per run and ``get_trace`` returns entries ordered by ordinal, the trace of a
multi-agent run is role-attributed and ordered by construction (Req 6.3).

The property is exercised through the real four roles under the keyless
``Fallback_Provider``. A small ``Max_Rounds`` combined with an always-revise Critic drives
the revision cycle so additional role steps for the revision passes appear in the trace
with the correct role identifiers and monotonically increasing ordinals.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.multiagent.models import Critic_Feedback
from agentforge.multiagent.orchestrator import Multi_Agent_Orchestrator
from agentforge.multiagent.roles.base import (
    DEFAULT_PIPELINE,
    Agent_Role_Interface,
    Agent_Role_Registry,
)
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.state import Blackboard_State
from agentforge.tools.registry import Tool_Registry
from agentforge.tracing.recorder import InMemory_Trace_Recorder


class _AlwaysReviseCritic(Agent_Role_Interface):
    """Drop-in Critic that always requires a revision to drive the revision cycle."""

    @property
    def role_id(self) -> str:
        return "critic"

    @property
    def instructions(self) -> str:
        return "always request a revision"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        state.critic_feedback = Critic_Feedback(
            revision_required=True, comments="revise"
        )
        return state


def _build_orchestrator(*, always_revise: bool, max_rounds: int, max_revisions: int):
    """Wire the real four roles (with the optional always-revise Critic) + a trace recorder."""
    agent = Agent_Orchestrator(Fallback_Provider(), Tool_Registry())
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(_AlwaysReviseCritic() if always_revise else Critic_Agent(agent))
    trace = InMemory_Trace_Recorder()
    orch = Multi_Agent_Orchestrator(
        registry,
        DEFAULT_PIPELINE,
        max_rounds=max_rounds,
        max_revisions=max_revisions,
        trace=trace,
    )
    return orch, trace


_VALID_ROLES = frozenset({"planner", "researcher", "writer", "critic"})


# Feature: agentforge-multi-agent, Property 15: Trace is complete, ordered by ordinal,
# and role-attributed.
@hyp_settings(max_examples=100, deadline=None)
@given(
    task=st.text(min_size=1, max_size=40),
    always_revise=st.booleans(),
    max_rounds=st.integers(min_value=1, max_value=4),
    max_revisions=st.integers(min_value=1, max_value=4),
)
def test_trace_is_complete_ordered_and_role_attributed(
    task, always_revise, max_rounds, max_revisions
):
    """Feature: agentforge-multi-agent, Property 15: Trace is complete, ordered by
    ordinal, and role-attributed — for any Multi_Agent_Run, the trace contains one entry
    per executed role step attributed to the producing ``role_id`` and associated with
    the run id, with contiguous ascending ordinals matching execution order, and
    ``get_trace`` returns the entries ordered by ordinal.

    Under an always-revise Critic with a small round bound the revision cycle produces
    additional role steps that must also appear in the trace with the correct role
    identifiers and monotonically increasing ordinals.

    Validates: Requirements 6.1, 6.3
    """
    orch, trace = _build_orchestrator(
        always_revise=always_revise,
        max_rounds=max_rounds,
        max_revisions=max_revisions,
    )
    state = orch.run(task)

    entries = trace.get_trace(state.run_id).entries

    # Every entry corresponds to an executed role step and is attributed to a real role.
    assert entries, "trace must not be empty"
    for entry in entries:
        assert entry.run_id == state.run_id
        assert entry.step_type.startswith("role:")
        role_id = entry.step_type.split(":", 1)[1]
        assert role_id in _VALID_ROLES
        assert entry.detail.get("role_id") == role_id  # Req 6.1 attribution

    # Ordinals are contiguous starting at 0 and match the entries' ascending order (Req 6.3).
    ordinals = [entry.ordinal for entry in entries]
    assert ordinals == list(range(len(entries)))

    # The first executed step is always the Planner — routing begins at pipeline[0].
    assert entries[0].step_type == "role:planner"

    # When at least one revision cycle occurred (always-revise Critic + a bound that
    # permits it), additional Writer/Critic role steps for the revision passes appear in
    # the trace with the correct role identifiers and monotonically increasing ordinals.
    role_steps = [entry.step_type.split(":", 1)[1] for entry in entries]
    critic_visits = role_steps.count("critic")
    writer_visits = role_steps.count("writer")

    # The Critic terminates each collaboration round, so its visit count equals the
    # completed round count in the trace (ordinals monotonically increase per role).
    assert critic_visits == state.round_count
    # A revision cycle always adds one Writer visit (per revision) and one Critic visit
    # (the follow-up review) on top of the initial pass.
    assert writer_visits == 1 + state.revision_count
    assert critic_visits == 1 + state.revision_count
    if state.revision_count > 0:
        # Revision cycle role steps were recorded -> more than the initial pair.
        assert writer_visits >= 2
        assert critic_visits >= 2
