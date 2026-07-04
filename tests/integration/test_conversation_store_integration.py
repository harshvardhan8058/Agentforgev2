"""Integration test: PgConversation_Store append/history + auto-create (Req 8.1-8.4).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the store converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.conversation.store import PgConversation_Store
from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations

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


async def test_pg_conversation_append_history_and_auto_create(engine):
    store = PgConversation_Store(_dsn())

    # A real organization is required for the org_id FK on conversations (Req 8.2).
    org_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'Conv Org')"),
            {"id": org_id},
        )

    # Unique ids from create (Req 8.1).
    id_a = store.create(org_id)
    id_b = store.create(org_id)
    assert id_a != id_b

    store.append(org_id, id_a, "user", "hello")
    store.append(org_id, id_a, "assistant", "hi there")
    history = store.history(org_id, id_a)
    assert [(m.role, m.content, m.position) for m in history] == [
        ("user", "hello", 0),
        ("assistant", "hi there", 1),
    ]

    # Auto-create on unknown id (Req 8.4).
    unknown = str(uuid.uuid4())
    msg = store.append(org_id, unknown, "user", "auto-created")
    assert msg.position == 0
    assert [m.content for m in store.history(org_id, unknown)] == ["auto-created"]

    # Cross-tenant history is empty (Req 4.6).
    other_org = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'Other Org')"),
            {"id": other_org},
        )
    assert store.history(other_org, id_a) == []
    assert store.exists(other_org, id_a) is False

    # Cleanup so re-runs stay deterministic (messages cascade on conversation delete).
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM conversations WHERE id = ANY(:ids)"),
            {"ids": [id_a, id_b, unknown]},
        )
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(:ids)"),
            {"ids": [org_id, other_org]},
        )
