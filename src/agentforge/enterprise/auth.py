"""Auth_Service: password hashing (argon2id) + JWT issue/verify + register/login.

The service depends only on the abstract :class:`Identity_Store` and on the configured
hashing + signing parameters — everything else is a swappable seam, so a future
OAuth/SSO provider implements the same surface and drops in via the composition root
without touching any endpoint (Req 9.6).

Design choices:

* **Argon2id** (via ``argon2-cffi``) for both passwords and API-key secrets — memory-hard,
  OWASP-recommended, with a constant-time ``verify`` we reuse everywhere. A plaintext
  comparison is never performed (Req 1.6).
* **PyJWT / HS256**. Claims: ``sub`` (user_id), ``org_id``, ``role``, ``exp``.
  :meth:`verify` returns ``None`` for **any** invalid token (bad signature, wrong secret,
  expired, malformed) and never raises, so callers cannot accidentally accept a bad token
  (Req 1.5).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError
from fastapi import status

from agentforge.api.errors import AppError
from agentforge.enterprise.base import Identity_Store
from agentforge.enterprise.models import Access_Token_Claims, Membership, User
from agentforge.enterprise.rbac import Role


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time (injectable ``now`` default)."""
    return datetime.now(timezone.utc)


def _epoch_seconds(moment: datetime) -> int:
    """Return whole unix seconds for a timezone-aware datetime."""
    return int(moment.timestamp())


class Auth_Service:
    """Verifies credentials, hashes passwords, and issues/verifies Access_Tokens."""

    def __init__(
        self,
        identity: Identity_Store,
        *,
        jwt_secret: str,
        jwt_algorithm: str = "HS256",
        jwt_expiry_seconds: int = 3600,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        if not jwt_secret:
            # A signing secret is mandatory; the composition root supplies a generated
            # dev secret in the local profile and a required one in production.
            raise ValueError("jwt_secret must be a non-empty string")
        self._identity = identity
        self._secret = jwt_secret
        self._algorithm = jwt_algorithm
        self._expiry_seconds = jwt_expiry_seconds
        self._hasher = password_hasher or PasswordHasher()

    # --- password hashing (constant-time verify; never a plaintext compare) ---------

    def hash_password(self, password: str) -> str:
        """Return the argon2id hash of ``password`` (Req 1.1)."""
        return self._hasher.hash(password)

    def verify_password(self, hashed: str, password: str) -> bool:
        """Return whether ``password`` matches ``hashed`` via argon2's verifier (Req 1.6)."""
        try:
            return self._hasher.verify(hashed, password)
        except (VerifyMismatchError, Argon2Error, ValueError, TypeError):
            # Mismatch, malformed hash, or invalid input — all "does not verify".
            return False

    # --- JWT issue / verify ---------------------------------------------------------

    def issue(
        self,
        user_id: UUID,
        org_id: UUID,
        role: Role,
        *,
        now: datetime | None = None,
    ) -> str:
        """Issue an HS256 Access_Token carrying ``sub``/``org_id``/``role``/``exp`` (Req 1.2)."""
        issued_at = now or _utcnow()
        claims = {
            "sub": str(user_id),
            "org_id": str(org_id),
            "role": role.value,
            "exp": _epoch_seconds(issued_at) + self._expiry_seconds,
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    def verify(
        self, token: str, *, now: datetime | None = None
    ) -> Access_Token_Claims | None:
        """Decode and validate ``token``; return claims or ``None`` (never raises) (Req 1.5).

        Returns ``None`` on bad signature, wrong secret, wrong algorithm, malformed
        payload, or expiry (``exp <= now``).
        """
        try:
            # Verify signature/algorithm here; validate expiry manually against ``now``
            # so callers can drive it deterministically in tests.
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"verify_exp": False},
            )
        except jwt.InvalidTokenError:
            return None

        try:
            exp = int(payload["exp"])
            claims = Access_Token_Claims(
                sub=UUID(str(payload["sub"])),
                org_id=UUID(str(payload["org_id"])),
                role=Role(payload["role"]),
                exp=exp,
            )
        except (KeyError, ValueError, TypeError):
            return None

        current = _epoch_seconds(now or _utcnow())
        if exp <= current:
            return None  # expired
        return claims

    # --- registration + login -------------------------------------------------------

    def register(self, email: str, password: str, org_id: UUID, role: Role) -> User:
        """Hash the password, persist the User, and grant a Membership (Req 1.1, 2.2).

        The plaintext password never leaves this call frame — only its hash is persisted.
        """
        password_hash = self.hash_password(password)
        user = self._identity.create_user(email, password_hash)
        self._identity.add_membership(user.id, org_id, role)
        return user

    def login(self, email: str, password: str) -> str:
        """Verify credentials and return a freshly-issued Access_Token (Req 1.2, 1.3).

        Raises ``AppError("auth_failed", 401)`` on an unknown email or a password that
        does not match the stored hash; no token is issued in either case.
        """
        user = self._identity.get_user_by_email(email)
        if user is None or not self.verify_password(user.password_hash, password):
            raise AppError(
                "auth_failed",
                "Invalid credentials.",
                status.HTTP_401_UNAUTHORIZED,
            )
        membership = self._resolve_primary_membership(user.id)
        if membership is None:
            # A user with no membership cannot be scoped to a tenant.
            raise AppError(
                "auth_failed",
                "Invalid credentials.",
                status.HTTP_401_UNAUTHORIZED,
            )
        return self.issue(user.id, membership.org_id, membership.role)

    def _resolve_primary_membership(self, user_id: UUID) -> Membership | None:
        """Return the User's membership used to scope a login token.

        The base :class:`Identity_Store` resolves memberships per ``(user, org)``; concrete
        stores expose ``list_memberships_for_user`` for the login path. Resolved via
        duck-typing so the abstract contract stays minimal.
        """
        lister = getattr(self._identity, "list_memberships_for_user", None)
        if lister is None:
            return None
        memberships = lister(user_id)
        return memberships[0] if memberships else None
