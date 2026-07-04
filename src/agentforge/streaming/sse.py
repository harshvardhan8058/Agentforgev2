"""SSE_Streaming_Service — Server-Sent Events streaming of an Agent_Run.

The service drives events from the orchestrator's ``stream_run`` generator in production
order, assigning each a monotonic ``sequence`` (Req 9.2, 9.4). It emits an initial
``step`` event immediately (Req 9.1), forwards each intermediate event as it is produced
(Req 9.5), and guarantees **exactly one** terminal event before closing — a
``completion`` on success (Req 9.6) xor a single ``error`` on failure (Req 9.8, 9.9).
Any exception raised by the underlying run is translated into that one ``error`` event,
and no ``completion`` is emitted in that case.

The event sequence is deterministic under the ``Fallback_Provider``: because the
orchestrator's reasoning, tool selection, and node order are all deterministic, two runs
with identical input yield identical ordered event sequences (Req 9.7).

``run_stream`` yields typed :class:`StreamEvent`s; :meth:`iter_sse_frames` renders them
as SSE frames for a FastAPI ``StreamingResponse``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from agentforge.agent.orchestrator import extract_citations
from agentforge.streaming.base import (
    AgentRunInput,
    StreamEvent,
    StreamEventType,
    format_sse_frame,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle at runtime
    from agentforge.agent.orchestrator import Agent_Orchestrator
    from agentforge.conversation.base import Conversation_Store


class SSE_Streaming_Service:
    """Stream an Agent_Run over Server-Sent Events with a single-terminal guarantee."""

    def __init__(
        self,
        orchestrator: Agent_Orchestrator,
        conversation_store: Conversation_Store | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        # Optional: when provided, the final assistant message is persisted on
        # successful completion (Req 8.5). Streaming works without it.
        self._conversation_store = conversation_store

    def run_stream(self, run_input: AgentRunInput) -> Iterator[StreamEvent]:
        """Yield ordered events ending in exactly one terminal event (Req 9.4, 9.6, 9.9)."""
        sequence = 0
        try:
            generator = self._orchestrator.stream_run(
                run_input.message,
                run_input.conversation_context,
                conversation_id=run_input.conversation_id,
                org_id=run_input.org_id,
            )
            # Drive the generator manually so its returned final state is captured from
            # StopIteration.value while each yielded event is forwarded with a sequence.
            final_state = None
            while True:
                try:
                    event = next(generator)
                except StopIteration as stop:
                    final_state = stop.value
                    break
                event.sequence = sequence
                sequence += 1
                yield event

            answer = (final_state.final_answer or "") if final_state else ""
            self._persist_final_answer(final_state, answer, run_input.org_id)
            yield StreamEvent(
                type=StreamEventType.COMPLETION,
                data={
                    "run_id": final_state.run_id if final_state else None,
                    "conversation_id": (
                        final_state.conversation_id if final_state else None
                    ),
                    "answer": answer,
                    "termination_reason": (
                        final_state.termination_reason.value
                        if final_state and final_state.termination_reason
                        else None
                    ),
                    "citations": extract_citations(final_state) if final_state else [],
                },
                sequence=sequence,
            )
        except Exception as exc:  # noqa: BLE001 - any failure becomes one error event
            # Exactly one terminal error event, and no completion for this stream
            # (Req 9.8). ``sequence`` continues monotonically from the last event.
            yield StreamEvent(
                type=StreamEventType.ERROR,
                data={"message": str(exc), "error_type": type(exc).__name__},
                sequence=sequence,
            )

    def iter_sse_frames(self, run_input: AgentRunInput) -> Iterator[str]:
        """Render :meth:`run_stream` events as SSE frames for a StreamingResponse."""
        for event in self.run_stream(run_input):
            yield format_sse_frame(event)

    def _persist_final_answer(self, final_state, answer: str, org_id) -> None:
        """Persist the final assistant message when a store and conversation exist (Req 8.5)."""
        if (
            self._conversation_store is not None
            and final_state is not None
            and final_state.conversation_id
        ):
            self._conversation_store.append(
                org_id, final_state.conversation_id, "assistant", answer
            )
