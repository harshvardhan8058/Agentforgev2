"""Webhook persistence: subscriptions and the delivery log, in-memory and Postgres.

Both stores take ``org_id`` on **every** call, so a cross-tenant read or write is
structurally impossible rather than filtered afterwards — the same rule every other store in
this codebase follows (Req 4.3, 4.4). The delivery log is scoped by org *and* subscription for
the same reason: a subscription id from another tenant matches zero rows.

The in-memory implementations are not throwaway test doubles; they are the keyless path the
platform runs on without a database, and they are held to the same behaviour as the Postgres
ones. That includes deleting a subscription's delivery log along with the subscription, which
Postgres does with ``ON DELETE CASCADE``: a fake that quietly kept the rows would let a test
pass over a difference the real deployment would not have.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.webhooks.base import (
    DeliveryStatus,
    Webhook_Delivery,
    Webhook_Event,
    Webhook_Subscription,
)


class _Unset:
    """Sentinel distinguishing "field absent from the request" from "field set to null".

    A ``PATCH`` needs both meanings: omitting ``description`` must leave it alone, and sending
    ``null`` must clear it. Collapsing them (the usual ``None means untouched``) makes a
    documented field silently unclearable, which is the kind of API lie that only surfaces
    when a customer asks why their edit did nothing.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return "UNSET"


UNSET: Final[_Unset] = _Unset()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Webhook_Subscription_Store:
    """Persistence seam for webhook subscriptions, org-scoped on every call."""

    def list_for_org(
        self, org_id: UUID
    ) -> list[Webhook_Subscription]:  # pragma: no cover - interface
        raise NotImplementedError

    def list_for_event(
        self, org_id: UUID, event: Webhook_Event
    ) -> list[Webhook_Subscription]:  # pragma: no cover - interface
        raise NotImplementedError

    def get(
        self, org_id: UUID, subscription_id: UUID
    ) -> Webhook_Subscription | None:  # pragma: no cover - interface
        raise NotImplementedError

    def count_for_org(self, org_id: UUID) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def create(
        self,
        org_id: UUID,
        *,
        url: str,
        secret: str,
        events: tuple[Webhook_Event, ...],
        description: str | None = None,
        active: bool = True,
    ) -> Webhook_Subscription:  # pragma: no cover - interface
        raise NotImplementedError

    def update(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        url: str | _Unset = UNSET,
        events: tuple[Webhook_Event, ...] | _Unset = UNSET,
        description: str | None | _Unset = UNSET,
        active: bool | _Unset = UNSET,
    ) -> Webhook_Subscription | None:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(
        self, org_id: UUID, subscription_id: UUID
    ) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class Webhook_Delivery_Store:
    """Persistence seam for the delivery log, scoped by org and subscription."""

    def record(
        self, delivery: Webhook_Delivery
    ) -> Webhook_Delivery:  # pragma: no cover - interface
        raise NotImplementedError

    def list_for_subscription(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        before: tuple[datetime, UUID] | None = None,
        limit: int = 25,
    ) -> list[Webhook_Delivery]:  # pragma: no cover - interface
        raise NotImplementedError

    def drop_for_subscription(
        self, org_id: UUID, subscription_id: UUID
    ) -> int:  # pragma: no cover - interface
        raise NotImplementedError


class InMemory_Webhook_Delivery_Store(Webhook_Delivery_Store):
    """Keyless/test delivery log. Newest-first reads, keyset cursor, org-scoped."""

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
        limit: int = 25,
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
        # Newest first, id as a stable tie-break: one fan-out writes several rows in the same
        # millisecond, and an arbitrary order there would make a page boundary unreliable.
        selected.sort(key=lambda d: (d.created_at, str(d.id)), reverse=True)
        return selected[:limit]

    def drop_for_subscription(self, org_id: UUID, subscription_id: UUID) -> int:
        """Delete a subscription's log, mirroring the Postgres ``ON DELETE CASCADE``."""
        keep = [
            d
            for d in self._deliveries
            if not (d.org_id == org_id and d.subscription_id == subscription_id)
        ]
        removed = len(self._deliveries) - len(keep)
        self._deliveries = keep
        return removed


class InMemory_Webhook_Subscription_Store(Webhook_Subscription_Store):
    """Keyless/test subscription store keyed by ``(org_id, id)``.

    ``deliveries`` is optional and, when supplied, is cascaded into on delete so this store
    behaves like the Postgres pair rather than like a fake that forgot the foreign key.
    """

    def __init__(self, deliveries: Webhook_Delivery_Store | None = None) -> None:
        self._subscriptions: dict[UUID, Webhook_Subscription] = {}
        self._deliveries = deliveries

    def list_for_org(self, org_id: UUID) -> list[Webhook_Subscription]:
        found = [s for s in self._subscriptions.values() if s.org_id == org_id]
        # Oldest first, id as a tie-break, so the console's list order is stable.
        found.sort(key=lambda s: (s.created_at, str(s.id)))
        return found

    def list_for_event(
        self, org_id: UUID, event: Webhook_Event
    ) -> list[Webhook_Subscription]:
        return [s for s in self.list_for_org(org_id) if s.wants(event)]

    def get(self, org_id: UUID, subscription_id: UUID) -> Webhook_Subscription | None:
        found = self._subscriptions.get(subscription_id)
        return found if found is not None and found.org_id == org_id else None

    def count_for_org(self, org_id: UUID) -> int:
        return len(self.list_for_org(org_id))

    def create(
        self,
        org_id: UUID,
        *,
        url: str,
        secret: str,
        events: tuple[Webhook_Event, ...],
        description: str | None = None,
        active: bool = True,
    ) -> Webhook_Subscription:
        now = _utcnow()
        subscription = Webhook_Subscription(
            id=uuid.uuid4(),
            org_id=org_id,
            url=url,
            secret=secret,
            events=tuple(events),
            description=description,
            active=active,
            created_at=now,
            updated_at=now,
        )
        self._subscriptions[subscription.id] = subscription
        return subscription

    def update(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        url: str | _Unset = UNSET,
        events: tuple[Webhook_Event, ...] | _Unset = UNSET,
        description: str | None | _Unset = UNSET,
        active: bool | _Unset = UNSET,
    ) -> Webhook_Subscription | None:
        existing = self.get(org_id, subscription_id)
        if existing is None:
            return None
        updated = Webhook_Subscription(
            id=existing.id,
            org_id=existing.org_id,
            url=existing.url if isinstance(url, _Unset) else url,
            secret=existing.secret,
            events=existing.events if isinstance(events, _Unset) else tuple(events),
            description=(
                existing.description
                if isinstance(description, _Unset)
                else description
            ),
            active=existing.active if isinstance(active, _Unset) else active,
            created_at=existing.created_at,
            updated_at=_utcnow(),
        )
        self._subscriptions[subscription_id] = updated
        return updated

    def delete(self, org_id: UUID, subscription_id: UUID) -> bool:
        if self.get(org_id, subscription_id) is None:
            return False
        del self._subscriptions[subscription_id]
        if self._deliveries is not None:
            # Mirrors ON DELETE CASCADE. Without this the keyless path would keep a log
            # pointing at a subscription that no longer exists — a difference from production
            # that a test could not see.
            self._deliveries.drop_for_subscription(org_id, subscription_id)
        return True


_SUBSCRIPTION_COLUMNS = (
    "id, org_id, url, secret, events, description, active, created_at, updated_at"
)


class Pg_Webhook_Subscription_Store(Webhook_Subscription_Store):
    """Postgres-backed subscription store over ``webhook_subscriptions`` (migration 0015).

    Synchronous SQLAlchemy, mirroring the other ``Pg_*`` stores; every statement is scoped by
    ``org_id`` in SQL, so a cross-tenant read or write matches zero rows.
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def list_for_org(self, org_id: UUID) -> list[Webhook_Subscription]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {_SUBSCRIPTION_COLUMNS} FROM webhook_subscriptions "
                    "WHERE org_id = :org_id ORDER BY created_at, id"
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def list_for_event(
        self, org_id: UUID, event: Webhook_Event
    ) -> list[Webhook_Subscription]:
        """Return the org's ACTIVE subscriptions that name ``event``.

        Filtered in SQL rather than in Python because this runs for every emitted event: an
        org with one subscription for one event should not read all of them to find out.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {_SUBSCRIPTION_COLUMNS} FROM webhook_subscriptions "
                    "WHERE org_id = :org_id AND active = TRUE "
                    "AND :event = ANY(events) ORDER BY created_at, id"
                ),
                {"org_id": str(org_id), "event": event.value},
            ).fetchall()
        return [self._row_to_subscription(row) for row in rows]

    def get(self, org_id: UUID, subscription_id: UUID) -> Webhook_Subscription | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT {_SUBSCRIPTION_COLUMNS} FROM webhook_subscriptions "
                    "WHERE org_id = :org_id AND id = :id"
                ),
                {"org_id": str(org_id), "id": str(subscription_id)},
            ).first()
        return self._row_to_subscription(row) if row is not None else None

    def count_for_org(self, org_id: UUID) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM webhook_subscriptions WHERE org_id = :org_id"
                ),
                {"org_id": str(org_id)},
            ).first()
        return int(row[0]) if row is not None else 0

    def create(
        self,
        org_id: UUID,
        *,
        url: str,
        secret: str,
        events: tuple[Webhook_Event, ...],
        description: str | None = None,
        active: bool = True,
    ) -> Webhook_Subscription:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO webhook_subscriptions
                        (id, org_id, url, secret, events, description, active)
                    VALUES
                        (:id, :org_id, :url, :secret, CAST(:events AS text[]),
                         :description, :active)
                    RETURNING id, org_id, url, secret, events, description, active,
                              created_at, updated_at
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org_id": str(org_id),
                    "url": url,
                    "secret": secret,
                    "events": [e.value for e in events],
                    "description": description,
                    "active": active,
                },
            ).first()
        return self._row_to_subscription(row)

    def update(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        url: str | _Unset = UNSET,
        events: tuple[Webhook_Event, ...] | _Unset = UNSET,
        description: str | None | _Unset = UNSET,
        active: bool | _Unset = UNSET,
    ) -> Webhook_Subscription | None:
        """Apply only the supplied fields; return ``None`` for unknown/cross-tenant.

        The ``SET`` list is built from the fields actually present, with every value bound.
        A ``COALESCE``-style statement would be shorter and would make ``description = null``
        unexpressible, which is exactly the semantics :data:`UNSET` exists to preserve.
        """
        assignments = ["updated_at = :updated_at"]
        params: dict[str, object] = {
            "org_id": str(org_id),
            "id": str(subscription_id),
            "updated_at": _utcnow(),
        }
        if not isinstance(url, _Unset):
            assignments.append("url = :url")
            params["url"] = url
        if not isinstance(events, _Unset):
            assignments.append("events = CAST(:events AS text[])")
            params["events"] = [e.value for e in events]
        if not isinstance(description, _Unset):
            assignments.append("description = :description")
            params["description"] = description
        if not isinstance(active, _Unset):
            assignments.append("active = :active")
            params["active"] = active

        sql = (
            f"UPDATE webhook_subscriptions SET {', '.join(assignments)} "
            "WHERE org_id = :org_id AND id = :id "
            f"RETURNING {_SUBSCRIPTION_COLUMNS}"
        )
        with self._engine.begin() as conn:
            row = conn.execute(text(sql), params).first()
        return self._row_to_subscription(row) if row is not None else None

    def delete(self, org_id: UUID, subscription_id: UUID) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM webhook_subscriptions "
                    "WHERE org_id = :org_id AND id = :id"
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
            secret=row[3],
            # Unknown event names are dropped rather than raising: a row written by a newer
            # version of the application must not make an older one unable to read its own
            # table. The subscription simply does not match the event it cannot name.
            events=tuple(
                Webhook_Event(name)
                for name in (row[4] or [])
                if name in _EVENT_VALUES
            ),
            description=row[5],
            active=bool(row[6]),
            created_at=row[7],
            updated_at=row[8],
        )


_EVENT_VALUES: Final[frozenset[str]] = frozenset(e.value for e in Webhook_Event)

_DELIVERY_COLUMNS = (
    "id, org_id, subscription_id, event, status, attempts, response_status, error, "
    "duration_ms, created_at"
)


class Pg_Webhook_Delivery_Store(Webhook_Delivery_Store):
    """Postgres-backed delivery log over ``webhook_deliveries`` (migration 0015)."""

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def record(self, delivery: Webhook_Delivery) -> Webhook_Delivery:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries
                        (id, org_id, subscription_id, event, status, attempts,
                         response_status, error, duration_ms, created_at)
                    VALUES
                        (:id, :org_id, :subscription_id, :event, :status, :attempts,
                         :response_status, :error, :duration_ms, :created_at)
                    """
                ),
                {
                    "id": str(delivery.id),
                    "org_id": str(delivery.org_id),
                    "subscription_id": str(delivery.subscription_id),
                    "event": delivery.event.value,
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
        limit: int = 25,
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
        sql = (
            f"SELECT {_DELIVERY_COLUMNS} FROM webhook_deliveries "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return [self._row_to_delivery(row) for row in rows]

    def drop_for_subscription(self, org_id: UUID, subscription_id: UUID) -> int:
        """Delete a subscription's log rows.

        Not used by :meth:`Pg_Webhook_Subscription_Store.delete` — the foreign key already
        cascades — but present so both implementations offer the same surface, and so a
        retention job has a scoped statement to call.
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM webhook_deliveries "
                    "WHERE org_id = :org_id AND subscription_id = :subscription_id"
                ),
                {"org_id": str(org_id), "subscription_id": str(subscription_id)},
            )
        return int(result.rowcount)

    @staticmethod
    def _row_to_delivery(row) -> Webhook_Delivery:
        status: DeliveryStatus = "delivered" if row[4] == "delivered" else "failed"
        return Webhook_Delivery(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            subscription_id=UUID(str(row[2])),
            event=Webhook_Event(row[3]),
            status=status,
            attempts=int(row[5]),
            response_status=int(row[6]) if row[6] is not None else None,
            error=row[7],
            duration_ms=int(row[8]),
            created_at=row[9],
        )
