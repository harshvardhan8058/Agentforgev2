"""Unit test asserting the RAG_Tool delegates to the RAG_Service (Req 4.2, 12.2)."""

from __future__ import annotations

from agentforge.models.domain import Citation, Grounded_Answer
from agentforge.tools.rag_tool import RAG_Tool


class _StubRAGService:
    """Records delegation so we can assert the tool reuses the RAG_Service."""

    def __init__(self) -> None:
        self.calls: list = []

    def answer(self, query, top_k=None) -> Grounded_Answer:
        self.calls.append((query, top_k))
        return Grounded_Answer(
            text="grounded",
            citations=[Citation(document_id="doc", chunk_id="chunk")],
            provider="fallback",
            grounded=True,
        )


def test_rag_tool_delegates_to_rag_service():
    """invoke() delegates to the injected RAG_Service exactly once and returns its output."""
    stub = _StubRAGService()
    tool = RAG_Tool(stub)

    result = tool.invoke({"query": "what is agentforge?"})

    # Delegation happened exactly once with the provided query.
    assert stub.calls == [("what is agentforge?", None)]
    assert result.content == "grounded"
    assert result.data["citations"] == [{"document_id": "doc", "chunk_id": "chunk"}]


def test_rag_tool_forwards_top_k():
    """An optional top_k argument is forwarded to the RAG_Service unchanged."""
    stub = _StubRAGService()
    tool = RAG_Tool(stub)

    tool.invoke({"query": "q", "top_k": 3})

    assert stub.calls == [("q", 3)]


def test_rag_tool_input_schema_declares_query_and_top_k():
    """The input schema requires query and accepts an optional top_k (Req 4.1)."""
    tool = RAG_Tool(_StubRAGService())
    schema = tool.input_schema

    assert schema["required"] == ["query"]
    assert "query" in schema["properties"]
    assert "top_k" in schema["properties"]
