"""Webhook security: URL admission (SSRF defence) and request signing.

Everything a hostile input can reach lives here, in one file, because both halves are
security-critical and reviewing them together is the point.

**URL admission.** A webhook URL is attacker-controlled by construction: any principal who can
manage webhooks supplies it, and the platform then makes an authenticated-from-inside request
to it. That is textbook SSRF — the classic target being a cloud metadata service at
``169.254.169.254``, which will happily hand out instance credentials to anything that asks
from inside the network. Defences, all of which must hold together:

* **HTTPS only**, except for an explicit loopback allowance outside the production profile so a
  developer can point a subscription at ``http://localhost:9000`` while building one.
* **No credentials in the URL**, no fragment, no non-standard port set (``80``/``443`` and the
  loopback development case only) — each of those is a way to make one URL read as another.
* **Resolved-address checks, not name checks.** ``http://internal.example.com`` looks fine and
  may resolve to ``10.0.0.5``. Admission resolves the host and refuses loopback, private,
  link-local (which is where metadata services live), multicast, reserved and unspecified
  addresses — for **every** address the name resolves to, since one public answer among
  several private ones must not be enough to pass.
* **Re-validated at delivery time, not only at creation.** DNS is mutable: a host that
  resolved publicly when the subscription was created can be re-pointed at ``127.0.0.1``
  afterwards. This is why :func:`assert_deliverable_url` is called by the transport on every
  attempt rather than trusted from the stored row.
* **Redirects disabled** in the transport, so a 302 cannot walk a validated request to an
  unvalidated address.

A DNS rebinding race remains theoretically open — the name is resolved for the check and again
by the HTTP client — and closing it needs pinning the connection to the checked address. That
bound is documented rather than hidden.

**Signing.** ``X-AgentForge-Signature: t=<unix>,v1=<hex>`` where the MAC is
``HMAC-SHA256(secret, f"{t}.{body}")``. The timestamp is inside the signed material so a
captured delivery cannot be replayed later against a consumer that checks it, and the scheme is
the one consumers already know from Stripe and GitHub rather than a bespoke one they must be
taught.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import socket
from typing import Final
from urllib.parse import urlsplit

#: Generated per subscription and shown exactly once, like an API key secret.
SECRET_PREFIX: Final[str] = "whsec_"
SECRET_ENTROPY_BYTES: Final[int] = 32

MAX_URL_LENGTH: Final[int] = 2048
#: The port each scheme may use, paired with the scheme rather than pooled. Pooling them
#: admitted ``https://host:80`` while the refusal message claimed to have checked "the default
#: port for its scheme" — a URL reading as one service and reaching another is the whole class
#: of confusion this check exists to prevent.
_ALLOWED_SCHEME_PORTS: Final[dict[str, int]] = {"https": 443, "http": 80}


class WebhookUrlRejected(ValueError):
    """Raised when a URL may not be subscribed to, or may not be delivered to."""


def generate_secret() -> str:
    """Return a new signing secret with the conventional prefix."""
    return SECRET_PREFIX + secrets.token_urlsafe(SECRET_ENTROPY_BYTES)


def _is_forbidden_address(address: str) -> bool:
    """True when ``address`` is one an outbound webhook must never reach.

    Expressed as an **allow-list**: only a globally routable unicast address is admissible.
    A deny-list of the ranges one thinks of — loopback, private, link-local — keeps missing
    ones. ``100.64.0.0/10`` (RFC 6598 shared address space, which several cloud providers use
    for internal service traffic) is the concrete example: it is not "private" by any of those
    predicates, and an explicit list written from memory lets it through. ``is_global`` also
    handles an IPv4-mapped IPv6 address correctly, so ``::ffff:10.0.0.1`` cannot be used to
    launder an internal target past an IPv4-only check.

    Multicast is rejected separately because ``224.0.0.1`` reports ``is_global`` as true.
    """
    ip = ipaddress.ip_address(address)
    return not ip.is_global or ip.is_multicast


def _is_loopback_host(host: str) -> bool:
    """True for the literal loopback names/addresses a developer would use locally.

    ``host`` is always ``urlsplit().hostname``, which lower-cases and strips the brackets from
    an IPv6 literal, so ``[::1]`` never arrives here in bracketed form.
    """
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_webhook_url(url: str, *, allow_loopback: bool = False) -> str:
    """Return ``url`` if it may be subscribed to, else raise :class:`WebhookUrlRejected`.

    ``allow_loopback`` is set by the composition root outside the production profile, so a
    developer can target a local listener. It relaxes **only** the scheme and address checks
    for loopback hosts; nothing else is loosened, and production never sets it.

    :class:`WebhookUrlRejected` is the **only** exception this raises. That is load-bearing:
    the transport layer maps it to a 400 and the delivery transport maps it to a failed
    attempt, so anything else escaping here becomes a 500 for an input the caller could have
    fixed. Both of the stdlib calls below leak other types for perfectly reachable inputs —
    ``urlsplit().port`` raises ``ValueError`` for ``:99999`` or ``:abc``, and
    ``getaddrinfo`` raises ``UnicodeError`` for a DNS label over 63 characters — so they are
    wrapped rather than trusted.
    """
    if not url or len(url) > MAX_URL_LENGTH:
        raise WebhookUrlRejected(
            f"a webhook URL must be between 1 and {MAX_URL_LENGTH} characters"
        )

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        # A port outside 0-65535, or one that is not a number at all.
        raise WebhookUrlRejected(f"a webhook URL must be well-formed: {exc}") from exc
    if parts.scheme not in _ALLOWED_SCHEME_PORTS:
        raise WebhookUrlRejected("a webhook URL must use https")
    host = parts.hostname
    if not host:
        raise WebhookUrlRejected("a webhook URL must include a host")
    loopback = _is_loopback_host(host)

    if parts.scheme == "http" and not (allow_loopback and loopback):
        # Plaintext would put the signed payload — and whatever the event carries — on the wire
        # in clear. The loopback exception exists only so a subscription can be developed.
        raise WebhookUrlRejected("a webhook URL must use https (http is allowed for localhost only)")
    if parts.username or parts.password:
        raise WebhookUrlRejected("a webhook URL must not embed credentials")
    if parts.fragment:
        raise WebhookUrlRejected("a webhook URL must not include a fragment")
    if port is not None and port != _ALLOWED_SCHEME_PORTS[parts.scheme]:
        if not (allow_loopback and loopback):
            raise WebhookUrlRejected(
                "a webhook URL must use the default port for its scheme"
            )
    if loopback:
        if allow_loopback:
            return url
        raise WebhookUrlRejected("a webhook URL must not target a loopback address")

    # Name-based checks are not enough: resolve, and refuse if ANY answer is an address an
    # outbound request must not reach.
    try:
        resolved = socket.getaddrinfo(host, port or _ALLOWED_SCHEME_PORTS[parts.scheme])
    except (socket.gaierror, UnicodeError, OSError) as exc:
        # UnicodeError: an over-long or empty DNS label, which the IDNA codec refuses before
        # any lookup happens. Reported as "did not resolve", which is what it amounts to.
        raise WebhookUrlRejected(f"a webhook URL must resolve: {host} did not") from exc

    addresses = {info[4][0] for info in resolved}
    if not addresses:
        raise WebhookUrlRejected(f"a webhook URL must resolve: {host} did not")
    for address in addresses:
        try:
            forbidden = _is_forbidden_address(address)
        except ValueError as exc:  # pragma: no cover - getaddrinfo returns parseable addresses
            # An address the resolver returned that `ipaddress` cannot parse. Unreachable in
            # practice, and refusing is the only safe reading of "we cannot classify this".
            raise WebhookUrlRejected("a webhook URL must resolve to a classifiable address") from exc
        if forbidden:
            # The address is deliberately not echoed: it is the platform's internal topology.
            raise WebhookUrlRejected(
                "a webhook URL must not resolve to a private, loopback, link-local or "
                "otherwise internal address"
            )
    return url


def assert_deliverable_url(url: str, *, allow_loopback: bool = False) -> None:
    """Re-check a stored URL immediately before delivering to it.

    DNS is mutable, so a host that resolved publicly at creation can be re-pointed at an
    internal address afterwards. Called by the transport on every attempt.
    """
    validate_webhook_url(url, allow_loopback=allow_loopback)


def sign_payload(secret: str, body: bytes, timestamp: int) -> str:
    """Return the ``X-AgentForge-Signature`` header value for ``body``.

    The timestamp is part of the signed material, so a consumer that rejects old timestamps
    also rejects replays of a captured delivery.
    """
    signed = f"{timestamp}.".encode() + body
    mac = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_signature(
    secret: str, body: bytes, header: str, *, tolerance_seconds: int = 300, now: int | None = None
) -> bool:
    """Verify a signature header the way a consumer should.

    Not used by the platform itself — the platform signs, it does not verify — but shipped and
    tested so the documented verification recipe is executable rather than prose, and so the
    header format is pinned by a test that fails if it ever changes.
    """
    import time

    parts = dict(
        piece.split("=", 1) for piece in header.split(",") if "=" in piece
    )
    timestamp, mac = parts.get("t"), parts.get("v1")
    if not timestamp or not mac:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else int(time.time())
    if abs(current - sent_at) > tolerance_seconds:
        return False
    expected = sign_payload(secret, body, sent_at).split("v1=", 1)[1]
    # Constant-time: a timing oracle on a MAC comparison is how forgeries get found.
    return hmac.compare_digest(expected, mac)
