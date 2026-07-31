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
* **No credential-shaped values.** Three shapes, because name-based checks alone miss the
  credentials people actually paste into connector settings:

  1. a recognisable vendor prefix (``xoxb-``, ``ghp_``, ``sk-``, …), matched **case-folded**
     — the same token pasted in upper case is the same token;
  2. a URL carrying **userinfo** (``postgresql://user:pw@host/db``) or a known
     **webhook** host (``hooks.slack.com``, Discord, Teams, Google Chat). An incoming-webhook
     URL *is* a bearer capability: possession is authority to post;
  3. a **JWT** (``eyJ`` — a base64url-encoded ``{"`` header), which is a bearer token
     whatever field it is sitting in.
* **Bounded size.** A key count and a value length cap, so the column cannot be used as
  general-purpose storage and one row cannot be made pathologically large.

Every rejection raises ``ValueError`` naming the offending field; the caller maps that onto
the uniform ``AppError`` envelope. The policy never echoes a rejected *value* back, since
that value may be the very credential it just refused.
"""

from __future__ import annotations

import re
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
    "session=",
    "access_key",
    "client_secret",
    "refresh",
    "signature",
    # Names that carry a capability without ever saying "secret":
    "cookie",
    "webhook",
    "hook_url",
)

# Markers matched against whole *segments* of the key rather than as substrings, because as
# substrings they produce false positives on ordinary settings: "pat" appears inside
# `folder_path`, and "key" inside `keyboard_shortcut`. A key is segmented on non-alphanumeric
# boundaries and camelCase, so `ssh_key`, `signingKey` and `deploy-key` are all caught while
# `folder_path` is not.
_CREDENTIAL_KEY_SEGMENTS: Final[tuple[str, ...]] = (
    "key",
    "keys",
    "pat",  # GitHub's own term for a personal access token
    "dsn",
    "auth",
)

# Recognisable credential prefixes for the providers this platform integrates with, plus the
# generic ones. Matched against a CASE-FOLDED value: an operator pasting `XOXB-…` has pasted
# the same token, and `Bearer`/`bearer` are both common in copied header values.
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
    "aiza",  # Google API key
    "bearer ",
    "eyj",  # a JWT: base64url of `{"`, so any signed bearer token
    "akia",  # AWS access key id
    "asia",  # AWS temporary access key id
    "-----begin",  # a PEM private key block
)

# Hosts whose URLs are themselves capabilities: possession of the URL is authority to post.
_WEBHOOK_HOSTS: Final[tuple[str, ...]] = (
    "hooks.slack.com",
    "discord.com/api/webhooks",
    "discordapp.com/api/webhooks",
    "outlook.office.com/webhook",
    "webhook.office.com",
    "chat.googleapis.com",
    "hooks.zapier.com",
)

# A config record is a handful of settings, not a document.
MAX_CONFIG_KEYS: Final[int] = 20
MAX_KEY_LENGTH: Final[int] = 64
MAX_VALUE_LENGTH: Final[int] = 512

# The scalar JSON types a setting may hold. ``None`` is allowed so a client can round-trip a
# field it does not set without special-casing it out of the object.
_ALLOWED_VALUE_TYPES: Final[tuple[type, ...]] = (str, int, float, bool, type(None))


def _key_segments(key: str) -> list[str]:
    """Split a key into lowercase words on non-alphanumeric and camelCase boundaries."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)
    return [segment for segment in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if segment]


def _is_credential_key(key: str) -> bool:
    lowered = key.lower()
    if any(marker in lowered for marker in _CREDENTIAL_KEY_MARKERS):
        return True
    return any(segment in _CREDENTIAL_KEY_SEGMENTS for segment in _key_segments(key))


def _has_url_userinfo(lowered: str) -> bool:
    """True when the value looks like a URL carrying ``user:password@`` userinfo.

    A DSN is the other credential an operator plausibly types into connector settings, and it
    has no distinguishing prefix — the password is inside the URL. Checked on the authority
    section only, so a path or query containing ``@`` is not mistaken for one.
    """
    if "://" not in lowered:
        return False
    authority = lowered.split("://", 1)[1].split("/", 1)[0]
    return ":" in authority.split("@")[0] and "@" in authority


def _is_credential_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    if any(lowered.startswith(prefix) for prefix in _CREDENTIAL_VALUE_PREFIXES):
        return True
    if any(host in lowered for host in _WEBHOOK_HOSTS):
        return True
    return _has_url_userinfo(lowered)


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
