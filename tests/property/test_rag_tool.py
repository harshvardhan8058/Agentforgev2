"""Property-based test for the RAG_Tool answer/citation mirroring (Property 12)."""

from __future__ import annotations

from dataclasses import asdict

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.models.domain import Citation, Grounded_Answer
from agentforge.tools.rag_tool import RAG_Tool


class _FakeRAGService:
    """A stand-in RAG_Service that returns a preset Grounded_Answer."""

    def __init__(self, answer: Grounded_Answer) -> None:
        self._answer = answer
        self.calls: list = []

    def answer(self, query, top_k=None) -> Grounded_Answer:
        self.calls.append((query, top_k))
        return self._answer


@st.composite
def _grounded_answers(draw):
    text = draw(st.text(max_size=60))
    n = draw(st.integers(min_value=0, max_value=5))
    citations = [
        Citation(
            document_id=draw(st.text(min_size=1, max_size=8)),
            chunk_id=draw(st.text(min_size=1, max_size=8)),
        )
        for _ in range(n)
    ]
    provider = draw(st.sampled_from(["fallback", "groq", "spy"]))
    grounded = draw(st.booleans())
    return Grounded_Answer(
        text=text, citations=citations, provider=provider, grounded=grounded
    )


# Feature: agentforge-agentic-layer, Property 12: RAG_Tool mirrors the RAG_Service answer
# and citations.
@hyp_settings(max_examples=100, deadline=None)
@given(answer=_grounded_answers(), query=st.text(min_size=1, max_size=40))
def test_rag_tool_mirrors_answer_and_citations(answer, query):
    """Feature: agentforge-agentic-layer, Property 12: For any grounded answer produced by
    the RAG_Service, the RAG_Tool's Tool_Result content equals the answer text and carries
    exactly the answer's citations, without altering or inventing citations.

    Validates: Requirements 4.3
    """
    tool = RAG_Tool(_FakeRAGService(answer))

    result = tool.invoke({"query": query})

    # Content mirrors the answer text exactly.
    assert result.content == answer.text
    # Citations are exactly those from the answer, in order, unaltered.
    assert result.data["citations"] == [asdict(c) for c in answer.citations]
    # The grounded flag and provider are mirrored faithfully.
    assert result.data["grounded"] == answer.grounded
    assert result.data["provider"] == answer.provider
    assert result.tool_name == "rag_search"
    assert result.ok is True
