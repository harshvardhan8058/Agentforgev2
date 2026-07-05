"""Prompt_Store implementations: ``InMemory_Prompt_Store`` and ``Pg_Prompt_Store``.

Both constrain every query by ``org_id`` so a cross-tenant lookup is structurally
``None``/empty (Req 4.8, 10.3). ``add_version`` is append-only (there is no update path),
so a persisted version's ``body``/``variables`` can never change; the synchronous
``Pg_Prompt_Store`` additionally relies on the ``UNIQUE (template_id, version)`` constraint
from migration ``0009`` to make a duplicate version number structurally impossible
(Req 4.1, 4.2, 4.9, 8.6). The Postgres adapter mirrors the Phase 5 ``Pg_*`` stores.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.observability.models import Prompt_Version
from agentforge.observability.prompt_registry.base import Prompt_Store


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class InMemory_Prompt_Store(Prompt_Store):
    """Keyless/test in-memory Prompt_Store scoped by ``org_id`` (Req 4.8, 10.3)."""

    def __init__(self) -> None:
        self._versions: list[Prompt_Version] = []

    def _for(self, org_id: UUID, name: str) -> list[Prompt_Version]:
        return [
            v
            for v in self._versions
            if v.org_id == org_id and v.template_name == name
        ]

    def next_version_number(self, org_id: UUID, name: str) -> int:
        """Return ``max(version) + 1`` for ``(org_id, name)``, or ``1`` if none (Req 4.1)."""
        existing = self._for(org_id, name)
        return max((v.version for v in existing), default=0) + 1

    def add_version(self, version: Prompt_Version) -> Prompt_Version:
        """Append an immutable Prompt_Version and return it (append-only) (Req 4.2)."""
        self._versions.append(version)
        return version

    def get_version(
        self, org_id: UUID, name: str, version: int
    ) -> Prompt_Version | None:
        """Return the given version for ``(org_id, name)`` or ``None`` (Req 4.4, 4.8)."""
        for v in self._for(org_id, name):
            if v.version == version:
                return v
        return None

    def get_latest(self, org_id: UUID, name: str) -> Prompt_Version | None:
        """Return the highest-numbered version for ``(org_id, name)`` or ``None`` (Req 4.3)."""
        existing = self._for(org_id, name)
        if not existing:
            return None
        return max(existing, key=lambda v: v.version)

    def list_versions(self, org_id: UUID, name: str) -> list[int]:
        """Return the version numbers for ``(org_id, name)`` in ascending order (Req 4.5)."""
        return sorted(v.version for v in self._for(org_id, name))

    def list_template_names(self, org_id: UUID) -> list[str]:
        """Return ``org_id``'s distinct template names ascending; never cross-org (Req 4.8)."""
        names = {v.template_name for v in self._versions if v.org_id == org_id}
        return sorted(names)


class Pg_Prompt_Store(Prompt_Store):
    """Synchronous Postgres-backed Prompt_Store, mirroring ``Pg_Identity_Store``.

    Maps onto the ``prompt_templates`` / ``prompt_versions`` tables from migration
    ``0009``. Every query is scoped by ``org_id``; ``add_version`` relies on the
    ``UNIQUE (template_id, version)`` constraint so a duplicate version is structurally
    impossible (Req 4.8, 8.6, 10.3).
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    @staticmethod
    def _get_template_id(conn, org_id: UUID, name: str) -> UUID | None:
        row = conn.execute(
            text(
                "SELECT id FROM prompt_templates "
                "WHERE org_id = :org_id AND name = :name"
            ),
            {"org_id": str(org_id), "name": name},
        ).first()
        return UUID(str(row[0])) if row is not None else None

    def _ensure_template_id(self, conn, org_id: UUID, name: str) -> UUID:
        existing = self._get_template_id(conn, org_id, name)
        if existing is not None:
            return existing
        template_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO prompt_templates (id, org_id, name, created_at) "
                "VALUES (:id, :org_id, :name, :created_at)"
            ),
            {
                "id": str(template_id),
                "org_id": str(org_id),
                "name": name,
                "created_at": _utcnow(),
            },
        )
        return template_id

    def next_version_number(self, org_id: UUID, name: str) -> int:
        """Return ``max(version) + 1`` for ``(org_id, name)``, or ``1`` if none (Req 4.1)."""
        with self._engine.connect() as conn:
            template_id = self._get_template_id(conn, org_id, name)
            if template_id is None:
                return 1
            row = conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) FROM prompt_versions "
                    "WHERE template_id = :template_id"
                ),
                {"template_id": str(template_id)},
            ).first()
        return int(row[0]) + 1

    def add_version(self, version: Prompt_Version) -> Prompt_Version:
        """Append an immutable Prompt_Version and return it (append-only) (Req 4.2)."""
        with self._engine.begin() as conn:
            template_id = self._ensure_template_id(
                conn, version.org_id, version.template_name
            )
            conn.execute(
                text(
                    """
                    INSERT INTO prompt_versions
                        (id, org_id, template_id, version, body, variables, created_at)
                    VALUES
                        (:id, :org_id, :template_id, :version, :body,
                         CAST(:variables AS JSONB), :created_at)
                    """
                ),
                {
                    "id": str(version.id),
                    "org_id": str(version.org_id),
                    "template_id": str(template_id),
                    "version": version.version,
                    "body": version.body,
                    "variables": json.dumps(list(version.variables)),
                    "created_at": version.created_at,
                },
            )
        return version

    def get_version(
        self, org_id: UUID, name: str, version: int
    ) -> Prompt_Version | None:
        """Return the given version for ``(org_id, name)`` or ``None`` (Req 4.4, 4.8)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT pv.id, pv.org_id, pt.name, pv.version, pv.body,
                           pv.variables, pv.created_at
                    FROM prompt_versions pv
                    JOIN prompt_templates pt ON pt.id = pv.template_id
                    WHERE pv.org_id = :org_id AND pt.name = :name AND pv.version = :version
                    """
                ),
                {"org_id": str(org_id), "name": name, "version": version},
            ).first()
        return self._row_to_version(row) if row is not None else None

    def get_latest(self, org_id: UUID, name: str) -> Prompt_Version | None:
        """Return the highest-numbered version for ``(org_id, name)`` or ``None`` (Req 4.3)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT pv.id, pv.org_id, pt.name, pv.version, pv.body,
                           pv.variables, pv.created_at
                    FROM prompt_versions pv
                    JOIN prompt_templates pt ON pt.id = pv.template_id
                    WHERE pv.org_id = :org_id AND pt.name = :name
                    ORDER BY pv.version DESC
                    LIMIT 1
                    """
                ),
                {"org_id": str(org_id), "name": name},
            ).first()
        return self._row_to_version(row) if row is not None else None

    def list_versions(self, org_id: UUID, name: str) -> list[int]:
        """Return the version numbers for ``(org_id, name)`` in ascending order (Req 4.5)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT pv.version
                    FROM prompt_versions pv
                    JOIN prompt_templates pt ON pt.id = pv.template_id
                    WHERE pv.org_id = :org_id AND pt.name = :name
                    ORDER BY pv.version ASC
                    """
                ),
                {"org_id": str(org_id), "name": name},
            ).fetchall()
        return [int(r[0]) for r in rows]

    def list_template_names(self, org_id: UUID) -> list[str]:
        """Return ``org_id``'s distinct template names ascending; never cross-org (Req 4.8)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT name FROM prompt_templates
                    WHERE org_id = :org_id
                    ORDER BY name ASC
                    """
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [str(r[0]) for r in rows]

    @staticmethod
    def _row_to_version(row) -> Prompt_Version:
        raw_vars = row[5]
        if isinstance(raw_vars, str):
            raw_vars = json.loads(raw_vars)
        return Prompt_Version(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            template_name=row[2],
            version=int(row[3]),
            body=row[4],
            variables=tuple(raw_vars or ()),
            created_at=row[6],
        )
