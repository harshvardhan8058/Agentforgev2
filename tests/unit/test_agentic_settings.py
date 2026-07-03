"""Unit tests for the Phase 3 agentic-layer settings (Req 1.5, 5.2, 5.4, 6.2)."""

from __future__ import annotations

from pydantic import SecretStr

from agentforge.config.settings import load_settings
from tests.conftest import apply_base_env


def test_agentic_settings_default_keyless(monkeypatch):
    """New agentic settings are optional and default to keyless-safe values."""
    apply_base_env(monkeypatch)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ITERATION_LIMIT", raising=False)
    monkeypatch.delenv("MEMORY_SIZE_BUDGET", raising=False)
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)

    settings = load_settings()

    assert settings.iteration_limit is None
    assert settings.memory_size_budget is None
    assert settings.search_provider == "disabled"
    assert settings.search_api_key is None


def test_active_search_disabled_without_key(monkeypatch):
    """active_search() returns 'disabled' whenever no search credential is present (Req 5.4)."""
    apply_base_env(monkeypatch)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    # Even when a provider name is configured, absence of a key disables web search.
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")

    settings = load_settings()

    assert settings.search_provider == "tavily"
    assert settings.search_api_key is None
    assert settings.active_search() == "disabled"


def test_active_search_returns_provider_when_keyed(monkeypatch):
    """active_search() returns the configured provider name when a key is present (Req 5.2)."""
    apply_base_env(monkeypatch)
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("SEARCH_API_KEY", "secret-search-key")

    settings = load_settings()

    assert isinstance(settings.search_api_key, SecretStr)
    assert settings.active_search() == "tavily"


def test_agentic_settings_parse_from_environment(monkeypatch):
    """Optional numeric settings load from the environment when provided (Req 1.5, 6.2)."""
    apply_base_env(monkeypatch)
    monkeypatch.setenv("ITERATION_LIMIT", "25")
    monkeypatch.setenv("MEMORY_SIZE_BUDGET", "2048")

    settings = load_settings()

    assert settings.iteration_limit == 25
    assert settings.memory_size_budget == 2048
