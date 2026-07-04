"""Trace recorders — a keyless in-memory recorder and a Postgres-backed recorder.

``InMemory_Trace_Recorder`` is the lightweight, dependency-free default used on the
keyless path and in tests. It appends a :class:`Trace_Entry` per executed Agent_Step with
a contiguous ascending ordinal per run and (for tool calls) the tool name and outcome,
and returns the ordered :class:`Trace` through the ``Trace_Recorder`` interface so a later
observability phase can consume it without modifying the Agent_Orchestrator (Req 10.1-10.4).

``Pg_Trace_Recorder`` persists the same entries to the existing Postgres instance (tables
from ``migrations/0004_create_agent_traces.sql``) for later inspection, honoring the same
``Trace_Recorder`` contract so it is swappable behind the seam without touching the core.
"""

from __future__ import annotations

import json
import uuid
from uuid import UUID

from agentforge.tracing.base import Trace, Trace_Entry, Trace_Recorder


class InMemory_Trace_Recorder(Trace_Recorder):
    """A keyless, in-memory ``Trace_Recorder`` keyed by ``(org_id, run_id)``.

    A run is bound to the ``org_id`` of its first recorded entry (its owning Agent_Run's
    tenant), so ``get_trace`` from a different org returns an empty Trace (Req 4.6, 10.3).
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[UUID, str], list[Trace_Entry]] = {}

    def record(
        self,
        org_id: UUID,
        run_id: str,
        step_type: str,
        *,
        tool_name: str | None = None,
        outcome: str | None = None,
        detail: dict | None = None,
    ) -> Trace_Entry:
        """Append an entry with the next ordinal for ``(org_id, run_id)`` (Req 10.1, 10.2)."""
        run_entries = self._entries.setdefault((org_id, run_id), [])
        entry = Trace_Entry(
            run_id=run_id,
            ordinal=len(run_entries),
            step_type=step_type,
            tool_name=tool_name,
            outcome=outcome,
            detail=detail or {},
        )
        run_entries.append(entry)
        return entry

    def get_trace(self, org_id: UUID, run_id: str) -> Trace:
        """Return ``org_id``'s ordered Trace for ``run_id`` (empty when unknown) (Req 10.3)."""
        entries = list(self._entries.get((org_id, run_id), []))
        return Trace(run_id=run_id, entries=entries)



class Pg_Trace_Recorder(Trace_Recorder):
    """Postgres-backed ``Trace_Recorder`` persisting runs and ordered trace entries.

    Issues **synchronous** SQL through a psycopg-backed SQLAlchemy engine (mirroring
    ``db/store.py``) so it can be driven off the event loop. ``record`` auto-creates the
    ``agent_runs`` row on first use and assigns the next 0-based ordinal within the run,
    matching the in-memory recorder's contiguous ascending ordering (Req 10.1-10.3).
    """

    def __init__(self, database_url: str, engine=None) -> None:
        # Imported here so the keyless in-memory path never requires SQLAlchemy/psycopg.
        from sqlalchemy import create_engine

        from agentforge.conversation.store import _to_sqlalchemy_sync_dsn

        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def record(
        self,
        org_id: UUID,
        run_id: str,
        step_type: str,
        *,
        tool_name: str | None = None,
        outcome: str | None = None,
        detail: dict | None = None,
    ) -> Trace_Entry:
        """Persist an entry with the next ordinal for ``run_id`` under ``org_id`` (Req 10.1, 10.2)."""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            # Auto-create the run row (owned by org_id) so the trace_entries FK is
            # satisfied on first use; the run's org_id is the tenant its trace inherits.
            conn.execute(
                text(
                    "INSERT INTO agent_runs (id, org_id) VALUES (:id, :org_id) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": run_id, "org_id": str(org_id)},
            )
            ordinal = conn.execute(
                text(
                    "SELECT COALESCE(MAX(t.ordinal) + 1, 0) FROM trace_entries t "
                    "JOIN agent_runs r ON r.id = t.run_id "
                    "WHERE t.run_id = :rid AND r.org_id = :org_id"
                ),
                {"rid": run_id, "org_id": str(org_id)},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO trace_entries
                        (id, run_id, ordinal, step_type, tool_name, outcome, detail)
                    VALUES
                        (:id, :rid, :ordinal, :step_type, :tool_name, :outcome,
                         CAST(:detail AS JSONB))
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    "ordinal": int(ordinal),
                    "step_type": step_type,
                    "tool_name": tool_name,
                    "outcome": outcome,
                    "detail": json.dumps(detail or {}),
                },
            )
        return Trace_Entry(
            run_id=run_id,
            ordinal=int(ordinal),
            step_type=step_type,
            tool_name=tool_name,
            outcome=outcome,
            detail=detail or {},
        )

    def get_trace(self, org_id: UUID, run_id: str) -> Trace:
        """Return ``org_id``'s ordered Trace for ``run_id`` (empty when unknown) (Req 10.3)."""
        from sqlalchemy import text

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT t.ordinal, t.step_type, t.tool_name, t.outcome, t.detail
                    FROM trace_entries t
                    JOIN agent_runs r ON r.id = t.run_id
                    WHERE t.run_id = :rid AND r.org_id = :org_id
                    ORDER BY t.ordinal ASC
                    """
                ),
                {"rid": run_id, "org_id": str(org_id)},
            ).fetchall()
        entries = [
            Trace_Entry(
                run_id=run_id,
                ordinal=int(r[0]),
                step_type=r[1],
                tool_name=r[2],
                outcome=r[3],
                detail=r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
            )
            for r in rows
        ]
        return Trace(run_id=run_id, entries=entries)
