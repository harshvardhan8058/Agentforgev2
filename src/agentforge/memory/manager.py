"""Composite_Memory_Manager — one Memory_Manager over short-term + long-term memory.

The orchestrator depends on the abstract :class:`Memory_Manager` seam (Req 12.3). This
concrete manager composes the two building blocks behind that single contract:

* :class:`~agentforge.memory.short_term.Short_Term_Memory` — the Size_Budget-bounded FIFO
  working context of a single run (Req 6).
* :class:`~agentforge.memory.long_term.Long_Term_Memory` — semantic recall across
  conversations over the existing ``Embedding_Provider`` + ``Vector_Store`` (Req 7, 12.3).

It reimplements neither embedding nor vector storage; it only delegates. The default
``Size_Budget`` may be supplied at construction (from the Configuration_Manager) and
overridden per run via :meth:`init_short_term`.
"""

from __future__ import annotations

from collections.abc import Callable

from agentforge.embeddings.base import Embedding_Provider
from agentforge.memory.base import Memory_Manager, MemoryEntry
from agentforge.memory.long_term import Long_Term_Memory
from agentforge.memory.short_term import Short_Term_Memory
from agentforge.vectorstore.base import Vector_Store


class Composite_Memory_Manager(Memory_Manager):
    """A Memory_Manager delegating to Short_Term_Memory and Long_Term_Memory."""

    def __init__(
        self,
        embedding_provider: Embedding_Provider,
        vector_store: Vector_Store,
        *,
        size_budget: object | None = None,
        size_fn: Callable[[str], int] | None = None,
        namespace_prefix: str = "ltm",
    ) -> None:
        self._default_budget = size_budget
        self._short_term = Short_Term_Memory(size_fn=size_fn)
        self._long_term = Long_Term_Memory(
            embedding_provider, vector_store, namespace_prefix=namespace_prefix
        )

    # --- short-term memory --------------------------------------------------------
    def init_short_term(self, user_request: str, size_budget: object = None) -> None:
        """Validate the Size_Budget and seed the working context (Req 6.2, 6.3).

        Uses the per-call ``size_budget`` when provided, else the default supplied at
        construction; an absent/invalid budget is rejected by ``Short_Term_Memory``.
        """
        budget = size_budget if size_budget is not None else self._default_budget
        self._short_term.init_short_term(user_request, budget)

    def add_short_term(self, entry: str) -> None:
        """Add a working-context entry with FIFO eviction to fit the budget (Req 6.4-6.6)."""
        self._short_term.add_short_term(entry)

    def short_term_entries(self) -> list[str]:
        """Return the retained working context (the user request is always present)."""
        return self._short_term.short_term_entries()

    # --- long-term memory ---------------------------------------------------------
    def persist_long_term(self, text: str, metadata: dict, *, org_id: object = None) -> str:
        """Store an entry as an embedding, tagged with ``org_id`` (Req 7.1, 7.5, 4.1)."""
        return self._long_term.persist_long_term(text, metadata, org_id=org_id)

    def retrieve_long_term(
        self, query: str, k: int, *, org_id: object = None
    ) -> list[MemoryEntry]:
        """Return ``min(k, stored_count)`` of ``org_id``'s entries by similarity (Req 7.2-7.4)."""
        return self._long_term.retrieve_long_term(query, k, org_id=org_id)
