"""Conversation_Store implementations: Postgres-backed and in-memory.

Both honor the same ``Conversation_Store`` contract (Req 8.1-8.5):

* :class:`PgConversation_Store` persists conversations and messages to the existing
  Postgres instance (tables from ``migrations/0003_create_conversations.sql``). It issues
  **synchronous** SQL through a psycopg-backed SQLAlchemy engine, mirroring
  ``db/store.py``'s ``DBDocumentStore`` so it can be driven off the event loop. ``append``
  computes the next ordinal as ``max(position)+1`` within the conversation and
  auto-creates the conversation when the id is unknown (Req 8.2, 8.4).
* :class:`InMemory_Conversation_Store` is the dependency-free, keyless double — mirroring
  the Phase 1-2 ``InMemoryDocumentStore`` pattern — used for keyless property testing and
  standalone runs.

Message ordinals are 0-based and contiguous, and ``history`` returns messages in
ascending ordinal order (Req 8.3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.base import Conversation_Store, Message
from agentforge.vectorstore.pgvector_store import to_sync_dsn


def _to_sqlalchemy_sync_dsn(database_url: str) -> str:
    """Return a synchronous SQLAlchemy DSN (psycopg driver) for the given URL."""
    libpq = to_sync_dsn(database_url)  # strips +asyncpg / +psycopg -> postgresql://
    return libpq.replace("postgresql://", "postgresql+psycopg://", 1)


class PgConversation_Store(Conversation_Store):
    """Synchronous Postgres-backed conversation/message persistence (Req 8.1-8.5)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def create(self) -> str:
        """Insert a conversation row with a generated UUID and return it (Req 8.1)."""
        conversation_id = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text("INSERT INTO conversations (id) VALUES (:id)"),
                {"id": conversation_id},
            )
        return conversation_id

    def append(self, conversation_id: str, role: str, content: str) -> Message:
        """Append a message with the next ordinal, auto-creating the conversation (Req 8.2, 8.4)."""
        with self._engine.begin() as conn:
            # Auto-create the conversation when the id is unknown (Req 8.4).
            conn.execute(
                text(
                    "INSERT INTO conversations (id) VALUES (:id) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": conversation_id},
            )
            # Next ordinal is max(position)+1 within the conversation (Req 8.2).
            next_position = conn.execute(
                text(
                    "SELECT COALESCE(MAX(position) + 1, 0) FROM messages "
                    "WHERE conversation_id = :cid"
                ),
                {"cid": conversation_id},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, position)
                    VALUES (:id, :cid, :role, :content, :position)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "cid": conversation_id,
                    "role": role,
                    "content": content,
                    "position": next_position,
                },
            )
        return Message(role=role, content=content, position=int(next_position))

    def history(self, conversation_id: str) -> list[Message]:
        """Return the conversation's messages in ascending ordinal order (Req 8.3)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT role, content, position FROM messages "
                    "WHERE conversation_id = :cid ORDER BY position ASC"
                ),
                {"cid": conversation_id},
            ).fetchall()
        return [Message(role=r[0], content=r[1], position=int(r[2])) for r in rows]

    def exists(self, conversation_id: str) -> bool:
        """Return whether the conversation row exists in Postgres."""
        with self._engine.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM conversations WHERE id = :cid"),
                {"cid": conversation_id},
            ).first()
        return found is not None


class InMemory_Conversation_Store(Conversation_Store):
    """Process-memory Conversation_Store — keyless double for tests/standalone runs."""

    def __init__(self) -> None:
        self._messages: dict[str, list[Message]] = {}

    def create(self) -> str:
        """Create an empty conversation with a unique id and return it (Req 8.1)."""
        conversation_id = str(uuid.uuid4())
        self._messages[conversation_id] = []
        return conversation_id

    def append(self, conversation_id: str, role: str, content: str) -> Message:
        """Append with the next ordinal, auto-creating unknown ids (Req 8.2, 8.4)."""
        messages = self._messages.setdefault(conversation_id, [])
        message = Message(role=role, content=content, position=len(messages))
        messages.append(message)
        return message

    def history(self, conversation_id: str) -> list[Message]:
        """Return messages in ascending ordinal order (Req 8.3)."""
        return sorted(self._messages.get(conversation_id, []), key=lambda m: m.position)

    def exists(self, conversation_id: str) -> bool:
        """Return whether the conversation has been created or has messages."""
        return conversation_id in self._messages
