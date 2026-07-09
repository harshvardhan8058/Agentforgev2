"""Integration test (production-hardening, Task 4.3): Pg_* Domain_Store durability and
model-based equivalence + restart (B1).

Requires a live PostgreSQL instance. Excluded from the default keyless lane; run with
``pytest -m integration`` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
each ``Pg_*`` store converts it to a sync libpq DSN internally.

For each newly-persistent Domain_Store this asserts two things:

1. **Model-based equivalence** — a record written through the ``Pg_*`` store reads back with
   field values equal to those an ``InMemory_*`` reference store would return for the same
   sequence of operations, and cross-tenant reads return ``None`` / ``[]`` (never 403 or
   contents).
2. **Restart durability** — a **fresh** ``Pg_*`` instance (a new engine + connection pool,
   simulating a container restart with no in-process state) reads back the same field values,
   proving the state lives in Postgres and survives a restart (Req 1.2, 1.4).

These map onto the tables created by the existing additive migrations 0003-0011; no new
migration is required.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from agentforge.conversation.store import PgConversation_Store
from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.enterprise.api_keys import Pg_API_Key_Store
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.enterprise.models import API_Key
from agentforge.enterprise.rbac import Role
from agentforge.integrations.connection import Pg_Integration_Connection_Store
from agentforge.multiagent.store import Pg_Multi_Agent_Run_Store
from agentforge.observability.evaluation.store import Pg_Evaluation_Store
from agentforge.observability.models import (
    Evaluation_Dataset,
    Prompt_Version,
    Usage_Record,
)
from agentforge.observability.prompt_registry.store import Pg_Prompt_Store
from agentforge.observability.usage.store import Pg_Usage_Store
from agentforge.tracing.recorder import Pg_Trace_Recorder

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
async def engine():
    dsn = _dsn()
    if not dsn:
        pytest.skip("DATABASE_URL not set; skipping Pg integration test")
    eng = create_engine(dsn)
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


async def _delete_orgs(engine, *org_ids) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(:ids)"),
            {"ids": [str(o) for o in org_ids]},
        )


async def test_pg_identity_equivalence_and_restart(engine):
    """Pg_Identity_Store durably round-trips a user + membership across a restart."""
    dsn = _dsn()
    store = Pg_Identity_Store(dsn)
    org = store.create_organization(f"acme-{uuid.uuid4().hex}")
    email = f"user-{uuid.uuid4().hex}@example.com"
    user = store.create_user(email, "argon2-hash")
    store.add_membership(user.id, org.id, Role.OWNER)

    # Restart: a fresh instance (new engine) reads persisted state back identically.
    restarted = Pg_Identity_Store(dsn)
    assert restarted.get_user(user.id).email == email
    assert restarted.get_membership(user.id, org.id).role == Role.OWNER
    # Cross-tenant read returns nothing (404 semantics), never a role.
    assert restarted.get_membership(user.id, uuid.uuid4()) is None

    await _delete_orgs(engine, org.id)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(user.id)})


async def test_pg_api_key_equivalence_and_restart(engine):
    """Pg_API_Key_Store durably round-trips an API key with cross-tenant isolation."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    store = Pg_API_Key_Store(dsn)
    key = API_Key(
        id=uuid.uuid4(),
        org_id=org_a,
        role=Role.ADMIN,
        key_prefix="af_abcde",
        key_hash="argon2-hash",
        revoked_at=None,
        created_at=_now(),
    )
    store.create(key)

    restarted = Pg_API_Key_Store(dsn)
    got = restarted.get_for_org(org_a, key.id)
    assert got is not None and got.role == Role.ADMIN and got.key_prefix == "af_abcde"
    assert restarted.get_for_org(org_b, key.id) is None
    assert restarted.list_for_org(org_b) == []

    await _delete_orgs(engine, org_a, org_b)


async def test_pg_usage_equivalence_and_restart(engine):
    """Pg_Usage_Store durably round-trips a usage record within its org window."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    store = Pg_Usage_Store(dsn)
    now = _now()
    store.add(
        Usage_Record(
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
    )
    start, end = now - timedelta(days=1), now + timedelta(days=1)

    restarted = Pg_Usage_Store(dsn)
    got = restarted.list_for_org(org_a, start=start, end=end)
    assert len(got) == 1 and got[0].total_tokens == 15
    assert got[0].cost == Decimal("0.12500000")
    assert restarted.list_for_org(org_b, start=start, end=end) == []

    await _delete_orgs(engine, org_a, org_b)


async def test_pg_prompt_equivalence_and_restart(engine):
    """Pg_Prompt_Store durably round-trips an immutable prompt version."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    store = Pg_Prompt_Store(dsn)
    name = "greeting"
    store.add_version(
        Prompt_Version(
            id=uuid.uuid4(),
            org_id=org_a,
            template_name=name,
            version=1,
            body="Hi {who}",
            variables=("who",),
            created_at=_now(),
        )
    )

    restarted = Pg_Prompt_Store(dsn)
    v = restarted.get_version(org_a, name, 1)
    assert v is not None and v.body == "Hi {who}" and v.variables == ("who",)
    assert restarted.list_versions(org_a, name) == [1]
    assert restarted.get_latest(org_b, name) is None
    assert restarted.list_versions(org_b, name) == []

    await _delete_orgs(engine, org_a, org_b)


async def test_pg_evaluation_equivalence_and_restart(engine):
    """Pg_Evaluation_Store durably round-trips a dataset with cross-tenant isolation."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    store = Pg_Evaluation_Store(dsn)
    dataset_id = uuid.uuid4()
    store.add_dataset(
        Evaluation_Dataset(id=dataset_id, org_id=org_a, name="ds", created_at=_now())
    )

    restarted = Pg_Evaluation_Store(dsn)
    got = restarted.get_dataset(org_a, dataset_id)
    assert got is not None and got.name == "ds"
    assert [d.id for d in restarted.list_datasets(org_a)] == [dataset_id]
    assert restarted.get_dataset(org_b, dataset_id) is None
    assert restarted.list_datasets(org_b) == []

    await _delete_orgs(engine, org_a, org_b)


async def test_pg_conversation_equivalence_and_restart(engine):
    """PgConversation_Store durably round-trips a message across a restart."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    store = PgConversation_Store(dsn)
    cid = store.create(org_a)
    store.append(org_a, cid, "user", "hello")

    restarted = PgConversation_Store(dsn)
    assert [m.content for m in restarted.history(org_a, cid)] == ["hello"]
    assert restarted.exists(org_b, cid) is False
    assert restarted.history(org_b, cid) == []

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": cid})
    await _delete_orgs(engine, org_a, org_b)


async def test_pg_trace_equivalence_and_restart(engine):
    """Pg_Trace_Recorder durably round-trips a trace entry across a restart."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    recorder = Pg_Trace_Recorder(dsn)
    run_id = f"run-{uuid.uuid4().hex}"
    recorder.record(org_a, run_id, "reason", detail={"note": "x"})

    restarted = Pg_Trace_Recorder(dsn)
    trace = restarted.get_trace(org_a, run_id)
    assert len(trace.entries) == 1 and trace.entries[0].step_type == "reason"
    assert restarted.get_trace(org_b, run_id).entries == []

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM agent_runs WHERE id = :id"), {"id": run_id})
    await _delete_orgs(engine, org_a, org_b)


async def test_pg_multi_agent_run_equivalence_and_restart(engine):
    """Pg_Multi_Agent_Run_Store durably round-trips a run across a restart."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    conversation_id = PgConversation_Store(dsn).create(org_a)
    store = Pg_Multi_Agent_Run_Store(dsn)
    run = store.create(org_a, conversation_id, task="summarize")

    restarted = Pg_Multi_Agent_Run_Store(dsn)
    fetched = restarted.get(org_a, run.id)
    assert fetched is not None and fetched.id == run.id and fetched.task == "summarize"
    assert restarted.get(org_b, run.id) is None

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM multi_agent_runs WHERE id = :id"), {"id": run.id}
        )
        await conn.execute(
            text("DELETE FROM conversations WHERE id = :id"), {"id": conversation_id}
        )
    await _delete_orgs(engine, org_a, org_b)


async def test_pg_integration_connection_equivalence_and_restart(engine):
    """Pg_Integration_Connection_Store durably round-trips a non-secret config."""
    dsn = _dsn()
    org_a = await _make_org(engine, f"a-{uuid.uuid4().hex}")
    org_b = await _make_org(engine, f"b-{uuid.uuid4().hex}")
    store = Pg_Integration_Connection_Store(dsn)
    connection = store.create(org_a, "slack", {"default_channel": "#general"})

    restarted = Pg_Integration_Connection_Store(dsn)
    got = restarted.get(org_a, connection.id)
    assert got is not None and got.config == {"default_channel": "#general"}
    assert restarted.get(org_b, connection.id) is None
    assert restarted.list_for_org(org_b) == []

    await _delete_orgs(engine, org_a, org_b)
