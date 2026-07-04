"""Unit tests for the Approval_Policy seam and Human_Approval_Gate (Task 7.5).

Covers policy selection (Auto_Approve as the keyless default; Req 5.7) and the fast/slow
lanes of :class:`Human_Approval_Gate.at_checkpoint`: CONTINUE returns the state unchanged
and PAUSE flips the state's approval flags and persists the Run_Checkpoint through the
:class:`Checkpoint_Store` (Req 5.1).
"""

from __future__ import annotations

from agentforge.multiagent.approval import (
    Auto_Approve_Policy,
    CHECKPOINT_AFTER_PLAN,
    Checkpoint_Store,
    Human_Approval_Gate,
    Human_In_The_Loop_Policy,
    build_approval_policy,
)
from agentforge.multiagent.state import Blackboard_State


def _state(run_id: str = "run-1") -> Blackboard_State:
    """Build a minimal Blackboard_State suitable for gate testing."""
    return Blackboard_State(run_id=run_id, conversation_id="conv-1", task="write a memo")


def test_default_auto_approve_policy() -> None:
    """`build_approval_policy` yields Auto_Approve for 'auto' and for absent config."""
    assert isinstance(build_approval_policy("auto"), Auto_Approve_Policy)
    assert isinstance(build_approval_policy(None), Auto_Approve_Policy)
    # An unknown value falls back to the keyless default rather than raising.
    assert isinstance(build_approval_policy("unknown"), Auto_Approve_Policy)
    # "human" opts explicitly into the human-in-the-loop policy.
    assert isinstance(build_approval_policy("human"), Human_In_The_Loop_Policy)


def test_auto_approve_continues_at_checkpoint() -> None:
    """Under Auto_Approve the gate returns the state unchanged and persists nothing."""
    store = Checkpoint_Store()
    gate = Human_Approval_Gate(policy=Auto_Approve_Policy(), store=store)

    state = _state()
    result = gate.at_checkpoint(state, CHECKPOINT_AFTER_PLAN)

    assert result is state
    assert result.awaiting_approval is False
    assert result.pending_checkpoint is None
    assert store.load(state.run_id) is None


def test_human_in_the_loop_pauses_at_checkpoint() -> None:
    """Under Human_In_The_Loop the gate sets awaiting flags and persists the checkpoint."""
    store = Checkpoint_Store()
    gate = Human_Approval_Gate(policy=Human_In_The_Loop_Policy(), store=store)

    state = _state()
    result = gate.at_checkpoint(state, CHECKPOINT_AFTER_PLAN)

    assert result.awaiting_approval is True
    assert result.pending_checkpoint == CHECKPOINT_AFTER_PLAN

    saved = store.load(state.run_id)
    assert saved is not None
    saved_checkpoint, saved_state = saved
    assert saved_checkpoint == CHECKPOINT_AFTER_PLAN
    assert saved_state.run_id == state.run_id
    assert saved_state.task == state.task
    # is_awaiting_approval mirrors what the store reports.
    assert gate.is_awaiting_approval(state.run_id) is True
