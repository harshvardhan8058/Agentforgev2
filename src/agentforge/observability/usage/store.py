"""Usage_Store implementations: ``InMemory_Usage_Store`` and ``Pg_Usage_Store``.

Both constrain every query by ``org_id`` so cross-org rows are never returned (Req 2.3,
3.3, 10.3). The keyless in-memory store backs the property/unit lanes; the synchronous
SQLAlchemy ``Pg_Usage_Store`` mirrors the Phase 5 ``Pg_*`` stores (e.g. ``Pg_Identity_Store``)
and maps onto the ``usage_records`` table from migration ``0008``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.base import Usage_Store


class InMemory_Usage_Store(Usage_Store):
    """Keyless/test in-memory Usage_Store keyed/filtered by ``org_id`` (Req 2.3, 3.3)."""

    def __init__(self) -> None:
        self._records: list[Usage_Record] = []

    def add(self, record: Usage_Record) -> Usage_Record:
        """Append ``record`` and return it (persisted scoped to its ``org_id``)."""
        self._records.append(record)
        return record

    def list_for_org(
        self, org_id: UUID, *, start: datetime, end: datetime
    ) -> list[Usage_Record]:
        """Return only ``org_id``'s records within ``[start, end]`` (never cross-org)."""
        return [
            record
            for record in self._records
            if record.org_id == org_id and start <= record.created_at <= end
        ]


class Pg_Usage_Store(Usage_Store):
    """Synchronous Postgres-backed Usage_Store, mirroring ``Pg_Identity_Store``.

    Uses the ``usage_records`` table from migration ``0008``. Both ``add`` and
    ``list_for_org`` constrain SQL by ``WHERE org_id = :org_id`` (and ``list_for_org``
    additionally by the ``[start, end]`` time range), so a cross-org read matches zero
    rows and can never return another tenant's usage (Req 2.3, 3.3, 10.3).
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def add(self, record: Usage_Record) -> Usage_Record:
        """Persist a Usage_Record row (scoped to its ``org_id``) and return it."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO usage_records
                        (id, org_id, user_id, provider, model, prompt_tokens,
                         completion_tokens, total_tokens, cost, created_at)
                    VALUES
                        (:id, :org_id, :user_id, :provider, :model, :prompt_tokens,
                         :completion_tokens, :total_tokens, :cost, :created_at)
                    """
                ),
                {
                    "id": str(record.id),
                    "org_id": str(record.org_id),
                    "user_id": str(record.user_id) if record.user_id is not None else None,
                    "provider": record.provider,
                    "model": record.model,
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                    "total_tokens": record.total_tokens,
                    "cost": record.cost,
                    "created_at": record.created_at,
                },
            )
        return record

    def list_for_org(
        self, org_id: UUID, *, start: datetime, end: datetime
    ) -> list[Usage_Record]:
        """Return ``org_id``'s records within ``[start, end]``; SQL scoped by ``org_id``."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, org_id, user_id, provider, model, prompt_tokens,
                           completion_tokens, total_tokens, cost, created_at
                    FROM usage_records
                    WHERE org_id = :org_id
                      AND created_at >= :start
                      AND created_at <= :end
                    ORDER BY created_at ASC
                    """
                ),
                {"org_id": str(org_id), "start": start, "end": end},
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row) -> Usage_Record:
        return Usage_Record(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            user_id=UUID(str(row[2])) if row[2] is not None else None,
            provider=row[3],
            model=row[4],
            prompt_tokens=row[5],
            completion_tokens=row[6],
            total_tokens=row[7],
            cost=row[8] if isinstance(row[8], Decimal) else Decimal(str(row[8])),
            created_at=row[9],
        )
