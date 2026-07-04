"""API_Key_Service + ``InMemory_API_Key_Store`` / ``Pg_API_Key_Store`` (Task 5).

An API key is an **org-scoped** credential authenticating programmatic clients that do
not log in as a user. Its permissions are derived from its ``role`` through the same
``RBAC_Policy`` used everywhere else, so a role or permission change propagates to API-key
principals with no extra plumbing (Req 5.1).

Secret format & hashing:

* ``secret = "af_" + token_urlsafe(32)`` — ~256 bits of entropy from :mod:`secrets`.
* ``key_prefix = secret[:8]`` is stored unhashed and indexed, so lookup narrows to a tiny
  candidate set in O(1); the full secret is then confirmed by a constant-time argon2
  ``verify`` against each candidate's ``key_hash``.
* Only ``key_prefix`` + ``key_hash`` are persisted — the plaintext secret is returned
  **exactly once** at creation and never stored or logged (Req 5.1, 5.2, 8.5).

The same argon2 ``PasswordHasher`` used by the ``Auth_Service`` is injected here, so there
is one hashing seam with two consumers and no plaintext comparison anywhere (Req 1.6).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.enterprise.base import API_Key_Store
from agentforge.enterprise.identity import _to_sqlalchemy_sync_dsn
from agentforge.enterprise.models import API_Key
from agentforge.enterprise.rbac import Permission, RBAC_Policy, Role

# The plaintext secret is prefixed for fast indexed candidate lookup; only the prefix +
# argon2 hash are persisted. Constants declared here so the service and the stores agree
# on the format.
API_KEY_PREFIX = "af_"
API_KEY_PREFIX_LEN = 8


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def to_metadata(api_key: API_Key) -> dict[str, Any]:
    """Project an API_Key onto its safe metadata shape.

    Includes ``id``, ``org_id``, ``role``, ``key_prefix``, ``revoked_at``, and
    ``created_at`` and **never** ``key_hash`` or the plaintext secret (Req 5.4).
    """
    return {
        "id": api_key.id,
        "org_id": api_key.org_id,
        "role": api_key.role.value,
        "key_prefix": api_key.key_prefix,
        "revoked_at": api_key.revoked_at,
        "created_at": api_key.created_at,
    }


class API_Key_Service:
    """Creates, resolves, lists, and revokes organization-scoped API keys."""

    def __init__(
        self,
        store: API_Key_Store,
        rbac: RBAC_Policy,
        hasher: PasswordHasher,
    ) -> None:
        self._store = store
        self._rbac = rbac
        self._hasher = hasher

    def create(self, org_id: UUID, role: Role) -> tuple[API_Key, str]:
        """Generate a new key; return ``(metadata, plaintext_secret)`` (Req 5.1, 5.2).

        The plaintext ``secret`` is returned exactly once — the caller surfaces it in the
        creation response and it is never persisted.
        """
        secret = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        key_prefix = secret[:API_KEY_PREFIX_LEN]
        key_hash = self._hasher.hash(secret)
        key = API_Key(
            id=uuid.uuid4(),
            org_id=org_id,
            role=role,
            key_prefix=key_prefix,
            key_hash=key_hash,
            revoked_at=None,
            created_at=_utcnow(),
        )
        stored = self._store.create(key)
        return stored, secret

    def resolve_key(self, presented: str) -> API_Key | None:
        """Resolve a presented secret to its active API_Key, or ``None`` (Req 5.3, 5.6).

        Rejects a wrong prefix immediately, narrows to the indexed prefix candidate set,
        and confirms with a constant-time argon2 ``verify``. Revoked keys are excluded by
        the store's ``list_active_by_prefix``, so they never resolve.
        """
        if not presented.startswith(API_KEY_PREFIX):
            return None
        prefix = presented[:API_KEY_PREFIX_LEN]
        for candidate in self._store.list_active_by_prefix(prefix):
            try:
                if self._hasher.verify(candidate.key_hash, presented):
                    return candidate
            except (VerifyMismatchError, Argon2Error, ValueError, TypeError):
                continue
        return None

    def permissions_for(self, api_key: API_Key) -> frozenset[Permission]:
        """Return the Permissions an API_Key grants, derived from its Role via RBAC."""
        return self._rbac.permissions_for(api_key.role)

    def list(self, org_id: UUID) -> list[API_Key]:
        """Return every API_Key scoped to ``org_id`` (metadata only; Req 5.4, 5.7)."""
        return self._store.list_for_org(org_id)

    def revoke(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Revoke ``key_id`` iff it belongs to ``org_id``; else ``None`` (Req 5.5, 5.7).

        A ``None`` result means the key is unknown or belongs to a different org — the
        router surfaces that as ``AppError("not_found", 404)``.
        """
        return self._store.revoke_for_org(org_id, key_id)


class InMemory_API_Key_Store(API_Key_Store):
    """Process-memory API_Key_Store — keyless double for tests/standalone runs."""

    def __init__(self) -> None:
        self._keys: dict[UUID, API_Key] = {}

    def create(self, api_key: API_Key) -> API_Key:
        """Persist an API_Key row (only the hash, never the secret) and return it."""
        self._keys[api_key.id] = api_key
        return api_key

    def list_active_by_prefix(self, prefix: str) -> list[API_Key]:
        """Return active (non-revoked) keys whose ``key_prefix`` equals ``prefix``."""
        return [
            k
            for k in self._keys.values()
            if k.key_prefix == prefix and k.revoked_at is None
        ]

    def list_for_org(self, org_id: UUID) -> list[API_Key]:
        """Return every API_Key scoped to ``org_id``."""
        return [k for k in self._keys.values() if k.org_id == org_id]

    def get_for_org(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Return the API_Key ``key_id`` iff it belongs to ``org_id`` (Req 5.7)."""
        key = self._keys.get(key_id)
        return key if key is not None and key.org_id == org_id else None

    def revoke_for_org(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Mark ``key_id`` revoked iff it belongs to ``org_id``; else ``None``."""
        key = self.get_for_org(org_id, key_id)
        if key is None:
            return None
        if key.revoked_at is None:
            key.revoked_at = _utcnow()
        return key


class Pg_API_Key_Store(API_Key_Store):
    """Synchronous Postgres-backed API_Key_Store, mirroring ``PgConversation_Store``.

    Uses the ``api_keys`` table from migration ``0006`` and its indexed
    ``key_prefix WHERE revoked_at IS NULL`` for O(1) active-candidate lookup.
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def create(self, api_key: API_Key) -> API_Key:
        """Persist an API_Key row and return it."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO api_keys
                        (id, org_id, role, key_prefix, key_hash, revoked_at, created_at)
                    VALUES
                        (:id, :org_id, :role, :key_prefix, :key_hash, :revoked_at, :created_at)
                    """
                ),
                {
                    "id": str(api_key.id),
                    "org_id": str(api_key.org_id),
                    "role": api_key.role.value,
                    "key_prefix": api_key.key_prefix,
                    "key_hash": api_key.key_hash,
                    "revoked_at": api_key.revoked_at,
                    "created_at": api_key.created_at,
                },
            )
        return api_key

    def list_active_by_prefix(self, prefix: str) -> list[API_Key]:
        """Return active (non-revoked) keys whose ``key_prefix`` equals ``prefix``."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, org_id, role, key_prefix, key_hash, revoked_at, created_at "
                    "FROM api_keys WHERE key_prefix = :prefix AND revoked_at IS NULL"
                ),
                {"prefix": prefix},
            ).fetchall()
        return [self._row_to_key(r) for r in rows]

    def list_for_org(self, org_id: UUID) -> list[API_Key]:
        """Return every API_Key scoped to ``org_id``."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, org_id, role, key_prefix, key_hash, revoked_at, created_at "
                    "FROM api_keys WHERE org_id = :org_id ORDER BY created_at ASC"
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [self._row_to_key(r) for r in rows]

    def get_for_org(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Return the API_Key ``key_id`` iff it belongs to ``org_id`` (Req 5.7)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, org_id, role, key_prefix, key_hash, revoked_at, created_at "
                    "FROM api_keys WHERE id = :id AND org_id = :org_id"
                ),
                {"id": str(key_id), "org_id": str(org_id)},
            ).first()
        return self._row_to_key(row) if row is not None else None

    def revoke_for_org(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Mark ``key_id`` revoked iff it belongs to ``org_id``; else ``None``.

        Idempotent: an already-revoked key keeps its original ``revoked_at``. A cross-org
        or unknown key matches no row and returns ``None``.
        """
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE api_keys
                    SET revoked_at = COALESCE(revoked_at, now())
                    WHERE id = :id AND org_id = :org_id
                    RETURNING id, org_id, role, key_prefix, key_hash, revoked_at, created_at
                    """
                ),
                {"id": str(key_id), "org_id": str(org_id)},
            ).first()
        return self._row_to_key(row) if row is not None else None

    @staticmethod
    def _row_to_key(row) -> API_Key:
        return API_Key(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            role=Role(row[2]),
            key_prefix=row[3],
            key_hash=row[4],
            revoked_at=row[5],
            created_at=row[6],
        )
