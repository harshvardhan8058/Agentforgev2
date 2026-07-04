"""Property-based test for the tenant-scoped store round-trip (Property 9, Task 10.6).

Runs fully keyless against the in-memory tenant-owned stores. For any organization ``A``
and any resource kind, a resource created by a principal in ``A`` persists under ``A``, a
read/list scoped to ``A`` returns it, and every read/list scoped to any ``B != A`` does
not — parametric across the four in-memory stores.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.models.domain import Chunk, Document
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder

_RESOURCE_KINDS = ["document", "conversation", "agent_run", "multi_agent_run"]
_org_pairs = st.lists(st.uuids(), min_size=2, max_size=2, unique=True)


def _document_roundtrip(org_a, org_b) -> None:
    store = InMemoryDocumentStore()
    doc = Document(
        id="doc-1",
        filename="f.txt",
        content_type="text/plain",
        size_bytes=1,
        status="ingested",
        created_at=datetime.now(timezone.utc),
    )
    store.persist(org_a, doc, [Chunk(id="c-1", document_id="doc-1", index=0, content="x")])
    assert store.get_document(org_a, "doc-1") is not None
    assert [d.document_id for d in store.list_documents(org_a)] == ["doc-1"]
    assert store.get_document(org_b, "doc-1") is None
    assert store.list_documents(org_b) == []


def _conversation_roundtrip(org_a, org_b) -> None:
    store = InMemory_Conversation_Store()
    cid = store.create(org_a)
    store.append(org_a, cid, "user", "hi")
    assert store.exists(org_a, cid) is True
    assert [m.content for m in store.history(org_a, cid)] == ["hi"]
    assert store.exists(org_b, cid) is False
    assert store.history(org_b, cid) == []


def _agent_run_roundtrip(org_a, org_b) -> None:
    recorder = InMemory_Trace_Recorder()
    recorder.record(org_a, "run-1", "reason")
    assert len(recorder.get_trace(org_a, "run-1").entries) == 1
    assert recorder.get_trace(org_b, "run-1").entries == []


def _multi_agent_roundtrip(org_a, org_b) -> None:
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(org_a, "conv", "task")
    assert store.get(org_a, run.id) is not None
    assert store.get(org_b, run.id) is None


_DISPATCH = {
    "document": _document_roundtrip,
    "conversation": _conversation_roundtrip,
    "agent_run": _agent_run_roundtrip,
    "multi_agent_run": _multi_agent_roundtrip,
}


# Feature: agentforge-enterprise, Property 9: Tenant-scoped store round-trip.
@hyp_settings(max_examples=100, deadline=None)
@given(orgs=_org_pairs, kind=st.sampled_from(_RESOURCE_KINDS))
def test_tenant_scoped_store_roundtrip(orgs, kind):
    """Feature: agentforge-enterprise, Property 9: For any organization A and any
    tenant-owned resource type, a resource created by a principal with org_id = A persists
    under A, a read/list scoped to A returns it, and every read/list scoped to any
    B != A does not — parametric across the four in-memory stores.

    Validates: Requirements 4.1, 4.2, 4.4, 7.3, 7.4
    """
    org_a, org_b = orgs
    _DISPATCH[kind](org_a, org_b)
