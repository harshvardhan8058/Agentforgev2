"""Event payloads and the emission helpers the routers call.

Every emission point goes through a function here rather than building an envelope inline, for
one reason that matters more than tidiness: a payload assembled at four call sites drifts at
four different rates, and a consumer parsing ``run.completed`` cannot tell which surface
produced the one it is holding. So the shape of each event is defined once, and the routers
supply facts rather than JSON.

Payloads carry **identifiers and outcomes, never content.** A run's answer, a document's text,
and a blocked prompt are all absent: a webhook crosses the trust boundary to an endpoint the
platform does not control, and the endpoint's job is to be told that something happened and
then come back through the authenticated API for the details.

Every helper here is total and silent — it returns ``None`` and raises nothing — because its
callers are finished runs and error paths, not clients.
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from agentforge.webhooks.base import Webhook_Delivery, Webhook_Event
from agentforge.webhooks.emitter import Webhook_Emitter

logger = logging.getLogger(__name__)

#: Termination reasons that mean the run produced an accepted result: ``final-answer`` for a
#: single-agent run, ``completed`` for a multi-agent one. Everything else — an iteration or
#: round bound, a rejection past the revision bound, an abort — is a ``run.failed``, because
#: from the caller's side a run that ended without an answer *did* fail, whatever the
#: mechanism. Kept as one set so the two orchestrators cannot be classified inconsistently.
SUCCESSFUL_TERMINATIONS: Final[frozenset[str]] = frozenset({"final-answer", "completed"})

#: The two run kinds a payload can report, so a consumer can route without inspecting ids.
RunKind = str


def run_outcome_event(termination_reason: str | None) -> Webhook_Event:
    """Classify a terminal run: :attr:`Webhook_Event.RUN_COMPLETED` xor ``RUN_FAILED``."""
    if termination_reason in SUCCESSFUL_TERMINATIONS:
        return Webhook_Event.RUN_COMPLETED
    return Webhook_Event.RUN_FAILED


def run_payload(
    *,
    run_id: str,
    kind: RunKind,
    termination_reason: str | None,
    conversation_id: str | None = None,
    citation_count: int | None = None,
) -> dict[str, object]:
    """Build the payload shared by ``run.completed`` and ``run.failed``.

    Every key is always present, ``null`` where a fact does not apply, so a consumer's parser
    is the same regardless of which surface emitted the event. Omitting absent keys instead
    would make ``run.completed`` from the approval endpoint a different shape from
    ``run.completed`` from a stream — the exact drift this module exists to prevent.
    """
    return {
        "run_id": run_id,
        "kind": kind,
        "conversation_id": conversation_id,
        "termination_reason": termination_reason,
        "citation_count": citation_count,
    }


def emit_run_outcome(
    emitter: Webhook_Emitter,
    org_id: UUID,
    *,
    run_id: str,
    kind: RunKind,
    termination_reason: str | None,
    conversation_id: str | None = None,
    citation_count: int | None = None,
) -> None:
    """Emit the terminal outcome of a run. Never raises."""
    _emit(
        emitter,
        org_id,
        run_outcome_event(termination_reason),
        run_payload(
            run_id=run_id,
            kind=kind,
            termination_reason=termination_reason,
            conversation_id=conversation_id,
            citation_count=citation_count,
        ),
    )


def emit_document_ingested(
    emitter: Webhook_Emitter,
    org_id: UUID,
    *,
    document_id: str,
    filename: str,
    chunk_count: int,
    duplicate: bool,
) -> None:
    """Emit ``document.ingested``. ``duplicate`` is reported, not suppressed.

    A duplicate upload is a real event with a real outcome ("this is already in your corpus,
    here is the document it matched"), and a consumer that indexes on ingestion needs to know
    the difference rather than being told nothing happened.
    """
    _emit(
        emitter,
        org_id,
        Webhook_Event.DOCUMENT_INGESTED,
        {
            "document_id": document_id,
            "filename": filename,
            "chunk_count": chunk_count,
            "duplicate": duplicate,
        },
    )


def emit_guardrail_blocked(
    emitter: Webhook_Emitter,
    org_id: UUID,
    *,
    surface: str,
    reason: str | None,
) -> None:
    """Emit ``guardrail.blocked``.

    ``surface`` names the endpoint family that refused (``"query"``, ``"agent.run"``,
    ``"multi_agent.run"``) so a consumer can tell a blocked search from a blocked agent run.
    ``reason`` is the guardrail's own explanation — the same text the refused caller already
    received in its 400 — and never the content that was blocked.
    """
    _emit(
        emitter,
        org_id,
        Webhook_Event.GUARDRAIL_BLOCKED,
        {"surface": surface, "reason": reason},
    )


def emit_budget_threshold_crossed(
    emitter: Webhook_Emitter,
    org_id: UUID,
    *,
    threshold_percent: int,
    spent: str,
    limit_amount: str,
    percent_used: str,
    period_start: str,
    period_end: str,
    blocked: bool,
) -> list[Webhook_Delivery]:
    """Emit ``budget.threshold_crossed`` and return the recorded deliveries.

    The only helper here that returns anything, because its caller needs it: the alert service
    claims a threshold before announcing it (so concurrent requests cannot both announce), and
    must release that claim if nothing was actually delivered — otherwise a delivery outage
    would silently consume the one notification an organization was going to get.

    Monetary values are exact decimal **strings**, as everywhere else in this codebase: a spend
    of ``0.00013`` is not representable as a float without drift, and a webhook consumer that
    parsed a float would report a different number from the console.
    """
    return _emit(
        emitter,
        org_id,
        Webhook_Event.BUDGET_THRESHOLD_CROSSED,
        {
            "threshold_percent": threshold_percent,
            "spent": spent,
            "limit_amount": limit_amount,
            "percent_used": percent_used,
            "period_start": period_start,
            "period_end": period_end,
            "blocked": blocked,
        },
    )


def _emit(
    emitter: Webhook_Emitter,
    org_id: UUID,
    event: Webhook_Event,
    data: dict[str, object],
) -> list[Webhook_Delivery]:
    """Emit, absorbing everything. The emitter already does; this is belt and braces.

    Deliberately duplicated defence: the emission call sites are background tasks and error
    paths, where an escaping exception is either logged by a framework the operator does not
    read or lost entirely.
    """
    try:
        return emitter.emit(org_id, event, data)
    except Exception:  # noqa: BLE001 - emission must never affect the caller
        logger.warning(
            "Webhook emission for %s (org %s) failed.", event.value, org_id, exc_info=True
        )
        return []
