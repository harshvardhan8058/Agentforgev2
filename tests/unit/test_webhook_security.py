"""Unit tests for webhook URL admission and payload signing.

The admission matrix is the security-critical part of this feature: ``POST /webhooks`` asks the
server to fetch a tenant-supplied address, so every row below is a way that could have become
an SSRF primitive. Cases that need DNS use a stubbed resolver — the point is the policy, not
the network — except the two that must reach the real resolver to reproduce the failure modes
it raises (a name that does not resolve, and a name that cannot be IDNA-encoded at all).
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from agentforge.webhooks.security import (
    MAX_URL_LENGTH,
    WebhookUrlRejected,
    generate_webhook_secret,
    sign_payload,
    validate_webhook_url,
    verify_signature,
)


@contextmanager
def _resolving_to(*addresses: str):
    """Patch :func:`socket.getaddrinfo` so a hostname resolves to ``addresses``."""
    infos = [(2, 1, 6, "", (a, 0)) for a in addresses]
    with patch("agentforge.webhooks.security.socket.getaddrinfo", return_value=infos):
        yield


# --- accepted shapes --------------------------------------------------------------


def test_a_public_https_url_is_admitted():
    with _resolving_to("93.184.216.34"):
        assert (
            validate_webhook_url("https://hooks.example.com/agentforge")
            == "https://hooks.example.com/agentforge"
        )


def test_a_non_standard_https_port_is_admitted():
    """8443 is an ordinary enterprise webhook port; refusing it would be policy theatre."""
    with _resolving_to("93.184.216.34"):
        assert validate_webhook_url("https://hooks.example.com:8443/h")


def test_loopback_http_is_admitted_only_when_the_deployment_allows_it():
    url = "http://localhost:9000/hook"
    assert validate_webhook_url(url, allow_loopback=True) == url
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url(url, allow_loopback=False)


def test_loopback_admission_does_not_require_dns():
    """A loopback destination is accepted without a resolver round trip."""

    def _explode(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("loopback admission must not resolve")

    with patch("agentforge.webhooks.security.socket.getaddrinfo", _explode):
        assert validate_webhook_url("http://127.0.0.1:8080/h", allow_loopback=True)


# --- refused shapes ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ftp://example.com/h",
        "file:///etc/passwd",
        "gopher://example.com/h",
        # A scheme-relative or bare host has no scheme at all.
        "example.com/h",
        # Credentials in the URL make the address a reader sees differ from the one dialled.
        "https://user:pass@hooks.example.com/h",
        "https://user@hooks.example.com/h",
        # A fragment is never sent and is a way to hide the real target from a reviewer.
        "https://hooks.example.com/h#@evil.example.com",
        # Scheme/port contradictions.
        "https://hooks.example.com:80/h",
        "http://127.0.0.1:443/h",
        # A host is required.
        "https:///hook",
    ],
)
def test_malformed_or_unsafe_urls_are_refused(url: str):
    with _resolving_to("93.184.216.34"):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url(url, allow_loopback=True)


def test_an_over_long_url_is_refused():
    url = "https://hooks.example.com/" + "a" * MAX_URL_LENGTH
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url(url)


@pytest.mark.parametrize(
    "port",
    ["99999", "0x50", "abc", "-1"],
)
def test_a_malformed_port_is_a_refusal_not_a_crash(port: str):
    """``urlsplit().port`` raises on access; unguarded that was a 500 on a validated field."""
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url(f"https://hooks.example.com:{port}/h")


def test_an_unencodable_dns_label_is_a_refusal_not_a_crash():
    """A label over 63 characters makes the real resolver raise ``UnicodeError``.

    Deliberately not stubbed: the point is that the resolver's *own* failure modes are mapped
    onto a refusal, and stubbing it would test the stub.
    """
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("https://" + "a" * 250 + ".example.com/h")


def test_a_host_that_does_not_resolve_is_refused():
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("https://webhook-host-that-does-not-exist.invalid/h")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC1918
        "172.16.4.4",
        "192.168.1.10",
        "169.254.169.254",  # cloud metadata — the reason this validator exists
        "100.64.0.1",  # CGNAT: a cloud provider's own network
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast (reported as global by ipaddress)
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local
        "::",  # IPv6 unspecified
        "::ffff:10.0.0.1",  # IPv4-mapped IPv6 — the classic bypass
        "::ffff:169.254.169.254",
        "192.0.2.1",  # documentation range
        "198.18.0.1",  # benchmarking range
    ],
)
def test_a_host_resolving_inside_the_network_is_refused(address: str):
    with _resolving_to(address):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url("https://sneaky.example.com/h")


def test_one_forbidden_address_among_several_refuses_the_whole_host():
    """Every resolved address must be safe: a host that answers with both is not usable."""
    with _resolving_to("93.184.216.34", "10.1.2.3"):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url("https://split-horizon.example.com/h")


def test_the_refusal_never_names_the_resolved_address():
    """Echoing it back would make this endpoint a scanner for the private network."""
    with _resolving_to("10.11.12.13"):
        with pytest.raises(WebhookUrlRejected) as caught:
            validate_webhook_url("https://sneaky.example.com/h")
    assert "10.11.12.13" not in str(caught.value)


def test_a_numeric_private_address_is_refused_even_with_loopback_allowed():
    """``allow_loopback`` admits loopback only — not the rest of the private space."""
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("http://10.0.0.5:9000/h", allow_loopback=True)


# --- signing ----------------------------------------------------------------------


def test_a_signature_verifies_against_the_exact_body():
    secret = generate_webhook_secret()
    body = b'{"event":"run.completed"}'
    header = sign_payload(secret, body, timestamp=1_800_000_000)
    assert verify_signature(secret, body, header, now=1_800_000_000)


def test_a_signature_does_not_verify_against_a_changed_body():
    secret = generate_webhook_secret()
    header = sign_payload(secret, b"original", timestamp=1_800_000_000)
    assert not verify_signature(secret, b"tampered", header, now=1_800_000_000)


def test_a_signature_does_not_verify_under_a_different_secret():
    header = sign_payload("secret-a", b"body", timestamp=1_800_000_000)
    assert not verify_signature("secret-b", b"body", header, now=1_800_000_000)


def test_a_stale_signature_is_refused():
    """The timestamp is inside the signed material, so a captured payload expires."""
    secret = generate_webhook_secret()
    header = sign_payload(secret, b"body", timestamp=1_800_000_000)
    assert not verify_signature(
        secret, b"body", header, now=1_800_000_000 + 301, tolerance_seconds=300
    )
    assert verify_signature(
        secret, b"body", header, now=1_800_000_000 + 299, tolerance_seconds=300
    )


def test_a_future_dated_signature_is_refused_symmetrically():
    """Clock skew is tolerated in both directions, and only within the window."""
    secret = generate_webhook_secret()
    header = sign_payload(secret, b"body", timestamp=1_800_000_000 + 400)
    assert not verify_signature(
        secret, b"body", header, now=1_800_000_000, tolerance_seconds=300
    )


@pytest.mark.parametrize(
    "header",
    [
        "",
        "garbage",
        "t=1800000000",  # no signature
        "v1=deadbeef",  # no timestamp
        "t=not-a-number,v1=deadbeef",
        "t=1800000000,v1=",
    ],
)
def test_a_malformed_signature_header_is_refused(header: str):
    assert not verify_signature("secret", b"body", header, now=1_800_000_000)


def test_the_signature_header_carries_the_timestamp_it_signed():
    header = sign_payload("secret", b"body", timestamp=1_800_000_000)
    assert header.startswith("t=1800000000,v1=")


def test_generated_secrets_are_unique_and_long():
    secrets = {generate_webhook_secret() for _ in range(50)}
    assert len(secrets) == 50
    assert all(len(s) >= 40 for s in secrets)
