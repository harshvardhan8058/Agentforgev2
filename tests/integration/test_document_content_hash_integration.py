"""Integration test: document content hashing against real Postgres (migration 0012).

Requires a live PostgreSQL instance. Excluded from the default keyless lane; run with
``pytest -m integration`` while the Docker stack is up.

The duplicate check that stops the same file being ingested repeatedly relies on three
pieces of raw SQL added with migration 0012 — the ``content_hash`` column on ``INSERT``,
the column on ``SELECT``, and the ``find_by_content_hash`` lookup. The in-memory store
satisfies the same contract but cannot validate any of them: a missing column, a typo, or
a mis-shaped aggregate would surface only in production, where the symptom is silently
duplicated documents rather than an error.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.db.store import DBDocumentStore
from agentforge.models.domain import Chunk, Document

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge",
    )


@pytest.fixture
async def engine():
    eng = create_engine(_dsn())
    await run_migrations(eng, EMBEDDING_DIMENSION)
    yield eng
    await eng.dispose()


async def _make_org(engine, name: str) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": str(org_id), "name": name},
        )
    return org_id


def _document(content_hash: str | None, *, created_at: datetime | None = None) -> Document:
    return Document(
        id=str(uuid.uuid4()),
        filename="policy.md",
        content_type="text/markdown",
        size_bytes=42,
        status="ingested",
        created_at=created_at or datetime.now(timezone.utc),
        content_hash=content_hash,
    )


def _chunks(document_id: str, count: int) -> list[Chunk]:
    return [
        Chunk(id=str(uuid.uuid4()), document_id=document_id, index=i, content=f"c{i}")
        for i in range(count)
    ]


async def test_content_hash_round_trips_through_postgres(engine):
    """The column added by 0012 is written on insert and read back on select."""
    org_id = await _make_org(engine, "Hash Org")
    store = DBDocumentStore(_dsn())

    document = _document("a" * 64)
    store.persist(org_id, document, _chunks(document.id, 2))

    loaded = store.get_document(org_id, document.id)

    assert loaded is not None
    assert loaded.content_hash == "a" * 64


async def test_find_by_content_hash_locates_the_existing_document(engine):
    org_id = await _make_org(engine, "Find Org")
    store = DBDocumentStore(_dsn())

    document = _document("b" * 64)
    store.persist(org_id, document, _chunks(document.id, 3))

    found = store.find_by_content_hash(org_id, "b" * 64)

    assert found is not None
    assert found.document_id == document.id
    assert found.filename == "policy.md"
    # The chunk count comes from a LEFT JOIN + GROUP BY, so it is worth asserting.
    assert found.chunk_count == 3


async def test_an_unknown_hash_is_not_found(engine):
    org_id = await _make_org(engine, "Miss Org")
    store = DBDocumentStore(_dsn())

    assert store.find_by_content_hash(org_id, "c" * 64) is None


async def test_another_orgs_identical_file_is_not_a_duplicate(engine):
    """Each tenant's corpus is independent, so the lookup must be org-scoped."""
    mine = await _make_org(engine, "Mine Org")
    theirs = await _make_org(engine, "Theirs Org")
    store = DBDocumentStore(_dsn())

    document = _document("d" * 64)
    store.persist(theirs, document, _chunks(document.id, 1))

    assert store.find_by_content_hash(mine, "d" * 64) is None
    assert store.find_by_content_hash(theirs, "d" * 64) is not None


async def test_a_document_without_a_hash_is_never_matched(engine):
    """Rows predating 0012 carry NULL and cannot be backfilled, so they never match.

    Guards against SQL that would treat ``content_hash = NULL`` as a match or otherwise
    surface a legacy row as a duplicate of an unrelated upload.
    """
    org_id = await _make_org(engine, "Legacy Org")
    store = DBDocumentStore(_dsn())

    legacy = _document(None)
    store.persist(org_id, legacy, _chunks(legacy.id, 1))

    assert store.find_by_content_hash(org_id, "e" * 64) is None
    # And the round trip reports the absence honestly rather than inventing a value.
    loaded = store.get_document(org_id, legacy.id)
    assert loaded is not None
    assert loaded.content_hash is None


async def test_the_oldest_copy_is_returned_when_duplicates_predate_the_check(engine):
    """``ORDER BY created_at ASC`` makes the earliest copy canonical.

    Two rows can share a hash if they were written concurrently — the index is
    deliberately not unique, because failing the request would be worse than a rare
    duplicate row. The lookup must then be deterministic rather than arbitrary.
    """
    org_id = await _make_org(engine, "Oldest Org")
    store = DBDocumentStore(_dsn())

    now = datetime.now(timezone.utc)
    older = _document("f" * 64, created_at=now - timedelta(hours=1))
    newer = _document("f" * 64, created_at=now)
    store.persist(org_id, older, _chunks(older.id, 1))
    store.persist(org_id, newer, _chunks(newer.id, 1))

    found = store.find_by_content_hash(org_id, "f" * 64)

    assert found is not None
    assert found.document_id == older.id
