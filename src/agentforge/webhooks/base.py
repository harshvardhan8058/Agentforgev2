"""Webhook seams and domain records: the event vocabulary, subscriptions, deliveries.

The vocabulary is closed and published through OpenAPI, exactly like the audit trail's, so a
client's event picker is generated from the contract instead of hardcoded. Adding an event is
an application change here plus one emission point — never a migration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID


class Webhook_Event(str, Enum):
    """The events an organization may subscribe to.

    Every member of this vocabulary is **single-shot**: it describes something that happened
    once, at a point in time. That is a deliberate constraint on what belongs here — a
    condition that stays true (an org sitting over its budget for a week) would fire on every
    request that observed it, so a state-based notification needs threshold tracking rather
    than an event, and is not pretended at.
    """

    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    DOCUMENT_INGESTED = "document.ingested"
    GUARDRAIL_BLOCKED = "guardrail.blocked"
    # Sent only by POST /webhooks/{id}/test, so a consumer can verify signature handling and
    # connectivity before waiting for real traffic. Cannot be subscribed to: it is addressed
    # at one subscription on demand, which is why it is absent from SUBSCRIBABLE_EVENTS.
    PING = "webhook.ping"


class Subscribable_Event(str, Enum):
    """The subset of :class:`Webhook_Event` a subscription may ask for.

    A separate enum rather than a runtime check against the full vocabulary, because this is
    what the *contract* admits: the request and response models are typed with it, so
    ``webhook.ping`` is rejected by schema validation and never appears in a generated client's
    event picker as if it were subscribable. :data:`SUBSCRIBABLE_EVENTS` is derived from this
    list rather than restated, so the two cannot drift.
    """

    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    DOCUMENT_INGESTED = "document.ingested"
    GUARDRAIL_BLOCKED = "guardrail.blocked"


#: The events a subscription may ask for. `webhook.ping` is deliberately excluded.
SUBSCRIBABLE_EVENTS: tuple[Webhook_Event, ...] = tuple(
    Webhook_Event(event.value) for event in Subscribable_Event
)

DeliveryStatus = Literal["delivered", "failed"]


@dataclass(frozen=True)
class Webhook_Subscription:
    """One org-scoped endpoint and the events it wants.

    ``secret`` is the HMAC signing key. It is part of the domain record because signing needs
    it, and it is the transport layer's job never to put it in a response — the API's
    subscription model has no such field, so it cannot leak by omission.
    """

    id: UUID
    org_id: UUID
    url: str
    events: tuple[str, ...]
    secret: str
    description: str | None
    active: bool
    created_at: datetime
    updated_at: datetime

    def wants(self, event: Webhook_Event | str) -> bool:
        """True when this subscription is active and asked for ``event``."""
        value = event.value if isinstance(event, Webhook_Event) else event
        return self.active and value in self.events


@dataclass(frozen=True)
class Webhook_Delivery:
    """The recorded outcome of delivering one event to one subscription."""

    id: UUID
    org_id: UUID
    subscription_id: UUID
    event_type: str
    status: DeliveryStatus
    attempts: int
    response_status: int | None = None
    error: str | None = None
    duration_ms: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Transport_Result:
    """What a single HTTP attempt produced.

    ``status`` is the endpoint's HTTP status, or ``None`` when no response was obtained at all
    (DNS failure, TLS failure, timeout, refused connection). ``error`` is a short diagnostic;
    it is never a response body, because a tenant's endpoint may echo material this platform
    has no business storing.
    """

    status: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True for any 2xx. Everything else is retried and then recorded as failed."""
        return self.status is not None and 200 <= self.status < 300


class Webhook_Subscription_Store(ABC):
    """Org-scoped persistence for subscriptions. Every method takes ``org_id``."""

    @abstractmethod
    def create(
        self,
        org_id: UUID,
        *,
        url: str,
        events: tuple[str, ...],
        secret: str,
        description: str | None = None,
    ) -> Webhook_Subscription:
        raise NotImplementedError

    @abstractmethod
    def get(self, org_id: UUID, subscription_id: UUID) -> Webhook_Subscription | None:
        """Return the subscription iff it belongs to ``org_id``, else ``None`` (→ uniform 404)."""
        raise NotImplementedError

    @abstractmethod
    def list_for_org(self, org_id: UUID) -> list[Webhook_Subscription]:
        """Return the org's subscriptions, newest first."""
        raise NotImplementedError

    @abstractmethod
    def list_for_event(self, org_id: UUID, event: str) -> list[Webhook_Subscription]:
        """Return the org's **active** subscriptions that asked for ``event``.

        Separate from :meth:`list_for_org` because this is the emission path: it runs for every
        emitted event and must not pay for rows it would immediately discard.
        """
        raise NotImplementedError

    @abstractmethod
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
        """Apply the supplied fields; ``None`` means "leave alone". ``None`` return = no such row.

        Partial update rather than replace, unlike the integration connection config: a
        subscription's fields are independent (pausing one should not require restating its URL
        and event list), and there is no "remove a field" case to express.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, org_id: UUID, subscription_id: UUID) -> bool:
        raise NotImplementedError


class Webhook_Delivery_Store(ABC):
    """Org-scoped, append-only delivery log."""

    @abstractmethod
    def record(self, delivery: Webhook_Delivery) -> Webhook_Delivery:
        raise NotImplementedError

    @abstractmethod
    def list_for_subscription(
        self,
        org_id: UUID,
        subscription_id: UUID,
        *,
        before: tuple[datetime, UUID] | None = None,
        limit: int = 50,
    ) -> list[Webhook_Delivery]:
        """Return the subscription's deliveries, newest first.

        ``before`` is the ``(created_at, id)`` keyset cursor, matching the audit trail: a
        timestamp alone cannot separate deliveries fanned out to one endpoint in one burst.
        """
        raise NotImplementedError


class Webhook_Transport(ABC):
    """The single outbound-HTTP seam, so no other module performs a network call.

    Exists to make the emitter testable without a network *and* to keep every outbound limit
    (timeout, redirect policy, response size) in one auditable place.
    """

    @abstractmethod
    def post(
        self, url: str, *, body: bytes, headers: dict[str, str], timeout_seconds: float
    ) -> Transport_Result:
        """POST ``body`` to ``url``. MUST NOT raise: transport failure is a result, not an error."""
        raise NotImplementedError
