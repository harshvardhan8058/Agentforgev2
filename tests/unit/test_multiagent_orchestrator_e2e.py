"""Keyless end-to-end checks for the Multi_Agent_Orchestrator with the real roles.

These exercise the Task 6 checkpoint: the orchestrator completes a run end-to-end under
the deterministic ``Fallback_Provider`` with the **real four roles** (approve Critic ->
completed), and terminates at the round and revision bounds when an always-revise Critic
is injected in place of the default (also demonstrating the add/replace-a-role seam).

They run fully keyless: each role reuses a single ``Agent_Orchestrator`` built on the
``Fallback_Provider`` with an empty ``Tool_Registry`` (no RAG grounding needed here), so
the whole collaboration is deterministic and network-free.
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.multiagent.models import Critic_Feedback, Termination_Reason
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


def _agent_orchestrator() -> Agent_Orchestrator:
    """A keyless single-agent orchestrator reused by every role."""
    return Agent_Orchestrator(Fallback_Provider(), Tool_Registry())


class _AlwaysReviseCritic(Agent_Role_Interface):
    """A Critic that always requests a revision (drop-in replacement for the default)."""

    @property
    def role_id(self) -> str:
        return "critic"

    @property
    def instructions(self) -> str:
        return "always request a revision"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        state.critic_feedback = Critic_Feedback(revision_required=True, comments="revise")
        return state


def _registry(critic: Agent_Role_Interface) -> Agent_Role_Registry:
    agent = _agent_orchestrator()
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(critic)
    return registry


def test_real_roles_complete_end_to_end():
    """Real four roles + approve Critic under Fallback -> completed (Req 2.3, 12.1)."""
    agent = _agent_orchestrator()
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(Critic_Agent(agent))  # default fallback Critic approves
    trace = InMemory_Trace_Recorder()

    orchestrator = Multi_Agent_Orchestrator(registry, DEFAULT_PIPELINE, trace=trace)
    state = orchestrator.run("Explain caching strategies")

    assert state.termination_reason is Termination_Reason.COMPLETED
    assert state.round_count == 1
    assert state.revision_count == 0
    # The approved Draft is emitted as the Final_Output.
    assert state.final_output is not None
    assert state.final_output.content == state.draft.content
    # Every role step is attributed, in pipeline order.
    steps = [e.step_type for e in trace.get_trace(state.run_id).entries]
    assert steps == ["role:planner", "role:researcher", "role:writer", "role:critic"]


def test_real_roles_terminate_at_round_bound():
    """Always-revise Critic + small Max_Rounds -> max-rounds-reached (Req 2.4)."""
    orchestrator = Multi_Agent_Orchestrator(
        _registry(_AlwaysReviseCritic()),
        DEFAULT_PIPELINE,
        max_rounds=3,
        max_revisions=20,  # ceiling: never intervenes, so the round bound is forced
    )
    state = orchestrator.run("Explain caching strategies")

    assert state.termination_reason is Termination_Reason.MAX_ROUNDS_REACHED
    assert state.round_count == 3  # never exceeds Max_Rounds
    assert state.final_output is not None
    assert state.final_output.content == state.draft.content


def test_real_roles_terminate_at_revision_bound():
    """Always-revise Critic + small Max_Revisions -> max-revisions-reached (Req 3.4)."""
    orchestrator = Multi_Agent_Orchestrator(
        _registry(_AlwaysReviseCritic()),
        DEFAULT_PIPELINE,
        max_rounds=20,  # large enough not to intervene
        max_revisions=2,
    )
    state = orchestrator.run("Explain caching strategies")

    assert state.termination_reason is Termination_Reason.MAX_REVISIONS_REACHED
    assert state.revision_count == 2  # never exceeds Max_Revisions
    assert state.final_output is not None
    assert state.final_output.content == state.draft.content
