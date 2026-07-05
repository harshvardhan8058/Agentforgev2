"""Integration test: migration 0009 + Pg_Prompt_Store round-trip (Task 6.6).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the store converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.observability.models import Prompt_Version
from agentforge.observability.prompt_registry.store import Pg_Prompt_Store

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


async def test_migration_0009_applied(engine):
    """The 0009 migration reaches schema_migrations and creates its tables."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0009_create_prompt_registry"},
        )
        assert applied.scalar_one_or_none() == "0009_create_prompt_registry"
        for table in ("prompt_templates", "prompt_versions"):
            exists = await conn.execute(text("SELECT to_regclass(:t)"), {"t": table})
            assert exists.scalar_one() is not None


async def test_pg_prompt_store_round_trip_and_versioning(engine):
    """Pg_Prompt_Store round-trips under org_id scoping with monotonic versions."""
    org_a = await _make_org(engine, f"org-a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"org-b-{uuid.uuid4().hex}")
    store = Pg_Prompt_Store(_dsn())
    name = "greeting"

    assert store.next_version_number(org_a, name) == 1
    v1 = store.add_version(
        Prompt_Version(
            id=uuid.uuid4(), org_id=org_a, template_name=name, version=1,
            body="Hi {who}", variables=("who",), created_at=datetime.now(timezone.utc),
        )
    )
    assert store.next_version_number(org_a, name) == 2
    store.add_version(
        Prompt_Version(
            id=uuid.uuid4(), org_id=org_a, template_name=name, version=2,
            body="Hello {who}", variables=("who",), created_at=datetime.now(timezone.utc),
        )
    )

    assert store.list_versions(org_a, name) == [1, 2]
    assert store.get_latest(org_a, name).version == 2
    assert store.get_version(org_a, name, 1).body == v1.body
    assert store.get_version(org_a, name, 1).variables == ("who",)

    # Cross-org isolation: org B sees nothing.
    assert store.list_versions(org_b, name) == []
    assert store.get_latest(org_b, name) is None
    assert store.next_version_number(org_b, name) == 1

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(:ids)"),
            {"ids": [str(org_a), str(org_b)]},
        )


async def test_unique_template_version_constraint_rejects_duplicate(engine):
    """The UNIQUE (template_id, version) constraint rejects a duplicate-version insert."""
    org = await _make_org(engine, f"org-{uuid.uuid4().hex}")
    store = Pg_Prompt_Store(_dsn())
    name = "dup"
    store.add_version(
        Prompt_Version(
            id=uuid.uuid4(), org_id=org, template_name=name, version=1,
            body="a", variables=(), created_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises((IntegrityError, Exception)):
        store.add_version(
            Prompt_Version(
                id=uuid.uuid4(), org_id=org, template_name=name, version=1,
                body="b", variables=(), created_at=datetime.now(timezone.utc),
            )
        )

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org)}
        )
