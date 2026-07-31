"""Admission policy for Integration_Connection config — keeps credentials out by shape.

``Integration_Connection`` persists **non-secret** per-org configuration (Req 11.4), and the
schema has no column that could hold a token. That is a structural guarantee about the
*store*; it says nothing about what an operator might type into a free-form JSON object. The
obvious mistake — pasting a bot token in as ``{"token": "xoxb-…"}`` — would be accepted by a
store that only rejects ``SecretStr`` instances, and the value would then be readable by
anyone in the org holding ``read``.

This module is the admission policy that closes that gap. It is a pure function over the
submitted mapping, so it is testable without a store, a request, or a database, and it is
applied at the boundary where untrusted input enters (the router), which is the only writer.

The rules, and why each exists:

* **Flat mapping of scalars.** Config is a handful of settings (a default channel, a repo
  name), not a document. Nested structures make the credential-shaped-key check evadable by
  one level of indirection, so they are refused outright.
* **No credential-shaped keys.** A key whose name says "secret" is refused regardless of its
  value, because the *intent* is what makes it dangerous — a placeholder today is a real
  token after someone "fills it in".
* **No credential-shaped values.** A value carrying a recognisable credential prefix
  (``xoxb-``, ``ghp_``, ``sk-``, …) is refused even under an innocent key name.
* **Bounded size.** A key count and a value length cap, so the column cannot be used as
  general-purpose storage and one row cannot be made pathologically large.

Every rejection raises ``ValueError`` naming the offending field; the caller maps that onto
the uniform ``AppError`` envelope. The policy never echoes a rejected *value* back, since
that value may be the very credential it just refused.
"""

from __future__ import annotations

from typing import Final

# A key containing any of these substrings (case-insensitive) is refused. Substring rather
# than exact match, so `slack_bot_token` and `apiKey` are caught as readily as `token`.
_CREDENTIAL_KEY_MARKERS: Final[tuple[str, ...]] = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "authorization",
    "auth_header",
    "bearer",
    "session_id",
    "access_key",
    "client_secret",
    "refresh",
    "signature",
)

# Recognisable credential prefixes for the providers this platform integrates with, plus the
# generic ones. Matched case-sensitively: these are literal vendor prefixes.
_CREDENTIAL_VALUE_PREFIXES: Final[tuple[str, ...]] = (
    "xoxb-",  # Slack bot
    "xoxp-",  # Slack user
    "xapp-",  # Slack app
    "ghp_",  # GitHub personal access token
    "gho_",  # GitHub OAuth
    "ghs_",  # GitHub server-to-server
    "github_pat_",
    "sk-",  # OpenAI-style
    "gsk_",  # Groq
    "ya29.",  # Google OAuth access token
    "AIza",  # Google API key
    "Bearer ",
)

# A config record is a handful of settings, not a document.
MAX_CONFIG_KEYS: Final[int] = 20
MAX_KEY_LENGTH: Final[int] = 64
MAX_VALUE_LENGTH: Final[int] = 512

# The scalar JSON types a setting may hold. ``None`` is allowed so a client can round-trip a
# field it does not set without special-casing it out of the object.
_ALLOWED_VALUE_TYPES: Final[tuple[type, ...]] = (str, int, float, bool, type(None))


def _is_credential_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _CREDENTIAL_KEY_MARKERS)


def _is_credential_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return any(value.startswith(prefix) for prefix in _CREDENTIAL_VALUE_PREFIXES)


def validate_connection_config(config: dict | None) -> dict[str, object]:
    """Return the accepted config, or raise ``ValueError`` naming the offending field.

    Total over its input space: any mapping either returns a copy that satisfies every rule
    above, or raises. Never raises anything other than ``ValueError``, and never includes a
    submitted *value* in the message.
    """
    materialized: dict[str, object] = dict(config or {})

    if len(materialized) > MAX_CONFIG_KEYS:
        raise ValueError(
            f"config holds {len(materialized)} keys; at most {MAX_CONFIG_KEYS} are allowed"
        )

    for key, value in materialized.items():
        if not isinstance(key, str) or key.strip() == "":
            raise ValueError("config keys must be non-empty strings")
        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(f"config key is longer than {MAX_KEY_LENGTH} characters")
        if not isinstance(value, _ALLOWED_VALUE_TYPES):
            raise ValueError(
                f"config value for {key!r} must be a string, number, boolean, or null "
                "(nested objects and arrays are not accepted)"
            )
        if _is_credential_key(key):
            raise ValueError(
                f"config key {key!r} names a credential; integration connections store "
                "NON-SECRET configuration only. Supply credentials through the server "
                "environment instead."
            )
        if _is_credential_value(value):
            raise ValueError(
                f"the value of {key!r} looks like a credential; integration connections "
                "store NON-SECRET configuration only. Supply credentials through the "
                "server environment instead."
            )
        if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
            raise ValueError(
                f"config value for {key!r} is longer than {MAX_VALUE_LENGTH} characters"
            )

    return materialized
