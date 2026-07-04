"""Approval_Policy seam and Human_Approval_Gate (Phase 4).

Approval is expressed as a policy seam so the pause/resume mechanism stays behind a clean
interface, testable without a real human (Req 5, 13.3). This module declares the
:class:`ApprovalOutcome` vocabulary, the abstract :class:`Approval_Policy` contract, the
two built-in policies (``Auto_Approve_Policy`` / ``Human_In_The_Loop_Policy``), an
in-memory :class:`Checkpoint_Store`, and the :class:`Human_Approval_Gate` orchestrating
the pause/resume protocol.

The gate is intentionally implemented as a plain in-memory pause/resume abstraction — it
does not depend on LangGraph's checkpointer. The design's LangGraph-integrated variant is
one valid implementation of the same seam; keeping this one framework-agnostic makes the
gate testable without a real human and without a real graph runtime, which is exactly the
property Req 13.3 asks for.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from enum import Enum

from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Critic_Feedback,
    Draft,
    Plan,
    Termination_Reason,
)
from agentforge.multiagent.state import Blackboard_State
from agentforge.tracing.base import Trace_Recorder

# Named Approval_Checkpoints exposed by the orchestrator (Req 5.1).
CHECKPOINT_AFTER_PLAN = "after_plan"
CHECKPOINT_BEFORE_FINALIZE = "before_finalize"


class ApprovalOutcome(str, Enum):
    """The outcome of applying an Approval_Policy at an Approval_Checkpoint."""

    CONTINUE = "continue"  # proceed past the checkpoint
    PAUSE = "pause"  # interrupt + persist Run_Checkpoint, await a decision


class Approval_Policy(ABC):
    """The configured policy that governs the Human_Approval_Gate (Req 5.6, 5.7)."""

    @abstractmethod
    def evaluate(self, checkpoint: str, state: Blackboard_State) -> ApprovalOutcome:
        """Decide whether to continue or pause at an Approval_Checkpoint."""


class Auto_Approve_Policy(Approval_Policy):
    """The keyless default policy: always continues past every checkpoint (Req 5.6, 5.7)."""

    def evaluate(self, checkpoint: str, state: Blackboard_State) -> ApprovalOutcome:
        return ApprovalOutcome.CONTINUE


class Human_In_The_Loop_Policy(Approval_Policy):
    """The human-in-the-loop policy: always pauses at every checkpoint (Req 5.1)."""

    def evaluate(self, checkpoint: str, state: Blackboard_State) -> ApprovalOutcome:
        return ApprovalOutcome.PAUSE


def build_approval_policy(configured: str | None) -> Approval_Policy:
    """Build the configured Approval_Policy, defaulting to Auto_Approve (Req 5.7).

    ``"auto"`` or an absent value yields :class:`Auto_Approve_Policy` (the keyless
    default), ``"human"`` yields :class:`Human_In_The_Loop_Policy`. Any other value is
    treated as absent — the auto policy keeps the keyless path safe.
    """
    if configured == "human":
        return Human_In_The_Loop_Policy()
    return Auto_Approve_Policy()


class RunNotAwaitingApprovalError(RuntimeError):
    """Raised when a decision arrives for a run not currently awaiting approval (Req 5.5)."""


class Checkpoint_Store:
    """A minimal in-memory Run_Checkpoint store keyed by run id.

    Snapshots are deep-copied on write and on read so later mutations of the live
    Blackboard_State never leak into (or out of) the saved checkpoint (Req 5.1, 10.4).
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, Blackboard_State]] = {}

    def save(
        self, run_id: str, checkpoint: str, blackboard: Blackboard_State
    ) -> None:
        """Persist the (checkpoint_name, deep-copied Blackboard_State) for ``run_id``."""
        self._entries[run_id] = (checkpoint, copy.deepcopy(blackboard))

    def load(self, run_id: str) -> tuple[str, Blackboard_State] | None:
        """Return a fresh deep copy of the saved (checkpoint_name, state) or None."""
        entry = self._entries.get(run_id)
        if entry is None:
            return None
        checkpoint, blackboard = entry
        return checkpoint, copy.deepcopy(blackboard)

    def clear(self, run_id: str) -> None:
        """Remove any persisted checkpoint for ``run_id`` (idempotent)."""
        self._entries.pop(run_id, None)


class Human_Approval_Gate:
    """Coordinates pause/resume at Approval_Checkpoints under an Approval_Policy.

    Wired collaborators:

    * ``policy`` — an :class:`Approval_Policy` selected by the composition root (Req 5.6,
      5.7). ``Auto_Approve_Policy`` is the keyless default and this class treats CONTINUE
      as a no-op so the auto path stays free of overhead.
    * ``store`` — a :class:`Checkpoint_Store` that persists the paused Blackboard_State so
      the run can be resumed from a decision message (Req 5.1, 10.4).
    * ``trace`` — the reused :class:`Trace_Recorder` (optional). Approval pause / decision
      / resume / rejected-attempt entries are recorded through the same recorder that
      captures the rest of the run (Req 6.4).
    * ``streaming`` — the streaming service (optional). When supplied and it exposes an
      ``emit`` method, an ``approval_required`` event is emitted on pause. The full
      streaming service is implemented in Task 8; keep this optional and best-effort so
      the gate does not depend on it.
    """

    def __init__(
        self,
        policy: Approval_Policy,
        store: Checkpoint_Store,
        trace: Trace_Recorder | None = None,
        streaming: object | None = None,
    ) -> None:
        self._policy = policy
        self._store = store
        self._trace = trace
        self._streaming = streaming

    # ------------------------------------------------------------------ pause
    def at_checkpoint(
        self, state: Blackboard_State, checkpoint: str
    ) -> Blackboard_State:
        """Evaluate the policy at ``checkpoint`` and pause the run if it says PAUSE.

        On CONTINUE the state is returned unchanged (the auto-path fast lane). On PAUSE
        the awaiting_approval / pending_checkpoint flags are set on the state, a snapshot
        is persisted through the :class:`Checkpoint_Store`, an ``approval_pause`` trace
        entry is recorded, and (when a streaming service is wired) an
        ``approval_required`` event is emitted best-effort (Req 5.1, 6.4, 7.5).
        """
        outcome = self._policy.evaluate(checkpoint, state)
        if outcome is ApprovalOutcome.CONTINUE:
            return state

        state.awaiting_approval = True
        state.pending_checkpoint = checkpoint
        self._store.save(state.run_id, checkpoint, state)

        if self._trace is not None:
            self._trace.record(
                state.run_id,
                step_type="approval_pause",
                detail={"checkpoint": checkpoint},
            )

        emit = getattr(self._streaming, "emit", None)
        if callable(emit):
            try:
                emit(
                    {
                        "type": "approval_required",
                        "run_id": state.run_id,
                        "checkpoint": checkpoint,
                    }
                )
            except Exception:  # noqa: BLE001 -- streaming is best-effort here (Req 7.5)
                pass
        return state

    # ----------------------------------------------------------------- resume
    def submit(
        self, run_id: str, decision: Approval_Decision
    ) -> Blackboard_State:
        """Apply a human ``decision`` to a paused run and resume from the checkpoint.

        Raises :class:`RunNotAwaitingApprovalError` when no Run_Checkpoint is persisted
        for ``run_id`` (Req 5.5); an ``approval_rejected`` trace entry is recorded first
        so the attempt is observable. Otherwise the decision is applied to a deep copy of
        the saved snapshot (approve leaves content unchanged, reject records
        :class:`Critic_Feedback` and terminates when the revision bound is already
        reached, edit replaces the field associated with the checkpoint), the approval
        flags are cleared, the checkpoint is discarded, and ``approval_decision`` +
        ``approval_resume`` trace entries are recorded (Req 5.2-5.4, 6.4).
        """
        loaded = self._store.load(run_id)
        if loaded is None:
            if self._trace is not None:
                self._trace.record(
                    run_id,
                    step_type="approval_rejected",
                    detail={
                        "reason": "run-not-awaiting-approval",
                        "decision_type": decision.type.value,
                    },
                )
            raise RunNotAwaitingApprovalError(
                f"Run {run_id!r} is not awaiting approval."
            )

        checkpoint, state = loaded
        # Work on a fresh deep copy so we never mutate the caller's or the store's state.
        state = copy.deepcopy(state)

        if decision.type is ApprovalDecisionType.APPROVE:
            # Nothing to change on the blackboard (Req 5.2).
            pass
        elif decision.type is ApprovalDecisionType.REJECT:
            # Record feedback as a Critic_Feedback revision request (Req 5.3).
            state.critic_feedback = Critic_Feedback(
                revision_required=True,
                comments=decision.feedback or "",
            )
            # If the revision bound is already reached, terminate as rejected (Req 5.3).
            if state.revision_count >= state.max_revisions:
                state.termination_reason = Termination_Reason.REJECTED
        elif decision.type is ApprovalDecisionType.EDIT:
            edited = decision.edited_content or ""
            if checkpoint == CHECKPOINT_AFTER_PLAN:
                state.plan = Plan(steps=[edited])
            elif checkpoint == CHECKPOINT_BEFORE_FINALIZE:
                existing_citations = list(state.draft.citations) if state.draft else []
                state.draft = Draft(content=edited, citations=existing_citations)

        # Resume: clear awaiting flags, remember the last decision, discard the checkpoint.
        state.awaiting_approval = False
        state.pending_checkpoint = None
        state.last_decision = decision
        self._store.clear(run_id)

        if self._trace is not None:
            self._trace.record(
                run_id,
                step_type="approval_decision",
                detail={"type": decision.type.value, "checkpoint": checkpoint},
            )
            self._trace.record(
                run_id,
                step_type="approval_resume",
                detail={"checkpoint": checkpoint},
            )
        return state

    # ------------------------------------------------------------------- probe
    def is_awaiting_approval(self, run_id: str) -> bool:
        """Return whether a Run_Checkpoint is currently persisted for ``run_id``."""
        return self._store.load(run_id) is not None
