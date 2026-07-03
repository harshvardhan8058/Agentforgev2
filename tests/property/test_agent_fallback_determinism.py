"""Property-based test for end-to-end fallback determinism (Property 19).

Runs fully keyless: the orchestrator is driven by the deterministic ``Fallback_Provider``
with the default deterministic fallback selection strategy, a ``RAG_Tool`` wrapping a
deterministic RAG double, and a disabled web search. Two runs with identical input must
produce an identical final answer, an identical ordered tool-call sequence, and an
identical ordered sequence of streamed events (Req 1.8, 3.5, 9.7).
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.models.domain import Citation, Grounded_Answer
from agentforge.streaming.base import AgentRunInput
from agentforge.streaming.sse import SSE_Streaming_Service
from agentforge.tools.rag_tool import RAG_Tool
from agentforge.tools.registry import Tool_Registry
from agentforge.llm.fallback_provider import Fallback_Provider


class _DeterministicRAG:
    """A deterministic RAG_Service double: the answer is a pure function of the query."""

    def answer(self, query: str, top_k: int | None = None) -> Grounded_Answer:
        return Grounded_Answer(
            text=f"grounded:{query}",
            citations=[Citation(document_id="doc-1", chunk_id="chunk-1")],
            provider="fallback",
            grounded=True,
        )


def _build_service() -> SSE_Streaming_Service:
    registry = Tool_Registry()
    registry.register(RAG_Tool(_DeterministicRAG()))
    orchestrator = Agent_Orchestrator(
        Fallback_Provider(), registry, iteration_limit=10
    )
    return SSE_Streaming_Service(orchestrator)


def _event_signature(run_input: AgentRunInput):
    """Return a comparable signature of the ordered streamed events for a run."""
    events = list(_build_service().run_stream(run_input))
    return [(e.sequence, e.type.value, e.data) for e in events]


# Feature: agentforge-agentic-layer, Property 19: Fallback determinism of answer and
# event sequence.
@hyp_settings(max_examples=100, deadline=None)
@given(message=st.text(min_size=1, max_size=60))
def test_fallback_determinism_of_answer_and_event_sequence(message):
    """Feature: agentforge-agentic-layer, Property 19: For any two Agent_Runs with
    identical input executed under the Fallback_Provider with no LLM or search credential,
    the runs produce an identical final answer, an identical ordered sequence of tool
    calls, and an identical ordered sequence of streamed events.

    Validates: Requirements 1.8, 3.5, 9.7
    """
    # Identical final answer and identical ordered tool-call sequence (non-streaming).
    first_state = _build_service()._orchestrator.run(message, conversation_id="fixed")
    second_state = _build_service()._orchestrator.run(message, conversation_id="fixed")

    assert first_state.final_answer == second_state.final_answer
    first_tools = [o.tool_name for o in first_state.observations]
    second_tools = [o.tool_name for o in second_state.observations]
    assert first_tools == second_tools

    # Identical ordered sequence of streamed events (excluding the volatile run_id,
    # which is a fresh UUID per run and does not reflect production order).
    sig_a = _event_signature(AgentRunInput(message=message, conversation_id="fixed"))
    sig_b = _event_signature(AgentRunInput(message=message, conversation_id="fixed"))

    def _strip_run_id(signature):
        cleaned = []
        for sequence, type_name, data in signature:
            data = {k: v for k, v in data.items() if k != "run_id"}
            cleaned.append((sequence, type_name, data))
        return cleaned

    assert _strip_run_id(sig_a) == _strip_run_id(sig_b)
