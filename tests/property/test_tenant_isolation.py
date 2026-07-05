"""Property-based test for the multi-tenant isolation invariant (Property 1, Task 10.5).

Runs fully keyless against the in-memory tenant-owned stores — no database. For any two
distinct organizations ``A`` and ``B`` and any tenant-owned resource created in ``A``
(Document, Conversation, Agent_Run trace, or Multi_Agent_Run), every read/list/mutate/
delete attempt scoped to ``B`` returns nothing (the router surfaces ``404``) and leaves
the resource unchanged; descendant resources (chunks, messages, trace entries,
approval_decisions, run_checkpoints) accessed through their parent's identifier obey the
same guard because the stores filter through the parent's ``org_id``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.models.domain import Chunk, Citation, Document
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Final_Output,
    Termination_Reason,
)
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder

_RESOURCE_KINDS = ["document", "conversation", "agent_run", "multi_agent_run"]

# Two distinct organizations, drawn as UUIDs.
_org_pairs = st.lists(st.uuids(), min_size=2, max_size=2, unique=True)


def _document_case(org_a, org_b) -> None:
    store = InMemoryDocumentStore()
    doc = Document(
        id="doc-1",
        filename="f.txt",
        content_type="text/plain",
        size_bytes=3,
        status="ingested",
        created_at=datetime.now(timezone.utc),
    )
    chunk = Chunk(id="chunk-1", document_id="doc-1", index=0, content="abc")
    store.persist(org_a, doc, [chunk])

    # Cross-tenant reads return nothing, incl. the descendant chunk text (parent join).
    assert store.get_document(org_b, "doc-1") is None
    assert store.list_documents(org_b) == []
    assert store.get_chunk_texts(org_b, ["chunk-1"]) == {}

    # Cross-tenant delete is a no-op — the row is untouched under its owner.
    store.delete_document(org_b, "doc-1")
    assert store.get_document(org_a, "doc-1") is not None
    assert store.get_chunk_texts(org_a, ["chunk-1"]) == {"chunk-1": "abc"}


def _conversation_case(org_a, org_b) -> None:
    store = InMemory_Conversation_Store()
    cid = store.create(org_a)
    store.append(org_a, cid, "user", "hello")

    # Cross-tenant existence/history return nothing (messages via parent conversation).
    assert store.exists(org_b, cid) is False
    assert store.history(org_b, cid) == []

    # A cross-tenant append lands in B's OWN (disjoint) conversation space, leaving A's
    # history unchanged.
    store.append(org_b, cid, "user", "intruder")
    assert [m.content for m in store.history(org_a, cid)] == ["hello"]


def _agent_run_case(org_a, org_b) -> None:
    recorder = InMemory_Trace_Recorder()
    run_id = "run-1"
    recorder.record(org_a, run_id, "reason")

    # The trace entry (descendant of the Agent_Run) is invisible cross-tenant.
    assert recorder.get_trace(org_b, run_id).entries == []
    # Still present for its owner.
    assert len(recorder.get_trace(org_a, run_id).entries) == 1


def _multi_agent_run_case(org_a, org_b) -> None:
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(org_a, "conv", "task")
    store.append_message(org_a, run.id, "planner", "plan")
    store.record_decision(org_a, run.id, Approval_Decision(type=ApprovalDecisionType.APPROVE))

    # Cross-tenant reads (run + its descendants) return nothing.
    assert store.get(org_b, run.id) is None
    assert store.messages(org_b, run.id) == []
    assert store.decisions(org_b, run.id) == []

    # Cross-tenant terminate is a no-op — the run stays 'running' under its owner.
    store.terminate(
        org_b,
        run.id,
        Final_Output(content="hijacked", citations=[Citation("d", "c")]),
        Termination_Reason.COMPLETED,
    )
    owner_run = store.get(org_a, run.id)
    assert owner_run is not None
    assert owner_run.status == "running"
    assert owner_run.final_output is None


_DISPATCH = {
    "document": _document_case,
    "conversation": _conversation_case,
    "agent_run": _agent_run_case,
    "multi_agent_run": _multi_agent_run_case,
}


# Feature: agentforge-enterprise, Property 1: Tenant isolation invariant across every
# resource type (Document/Conversation/Agent_Run/Multi_Agent_Run incl. descendants via
# parent id -> cross-org 404/None).
@hyp_settings(max_examples=100, deadline=None)
@given(orgs=_org_pairs, kind=st.sampled_from(_RESOURCE_KINDS))
def test_tenant_isolation_across_resource_types(orgs, kind):
    """Feature: agentforge-enterprise, Property 1: For any two distinct organizations A
    and B, any tenant-owned resource created in A, and any principal scoped to B, every
    read/list/mutate/delete against that resource (and its descendants accessed via the
    parent id) yields nothing and leaves the resource unchanged.

    Validates: Requirements 4.3, 4.5, 4.6, 7.5, 10.4
    """
    org_a, org_b = orgs
    _DISPATCH[kind](org_a, org_b)
