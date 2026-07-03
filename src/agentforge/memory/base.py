"""Memory_Manager interface, MemoryError, and MemoryEntry (Pluggable Seam: memory).

The ``Memory_Manager`` provides short-term (within-run working context, bounded by a
Size_Budget with FIFO eviction that always retains the current request) and long-term
(cross-conversation semantic recall over the existing Embedding_Provider + Vector_Store)
memory to the orchestrator (Req 6, 7, 12.3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class MemoryError(RuntimeError):
    """Raised when Short_Term_Memory cannot be initialized or satisfied (Req 6.3, 6.6)."""


@dataclass
class MemoryEntry:
    """A single long-term memory record returned by retrieval."""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)


class Memory_Manager(ABC):
    """Abstract contract for short-term and long-term agent memory."""

    # --- short-term memory (within-run working context) ---
    @abstractmethod
    def init_short_term(self, user_request: str, size_budget: object) -> None:
        """Validate the Size_Budget and seed the working context with the request.

        Rejects an absent, non-numeric, or ``<= 0`` budget with ``MemoryError`` and
        maintains no short-term memory (Req 6.2, 6.3).
        """
        raise NotImplementedError

    @abstractmethod
    def add_short_term(self, entry: str) -> None:
        """Add a working-context entry, FIFO-evicting oldest-first to fit the budget.

        The current user request is always retained; if it alone exceeds the budget after
        evicting everything else, it is kept and a ``MemoryError`` is produced (Req 6.4,
        6.5, 6.6).
        """
        raise NotImplementedError

    @abstractmethod
    def short_term_entries(self) -> list[str]:
        """Return the retained working context (the current user request is present)."""
        raise NotImplementedError

    # --- long-term memory (cross-conversation semantic recall) ---
    @abstractmethod
    def persist_long_term(self, text: str, metadata: dict) -> str:
        """Store an entry as an embedding via Embedding_Provider + Vector_Store (Req 7.1)."""
        raise NotImplementedError

    @abstractmethod
    def retrieve_long_term(self, query: str, k: int) -> list[MemoryEntry]:
        """Return ``min(k, stored_count)`` entries by descending similarity (Req 7.2-7.4)."""
        raise NotImplementedError
