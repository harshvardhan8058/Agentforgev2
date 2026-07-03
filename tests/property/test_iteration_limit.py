"""Property-based test for Iteration_Limit resolution (Property 4)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.agent.state import (
    DEFAULT_ITERATION_LIMIT,
    resolve_iteration_limit,
)

# A broad space of configured values: valid/invalid ints, booleans, None, floats,
# strings, and out-of-range integers (including the 1/100 boundaries and just outside).
_configured_values = st.one_of(
    st.none(),
    st.integers(min_value=-50, max_value=200),
    st.sampled_from([1, 100, 0, 101, -1]),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-10, max_value=200),
    st.text(max_size=8),
)


# Feature: agentforge-agentic-layer, Property 4: Iteration_Limit resolution.
@hyp_settings(max_examples=100, deadline=None)
@given(configured=_configured_values)
def test_iteration_limit_resolution(configured):
    """Feature: agentforge-agentic-layer, Property 4: For any configured Iteration_Limit
    value, the resolved limit equals that value when it is an integer in [1, 100]; when
    absent it resolves to the default 10 with no invalid flag; and when it is a
    non-integer, a boolean, or an integer outside [1, 100], it resolves to the default 10
    and the invalid-limit indication is recorded.

    Validates: Requirements 1.5, 1.6
    """
    limit, invalid = resolve_iteration_limit(configured)

    is_valid_int = (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and 1 <= configured <= 100
    )

    if configured is None:
        assert (limit, invalid) == (DEFAULT_ITERATION_LIMIT, False)
    elif is_valid_int:
        assert (limit, invalid) == (configured, False)
    else:
        assert (limit, invalid) == (DEFAULT_ITERATION_LIMIT, True)

    # The resolved limit is always a valid in-range integer.
    assert isinstance(limit, int) and 1 <= limit <= 100
