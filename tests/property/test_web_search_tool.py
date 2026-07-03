"""Property-based test for disabled web search (Property 11)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.tools.search.base import Search_Provider, SearchResult
from agentforge.tools.web_search_tool import UNAVAILABLE_MESSAGE, Web_Search_Tool


class _NoNetworkGuardProvider(Search_Provider):
    """A disabled provider that fails loudly if any network search is attempted."""

    def __init__(self) -> None:
        self.search_calls = 0

    @property
    def available(self) -> bool:
        return False

    def search(self, query: str) -> list[SearchResult]:
        # Reaching here would mean the tool attempted a network request while disabled.
        self.search_calls += 1
        raise AssertionError("network search attempted while disabled")


# Feature: agentforge-agentic-layer, Property 11: Disabled web search returns an
# unavailable result without network access.
@hyp_settings(max_examples=100, deadline=None)
@given(query=st.text(max_size=60))
def test_disabled_web_search_returns_unavailable_without_network(query):
    """Feature: agentforge-agentic-layer, Property 11: For any query, when the
    Web_Search_Tool is disabled (no search credential), invoking it returns a Tool_Result
    indicating web search is unavailable and performs no external network request.

    Validates: Requirements 5.4, 5.5
    """
    provider = _NoNetworkGuardProvider()
    tool = Web_Search_Tool(provider)

    result = tool.invoke({"query": query})

    # The tool mirrors the provider's disabled state.
    assert tool.available is False
    # A Tool_Result indicating unavailability is returned.
    assert result.ok is False
    assert result.content == UNAVAILABLE_MESSAGE
    # No external network request was performed.
    assert provider.search_calls == 0
