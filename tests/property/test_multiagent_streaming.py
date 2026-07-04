"""Property test for the Multi_Agent_Streaming_Service (Task 8.2, Property 14).

Every streamed multi-agent event must carry exactly one type, every agent-produced event
must identify its acting ``role_id``, events must strictly increase in ``sequence``
starting at 0, and every stream must end with exactly one terminal event
(``completion`` xor ``error`` — never both). This property exercises **both** paths: the
successful run over the real four roles under the ``Fallback_Provider`` (Req 12.1) and an
injected role that always raises, forcing the single-``error`` terminal path.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.llm.fallback_provider import Fallback_Provider
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
from agentforge.multiagent.streaming import (
    MA_TERMINAL_EVENT_TYPES,
    MultiAgentStreamEventType,
    Multi_Agent_Streaming_Service,
)
from agentforge.tools.registry import Tool_Registry

# Event types whose semantics require an identifying ``role_id`` (Req 7.3).
_AGENT_PRODUCED = frozenset(
    {
        MultiAgentStreamEventType.AGENT_STARTED,
        MultiAgentStreamEventType.PLAN,
        MultiAgentStreamEventType.RESEARCH,
        MultiAgentStreamEventType.DRAFT,
        MultiAgentStreamEventType.CRITIC_FEEDBACK,
    }
)


def _real_registry() -> Agent_Role_Registry:
    """Wire the real four roles onto a keyless ``Fallback_Provider`` orchestrator."""
    agent = Agent_Orchestrator(Fallback_Provider(), Tool_Registry())
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(Critic_Agent(agent))
    return registry


class _RaisingCritic(Agent_Role_Interface):
    """A Critic replacement that always raises, forcing the ERROR terminal path."""

    @property
    def role_id(self) -> str:
        return "critic"

    @property
    def instructions(self) -> str:
        return "always raise"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        raise RuntimeError("injected critic failure")


def _failing_registry() -> Agent_Role_Registry:
    """Real Planner/Researcher/Writer plus an always-raising Critic (Req 7.7)."""
    agent = Agent_Orchestrator(Fallback_Provider(), Tool_Registry())
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(_RaisingCritic())
    return registry


# Feature: agentforge-multi-agent, Property 14: Streaming emits exactly one terminal
# event, ordered and role-attributed.
@hyp_settings(max_examples=100, deadline=None)
@given(task=st.text(min_size=1, max_size=40), inject_error=st.booleans())
def test_streaming_emits_exactly_one_terminal_ordered_and_attributed(task, inject_error):
    """Feature: agentforge-multi-agent, Property 14: Streaming emits exactly one terminal
    event, ordered and role-attributed — every event carries exactly one type, every
    agent-produced event identifies its acting ``role_id``, sequences strictly increase
    from 0, and the stream ends with exactly one terminal event (``completion`` xor
    ``error`` — never both), for both the success and the injected-error paths.

    Validates: Requirements 7.3, 7.4, 7.6, 7.7, 7.8
    """
    registry = _failing_registry() if inject_error else _real_registry()
    orch = Multi_Agent_Orchestrator(registry, DEFAULT_PIPELINE)
    service = Multi_Agent_Streaming_Service(orch)

    events = list(service.run_stream(task))

    # Non-empty stream, and every event carries exactly one valid multi-agent type.
    assert events, "stream must not be empty"
    for event in events:
        assert isinstance(event.type, MultiAgentStreamEventType)

    # Sequences strictly increase from 0 (production order preserved end-to-end).
    assert [e.sequence for e in events] == list(range(len(events)))

    # Every agent-produced event identifies its acting ``role_id`` (Req 7.3).
    for event in events:
        if event.type in _AGENT_PRODUCED:
            role_id = event.data.get("role_id")
            assert isinstance(role_id, str) and role_id, (
                f"agent event {event.type.value} missing role_id"
            )

    # Exactly one terminal event, and it is the last event (Req 7.6, 7.7, 7.8).
    terminals = [e for e in events if e.type in MA_TERMINAL_EVENT_TYPES]
    assert len(terminals) == 1
    assert terminals[0] is events[-1]

    # Success vs error: the terminal type matches the injected condition — never both.
    types = {e.type for e in events}
    if inject_error:
        assert events[-1].type is MultiAgentStreamEventType.ERROR
        assert MultiAgentStreamEventType.COMPLETION not in types
        # The initial agent_started + plan/research/draft events precede the error.
        assert events[0].type is MultiAgentStreamEventType.AGENT_STARTED
    else:
        assert events[-1].type is MultiAgentStreamEventType.COMPLETION
        assert MultiAgentStreamEventType.ERROR not in types
        # Completion payload includes the run identifier and the final answer/citations.
        payload = events[-1].data
        assert "run_id" in payload and payload["run_id"]
        assert payload["termination_reason"] == "completed"
        assert "answer" in payload and "citations" in payload
