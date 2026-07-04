"""Unit tests for Multi_Agent_Streaming_Service incremental emission (Task 8.4).

Two behaviors covered:

* Incremental emission (Req 7.2). Events are produced as the run progresses, not batched
  at the end. Driving the returned generator manually with :func:`next` must yield at
  least an ``agent_started`` and a ``plan`` event **before** a terminal ``completion``
  is reached.
* ``approval_required`` on pause (Req 7.5). When a :class:`Human_Approval_Gate` under
  :class:`Human_In_The_Loop_Policy` is wired, the service consults the gate at the
  ``after_plan`` checkpoint, detects the paused ``state.awaiting_approval`` flag, and
  emits an ``approval_required`` event as the last (non-terminal) event of the stream.
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.multiagent.approval import (
    Checkpoint_Store,
    Human_Approval_Gate,
    Human_In_The_Loop_Policy,
)
from agentforge.multiagent.orchestrator import Multi_Agent_Orchestrator
from agentforge.multiagent.roles.base import DEFAULT_PIPELINE, Agent_Role_Registry
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.streaming import (
    MA_TERMINAL_EVENT_TYPES,
    MultiAgentStreamEventType,
    Multi_Agent_Streaming_Service,
)
from agentforge.tools.registry import Tool_Registry


def _real_orchestrator() -> Multi_Agent_Orchestrator:
    """Keyless Multi_Agent_Orchestrator wired with the four real roles."""
    agent = Agent_Orchestrator(Fallback_Provider(), Tool_Registry())
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(Critic_Agent(agent))
    return Multi_Agent_Orchestrator(registry, DEFAULT_PIPELINE)


def test_events_are_emitted_incrementally_before_completion() -> None:
    """At least AGENT_STARTED and PLAN must be yielded before COMPLETION is reached (Req 7.2)."""
    service = Multi_Agent_Streaming_Service(_real_orchestrator())
    generator = service.run_stream("Explain caching strategies")

    first = next(generator)
    second = next(generator)

    # First event is the initial Planner ``agent_started`` (Req 7.1).
    assert first.type is MultiAgentStreamEventType.AGENT_STARTED
    assert first.data.get("role_id") == "planner"
    assert first.sequence == 0

    # The next event is the Planner's ``plan`` contribution — neither of these two is a
    # terminal event, so events are being produced as the run progresses, not batched at
    # the end (Req 7.2).
    assert second.type is MultiAgentStreamEventType.PLAN
    assert second.data.get("role_id") == "planner"
    assert not first.is_terminal
    assert not second.is_terminal

    # Drain the rest of the stream to confirm it eventually terminates with exactly one
    # terminal event, further down the sequence.
    remaining = list(generator)
    terminals = [e for e in remaining if e.type in MA_TERMINAL_EVENT_TYPES]
    assert len(terminals) == 1
    assert terminals[0] is remaining[-1]
    assert terminals[0].type is MultiAgentStreamEventType.COMPLETION


def test_approval_required_is_emitted_when_gate_pauses() -> None:
    """Wiring a Human_In_The_Loop gate makes the stream pause with APPROVAL_REQUIRED (Req 7.5)."""
    gate = Human_Approval_Gate(
        policy=Human_In_The_Loop_Policy(), store=Checkpoint_Store()
    )
    service = Multi_Agent_Streaming_Service(_real_orchestrator(), gate=gate)

    events = list(service.run_stream("Explain caching strategies"))

    # The stream stops after the Planner's ``plan`` event with an ``approval_required``
    # signal identifying the paused run and the pending checkpoint.
    types = [e.type for e in events]
    assert types == [
        MultiAgentStreamEventType.AGENT_STARTED,
        MultiAgentStreamEventType.PLAN,
        MultiAgentStreamEventType.APPROVAL_REQUIRED,
    ]
    pause = events[-1]
    assert pause.data.get("checkpoint") == "after_plan"
    assert isinstance(pause.data.get("run_id"), str) and pause.data["run_id"]

    # ``approval_required`` is NOT a terminal event — the stream simply ends here so the
    # run can be resumed on a separate request.
    assert not pause.is_terminal
    assert MultiAgentStreamEventType.COMPLETION not in types
    assert MultiAgentStreamEventType.ERROR not in types
