"""Short_Term_Memory — a Size_Budget-bounded FIFO working context (Req 6.1-6.6).

The Short_Term_Memory holds the working context of a single Agent_Run: the current user
request plus a scratchpad of recent working-context entries. It enforces a strict
``Size_Budget`` with FIFO eviction that always retains the current user request:

* :meth:`init_short_term` validates the budget — an absent, non-numeric, or ``<= 0``
  value is rejected with :class:`MemoryError` and no working context is maintained
  (Req 6.2, 6.3).
* :meth:`add_short_term` appends an entry and, when the total retained size would exceed
  the budget, evicts working-context entries oldest-first (excluding the current user
  request) until the total fits (Req 6.4). The current user request is retained through
  every add/evict (Req 6.5).
* If, after evicting every other entry, the current user request alone still exceeds the
  budget, the request is retained and a budget-cannot-be-satisfied :class:`MemoryError`
  is raised (Req 6.6) — the request is never dropped.

Entry size is measured by a pluggable ``size_fn`` (default: character count), so the same
component can be budgeted in characters or tokens without code changes.
"""

from __future__ import annotations

from collections.abc import Callable
from numbers import Real

from agentforge.memory.base import MemoryError


class Short_Term_Memory:
    """A within-run working context bounded by a Size_Budget with FIFO eviction."""

    def __init__(self, size_fn: Callable[[str], int] | None = None) -> None:
        # ``size_fn`` measures an entry's size; character count is the keyless default.
        self._size_fn: Callable[[str], int] = size_fn or (lambda text: len(text))
        self._initialized = False
        self._budget: int = 0
        self._user_request: str = ""
        # Working-context entries in FIFO (oldest-first) insertion order; the current
        # user request is tracked separately so it is never evicted (Req 6.5).
        self._entries: list[str] = []

    # --- lifecycle ----------------------------------------------------------------
    def init_short_term(self, user_request: str, size_budget: object) -> None:
        """Validate the Size_Budget and seed the working context (Req 6.2, 6.3).

        Rejects an absent, non-numeric, boolean, or ``<= 0`` budget with
        :class:`MemoryError` and maintains no short-term memory.
        """
        budget = self._validate_budget(size_budget)
        self._budget = budget
        self._user_request = user_request
        self._entries = []
        self._initialized = True

    @staticmethod
    def _validate_budget(size_budget: object) -> int:
        """Return a positive integer budget or raise :class:`MemoryError` (Req 6.3)."""
        # ``bool`` is a subclass of ``int`` but is not a meaningful budget.
        if size_budget is None or isinstance(size_budget, bool):
            raise MemoryError("a valid positive Size_Budget is required")
        if not isinstance(size_budget, Real):
            raise MemoryError("a valid positive Size_Budget is required")
        if size_budget <= 0:
            raise MemoryError("a valid positive Size_Budget is required")
        return int(size_budget)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise MemoryError("short-term memory has not been initialized")

    # --- mutation -----------------------------------------------------------------
    def add_short_term(self, entry: str) -> None:
        """Add a working-context entry, FIFO-evicting to satisfy the budget (Req 6.4-6.6).

        The newly added entry is subject to the same oldest-first eviction as any other
        working-context entry. The current user request is always retained; if it alone
        exceeds the budget after every other entry is evicted, a :class:`MemoryError`
        indicating the budget cannot be satisfied is raised with the request retained.
        """
        self._require_initialized()
        self._entries.append(entry)
        self._enforce_budget()

    def _enforce_budget(self) -> None:
        """Evict oldest-first (excluding the request) until within budget (Req 6.4-6.6)."""
        request_size = self._size_fn(self._user_request)
        # Evict oldest working-context entries first until the total fits the budget.
        while self._entries and self._total_size() > self._budget:
            self._entries.pop(0)
        # Only the request remains and it alone still exceeds the budget (Req 6.6).
        if not self._entries and request_size > self._budget:
            raise MemoryError(
                "Size_Budget cannot be satisfied by the current user request"
            )

    # --- inspection ---------------------------------------------------------------
    def short_term_entries(self) -> list[str]:
        """Return the retained working context; the user request is always present."""
        self._require_initialized()
        return [self._user_request, *self._entries]

    def _total_size(self) -> int:
        """Total retained size: the request plus all working-context entries."""
        return self._size_fn(self._user_request) + sum(
            self._size_fn(e) for e in self._entries
        )
