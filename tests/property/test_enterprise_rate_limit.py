"""Property test for the Rate_Limiter bound + isolation + rollover (Task 6.2 — Property 7).

Deterministic and keyless: the ``Fake_Clock_Rate_Limiter`` is driven by an injected clock
so the fixed-window bound, per-principal isolation, and window rollover are all decidable
in-process. ``max_requests`` is drawn from a modest range to keep the per-example call
count bounded while still exercising the bound universally over that range; the numeric
extremes are covered by construction of the fixed-window arithmetic.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.api.errors import AppError
from agentforge.enterprise.rate_limit import Fake_Clock_Rate_Limiter


# Feature: agentforge-enterprise, Property 7: Rate limiter bound and per-principal
# isolation.
@hyp_settings(max_examples=100, deadline=None)
@given(
    max_requests=st.integers(min_value=1, max_value=25),
    window=st.integers(min_value=1, max_value=86_400),
    start=st.integers(min_value=0, max_value=100_000),
    k1=st.uuids().map(lambda u: f"user:{u}"),
    k2=st.uuids().map(lambda u: f"key:{u}"),
)
def test_rate_limiter_bound_isolation_rollover(max_requests, window, start, k1, k2):
    """Feature: agentforge-enterprise, Property 7: Rate limiter bound and per-principal
    isolation — the first Max calls to check(k1) in a single window succeed and the
    (Max + 1)-th raises AppError("rate_limited", 429); check(k2) is counted independently
    and follows the same bound; at window rollover each key's count resets and admits Max
    more successful calls.

    Validates: Requirements 6.1, 6.2, 6.3, 6.6, 10.7
    """
    assume(k1 != k2)
    clock_state = {"now": float(start)}
    limiter = Fake_Clock_Rate_Limiter(
        max_requests=max_requests,
        window_seconds=window,
        clock=lambda: clock_state["now"],
    )

    # First Max calls for k1 succeed; the (Max + 1)-th raises 429.
    for _ in range(max_requests):
        limiter.check(k1)
    with pytest.raises(AppError) as excinfo:
        limiter.check(k1)
    assert excinfo.value.status_code == 429
    assert excinfo.value.code == "rate_limited"
    assert excinfo.value.details == {"limit": max_requests, "window_seconds": window}

    # k2 is counted independently: k1 being over the limit does not affect it (Req 6.6).
    for _ in range(max_requests):
        limiter.check(k2)
    with pytest.raises(AppError):
        limiter.check(k2)

    # Window rollover: advancing exactly one window resets both keys' counts.
    clock_state["now"] += window
    for _ in range(max_requests):
        limiter.check(k1)
        limiter.check(k2)
    with pytest.raises(AppError):
        limiter.check(k1)
    with pytest.raises(AppError):
        limiter.check(k2)
