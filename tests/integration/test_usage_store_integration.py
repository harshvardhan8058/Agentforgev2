"""Integration test: migration 0008 + Pg_Usage_Store round-trip (Task 5.5).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the store converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.store import Pg_Usage_Store

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


async def test_migration_0008_applied(engine):
    """The 0008 migration reaches schema_migrations and creates usage_records."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0008_create_usage_records"},
        )
        assert applied.scalar_one_or_none() == "0008_create_usage_records"
        exists = await conn.execute(
            text("SELECT to_regclass(:t)"), {"t": "usage_records"}
        )
        assert exists.scalar_one() is not None


async def test_total_tokens_check_rejects_inconsistent_row(engine):
    """The total = prompt + completion CHECK rejects an inconsistent row (Req 2.7)."""
    org_id = await _make_org(engine, f"org-{uuid.uuid4().hex}")
    with pytest.raises((IntegrityError, Exception)):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO usage_records
                        (id, org_id, user_id, provider, model, prompt_tokens,
                         completion_tokens, total_tokens, cost, created_at)
                    VALUES
                        (:id, :org_id, NULL, 'p', 'm', 3, 4, 999, 0, now())
                    """
                ),
                {"id": str(uuid.uuid4()), "org_id": str(org_id)},
            )


async def test_pg_usage_store_round_trip_and_isolation(engine):
    """Pg_Usage_Store round-trips under org_id scoping with cross-org isolation."""
    org_a = await _make_org(engine, f"org-a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"org-b-{uuid.uuid4().hex}")
    store = Pg_Usage_Store(_dsn())

    now = datetime.now(timezone.utc)
    rec = Usage_Record(
        id=uuid.uuid4(),
        org_id=org_a,
        user_id=None,
        provider="groq",
        model="llama",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost=Decimal("0.12500000"),
        created_at=now,
    )
    store.add(rec)

    got = store.list_for_org(
        org_a, start=now - timedelta(days=1), end=now + timedelta(days=1)
    )
    assert len(got) == 1
    assert got[0].total_tokens == 15
    assert got[0].cost == Decimal("0.12500000")

    # Cross-org read returns nothing.
    assert store.list_for_org(
        org_b, start=now - timedelta(days=1), end=now + timedelta(days=1)
    ) == []

    # Cleanup: deleting the orgs cascades to usage_records.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(:ids)"),
            {"ids": [str(org_a), str(org_b)]},
        )
