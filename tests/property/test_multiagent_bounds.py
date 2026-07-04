"""Property tests for multi-agent bound resolution (Properties 5 and 6).

Both properties exercise the pure ``resolve_max_rounds`` / ``resolve_max_revisions``
normalizers over a wide input space — valid in-range integers (including the exact
boundaries), out-of-range integers, booleans, non-integers, and the absent (``None``)
case — asserting the ``(value, invalid_flag)`` contract from the design.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.multiagent.state import (
    DEFAULT_MAX_REVISIONS,
    DEFAULT_MAX_ROUNDS,
    MAX_MAX_REVISIONS,
    MAX_MAX_ROUNDS,
    MIN_MAX_REVISIONS,
    MIN_MAX_ROUNDS,
    resolve_max_revisions,
    resolve_max_rounds,
)

# A generator spanning the whole configured-value input space: valid/invalid integers,
# booleans, non-integers, and None. Boundaries are included explicitly.
_configured_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100, max_value=200),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=8),
)


def _assert_resolution(configured, resolved, invalid, default, low, high):
    """Assert the shared (value, invalid_flag) contract for one resolution."""
    if configured is None:
        assert (resolved, invalid) == (default, False)
    elif (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and low <= configured <= high
    ):
        assert (resolved, invalid) == (configured, False)
    else:
        assert (resolved, invalid) == (default, True)


# Feature: agentforge-multi-agent, Property 5: Max_Rounds resolution
@hyp_settings(max_examples=200, deadline=None)
@given(configured=_configured_values)
def test_max_rounds_resolution(configured):
    """Feature: agentforge-multi-agent, Property 5: Max_Rounds resolution — the resolved
    bound equals the configured value when it is an integer in [1, 50]; resolves to the
    default 6 with no invalid flag when absent; and resolves to the default 6 with the
    invalid indication recorded when the value is a non-integer, a boolean, or an integer
    outside [1, 50].

    Validates: Requirements 2.5, 2.6
    """
    resolved, invalid = resolve_max_rounds(configured)
    _assert_resolution(
        configured, resolved, invalid, DEFAULT_MAX_ROUNDS, MIN_MAX_ROUNDS, MAX_MAX_ROUNDS
    )


# Feature: agentforge-multi-agent, Property 6: Max_Revisions resolution
@hyp_settings(max_examples=200, deadline=None)
@given(configured=_configured_values)
def test_max_revisions_resolution(configured):
    """Feature: agentforge-multi-agent, Property 6: Max_Revisions resolution — the resolved
    bound equals the configured value when it is an integer in [1, 20]; resolves to the
    default 3 with no invalid flag when absent; and resolves to the default 3 with the
    invalid indication recorded when the value is a non-integer, a boolean, or an integer
    outside [1, 20].

    Validates: Requirements 3.5, 3.6
    """
    resolved, invalid = resolve_max_revisions(configured)
    _assert_resolution(
        configured,
        resolved,
        invalid,
        DEFAULT_MAX_REVISIONS,
        MIN_MAX_REVISIONS,
        MAX_MAX_REVISIONS,
    )
