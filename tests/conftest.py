"""Shared pytest fixtures and helpers for the AgentForge test suite."""

from __future__ import annotations

import logging

import pytest

# Chroma's telemetry shim emits noisy (harmless) errors even when telemetry is
# disabled; silence it so test output stays readable.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)


@pytest.fixture(autouse=True)
def _reset_tenancy_context():
    """Reset the request-scoped tenancy context around every test.

    The tenancy ``org_id`` / ``user_id`` are published through process-wide context
    variables (``enterprise/tenancy``). Tests that set them directly (e.g. the Phase 6
    observability usage tests) would otherwise leak their value into later tests that
    inherit the ambient tenant (e.g. an orchestrator run invoked without an explicit
    ``org_id``). Resetting to the keyless defaults before and after each test restores
    the isolation a fresh process would have.
    """
    from agentforge.enterprise.tenancy import (
        NIL_ORG_ID,
        set_current_org,
        set_current_user,
    )

    set_current_org(NIL_ORG_ID)
    set_current_user(None)
    yield
    set_current_org(NIL_ORG_ID)
    set_current_user(None)

# Environment values used to construct a valid Settings object in tests.
BASE_ENV = {
    "PROFILE": "local",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/agentforge",
    "REDIS_URL": "redis://localhost:6379/0",
}


def apply_base_env(monkeypatch) -> None:
    """Set the minimum required non-secret settings in the environment."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    # Ensure no stray credentials leak in from the host environment.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HOSTED_EMBEDDING_API_KEY", raising=False)
