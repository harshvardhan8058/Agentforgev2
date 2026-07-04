"""Unit tests for Auth_Service password hashing + verification basics (Task 3.4).

Cover the argon2 ``VerifyMismatchError`` path, unicode passwords, empty strings, and
long inputs. A low-cost argon2 hasher keeps the tests fast while exercising the real
verifier (Req 1.1, 1.6).
"""

from __future__ import annotations

from argon2 import PasswordHasher

from agentforge.enterprise.auth import Auth_Service

_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def _auth() -> Auth_Service:
    return Auth_Service(
        identity=None,  # type: ignore[arg-type]
        jwt_secret="unit-test-secret",
        password_hasher=_FAST_HASHER,
    )


def test_hash_then_verify_true():
    """A password verifies against its own hash."""
    auth = _auth()
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password(hashed, "correct horse battery staple") is True


def test_verify_wrong_password_false():
    """A different password does not verify (VerifyMismatchError path -> False)."""
    auth = _auth()
    hashed = auth.hash_password("s3cret-value")
    assert auth.verify_password(hashed, "not-the-password") is False


def test_hash_is_salted_unique_per_call():
    """Hashing the same password twice yields distinct salted hashes that both verify."""
    auth = _auth()
    h1 = auth.hash_password("same-password")
    h2 = auth.hash_password("same-password")
    assert h1 != h2
    assert auth.verify_password(h1, "same-password") is True
    assert auth.verify_password(h2, "same-password") is True


def test_unicode_password_round_trips():
    """Unicode passwords hash and verify correctly."""
    auth = _auth()
    pw = "pÁsswörd-🔐-日本語"
    hashed = auth.hash_password(pw)
    assert auth.verify_password(hashed, pw) is True
    assert auth.verify_password(hashed, "pAsswOrd") is False


def test_empty_password_round_trips():
    """An empty password hashes and verifies; a non-empty one does not match it."""
    auth = _auth()
    hashed = auth.hash_password("")
    assert auth.verify_password(hashed, "") is True
    assert auth.verify_password(hashed, "x") is False


def test_long_password_round_trips():
    """A very long password hashes and verifies correctly."""
    auth = _auth()
    pw = "a" * 4096
    hashed = auth.hash_password(pw)
    assert auth.verify_password(hashed, pw) is True
    assert auth.verify_password(hashed, "a" * 4095) is False


def test_verify_against_malformed_hash_returns_false():
    """A malformed hash string never raises; verification returns False."""
    auth = _auth()
    assert auth.verify_password("not-a-valid-argon2-hash", "whatever") is False
