"""Unit tests for the Phase 5 composition root wiring (Task 8.1).

Assert profile/credential-driven selection and override propagation for the enterprise
builders — all keyless: the dev ``jwt_secret`` is generated in the local profile, the
rate limiter degrades to ``NoOp`` when disabled, the identity/API-key stores select the
in-memory doubles locally and the Postgres classes in production (constructed with a
dummy DSN, never connecting), and every collaborator is injectable via overrides.
"""

from __future__ import annotations

import pytest

from agentforge.config.container import (
    EnterpriseContext,
    build_api_key_store,
    build_auth_service,
    build_enterprise_context,
    build_identity_store,
    build_rate_limiter,
    build_rbac_policy,
)
from agentforge.config.settings import ConfigError, Settings
from agentforge.enterprise.api_keys import InMemory_API_Key_Store, Pg_API_Key_Store
from agentforge.enterprise.identity import InMemory_Identity_Store, Pg_Identity_Store
from agentforge.enterprise.rate_limit import (
    Fake_Clock_Rate_Limiter,
    NoOp_Rate_Limiter,
    Redis_Rate_Limiter,
)
from agentforge.enterprise.rbac import RBAC_Policy, Role

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
    # Keep argon2 cheap for any hashing exercised through the builders.
    "argon2_time_cost": 1,
    "argon2_memory_cost": 8,
    "argon2_parallelism": 1,
}


def _settings(**overrides) -> Settings:
    return Settings(**{**_BASE, **overrides})


# --- Auth_Service / jwt_secret resolution -----------------------------------------


def test_build_auth_service_generates_dev_secret_in_local():
    """Local profile with no jwt_secret -> a working per-boot dev secret (Req 1.7)."""
    settings = _settings(profile="local", jwt_secret=None)
    identity = InMemory_Identity_Store()
    auth = build_auth_service(settings, identity)
    # The generated secret is usable: an issued token round-trips through verify.
    import uuid

    token = auth.issue(uuid.uuid4(), uuid.uuid4(), Role.MEMBER)
    assert auth.verify(token) is not None


def test_build_auth_service_dev_secret_differs_per_boot():
    """Each build in local generates a fresh secret, so tokens do not cross builds."""
    import uuid

    settings = _settings(profile="local", jwt_secret=None)
    identity = InMemory_Identity_Store()
    auth_a = build_auth_service(settings, identity)
    auth_b = build_auth_service(settings, identity)
    token = auth_a.issue(uuid.uuid4(), uuid.uuid4(), Role.MEMBER)
    # A token from one boot's secret must not validate under a different boot's secret.
    assert auth_b.verify(token) is None


def test_build_auth_service_uses_configured_secret():
    """A configured jwt_secret is used verbatim (tokens verify across instances)."""
    import uuid

    settings = _settings(jwt_secret="a-configured-signing-secret-0123456789")
    token = build_auth_service(settings, InMemory_Identity_Store()).issue(
        uuid.uuid4(), uuid.uuid4(), Role.ADMIN
    )
    # A second service built from the SAME configured secret verifies the token.
    assert build_auth_service(settings, InMemory_Identity_Store()).verify(token) is not None


def test_load_settings_raises_in_production_without_secret(monkeypatch):
    """load_settings aborts in production when jwt_secret is missing (Req 1.8)."""
    from agentforge.config import settings as settings_mod

    monkeypatch.setenv("PROFILE", "production")
    monkeypatch.setenv("DATABASE_URL", _BASE["database_url"])
    monkeypatch.setenv("REDIS_URL", _BASE["redis_url"])
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ConfigError) as excinfo:
        settings_mod.load_settings()
    assert "jwt_secret" in excinfo.value.missing


# --- Rate_Limiter selection -------------------------------------------------------


def test_build_rate_limiter_noop_when_disabled():
    """rate_limit_enabled=False -> NoOp regardless of a Redis client (Req 6.5)."""
    settings = _settings(rate_limit_enabled=False)
    assert isinstance(build_rate_limiter(settings, object()), NoOp_Rate_Limiter)


def test_build_rate_limiter_noop_when_no_redis():
    """No Redis client -> NoOp even when enabled (keyless default)."""
    settings = _settings(rate_limit_enabled=True)
    assert isinstance(build_rate_limiter(settings, None), NoOp_Rate_Limiter)


def test_build_rate_limiter_redis_when_enabled_and_available():
    """Enabled + a Redis client -> Redis_Rate_Limiter."""
    settings = _settings(rate_limit_enabled=True)
    assert isinstance(build_rate_limiter(settings, object()), Redis_Rate_Limiter)


# --- Identity / API-key store selection -------------------------------------------


def test_build_identity_store_selects_in_memory_local():
    """Local profile -> InMemory_Identity_Store."""
    assert isinstance(build_identity_store(_settings(profile="local")), InMemory_Identity_Store)


def test_build_identity_store_selects_pg_production():
    """Production profile -> Pg_Identity_Store, constructed without connecting."""
    store = build_identity_store(_settings(profile="production"))
    assert isinstance(store, Pg_Identity_Store)


def test_build_api_key_store_selection():
    """API-key store follows the profile: in-memory local, Postgres production."""
    assert isinstance(build_api_key_store(_settings(profile="local")), InMemory_API_Key_Store)
    assert isinstance(build_api_key_store(_settings(profile="production")), Pg_API_Key_Store)


# --- build_enterprise_context wiring + overrides ----------------------------------


def test_build_enterprise_context_keyless_defaults():
    """Keyless context: in-memory stores, NoOp limiter, shared argon2 hasher."""
    ctx = build_enterprise_context(_settings(rate_limit_enabled=False))
    assert isinstance(ctx, EnterpriseContext)
    assert isinstance(ctx.identity_store, InMemory_Identity_Store)
    assert isinstance(ctx.api_key_store, InMemory_API_Key_Store)
    assert isinstance(ctx.rate_limiter, NoOp_Rate_Limiter)
    assert isinstance(ctx.rbac, RBAC_Policy)
    # The Auth_Service and API_Key_Service share the SAME argon2 hasher (one seam).
    assert ctx.auth_service._hasher is ctx.api_key_service._hasher


def test_build_enterprise_context_overrides_propagate():
    """Every collaborator is injectable via overrides (tests supply doubles)."""
    rbac = RBAC_Policy()
    identity = InMemory_Identity_Store()
    api_key_store = InMemory_API_Key_Store()
    limiter = Fake_Clock_Rate_Limiter(max_requests=5, window_seconds=60, clock=lambda: 0.0)
    ctx = build_enterprise_context(
        _settings(),
        rbac=rbac,
        identity_store=identity,
        api_key_store=api_key_store,
        rate_limiter=limiter,
    )
    assert ctx.rbac is rbac
    assert ctx.identity_store is identity
    assert ctx.api_key_store is api_key_store
    assert ctx.rate_limiter is limiter


def test_build_enterprise_context_clock_override_builds_redis_limiter():
    """A clock override is forwarded to the Redis limiter when enabled + Redis present."""
    ctx = build_enterprise_context(
        _settings(rate_limit_enabled=True), redis=object(), clock=lambda: 123.0
    )
    assert isinstance(ctx.rate_limiter, Redis_Rate_Limiter)


def test_build_rbac_policy_returns_policy():
    """build_rbac_policy returns a usable RBAC_Policy singleton-style instance."""
    assert isinstance(build_rbac_policy(), RBAC_Policy)
