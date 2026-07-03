"""Keyed_Search_Provider — a credentialed web-search provider (built only when keyed).

This is the concrete provider selected when a search credential *is* configured. It is a
minimal, deterministic stand-in for a real external search API (e.g. Tavily): it reports
itself available and returns a deterministic placeholder result rather than performing a
live network call, so the composition-root registration policy (register the
Web_Search_Tool only when a key is present, Req 5.3) can be exercised without a paid key.

A real integration replaces :meth:`search` with an actual HTTP call while keeping this
class behind the ``Search_Provider`` seam — the Web_Search_Tool and orchestrator are
untouched (Req 5.2, 2.5). It is never constructed on the keyless default path.
"""

from __future__ import annotations

from agentforge.tools.search.base import Search_Provider, SearchResult


class Keyed_Search_Provider(Search_Provider):
    """An available Search_Provider constructed only when a search credential is present."""

    def __init__(self, api_key: str, provider_name: str = "keyed") -> None:
        if not api_key:
            raise ValueError("Keyed_Search_Provider requires a non-empty api key")
        self._api_key = api_key
        self._provider_name = provider_name

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str) -> list[SearchResult]:
        """Return a deterministic placeholder result for ``query``.

        A real provider issues an external request here; this stand-in stays offline and
        deterministic so the keyed registration path is testable without a live API.
        """
        return [
            SearchResult(
                title=f"Result for: {query}",
                url="https://example.invalid/search",
                snippet=(
                    f"Web search via {self._provider_name} is configured; "
                    "a real provider would return live results here."
                ),
            )
        ]
