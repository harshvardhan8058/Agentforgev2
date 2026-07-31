"""Unit tests for the Configuration_Manager (Req 3.1, 3.2, 3.3, 3.4, 4.5)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from agentforge.config.settings import ConfigError, load_settings
from tests.conftest import apply_base_env


def test_loads_settings_from_environment(monkeypatch):
    """All settings load from environment variables (Req 3.1)."""
    apply_base_env(monkeypatch)
    monkeypatch.setenv("API_PORT", "9001")
    monkeypatch.setenv("PROFILE", "production")
    # The production profile requires a Token_Signing_Secret (Phase 5, Req 1.8).
    monkeypatch.setenv("JWT_SECRET", "prod-signing-secret")

    settings = load_settings()

    assert settings.api_port == 9001
    assert settings.profile == "production"
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost:5432/agentforge"
    assert settings.redis_url == "redis://localhost:6379/0"


def test_defaults_applied_for_optional_settings(monkeypatch):
    apply_base_env(monkeypatch)
    settings = load_settings()

    assert settings.profile == "local"
    assert settings.embedding_dimension == 384
    assert settings.top_k_default == 4
    assert settings.max_document_bytes == 50 * 1024 * 1024


def test_credentials_are_optional(monkeypatch):
    """Every credential is optional at startup (Req 3.2)."""
    apply_base_env(monkeypatch)
    settings = load_settings()

    assert settings.groq_api_key is None
    assert settings.hosted_embedding_api_key is None
    # Keyless -> fallback LLM and local (chroma) vector store.
    assert settings.active_llm() == "fallback"
    assert settings.active_vector_store() == "chroma"


def test_credentials_activate_providers_when_present(monkeypatch):
    apply_base_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "secret-key-value")
    monkeypatch.setenv("PROFILE", "production")
    # The production profile requires a Token_Signing_Secret (Phase 5, Req 1.8).
    monkeypatch.setenv("JWT_SECRET", "prod-signing-secret")
    settings = load_settings()

    assert isinstance(settings.groq_api_key, SecretStr)
    assert settings.active_llm() == "groq"
    assert settings.active_vector_store() == "pgvector"


def test_missing_required_setting_aborts_with_name(monkeypatch):
    """Missing required non-secret setting aborts and names the key (Req 3.3, 3.4)."""
    apply_base_env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_settings()

    assert "database_url" in excinfo.value.missing
    assert "database_url" in str(excinfo.value)


def test_missing_multiple_required_settings_named(monkeypatch):
    apply_base_env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_settings()

    assert "database_url" in excinfo.value.missing
    assert "redis_url" in excinfo.value.missing


def test_database_settings_exposed(monkeypatch):
    """DB connection settings are exposed via the Configuration_Manager (Req 4.5)."""
    apply_base_env(monkeypatch)
    settings = load_settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_embedding_dimension_exposed(monkeypatch):
    apply_base_env(monkeypatch)
    settings = load_settings()
    assert isinstance(settings.embedding_dimension, int)
    assert settings.embedding_dimension == 384



# --- outbound webhook delivery bounds ---------------------------------------------
#
# These three settings ARE the mechanism that keeps a pathological consumer cheap: a delivery
# occupies a worker thread for up to attempts x timeout. Left unvalidated,
# WEBHOOK_MAX_ATTEMPTS=1000 with WEBHOOK_TIMEOUT_SECONDS=600 was accepted, and one event could
# then occupy that worker for days. The upper bounds are the point.


def _webhook_settings(**overrides):
    from agentforge.config.settings import Settings

    base = {
        "profile": "local",
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/agentforge",
        "redis_url": "redis://localhost:6379/0",
    }
    return Settings(**{**base, **overrides})


def test_the_webhook_delivery_bounds_have_sane_defaults():
    settings = _webhook_settings()

    assert settings.webhook_max_attempts == 3
    assert settings.webhook_timeout_seconds == 4.0
    assert settings.webhook_backoff_seconds == 0.5


@pytest.mark.parametrize(
    "overrides",
    [
        {"webhook_max_attempts": 0},
        {"webhook_max_attempts": 1000},
        {"webhook_timeout_seconds": 0.0},
        {"webhook_timeout_seconds": 600.0},
        {"webhook_backoff_seconds": -1.0},
        {"webhook_backoff_seconds": 3600.0},
    ],
)
def test_an_unbounded_webhook_setting_is_refused(overrides):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _webhook_settings(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"webhook_max_attempts": 1},
        {"webhook_max_attempts": 10},
        {"webhook_timeout_seconds": 30.0},
        {"webhook_backoff_seconds": 0.0},
    ],
)
def test_the_edges_of_the_allowed_ranges_are_accepted(overrides):
    """A single attempt and a zero backoff are legitimate operator choices, not mistakes."""
    settings = _webhook_settings(**overrides)

    for field, value in overrides.items():
        assert getattr(settings, field) == value


def test_loopback_webhook_targets_are_allowed_outside_production_only():
    """So a subscription can be developed against a local listener, and never in production."""
    assert _webhook_settings().allow_loopback_webhooks() is True
    production = _webhook_settings(
        profile="production", jwt_secret="x" * 40, use_database=True
    )
    assert production.allow_loopback_webhooks() is False
