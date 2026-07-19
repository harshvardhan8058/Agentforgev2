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


async def _seed_document_and_chunks(
    engine, org_id: str, document_id: str, chunk_ids: list[str]
):
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": org_id, "name": f"pgvector-test-{org_id}"},
        )
        await conn.execute(
            text(
                """
                INSERT INTO documents
                    (id, org_id, filename, content_type, size_bytes, status)
                VALUES (:id, :org_id, 'doc.txt', 'text/plain', 10, 'ingested')
                """
            ),
            {"id": document_id, "org_id": org_id},
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
    org_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    chunk_ids = [str(uuid.uuid4()) for _ in range(3)]
    await _seed_document_and_chunks(engine, org_id, document_id, chunk_ids)

    store = Pgvector_Store(dim=EMBEDDING_DIMENSION, dsn=_dsn())

    try:
        # chunk 0 == query direction (most similar); chunk 1 partially aligned;
        # chunk 2 orthogonal (least similar).
        store.upsert(chunk_ids[0], document_id, _unit_vector(0))
        partial = [0.0] * EMBEDDING_DIMENSION
        partial[0] = 1.0
        partial[1] = 1.0
        store.upsert(chunk_ids[1], document_id, partial)
        store.upsert(chunk_ids[2], document_id, _unit_vector(1))

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT count(*) FROM chunk_embeddings"))
            stored_count = result.scalar_one()

        query = _unit_vector(0)

        # Bound: requesting more than stored returns exactly the stored count.
        all_matches = store.query(query, stored_count + 10)
        assert len(all_matches) == stored_count
        assert all(
            all_matches[i].score >= all_matches[i + 1].score
            for i in range(len(all_matches) - 1)
        )

        # Verify this fixture's rows independently of any pre-existing shared rows.
        seeded_matches = [m for m in all_matches if m.chunk_id in chunk_ids]
        assert len(seeded_matches) == 3
        assert seeded_matches[0].chunk_id == chunk_ids[0]
        assert seeded_matches[0].document_id == document_id
        seeded_scores = [m.score for m in seeded_matches]
        assert all(
            seeded_scores[i] >= seeded_scores[i + 1]
            for i in range(len(seeded_scores) - 1)
        )

        # Bound: requesting fewer than stored returns exactly k globally ordered rows.
        top2 = store.query(query, 2)
        assert len(top2) == 2
        assert top2[0].score >= top2[1].score
    finally:
        # The organization cascade removes the document, chunks, and embeddings.
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM organizations WHERE id = :id"), {"id": org_id}
            )



async def test_pgvector_tenant_scope_filters_before_top_k(engine):
    org_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())
    document_a = str(uuid.uuid4())
    document_b = str(uuid.uuid4())
    chunk_a = str(uuid.uuid4())
    chunk_b = str(uuid.uuid4())

    try:
        await _seed_document_and_chunks(engine, org_a, document_a, [chunk_a])
        await _seed_document_and_chunks(engine, org_b, document_b, [chunk_b])

        store = Pgvector_Store(dim=EMBEDDING_DIMENSION, dsn=_dsn())
        store.upsert(chunk_a, document_a, _unit_vector(0))
        store.upsert(chunk_b, document_b, _unit_vector(1))

        # Filtering must happen before LIMIT so org B receives its own result even
        # though org A's vector is more similar to the query.
        matches = store.query_for_org(_unit_vector(0), 1, uuid.UUID(org_b))
        assert [(m.chunk_id, m.document_id) for m in matches] == [
            (chunk_b, document_b)
        ]
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM organizations WHERE id = ANY(:ids)"),
                {"ids": [org_a, org_b]},
            )
