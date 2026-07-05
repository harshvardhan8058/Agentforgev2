"""Integration test: Pg_Trace_Recorder record/get_trace ordering (Req 10.1-10.3).

Requires a live PostgreSQL instance. Excluded from the default suite; run with
`pytest -m integration` while the Docker stack is up. Uses ``DATABASE_URL`` (async DSN);
the recorder converts it to a sync libpq DSN internally.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.tracing.recorder import Pg_Trace_Recorder

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


async def test_pg_trace_recorder_records_ordered_entries(engine):
    recorder = Pg_Trace_Recorder(_dsn())
    run_id = str(uuid.uuid4())

    # A real organization is required for the org_id FK on the auto-created agent_runs row.
    org_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'Trace Org')"),
            {"id": org_id},
        )

    recorder.record(org_id, run_id, "reason")
    recorder.record(
        org_id, run_id, "tool_call", tool_name="rag_search", outcome="tool_result"
    )
    recorder.record(org_id, run_id, "observe", detail={"iteration_count": 1})

    trace = recorder.get_trace(org_id, run_id)

    # Contiguous ascending ordinals in execution order (Req 10.1, 10.3).
    assert [e.ordinal for e in trace.entries] == [0, 1, 2]
    assert [e.step_type for e in trace.entries] == ["reason", "tool_call", "observe"]

    # The tool-call entry carries its tool name and outcome (Req 10.2).
    tool_call = trace.entries[1]
    assert tool_call.tool_name == "rag_search"
    assert tool_call.outcome == "tool_result"
    assert trace.entries[2].detail == {"iteration_count": 1}

    # Cleanup so re-runs stay deterministic (entries cascade on run delete).
    # Cross-tenant trace is empty (Req 4.6).
    other_org = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'Other Org')"),
            {"id": other_org},
        )
    assert recorder.get_trace(other_org, run_id).entries == []

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM agent_runs WHERE id = :id"), {"id": run_id}
        )
        await conn.execute(
            text("DELETE FROM organizations WHERE id = ANY(:ids)"),
            {"ids": [org_id, other_org]},
        )
