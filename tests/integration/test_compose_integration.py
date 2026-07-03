"""Integration test: Docker Compose startup and reachability (Req 5.1-5.4, 14.1).

Requires the Docker Compose stack to be running (`docker compose up`). Excluded
from the default suite; run with `pytest -m integration`. The target base URL can be
overridden via ``AGENTFORGE_BASE_URL`` (default http://localhost:8000).
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("AGENTFORGE_BASE_URL", "http://localhost:8000")
STARTUP_BUDGET_SECONDS = 60


def _wait_for(url: str, budget: int) -> httpx.Response | None:
    deadline = time.monotonic() + budget
    last: httpx.Response | None = None
    while time.monotonic() < deadline:
        try:
            last = httpx.get(url, timeout=5.0)
            if last.status_code == 200:
                return last
        except httpx.HTTPError:
            pass
        time.sleep(2.0)
    return last


def test_api_reachable_within_budget():
    """The API becomes reachable on the documented port within 60s (Req 5.3)."""
    resp = _wait_for(f"{BASE_URL}/health/live", STARTUP_BUDGET_SECONDS)
    assert resp is not None, "API never became reachable"
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_readiness_reports_dependencies():
    """Readiness reports Postgres + Redis once the full stack is up (Req 5.1, 5.2)."""
    resp = _wait_for(f"{BASE_URL}/health/ready", STARTUP_BUDGET_SECONDS)
    assert resp is not None
    body = resp.json()
    assert "dependencies" in body
    assert set(body["dependencies"]) == {"database", "redis"}
    # When the whole stack is healthy this should be ready/200.
    assert resp.status_code == 200
    assert body["status"] == "ready"
