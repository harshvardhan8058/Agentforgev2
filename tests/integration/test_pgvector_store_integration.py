"""Integration test: Pgvector_Store ordering and bounds (Req 10.3, 10.5, 10.6).

Requires a live PostgreSQL (pgvector) instance. Excluded from the default suite; run
with `pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async
DSN); the store converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.vectorstore.pgvector_store import Pgvector_Store

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge",
    )


def _unit_vector(index: int) -> list[float]:
    """A one-hot vector of the configured dimension."""
    vec = [0.0] * EMBEDDING_DIMENSION
    vec[index] = 1.0
    return vec


async def _seed_document_and_chunks(engine, document_id: str, chunk_ids: list[str]):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO documents (id, filename, content_type, size_bytes, status)
                VALUES (:id, 'doc.txt', 'text/plain', 10, 'ingested')
                """
            ),
            {"id": document_id},
        )
        for idx, chunk_id in enumerate(chunk_ids):
            await conn.execute(
                text(
                    """
                    INSERT INTO chunks (id, document_id, idx, content, overlap_prev)
                    VALUES (:id, :doc, :idx, :content, 0)
                    """
                ),
                {"id": chunk_id, "doc": document_id, "idx": idx, "content": f"c{idx}"},
            )


@pytest.fixture
async def engine():
    eng = create_engine(_dsn())
    await run_migrations(eng, EMBEDDING_DIMENSION)
    yield eng
    await eng.dispose()


async def test_pgvector_ordering_and_bounds(engine):
    document_id = str(uuid.uuid4())
    chunk_ids = [str(uuid.uuid4()) for _ in range(3)]
    await _seed_document_and_chunks(engine, document_id, chunk_ids)

    store = Pgvector_Store(dim=EMBEDDING_DIMENSION, dsn=_dsn())

    # chunk 0 == query direction (most similar); chunk 1 partially aligned; chunk 2
    # orthogonal (least similar).
    store.upsert(chunk_ids[0], document_id, _unit_vector(0))
    partial = [0.0] * EMBEDDING_DIMENSION
    partial[0] = 1.0
    partial[1] = 1.0
    store.upsert(chunk_ids[1], document_id, partial)
    store.upsert(chunk_ids[2], document_id, _unit_vector(1))

    query = _unit_vector(0)

    # Bound: request more than stored -> exactly stored_count returned (Req 10.6).
    all_matches = store.query(query, 10)
    assert len(all_matches) == 3

    # Ordering: descending similarity (Req 10.5). chunk 0 is the most similar.
    scores = [m.score for m in all_matches]
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
    assert all_matches[0].chunk_id == chunk_ids[0]
    assert all_matches[0].document_id == document_id

    # Bound: request fewer than stored -> exactly k returned (Req 10.5).
    top2 = store.query(query, 2)
    assert len(top2) == 2
    assert top2[0].chunk_id == chunk_ids[0]

    # Cleanup so re-runs stay deterministic.
    store.delete_document(document_id)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM documents WHERE id = :id"), {"id": document_id}
        )
