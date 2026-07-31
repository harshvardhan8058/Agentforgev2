"""Property-based tests: webhook URL admission, and the secret's one-way disclosure.

Two properties, both about things a table of hand-picked examples cannot establish:

**Property: no generated URL whose host resolves to a non-global address is ever admitted.**
The example-based matrix in ``tests/unit/test_webhook_security.py`` checks the ranges a human
thought of. Hypothesis generates arbitrary IPv4 and IPv6 addresses and asserts the *rule*:
admission succeeds if and only if every resolved address is globally routable unicast. That is
the property SSRF defence rests on, and it holds for ranges nobody enumerated.

**Property: a subscription's secret never appears in any response model.** Generated over
arbitrary secret values, because "the field is absent" must hold for every value, not just for
the ones a fixture happened to produce.
"""

from __future__ import annotations

import ipaddress
import socket
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.api.schemas import (
    CreateWebhookResponse,
    WebhookSubscriptionResponse,
)
from agentforge.webhooks.security import (
    WebhookUrlRejected,
    generate_secret,
    sign_payload,
    validate_webhook_url,
    verify_signature,
)

_ADDRESSES = st.one_of(
    st.ip_addresses(v=4).map(str),
    st.ip_addresses(v=6).map(str),
)


@contextmanager
def _resolving_to(*addresses: str):
    """Pin DNS for the duration of one example.

    A context manager rather than the ``monkeypatch`` fixture: a function-scoped fixture is not
    reset between Hypothesis examples, and Hypothesis rightly refuses to pretend otherwise.
    """

    def fake_getaddrinfo(host, port, *_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]

    with patch.object(socket, "getaddrinfo", fake_getaddrinfo):
        yield


def _is_admissible(address: str) -> bool:
    """The rule admission is supposed to implement: globally routable unicast only."""
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


@hyp_settings(max_examples=300, deadline=None)
@given(address=_ADDRESSES)
def test_admission_accepts_a_host_exactly_when_every_resolved_address_is_global(address: str):
    """The SSRF property: admitted ⟺ globally routable. No enumerated range required."""
    with _resolving_to(address):
        try:
            validate_webhook_url("https://hooks.example.com/agentforge")
            admitted = True
        except WebhookUrlRejected:
            admitted = False

    assert admitted is _is_admissible(address)


@hyp_settings(max_examples=200, deadline=None)
@given(addresses=st.lists(_ADDRESSES, min_size=1, max_size=4))
def test_one_internal_answer_among_several_is_enough_to_refuse(addresses: list[str]):
    """A resolver can return many addresses; an attacker needs only the internal one to be used."""
    with _resolving_to(*addresses):
        try:
            validate_webhook_url("https://hooks.example.com/agentforge")
            admitted = True
        except WebhookUrlRejected:
            admitted = False

    assert admitted is all(_is_admissible(address) for address in addresses)


@hyp_settings(max_examples=200, deadline=None)
@given(address=_ADDRESSES)
def test_a_non_https_scheme_is_refused_regardless_of_where_it_resolves(address: str):
    """Plaintext would put the signed payload on the wire in clear, wherever it points."""
    with _resolving_to(address), pytest.raises(WebhookUrlRejected):
        validate_webhook_url("http://hooks.example.com/agentforge")


@hyp_settings(max_examples=100)
@given(
    secret=st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=64
    ).map(lambda s: f"whsec_{s}")
)
def test_the_subscription_response_model_cannot_carry_a_secret(secret: str):
    """Absent by shape, not by a handler remembering to strip it."""
    assert "secret" not in WebhookSubscriptionResponse.model_fields
    # And the creation model, which does carry it, is the only one that does.
    assert "secret" in CreateWebhookResponse.model_fields
    assert secret not in str(WebhookSubscriptionResponse.model_fields)


@hyp_settings(max_examples=200, deadline=None)
@given(
    body=st.binary(max_size=512),
    timestamp=st.integers(min_value=0, max_value=2_000_000_000),
)
def test_a_signature_verifies_for_any_body_and_never_for_a_different_secret(
    body: bytes, timestamp: int
):
    """Signing is total over byte bodies, and the MAC actually depends on the key."""
    secret = generate_secret()
    header = sign_payload(secret, body, timestamp)

    assert verify_signature(secret, body, header, now=timestamp) is True
    assert verify_signature(generate_secret(), body, header, now=timestamp) is False
