"""DBDocumentStore: DB-backed DocumentStore adapter (production).

Bridges the Ingestion_Service, Retriever, and documents router to the relational
``documents`` / ``chunks`` tables created by the migrations — the same tables the async
``db/repositories.py`` module targets. It issues **synchronous** SQL through a
psycopg-backed SQLAlchemy engine so it can be driven from the Ingestion_Service and
Retriever, which run in a worker thread off the event loop. The app's async engine is
reserved for health checks and migrations.

``persist`` writes the document row and all chunk rows inside a single transaction, so a
failure leaves nothing behind — reinforcing the atomic-ingestion guarantee (Req 7.3-7.6).
Deleting a document cascades to its chunks (and embeddings) via the schema's
``ON DELETE CASCADE`` foreign keys.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.models.domain import Chunk, Document
from agentforge.storage.base import DocumentListing
from agentforge.vectorstore.pgvector_store import to_sync_dsn


def _to_sqlalchemy_sync_dsn(database_url: str) -> str:
    """Return a synchronous SQLAlchemy DSN (psycopg driver) for the given URL."""
    libpq = to_sync_dsn(database_url)  # strips +asyncpg / +psycopg -> postgresql://
    return libpq.replace("postgresql://", "postgresql+psycopg://", 1)


class DBDocumentStore:
    """Synchronous relational document/chunk store implementing the DocumentStore port."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def persist(self, document: Document, chunks: list[Chunk]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO documents
                        (id, filename, content_type, size_bytes, status, created_at)
                    VALUES (:id, :filename, :content_type, :size_bytes, :status, :created_at)
                    """
                ),
                {
                    "id": document.id,
                    "filename": document.filename,
                    "content_type": document.content_type,
                    "size_bytes": document.size_bytes,
                    "status": document.status,
                    "created_at": document.created_at,
                },
            )
            for chunk in chunks:
                conn.execute(
                    text(
                        """
                        INSERT INTO chunks (id, document_id, idx, content, overlap_prev)
                        VALUES (:id, :document_id, :idx, :content, :overlap_prev)
                        """
                    ),
                    {
                        "id": chunk.id,
                        "document_id": chunk.document_id,
                        "idx": chunk.index,
                        "content": chunk.content,
                        "overlap_prev": chunk.overlap_prev,
                    },
                )

    def get_chunk_texts(self, chunk_ids: list[str]) -> dict[str, str]:
        if not chunk_ids:
            return {}
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, content FROM chunks WHERE id = ANY(:ids)"),
                {"ids": list(chunk_ids)},
            ).fetchall()
        return {str(r[0]): r[1] for r in rows}

    def list_documents(self) -> list[DocumentListing]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT d.id, d.filename, d.content_type, d.size_bytes, d.status,
                           d.created_at, count(c.id) AS chunk_count
                    FROM documents d
                    LEFT JOIN chunks c ON c.document_id = d.id
                    GROUP BY d.id
                    ORDER BY d.created_at DESC
                    """
                )
            ).fetchall()
        return [
            DocumentListing(
                document_id=str(r[0]),
                filename=r[1],
                content_type=r[2],
                size_bytes=int(r[3]),
                status=r[4],
                chunk_count=int(r[6]),
                created_at=r[5].isoformat() if r[5] is not None else "",
            )
            for r in rows
        ]

    def get_document(self, document_id: str) -> Document | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, filename, content_type, size_bytes, status, created_at
                    FROM documents WHERE id = :id
                    """
                ),
                {"id": document_id},
            ).one_or_none()
        if row is None:
            return None
        return Document(
            id=str(row[0]),
            filename=row[1],
            content_type=row[2],
            size_bytes=int(row[3]),
            status=row[4],
            created_at=row[5],
        )

    def delete_document(self, document_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM documents WHERE id = :id"), {"id": document_id}
            )
