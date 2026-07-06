"""Property test: keyless local stack reaches all-healthy (Phase 9, Property 2).

Feature: agentforge-deployment, Property 2: Keyless local stack reaches all-healthy with
zero credentials.
Validates: Requirements 4.2, 20.1

For any start of the keyless Local_Compose stack with an environment containing no
credentials, the frontend, backend, PostgreSQL, and Redis all reach a healthy state and
the platform serves traffic through the single nginx Reverse_Proxy — the browser reaches
both the SPA and the API same-origin at the proxy origin.

This test requires the stack to already be running behind the proxy
(``scripts/compose_smoke.sh`` brings it up with zero credentials). It is marked
``@pytest.mark.integration`` and runs ONLY in the integration lane; the default keyless
lane (``pytest -m 'not integration'``) never starts containers or requires a network.
The proxy origin is overridable via ``AGENTFORGE_PROXY_URL`` (default http://localhost).
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.integration

PROXY_URL = os.environ.get("AGENTFORGE_PROXY_URL", "http://localhost")
STARTUP_BUDGET_SECONDS = 240


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
        time.sleep(3.0)
    return last


def test_proxy_serves_frontend_spa_keyless():
    """The frontend SPA is served through the single nginx entry point (Req 4.2, 6.4)."""
    resp = _wait_for(f"{PROXY_URL}/", STARTUP_BUDGET_SECONDS)
    assert resp is not None, "proxy never served the frontend"
    assert resp.status_code == 200
    assert "<!doctype html" in resp.text.lower()


def test_proxy_self_health_ok():
    """The proxy reports healthy at /healthz (Req 11.5)."""
    resp = _wait_for(f"{PROXY_URL}/healthz", STARTUP_BUDGET_SECONDS)
    assert resp is not None and resp.status_code == 200


def test_api_all_dependencies_healthy_through_proxy():
    """Backend + Postgres + Redis all reach healthy, reported same-origin (Req 20.1)."""
    resp = _wait_for(f"{PROXY_URL}/health/ready", STARTUP_BUDGET_SECONDS)
    assert resp is not None, "API never became ready through the proxy"
    body = resp.json()
    assert set(body["dependencies"]) == {"database", "redis"}
    assert resp.status_code == 200
    assert body["status"] == "ready"
