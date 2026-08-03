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

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentforge.agent.orchestrator import extract_citations
from agentforge.enterprise.tenancy import set_current_org
from agentforge.streaming.base import (
    AgentRunInput,
    StreamEvent,
    StreamEventType,
    format_sse_frame,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle at runtime
    from agentforge.agent.orchestrator import Agent_Orchestrator
    from agentforge.conversation.base import Conversation_Store


@dataclass(frozen=True)
class Completed_Run:
    """What the completion hook is told about a finished streamed run.

    A record rather than a widening list of positional arguments: the hook started out needing
    only the run id (trace export), and now also needs the outcome (so a streamed run can emit
    the same ``run.completed`` / ``run.failed`` webhook a non-streamed one does). Passing a
    frozen record means the next fact a hook needs is an added field, not a changed signature
    at every call site.
    """

    run_id: str
    conversation_id: str | None
    termination_reason: str | None
    citation_count: int


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

    def run_stream(
        self,
        run_input: AgentRunInput,
        *,
        on_complete: Callable[[Completed_Run], None] | None = None,
    ) -> Iterator[StreamEvent]:
        """Yield ordered events ending in exactly one terminal event (Req 9.4, 9.6, 9.9).

        ``on_complete`` is invoked with a :class:`Completed_Run` **after** the terminal
        completion event has been handed to the consumer, and only for a successful run.
        It is how post-run work (trace export, webhook emission) attaches to a streamed run
        without this service knowing what that work is. A hook failure is swallowed: emitting a
        second terminal event because a side effect failed would break the single-terminal
        guarantee the whole stream contract rests on (Req 9.6).
        """
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
            citations = extract_citations(final_state) if final_state else []
            completed = (
                Completed_Run(
                    run_id=final_state.run_id,
                    conversation_id=final_state.conversation_id,
                    termination_reason=(
                        final_state.termination_reason.value
                        if final_state.termination_reason
                        else None
                    ),
                    citation_count=len(citations),
                )
                if final_state is not None and final_state.run_id
                else None
            )
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
                    "citations": citations,
                },
                sequence=sequence,
            )
            # Reached once the consumer asks for the frame after the terminal one, i.e.
            # after the client already holds the completion event.
            self._notify_complete(completed, on_complete)
        except Exception as exc:  # noqa: BLE001 - any failure becomes one error event
            # Exactly one terminal error event, and no completion for this stream
            # (Req 9.8). ``sequence`` continues monotonically from the last event.
            yield StreamEvent(
                type=StreamEventType.ERROR,
                data={"message": str(exc), "error_type": type(exc).__name__},
                sequence=sequence,
            )

    def iter_sse_frames(
        self,
        run_input: AgentRunInput,
        *,
        on_complete: Callable[[Completed_Run], None] | None = None,
    ) -> Iterator[str]:
        """Render :meth:`run_stream` events as SSE frames for a StreamingResponse.

        Starlette advances synchronous response iterators in an AnyIO worker context.
        Context-variable writes made while producing one frame do not flow back through
        the event loop into the worker context used for the next frame. Re-publish the
        explicit tenant before every nested-generator advance so streamed tool and trace
        work remains scoped after each yield boundary.
        """
        events = self.run_stream(run_input, on_complete=on_complete)
        while True:
            if run_input.org_id is not None:
                set_current_org(run_input.org_id)
            try:
                event = next(events)
            except StopIteration:
                return
            yield format_sse_frame(event)

    @staticmethod
    def _notify_complete(
        completed: Completed_Run | None,
        on_complete: Callable[[Completed_Run], None] | None,
    ) -> None:
        """Run the completion hook, absorbing every failure (Req 9.6, 10.2)."""
        if on_complete is None or completed is None:
            return
        try:
            on_complete(completed)
        except Exception:  # noqa: BLE001 - a side effect must not alter the stream
            logger.warning(
                "Stream completion hook failed for run %s.",
                completed.run_id,
                exc_info=True,
            )

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
