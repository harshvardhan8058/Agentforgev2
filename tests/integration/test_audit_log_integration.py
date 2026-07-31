"""Integration test: migration 0013 + Pg_Audit_Log against a live PostgreSQL.

Requires a live PostgreSQL instance (excluded from the default suite; run with
``pytest -m integration`` while the stack is up). Asserts the half of the audit trail the
keyless lane structurally cannot: the real table and its constraints, JSONB metadata
round-tripping, the composed SQL filters, newest-first ordering with an id tie-break, the
``ON DELETE SET NULL`` that keeps an event after its actor is deleted, and the ``org_id``
cascade that removes a trail with its tenant.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.enterprise.audit import Audit_Action, Pg_Audit_Log
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.enterprise.models import Audit_Event
from agentforge.enterprise.rbac import Role

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


def _event(org_id, *, action: Audit_Action, actor_user_id=None, actor_key_id=None,
           created_at=None, metadata=None) -> Audit_Event:
    return Audit_Event(
        id=uuid.uuid4(),
        org_id=org_id,
        actor_kind="user" if actor_user_id is not None else "api_key",
        actor_user_id=actor_user_id,
        actor_key_id=actor_key_id,
        action=action.value,
        target_type="member",
        target_id="target-1",
        metadata=metadata or {},
        created_at=created_at or datetime.now(timezone.utc),
    )


async def test_migration_0013_applied(engine):
    """The 0013 migration reaches schema_migrations and creates its table."""
    async with engine.connect() as conn:
        applied = await conn.execute(
            text("SELECT id FROM schema_migrations WHERE id = :id"),
            {"id": "0013_create_audit_events"},
        )
        assert applied.scalar_one_or_none() == "0013_create_audit_events"
        exists = await conn.execute(text("SELECT to_regclass('audit_events')"))
        assert exists.scalar_one() is not None


async def test_pg_audit_log_round_trip_filters_and_isolation(engine):
    store = Pg_Audit_Log(_dsn())
    identity = Pg_Identity_Store(_dsn())

    org = identity.create_organization("Acme")
    other_org = identity.create_organization("Beta")
    actor = identity.create_user(f"actor-{uuid.uuid4().hex}@example.com", "hash")
    identity.add_membership(actor.id, org.id, Role.OWNER)

    base = datetime.now(timezone.utc) - timedelta(hours=1)
    first = store.record(
        _event(
            org.id,
            action=Audit_Action.MEMBER_ADDED,
            actor_user_id=actor.id,
            created_at=base,
            metadata={"email": "new@example.com", "role": "member", "count": 2, "ok": True},
        )
    )
    second = store.record(
        _event(
            org.id,
            action=Audit_Action.TEAM_CREATED,
            actor_user_id=actor.id,
            created_at=base + timedelta(minutes=10),
        )
    )
    key_event = store.record(
        _event(
            org.id,
            action=Audit_Action.API_KEY_CREATED,
            actor_key_id=uuid.uuid4(),
            created_at=base + timedelta(minutes=20),
        )
    )
    store.record(_event(other_org.id, action=Audit_Action.MEMBER_REMOVED, actor_key_id=uuid.uuid4()))

    # --- newest first, org-scoped ---
    listed = store.list_for_org(org.id, limit=10)
    assert [e.id for e in listed] == [key_event.id, second.id, first.id]
    assert all(e.org_id == org.id for e in listed)

    # --- JSONB metadata survives with its scalar types intact ---
    restored = next(e for e in listed if e.id == first.id)
    assert restored.metadata == {
        "email": "new@example.com",
        "role": "member",
        "count": 2,
        "ok": True,
    }
    assert restored.actor_kind == "user"
    assert restored.actor_user_id == actor.id
    assert restored.target_type == "member"
    assert restored.target_id == "target-1"

    # --- filters compose in SQL ---
    assert [e.id for e in store.list_for_org(org.id, actions=["team.created"])] == [
        second.id
    ]
    assert len(store.list_for_org(org.id, actions=["team.created", "member.added"])) == 2
    assert [e.id for e in store.list_for_org(org.id, actor_user_id=actor.id)] == [
        second.id,
        first.id,
    ]
    assert [e.id for e in store.list_for_org(org.id, limit=1)] == [key_event.id]
    assert [
        e.id
        for e in store.list_for_org(
            org.id, start=base, end=base + timedelta(minutes=15)
        )
    ] == [second.id, first.id]

    # --- cross-tenant reads return nothing, never the other trail ---
    assert store.list_for_org(uuid.uuid4()) == []
    assert [e.action for e in store.list_for_org(other_org.id)] == ["member.removed"]

    # --- an actor deletion must not erase what they did (ON DELETE SET NULL) ---
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(actor.id)}
        )
    surviving = store.list_for_org(org.id, limit=10)
    assert {e.id for e in surviving} == {key_event.id, second.id, first.id}
    assert all(
        e.actor_user_id is None for e in surviving if e.actor_kind == "user"
    ), "the event survives with an unresolvable actor rather than being deleted"

    # --- equal timestamps still order deterministically ---
    same_time = datetime.now(timezone.utc)
    tied = [
        store.record(
            _event(
                org.id,
                action=Audit_Action.TEAM_DELETED,
                actor_key_id=uuid.uuid4(),
                created_at=same_time,
            )
        )
        for _ in range(4)
    ]
    page = store.list_for_org(org.id, actions=["team.deleted"], limit=2)
    assert page == store.list_for_org(org.id, actions=["team.deleted"], limit=2)
    assert {e.id for e in page} <= {e.id for e in tied}

    # --- a deleted org takes its trail with it (org_id CASCADE) ---
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(org.id)}
        )
    assert store.list_for_org(org.id) == []

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = :id"), {"id": str(other_org.id)}
        )
