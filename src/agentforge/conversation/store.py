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
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.base import (
    PREVIEW_MAX_CHARS,
    Conversation_Store,
    Conversation_Summary,
    Message,
)
from agentforge.vectorstore.pgvector_store import to_sync_dsn


def _to_sqlalchemy_sync_dsn(database_url: str) -> str:
    """Return a synchronous SQLAlchemy DSN (psycopg driver) for the given URL."""
    libpq = to_sync_dsn(database_url)  # strips +asyncpg / +psycopg -> postgresql://
    return libpq.replace("postgresql://", "postgresql+psycopg://", 1)


def _preview(content: str | None) -> str | None:
    """Return a bounded, single-line preview of a message body, or ``None``.

    Collapses whitespace so a multi-line first message does not break the list layout,
    and truncates so listing does not ship whole message bodies.
    """
    if not content:
        return None
    collapsed = " ".join(content.split())
    if not collapsed:
        return None
    if len(collapsed) <= PREVIEW_MAX_CHARS:
        return collapsed
    return collapsed[:PREVIEW_MAX_CHARS].rstrip() + "…"


class PgConversation_Store(Conversation_Store):
    """Synchronous Postgres-backed conversation/message persistence (Req 8.1-8.5)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def create(self, org_id: UUID) -> str:
        """Insert a conversation row owned by ``org_id`` and return its id (Req 8.1, 4.4)."""
        conversation_id = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text("INSERT INTO conversations (id, org_id) VALUES (:id, :org_id)"),
                {"id": conversation_id, "org_id": str(org_id)},
            )
        return conversation_id

    def append(self, org_id: UUID, conversation_id: str, role: str, content: str) -> Message:
        """Append a message with the next ordinal, auto-creating the conversation (Req 8.2, 8.4)."""
        with self._engine.begin() as conn:
            # Auto-create the conversation (scoped to org_id) when the id is unknown
            # (Req 8.4). A conflicting id in ANOTHER org leaves the row untouched, so the
            # subsequent org-scoped message insert stays tenant-correct.
            conn.execute(
                text(
                    "INSERT INTO conversations (id, org_id) VALUES (:id, :org_id) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": conversation_id, "org_id": str(org_id)},
            )
            # Next ordinal is max(position)+1 within the org's conversation (Req 8.2).
            next_position = conn.execute(
                text(
                    "SELECT COALESCE(MAX(m.position) + 1, 0) FROM messages m "
                    "JOIN conversations c ON c.id = m.conversation_id "
                    "WHERE m.conversation_id = :cid AND c.org_id = :org_id"
                ),
                {"cid": conversation_id, "org_id": str(org_id)},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, position)
                    SELECT :id, :cid, :role, :content, :position
                    WHERE EXISTS (
                        SELECT 1 FROM conversations WHERE id = :cid AND org_id = :org_id
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "cid": conversation_id,
                    "role": role,
                    "content": content,
                    "position": next_position,
                    "org_id": str(org_id),
                },
            )
        return Message(role=role, content=content, position=int(next_position))

    def history(self, org_id: UUID, conversation_id: str) -> list[Message]:
        """Return the org's conversation messages in ascending ordinal order (Req 8.3)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT m.role, m.content, m.position FROM messages m "
                    "JOIN conversations c ON c.id = m.conversation_id "
                    "WHERE m.conversation_id = :cid AND c.org_id = :org_id "
                    "ORDER BY m.position ASC"
                ),
                {"cid": conversation_id, "org_id": str(org_id)},
            ).fetchall()
        return [Message(role=r[0], content=r[1], position=int(r[2])) for r in rows]

    def exists(self, org_id: UUID, conversation_id: str) -> bool:
        """Return whether the conversation row exists in ``org_id``."""
        with self._engine.connect() as conn:
            found = conn.execute(
                text(
                    "SELECT 1 FROM conversations WHERE id = :cid AND org_id = :org_id"
                ),
                {"cid": conversation_id, "org_id": str(org_id)},
            ).first()
        return found is not None

    def list_conversations(
        self, org_id: UUID, *, limit: int = 50
    ) -> list[Conversation_Summary]:
        """Return the org's conversations, newest first, with a first-message preview."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT c.id, c.created_at, count(m.id) AS message_count,
                           (SELECT m2.content
                              FROM messages m2
                             WHERE m2.conversation_id = c.id
                             ORDER BY m2.position ASC
                             LIMIT 1) AS preview
                    FROM conversations c
                    LEFT JOIN messages m ON m.conversation_id = c.id
                    WHERE c.org_id = :org_id
                    GROUP BY c.id, c.created_at
                    ORDER BY c.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"org_id": str(org_id), "limit": limit},
            ).fetchall()
        return [
            Conversation_Summary(
                id=str(r[0]),
                created_at=r[1],
                message_count=int(r[2]),
                preview=_preview(r[3]),
            )
            for r in rows
        ]


class InMemory_Conversation_Store(Conversation_Store):
    """Process-memory Conversation_Store — keyless double for tests/standalone runs."""

    def __init__(self) -> None:
        # Keyed by (org_id, conversation_id) so cross-tenant access is impossible.
        self._messages: dict[tuple[UUID, str], list[Message]] = {}
        # Creation times, so listing can order newest-first like the Postgres store
        # (whose `conversations.created_at` column provides the same ordering).
        self._created_at: dict[tuple[UUID, str], datetime] = {}

    def create(self, org_id: UUID) -> str:
        """Create an empty conversation owned by ``org_id`` with a unique id (Req 8.1, 4.4)."""
        conversation_id = str(uuid.uuid4())
        self._messages[(org_id, conversation_id)] = []
        self._created_at[(org_id, conversation_id)] = datetime.now(timezone.utc)
        return conversation_id

    def append(self, org_id: UUID, conversation_id: str, role: str, content: str) -> Message:
        """Append with the next ordinal, auto-creating unknown ids in ``org_id`` (Req 8.2, 8.4)."""
        messages = self._messages.setdefault((org_id, conversation_id), [])
        # An auto-created conversation (Req 8.4) still needs a creation time to be
        # listable; the first append is the earliest moment it is known to exist.
        self._created_at.setdefault(
            (org_id, conversation_id), datetime.now(timezone.utc)
        )
        message = Message(role=role, content=content, position=len(messages))
        messages.append(message)
        return message

    def history(self, org_id: UUID, conversation_id: str) -> list[Message]:
        """Return ``org_id``'s conversation messages in ascending ordinal order (Req 8.3)."""
        return sorted(
            self._messages.get((org_id, conversation_id), []), key=lambda m: m.position
        )

    def exists(self, org_id: UUID, conversation_id: str) -> bool:
        """Return whether the conversation exists in ``org_id``."""
        return (org_id, conversation_id) in self._messages

    def list_conversations(
        self, org_id: UUID, *, limit: int = 50
    ) -> list[Conversation_Summary]:
        """Return this org's conversations, newest first, with a first-message preview."""
        summaries: list[Conversation_Summary] = []
        for (owner, conversation_id), messages in self._messages.items():
            if owner != org_id:
                continue
            ordered = sorted(messages, key=lambda m: m.position)
            summaries.append(
                Conversation_Summary(
                    id=conversation_id,
                    created_at=self._created_at.get(
                        (owner, conversation_id), datetime.now(timezone.utc)
                    ),
                    message_count=len(ordered),
                    preview=_preview(ordered[0].content) if ordered else None,
                )
            )
        summaries.sort(key=lambda s: s.created_at, reverse=True)
        return summaries[:limit]
