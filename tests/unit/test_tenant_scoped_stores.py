"""Unit tests: cross-tenant access returns ``None``/empty on each in-memory store (Task 10.7).

Creating a resource under ``org_a`` and reading/mutating it under ``org_b`` returns
nothing and changes zero rows; the resource remains intact when re-read under ``org_a``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.models.domain import Chunk, Document
from agentforge.multiagent.models import Final_Output, Termination_Reason
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


def test_document_store_cross_tenant_returns_none_and_no_op_delete():
    store = InMemoryDocumentStore()
    doc = Document(
        id="d1",
        filename="f.txt",
        content_type="text/plain",
        size_bytes=1,
        status="ingested",
        created_at=datetime.now(timezone.utc),
    )
    store.persist(ORG_A, doc, [Chunk(id="c1", document_id="d1", index=0, content="x")])

    assert store.get_document(ORG_B, "d1") is None
    assert store.list_documents(ORG_B) == []
    assert store.get_chunk_texts(ORG_B, ["c1"]) == {}

    store.delete_document(ORG_B, "d1")  # no-op
    assert store.get_document(ORG_A, "d1") is not None


def test_conversation_store_cross_tenant_returns_empty():
    store = InMemory_Conversation_Store()
    cid = store.create(ORG_A)
    store.append(ORG_A, cid, "user", "hi")

    assert store.exists(ORG_B, cid) is False
    assert store.history(ORG_B, cid) == []
    # A's history is intact.
    assert [m.content for m in store.history(ORG_A, cid)] == ["hi"]


def test_trace_recorder_cross_tenant_returns_empty_trace():
    recorder = InMemory_Trace_Recorder()
    recorder.record(ORG_A, "run-1", "reason")

    assert recorder.get_trace(ORG_B, "run-1").entries == []
    assert len(recorder.get_trace(ORG_A, "run-1").entries) == 1


def test_multi_agent_run_store_cross_tenant_returns_none_and_no_op_terminate():
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(ORG_A, "conv", "task")

    assert store.get(ORG_B, run.id) is None
    assert store.messages(ORG_B, run.id) == []

    store.terminate(ORG_B, run.id, Final_Output(content="", citations=[]), Termination_Reason.COMPLETED)
    owner = store.get(ORG_A, run.id)
    assert owner is not None
    assert owner.status == "running"  # unchanged by the cross-tenant terminate
