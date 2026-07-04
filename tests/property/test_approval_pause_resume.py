"""Property test for approve/edit pause -> decision -> resume (Task 7.2, Property 10).

Under :class:`Human_In_The_Loop_Policy` any Blackboard_State reaching one of the two named
checkpoints must pause (awaiting_approval flag set, Run_Checkpoint persisted). Submitting
an ``approve`` decision resumes the run without touching the blackboard content;
submitting an ``edit`` replaces exactly the field associated with the checkpoint and
leaves everything else in place.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.multiagent.approval import (
    CHECKPOINT_AFTER_PLAN,
    CHECKPOINT_BEFORE_FINALIZE,
    Checkpoint_Store,
    Human_Approval_Gate,
    Human_In_The_Loop_Policy,
)
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Draft,
    Plan,
)
from agentforge.multiagent.state import Blackboard_State
from agentforge.tracing.recorder import InMemory_Trace_Recorder

# Small, well-formed input space: identifiers and content stay bounded so counter-example
# shrinking is fast and readable.
_ids = st.text(alphabet="abcdefghij0123456789", min_size=1, max_size=6)
_content = st.text(min_size=0, max_size=32)
_checkpoints = st.sampled_from([CHECKPOINT_AFTER_PLAN, CHECKPOINT_BEFORE_FINALIZE])


def _build_state(run_id: str, task: str, checkpoint: str) -> Blackboard_State:
    """Build a Blackboard_State pre-populated for the given checkpoint."""
    state = Blackboard_State(run_id=run_id, conversation_id="conv", task=task)
    if checkpoint == CHECKPOINT_AFTER_PLAN:
        state.plan = Plan(steps=["draft the plan", "gather sources"])
    else:  # CHECKPOINT_BEFORE_FINALIZE
        state.plan = Plan(steps=["draft the plan"])
        state.draft = Draft(content="initial draft", citations=[])
    return state


# Feature: agentforge-multi-agent, Property 10: Human-approval pause -> decision -> resume
#                                                for approve and edit
@hyp_settings(max_examples=100, deadline=None)
@given(
    run_id=_ids,
    task=_content,
    checkpoint=_checkpoints,
    edited=_content,
    decide=st.sampled_from(["approve", "edit"]),
)
def test_approve_or_edit_pause_and_resume(run_id, task, checkpoint, edited, decide):
    """Feature: agentforge-multi-agent, Property 10: Human-approval pause -> decision ->
    resume for approve and edit — under Human_In_The_Loop_Policy the state pauses and is
    persisted as a Run_Checkpoint; submitting ``approve`` resumes with the blackboard
    content unchanged; submitting ``edit`` replaces the checkpoint-associated field with
    the edited content and clears the awaiting flags on resume.

    Validates: Requirements 5.1, 5.2, 5.4, 10.4, 12.5
    """
    store = Checkpoint_Store()
    trace = InMemory_Trace_Recorder()
    gate = Human_Approval_Gate(
        policy=Human_In_The_Loop_Policy(), store=store, trace=trace
    )

    state = _build_state(run_id, task, checkpoint)
    paused = gate.at_checkpoint(state, checkpoint)

    # Pause invariants: flags set on the live state, and a Run_Checkpoint is persisted.
    assert paused.awaiting_approval is True
    assert paused.pending_checkpoint == checkpoint
    assert store.load(run_id) is not None
    assert gate.is_awaiting_approval(run_id) is True

    if decide == "approve":
        decision = Approval_Decision(type=ApprovalDecisionType.APPROVE)
        resumed = gate.submit(run_id, decision)
        # Approve leaves the blackboard content unchanged.
        if checkpoint == CHECKPOINT_AFTER_PLAN:
            assert resumed.plan is not None
            assert resumed.plan.steps == state.plan.steps
        else:
            assert resumed.draft is not None
            assert resumed.draft.content == state.draft.content
    else:  # edit
        decision = Approval_Decision(
            type=ApprovalDecisionType.EDIT, edited_content=edited
        )
        resumed = gate.submit(run_id, decision)
        # Edit replaces exactly the field associated with the checkpoint.
        if checkpoint == CHECKPOINT_AFTER_PLAN:
            assert resumed.plan == Plan(steps=[edited])
        else:
            assert resumed.draft is not None
            assert resumed.draft.content == edited
            # Citations are carried forward, not clobbered (Req 8.2 in spirit).
            assert resumed.draft.citations == []

    # Resume invariants: awaiting flags cleared, checkpoint discarded, decision remembered.
    assert resumed.awaiting_approval is False
    assert resumed.pending_checkpoint is None
    assert resumed.last_decision == decision
    assert store.load(run_id) is None
    assert gate.is_awaiting_approval(run_id) is False
