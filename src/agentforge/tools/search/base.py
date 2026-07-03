"""Search_Provider interface and SearchResult (Pluggable Seam: web search).

The Web_Search_Tool performs searches through this abstract ``Search_Provider`` selected
by the Configuration_Manager (Req 5.2). Concrete providers live in sibling modules; the
keyless default (``Disabled_Search_Provider``) reports itself unavailable and performs no
network request (Req 5.4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """A single web search hit returned by a Search_Provider."""

    title: str
    url: str
    snippet: str


class Search_Provider(ABC):
    """Abstract contract for performing external web searches."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether searches can be performed (i.e. a credential is configured)."""
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str) -> list[SearchResult]:
        """Return search results for ``query`` (only called when ``available``)."""
        raise NotImplementedError
