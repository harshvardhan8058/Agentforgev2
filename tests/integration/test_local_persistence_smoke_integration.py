"""Integration smoke (production-hardening, Task 5.1): local stack persistence survives
`docker compose restart` (B1, Req 1.2, 1.5, 9.1).

Requires the keyless Local_Stack to be running behind the nginx Reverse_Proxy
(`docker compose up`, zero credentials) AND a Docker host so this test can invoke
`docker compose restart`. Excluded from the default keyless lane; run with
`pytest -m integration` on a Docker host.

The probe writes application data through a Domain_Store (the identity store, via
`POST /auth/register-self`), restarts the stack, waits for it to return to a healthy
serving state within 180s using no credentials, and then verifies the data survived:

* re-registering the SAME email returns a duplicate-email 400 (the user row persisted), and
* logging in with the same credentials succeeds (the persisted password hash still verifies)

— i.e. field values read back after the restart equal those written before it. With the
in-memory stores (USE_DATABASE unset/false) the user would be gone after restart and the
re-registration would instead succeed with 201, so this test also guards the regression.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

PROXY_URL = os.environ.get("AGENTFORGE_PROXY_URL", "http://localhost")
# Base directory containing docker-compose.yml (repo root by default).
COMPOSE_DIR = os.environ.get("AGENTFORGE_COMPOSE_DIR", os.getcwd())
HEALTHY_BUDGET_SECONDS = 180


def _wait_until_ready(budget: int) -> httpx.Response | None:
    """Poll the same-origin readiness endpoint until it reports ready or the budget lapses."""
    deadline = time.monotonic() + budget
    last: httpx.Response | None = None
    while time.monotonic() < deadline:
        try:
            last = httpx.get(f"{PROXY_URL}/health/ready", timeout=5.0)
            if last.status_code == 200 and last.json().get("status") == "ready":
                return last
        except httpx.HTTPError:
            pass
        time.sleep(3.0)
    return last


def _restart_stack() -> None:
    """Restart the running compose stack in place (no credentials introduced)."""
    subprocess.run(
        ["docker", "compose", "restart"],
        cwd=COMPOSE_DIR,
        check=True,
        timeout=HEALTHY_BUDGET_SECONDS,
    )


def test_domain_store_data_survives_compose_restart():
    """Data written before `docker compose restart` reads back identically after it."""
    # Preconditions: the keyless stack is up and healthy through the proxy.
    ready = _wait_until_ready(HEALTHY_BUDGET_SECONDS)
    assert ready is not None and ready.status_code == 200, "stack not healthy before test"

    email = f"persist-{uuid.uuid4().hex}@example.com"
    password = "correct horse battery staple"
    org_name = f"org-{uuid.uuid4().hex}"

    # Write: register an owner user + organization (persisted via the identity Domain_Store).
    created = httpx.post(
        f"{PROXY_URL}/auth/register-self",
        json={"email": email, "password": password, "org_name": org_name},
        timeout=10.0,
    )
    assert created.status_code == 201, created.text
    assert created.json().get("access_token")

    # Restart the stack in place with zero credentials.
    _restart_stack()

    # The full stack (Frontend, Backend, PostgreSQL, Redis) returns to healthy within 180s.
    after = _wait_until_ready(HEALTHY_BUDGET_SECONDS)
    assert after is not None and after.status_code == 200, "stack not healthy after restart"
    assert set(after.json()["dependencies"]) == {"database", "redis"}

    # Read back #1: the user row persisted — a duplicate registration is now rejected (400).
    duplicate = httpx.post(
        f"{PROXY_URL}/auth/register-self",
        json={"email": email, "password": password, "org_name": org_name},
        timeout=10.0,
    )
    assert duplicate.status_code == 400, duplicate.text

    # Read back #2: the persisted password hash still verifies — login succeeds post-restart.
    login = httpx.post(
        f"{PROXY_URL}/auth/login",
        json={"email": email, "password": password},
        timeout=10.0,
    )
    assert login.status_code == 200, login.text
    assert login.json().get("access_token")
