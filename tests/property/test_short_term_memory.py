"""Property-based tests for Short_Term_Memory (Properties 13, 14).

Both run fully keyless and dependency-free against the character-counting default
``size_fn``, exercising the Size_Budget invariant, request retention, FIFO eviction, and
budget validation across many generated inputs.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.memory.base import MemoryError
from agentforge.memory.short_term import Short_Term_Memory


# Feature: agentforge-agentic-layer, Property 13: Short-term memory size invariant with
# request retention and FIFO eviction.
@hyp_settings(max_examples=200, deadline=None)
@given(
    user_request=st.text(min_size=0, max_size=30),
    budget=st.integers(min_value=1, max_value=40),
    entries=st.lists(st.text(min_size=0, max_size=20), max_size=25),
)
def test_short_term_size_invariant_retention_and_fifo(user_request, budget, entries):
    """Feature: agentforge-agentic-layer, Property 13: For any valid positive Size_Budget
    and any sequence of add operations, after each operation the current user request
    remains present and the total retained size is <= the Size_Budget; when an add would
    exceed the budget, working-context entries are evicted oldest-first (FIFO) excluding
    the current user request; and if the current user request alone exceeds the budget
    after all other entries are evicted, the request is retained and a
    budget-cannot-be-satisfied indication is produced.

    Validates: Requirements 6.4, 6.5, 6.6
    """
    memory = Short_Term_Memory()
    memory.init_short_term(user_request, budget)

    added: list[str] = []
    for entry in entries:
        added.append(entry)
        budget_cannot_be_satisfied = False
        try:
            memory.add_short_term(entry)
        except MemoryError:
            budget_cannot_be_satisfied = True

        retained = memory.short_term_entries()
        # The current user request is retained through every add/evict (Req 6.5).
        assert retained[0] == user_request
        survivors = retained[1:]

        # FIFO: survivors are always a contiguous suffix of the appended order (Req 6.4).
        if survivors:
            assert survivors == added[len(added) - len(survivors):]

        total = len(user_request) + sum(len(s) for s in survivors)
        if budget_cannot_be_satisfied:
            # The request alone exceeds the budget: it is retained, all else evicted,
            # and the budget-cannot-be-satisfied indication was produced (Req 6.6).
            assert len(user_request) > budget
            assert survivors == []
        else:
            # After a successful op the total retained size fits the budget (Req 6.5).
            assert total <= budget


# Feature: agentforge-agentic-layer, Property 14: Invalid Size_Budget is rejected.
@hyp_settings(max_examples=100, deadline=None)
@given(
    user_request=st.text(max_size=30),
    bad_budget=st.one_of(
        st.none(),
        st.text(max_size=5),
        st.booleans(),
        st.integers(max_value=0),
        st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    ),
)
def test_invalid_size_budget_is_rejected(user_request, bad_budget):
    """Feature: agentforge-agentic-layer, Property 14: For any Size_Budget value that is
    absent, non-numeric, or <= 0, initializing the Short_Term_Memory produces an error
    indication and no Short_Term_Memory is maintained.

    Validates: Requirements 6.3
    """
    memory = Short_Term_Memory()
    with pytest.raises(MemoryError):
        memory.init_short_term(user_request, bad_budget)

    # No short-term memory is maintained: inspection also errors (not initialized).
    with pytest.raises(MemoryError):
        memory.short_term_entries()
