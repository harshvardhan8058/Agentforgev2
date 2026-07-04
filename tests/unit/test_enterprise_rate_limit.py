"""Unit tests for the Rate_Limiter implementations (Task 6.3).

Cover window rollover under the ``Fake_Clock_Rate_Limiter`` and the pass-through
``NoOp_Rate_Limiter`` (the keyless default).
"""

from __future__ import annotations

import pytest

from agentforge.api.errors import AppError
from agentforge.enterprise.rate_limit import (
    Fake_Clock_Rate_Limiter,
    NoOp_Rate_Limiter,
)


def test_window_rollover_resets_count():
    """A principal fills the window, the clock advances one full window, Max more succeed."""
    now = {"t": 1000.0}
    limiter = Fake_Clock_Rate_Limiter(
        max_requests=3, window_seconds=60, clock=lambda: now["t"]
    )

    # Fill the window.
    for _ in range(3):
        limiter.check("user:alice")
    with pytest.raises(AppError) as excinfo:
        limiter.check("user:alice")
    assert excinfo.value.status_code == 429

    # Advance one full window; the count resets and Max more calls succeed.
    now["t"] += 60
    for _ in range(3):
        limiter.check("user:alice")
    with pytest.raises(AppError):
        limiter.check("user:alice")


def test_partial_advance_within_window_does_not_reset():
    """Advancing less than a full window keeps the same counter bucket."""
    now = {"t": 0.0}
    limiter = Fake_Clock_Rate_Limiter(
        max_requests=2, window_seconds=100, clock=lambda: now["t"]
    )
    limiter.check("k1")
    now["t"] += 50  # still within the first window
    limiter.check("k1")
    with pytest.raises(AppError):
        limiter.check("k1")


def test_noop_limiter_never_raises():
    """The keyless-default NoOp limiter permits unbounded requests."""
    limiter = NoOp_Rate_Limiter()
    for _ in range(1000):
        limiter.check("anyone")
