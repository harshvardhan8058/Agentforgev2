"""Property test for bounded reject decisions (Task 7.3, Property 11).

A ``reject`` decision either records structured Critic_Feedback (bounded revision) or —
when the revision bound is already reached — terminates the run as ``rejected``. Nothing
about the revision counters themselves changes inside ``submit`` — that bookkeeping is
the graph's responsibility (Property 2), not the gate's.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.multiagent.approval import (
    CHECKPOINT_BEFORE_FINALIZE,
    Checkpoint_Store,
    Human_Approval_Gate,
    Human_In_The_Loop_Policy,
)
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Draft,
    Termination_Reason,
)
from agentforge.multiagent.state import Blackboard_State


# Feature: agentforge-multi-agent, Property 11: Reject decision is bounded to
#                                                revision-or-terminate
@hyp_settings(max_examples=100, deadline=None)
@given(
    max_revisions=st.integers(min_value=1, max_value=6),
    # revision_count spans below, at, and beyond the bound so both branches are exercised.
    revision_count=st.integers(min_value=0, max_value=6),
    feedback=st.text(min_size=0, max_size=48),
)
def test_reject_records_feedback_or_terminates(max_revisions, revision_count, feedback):
    """Feature: agentforge-multi-agent, Property 11: Reject decision is bounded to
    revision-or-terminate — submitting ``reject(+feedback)`` on a paused run always sets
    Critic_Feedback(revision_required=True, comments=feedback). When the pre-load
    revision_count is strictly below max_revisions the run stays running (no termination);
    when it has already reached the bound the run is terminated as ``rejected``. The gate
    never mutates the counters itself.

    Validates: Requirements 5.3
    """
    store = Checkpoint_Store()
    gate = Human_Approval_Gate(policy=Human_In_The_Loop_Policy(), store=store)

    # Build a paused state at the before-finalize checkpoint with the sampled counters.
    state = Blackboard_State(
        run_id="run-reject",
        conversation_id="conv",
        task="revise the memo",
        draft=Draft(content="initial draft", citations=[]),
        max_revisions=max_revisions,
        revision_count=revision_count,
    )
    gate.at_checkpoint(state, CHECKPOINT_BEFORE_FINALIZE)

    resumed = gate.submit(
        "run-reject",
        Approval_Decision(type=ApprovalDecisionType.REJECT, feedback=feedback),
    )

    # Critic_Feedback is always populated with revision_required=True and the feedback.
    assert resumed.critic_feedback is not None
    assert resumed.critic_feedback.revision_required is True
    assert resumed.critic_feedback.comments == feedback

    # The gate never mutates revision counters itself (Property 2 owns that).
    assert resumed.revision_count == revision_count
    assert resumed.max_revisions == max_revisions

    if revision_count < max_revisions:
        # Under-bound: continue as a bounded revision, no termination yet.
        assert resumed.termination_reason is None
    else:
        # At or above the bound: terminate as rejected (Req 5.3).
        assert resumed.termination_reason == Termination_Reason.REJECTED

    # Resume invariants always hold.
    assert resumed.awaiting_approval is False
    assert resumed.pending_checkpoint is None
    assert store.load("run-reject") is None
