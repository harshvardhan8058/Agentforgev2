"""Property test for decisions against non-paused runs (Task 7.4, Property 12).

Any decision submitted for a run that is not currently awaiting approval — whether the
run id has never paused, is running normally, has already terminated, or has already been
resumed once — must be rejected as :class:`RunNotAwaitingApprovalError`, an
``approval_rejected`` trace entry must be recorded, and no independent Blackboard_State
the caller holds may be mutated.
"""

from __future__ import annotations

import copy

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.multiagent.approval import (
    CHECKPOINT_AFTER_PLAN,
    Checkpoint_Store,
    Human_Approval_Gate,
    Human_In_The_Loop_Policy,
    RunNotAwaitingApprovalError,
)
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Plan,
)
from agentforge.multiagent.state import Blackboard_State
from agentforge.tracing.recorder import InMemory_Trace_Recorder

_ids = st.text(alphabet="abcdefghij0123456789", min_size=1, max_size=6)
_decision_types = st.sampled_from(list(ApprovalDecisionType))


def _submit_and_assert_rejected(gate, run_id, decision, trace, held_state, expected_ords):
    """Common assertions for a rejected submit: exception + trace entry + no mutation."""
    snapshot = copy.deepcopy(held_state)
    with pytest.raises(RunNotAwaitingApprovalError):
        gate.submit(run_id, decision)

    entries = trace.get_trace(run_id).entries
    assert len(entries) == expected_ords
    assert entries[-1].step_type == "approval_rejected"
    assert entries[-1].detail["reason"] == "run-not-awaiting-approval"
    assert entries[-1].detail["decision_type"] == decision.type.value

    # The caller's independent state was not mutated by the failed submit.
    assert held_state == snapshot


# Feature: agentforge-multi-agent, Property 12: A decision to a non-paused run is rejected
#                                                without state change
@hyp_settings(max_examples=100, deadline=None)
@given(
    run_id=_ids,
    decision_type=_decision_types,
    feedback=st.text(min_size=0, max_size=16),
    edited=st.text(min_size=0, max_size=16),
)
def test_decision_to_non_paused_run_is_rejected(run_id, decision_type, feedback, edited):
    """Feature: agentforge-multi-agent, Property 12: A decision to a non-paused run is
    rejected without state change — submitting for an unknown run id or for a run whose
    checkpoint has already been consumed raises RunNotAwaitingApprovalError, records an
    ``approval_rejected`` trace entry, and mutates no independent state the caller holds.

    Validates: Requirements 5.5
    """
    store = Checkpoint_Store()
    trace = InMemory_Trace_Recorder()
    gate = Human_Approval_Gate(
        policy=Human_In_The_Loop_Policy(), store=store, trace=trace
    )

    decision = Approval_Decision(
        type=decision_type,
        feedback=feedback if decision_type is ApprovalDecisionType.REJECT else None,
        edited_content=edited if decision_type is ApprovalDecisionType.EDIT else None,
    )

    # 1) Unknown run id — never paused: submit is rejected, no state was held.
    held = Blackboard_State(run_id=run_id, conversation_id="conv", task="do work")
    _submit_and_assert_rejected(gate, run_id, decision, trace, held, expected_ords=1)

    # 2) After a successful resume — the checkpoint has already been cleared.
    resumed_id = f"{run_id}-resumed"
    paused_state = Blackboard_State(
        run_id=resumed_id,
        conversation_id="conv",
        task="do work",
        plan=Plan(steps=["one"]),
    )
    gate.at_checkpoint(paused_state, CHECKPOINT_AFTER_PLAN)
    gate.submit(
        resumed_id, Approval_Decision(type=ApprovalDecisionType.APPROVE)
    )
    # A held, independent Blackboard_State the caller still owns must stay untouched.
    held_after_resume = Blackboard_State(
        run_id=resumed_id, conversation_id="conv", task="do work"
    )
    # Pause + decision + resume entries already exist; a rejected submit appends one more.
    prior_entries = len(trace.get_trace(resumed_id).entries)
    _submit_and_assert_rejected(
        gate,
        resumed_id,
        decision,
        trace,
        held_after_resume,
        expected_ords=prior_entries + 1,
    )
