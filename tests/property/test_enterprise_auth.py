"""Property tests for the Auth_Service (Tasks 3.2, 3.3 — Properties 4 and 5).

Both properties are keyless: JWT round-trip needs only a dev secret, and password
hashing uses a low-cost argon2 hasher for fast, deterministic runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from hypothesis import assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.enterprise.auth import Auth_Service
from agentforge.enterprise.rbac import Role

# At least 32 bytes, matching the HS256 key minimum that `load_settings` enforces in
# production (RFC 7518 §3.2), so the property suite signs with a realistically-sized key.
_SECRET = "dev-signing-secret-for-tests-0123456789"
_ROLES = list(Role)
_BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# A fast argon2 hasher keeps the 100-iteration password property quick while still
# exercising the real argon2id verifier (never a plaintext compare).
_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def _auth(secret: str = _SECRET, *, expiry: int = 3600) -> Auth_Service:
    return Auth_Service(
        identity=None,  # type: ignore[arg-type]  # JWT/hash paths do not touch identity
        jwt_secret=secret,
        jwt_expiry_seconds=expiry,
        password_hasher=_FAST_HASHER,
    )


# Feature: agentforge-enterprise, Property 4: JWT issue/verify round-trip and rejection
# of tampered tokens.
@hyp_settings(max_examples=150, deadline=None)
@given(
    user_id=st.uuids(),
    org_id=st.uuids(),
    role=st.sampled_from(_ROLES),
    expiry=st.integers(min_value=1, max_value=100_000),
)
def test_jwt_round_trip_and_tamper_rejection(user_id, org_id, role, expiry):
    """Feature: agentforge-enterprise, Property 4: JWT issue/verify round-trip and
    rejection of tampered tokens — a token issued with a positive expiry round-trips
    through verify to the same claims; a token with a flipped payload, stripped
    signature, wrong secret, or expired exp verifies to None without raising.

    Validates: Requirements 1.2, 1.5
    """
    auth = _auth(expiry=expiry)
    token = auth.issue(user_id, org_id, role, now=_BASE)

    # (a) Round-trip within the validity window returns exactly the issued claims.
    claims = auth.verify(token, now=_BASE)
    assert claims is not None
    assert claims.sub == user_id
    assert claims.org_id == org_id
    assert claims.role == role
    assert claims.exp == int(_BASE.timestamp()) + expiry

    # (b) Expired (exp <= now) verifies to None.
    expired_at = _BASE + timedelta(seconds=expiry)
    assert auth.verify(token, now=expired_at) is None

    # (c) Wrong signing secret verifies to None.
    other = _auth(secret=_SECRET + "-different", expiry=expiry)
    assert other.verify(token, now=_BASE) is None

    # (d) Stripped HS256 signature verifies to None.
    header, payload, _sig = token.split(".")
    assert auth.verify(f"{header}.{payload}.", now=_BASE) is None

    # (e) Tampered payload (one character flipped) verifies to None.
    idx = len(payload) // 2
    flipped = "A" if payload[idx] != "A" else "B"
    tampered_payload = payload[:idx] + flipped + payload[idx + 1 :]
    tampered = f"{header}.{tampered_payload}.{_sig}"
    assert auth.verify(tampered, now=_BASE) is None


# Feature: agentforge-enterprise, Property 5: Password hash correctness and plaintext
# non-disclosure.
@hyp_settings(max_examples=100, deadline=None)
@given(
    password=st.text(min_size=6, max_size=64),
    other=st.text(min_size=6, max_size=64),
)
def test_password_hash_correctness_and_non_disclosure(password, other):
    """Feature: agentforge-enterprise, Property 5: Password hash correctness and plaintext
    non-disclosure — verify_password(hash_password(pw), pw) is True,
    verify_password(hash_password(pw), pw') is False for pw' != pw, and the hash string
    does not contain pw as a substring (verification is always via the argon2 verifier).

    Validates: Requirements 1.1, 1.6, 8.5
    """
    assume(password != other)
    auth = _auth()

    hashed = auth.hash_password(password)

    assert auth.verify_password(hashed, password) is True
    assert auth.verify_password(hashed, other) is False
    # The plaintext is never embedded in the stored hash.
    assert password not in hashed
