"""Blackboard_State and bound resolution — the typed multi-agent shared state.

``Blackboard_State`` is the typed shared state carried between Agent_Role nodes (Req 4.1):
it holds the task and each role's contribution (Plan, Research_Findings with Citations,
Draft, Critic_Feedback), the two counters (Round_Count, Revision_Count) initialized to
zero (Req 4.7), the resolved bounds, the invalid-limit flags, and the approval fields.

``resolve_max_rounds`` / ``resolve_max_revisions`` normalize the configured bounds with
the same pattern as Phase 3's ``resolve_iteration_limit`` (Req 2.5, 2.6, 3.5, 3.6): a
valid in-range integer passes through, an absent value resolves to the bounded default
with no invalid flag, and a non-integer / boolean / out-of-range value is rejected — the
default is applied and the invalid flag is set.

These are plain, framework-agnostic dataclasses (consistent with ``models/domain.py`` and
``agent/state.py``); they depend on neither FastAPI nor LangGraph so the core stays
decoupled and usable as a LangGraph state schema.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentforge.multiagent.models import (
    Approval_Decision,
    Critic_Feedback,
    Draft,
    Final_Output,
    Plan,
    Research_Findings,
    Termination_Reason,
)

# The bounded default and inclusive range for Max_Rounds (Req 2.5, 2.6).
DEFAULT_MAX_ROUNDS = 6
MIN_MAX_ROUNDS = 1
MAX_MAX_ROUNDS = 50

# The bounded default and inclusive range for Max_Revisions (Req 3.5, 3.6).
DEFAULT_MAX_REVISIONS = 3
MIN_MAX_REVISIONS = 1
MAX_MAX_REVISIONS = 20


def _resolve_bound(
    configured: object | None, default: int, low: int, high: int
) -> tuple[int, bool]:
    """Normalize a configured bound into ``(value, invalid_flag)``.

    - An integer within ``[low, high]`` passes through unchanged with
      ``invalid_flag=False``.
    - ``None`` (absent) resolves to ``default`` with ``invalid_flag=False``.
    - Anything else — a non-integer, a boolean, or an integer outside ``[low, high]`` — is
      rejected: ``default`` is applied and ``invalid_flag=True``.

    Booleans are rejected explicitly because ``bool`` is a subclass of ``int`` in Python
    and ``True``/``False`` are not meaningful bounds.
    """
    if configured is None:
        return default, False
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and low <= configured <= high
    ):
        return configured, False
    # Rejected: apply the bounded default and flag the invalid configuration.
    return default, True


def resolve_max_rounds(configured: object | None) -> tuple[int, bool]:
    """Normalize Max_Rounds into ``(value, invalid_flag)`` (Req 2.5, 2.6)."""
    return _resolve_bound(configured, DEFAULT_MAX_ROUNDS, MIN_MAX_ROUNDS, MAX_MAX_ROUNDS)


def resolve_max_revisions(configured: object | None) -> tuple[int, bool]:
    """Normalize Max_Revisions into ``(value, invalid_flag)`` (Req 3.5, 3.6)."""
    return _resolve_bound(
        configured, DEFAULT_MAX_REVISIONS, MIN_MAX_REVISIONS, MAX_MAX_REVISIONS
    )


@dataclass
class Blackboard_State:
    """The typed shared state carried between Agent_Role nodes (Req 4.1)."""

    run_id: str
    conversation_id: str
    # The task; never replaced during a run (Req 4.1).
    task: str

    # --- per-role contributions (Req 4.3-4.6) ---
    plan: Plan | None = None  # Planner contribution (Req 4.3)
    research_findings: Research_Findings | None = None  # Researcher contribution (Req 4.4)
    draft: Draft | None = None  # Writer contribution (Req 4.5)
    critic_feedback: Critic_Feedback | None = None  # Critic contribution (Req 4.6)

    # --- counters, initialized to zero at the start of a run (Req 4.7) ---
    round_count: int = 0  # +1 per completed collaboration round (Req 2.2)
    revision_count: int = 0  # +1 per revision cycle routed to the Writer (Req 3.1)

    # --- resolved bounds and invalid-limit flags ---
    max_rounds: int = DEFAULT_MAX_ROUNDS  # resolved bound (Req 2.5)
    max_revisions: int = DEFAULT_MAX_REVISIONS  # resolved bound (Req 3.5)
    invalid_rounds_flagged: bool = False  # Req 2.6
    invalid_revisions_flagged: bool = False  # Req 3.6

    # --- termination and output ---
    termination_reason: Termination_Reason | None = None  # exactly one per run (Req 2.7)
    final_output: Final_Output | None = None  # Req 2.3, 8.3

    # --- approval fields ---
    approval_policy: str = "auto"  # "auto" | "human"
    awaiting_approval: bool = False  # set on pause (Req 5.1)
    pending_checkpoint: str | None = None  # "after_plan" | "before_finalize"
    last_decision: Approval_Decision | None = None
