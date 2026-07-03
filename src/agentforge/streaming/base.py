"""Streaming_Service interface, StreamEvent, and StreamEventType (Pluggable Seam: streaming).

The ``Streaming_Service`` yields typed ``StreamEvent``s in strictly increasing production
order and guarantees exactly one terminal event (``completion`` xor ``error``) before
closing (Req 9.3-9.6, 9.8, 9.9). ``StreamEvent`` is a plain framework-agnostic dataclass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum


class StreamEventType(str, Enum):
    """The exactly-one type carried by each streamed event (Req 9.3)."""

    STEP = "step"
    TOOL_CALL = "tool_call"
    DELTA = "delta"
    COMPLETION = "completion"  # terminal (success)
    ERROR = "error"  # terminal (failure)


@dataclass
class StreamEvent:
    """A single streamed event with a monotonic sequence preserving order (Req 9.4)."""

    type: StreamEventType
    data: dict = field(default_factory=dict)
    sequence: int = 0


class Streaming_Service(ABC):
    """Abstract contract for streaming incremental Agent_Run output."""

    @abstractmethod
    def run_stream(self, run_input: object) -> Iterator[StreamEvent]:
        """Yield events in production order; emit exactly one terminal event, then close.

        ``run_input`` carries the agent run request (conversation id + message). The
        service wraps the underlying run so any exception becomes a single ``error``
        terminal event (Req 9.2, 9.6, 9.8, 9.9).
        """
        raise NotImplementedError
