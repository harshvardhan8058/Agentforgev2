"""Property-based test for agent-message persistence (Property 16, Task 10.3).

Exercises :class:`InMemory_Multi_Agent_Run_Store.append_message` for any sequence of
(role_id, content) appends to a Multi_Agent_Run and verifies that reading the messages
back returns exactly those messages in append order, with contiguous ascending ordinal
positions and their ``role_id`` and content preserved (Req 10.2).
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.enterprise.tenancy import NIL_ORG_ID as ORG
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store

# The four built-in roles plus a demonstration of the add-a-role seam. The store is
# role-agnostic: it must round-trip any string role_id.
_ROLE_IDS = ["planner", "researcher", "writer", "critic", "reviewer"]

_messages = st.lists(
    st.tuples(st.sampled_from(_ROLE_IDS), st.text(max_size=40)),
    min_size=1,
    max_size=25,
)


# Feature: agentforge-multi-agent, Property 16: Agent-message persistence round-trip
# with ordinal and role.
@hyp_settings(max_examples=100, deadline=None)
@given(messages=_messages)
def test_multiagent_message_persistence_roundtrip(messages):
    """Feature: agentforge-multi-agent, Property 16: For any sequence of agent messages
    appended during a Multi_Agent_Run, reading the run's messages back returns exactly
    those messages in append order, with contiguous ascending ordinal positions and
    their ``role_id`` and content preserved.

    Validates: Requirements 10.2
    """
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(ORG, conversation_id="conv-1", task="task")

    for expected_position, (role_id, content) in enumerate(messages):
        assigned = store.append_message(ORG, run.id, role_id, content)
        # ``append_message`` returns the ordinal it assigned, contiguous from 0.
        assert assigned == expected_position

    persisted = store.messages(ORG, run.id)

    # Exactly the appended messages, in append order, with contiguous ascending ordinals.
    assert [position for _, _, position in persisted] == list(range(len(messages)))
    assert [(role_id, content) for role_id, content, _ in persisted] == list(messages)
