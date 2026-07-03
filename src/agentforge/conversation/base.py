"""Conversation_Store interface, Conversation, and Message (Pluggable Seam: conversation).

The ``Conversation_Store`` creates Conversations with unique ids, appends Messages with
contiguous ascending ordinal positions (auto-creating an unknown conversation id), and
returns history in ascending ordinal order (Req 8.1-8.4). ``Conversation`` and
``Message`` are plain framework-agnostic dataclasses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    """A single entry in a Conversation."""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    position: int  # 0-based ordinal position within the conversation (ascending)


@dataclass
class Conversation:
    """A persistent, ordered sequence of Messages identified by ``id``."""

    id: str
    messages: list[Message] = field(default_factory=list)


class Conversation_Store(ABC):
    """Abstract contract for persisting Conversations and Messages."""

    @abstractmethod
    def create(self) -> str:
        """Create a Conversation with a unique id and return it (Req 8.1)."""
        raise NotImplementedError

    @abstractmethod
    def append(self, conversation_id: str, role: str, content: str) -> Message:
        """Append a Message with the next ordinal; auto-create unknown id (Req 8.2, 8.4)."""
        raise NotImplementedError

    @abstractmethod
    def history(self, conversation_id: str) -> list[Message]:
        """Return the Messages in ascending ordinal position order (Req 8.3)."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, conversation_id: str) -> bool:
        """Return whether a Conversation with ``conversation_id`` exists.

        Lets the transport layer distinguish an unknown conversation (``404``) from a
        known-but-empty one when serving history.
        """
        raise NotImplementedError
