"""Property tests for webhook URL admission — the SSRF boundary.

The properties, rather than a list of examples:

* **Nothing resolving inside the deployment is ever admitted.** Generated over the private,
  loopback, link-local, CGNAT and IPv4-mapped ranges, so a range nobody thought to write an
  example for is still covered.
* **Admission is total.** For arbitrary text, ``validate_webhook_url`` either returns the URL
  or raises :class:`WebhookUrlRejected` — never anything else. That is the property the 500s
  came from: a bare ``ValueError`` from port parsing and a ``UnicodeError`` from the resolver
  both escaped a validator that was supposed to be the boundary.
* **Signing round-trips.** Any body verifies under its own signature and fails under any other
  secret.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from agentforge.webhooks.security import (
    WebhookUrlRejected,
    generate_webhook_secret,
    sign_payload,
    validate_webhook_url,
    verify_signature,
)

_SETTINGS = settings(
    max_examples=75,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@contextmanager
def _resolving_to(address: str):
    with patch(
        "agentforge.webhooks.security.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", (address, 0))],
    ):
        yield


_private_v4 = st.one_of(
    st.builds(lambda a: f"10.{a % 256}.0.1", st.integers(0, 255)),
    st.builds(lambda a: f"192.168.{a % 256}.1", st.integers(0, 255)),
    st.builds(lambda a: f"172.{16 + (a % 16)}.0.1", st.integers(0, 255)),
    st.builds(lambda a: f"127.0.0.{1 + (a % 254)}", st.integers(0, 253)),
    st.builds(lambda a: f"169.254.{a % 256}.1", st.integers(0, 255)),
    st.builds(lambda a: f"100.{64 + (a % 64)}.0.1", st.integers(0, 63)),
    st.just("0.0.0.0"),
)


@_SETTINGS
@given(address=_private_v4)
def test_no_internal_address_is_ever_admitted(address: str):
    with _resolving_to(address):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url("https://tenant-supplied.example.com/hook")


@_SETTINGS
@given(address=_private_v4)
def test_the_ipv4_mapped_ipv6_spelling_is_also_refused(address: str):
    with _resolving_to(f"::ffff:{address}"):
        with pytest.raises(WebhookUrlRejected):
            validate_webhook_url("https://tenant-supplied.example.com/hook")


@_SETTINGS
@given(candidate=st.text(max_size=120))
def test_admission_is_total_and_raises_only_its_own_error(candidate: str):
    """Any string is admitted or refused — never a bare ValueError, UnicodeError, or OSError."""
    try:
        result = validate_webhook_url(candidate, allow_loopback=True)
    except WebhookUrlRejected:
        return
    assert result == candidate


@_SETTINGS
@given(
    scheme=st.sampled_from(["https", "http", "ftp", "ws", "javascript", ""]),
    port=st.sampled_from(["", ":0", ":80", ":443", ":8443", ":65536", ":99999", ":abc"]),
    host=st.sampled_from(["example.com", "localhost", "127.0.0.1", "[::1]", "", "a..b"]),
)
def test_admission_is_total_over_url_shapes(scheme: str, port: str, host: str):
    url = f"{scheme}://{host}{port}/hook"
    try:
        with _resolving_to("93.184.216.34"):
            result = validate_webhook_url(url, allow_loopback=True)
    except WebhookUrlRejected:
        return
    assert result == url


@_SETTINGS
@given(body=st.binary(max_size=512))
def test_a_signature_verifies_under_its_own_secret_only(body: bytes):
    secret = generate_webhook_secret()
    other = generate_webhook_secret()
    header = sign_payload(secret, body, timestamp=1_800_000_000)
    assert verify_signature(secret, body, header, now=1_800_000_000)
    assert not verify_signature(other, body, header, now=1_800_000_000)


@_SETTINGS
@given(body=st.binary(max_size=256), suffix=st.binary(min_size=1, max_size=16))
def test_any_modification_to_the_body_invalidates_the_signature(body: bytes, suffix: bytes):
    secret = generate_webhook_secret()
    header = sign_payload(secret, body, timestamp=1_800_000_000)
    assert not verify_signature(secret, body + suffix, header, now=1_800_000_000)
