"""Unit tests for :class:`InMemory_Multi_Agent_Run_Store` (Task 10.4).

Cover run lifecycle round-trips on the keyless in-memory store:

* :meth:`create` yields unique ids and ``status='running'`` (Req 10.1).
* :meth:`record_decision` persists in append order with type/feedback/edited_content
  (Req 10.3).
* :meth:`save_checkpoint` + :meth:`load_checkpoint` round-trip a blackboard snapshot and
  are deep-copied so mutations to the caller's dict cannot corrupt stored state (Req 10.4).
* :meth:`terminate` persists ``final_output`` and ``termination_reason`` and :meth:`get`
  returns them (Req 10.5).
* :meth:`get` on an unknown id returns ``None``.
* Multiple :meth:`append_message` calls hand out contiguous ascending ordinals (Req 10.2).
"""

from __future__ import annotations

from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Final_Output,
    Termination_Reason,
)
from agentforge.enterprise.tenancy import NIL_ORG_ID as ORG
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store


def test_create_yields_unique_ids_and_running_status():
    """``create`` returns a Multi_Agent_Run with a unique id and ``status='running'`` (Req 10.1)."""
    store = InMemory_Multi_Agent_Run_Store()

    run_a = store.create(ORG, conversation_id="conv-a", task="task-a")
    run_b = store.create(ORG, conversation_id="conv-b", task="task-b")

    assert run_a.id and run_b.id
    assert run_a.id != run_b.id
    assert run_a.status == "running"
    assert run_a.termination_reason is None
    assert run_a.final_output is None
    # The persisted run is retrievable and equal to what was returned.
    assert store.get(ORG, run_a.id) is run_a


def test_record_decision_persists_in_append_order_with_full_fields():
    """Decisions are persisted in append order carrying type/feedback/edited_content (Req 10.3)."""
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(ORG, conversation_id="conv", task="task")

    decisions = [
        Approval_Decision(type=ApprovalDecisionType.APPROVE),
        Approval_Decision(
            type=ApprovalDecisionType.REJECT, feedback="please tighten section 2"
        ),
        Approval_Decision(
            type=ApprovalDecisionType.EDIT, edited_content="revised draft body"
        ),
    ]
    for decision in decisions:
        store.record_decision(ORG, run.id, decision)

    persisted = store.decisions(ORG, run.id)

    assert persisted == decisions
    # Preserving the full fields (not just types) matters for downstream audit + resume.
    assert persisted[1].feedback == "please tighten section 2"
    assert persisted[2].edited_content == "revised draft body"


def test_save_and_load_checkpoint_deep_copies_blackboard():
    """``save_checkpoint`` + ``load_checkpoint`` round-trip is deep-copied (Req 10.4)."""
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(ORG, conversation_id="conv", task="task")

    blackboard = {"plan": {"steps": ["a", "b"]}, "round_count": 1}
    store.save_checkpoint(ORG, run.id, "after_plan", blackboard)

    # Mutating the caller's dict after saving must not corrupt the stored snapshot.
    blackboard["round_count"] = 999
    blackboard["plan"]["steps"].append("mutated")

    loaded = store.load_checkpoint(ORG, run.id)
    assert loaded is not None
    checkpoint_name, restored = loaded
    assert checkpoint_name == "after_plan"
    assert restored == {"plan": {"steps": ["a", "b"]}, "round_count": 1}

    # Mutating the loaded snapshot must not corrupt the stored one either.
    restored["round_count"] = -1
    checkpoint_name_2, restored_again = store.load_checkpoint(ORG, run.id)  # type: ignore[misc]
    assert checkpoint_name_2 == "after_plan"
    assert restored_again["round_count"] == 1

    # Saving a second checkpoint wins on load (latest-wins semantics).
    store.save_checkpoint(ORG, run.id, "before_finalize", {"draft": "final"})
    latest = store.load_checkpoint(ORG, run.id)
    assert latest == ("before_finalize", {"draft": "final"})


def test_terminate_persists_final_output_and_reason_and_get_returns_them():
    """``terminate`` persists Final_Output + reason; ``get`` returns them (Req 10.5)."""
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(ORG, conversation_id="conv", task="task")

    final = Final_Output(
        content="the answer",
        citations=[Citation(document_id="doc-1", chunk_id="chunk-1")],
    )
    store.terminate(ORG, run.id, final, Termination_Reason.COMPLETED)

    got = store.get(ORG, run.id)
    assert got is not None
    assert got.status == "terminated"
    assert got.termination_reason is Termination_Reason.COMPLETED
    assert got.final_output == final


def test_get_unknown_run_returns_none():
    """``get`` on an unknown id returns ``None`` without raising."""
    store = InMemory_Multi_Agent_Run_Store()
    assert store.get(ORG, "not-a-real-run") is None
    # ``load_checkpoint`` on an unknown run likewise returns ``None``.
    assert store.load_checkpoint(ORG, "not-a-real-run") is None


def test_append_message_hands_out_contiguous_ordinals():
    """Multiple appends produce 0-based, strictly ascending contiguous positions (Req 10.2)."""
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(ORG, conversation_id="conv", task="task")

    positions = [
        store.append_message(ORG, run.id, role_id, f"content-{index}")
        for index, role_id in enumerate(["planner", "researcher", "writer", "critic"])
    ]

    assert positions == [0, 1, 2, 3]
    persisted = store.messages(ORG, run.id)
    assert [p for _, _, p in persisted] == [0, 1, 2, 3]
    assert [role_id for role_id, _, _ in persisted] == [
        "planner",
        "researcher",
        "writer",
        "critic",
    ]
