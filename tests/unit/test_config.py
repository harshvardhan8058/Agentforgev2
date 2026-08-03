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



# --- webhook delivery bounds ------------------------------------------------------
#
# Each of these multiplies how long a worker thread can be held by somebody else's slow
# endpoint, so they are bounded at the type level and a bad value must abort startup naming
# the key — not be accepted and discovered as an outage.


def test_webhook_delivery_defaults(monkeypatch):
    """The defaults describe a DURABLE schedule: eight attempts on a 60s exponential base spans
    roughly a day, which is what "a consumer broke overnight and was fixed in the morning" needs.
    """
    apply_base_env(monkeypatch)
    settings = load_settings()
    assert settings.webhook_max_attempts == 8
    assert settings.webhook_timeout_seconds == 4.0
    assert settings.webhook_backoff_seconds == 60.0
    assert settings.webhook_max_per_org == 20
    assert settings.webhook_batch_size == 20
    assert settings.webhook_poll_seconds == 2.0
    assert settings.webhook_worker_enabled is True


def test_webhook_loopback_is_allowed_locally_and_never_in_production(monkeypatch):
    apply_base_env(monkeypatch)
    assert load_settings().allow_loopback_webhooks() is True

    monkeypatch.setenv("PROFILE", "production")
    monkeypatch.setenv("JWT_SECRET", "prod-signing-secret")
    assert load_settings().allow_loopback_webhooks() is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("WEBHOOK_MAX_ATTEMPTS", "0"),
        ("WEBHOOK_MAX_ATTEMPTS", "50"),
        ("WEBHOOK_TIMEOUT_SECONDS", "0"),
        ("WEBHOOK_TIMEOUT_SECONDS", "600"),
        ("WEBHOOK_BACKOFF_SECONDS", "0"),
        ("WEBHOOK_BACKOFF_SECONDS", "99999"),
        ("WEBHOOK_MAX_PER_ORG", "0"),
        ("WEBHOOK_MAX_PER_ORG", "10000"),
        ("WEBHOOK_BATCH_SIZE", "0"),
        ("WEBHOOK_BATCH_SIZE", "5000"),
        ("WEBHOOK_POLL_SECONDS", "0"),
        ("WEBHOOK_POLL_SECONDS", "120"),
    ],
)
def test_an_out_of_range_webhook_bound_aborts_startup_naming_the_key(
    monkeypatch, key: str, value: str
):
    apply_base_env(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError) as caught:
        load_settings()
    assert key.lower() in caught.value.missing
