"""Unit tests for the Conversation_Store contract (Req 8.1, 8.5).

Exercise conversation-id uniqueness and the final-assistant-message persistence pattern
against the keyless ``InMemory_Conversation_Store``.
"""

from __future__ import annotations

from agentforge.conversation.store import InMemory_Conversation_Store


def test_create_yields_unique_conversation_ids():
    """``create`` returns a distinct id each time (Req 8.1)."""
    store = InMemory_Conversation_Store()
    ids = {store.create() for _ in range(50)}
    assert len(ids) == 50


def test_final_assistant_message_persistence_pattern():
    """A completed run appends the final assistant message after the user turn (Req 8.5)."""
    store = InMemory_Conversation_Store()
    conversation_id = store.create()

    store.append(conversation_id, "user", "what is agentforge?")
    final = store.append(conversation_id, "assistant", "AgentForge is a platform.")

    history = store.history(conversation_id)
    assert [m.role for m in history] == ["user", "assistant"]
    # The final assistant message is persisted last with the highest ordinal.
    assert history[-1] is not None
    assert history[-1].role == "assistant"
    assert history[-1].content == "AgentForge is a platform."
    assert final.position == 1


def test_append_auto_creates_unknown_conversation():
    """Appending to an unknown id auto-creates the conversation (Req 8.4)."""
    store = InMemory_Conversation_Store()
    message = store.append("brand-new-id", "user", "hello")
    assert message.position == 0
    assert [m.content for m in store.history("brand-new-id")] == ["hello"]
