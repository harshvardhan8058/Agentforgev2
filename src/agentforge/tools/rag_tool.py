"""RAG_Tool — built-in tool wrapping the existing RAG_Service.

The RAG_Tool implements ``Tool_Interface`` with an input schema accepting a ``query``
(required) and an optional ``top_k`` result count (Req 4.1). Its ``invoke`` delegates to
the injected existing ``RAG_Service`` and returns a ``Tool_Result`` whose ``content`` is
the grounded answer text and whose ``data`` carries the associated citations plus the
``grounded`` flag and ``provider`` — it does **not** reimplement retrieval or generation
(Req 4.2, 4.3, 12.2). Because the ``RAG_Service`` already runs through the keyless
``Fallback_Provider`` when no LLM credential is configured, the RAG_Tool returns a
deterministic grounded result keylessly (Req 4.4).
"""

from __future__ import annotations

from dataclasses import asdict

from agentforge.rag.service import RAG_Service
from agentforge.tools.base import Tool_Interface, Tool_Result

# The RAG_Tool's registered name; kept as a module constant so the selection strategy and
# composition root can reference it without importing the class.
RAG_TOOL_NAME = "rag_search"

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["query"],
    "additionalProperties": False,
}


class RAG_Tool(Tool_Interface):
    """Answer a question grounded in the ingested knowledge base, with citations."""

    def __init__(self, rag_service: RAG_Service) -> None:
        self._rag = rag_service

    @property
    def name(self) -> str:
        return RAG_TOOL_NAME

    @property
    def description(self) -> str:
        return (
            "Answer a question grounded in the ingested knowledge base, "
            "returning citations to the supporting documents."
        )

    @property
    def input_schema(self) -> dict:
        return _INPUT_SCHEMA

    def invoke(self, arguments: dict) -> Tool_Result:
        """Delegate to the RAG_Service and mirror its answer and citations (Req 4.2, 4.3)."""
        answer = self._rag.answer(arguments["query"], arguments.get("top_k"))
        return Tool_Result(
            tool_name=self.name,
            ok=True,
            content=answer.text,
            data={
                "citations": [asdict(c) for c in answer.citations],
                "grounded": answer.grounded,
                "provider": answer.provider,
            },
        )
