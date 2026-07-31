"""Unit tests for the Integration_Connection config admission policy (Req 11.4).

``integration_connections`` has no column that could hold a credential, which is a
guarantee about the *schema*, not about what an operator types into a free-form JSON
object. The obvious mistake — pasting a bot token in as ``{"token": "xoxb-…"}`` — would
otherwise be stored happily and become readable by anyone in the org holding ``read``.

These tests pin the policy that refuses it: credential-shaped keys, credential-shaped
values, nested structures (which would let one level of indirection evade the key check),
and unbounded payloads. Every rejection must name the field and must never echo the
submitted value, since that value may be the credential it just refused.
"""

from __future__ import annotations

import pytest

from agentforge.integrations.config_policy import (
    MAX_CONFIG_KEYS,
    MAX_KEY_LENGTH,
    MAX_VALUE_LENGTH,
    validate_connection_config,
)


# --- accepted ---------------------------------------------------------------------


def test_none_and_empty_are_accepted_as_empty():
    assert validate_connection_config(None) == {}
    assert validate_connection_config({}) == {}


def test_flat_scalar_settings_are_accepted_verbatim():
    config = {
        "default_channel": "#ops",
        "max_results": 25,
        "threshold": 0.5,
        "notify": True,
        "label": None,
    }
    assert validate_connection_config(config) == config


def test_the_returned_mapping_is_a_copy():
    """A caller mutating the result must not mutate what it submitted."""
    submitted = {"default_channel": "#ops"}
    accepted = validate_connection_config(submitted)
    accepted["default_channel"] = "#changed"
    assert submitted == {"default_channel": "#ops"}


# --- credential-shaped keys -------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "TOKEN",
        "slack_bot_token",
        "api_key",
        "apiKey",
        "client_secret",
        "password",
        "passwd",
        "credential",
        "private_key",
        "Authorization",
        "bearer",
        "refresh_token",
        "session_id",
        "access_key_id",
        "webhook_signature",
    ],
)
def test_credential_shaped_keys_are_refused(key: str):
    """The key's *intent* is what makes it dangerous: a placeholder becomes a real token."""
    with pytest.raises(ValueError) as excinfo:
        validate_connection_config({key: "placeholder"})
    assert key in str(excinfo.value)


def test_an_innocent_key_containing_a_marker_substring_is_still_refused():
    """Substring matching is deliberate: `user_token_hint` is not worth the argument."""
    with pytest.raises(ValueError):
        validate_connection_config({"user_token_hint": "x"})


# --- credential-shaped values -----------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "xoxb-1111-2222-abcdef",
        "xoxp-1111-2222",
        "xapp-1-A0000",
        "ghp_0123456789abcdef",
        "github_pat_0123456789",
        "sk-0123456789abcdef",
        "gsk_0123456789abcdef",
        "ya29.a0AfB_placeholder",
        "AIzaSyPlaceholderValue",
        "Bearer abcdef",
    ],
)
def test_credential_shaped_values_are_refused_under_any_key(value: str):
    with pytest.raises(ValueError) as excinfo:
        validate_connection_config({"default_channel": value})
    assert "default_channel" in str(excinfo.value)


def test_a_refusal_never_echoes_the_submitted_value():
    """The message may be logged or returned; it must not carry the credential."""
    secret = "xoxb-do-not-echo-this-value"
    with pytest.raises(ValueError) as excinfo:
        validate_connection_config({"channel": secret})
    assert secret not in str(excinfo.value)


# --- shape and size ---------------------------------------------------------------


@pytest.mark.parametrize("value", [{"nested": "x"}, ["a", "b"], (1, 2), {1, 2}])
def test_non_scalar_values_are_refused(value):
    """Nesting would let one level of indirection evade the credential-key check."""
    with pytest.raises(ValueError) as excinfo:
        validate_connection_config({"settings": value})
    assert "settings" in str(excinfo.value)


def test_empty_or_non_string_keys_are_refused():
    with pytest.raises(ValueError):
        validate_connection_config({"": "x"})
    with pytest.raises(ValueError):
        validate_connection_config({"   ": "x"})
    with pytest.raises(ValueError):
        validate_connection_config({1: "x"})


def test_too_many_keys_are_refused():
    config = {f"setting_{i}": "x" for i in range(MAX_CONFIG_KEYS + 1)}
    with pytest.raises(ValueError) as excinfo:
        validate_connection_config(config)
    assert str(MAX_CONFIG_KEYS) in str(excinfo.value)
    # Exactly at the limit is accepted.
    assert len(
        validate_connection_config({f"setting_{i}": "x" for i in range(MAX_CONFIG_KEYS)})
    ) == MAX_CONFIG_KEYS


def test_oversized_key_and_value_are_refused():
    with pytest.raises(ValueError):
        validate_connection_config({"k" * (MAX_KEY_LENGTH + 1): "x"})
    with pytest.raises(ValueError):
        validate_connection_config({"default_channel": "v" * (MAX_VALUE_LENGTH + 1)})
    # At the limit both are accepted.
    assert validate_connection_config(
        {"k" * MAX_KEY_LENGTH: "v" * MAX_VALUE_LENGTH}
    ) == {"k" * MAX_KEY_LENGTH: "v" * MAX_VALUE_LENGTH}
