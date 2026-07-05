"""Rate_Limiter implementations: Redis / NoOp / Fake_Clock (Task 6).

A per-principal **fixed-window** counter. Chosen over sliding-log for two reasons: an
atomic ``INCR`` + ``EXPIRE`` in Redis is the simplest correct implementation with
predictable memory (``O(active principals)``), and a fixed window is trivially
deterministic under an injected clock — which makes property-testing the bound
straightforward.

Three concretes ship:

* :class:`Redis_Rate_Limiter` — the production limiter, atomic ``INCR`` + ``EXPIRE`` per
  ``(principal_key, window_start)`` over the existing Redis.
* :class:`NoOp_Rate_Limiter` — the keyless default; ``check`` is a pass-through so runs
  proceed unhindered (Req 6.5).
* :class:`Fake_Clock_Rate_Limiter` — a deterministic in-memory limiter driven by an
  injected clock, used by the property/unit lanes (Req 6.5, 10.7).

The window key is per-principal, so one principal reaching the limit never affects
another's count (Req 6.6).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import status

from agentforge.api.errors import AppError
from agentforge.enterprise.base import Rate_Limiter


def _rate_limited(max_requests: int, window_seconds: int) -> AppError:
    """Build the uniform 429 error for an exceeded window (Req 6.3)."""
    return AppError(
        "rate_limited",
        "Rate limit exceeded.",
        status.HTTP_429_TOO_MANY_REQUESTS,
        {"limit": max_requests, "window_seconds": window_seconds},
    )


class Redis_Rate_Limiter(Rate_Limiter):
    """Per-principal fixed-window limiter backed by Redis (Req 6.1-6.3, 6.6, 9.4)."""

    def __init__(
        self,
        redis,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock

    def check(self, principal_key: str) -> None:
        """Count a request for ``principal_key``; raise 429 on overflow (Req 6.3)."""
        window_start = int(self._clock()) // self._window * self._window
        key = f"rl:{principal_key}:{window_start}"
        # Pipelined atomic INCR + EXPIRE: the counter is created/incremented and its TTL
        # is (re)set to the window length in a single round-trip.
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._window)
        current = pipe.execute()[0]
        if int(current) > self._max:
            raise _rate_limited(self._max, self._window)


class NoOp_Rate_Limiter(Rate_Limiter):
    """Keyless default; ``check`` is a no-op so runs proceed unhindered (Req 6.5)."""

    def check(self, principal_key: str) -> None:
        """Permit every request unconditionally."""
        return None


class Fake_Clock_Rate_Limiter(Rate_Limiter):
    """Deterministic in-memory fixed-window limiter for tests (Req 6.5, 10.7).

    Uses an injected ``clock()`` callable so property tests advance time explicitly and
    reproducibly. Counters are keyed by ``(principal_key, window_start)``, mirroring the
    Redis key layout, so per-principal isolation and window rollover behave identically.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float],
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._counters: dict[tuple[str, int], int] = {}

    def check(self, principal_key: str) -> None:
        """Count a request for ``principal_key``; raise 429 on overflow (Req 6.3)."""
        window_start = int(self._clock()) // self._window * self._window
        key = (principal_key, window_start)
        current = self._counters.get(key, 0) + 1
        self._counters[key] = current
        if current > self._max:
            raise _rate_limited(self._max, self._window)
