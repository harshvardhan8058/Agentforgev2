"""Webhook stores: in-memory (keyless) and Postgres (migration 0015).

Both take ``org_id`` on every call and put it in the query, so another tenant's subscription or
delivery log is structurally unreachable rather than filtered afterwards (Req 4.3, 4.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.webhooks.base import (
    Webhook_Delivery,
    Webhook_Delivery_Store,
    Webhook_Subscription,
    Webhook_Subscription_Store,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemory_Webhook_Subscription_Store(Webhook_Subscription_Store):
    """Keyless/test subscription store keyed by ``(org_id, subscription_id)``.

    ``deliveries`` may be attached so that deleting a subscription also sweeps its delivery log,
    mirroring the ``ON DELETE CASCADE`` in migration 0015. Without it the keyless store would
    keep rows the Postgres store removes, and a test asserting the documented behaviour would
    pass against the fake and fail against the real thing.
    """

    def __init__(self, deliveries: "InMemory_Webhook_Delivery_Store | None" = None) -> None:
        self._by_key: dict[tuple[UUID, UUID], Webhook_Subscription] = {}
        self._deliveries = deliveries

    def create(
        self,
        org_id: UUID,
        *,
        url: str,
        events: tuple[str, ...],
        secret: str,
        description: str | None = None,
    ) -> Webhook_Subscription:
        now = _utcnow()
        subscription = Webhook_Subscription(
            id=uuid.uuid4(),
            org_id=org_id,
            url=url,
            events=tuple(events),
            secret=secret,
            description=description,
            active=True,
            created_at=now,
            updated_at=now,
        )
        self._by_key[(org_id, subscription.id)] = subscription
        return subscription

    def get(self, org_id: UUID, subscription_id: UUID) -> Webhook_Subscription | None:
        return self._by_key.get((org_id, subscription_id))

    def list_for_org(self, org_id: UUID) -> list[Webhook_Subscription]:
        found = [s for (owner, _sid), s in self._by_key.items() if owner == org_id]
        return sorted(found, key=lambda s: (s.created_at, str(s.id)), reverse=True)

    def list_for_event(self, org_id: UUID, event: str) -> list[Webhook_Subscription]:
        return [s for s in self.list_for_org(org_id) if s.wants(event)]

    def update(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        url: str | None = None,
        events: tuple[str, ...] | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> Webhook_Subscription | None:
        existing = self._by_key.get((org_id, subscription_id))
        if existing is None:
            return None
        updated = Webhook_Subscription(
            id=existing.id,
            org_id=existing.org_id,
            url=existing.url if url is None else url,
            events=existing.events if events is None else tuple(events),
            # The secret is never rotated by an update: doing so silently would break the
            # consumer, so rotation would need its own explicit endpoint.
            secret=existing.secret,
            description=existing.description if description is None else description,
            active=existing.active if active is None else active,
            created_at=existing.created_at,
            updated_at=_utcnow(),
        )
        self._by_key[(org_id, subscription_id)] = updated
        return updated

    def delete(self, org_id: UUID, subscription_id: UUID) -> bool:
        removed = self._by_key.pop((org_id, subscription_id), None) is not None
        if removed and self._deliveries is not None:
            self._deliveries.forget_subscription(org_id, subscription_id)
        return removed


class InMemory_Webhook_Delivery_Store(Webhook_Delivery_Store):
    """Keyless/test delivery log."""

    def __init__(self) -> None:
        self._deliveries: list[Webhook_Delivery] = []

    def record(self, delivery: Webhook_Delivery) -> Webhook_Delivery:
        self._deliveries.append(delivery)
        return delivery

    def list_for_subscription(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        before: tuple[datetime, UUID] | None = None,
        limit: int = 50,
    ) -> list[Webhook_Delivery]:
        selected = [
            d
            for d in self._deliveries
            if d.org_id == org_id
            and d.subscription_id == subscription_id
            and (
                before is None
                or (d.created_at, str(d.id)) < (before[0], str(before[1]))
            )
        ]
        selected.sort(key=lambda d: (d.created_at, str(d.id)), reverse=True)
        return selected[:limit]

    def forget_subscription(self, org_id: UUID, subscription_id: UUID) -> None:
        """Drop a deleted subscription's deliveries, standing in for the SQL cascade.

        Not part of :class:`Webhook_Delivery_Store`: the log is append-only through the seam, and
        the Postgres implementation does not need a method for this because the foreign key does
        it. This exists only so the in-memory pair behaves the same way.
        """
        self._deliveries = [
            d
            for d in self._deliveries
            if not (d.org_id == org_id and d.subscription_id == subscription_id)
        ]


class Pg_Webhook_Subscription_Store(Webhook_Subscription_Store):
    """Postgres subscription store over ``webhook_subscriptions`` (migration 0015)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    _COLUMNS = (
        "id, org_id, url, events, secret, description, active, created_at, updated_at"
    )

    def create(
        self,
        org_id: UUID,
        *,
        url: str,
        events: tuple[str, ...],
        secret: str,
        description: str | None = None,
    ) -> Webhook_Subscription:
        now = _utcnow()
        subscription_id = uuid.uuid4()
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    f"""
                    INSERT INTO webhook_subscriptions
                        (id, org_id, url, events, secret, description, active,
                         created_at, updated_at)
                    VALUES
                        (:id, :org_id, :url, CAST(:events AS text[]), :secret, :description,
                         TRUE, :created_at, :updated_at)
                    RETURNING {self._COLUMNS}
                    """
                ),
                {
                    "id": str(subscription_id),
                    "org_id": str(org_id),
                    "url": url,
                    "events": list(events),
                    "secret": secret,
                    "description": description,
                    "created_at": now,
                    "updated_at": now,
                },
            ).first()
        return self._row_to_subscription(row)

    def get(self, org_id: UUID, subscription_id: UUID) -> Webhook_Subscription | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT {self._COLUMNS} FROM webhook_subscriptions "
                    "WHERE org_id = :org_id AND id = :id"
                ),
                {"org_id": str(org_id), "id": str(subscription_id)},
            ).first()
        return self._row_to_subscription(row) if row is not None else None

    def list_for_org(self, org_id: UUID) -> list[Webhook_Subscription]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {self._COLUMNS} FROM webhook_subscriptions "
                    "WHERE org_id = :org_id ORDER BY created_at DESC, id DESC"
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def list_for_event(self, org_id: UUID, event: str) -> list[Webhook_Subscription]:
        """Active subscriptions that asked for ``event``, filtered in SQL.

        ``:event = ANY(events)`` keeps the emission path from fetching rows it would discard —
        this runs for every emitted event, unlike the listing endpoint.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {self._COLUMNS} FROM webhook_subscriptions "
                    "WHERE org_id = :org_id AND active AND :event = ANY(events) "
                    "ORDER BY created_at DESC, id DESC"
                ),
                {"org_id": str(org_id), "event": event},
            ).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def update(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        url: str | None = None,
        events: tuple[str, ...] | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> Webhook_Subscription | None:
        """Apply only the supplied fields, in one statement.

        ``COALESCE`` on a bound parameter rather than a dynamically assembled SET list: the
        statement text is then constant, so it plans once and cannot be shaped by input.
        (``description`` is deliberately not clearable through this path — there is no
        "unset" case, and COALESCE could not express one anyway.)
        """
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    f"""
                    UPDATE webhook_subscriptions SET
                        url = COALESCE(:url, url),
                        events = COALESCE(CAST(:events AS text[]), events),
                        description = COALESCE(:description, description),
                        active = COALESCE(:active, active),
                        updated_at = :updated_at
                    WHERE org_id = :org_id AND id = :id
                    RETURNING {self._COLUMNS}
                    """
                ),
                {
                    "url": url,
                    "events": list(events) if events is not None else None,
                    "description": description,
                    "active": active,
                    "updated_at": _utcnow(),
                    "org_id": str(org_id),
                    "id": str(subscription_id),
                },
            ).first()
        return self._row_to_subscription(row) if row is not None else None

    def delete(self, org_id: UUID, subscription_id: UUID) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM webhook_subscriptions WHERE org_id = :org_id AND id = :id"
                ),
                {"org_id": str(org_id), "id": str(subscription_id)},
            )
        return result.rowcount > 0

    @staticmethod
    def _row_to_subscription(row) -> Webhook_Subscription:
        return Webhook_Subscription(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            url=row[2],
            events=tuple(row[3] or ()),
            secret=row[4],
            description=row[5],
            active=bool(row[6]),
            created_at=row[7],
            updated_at=row[8],
        )


class Pg_Webhook_Delivery_Store(Webhook_Delivery_Store):
    """Postgres delivery log over ``webhook_deliveries`` (migration 0015)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    _COLUMNS = (
        "id, org_id, subscription_id, event_type, status, attempts, response_status, "
        "error, duration_ms, created_at"
    )

    def record(self, delivery: Webhook_Delivery) -> Webhook_Delivery:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries
                        (id, org_id, subscription_id, event_type, status, attempts,
                         response_status, error, duration_ms, created_at)
                    VALUES
                        (:id, :org_id, :subscription_id, :event_type, :status, :attempts,
                         :response_status, :error, :duration_ms, :created_at)
                    """
                ),
                {
                    "id": str(delivery.id),
                    "org_id": str(delivery.org_id),
                    "subscription_id": str(delivery.subscription_id),
                    "event_type": delivery.event_type,
                    "status": delivery.status,
                    "attempts": delivery.attempts,
                    "response_status": delivery.response_status,
                    "error": delivery.error,
                    "duration_ms": delivery.duration_ms,
                    "created_at": delivery.created_at,
                },
            )
        return delivery

    def list_for_subscription(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        before: tuple[datetime, UUID] | None = None,
        limit: int = 50,
    ) -> list[Webhook_Delivery]:
        clauses = ["org_id = :org_id", "subscription_id = :subscription_id"]
        params: dict[str, object] = {
            "org_id": str(org_id),
            "subscription_id": str(subscription_id),
            "limit": limit,
        }
        if before is not None:
            clauses.append("(created_at, id) < (:before_at, CAST(:before_id AS uuid))")
            params["before_at"] = before[0]
            params["before_id"] = str(before[1])
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {self._COLUMNS} FROM webhook_deliveries "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                params,
            ).fetchall()
        return [self._row_to_delivery(row) for row in rows]

    @staticmethod
    def _row_to_delivery(row) -> Webhook_Delivery:
        return Webhook_Delivery(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            subscription_id=UUID(str(row[2])),
            event_type=row[3],
            status=row[4],
            attempts=row[5],
            response_status=row[6],
            error=row[7],
            duration_ms=row[8],
            created_at=row[9],
        )


def disabled_webhook_emitter():
    """Return an emitter with no subscriptions, for a partially-wired app.

    Lives here because naming concrete implementations is this layer's job, not the transport
    layer's (``api/deps.py`` must not name a concrete — a property test enforces it). The
    instance is shared and holds nothing: with no subscriptions, ``emit`` returns after one
    dictionary lookup.
    """
    return _DISABLED_EMITTER


def _build_disabled_emitter():
    from agentforge.webhooks.emitter import Webhook_Emitter
    from agentforge.webhooks.transport import Recording_Webhook_Transport

    deliveries = InMemory_Webhook_Delivery_Store()
    return Webhook_Emitter(
        InMemory_Webhook_Subscription_Store(deliveries),
        deliveries,
        # Never reached: there are no subscriptions to deliver to. Present so the seam is
        # satisfied without importing the real HTTP transport into this path.
        Recording_Webhook_Transport(),
    )


_DISABLED_EMITTER = _build_disabled_emitter()
