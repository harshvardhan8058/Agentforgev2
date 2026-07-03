"""Web_Search_Tool — built-in web search with graceful degradation.

The Web_Search_Tool implements ``Tool_Interface`` with a ``query`` input schema (Req 5.1)
and performs searches through a pluggable ``Search_Provider`` selected by the
Configuration_Manager (Req 5.2). Its ``available`` mirrors the provider, so a disabled
tool is never offered to the LLM (Req 5.3, 5.4). When the provider is disabled, ``invoke``
returns a ``Tool_Result`` indicating web search is unavailable and performs **no** external
network request (Req 5.4, 5.5); otherwise it formats the provider's results.
"""

from __future__ import annotations

from dataclasses import asdict

from agentforge.tools.base import Tool_Interface, Tool_Result
from agentforge.tools.search.base import Search_Provider, SearchResult

WEB_SEARCH_TOOL_NAME = "web_search"

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
    },
    "required": ["query"],
    "additionalProperties": False,
}

# The message returned when web search is invoked while disabled (Req 5.5).
UNAVAILABLE_MESSAGE = "web search is unavailable"


class Web_Search_Tool(Tool_Interface):
    """Search the public web for information beyond the knowledge base."""

    def __init__(self, provider: Search_Provider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return WEB_SEARCH_TOOL_NAME

    @property
    def description(self) -> str:
        return "Search the public web for information beyond the knowledge base."

    @property
    def input_schema(self) -> dict:
        return _INPUT_SCHEMA

    @property
    def available(self) -> bool:
        """Mirror the provider so a disabled tool is never offered (Req 5.3, 5.4)."""
        return self._provider.available

    def invoke(self, arguments: dict) -> Tool_Result:
        """Search via the provider, or report unavailable without any network call."""
        if not self._provider.available:
            # Disabled: no external network request is performed (Req 5.4, 5.5).
            return Tool_Result(
                tool_name=self.name,
                ok=False,
                content=UNAVAILABLE_MESSAGE,
            )
        results = self._provider.search(arguments["query"])
        return Tool_Result(
            tool_name=self.name,
            ok=True,
            content=_format_results(results),
            data={"results": [asdict(r) for r in results]},
        )


def _format_results(results: list[SearchResult]) -> str:
    """Render search results into a compact human-readable summary."""
    if not results:
        return "no results found"
    return "\n".join(f"{r.title} — {r.url}\n{r.snippet}" for r in results)
