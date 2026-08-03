"""The webhook outbox: delivery intent written down before anything is dialled.

The difference between *sending* webhooks and *delivering* them. Previously an event was POSTed
inside a background task with two or three retries over a few seconds; a deploy, a crash, or a
consumer that was down for a minute lost it permanently. Now the intent is persisted in the same
request that produced it and a worker drains it, so:

* **A restart cannot lose an event.** The row outlives the process.
* **Retries span hours, not seconds.** An exponential schedule (see :func:`next_attempt_delay`)
  gives a consumer time to be fixed, which is the actual failure mode — a deploy, an expired
  certificate, a full disk.
* **Nothing holds a request or a connection.** Enqueueing is one INSERT. The streamed-run
  connection that used to stay open for a subscriber's timeout closes immediately.
* **Several application instances can share the work** without double-delivering, because
  claiming a row takes a lease in one atomic statement.

The guarantee is **at-least-once**, deliberately. A worker that delivers and then dies before
recording the success will deliver again, and choosing exactly-once here would mean a distributed
transaction with an endpoint the platform does not control. That is why every envelope carries an
``idempotency_key``: the consumer's deduplication is the other half of the contract, and it is
documented in docs/WEBHOOKS.md rather than left as folklore.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.webhooks.base import Webhook_Event

logger = logging.getLogger(__name__)

OutboxStatus = Literal["pending", "delivered", "abandoned"]

#: Longest gap between attempts. Six hours: long enough that an overnight outage is survived
#: without the queue growing, short enough that a fixed consumer is not left waiting a day.
MAX_ATTEMPT_DELAY_SECONDS: Final[float] = 6 * 60 * 60.0

#: How long a claimed row stays leased. Comfortably longer than one attempt's timeout, so a
#: worker mid-request never has its row stolen; short enough that a crashed worker's backlog
#: becomes deliverable again promptly.
LEASE_SECONDS: Final[float] = 120.0


def next_attempt_delay(attempts: int, *, base_seconds: float) -> timedelta:
    """Return the delay before attempt number ``attempts + 1``.

    Exponential from ``base_seconds``, capped at :data:`MAX_ATTEMPT_DELAY_SECONDS`. With the
    default 60-second base that is roughly 1m, 2m, 4m, 8m, 16m… — the first retry is soon
    enough for a restarting consumer, and the later ones are far enough apart that a persistently
    broken endpoint costs almost nothing.

    Deliberately not jittered. Jitter matters when many clients retry against one server; here
    the retries of one tenant's events are already spread by when they were enqueued, and a
    deterministic schedule is one an operator can predict from ``attempts`` alone.
    """
    delay = base_seconds * (2 ** max(0, attempts - 1))
    return timedelta(seconds=min(delay, MAX_ATTEMPT_DELAY_SECONDS))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Outbox_Entry:
    """One event awaiting delivery to one subscription.

    ``id`` doubles as the delivery id in the ``X-AgentForge-Delivery`` header and the envelope,
    so retries of this entry are recognisable to the consumer and the row an operator is reading
    is the one the consumer saw.
    """

    id: UUID
    org_id: UUID
    subscription_id: UUID
    event: Webhook_Event
    payload: dict[str, object]
    idempotency_key: str | None
    status: OutboxStatus
    attempts: int
    next_attempt_at: datetime
    leased_until: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def new(
        *,
        org_id: UUID,
        subscription_id: UUID,
        event: Webhook_Event,
        payload: dict[str, object],
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> Outbox_Entry:
        """Build a pending entry due immediately."""
        moment = now or _utcnow()
        return Outbox_Entry(
            id=uuid.uuid4(),
            org_id=org_id,
            subscription_id=subscription_id,
            event=event,
            payload=payload,
            idempotency_key=idempotency_key,
            status="pending",
            attempts=0,
            next_attempt_at=moment,
            leased_until=None,
            last_error=None,
            created_at=moment,
            updated_at=moment,
        )


class Webhook_Outbox:
    """Persistence seam for delivery intent.

    ``claim_due`` is the only method with a concurrency contract, and it is the reason this is a
    seam rather than a table the worker queries directly: it must atomically select *and* lease,
    so two workers never take the same row.
    """

    def enqueue(self, entry: Outbox_Entry) -> Outbox_Entry:  # pragma: no cover - interface
        raise NotImplementedError

    def claim_due(
        self, *, limit: int, now: datetime | None = None
    ) -> list[Outbox_Entry]:  # pragma: no cover - interface
        """Atomically lease up to ``limit`` due entries and return them, oldest due first.

        The order is part of the contract, not incidental: the longest-waiting event should be
        attempted first, and a caller that had to re-sort would be compensating for the store.
        """
        raise NotImplementedError

    def mark_delivered(
        self, entry_id: UUID, *, attempts: int
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def reschedule(
        self, entry_id: UUID, *, attempts: int, next_attempt_at: datetime, error: str | None
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def abandon(
        self, entry_id: UUID, *, attempts: int, error: str | None
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get(
        self, org_id: UUID, entry_id: UUID
    ) -> Outbox_Entry | None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_for_org(
        self, org_id: UUID, *, status: OutboxStatus | None = None, limit: int = 50
    ) -> list[Outbox_Entry]:  # pragma: no cover - interface
        raise NotImplementedError

    def list_outstanding(
        self,
        org_id: UUID,
        *,
        status: OutboxStatus | None = None,
        limit: int = 25,
    ) -> list[Outbox_Entry]:  # pragma: no cover - interface
        """Return entries that have NOT been delivered, newest first.

        Separate from :meth:`list_for_org` because the operator-facing question is "what has not
        arrived", and answering it with delivered rows too would bury the three that matter under a
        page of successes. What *did* arrive is the delivery log's job.
        """
        raise NotImplementedError

    def status_counts(self, org_id: UUID) -> dict[str, int]:  # pragma: no cover - interface
        """Return ``{status: count}`` for the org, so a console can be honest about totals.

        Counted over the whole queue rather than the returned page: "12 waiting, 3 gave up" is the
        number an operator needs, and paginating it would make it a lie.
        """
        raise NotImplementedError

    def pending_count(self, org_id: UUID) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def requeue(
        self, org_id: UUID, entry_id: UUID, *, now: datetime | None = None
    ) -> Outbox_Entry | None:  # pragma: no cover - interface
        """Make an abandoned entry due again, resetting its attempt count."""
        raise NotImplementedError

    def prune_settled(
        self, *, older_than: datetime
    ) -> int:  # pragma: no cover - interface
        """Delete delivered entries settled before ``older_than``; return how many."""
        raise NotImplementedError


class InMemory_Webhook_Outbox(Webhook_Outbox):
    """Keyless/test outbox. Single-process, and leases are honoured so the worker logic is
    exercised identically to production."""

    def __init__(self) -> None:
        self._entries: dict[UUID, Outbox_Entry] = {}

    def enqueue(self, entry: Outbox_Entry) -> Outbox_Entry:
        self._entries[entry.id] = entry
        return entry

    def claim_due(self, *, limit: int, now: datetime | None = None) -> list[Outbox_Entry]:
        moment = now or _utcnow()
        due = [
            e
            for e in self._entries.values()
            if e.status == "pending"
            and e.next_attempt_at <= moment
            and (e.leased_until is None or e.leased_until <= moment)
        ]
        due.sort(key=lambda e: (e.next_attempt_at, str(e.id)))
        claimed: list[Outbox_Entry] = []
        for entry in due[:limit]:
            leased = replace(
                entry,
                leased_until=moment + timedelta(seconds=LEASE_SECONDS),
                updated_at=moment,
            )
            self._entries[entry.id] = leased
            claimed.append(leased)
        return claimed

    def mark_delivered(self, entry_id: UUID, *, attempts: int) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        self._entries[entry_id] = replace(
            entry,
            status="delivered",
            attempts=attempts,
            leased_until=None,
            last_error=None,
            updated_at=_utcnow(),
        )

    def reschedule(
        self, entry_id: UUID, *, attempts: int, next_attempt_at: datetime, error: str | None
    ) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        self._entries[entry_id] = replace(
            entry,
            status="pending",
            attempts=attempts,
            next_attempt_at=next_attempt_at,
            leased_until=None,
            last_error=error,
            updated_at=_utcnow(),
        )

    def abandon(self, entry_id: UUID, *, attempts: int, error: str | None) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        self._entries[entry_id] = replace(
            entry,
            status="abandoned",
            attempts=attempts,
            leased_until=None,
            last_error=error,
            updated_at=_utcnow(),
        )

    def get(self, org_id: UUID, entry_id: UUID) -> Outbox_Entry | None:
        entry = self._entries.get(entry_id)
        return entry if entry is not None and entry.org_id == org_id else None

    def list_for_org(
        self, org_id: UUID, *, status: OutboxStatus | None = None, limit: int = 50
    ) -> list[Outbox_Entry]:
        found = [
            e
            for e in self._entries.values()
            if e.org_id == org_id and (status is None or e.status == status)
        ]
        found.sort(key=lambda e: (e.created_at, str(e.id)), reverse=True)
        return found[:limit]

    def list_outstanding(
        self, org_id: UUID, *, status: OutboxStatus | None = None, limit: int = 25
    ) -> list[Outbox_Entry]:
        wanted = ("pending", "abandoned") if status is None else (status,)
        found = [
            e
            for e in self._entries.values()
            if e.org_id == org_id and e.status in wanted and e.status != "delivered"
        ]
        found.sort(key=lambda e: (e.created_at, str(e.id)), reverse=True)
        return found[:limit]

    def status_counts(self, org_id: UUID) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self._entries.values():
            if entry.org_id == org_id:
                counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    def pending_count(self, org_id: UUID) -> int:
        return self.status_counts(org_id).get("pending", 0)

    def requeue(
        self, org_id: UUID, entry_id: UUID, *, now: datetime | None = None
    ) -> Outbox_Entry | None:
        entry = self.get(org_id, entry_id)
        if entry is None or entry.status != "abandoned":
            return None
        moment = now or _utcnow()
        requeued = replace(
            entry,
            status="pending",
            attempts=0,
            next_attempt_at=moment,
            leased_until=None,
            updated_at=moment,
        )
        self._entries[entry_id] = requeued
        return requeued

    def prune_settled(self, *, older_than: datetime) -> int:
        doomed = [
            e.id
            for e in self._entries.values()
            if e.status == "delivered" and e.updated_at < older_than
        ]
        for entry_id in doomed:
            del self._entries[entry_id]
        return len(doomed)


_COLUMNS = (
    "id, org_id, subscription_id, event, payload, idempotency_key, status, attempts, "
    "next_attempt_at, leased_until, last_error, created_at, updated_at"
)


class Pg_Webhook_Outbox(Webhook_Outbox):
    """Postgres-backed outbox over ``webhook_outbox`` (migration 0017)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def enqueue(self, entry: Outbox_Entry) -> Outbox_Entry:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_outbox
                        (id, org_id, subscription_id, event, payload, idempotency_key,
                         status, attempts, next_attempt_at, created_at, updated_at)
                    VALUES
                        (:id, :org_id, :subscription_id, :event, CAST(:payload AS jsonb),
                         :idempotency_key, :status, :attempts, :next_attempt_at,
                         :created_at, :updated_at)
                    """
                ),
                {
                    "id": str(entry.id),
                    "org_id": str(entry.org_id),
                    "subscription_id": str(entry.subscription_id),
                    "event": entry.event.value,
                    "payload": json.dumps(entry.payload, sort_keys=True),
                    "idempotency_key": entry.idempotency_key,
                    "status": entry.status,
                    "attempts": entry.attempts,
                    "next_attempt_at": entry.next_attempt_at,
                    "created_at": entry.created_at,
                    "updated_at": entry.updated_at,
                },
            )
        return entry

    def claim_due(self, *, limit: int, now: datetime | None = None) -> list[Outbox_Entry]:
        """Select and lease in ONE statement.

        ``FOR UPDATE SKIP LOCKED`` inside the sub-select is what makes several application
        instances safe to run against one table: each takes different rows instead of blocking
        on each other, and a row is never handed to two workers. Doing this as a SELECT followed
        by an UPDATE would be a race whose symptom is a duplicate webhook.
        """
        moment = now or _utcnow()
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"""
                    UPDATE webhook_outbox SET
                        leased_until = :leased_until,
                        updated_at = :now
                    WHERE id IN (
                        SELECT id FROM webhook_outbox
                        WHERE status = 'pending'
                          AND next_attempt_at <= :now
                          AND (leased_until IS NULL OR leased_until <= :now)
                        ORDER BY next_attempt_at
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "now": moment,
                    "leased_until": moment + timedelta(seconds=LEASE_SECONDS),
                    "limit": limit,
                },
            ).fetchall()
        claimed = [self._row(row) for row in rows]
        # The ORDER BY inside the sub-select decides WHICH rows are claimed; it does not decide
        # the order `RETURNING` hands them back, which SQL leaves unspecified and PostgreSQL
        # varies with the plan. Sorting here makes the seam's contract — oldest due first — true
        # of the returned list too, so the worker attempts the longest-waiting event first
        # instead of in whatever order the executor happened to produce. Cheap: the batch is at
        # most `WEBHOOK_BATCH_SIZE`.
        claimed.sort(key=lambda entry: (entry.next_attempt_at, str(entry.id)))
        return claimed

    def mark_delivered(self, entry_id: UUID, *, attempts: int) -> None:
        self._settle(entry_id, status="delivered", attempts=attempts, error=None)

    def abandon(self, entry_id: UUID, *, attempts: int, error: str | None) -> None:
        self._settle(entry_id, status="abandoned", attempts=attempts, error=error)

    def _settle(
        self, entry_id: UUID, *, status: str, attempts: int, error: str | None
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE webhook_outbox SET status = :status, attempts = :attempts, "
                    "leased_until = NULL, last_error = :error, updated_at = :now "
                    "WHERE id = :id"
                ),
                {
                    "id": str(entry_id),
                    "status": status,
                    "attempts": attempts,
                    "error": error,
                    "now": _utcnow(),
                },
            )

    def reschedule(
        self, entry_id: UUID, *, attempts: int, next_attempt_at: datetime, error: str | None
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE webhook_outbox SET status = 'pending', attempts = :attempts, "
                    "next_attempt_at = :next_attempt_at, leased_until = NULL, "
                    "last_error = :error, updated_at = :now WHERE id = :id"
                ),
                {
                    "id": str(entry_id),
                    "attempts": attempts,
                    "next_attempt_at": next_attempt_at,
                    "error": error,
                    "now": _utcnow(),
                },
            )

    def get(self, org_id: UUID, entry_id: UUID) -> Outbox_Entry | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM webhook_outbox "
                    "WHERE org_id = :org_id AND id = :id"
                ),
                {"org_id": str(org_id), "id": str(entry_id)},
            ).first()
        return self._row(row) if row is not None else None

    def list_for_org(
        self, org_id: UUID, *, status: OutboxStatus | None = None, limit: int = 50
    ) -> list[Outbox_Entry]:
        clauses = ["org_id = :org_id"]
        params: dict[str, object] = {"org_id": str(org_id), "limit": limit}
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM webhook_outbox WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_outstanding(
        self, org_id: UUID, *, status: OutboxStatus | None = None, limit: int = 25
    ) -> list[Outbox_Entry]:
        clauses = ["org_id = :org_id", "status <> 'delivered'"]
        params: dict[str, object] = {"org_id": str(org_id), "limit": limit}
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM webhook_outbox WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def status_counts(self, org_id: UUID) -> dict[str, int]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, COUNT(*) FROM webhook_outbox "
                    "WHERE org_id = :org_id GROUP BY status"
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def pending_count(self, org_id: UUID) -> int:
        return self.status_counts(org_id).get("pending", 0)

    def requeue(
        self, org_id: UUID, entry_id: UUID, *, now: datetime | None = None
    ) -> Outbox_Entry | None:
        moment = now or _utcnow()
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    f"UPDATE webhook_outbox SET status = 'pending', attempts = 0, "
                    "next_attempt_at = :now, leased_until = NULL, updated_at = :now "
                    "WHERE org_id = :org_id AND id = :id AND status = 'abandoned' "
                    f"RETURNING {_COLUMNS}"
                ),
                {"org_id": str(org_id), "id": str(entry_id), "now": moment},
            ).first()
        return self._row(row) if row is not None else None

    def prune_settled(self, *, older_than: datetime) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM webhook_outbox WHERE status = 'delivered' "
                    "AND updated_at < :older_than"
                ),
                {"older_than": older_than},
            )
        return int(result.rowcount)

    @staticmethod
    def _row(row) -> Outbox_Entry:
        payload = row[4]
        return Outbox_Entry(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            subscription_id=UUID(str(row[2])),
            event=Webhook_Event(row[3]),
            # psycopg returns JSONB already decoded; tolerate a driver that hands back text.
            payload=payload if isinstance(payload, dict) else json.loads(payload),
            idempotency_key=row[5],
            status=row[6],
            attempts=int(row[7]),
            next_attempt_at=row[8],
            leased_until=row[9],
            last_error=row[10],
            created_at=row[11],
            updated_at=row[12],
        )
