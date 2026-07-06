"""Unit tests for the Phase 8 integration settings (task 2.4).

Cover credential redaction, keyless defaults (every integration Disabled with no env), and
the bounded timeout / result-cap defaults (Req 3.8, 4.2, 6.4).
"""

from __future__ import annotations

from pydantic import SecretStr

from agentforge.config.settings import Settings, load_settings
from agentforge.integrations import INTEGRATION_NAMES
from tests.conftest import apply_base_env

_CREDENTIAL_ATTRS = (
    "slack_bot_token",
    "gmail_token",
    "google_drive_token",
    "github_token",
)


def _clear_integration_env(monkeypatch) -> None:
    for env in (
        "SLACK_BOT_TOKEN",
        "GMAIL_TOKEN",
        "GOOGLE_DRIVE_TOKEN",
        "GITHUB_TOKEN",
        "SLACK_ENABLED",
        "GMAIL_ENABLED",
        "GOOGLE_DRIVE_ENABLED",
        "GITHUB_ENABLED",
        "INTEGRATION_TIMEOUT_SECONDS",
        "INTEGRATION_MAX_RESULTS",
    ):
        monkeypatch.delenv(env, raising=False)


def test_integration_credentials_optional_and_absent_by_default(monkeypatch):
    """Each integration credential is optional and absent by default (Req 3.3, 3.8)."""
    apply_base_env(monkeypatch)
    _clear_integration_env(monkeypatch)

    settings = load_settings()

    for attr in _CREDENTIAL_ATTRS:
        assert getattr(settings, attr) is None


def test_keyless_defaults_leave_every_integration_disabled(monkeypatch):
    """With no integration credential configured, every integration is Disabled (Req 3.1, 3.8)."""
    apply_base_env(monkeypatch)
    _clear_integration_env(monkeypatch)

    settings = load_settings()

    for name in INTEGRATION_NAMES:
        assert settings.integration_enabled(name) is False


def test_enable_toggle_and_limit_defaults(monkeypatch):
    """Enable toggles default True and the bounded limits carry keyless-safe defaults (Req 6.4)."""
    apply_base_env(monkeypatch)
    _clear_integration_env(monkeypatch)

    settings = load_settings()

    assert settings.slack_enabled is True
    assert settings.gmail_enabled is True
    assert settings.google_drive_enabled is True
    assert settings.github_enabled is True
    assert settings.integration_timeout_seconds == 10
    assert settings.integration_max_results == 20


def test_present_credential_with_toggle_false_is_disabled(monkeypatch):
    """A present Credential with the Enable_Setting false is Disabled (Req 3.7)."""
    apply_base_env(monkeypatch)
    _clear_integration_env(monkeypatch)

    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        github_token="SEKRET-github",
        github_enabled=False,
    )  # type: ignore[call-arg]

    assert settings.github_token is not None
    assert settings.integration_enabled("github") is False


def test_integration_credentials_are_redacted():
    """Integration credentials are SecretStr and never appear in repr / str / model_dump (Req 4.2)."""
    secret = "SEKRET-TOKEN-integration-value"
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        slack_bot_token=secret,
        gmail_token=secret,
        google_drive_token=secret,
        github_token=secret,
    )  # type: ignore[call-arg]

    # Recoverable only via the explicit accessor.
    assert isinstance(settings.slack_bot_token, SecretStr)
    assert settings.slack_bot_token.get_secret_value() == secret

    # Never present in any serialized / rendered form.
    dumped = str(settings.model_dump())
    dumped_json = settings.model_dump_json()
    for blob in (repr(settings), str(settings), dumped, dumped_json):
        assert secret not in blob
