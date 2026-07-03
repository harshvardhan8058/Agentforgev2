"""Streaming_Service interface, StreamEvent, and StreamEventType (Pluggable Seam: streaming).

The ``Streaming_Service`` yields typed ``StreamEvent``s in strictly increasing production
order and guarantees exactly one terminal event (``completion`` xor ``error``) before
closing (Req 9.3-9.6, 9.8, 9.9). ``StreamEvent`` and ``AgentRunInput`` are plain
framework-agnostic dataclasses; :func:`format_sse_frame` renders an event as a
Server-Sent Events frame for the transport layer.
"""

from __future__ import annotations

import json
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


# The two terminal event types; a stream emits exactly one of these, then closes
# (Req 9.6, 9.8, 9.9).
TERMINAL_EVENT_TYPES: frozenset[StreamEventType] = frozenset(
    {StreamEventType.COMPLETION, StreamEventType.ERROR}
)


@dataclass
class StreamEvent:
    """A single streamed event with a monotonic sequence preserving order (Req 9.4)."""

    type: StreamEventType
    data: dict = field(default_factory=dict)
    sequence: int = 0

    @property
    def is_terminal(self) -> bool:
        """Whether this event is a terminal event (``completion`` or ``error``)."""
        return self.type in TERMINAL_EVENT_TYPES


@dataclass
class AgentRunInput:
    """The input for a streaming Agent_Run: the user message and its conversation."""

    message: str
    conversation_id: str | None = None
    conversation_context: list = field(default_factory=list)


def format_sse_frame(event: StreamEvent) -> str:
    """Render a :class:`StreamEvent` as a Server-Sent Events frame.

    The frame is ``event: <type>\\ndata: <json>\\n\\n``; the JSON payload embeds the
    monotonic ``sequence`` so clients can preserve production order end-to-end (Req 9.4).
    """
    payload = {"sequence": event.sequence, **event.data}
    body = json.dumps(payload, sort_keys=True, default=str)
    return f"event: {event.type.value}\ndata: {body}\n\n"


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
