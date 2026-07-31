"""Conversation_Store interface, Conversation, and Message (Pluggable Seam: conversation).

The ``Conversation_Store`` creates Conversations with unique ids, appends Messages with
contiguous ascending ordinal positions (auto-creating an unknown conversation id), and
returns history in ascending ordinal order (Req 8.1-8.4). ``Conversation`` and
``Message`` are plain framework-agnostic dataclasses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

# Longest preview retained for a conversation summary. Enough to recognise a thread
# without shipping whole message bodies in a list response.
PREVIEW_MAX_CHARS = 160


@dataclass
class Message:
    """A single entry in a Conversation."""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    position: int  # 0-based ordinal position within the conversation (ascending)


@dataclass
class Conversation_Summary:
    """A row in the org's conversation list.

    Carries a ``preview`` — the first message's opening characters — because a
    conversation is otherwise identified only by a generated UUID, which tells an
    operator nothing about which thread it is. Message bodies are excluded so listing
    stays cheap regardless of thread length.
    """

    id: str
    created_at: datetime
    message_count: int
    preview: str | None = None


@dataclass
class Conversation:
    """A persistent, ordered sequence of Messages identified by ``id``."""

    id: str
    messages: list[Message] = field(default_factory=list)


class Conversation_Store(ABC):
    """Abstract contract for persisting Conversations and Messages.

    Every method is tenant-scoped by a leading ``org_id`` so a Conversation (and its
    Messages, via the parent FK) can only be read or mutated within its owning
    organization; cross-tenant access yields ``None`` / empty / a no-op so the router
    surfaces ``404`` (Req 4.2, 4.3, 4.6).
    """

    @abstractmethod
    def create(self, org_id: UUID) -> str:
        """Create a Conversation owned by ``org_id`` with a unique id (Req 8.1, 4.4)."""
        raise NotImplementedError

    @abstractmethod
    def append(self, org_id: UUID, conversation_id: str, role: str, content: str) -> Message:
        """Append a Message with the next ordinal; auto-create unknown id (Req 8.2, 8.4)."""
        raise NotImplementedError

    @abstractmethod
    def history(self, org_id: UUID, conversation_id: str) -> list[Message]:
        """Return ``org_id``'s conversation Messages in ascending ordinal order (Req 8.3)."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, org_id: UUID, conversation_id: str) -> bool:
        """Return whether a Conversation with ``conversation_id`` exists in ``org_id``.

        Lets the transport layer distinguish an unknown/cross-tenant conversation
        (``404``) from a known-but-empty one when serving history.
        """
        raise NotImplementedError

    @abstractmethod
    def list_conversations(
        self, org_id: UUID, *, limit: int = 50
    ) -> list[Conversation_Summary]:
        """Return ``org_id``'s conversations, most recently created first.

        Without this the store could only create and read a conversation by id, so the
        console could start threads but never show which ones existed — the id was
        returned once and then unrecoverable. ``limit`` bounds the response because the
        list grows without end.
        """
        raise NotImplementedError
