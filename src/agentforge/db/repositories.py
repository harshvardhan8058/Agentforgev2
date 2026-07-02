"""Repositories for document and chunk persistence.

These persist ``Document`` and ``Chunk`` domain objects into the relational
``documents`` and ``chunks`` tables created by the migrations. Each chunk row is
associated with its originating ``document_id`` (Req 7.3). SQL is issued via the
SQLAlchemy Core text API so the repositories stay independent of any ORM mapping.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.models.domain import Chunk, Document

_INSERT_DOCUMENT = text(
    """
    INSERT INTO documents (id, filename, content_type, size_bytes, status, created_at)
    VALUES (:id, :filename, :content_type, :size_bytes, :status, :created_at)
    """
)

_INSERT_CHUNK = text(
    """
    INSERT INTO chunks (id, document_id, idx, content, overlap_prev)
    VALUES (:id, :document_id, :idx, :content, :overlap_prev)
    """
)

_SELECT_DOCUMENT = text(
    """
    SELECT id, filename, content_type, size_bytes, status, created_at
    FROM documents WHERE id = :id
    """
)

_COUNT_CHUNKS = text("SELECT count(*) FROM chunks WHERE document_id = :document_id")

_DELETE_DOCUMENT = text("DELETE FROM documents WHERE id = :id")


class DocumentRepository:
    """Persistence for Document records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: Document) -> None:
        await self._session.execute(
            _INSERT_DOCUMENT,
            {
                "id": document.id,
                "filename": document.filename,
                "content_type": document.content_type,
                "size_bytes": document.size_bytes,
                "status": document.status,
                "created_at": document.created_at,
            },
        )

    async def get(self, document_id: str) -> Document | None:
        row = (
            await self._session.execute(_SELECT_DOCUMENT, {"id": document_id})
        ).one_or_none()
        if row is None:
            return None
        return Document(
            id=str(row.id),
            filename=row.filename,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            status=row.status,
            created_at=row.created_at,
        )

    async def delete(self, document_id: str) -> None:
        # chunks / embeddings cascade via ON DELETE CASCADE in the schema.
        await self._session.execute(_DELETE_DOCUMENT, {"id": document_id})


class ChunkRepository:
    """Persistence for Chunk records, associated with their document."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, chunks: list[Chunk]) -> None:
        """Persist chunks, each carrying its originating document_id (Req 7.3)."""
        for chunk in chunks:
            await self._session.execute(
                _INSERT_CHUNK,
                {
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "idx": chunk.index,
                    "content": chunk.content,
                    "overlap_prev": chunk.overlap_prev,
                },
            )

    async def count_for_document(self, document_id: str) -> int:
        result = await self._session.execute(
            _COUNT_CHUNKS, {"document_id": document_id}
        )
        return int(result.scalar_one())
