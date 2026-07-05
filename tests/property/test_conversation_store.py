"""Property-based test for conversation append/history ordering (Property 16).

Runs keyless against the dependency-free ``InMemory_Conversation_Store`` — no database
required. The Postgres-backed store honors the same contract and is covered by a separate
``@pytest.mark.integration`` test.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.tenancy import NIL_ORG_ID as ORG

_ROLES = ["user", "assistant", "tool", "system"]

_messages = st.lists(
    st.tuples(st.sampled_from(_ROLES), st.text(max_size=40)),
    min_size=1,
    max_size=20,
)


# Feature: agentforge-agentic-layer, Property 16: Conversation append/history ordering
# with auto-create.
@hyp_settings(max_examples=100, deadline=None)
@given(messages=_messages, use_unknown_id=st.booleans())
def test_conversation_append_history_ordering_with_auto_create(messages, use_unknown_id):
    """Feature: agentforge-agentic-layer, Property 16: For any sequence of message appends
    to a conversation (including the first append to a previously unknown conversation id,
    which auto-creates the conversation), retrieving the history returns exactly those
    messages in append order, with contiguous ascending ordinal positions and their roles
    and contents preserved.

    Validates: Requirements 8.2, 8.3, 8.4
    """
    store = InMemory_Conversation_Store()
    # Either append to an explicitly-created conversation or to an unknown id that must be
    # auto-created on first append (Req 8.4).
    conversation_id = "unknown-conversation-id" if use_unknown_id else store.create(ORG)

    appended = []
    for position, (role, content) in enumerate(messages):
        message = store.append(ORG, conversation_id, role, content)
        # append returns the persisted message with its assigned ordinal.
        assert message.position == position
        appended.append(message)

    history = store.history(ORG, conversation_id)

    # Exactly the appended messages, in append order, with contiguous ascending ordinals.
    assert [m.position for m in history] == list(range(len(messages)))
    assert [(m.role, m.content) for m in history] == list(messages)
