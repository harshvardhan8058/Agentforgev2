"""Smoke tests for the Phase 5 enterprise scaffolding (Task 1.1).

Assert every ``enterprise/*`` submodule imports cleanly, the three seams
(``Identity_Store``, ``API_Key_Store``, ``Rate_Limiter``) are abstract, and the new
``Settings`` fields default to keyless-safe values in the local profile (Req 9.1, 10.1).
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from agentforge.config.settings import Settings
from agentforge.enterprise.base import API_Key_Store, Identity_Store, Rate_Limiter

_SUBMODULES = [
    "base",
    "models",
    "rbac",
    "auth",
    "identity",
    "api_keys",
    "rate_limit",
    "principal",
    "store",
]


@pytest.mark.parametrize("name", _SUBMODULES)
def test_enterprise_submodule_imports_cleanly(name):
    """Every enterprise submodule imports without error."""
    module = importlib.import_module(f"agentforge.enterprise.{name}")
    assert module is not None


@pytest.mark.parametrize("cls", [Identity_Store, API_Key_Store, Rate_Limiter])
def test_seam_is_abstract(cls):
    """The abstract seam cannot be instantiated directly."""
    assert inspect.isabstract(cls)
    with pytest.raises(TypeError):
        cls()  # type: ignore[abstract]


@pytest.mark.parametrize(
    ("cls", "expected_methods"),
    [
        (
            Identity_Store,
            {
                "create_user",
                "get_user_by_email",
                "get_user",
                "create_organization",
                "get_organization",
                "add_membership",
                "get_membership",
                "list_org_members",
                "create_team",
                "add_team_member",
            },
        ),
        (
            API_Key_Store,
            {
                "create",
                "list_active_by_prefix",
                "list_for_org",
                "get_for_org",
                "revoke_for_org",
            },
        ),
        (Rate_Limiter, {"check"}),
    ],
)
def test_seam_declares_required_abstract_methods(cls, expected_methods):
    """Each seam declares exactly the abstract operations from the design."""
    assert expected_methods.issubset(cls.__abstractmethods__)


def test_keyless_settings_defaults(monkeypatch):
    """A local-profile Settings with no Phase 5 env vars uses keyless-safe defaults."""
    monkeypatch.setenv("PROFILE", "local")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/agentforge")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    for var in (
        "AUTH_ENABLED",
        "JWT_SECRET",
        "JWT_ALGORITHM",
        "JWT_EXPIRY_SECONDS",
        "ARGON2_TIME_COST",
        "ARGON2_MEMORY_COST",
        "ARGON2_PARALLELISM",
        "RATE_LIMIT_ENABLED",
        "RATE_LIMIT_MAX",
        "RATE_LIMIT_WINDOW_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.auth_enabled is True
    assert settings.jwt_secret is None
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expiry_seconds == 3600
    assert settings.argon2_time_cost == 2
    assert settings.argon2_memory_cost == 64 * 1024
    assert settings.argon2_parallelism == 2
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_max == 60
    assert settings.rate_limit_window_seconds == 60



def _apply_prod_env(monkeypatch) -> None:
    monkeypatch.setenv("PROFILE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/agentforge")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("JWT_SECRET", raising=False)


def test_load_settings_requires_jwt_secret_in_production(monkeypatch):
    """load_settings aborts naming jwt_secret when production omits it (Req 1.8)."""
    from agentforge.config.settings import ConfigError, load_settings

    _apply_prod_env(monkeypatch)

    with pytest.raises(ConfigError) as exc_info:
        load_settings()
    assert "jwt_secret" in exc_info.value.missing


def test_load_settings_allows_production_with_jwt_secret(monkeypatch):
    """A production profile with a jwt_secret loads successfully."""
    from agentforge.config.settings import load_settings

    _apply_prod_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "a-strong-production-secret-over-32-bytes")

    settings = load_settings()
    assert settings.profile == "production"
    assert settings.jwt_secret is not None
    assert settings.jwt_secret.get_secret_value() == "a-strong-production-secret-over-32-bytes"


def test_load_settings_skips_guard_when_auth_disabled(monkeypatch):
    """When auth is disabled, production boot does not require a jwt_secret."""
    from agentforge.config.settings import load_settings

    _apply_prod_env(monkeypatch)
    monkeypatch.setenv("AUTH_ENABLED", "false")

    settings = load_settings()
    assert settings.auth_enabled is False
    assert settings.jwt_secret is None


# --- Token_Signing_Secret strength guard (RFC 7518 §3.2) ---------------------------


def test_load_settings_rejects_weak_jwt_secret_in_production(monkeypatch):
    """A production jwt_secret shorter than the HS256 key minimum aborts startup.

    HS256 is HMAC-SHA-256, so RFC 7518 §3.2 requires a key of at least the 32-byte hash
    output size. A shorter secret makes Access_Tokens cheaper to forge, which would let an
    attacker mint arbitrary ``org_id``/``role`` claims and defeat RBAC + tenant isolation.
    """
    from agentforge.config.settings import MIN_JWT_SECRET_BYTES, ConfigError, load_settings

    _apply_prod_env(monkeypatch)
    weak = "x" * (MIN_JWT_SECRET_BYTES - 1)
    monkeypatch.setenv("JWT_SECRET", weak)

    with pytest.raises(ConfigError) as exc_info:
        load_settings()
    assert "jwt_secret" in exc_info.value.missing
    # The abort names the setting and the requirement, and never leaks the value itself.
    assert weak not in str(exc_info.value)


def test_load_settings_accepts_jwt_secret_at_exact_minimum(monkeypatch):
    """A secret at exactly the minimum length is accepted (boundary is inclusive)."""
    from agentforge.config.settings import MIN_JWT_SECRET_BYTES, load_settings

    _apply_prod_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "y" * MIN_JWT_SECRET_BYTES)

    settings = load_settings()
    assert len(settings.jwt_secret.get_secret_value()) == MIN_JWT_SECRET_BYTES


def test_generated_local_dev_secret_satisfies_the_production_minimum():
    """The per-boot local dev secret is well above the HS256 minimum.

    Guards against the guard only being satisfiable in production: the keyless local boot
    path must never generate a secret that production would reject.
    """
    from agentforge.config.settings import MIN_JWT_SECRET_BYTES, Settings
    from agentforge.config.container import build_auth_service
    from agentforge.enterprise.identity import InMemory_Identity_Store

    settings = Settings(  # type: ignore[call-arg]
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )
    auth = build_auth_service(settings, InMemory_Identity_Store())
    assert len(auth._secret.encode("utf-8")) >= MIN_JWT_SECRET_BYTES
