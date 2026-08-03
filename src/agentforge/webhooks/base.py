"""Webhook domain types: the event vocabulary, the subscription, and the delivery record.

The platform was excellent at *recording* things and incapable of *saying* them. A run
finished, a guardrail blocked an input, an organization crossed its spend threshold — each
was visible to whoever went looking, and to nobody else. Every comparable product (Stripe,
GitHub, Slack, LangSmith) solves this the same way, because the shape is right: an
org-scoped subscription, a signed POST, and a log of what happened.

Two decisions are worth stating here, because the rest of the package follows from them:

**The event vocabulary is closed, and every event is single-shot.** :class:`Webhook_Event`
is a fixed enum, published through the API so the console's checklist is generated from the
contract rather than hardcoded. Every member fires exactly once per occurrence, which is why
no deduplication or threshold state exists anywhere in this package: an event that could
fire on every request (say "budget exceeded", evaluated per run) would need debounce state,
and that state belongs to whatever owns the threshold — not here.

**Ping is not subscribable.** ``webhook.ping`` exists so an operator can prove an endpoint
works before trusting it with real traffic. It is deliberately absent from
:data:`SUBSCRIBABLE_EVENTS`: a subscription to it would be a subscription to nothing, since
nothing in the platform ever emits it spontaneously.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID


class Webhook_Event(str, Enum):
    """The closed vocabulary of events a webhook can carry.

    Dotted ``subject.verb`` in the past tense, matching :class:`~agentforge.enterprise.audit.Audit_Action`.
    A ``str`` enum so it serialises as its value in the API contract (and therefore reaches
    the generated TypeScript client as a union type) while remaining one authoritative list.
    """

    #: A single- or multi-agent run reached a successful terminal state.
    RUN_COMPLETED = "run.completed"
    #: A run reached a terminal state **without** producing an accepted result — an
    #: iteration/round bound, a rejected-past-the-revision-bound critique, or an abort. Not
    #: "the request raised": a failed request already tells its caller, and emission is
    #: deliberately off the request path (see :mod:`agentforge.webhooks.emitter`).
    RUN_FAILED = "run.failed"
    #: A document finished ingestion (including a duplicate, which is reported as such).
    DOCUMENT_INGESTED = "document.ingested"
    #: An input guardrail blocked a request before any model was invoked.
    GUARDRAIL_BLOCKED = "guardrail.blocked"
    #: An organization crossed a spend-budget threshold for the current period.
    BUDGET_THRESHOLD_CROSSED = "budget.threshold_crossed"
    #: Sent only by ``POST /webhooks/{id}/test``. Never emitted by the platform itself, and
    #: therefore not subscribable — see the module docstring.
    PING = "webhook.ping"


#: The events a subscription may name. Derived from the enum rather than restated, so a new
#: event is subscribable by construction and cannot be forgotten here; ``PING`` is the single
#: deliberate exclusion.
SUBSCRIBABLE_EVENTS: tuple[Webhook_Event, ...] = tuple(
    event for event in Webhook_Event if event is not Webhook_Event.PING
)


class Subscribable_Event(str, Enum):
    """The subset of :class:`Webhook_Event` a client may subscribe to.

    A separate enum, rather than validation inside the router, so the *contract* refuses
    ``webhook.ping`` and the generated client cannot offer it. Kept honest by
    :func:`_assert_subscribable_events_match` below, which runs at import: the two lists
    drifting apart would be a silent API lie.
    """

    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    DOCUMENT_INGESTED = "document.ingested"
    GUARDRAIL_BLOCKED = "guardrail.blocked"
    BUDGET_THRESHOLD_CROSSED = "budget.threshold_crossed"


def _assert_subscribable_events_match() -> None:
    """Fail at import if :class:`Subscribable_Event` has drifted from the vocabulary."""
    expected = {event.value for event in SUBSCRIBABLE_EVENTS}
    declared = {event.value for event in Subscribable_Event}
    if expected != declared:  # pragma: no cover - a broken build, not a runtime path
        raise RuntimeError(
            "Subscribable_Event has drifted from Webhook_Event: "
            f"missing={sorted(expected - declared)} extra={sorted(declared - expected)}"
        )


_assert_subscribable_events_match()


DeliveryStatus = Literal["delivered", "failed"]


@dataclass(frozen=True)
class Webhook_Subscription:
    """One organization's webhook endpoint: where to send, what to send, and how to sign.

    ``secret`` is the raw HMAC key. It is present on this domain record because signing needs
    it, and it is absent from every API response model by construction — the router maps
    subscriptions onto a response type that has no such field, so there is no code path that
    could leak it by forgetting to strip it.
    """

    id: UUID
    org_id: UUID
    url: str
    secret: str
    events: tuple[Webhook_Event, ...]
    description: str | None
    active: bool
    created_at: datetime
    updated_at: datetime

    def wants(self, event: Webhook_Event) -> bool:
        """Return whether this subscription should receive ``event`` right now."""
        return self.active and event in self.events


@dataclass(frozen=True)
class Webhook_Delivery:
    """The record of one attempt sequence: did this event reach this endpoint, and why not.

    ``attempts`` is the number of HTTP attempts made, ``duration_ms`` the time spent in HTTP
    work **excluding** the backoff sleeps between them (so it answers "how slow is this
    endpoint"), and ``response_status`` is ``None`` when no response was ever obtained —
    which distinguishes "your endpoint said 500" from "we could not reach your endpoint".
    """

    id: UUID
    org_id: UUID
    subscription_id: UUID
    event: Webhook_Event
    status: DeliveryStatus
    attempts: int
    response_status: int | None
    error: str | None
    duration_ms: int
    created_at: datetime


@dataclass(frozen=True)
class Transport_Result:
    """The outcome of a single HTTP attempt, as reported by a :class:`Webhook_Transport`.

    ``error`` is a short sanitised summary safe to show the tenant's admins. It is never the
    response body: that body arrives from outside the trust boundary, and this field is read
    in a console and stored in a queryable table.
    """

    delivered: bool
    response_status: int | None
    error: str | None


class Webhook_Transport(ABC):
    """The seam between "we decided to deliver" and "an HTTP request happened".

    Exists so the emitter can be tested without a network and so a deployment could route
    deliveries through something other than direct HTTP (an egress proxy, a queue) without
    touching the emitter.

    Implementations **MUST NOT** raise: a transport failure is data (an undelivered event),
    not an exception, and the emitter's contract — that emitting can never affect the work
    that triggered it — rests on that.
    """

    @abstractmethod
    def post(
        self, url: str, body: bytes, headers: dict[str, str], *, timeout_seconds: float
    ) -> Transport_Result:
        """POST ``body`` to ``url``; report the outcome, never raise."""
        raise NotImplementedError
