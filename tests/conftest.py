"""Shared pytest fixtures and helpers for the AgentForge test suite."""

from __future__ import annotations

import logging

# Chroma's telemetry shim emits noisy (harmless) errors even when telemetry is
# disabled; silence it so test output stays readable.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

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
