"""Multi-agent LangGraph nodes and conditional routing (Phase 4).

This module holds the role-node wrappers and the conditional routing that turn the
declarative pipeline into a bounded, terminating collaboration graph over the typed
:class:`~agentforge.multiagent.state.Blackboard_State`. It mirrors the Phase 3 agent
graph pattern (``agent/graph.py``): role work happens inside nodes, and **all bound
enforcement lives in the counting nodes and the conditional edge**, so each counter is
checked the instant it changes and can never be pushed past its limit.

Structural bound enforcement
----------------------------
- **Round bound (Req 2.2, 2.4).** The reviewer (Critic) node increments ``round_count``
  by **exactly 1** after each completed collaboration round. :func:`route_after_critic`
  routes to :data:`NODE_FINALIZE_ROUNDS` the instant ``round_count >= max_rounds``, so a
  new round can never push the count past ``max_rounds``.
- **Revision bound (Req 3.1, 3.3, 3.4).** :func:`route_after_critic` routes a required
  revision back to the reviser (Writer) **only while** ``revision_count < max_revisions``
  (so a revision is still permitted exactly when ``revision_count == max_revisions - 1``);
  otherwise it routes to :data:`NODE_FINALIZE_REVS`. The reviser node increments
  ``revision_count`` by exactly 1 on each revision entry. Because the router checks the
  pre-increment value before ever routing to the reviser, ``revision_count`` never
  exceeds ``max_revisions``.

The graph is built **generically** from the pipeline order (no per-role code): the last
pipeline phase is the reviewer that counts rounds and drives routing, and the phase before
it is the reviser that revisions route back to. A new role is added by editing the
declarative pipeline, never this core (Req 1.4).
"""

from __future__ import annotations

from dataclasses import fields

from agentforge.enterprise.tenancy import current_org
from agentforge.multiagent.models import Final_Output, Termination_Reason
from agentforge.multiagent.roles.base import Agent_Role_Interface, Agent_Role_Registry
from agentforge.multiagent.state import Blackboard_State
from agentforge.tracing.base import Trace_Recorder

# --- Terminal graph node names ----------------------------------------------------
NODE_FINALIZE_DONE = "finalize_done"  # Critic approved -> completed (Req 2.3)
NODE_FINALIZE_ROUNDS = "finalize_rounds"  # round bound reached (Req 2.4)
NODE_FINALIZE_REVS = "finalize_revs"  # revision bound reached (Req 3.4)

# --- Pure routing decisions out of the reviewer (shared by the graph and the gate) ---
ROUTE_APPROVE = "approve"  # Critic approved -> complete (or pause at before_finalize)
ROUTE_ROUNDS = "rounds"  # round bound reached
ROUTE_REVS = "revs"  # revision bound reached
ROUTE_REVISE = "revise"  # route one more revision back to the reviser

# Field names of Blackboard_State, used to project a returned state into LangGraph
# per-field state updates (mirroring the Phase 3 orchestrator's approach).
_BLACKBOARD_FIELDS = tuple(f.name for f in fields(Blackboard_State))


def _to_updates(state: Blackboard_State) -> dict:
    """Project a Blackboard_State into a dict of per-field LangGraph state updates."""
    return {name: getattr(state, name) for name in _BLACKBOARD_FIELDS}


def _is_revision_entry(state: Blackboard_State) -> bool:
    """Return whether the reviser is being entered for a Critic-requested revision."""
    feedback = state.critic_feedback
    return feedback is not None and feedback.revision_required


def _record_step(trace: Trace_Recorder | None, run_id: str, role_id: str) -> None:
    """Record a role-attributed Trace entry for a role step (Req 6.1), tenant-scoped."""
    if trace is not None:
        trace.record(
            current_org(),
            run_id,
            f"role:{role_id}",
            detail={"role_id": role_id, "checkpoint": None},
        )


def next_after_review(state: Blackboard_State) -> str:
    """Pure routing decision out of the reviewer, given a just-reviewed state.

    This is the single source of truth for the bounded routing (Req 2.3, 2.4, 3.3, 3.4),
    shared by the LangGraph conditional edge and the gate-driven human-in-the-loop flow so
    both enforce identical semantics. It is evaluated **after** the reviewer has run (the
    round already incremented) and **before** any revision increment:

    1. Critic approved (no revision required) -> :data:`ROUTE_APPROVE`.
    2. ``round_count >= max_rounds`` -> :data:`ROUTE_ROUNDS`.
    3. revision required AND ``revision_count >= max_revisions`` -> :data:`ROUTE_REVS`.
    4. otherwise (revision required AND ``revision_count < max_revisions``) ->
       :data:`ROUTE_REVISE`, so a revision is still permitted exactly when
       ``revision_count == max_revisions - 1``.
    """
    feedback = state.critic_feedback
    if feedback is None or not feedback.revision_required:
        return ROUTE_APPROVE
    if state.round_count >= state.max_rounds:
        return ROUTE_ROUNDS
    if state.revision_count >= state.max_revisions:
        return ROUTE_REVS
    return ROUTE_REVISE


def run_role_step(
    role: Agent_Role_Interface,
    state: Blackboard_State,
    trace: Trace_Recorder | None,
    *,
    is_reviewer: bool,
    is_reviser: bool,
) -> Blackboard_State:
    """Run one role's ``act`` and apply the graph-owned counters + trace (Req 2.2, 3.1).

    The role does its real work in ``act``; the structural counters are owned here (never
    by the role): the **reviewer** increments ``round_count`` by exactly 1 after each
    completed round, and the **reviser** increments ``revision_count`` by exactly 1 when
    it is entered for a Critic-requested revision (its pre-increment value having already
    been gated by :func:`next_after_review`). The role step is then attributed in the
    trace by ``role_id`` (Req 6.1). Shared by the graph node and the gate-driven flow so
    counting and tracing stay identical across both.
    """
    # Capture the revision-entry flag before ``act`` runs so the increment reflects the
    # reason this step was entered, not any change ``act`` might make.
    revision_entry = is_reviser and _is_revision_entry(state)
    updated = role.act(state)
    if revision_entry:
        updated.revision_count += 1
    if is_reviewer:
        updated.round_count += 1
    _record_step(trace, updated.run_id, role.role_id)
    return updated


def _make_role_node(
    role: Agent_Role_Interface,
    trace: Trace_Recorder | None,
    *,
    is_reviewer: bool,
    is_reviser: bool,
):
    """Build the LangGraph node for ``role``.

    The node runs ``role.act`` (the role's real work), applies the structural counter
    updates owned by the graph (never by the role), records the role step in the trace,
    and returns the updated state as LangGraph per-field updates.

    - The **reviewer** node increments ``round_count`` by exactly 1 (Req 2.2).
    - The **reviser** node increments ``revision_count`` by exactly 1 on a revision entry
      (Req 3.1); the pre-increment value was already gated by :func:`route_after_critic`.
    """
    def node(state: Blackboard_State) -> dict:
        updated = run_role_step(
            role, state, trace, is_reviewer=is_reviewer, is_reviser=is_reviser
        )
        return _to_updates(updated)

    return node


def _make_route_after_critic(reviser_role_id: str):
    """Build the conditional edge out of the reviewer node (Req 2.3, 2.4, 3.3, 3.4).

    Routing order (matching the design):
    1. Critic approved (no revision required) -> finalize completed.
    2. ``round_count >= max_rounds`` -> finalize max-rounds-reached.
    3. revision required AND ``revision_count >= max_revisions`` -> finalize
       max-revisions-reached.
    4. otherwise (revision required AND ``revision_count < max_revisions``) -> route back
       to the reviser (which increments ``revision_count``).
    """

    _ROUTE_TO_NODE = {
        ROUTE_APPROVE: NODE_FINALIZE_DONE,
        ROUTE_ROUNDS: NODE_FINALIZE_ROUNDS,
        ROUTE_REVS: NODE_FINALIZE_REVS,
        ROUTE_REVISE: reviser_role_id,
    }

    def route_after_critic(state: Blackboard_State) -> str:
        return _ROUTE_TO_NODE[next_after_review(state)]

    return route_after_critic


def _final_output_from_draft(state: Blackboard_State) -> Final_Output:
    """Build the Final_Output from the most recent Draft, preserving its Citations."""
    draft = state.draft
    if draft is None:
        return Final_Output(content="", citations=[])
    return Final_Output(content=draft.content, citations=list(draft.citations))


def finalize_done(state: Blackboard_State) -> dict:
    """Terminal node for Critic approval (Req 2.3, 8.3).

    Terminates with ``completed`` and emits the approved Draft as the Final_Output.
    """
    return {
        "termination_reason": Termination_Reason.COMPLETED,
        "final_output": _final_output_from_draft(state),
        "awaiting_approval": False,
    }


def finalize_rounds(state: Blackboard_State) -> dict:
    """Terminal node for the round bound (Req 2.4).

    Terminates with ``max-rounds-reached`` and returns the most recent available Draft.
    """
    return {
        "termination_reason": Termination_Reason.MAX_ROUNDS_REACHED,
        "final_output": _final_output_from_draft(state),
    }


def finalize_revs(state: Blackboard_State) -> dict:
    """Terminal node for the revision bound (Req 3.4).

    Terminates with ``max-revisions-reached`` and returns the most recent available Draft.
    """
    return {
        "termination_reason": Termination_Reason.MAX_REVISIONS_REACHED,
        "final_output": _final_output_from_draft(state),
    }


def build_multi_agent_graph(
    registry: Agent_Role_Registry,
    pipeline: list[str],
    *,
    trace: Trace_Recorder | None = None,
):
    """Assemble and compile the LangGraph ``StateGraph`` over :class:`Blackboard_State`.

    The graph is built **generically** by iterating ``pipeline`` and resolving each
    ``role_id`` from ``registry`` — there is no per-role code in this core (Req 1.4). It
    wires linear edges between consecutive phases (``planner -> researcher -> writer ->
    critic``), a conditional edge out of the reviewer (last phase) enforcing both bounds,
    the revision edge back to the reviser (second-to-last phase), and every terminal node
    to ``END``.

    Args:
        registry: The Agent_Role_Registry the pipeline roles are resolved from.
        pipeline: The declarative ordered list of ``role_id``s (>= 2 phases).
        trace: Optional Trace_Recorder; each role step is attributed to its ``role_id``.

    Raises:
        ValueError: if the pipeline has fewer than two phases or names an unregistered
            role (so misconfiguration fails fast rather than at run time).
    """
    from langgraph.graph import END, START, StateGraph

    if len(pipeline) < 2:
        raise ValueError(
            "the multi-agent pipeline requires at least two phases "
            "(a reviser and a reviewer)"
        )

    reviewer_id = pipeline[-1]
    reviser_id = pipeline[-2]

    graph = StateGraph(Blackboard_State)

    # Role nodes: resolve each pipeline phase from the registry (no per-role code).
    for index, role_id in enumerate(pipeline):
        role = registry.resolve(role_id)
        if role is None:
            raise ValueError(f"pipeline role {role_id!r} is not registered")
        graph.add_node(
            role_id,
            _make_role_node(
                role,
                trace,
                is_reviewer=index == len(pipeline) - 1,
                is_reviser=index == len(pipeline) - 2,
            ),
        )

    # Terminal nodes (each sets exactly one Termination_Reason).
    graph.add_node(NODE_FINALIZE_DONE, finalize_done)
    graph.add_node(NODE_FINALIZE_ROUNDS, finalize_rounds)
    graph.add_node(NODE_FINALIZE_REVS, finalize_revs)

    # Begin every run at the first pipeline phase (the Planner) (Req 2.1).
    graph.add_edge(START, pipeline[0])

    # Linear edges between consecutive phases, up to and including reviser -> reviewer.
    for index in range(len(pipeline) - 1):
        graph.add_edge(pipeline[index], pipeline[index + 1])

    # Conditional edge out of the reviewer enforces both bounds structurally.
    graph.add_conditional_edges(
        reviewer_id,
        _make_route_after_critic(reviser_id),
        {
            NODE_FINALIZE_DONE: NODE_FINALIZE_DONE,
            NODE_FINALIZE_ROUNDS: NODE_FINALIZE_ROUNDS,
            NODE_FINALIZE_REVS: NODE_FINALIZE_REVS,
            reviser_id: reviser_id,
        },
    )

    graph.add_edge(NODE_FINALIZE_DONE, END)
    graph.add_edge(NODE_FINALIZE_ROUNDS, END)
    graph.add_edge(NODE_FINALIZE_REVS, END)

    return graph.compile()
