"""Webhook URL admission and payload signing — the two places this feature can go wrong.

A webhook endpoint is a URL supplied by a tenant that the *server* then fetches. That is
textbook SSRF: without admission control, ``POST /webhooks`` would be an API for asking the
platform to make authenticated-from-inside requests to its own database, its Redis, its
cloud metadata service, or any host reachable from the pod but not from the internet.

:func:`validate_webhook_url` is therefore an **allow-list of shapes**, applied at creation
*and* again immediately before every delivery:

* TLS required. Plain ``http`` is admitted only for loopback, and only when the deployment
  says so (``allow_loopback``, true outside the production profile) — that is what makes
  ``http://localhost:9000`` usable while developing without opening a hole in production.
* No credentials in the URL, and no fragment: both are ways to make the address a human
  reviewer reads differ from the address the client dials.
* Every address the host resolves to must be *globally routable*. Not a deny-list of RFC1918
  ranges — an allow-list, because deny-lists have to enumerate every special range correctly
  (loopback, link-local, CGNAT, IPv4-mapped IPv6, benchmarking, documentation, 0.0.0.0) and
  the interesting bypasses are always the range that was forgotten.
* Redirects are refused by the transport, so a public URL cannot hand off to a private one.

The residual hole is documented rather than papered over: between the check and the connect,
DNS can change (a rebinding attack). Closing it properly means connecting to a pinned,
already-validated IP with the hostname carried in SNI plus ``Host``, which the HTTP client
here cannot express; see docs/KNOWN_LIMITATIONS.md.

Signing is Stripe-shaped: ``t=<unix>,v1=<hex hmac-sha256 of "t.body">``. The timestamp is
inside the signed material, so a captured payload cannot be replayed later without the
signature also being wrong. :func:`verify_signature` ships as part of the platform (rather
than only as prose in the docs) so the documented consumer recipe is executable and tested.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import socket
import time
from ipaddress import ip_address
from typing import Final
from urllib.parse import urlsplit

#: Generous but bounded: a URL is stored, logged, and rendered in a console, and an unbounded
#: one is a way to put a megabyte into a text column through a validated field.
MAX_URL_LENGTH: Final[int] = 2048

#: Hostnames that mean "this machine" without needing DNS.
_LOOPBACK_NAMES: Final[frozenset[str]] = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)

#: Signature freshness window for :func:`verify_signature`. Five minutes is the same order as
#: every comparable product: long enough to survive clock skew and a slow queue, short enough
#: that a captured payload is not replayable tomorrow.
DEFAULT_SIGNATURE_TOLERANCE_SECONDS: Final[int] = 300

SIGNATURE_HEADER: Final[str] = "X-AgentForge-Signature"
EVENT_HEADER: Final[str] = "X-AgentForge-Event"
DELIVERY_HEADER: Final[str] = "X-AgentForge-Delivery"
SUBSCRIPTION_HEADER: Final[str] = "X-AgentForge-Webhook-Id"
#: Which attempt this is, 1-based. Lets a consumer log "this is a retry" without diffing bodies —
#: a retry is byte-identical to its first attempt, deliberately.
ATTEMPT_HEADER: Final[str] = "X-AgentForge-Attempt"
#: The logical identity of the occurrence. The header a consumer should deduplicate on: unlike
#: the delivery id, it is also stable across a repeated occurrence that means the same thing.
IDEMPOTENCY_HEADER: Final[str] = "X-AgentForge-Idempotency-Key"


class WebhookUrlRejected(ValueError):
    """Raised when a webhook URL fails admission.

    The message is safe to return to the caller: it says which rule was broken and never
    echoes a resolved address, because "your hostname resolves to 10.0.3.7" would turn the
    validator into an internal-network scanner with a friendly error format.
    """


def generate_webhook_secret() -> str:
    """Return a fresh 256-bit signing secret, URL-safe base64.

    ``secrets``, not ``random``: this key is the only thing standing between a consumer and a
    forged event.
    """
    return secrets.token_urlsafe(32)


def _is_forbidden_address(raw: str) -> bool:
    """Return whether ``raw`` (a resolved IP) must not be dialled.

    Allow-list semantics: an address is admitted only when Python considers it *globally
    routable*, which excludes loopback, private, link-local, unspecified, reserved, CGNAT
    (100.64.0.0/10 — a cloud provider's own network), documentation and benchmarking ranges,
    and their IPv4-mapped IPv6 spellings, in one check that stays correct as the registry
    grows. Multicast is excluded explicitly because ``is_global`` reports some multicast
    addresses as global, and a webhook to a multicast group is never a legitimate endpoint.
    """
    try:
        address = ip_address(raw)
    except ValueError:
        # An address the resolver produced but the ipaddress module cannot parse is not an
        # address we are willing to dial.
        return True
    return not address.is_global or address.is_multicast


def _resolved_addresses(host: str) -> list[str]:
    """Return every address ``host`` resolves to, or raise :class:`WebhookUrlRejected`.

    Every failure mode of :func:`socket.getaddrinfo` is mapped onto the same refusal:
    ``gaierror`` for a name that does not resolve, ``UnicodeError`` for a name whose labels
    cannot be IDNA-encoded (a label over 63 characters, an empty label), and ``OSError`` for
    a resolver failure. Letting any of those escape would turn a bad-but-well-formed URL into
    a 500 on a validated field.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise WebhookUrlRejected(
            "the webhook host could not be resolved; a webhook URL must name a host that "
            "resolves to a public address"
        ) from exc
    return [info[4][0] for info in infos]


def validate_webhook_url(url: str, *, allow_loopback: bool = False) -> str:
    """Return ``url`` unchanged if it may be dialled, else raise :class:`WebhookUrlRejected`.

    ``allow_loopback`` admits ``http://localhost:9000``-shaped destinations so a developer can
    point a subscription at a local listener. It is derived from the profile, never from a
    request, and is false in production.
    """
    if not isinstance(url, str) or not url.strip():
        raise WebhookUrlRejected("a webhook URL is required")
    if len(url) > MAX_URL_LENGTH:
        raise WebhookUrlRejected(
            f"a webhook URL must be at most {MAX_URL_LENGTH} characters"
        )

    parts = urlsplit(url)

    if parts.scheme not in ("https", "http"):
        raise WebhookUrlRejected(
            "a webhook URL must use https (http is accepted only for loopback addresses "
            "outside production)"
        )
    if parts.username or parts.password:
        raise WebhookUrlRejected(
            "a webhook URL must not embed credentials; the request is authenticated by its "
            "signature, not by the URL"
        )
    if parts.fragment:
        raise WebhookUrlRejected("a webhook URL must not contain a fragment")

    # ``parts.port`` PARSES on access and raises for a non-numeric or out-of-range value, so
    # it is read inside the guard: unguarded, ":99999" reached the caller as a bare ValueError
    # and became a 500 on a field the API is supposed to be validating.
    try:
        port = parts.port
    except ValueError as exc:
        raise WebhookUrlRejected(
            "the webhook URL's port is not a valid port number"
        ) from exc

    host = (parts.hostname or "").strip()
    if not host:
        raise WebhookUrlRejected("a webhook URL must name a host")

    # A scheme/port contradiction (TLS on 80, cleartext on 443) is far more likely a mistake
    # or an attempt to make the address read differently than it dials than a real endpoint.
    if parts.scheme == "https" and port == 80:
        raise WebhookUrlRejected("an https webhook URL must not use port 80")
    if parts.scheme == "http" and port == 443:
        raise WebhookUrlRejected("an http webhook URL must not use port 443")

    is_loopback_name = host.lower() in _LOOPBACK_NAMES
    if not is_loopback_name:
        try:
            is_loopback_name = ip_address(host).is_loopback
        except ValueError:
            is_loopback_name = False

    if is_loopback_name:
        if not allow_loopback:
            raise WebhookUrlRejected(
                "a webhook URL must not point at the platform itself"
            )
        # A deployment that opted into loopback destinations gets them without a DNS round
        # trip; "localhost" is the one host whose meaning is not in question.
        return url

    if parts.scheme != "https":
        raise WebhookUrlRejected(
            "a webhook URL must use https (http is accepted only for loopback addresses "
            "outside production)"
        )

    addresses = _resolved_addresses(host)
    if not addresses or any(_is_forbidden_address(a) for a in addresses):
        # Deliberately does NOT name the offending address: echoing it back would make this
        # endpoint a DNS-backed scanner for the deployment's private network.
        raise WebhookUrlRejected(
            "the webhook host resolves to an address that is not publicly routable; a "
            "webhook URL must not target the deployment's own network"
        )
    return url


def assert_deliverable_url(url: str, *, allow_loopback: bool = False) -> None:
    """Re-check ``url`` immediately before an HTTP attempt.

    Separate from :func:`validate_webhook_url` only by intent, and it re-resolves on purpose:
    a hostname that pointed somewhere public when the subscription was created can point
    inside the network by the time an event fires, and a check that ran only at creation would
    be a check an attacker simply waits out.
    """
    validate_webhook_url(url, allow_loopback=allow_loopback)


def _signing_material(timestamp: int, body: bytes) -> bytes:
    """Return the bytes actually signed: ``"<timestamp>."`` followed by the body."""
    return f"{timestamp}.".encode("ascii") + body


def sign_payload(secret: str, body: bytes, *, timestamp: int | None = None) -> str:
    """Return the ``X-AgentForge-Signature`` value for ``body``.

    Format: ``t=<unix seconds>,v1=<hex hmac-sha256>``. The timestamp is part of the signed
    material, which is what makes a captured request non-replayable, and the ``v1`` prefix is
    the room a future scheme needs to be added without breaking every consumer.
    """
    moment = int(time.time()) if timestamp is None else int(timestamp)
    digest = hmac.new(
        secret.encode("utf-8"), _signing_material(moment, body), hashlib.sha256
    ).hexdigest()
    return f"t={moment},v1={digest}"


def verify_signature(
    secret: str,
    body: bytes,
    header: str,
    *,
    tolerance_seconds: int = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    now: int | None = None,
) -> bool:
    """Return whether ``header`` is a valid, fresh signature of ``body`` under ``secret``.

    Shipped as platform code, not only as documentation prose, for two reasons: the recipe
    consumers copy is then something the test suite actually exercises, and the comparison is
    :func:`hmac.compare_digest` rather than ``==``, which is the detail a hand-rolled verifier
    gets wrong.
    """
    if not header:
        return False
    fields: dict[str, str] = {}
    for chunk in header.split(","):
        key, sep, value = chunk.strip().partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    raw_timestamp = fields.get("t")
    provided = fields.get("v1")
    if not raw_timestamp or not provided:
        return False
    try:
        timestamp = int(raw_timestamp)
    except ValueError:
        return False
    moment = int(time.time()) if now is None else int(now)
    if abs(moment - timestamp) > tolerance_seconds:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), _signing_material(timestamp, body), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)
