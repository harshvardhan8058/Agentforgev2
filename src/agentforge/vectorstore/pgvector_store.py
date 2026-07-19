"""Pgvector_Store: production Vector_Store backed by PostgreSQL + pgvector.

Used in the ``production`` profile (Req 10.3). Embeddings live in the
``chunk_embeddings`` table, each row associating an embedding with its originating
chunk id and document id (Req 10.4). Queries use the pgvector cosine-distance operator
``<=>`` with ``ORDER BY distance ASC LIMIT k`` — ascending distance is descending
similarity — so the ``query`` bound/ordering post-conditions hold: at most ``k`` matches
and all stored matches when fewer than ``k`` exist (Req 10.5, 10.6).

The store issues **synchronous** SQL through psycopg so it can be driven from the
Ingestion_Service and Retriever (which run in a worker thread off the event loop). The
async engine used elsewhere in the app is reserved for health checks and migrations.
"""

from __future__ import annotations

from uuid import UUID

from agentforge.vectorstore.base import StoredMatch, Vector_Store


def to_sync_dsn(database_url: str) -> str:
    """Normalize a SQLAlchemy-style DSN into a libpq DSN psycopg can consume.

    ``postgresql+asyncpg://...`` / ``postgresql+psycopg://...`` -> ``postgresql://...``
    """
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix) :]
    return database_url


class Pgvector_Store(Vector_Store):
    """PostgreSQL + pgvector implementation of the Vector_Store interface."""

    def __init__(self, dim: int, dsn: str) -> None:
        self._dim = dim
        self._dsn = to_sync_dsn(dsn)

    def _connect(self):
        """Open a psycopg connection with the pgvector type registered."""
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(self._dsn)
        register_vector(conn)
        return conn

    def upsert(self, chunk_id: str, document_id: str, embedding: list[float]) -> None:
        """Persist an embedding associated with its chunk and document (Req 10.4)."""
        import numpy as np

        vector = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chunk_embeddings (chunk_id, document_id, embedding)
                VALUES (%s, %s, %s)
                ON CONFLICT (chunk_id)
                DO UPDATE SET document_id = EXCLUDED.document_id,
                              embedding = EXCLUDED.embedding
                """,
                (chunk_id, document_id, vector),
            )
            conn.commit()

    def query(self, embedding: list[float], k: int) -> list[StoredMatch]:
        """Return at most ``min(k, count)`` matches ordered by descending similarity."""
        import numpy as np

        n = min(k, self.count())
        if n <= 0:
            return []

        vector = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, document_id, 1 - (embedding <=> %s) AS score
                FROM chunk_embeddings
                ORDER BY embedding <=> %s ASC
                LIMIT %s
                """,
                (vector, vector, n),
            ).fetchall()

        return [
            StoredMatch(chunk_id=str(r[0]), document_id=str(r[1]), score=float(r[2]))
            for r in rows
        ]

    def query_for_org(
        self, embedding: list[float], k: int, org_id: UUID
    ) -> list[StoredMatch]:
        """Return tenant-owned matches, applying the organization filter before LIMIT."""
        if k <= 0:
            return []

        import numpy as np

        vector = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH tenant_embeddings AS MATERIALIZED (
                    SELECT ce.chunk_id, ce.document_id, ce.embedding
                    FROM chunk_embeddings ce
                    JOIN documents d ON d.id = ce.document_id
                    WHERE d.org_id = %s
                )
                SELECT chunk_id,
                       document_id,
                       1 - (embedding <=> %s) AS score
                FROM tenant_embeddings
                ORDER BY embedding <=> %s ASC
                LIMIT %s
                """,
                (str(org_id), vector, vector, k),
            ).fetchall()

        return [
            StoredMatch(chunk_id=str(r[0]), document_id=str(r[1]), score=float(r[2]))
            for r in rows
        ]

    def delete_document(self, document_id: str) -> None:
        """Remove all embeddings belonging to a document."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM chunk_embeddings WHERE document_id = %s", (document_id,)
            )
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT count(*) FROM chunk_embeddings").fetchone()
        return int(row[0]) if row else 0
