"""Trace_Recorder interface, Trace, and Trace_Entry (Pluggable Seam: tracing).

The ``Trace_Recorder`` records a ``Trace_Entry`` per executed Agent_Step with a contiguous
ascending ordinal (and the tool name + outcome for tool calls) and exposes the ordered
``Trace`` through this interface so a later observability phase can consume it without
modifying the Agent_Orchestrator (Req 10.1-10.4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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


class Trace_Recorder(ABC):
    """Abstract contract for recording and exposing agent-run traces."""

    @abstractmethod
    def record(
        self,
        run_id: str,
        step_type: str,
        *,
        tool_name: str | None = None,
        outcome: str | None = None,
        detail: dict | None = None,
    ) -> Trace_Entry:
        """Append a Trace entry with the next ordinal for the run (Req 10.1, 10.2)."""
        raise NotImplementedError

    @abstractmethod
    def get_trace(self, run_id: str) -> Trace:
        """Return the ordered Trace for a run (Req 10.3, 10.4)."""
        raise NotImplementedError
