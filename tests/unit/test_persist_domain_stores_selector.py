"""Unit tests for the ``Settings.persist_domain_stores()`` selector (B1, Task 1.1).

The selector splits *persistence* from *profile*: Domain_Stores are DB-backed when
persistence is explicitly enabled via ``use_database`` OR the production profile is
selected, and in-memory otherwise. The default keyless settings therefore stay in-memory,
preserving the deterministic keyless unit lane (Req 1.1, 1.3, 10.1).
"""

from __future__ import annotations

from agentforge.config.settings import Settings

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
}


def _settings(**overrides) -> Settings:
    return Settings(**{**_BASE, **overrides})


def test_selector_false_for_default_keyless_settings():
    """Default keyless settings (local profile, use_database unset) -> in-memory (Req 10.1)."""
    settings = _settings()
    assert settings.profile == "local"
    assert settings.use_database is False
    assert settings.persist_domain_stores() is False


def test_selector_true_when_use_database_enabled():
    """``use_database=True`` opts the local stack into persistence (Req 1.1, 1.3)."""
    settings = _settings(use_database=True)
    assert settings.profile == "local"
    assert settings.persist_domain_stores() is True


def test_selector_true_when_profile_production():
    """Production profile persists regardless of ``use_database`` (unchanged behavior)."""
    assert _settings(profile="production").persist_domain_stores() is True
    assert _settings(profile="production", use_database=True).persist_domain_stores() is True


def test_selector_true_when_both_axes_set():
    """Both axes on -> persistent (belt-and-suspenders, as in the production overlay)."""
    settings = _settings(profile="production", use_database=True)
    assert settings.persist_domain_stores() is True
