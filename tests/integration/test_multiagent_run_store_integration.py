"""Integration test: Pg_Multi_Agent_Run_Store end-to-end round-trip (Task 10.5).

Applies migration 0005 against a live Postgres instance and round-trips a Multi_Agent_Run
through :class:`Pg_Multi_Agent_Run_Store` — create, append_message (via the existing
messages table), record_decision, save/load_checkpoint, terminate, get — verifying the
new schema (multi_agent_runs, approval_decisions, run_checkpoints) and the FKs to the
existing conversations table all work (Req 10.6).

Excluded from the default suite; run with ``pytest -m integration`` while the Docker
stack is up. Skips cleanly if ``DATABASE_URL`` is not set.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from agentforge.conversation.store import PgConversation_Store
from agentforge.db.engine import create_engine
from agentforge.db.migrations import run_migrations
from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Final_Output,
    Termination_Reason,
)
from agentforge.multiagent.store import Pg_Multi_Agent_Run_Store

pytestmark = pytest.mark.integration

EMBEDDING_DIMENSION = 384


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


@pytest.fixture
async def engine():
    dsn = _dsn()
    if not dsn:
        pytest.skip("DATABASE_URL not set; skipping Pg integration test")
    eng = create_engine(dsn)
    await run_migrations(eng, EMBEDDING_DIMENSION)
    yield eng
    await eng.dispose()


async def test_pg_multi_agent_run_store_full_roundtrip(engine):
    """Apply migration 0005 and round-trip a Multi_Agent_Run through Pg_Multi_Agent_Run_Store."""
    dsn = _dsn()
    assert dsn is not None  # narrowed by the skip in the fixture

    # A real conversation is required for the FK on multi_agent_runs.conversation_id.
    conversation_store = PgConversation_Store(dsn)
    conversation_id = conversation_store.create()

    store = Pg_Multi_Agent_Run_Store(dsn)

    # create() persists a running run and returns the domain object.
    run = store.create(conversation_id, task="write a short summary")
    assert run.status == "running"
    assert run.termination_reason is None
    assert run.final_output is None
    # A fresh get() returns the same run.
    fetched = store.get(run.id)
    assert fetched is not None
    assert fetched.id == run.id
    assert fetched.task == "write a short summary"

    # append_message reuses the existing messages table with contiguous ordinals.
    p0 = store.append_message(run.id, "planner", "step 1; step 2")
    p1 = store.append_message(run.id, "writer", "draft body")
    assert (p0, p1) == (0, 1)
    persisted_messages = store.messages(run.id)
    assert [(r, c, p) for r, c, p in persisted_messages] == [
        ("planner", "step 1; step 2", 0),
        ("writer", "draft body", 1),
    ]

    # record_decision assigns append-order positions per run.
    store.record_decision(
        run.id,
        Approval_Decision(type=ApprovalDecisionType.REJECT, feedback="tighten"),
    )
    store.record_decision(
        run.id,
        Approval_Decision(type=ApprovalDecisionType.EDIT, edited_content="revised"),
    )
    decisions = store.decisions(run.id)
    assert [d.type for d in decisions] == [
        ApprovalDecisionType.REJECT,
        ApprovalDecisionType.EDIT,
    ]
    assert decisions[0].feedback == "tighten"
    assert decisions[1].edited_content == "revised"

    # save_checkpoint / load_checkpoint round-trip the blackboard (latest wins).
    store.save_checkpoint(run.id, "after_plan", {"plan": {"steps": ["a", "b"]}})
    store.save_checkpoint(
        run.id, "before_finalize", {"draft": "final", "round_count": 2}
    )
    loaded = store.load_checkpoint(run.id)
    assert loaded == ("before_finalize", {"draft": "final", "round_count": 2})

    # terminate persists Final_Output + termination_reason; get() hydrates them.
    final = Final_Output(
        content="the summary",
        citations=[Citation(document_id="doc-1", chunk_id="chunk-1")],
    )
    store.terminate(run.id, final, Termination_Reason.COMPLETED)

    final_run = store.get(run.id)
    assert final_run is not None
    assert final_run.status == "terminated"
    assert final_run.termination_reason is Termination_Reason.COMPLETED
    assert final_run.final_output == final

    # get() on an unknown id returns None.
    assert store.get(str(uuid.uuid4())) is None

    # Cleanup: cascading FKs drop everything associated with the conversation/run.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM multi_agent_runs WHERE id = :id"), {"id": run.id}
        )
        await conn.execute(
            text("DELETE FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
