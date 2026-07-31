"""Trace_Recorder interface, Trace, and Trace_Entry (Pluggable Seam: tracing).

The ``Trace_Recorder`` records a ``Trace_Entry`` per executed Agent_Step with a contiguous
ascending ordinal (and the tool name + outcome for tool calls) and exposes the ordered
``Trace`` through this interface so a later observability phase can consume it without
modifying the Agent_Orchestrator (Req 10.1-10.4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class Trace_Entry:
    """One recorded Agent_Step within a run's Trace."""

    run_id: str
    ordinal: int  # ascending position within the run (Req 10.1, 10.3)
    step_type: str  # "reason" | "tool_call" | "observe"
    tool_name: str | None = None  # set for tool_call entries (Req 10.2)
    outcome: str | None = None  # tool invocation outcome (Req 10.2)
    detail: dict = field(default_factory=dict)


@dataclass
class Trace:
    """The ordered record of Agent_Steps produced during an Agent_Run."""

    run_id: str
    entries: list[Trace_Entry] = field(default_factory=list)  # ordered by ordinal


@dataclass
class Agent_Run_Summary:
    """A row in the org's agent-run list.

    Deliberately limited to what the trace actually records. ``agent_runs`` carries a
    ``termination_reason`` column, but nothing ever writes it — the recorder inserts only
    the run's id and org on first use — so exposing it would surface a permanent ``null``
    dressed as data. Step and tool-call counts are derived from entries that do exist.
    """

    run_id: str
    created_at: datetime
    step_count: int
    tool_call_count: int


class Trace_Recorder(ABC):
    """Abstract contract for recording and exposing agent-run traces."""

    @abstractmethod
    def record(
        self,
        org_id: UUID,
        run_id: str,
        step_type: str,
        *,
        tool_name: str | None = None,
        outcome: str | None = None,
        detail: dict | None = None,
    ) -> Trace_Entry:
        """Append a Trace entry (owned by ``org_id``) with the next ordinal (Req 10.1, 10.2).

        The trace entry inherits tenancy through its parent Agent_Run, whose ``org_id`` is
        set here on first use so the run and its trace are scoped to the same tenant.
        """
        raise NotImplementedError

    @abstractmethod
    def get_trace(self, org_id: UUID, run_id: str) -> Trace:
        """Return ``org_id``'s Trace for the run; empty when unknown/cross-tenant (Req 10.3)."""
        raise NotImplementedError

    @abstractmethod
    def list_runs(self, org_id: UUID, *, limit: int = 50) -> list[Agent_Run_Summary]:
        """Return ``org_id``'s agent runs, most recent first.

        A trace could previously only be fetched by a run id the caller already held, so
        a finished run became unreachable the moment its id left the screen. ``limit``
        bounds the response because runs accumulate without end.
        """
        raise NotImplementedError
