"""Disabled_Search_Provider — the keyless default web-search provider.

This is the provider selected when no search credential is configured. It reports itself
unavailable and never performs a network request, preserving the keyless promise
(Req 5.4). The Web_Search_Tool guards on availability and therefore never calls
``search`` while disabled; the method raises defensively should it ever be called.
"""

from __future__ import annotations

from agentforge.tools.search.base import Search_Provider, SearchResult


class Disabled_Search_Provider(Search_Provider):
    """A no-network search provider used when no search credential is present."""

    @property
    def available(self) -> bool:
        return False

    def search(self, query: str) -> list[SearchResult]:
        # Never reached: the Web_Search_Tool guards on ``available`` before searching.
        # Guarding here makes an accidental call fail loudly rather than hit the network.
        raise RuntimeError("web search is disabled: no search credential configured")
