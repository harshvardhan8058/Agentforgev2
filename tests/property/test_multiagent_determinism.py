"""Property test for auto-approve determinism (Task 8.3, Property 13).

Under the ``Fallback_Provider`` and ``Auto_Approve_Policy`` (no gate wired), two runs
with identical input must produce identical final output, an identical termination
reason, an identical number of revision cycles, and identical ordered sequences of
streamed event **types** and **role_ids**. Data content matches for fields that are pure
functions of the input (steps, findings content and citations, draft content, critic
comments, final answer + citations); the run identifier is generated per run and is not
compared.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.multiagent.orchestrator import Multi_Agent_Orchestrator
from agentforge.multiagent.roles.base import DEFAULT_PIPELINE, Agent_Role_Registry
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.streaming import (
    Multi_Agent_Streaming_Service,
)
from agentforge.tools.registry import Tool_Registry


def _build_service() -> Multi_Agent_Streaming_Service:
    """A freshly-wired streaming service using the real roles under Fallback + Auto."""
    agent = Agent_Orchestrator(Fallback_Provider(), Tool_Registry())
    registry = Agent_Role_Registry()
    registry.register(Planner_Agent(agent))
    registry.register(Researcher_Agent(agent))
    registry.register(Writer_Agent(agent))
    registry.register(Critic_Agent(agent))
    orch = Multi_Agent_Orchestrator(registry, DEFAULT_PIPELINE)
    return Multi_Agent_Streaming_Service(orch)


# Fields on each event payload that are pure functions of the input (independent of the
# per-run generated ``run_id``); these must match between two runs of identical input.
_DETERMINISTIC_KEYS = (
    "role_id",
    "steps",
    "findings",
    "content",
    "citations",
    "revision_required",
    "comments",
    "answer",
    "termination_reason",
)


def _projected_payload(data: dict) -> dict:
    """Project an event's data down to its deterministic (input-derived) keys only."""
    return {k: data[k] for k in _DETERMINISTIC_KEYS if k in data}


# Feature: agentforge-multi-agent, Property 13: Auto-approve determinism of final output
# and event sequence.
@hyp_settings(max_examples=100, deadline=None)
@given(task=st.text(min_size=1, max_size=40))
def test_auto_approve_determinism_of_output_and_event_sequence(task):
    """Feature: agentforge-multi-agent, Property 13: Auto-approve determinism of final
    output and event sequence — two Multi_Agent_Runs with identical input under the
    Fallback_Provider + Auto_Approve_Policy complete and produce identical Final_Output
    content, identical termination_reason, identical revision_count, and identical
    ordered sequences of streamed event types + role_ids (with identical per-event data
    for fields that are pure functions of the input).

    Validates: Requirements 1.5, 3.7, 5.6, 7.9, 12.1
    """
    events_a = list(_build_service().run_stream(task))
    events_b = list(_build_service().run_stream(task))

    # Same length and identical ordered sequence of event types.
    assert len(events_a) == len(events_b)
    assert [e.type for e in events_a] == [e.type for e in events_b]

    # Sequences are 0..n-1 in both runs (Req 7.4).
    assert [e.sequence for e in events_a] == list(range(len(events_a)))
    assert [e.sequence for e in events_b] == list(range(len(events_b)))

    # Identical role_id on every corresponding event (agent-produced or otherwise).
    for a, b in zip(events_a, events_b):
        assert a.data.get("role_id") == b.data.get("role_id")

    # Per-event pure-function fields match between runs (steps, findings, citations,
    # draft content, critic comments, final answer + citations, termination_reason).
    for a, b in zip(events_a, events_b):
        assert _projected_payload(a.data) == _projected_payload(b.data)

    # Same terminal event (Req 7.6), same termination reason, same final answer.
    terminal_a = events_a[-1]
    terminal_b = events_b[-1]
    assert terminal_a.type is terminal_b.type
    assert terminal_a.data.get("termination_reason") == terminal_b.data.get(
        "termination_reason"
    )
    assert terminal_a.data.get("answer") == terminal_b.data.get("answer")
    assert terminal_a.data.get("citations") == terminal_b.data.get("citations")
