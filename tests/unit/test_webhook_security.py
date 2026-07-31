"""Unit tests: webhook URL admission (SSRF defence) and request signing.

This is the file that matters most in the webhook feature. A webhook URL is
attacker-controlled by construction — any principal who can manage webhooks supplies it, and
the platform then makes a request to it from *inside* its own network — so every case below is
a real attack shape rather than a hypothetical:

* the cloud metadata service, which hands out instance credentials to anything that asks;
* a public hostname that resolves to a private address (the check that a name-based allow-list
  cannot make);
* credentials or a fragment smuggled into the URL so it reads as a different host;
* IPv4-mapped IPv6 and RFC 6598 shared space, the two ranges a hand-written deny-list misses.

DNS is monkeypatched wherever a *name* is under test, so these assert the policy rather than
whatever the sandbox's resolver happens to answer. Numeric addresses need no resolver.
"""

from __future__ import annotations

import socket

import pytest

from agentforge.webhooks.security import (
    MAX_URL_LENGTH,
    SECRET_PREFIX,
    WebhookUrlRejected,
    generate_secret,
    sign_payload,
    validate_webhook_url,
    verify_signature,
)


def _resolve_to(monkeypatch, *addresses: str) -> None:
    """Make every name resolve to ``addresses``, so the policy is what is under test."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in addresses]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# --- what is admitted --------------------------------------------------------------


def test_a_public_https_url_is_admitted(monkeypatch):
    _resolve_to(monkeypatch, "8.8.8.8")
    assert validate_webhook_url("https://hooks.example.com/agentforge") == (
        "https://hooks.example.com/agentforge"
    )


def test_an_explicit_443_and_a_query_string_are_admitted(monkeypatch):
    _resolve_to(monkeypatch, "8.8.8.8")
    url = "https://hooks.example.com:443/agentforge?tenant=acme"
    assert validate_webhook_url(url) == url


def test_every_resolved_address_must_be_public(monkeypatch):
    """One public answer among private ones must not be enough to pass.

    A resolver can return several addresses, and an attacker only needs the connection to land
    on the internal one. Admission is therefore all-or-nothing.
    """
    _resolve_to(monkeypatch, "8.8.8.8", "10.0.0.5")
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("https://split-horizon.example.com/hook")


# --- SSRF: the address matrix ------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("https://169.254.169.254/latest/meta-data/", "cloud instance metadata"),
        ("https://127.0.0.1/hook", "loopback"),
        ("https://10.0.0.5/hook", "RFC1918 private"),
        ("https://192.168.1.1/hook", "RFC1918 private"),
        ("https://172.16.0.1/hook", "RFC1918 private"),
        ("https://100.64.0.1/hook", "RFC6598 shared address space"),
        ("https://0.0.0.0/hook", "unspecified"),
        ("https://[::1]/hook", "IPv6 loopback"),
        ("https://[fd00::1]/hook", "IPv6 unique-local"),
        ("https://[fe80::1]/hook", "IPv6 link-local"),
        ("https://[::ffff:10.0.0.1]/hook", "IPv4-mapped private"),
        ("https://224.0.0.1/hook", "multicast"),
    ],
)
def test_an_internal_address_is_refused(url: str, why: str):
    """Numeric literals need no resolver, so this is the policy with nothing mocked."""
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url(url)


def test_a_public_name_that_resolves_privately_is_refused(monkeypatch):
    """The check a name-based allow-list cannot make."""
    _resolve_to(monkeypatch, "10.0.0.5")
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("https://internal.example.com/hook")


def test_the_refusal_does_not_echo_the_resolved_address(monkeypatch):
    """The resolved address is this platform's internal topology, not the caller's business."""
    _resolve_to(monkeypatch, "10.11.12.13")
    with pytest.raises(WebhookUrlRejected) as raised:
        validate_webhook_url("https://internal.example.com/hook")
    assert "10.11.12.13" not in str(raised.value)


def test_a_name_that_does_not_resolve_is_refused(monkeypatch):
    def boom(*_args, **_kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("https://nowhere.example.com/hook")


# --- SSRF: the URL shape -----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/hook",  # plaintext would put the payload on the wire in clear
        "ftp://hooks.example.com/hook",
        "file:///etc/passwd",
        "gopher://hooks.example.com/hook",
        "https://user:pass@hooks.example.com/hook",  # credentials read as part of the host
        "https://hooks.example.com/hook#fragment",
        "https://hooks.example.com:8080/hook",  # a non-standard port is a different service
        "https:///hook",  # no host
        "",
    ],
)
def test_a_malformed_or_unsafe_url_shape_is_refused(url: str, monkeypatch):
    _resolve_to(monkeypatch, "8.8.8.8")
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url(url)


def test_an_over_long_url_is_refused():
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url("https://example.com/" + "a" * MAX_URL_LENGTH)


# --- the development loopback allowance -------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:9000/hook",
        "http://127.0.0.1:9000/hook",
        "https://localhost/hook",
        "http://[::1]:9000/hook",
    ],
)
def test_loopback_is_admitted_only_when_explicitly_allowed(url: str):
    """Outside production a developer must be able to point a subscription at a local listener."""
    assert validate_webhook_url(url, allow_loopback=True) == url
    with pytest.raises(WebhookUrlRejected):
        validate_webhook_url(url, allow_loopback=False)


def test_the_loopback_allowance_does_not_extend_to_other_internal_addresses():
    """It relaxes loopback, not "internal" — the metadata service stays unreachable."""
    for url in ("https://169.254.169.254/latest/meta-data/", "https://10.0.0.5/hook"):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url(url, allow_loopback=True)


def test_the_loopback_allowance_does_not_permit_credentials_or_a_fragment():
    for url in ("http://u:p@localhost:9000/hook", "http://localhost:9000/hook#f"):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url(url, allow_loopback=True)


# --- secrets -----------------------------------------------------------------------


def test_a_generated_secret_is_prefixed_and_unguessable():
    first, second = generate_secret(), generate_secret()
    assert first.startswith(SECRET_PREFIX)
    assert first != second
    # 32 bytes of entropy, urlsafe-base64 encoded, plus the prefix.
    assert len(first) > len(SECRET_PREFIX) + 40


# --- signing ---------------------------------------------------------------------


def test_the_signature_header_format_is_stable():
    """Consumers parse this string; the format is a published contract."""
    header = sign_payload("whsec_test", b'{"a":1}', 1700000000)
    assert header.startswith("t=1700000000,v1=")
    assert len(header.split("v1=")[1]) == 64  # hex sha256


def test_a_signature_verifies_with_the_shipped_recipe():
    body = b'{"event":"webhook.ping"}'
    header = sign_payload("whsec_test", body, 1700000000)
    assert verify_signature("whsec_test", body, header, now=1700000000) is True


def test_verification_fails_for_a_wrong_secret_or_a_tampered_body():
    body = b'{"event":"webhook.ping"}'
    header = sign_payload("whsec_test", body, 1700000000)

    assert verify_signature("whsec_other", body, header, now=1700000000) is False
    assert verify_signature("whsec_test", b'{"event":"evil"}', header, now=1700000000) is False


def test_the_timestamp_is_signed_so_a_replay_is_detectable():
    """A captured delivery replayed later fails, because ``t`` is inside the MAC."""
    body = b'{"event":"webhook.ping"}'
    header = sign_payload("whsec_test", body, 1700000000)

    assert verify_signature("whsec_test", body, header, now=1700000000 + 301) is False
    assert verify_signature("whsec_test", body, header, now=1700000000 + 299) is True
    # Editing the timestamp to make it fresh invalidates the MAC.
    forged = header.replace("t=1700000000", "t=1700000301")
    assert verify_signature("whsec_test", body, forged, now=1700000301) is False


@pytest.mark.parametrize(
    "header",
    ["", "garbage", "t=1700000000", "v1=abc", "t=notanumber,v1=abc", "t=1700000000,v1="],
)
def test_a_malformed_signature_header_never_verifies(header: str):
    assert verify_signature("whsec_test", b"{}", header, now=1700000000) is False
