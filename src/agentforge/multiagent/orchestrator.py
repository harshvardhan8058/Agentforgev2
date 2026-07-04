"""Multi_Agent_Orchestrator (Phase 4).

The Multi_Agent_Orchestrator builds and runs a bounded LangGraph ``StateGraph`` over the
typed :class:`~agentforge.multiagent.state.Blackboard_State`, routing work between
Agent_Role nodes resolved from the
:class:`~agentforge.multiagent.roles.base.Agent_Role_Registry` in the declarative pipeline
order. It depends only on the abstract seams — the registry, the declarative pipeline, and
an optional ``Trace_Recorder`` (and, in later tasks, an approval gate / streaming service)
— so it is fully testable keyless with injected roles and never constructs its own
providers or references a concrete role class (Req 11.1).

Bound resolution and structural enforcement
--------------------------------------------
``max_rounds`` and ``max_revisions`` are normalized once via
:func:`~agentforge.multiagent.state.resolve_max_rounds` /
:func:`~agentforge.multiagent.state.resolve_max_revisions`, surfacing the invalid-limit
flags on the blackboard (Req 2.5, 2.6, 3.5, 3.6). The bounds are then enforced
**structurally** inside the graph's counting nodes and conditional edge (see
``multiagent/graph.py``), so neither counter can exceed its limit and every run terminates
with exactly one ``Termination_Reason`` (Req 2.7). ``run`` sets a defensive LangGraph
``recursion_limit`` derived from the bounds and applies a defensive ``aborted`` guard only
if the graph ever exits with an unset reason (it never should).
"""

from __future__ import annotations

import uuid
from dataclasses import fields

from agentforge.multiagent.graph import (
    _final_output_from_draft,
    build_multi_agent_graph,
    next_after_review,
    run_role_step,
)
from agentforge.multiagent.models import Termination_Reason
from agentforge.multiagent.roles.base import DEFAULT_PIPELINE, Agent_Role_Registry
from agentforge.multiagent.state import (
    Blackboard_State,
    resolve_max_revisions,
    resolve_max_rounds,
)
from agentforge.tracing.base import Trace_Recorder

# Node visits added per collaboration round (a reviser pass + a reviewer pass); used with
# ``max_rounds`` (the global round backstop) to derive the defensive recursion limit.
_NODES_PER_ROUND = 2
_RECURSION_BUFFER = 25

# Field names of Blackboard_State, used to reconstruct the dataclass from graph output.
_STATE_FIELDS = frozenset(f.name for f in fields(Blackboard_State))


class Multi_Agent_Orchestrator:
    """Runs the bounded multi-agent collaboration as a LangGraph state graph (Req 2.1)."""

    def __init__(
        self,
        registry: Agent_Role_Registry,
        pipeline: list[str] | None = None,
        *,
        max_rounds: object | None = None,
        max_revisions: object | None = None,
        trace: Trace_Recorder | None = None,
        gate: object | None = None,
    ) -> None:
        self._registry = registry
        self._pipeline = list(pipeline if pipeline is not None else DEFAULT_PIPELINE)
        self._trace = trace
        # Reserved seam: the Human_Approval_Gate is wired in a later task. For Task 5 the
        # approval checkpoints are pass-through (auto-approve), so the graph runs keyless
        # end-to-end without pausing.
        self._gate = gate

        # Resolve the configured bounds once; the invalid flags are surfaced on every
        # run's blackboard (Req 2.5, 2.6, 3.5, 3.6).
        self._max_rounds, self._invalid_rounds_flagged = resolve_max_rounds(max_rounds)
        self._max_revisions, self._invalid_revisions_flagged = resolve_max_revisions(
            max_revisions
        )

        self._graph = build_multi_agent_graph(registry, self._pipeline, trace=trace)

    @property
    def max_rounds(self) -> int:
        """The resolved Max_Rounds applied to every run (Req 2.5)."""
        return self._max_rounds

    @property
    def max_revisions(self) -> int:
        """The resolved Max_Revisions applied to every run (Req 3.5)."""
        return self._max_revisions

    @property
    def pipeline(self) -> list[str]:
        """The declarative role pipeline this orchestrator routes over (Req 1.4)."""
        return list(self._pipeline)

    @property
    def planner_id(self) -> str:
        """The first pipeline phase (begins every run at the Planner) (Req 2.1)."""
        return self._pipeline[0]

    @property
    def reviser_id(self) -> str:
        """The reviser phase (the Writer) that revisions route back to (Req 3.1)."""
        return self._pipeline[-2]

    @property
    def reviewer_id(self) -> str:
        """The reviewer phase (the Critic) that counts rounds and drives routing."""
        return self._pipeline[-1]

    @property
    def middle_ids(self) -> list[str]:
        """The phases between the Planner and the reviser (e.g. the Researcher)."""
        return list(self._pipeline[1:-2])

    def initialize_state(
        self, task: str, conversation_id: str | None = None, *, run_id: str | None = None
    ) -> Blackboard_State:
        """Build a fresh Blackboard_State with counters zeroed and bounds resolved.

        Shared by :meth:`run` and the gate-driven human-in-the-loop flow so every run
        starts from an identical, deterministic initial state (Req 4.7, 2.5, 3.5).
        """
        return Blackboard_State(
            run_id=run_id or str(uuid.uuid4()),
            conversation_id=conversation_id or str(uuid.uuid4()),
            task=task,
            round_count=0,
            revision_count=0,
            max_rounds=self._max_rounds,
            max_revisions=self._max_revisions,
            invalid_rounds_flagged=self._invalid_rounds_flagged,
            invalid_revisions_flagged=self._invalid_revisions_flagged,
            approval_policy="auto",
        )

    def act_role(self, role_id: str, state: Blackboard_State) -> Blackboard_State:
        """Run one pipeline role, applying the graph-owned counters + trace (Req 2.2, 3.1).

        Thin reuse of :func:`~agentforge.multiagent.graph.run_role_step`: the reviewer
        increments ``round_count`` and the reviser increments ``revision_count`` on a
        revision entry, so the gate-driven flow counts identically to the graph.
        """
        role = self._registry.resolve(role_id)
        if role is None:
            raise ValueError(f"pipeline role {role_id!r} is not registered")
        return run_role_step(
            role,
            state,
            self._trace,
            is_reviewer=role_id == self.reviewer_id,
            is_reviser=role_id == self.reviser_id,
        )

    @staticmethod
    def route_after_review(state: Blackboard_State) -> str:
        """The pure bounded routing decision out of the reviewer (Req 2.3, 2.4, 3.3, 3.4)."""
        return next_after_review(state)

    @staticmethod
    def final_output_for(state: Blackboard_State):
        """Build the Final_Output from the most recent Draft, preserving its Citations."""
        return _final_output_from_draft(state)

    def run(
        self,
        task: str,
        conversation_id: str | None = None,
        *,
        run_id: str | None = None,
    ) -> Blackboard_State:
        """Execute a single Multi_Agent_Run and return the final Blackboard_State.

        Builds the initial blackboard with the counters initialized to zero (Req 4.7) and
        the resolved bounds/flags, runs the compiled graph with a defensive
        ``recursion_limit`` backstop, reconstructs the final state, and guarantees exactly
        one ``Termination_Reason`` — applying the defensive ``aborted`` guard only if the
        graph ever exits with an unset reason (Req 2.7).

        An external ``run_id`` may be supplied (e.g. the id already assigned by the
        ``Multi_Agent_Run_Store``) so the orchestrator's run id, the run-store record,
        and the trace all key off the same value.
        """
        initial = self.initialize_state(task, conversation_id, run_id=run_id)

        # The round bound caps completed rounds at ``max_rounds``; each round adds at most
        # ``_NODES_PER_ROUND`` node visits, so this backstop never trips before a bound.
        recursion_limit = (
            _NODES_PER_ROUND * self._max_rounds + len(self._pipeline) + _RECURSION_BUFFER
        )
        raw = self._graph.invoke(initial, {"recursion_limit": recursion_limit})
        final = self._to_state(raw)

        # Defensive invariant guard: a run must always end with exactly one reason.
        if final.termination_reason is None:
            final.termination_reason = Termination_Reason.ABORTED
            if final.final_output is None:
                final.final_output = _final_output_from_draft(final)
        return final

    @staticmethod
    def _to_state(raw: object) -> Blackboard_State:
        """Reconstruct a :class:`Blackboard_State` from the graph's output mapping."""
        if isinstance(raw, Blackboard_State):
            return raw
        data = {k: v for k, v in dict(raw).items() if k in _STATE_FIELDS}
        return Blackboard_State(**data)
