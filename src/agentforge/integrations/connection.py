"""Integration_Connection — optional, additive, org-scoped non-secret persistence.

Optional persistence of **non-secret** per-org integration configuration (e.g. a default
Slack channel). It never stores credential material, and enablement never depends on it — a
Disabled/Enabled decision is derived solely from ``Settings`` (Req 11.4, 11.5).

Tenant isolation is enforced at the data-access layer: every method takes ``org_id`` as a
required parameter, so a cross-tenant read/mutate matches no row → ``None``/``[]`` → the
caller raises ``AppError("not_found", 404)`` — 404, never 403 (Req 11.1, 11.2). The
in-memory store below is the keyless default; the Postgres-backed store uses migration
``0011``.

The store deliberately does **not** police config *shape* — that is
``integrations/config_policy.py``, applied where untrusted input enters. What the store
guarantees is that a ``SecretStr`` can never be persisted and that every read/write is
constrained by ``org_id``.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import SecretStr


@dataclass
class Integration_Connection:
    """A per-org, non-secret integration configuration record (Req 11.1, 11.4)."""

    id: UUID
    org_id: UUID
    integration: str
    config: dict  # NON-SECRET only (e.g. {"default_channel": "#general"})
    created_at: datetime


def _reject_secret_config(config: dict | None) -> dict:
    """Return a shallow copy of ``config``, rejecting any credential/SecretStr value (Req 11.4).

    The store structurally never accepts or persists a ``SecretStr``; a defensive check keeps
    an accidental credential out of persistence entirely.
    """
    materialized = dict(config or {})
    for key, value in materialized.items():
        if isinstance(value, SecretStr):
            raise ValueError(
                f"integration connection config must not contain a secret value: {key!r}"
            )
    return materialized


class Integration_Connection_Store(ABC):
    """Abstract org-scoped store for non-secret Integration_Connection records.

    Every method takes ``org_id`` as a required parameter and never accepts or persists a
    credential / ``SecretStr`` field (Req 11.1, 11.4).
    """

    @abstractmethod
    def create(self, org_id: UUID, integration: str, config: dict) -> Integration_Connection:
        raise NotImplementedError

    @abstractmethod
    def get(self, org_id: UUID, connection_id: UUID) -> Integration_Connection | None:
        raise NotImplementedError

    @abstractmethod
    def list_for_org(self, org_id: UUID) -> list[Integration_Connection]:
        raise NotImplementedError

    @abstractmethod
    def update_config(
        self, org_id: UUID, connection_id: UUID, config: dict
    ) -> Integration_Connection | None:
        """Replace a connection's config iff it belongs to ``org_id``.

        Returns the updated record, or ``None`` when no row matched — so an unknown or
        cross-tenant connection is the uniform 404, never a 403 (Req 11.1, 11.2). The
        config is **replaced**, not merged: a partial merge would make removing a setting
        impossible, and the record is small enough that the client always holds all of it.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, org_id: UUID, connection_id: UUID) -> bool:
        """Delete a connection iff it belongs to ``org_id``; ``False`` when none matched."""
        raise NotImplementedError


class InMemory_Integration_Connection_Store(Integration_Connection_Store):
    """Keyless default store keyed by ``(org_id, id)`` so cross-org access finds no row.

    A cross-org ``get`` returns ``None`` and ``list_for_org`` returns ``[]`` for an org with
    no rows — tenant isolation at the data-access layer (Req 11.1, 11.2).
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[UUID, UUID], Integration_Connection] = {}

    def create(self, org_id: UUID, integration: str, config: dict) -> Integration_Connection:
        connection = Integration_Connection(
            id=uuid4(),
            org_id=org_id,
            integration=integration,
            config=_reject_secret_config(config),
            created_at=datetime.now(timezone.utc),
        )
        self._by_key[(org_id, connection.id)] = connection
        return connection

    def get(self, org_id: UUID, connection_id: UUID) -> Integration_Connection | None:
        return self._by_key.get((org_id, connection_id))

    def list_for_org(self, org_id: UUID) -> list[Integration_Connection]:
        return sorted(
            (
                connection
                for (owner_org, _cid), connection in self._by_key.items()
                if owner_org == org_id
            ),
            key=lambda c: (c.created_at, str(c.id)),
        )

    def update_config(
        self, org_id: UUID, connection_id: UUID, config: dict
    ) -> Integration_Connection | None:
        """Replace the config of ``connection_id`` iff owned by ``org_id`` (Req 11.2)."""
        existing = self._by_key.get((org_id, connection_id))
        if existing is None:
            return None
        updated = Integration_Connection(
            id=existing.id,
            org_id=existing.org_id,
            integration=existing.integration,
            config=_reject_secret_config(config),
            created_at=existing.created_at,
        )
        self._by_key[(org_id, connection_id)] = updated
        return updated

    def delete(self, org_id: UUID, connection_id: UUID) -> bool:
        """Delete ``connection_id`` iff owned by ``org_id`` (Req 11.2)."""
        return self._by_key.pop((org_id, connection_id), None) is not None


class Pg_Integration_Connection_Store(Integration_Connection_Store):
    """Synchronous Postgres-backed store, mirroring ``Pg_Usage_Store`` / ``Pg_*`` stores.

    Uses the ``integration_connections`` table from migration ``0011``. Every method
    constrains its SQL by ``WHERE org_id = :org_id`` (``create`` inserts the row under its
    ``org_id``; ``get`` / ``list_for_org`` filter by it), so a cross-tenant read matches
    zero rows → ``None`` / ``[]`` → the caller raises ``AppError("not_found", 404)`` — 404,
    never 403 (Req 11.1, 11.2). There is **no** column for a token/secret and the store
    never accepts or persists credential material (Req 4.3, 11.4).
    """

    def __init__(self, database_url: str, engine=None) -> None:
        # Local imports keep the keyless in-memory path free of SQLAlchemy/psycopg.
        from sqlalchemy import create_engine

        from agentforge.conversation.store import _to_sqlalchemy_sync_dsn

        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def create(self, org_id: UUID, integration: str, config: dict) -> Integration_Connection:
        """Persist a non-secret connection row scoped to ``org_id`` and return it."""
        from sqlalchemy import text

        connection = Integration_Connection(
            id=uuid4(),
            org_id=org_id,
            integration=integration,
            config=_reject_secret_config(config),
            created_at=datetime.now(timezone.utc),
        )
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO integration_connections
                        (id, org_id, integration, config, created_at)
                    VALUES
                        (:id, :org_id, :integration, CAST(:config AS JSONB), :created_at)
                    """
                ),
                {
                    "id": str(connection.id),
                    "org_id": str(connection.org_id),
                    "integration": connection.integration,
                    "config": json.dumps(connection.config),
                    "created_at": connection.created_at,
                },
            )
        return connection

    def get(self, org_id: UUID, connection_id: UUID) -> Integration_Connection | None:
        """Return the connection iff owned by ``org_id``; SQL scoped by ``org_id`` (Req 11.2)."""
        from sqlalchemy import text

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, org_id, integration, config, created_at
                    FROM integration_connections
                    WHERE org_id = :org_id AND id = :id
                    """
                ),
                {"org_id": str(org_id), "id": str(connection_id)},
            ).fetchone()
        return self._row_to_connection(row) if row is not None else None

    def list_for_org(self, org_id: UUID) -> list[Integration_Connection]:
        """Return only ``org_id``'s connections; SQL scoped by ``org_id`` (Req 11.2)."""
        from sqlalchemy import text

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, org_id, integration, config, created_at
                    FROM integration_connections
                    WHERE org_id = :org_id
                    ORDER BY created_at ASC
                    """
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    def update_config(
        self, org_id: UUID, connection_id: UUID, config: dict
    ) -> Integration_Connection | None:
        """Replace the config iff the row belongs to ``org_id``; SQL scoped by it (Req 11.2)."""
        from sqlalchemy import text

        accepted = _reject_secret_config(config)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE integration_connections
                    SET config = CAST(:config AS JSONB)
                    WHERE org_id = :org_id AND id = :id
                    RETURNING id, org_id, integration, config, created_at
                    """
                ),
                {
                    "config": json.dumps(accepted),
                    "org_id": str(org_id),
                    "id": str(connection_id),
                },
            ).fetchone()
        return self._row_to_connection(row) if row is not None else None

    def delete(self, org_id: UUID, connection_id: UUID) -> bool:
        """Delete the row iff it belongs to ``org_id``; SQL scoped by it (Req 11.2)."""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM integration_connections "
                    "WHERE org_id = :org_id AND id = :id"
                ),
                {"org_id": str(org_id), "id": str(connection_id)},
            )
        return result.rowcount > 0

    @staticmethod
    def _row_to_connection(row) -> Integration_Connection:
        config = row[3]
        if isinstance(config, str):
            config = json.loads(config)
        return Integration_Connection(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            integration=row[2],
            config=config or {},
            created_at=row[4],
        )
