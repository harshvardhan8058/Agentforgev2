"""Multi_Agent_Run_Store — ABC + InMemory and Postgres implementations (Phase 4).

The ``Multi_Agent_Run_Store`` persists the Multi_Agent_Run lifecycle: the run itself, its
per-agent messages, the human ``Approval_Decision`` history, resumable ``Run_Checkpoint``
snapshots, and the terminal ``Final_Output`` / ``Termination_Reason`` (Req 10.1-10.5).

Two implementations honor the same contract:

* :class:`InMemory_Multi_Agent_Run_Store` is the dependency-free, keyless double used by
  property/unit tests and standalone runs. Blackboard snapshots are deep-copied on
  ``save_checkpoint`` / ``load_checkpoint`` so callers cannot corrupt stored state.
* :class:`Pg_Multi_Agent_Run_Store` persists to the existing Postgres instance (tables
  from ``migrations/0005_create_multi_agent_runs.sql``), mirroring
  :class:`PgConversation_Store` — synchronous SQL through a psycopg-backed SQLAlchemy
  engine so it can be driven from a worker thread off the event loop. Agent messages
  reuse the existing ``messages`` table (role = ``role_id``, position = ordinal) so no
  new schema is needed for them (Req 10.2).

The SQLAlchemy / psycopg imports live inside :class:`Pg_Multi_Agent_Run_Store` so the
keyless in-memory path never requires those dependencies, matching the pattern used by
``Pg_Trace_Recorder`` elsewhere in the repo.
"""

from __future__ import annotations

import copy
import threading
import uuid
from abc import ABC, abstractmethod

from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Approval_Decision,
    ApprovalDecisionType,
    Final_Output,
    Multi_Agent_Run,
    Termination_Reason,
)


class Multi_Agent_Run_Store(ABC):
    """Persists the Multi_Agent_Run lifecycle (Req 10.1-10.5)."""

    @abstractmethod
    def create(self, conversation_id: str, task: str) -> Multi_Agent_Run:
        """Create and persist a new Multi_Agent_Run (Req 10.1)."""

    @abstractmethod
    def append_message(self, run_id: str, role_id: str, content: str) -> int:
        """Persist an agent message and return its ordinal position (Req 10.2)."""

    @abstractmethod
    def record_decision(self, run_id: str, decision: Approval_Decision) -> None:
        """Persist an applied Approval_Decision in append order (Req 10.3)."""

    @abstractmethod
    def save_checkpoint(self, run_id: str, checkpoint: str, blackboard: dict) -> None:
        """Persist a Run_Checkpoint sufficient to resume the run (Req 10.4)."""

    @abstractmethod
    def load_checkpoint(self, run_id: str) -> tuple[str, dict] | None:
        """Return the most recent ``(checkpoint_name, blackboard)`` for the run, or ``None``."""

    @abstractmethod
    def terminate(
        self,
        run_id: str,
        final_output: Final_Output | None,
        reason: Termination_Reason,
    ) -> None:
        """Persist the Final_Output and Termination_Reason for the run (Req 10.5)."""

    @abstractmethod
    def get(self, run_id: str) -> Multi_Agent_Run | None:
        """Return the persisted Multi_Agent_Run, or ``None`` if unknown."""


# --------------------------------------------------------------------------- InMemory


class InMemory_Multi_Agent_Run_Store(Multi_Agent_Run_Store):
    """Process-memory ``Multi_Agent_Run_Store`` — keyless double for tests/standalone runs.

    Thread-safe for the concurrent access pattern the property tests exercise: every
    mutating operation is serialized by a single lock, and blackboard snapshots are
    deep-copied on the way in and out so mutations to the caller's dict cannot corrupt
    stored state.
    """

    def __init__(self) -> None:
        self._runs: dict[str, Multi_Agent_Run] = {}
        # Per-run parallel state: messages (ordered), decisions (ordered), checkpoints
        # (append-only; the latest wins on load).
        self._messages: dict[str, list[tuple[str, str, int]]] = {}
        self._decisions: dict[str, list[Approval_Decision]] = {}
        self._checkpoints: dict[str, list[tuple[str, dict]]] = {}
        self._lock = threading.Lock()

    def create(self, conversation_id: str, task: str) -> Multi_Agent_Run:
        """Insert a new Multi_Agent_Run with a unique id, status=``running`` (Req 10.1)."""
        run = Multi_Agent_Run(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            task=task,
            status="running",
        )
        with self._lock:
            self._runs[run.id] = run
            self._messages[run.id] = []
            self._decisions[run.id] = []
            self._checkpoints[run.id] = []
        return run

    def append_message(self, run_id: str, role_id: str, content: str) -> int:
        """Append a (role_id, content) message; return the assigned 0-based ordinal (Req 10.2)."""
        with self._lock:
            bucket = self._messages.setdefault(run_id, [])
            position = len(bucket)
            bucket.append((role_id, content, position))
        return position

    def record_decision(self, run_id: str, decision: Approval_Decision) -> None:
        """Persist an Approval_Decision in append order (Req 10.3)."""
        with self._lock:
            self._decisions.setdefault(run_id, []).append(decision)

    def save_checkpoint(
        self, run_id: str, checkpoint: str, blackboard: dict
    ) -> None:
        """Persist a Run_Checkpoint (blackboard is deep-copied) (Req 10.4)."""
        snapshot = copy.deepcopy(blackboard)
        with self._lock:
            self._checkpoints.setdefault(run_id, []).append((checkpoint, snapshot))

    def load_checkpoint(self, run_id: str) -> tuple[str, dict] | None:
        """Return the latest ``(checkpoint, blackboard)`` (deep-copied), or ``None``."""
        with self._lock:
            history = self._checkpoints.get(run_id)
            if not history:
                return None
            checkpoint, blackboard = history[-1]
            return checkpoint, copy.deepcopy(blackboard)

    def terminate(
        self,
        run_id: str,
        final_output: Final_Output | None,
        reason: Termination_Reason,
    ) -> None:
        """Set the run's status/termination_reason/final_output (Req 10.5)."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = "terminated"
            run.termination_reason = reason
            run.final_output = final_output

    def get(self, run_id: str) -> Multi_Agent_Run | None:
        """Return the persisted Multi_Agent_Run, or ``None`` if unknown."""
        with self._lock:
            return self._runs.get(run_id)

    # ------------------------------------------------------------------ read helpers

    def messages(self, run_id: str) -> list[tuple[str, str, int]]:
        """Return ``(role_id, content, position)`` messages for the run in append order."""
        with self._lock:
            return list(self._messages.get(run_id, []))

    def decisions(self, run_id: str) -> list[Approval_Decision]:
        """Return the recorded Approval_Decisions for the run in append order (Req 10.3)."""
        with self._lock:
            return list(self._decisions.get(run_id, []))


# --------------------------------------------------------------------------- Postgres


class Pg_Multi_Agent_Run_Store(Multi_Agent_Run_Store):
    """Synchronous Postgres-backed ``Multi_Agent_Run_Store`` (Req 10.1-10.6).

    Mirrors :class:`PgConversation_Store`: a single psycopg-backed SQLAlchemy engine, all
    writes wrapped in a transaction, and every read returning framework-agnostic domain
    objects. Reuses the existing ``messages`` table for agent messages (role = ``role_id``,
    position = ordinal within the run's conversation), so no new message schema is needed.
    """

    def __init__(self, database_url: str, engine=None) -> None:
        # Imported here so the keyless in-memory path never requires SQLAlchemy/psycopg,
        # matching Pg_Trace_Recorder's pattern.
        from sqlalchemy import create_engine

        from agentforge.conversation.store import _to_sqlalchemy_sync_dsn

        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def create(self, conversation_id: str, task: str) -> Multi_Agent_Run:
        """Insert a new Multi_Agent_Run row and return it (Req 10.1)."""
        from sqlalchemy import text

        run_id = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO multi_agent_runs (id, conversation_id, task, status)
                    VALUES (:id, :cid, :task, 'running')
                    """
                ),
                {"id": run_id, "cid": conversation_id, "task": task},
            )
        return Multi_Agent_Run(
            id=run_id,
            conversation_id=conversation_id,
            task=task,
            status="running",
        )

    def append_message(self, run_id: str, role_id: str, content: str) -> int:
        """Append an agent message to the run's conversation, returning its ordinal (Req 10.2)."""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conversation_id = conn.execute(
                text("SELECT conversation_id FROM multi_agent_runs WHERE id = :id"),
                {"id": run_id},
            ).scalar_one()
            next_position = conn.execute(
                text(
                    "SELECT COALESCE(MAX(position) + 1, 0) FROM messages "
                    "WHERE conversation_id = :cid"
                ),
                {"cid": conversation_id},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, position)
                    VALUES (:id, :cid, :role, :content, :position)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "cid": conversation_id,
                    "role": role_id,
                    "content": content,
                    "position": int(next_position),
                },
            )
        return int(next_position)

    def record_decision(self, run_id: str, decision: Approval_Decision) -> None:
        """Insert a decision row with ``position = max(position)+1`` for the run (Req 10.3)."""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            next_position = conn.execute(
                text(
                    "SELECT COALESCE(MAX(position) + 1, 0) FROM approval_decisions "
                    "WHERE run_id = :rid"
                ),
                {"rid": run_id},
            ).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO approval_decisions
                        (id, run_id, checkpoint, decision_type, feedback,
                         edited_content, position)
                    VALUES (:id, :rid, :checkpoint, :decision_type, :feedback,
                            :edited_content, :position)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    # The current gate does not attach the checkpoint to a decision; the
                    # column exists for later filtering and defaults to empty.
                    "checkpoint": "",
                    "decision_type": decision.type.value,
                    "feedback": decision.feedback,
                    "edited_content": decision.edited_content,
                    "position": int(next_position),
                },
            )

    def save_checkpoint(
        self, run_id: str, checkpoint: str, blackboard: dict
    ) -> None:
        """Append a Run_Checkpoint snapshot; the latest row wins on load (Req 10.4)."""
        import json

        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO run_checkpoints (id, run_id, checkpoint, blackboard)
                    VALUES (:id, :rid, :checkpoint, CAST(:blackboard AS JSONB))
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    "checkpoint": checkpoint,
                    "blackboard": json.dumps(blackboard),
                },
            )

    def load_checkpoint(self, run_id: str) -> tuple[str, dict] | None:
        """Return the most recent ``(checkpoint, blackboard)`` for the run, or ``None``."""
        import json

        from sqlalchemy import text

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT checkpoint, blackboard FROM run_checkpoints
                    WHERE run_id = :rid ORDER BY created_at DESC, id DESC LIMIT 1
                    """
                ),
                {"rid": run_id},
            ).one_or_none()
        if row is None:
            return None
        checkpoint = row[0]
        blackboard = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
        return checkpoint, blackboard

    def terminate(
        self,
        run_id: str,
        final_output: Final_Output | None,
        reason: Termination_Reason,
    ) -> None:
        """Persist the Final_Output + Termination_Reason and mark the run terminated (Req 10.5)."""
        import json

        from sqlalchemy import text

        content = final_output.content if final_output is not None else None
        citations = (
            [
                {"document_id": c.document_id, "chunk_id": c.chunk_id}
                for c in final_output.citations
            ]
            if final_output is not None
            else []
        )
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE multi_agent_runs
                    SET status = 'terminated',
                        termination_reason = :reason,
                        final_output = :final_output,
                        final_citations = CAST(:final_citations AS JSONB),
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "id": run_id,
                    "reason": reason.value,
                    "final_output": content,
                    "final_citations": json.dumps(citations),
                },
            )

    def get(self, run_id: str) -> Multi_Agent_Run | None:
        """Return the persisted Multi_Agent_Run, hydrating the Final_Output when set."""
        import json

        from sqlalchemy import text

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, conversation_id, task, status, termination_reason,
                           final_output, final_citations
                    FROM multi_agent_runs WHERE id = :id
                    """
                ),
                {"id": run_id},
            ).one_or_none()
        if row is None:
            return None
        raw_citations = row[6]
        citations_json = (
            raw_citations if isinstance(raw_citations, list) else json.loads(raw_citations or "[]")
        )
        final_output: Final_Output | None = None
        if row[5] is not None:
            final_output = Final_Output(
                content=row[5],
                citations=[
                    Citation(document_id=c["document_id"], chunk_id=c["chunk_id"])
                    for c in citations_json
                ],
            )
        termination_reason = (
            Termination_Reason(row[4]) if row[4] is not None else None
        )
        return Multi_Agent_Run(
            id=str(row[0]),
            conversation_id=str(row[1]) if row[1] is not None else "",
            task=row[2],
            status=row[3],
            termination_reason=termination_reason,
            final_output=final_output,
        )

    # ------------------------------------------------------------------ read helpers

    def messages(self, run_id: str) -> list[tuple[str, str, int]]:
        """Return the run's agent messages ``(role_id, content, position)`` in order."""
        from sqlalchemy import text

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT m.role, m.content, m.position
                    FROM messages m
                    JOIN multi_agent_runs r ON r.conversation_id = m.conversation_id
                    WHERE r.id = :rid
                    ORDER BY m.position ASC
                    """
                ),
                {"rid": run_id},
            ).fetchall()
        return [(r[0], r[1], int(r[2])) for r in rows]

    def decisions(self, run_id: str) -> list[Approval_Decision]:
        """Return the recorded Approval_Decisions for the run in append order (Req 10.3)."""
        from sqlalchemy import text

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT decision_type, feedback, edited_content, position
                    FROM approval_decisions WHERE run_id = :rid ORDER BY position ASC
                    """
                ),
                {"rid": run_id},
            ).fetchall()
        return [
            Approval_Decision(
                type=ApprovalDecisionType(r[0]),
                feedback=r[1],
                edited_content=r[2],
            )
            for r in rows
        ]
