"""The emission points' payloads, in one place.

Every webhook body a subscriber receives is built here rather than at the router that triggers
it, for three reasons:

* **The payload is a published contract.** A consumer parses these keys. Spreading their
  construction across five routers is how one of them quietly starts sending a different shape.
* **What is *not* sent is a security decision.** These bodies carry identifiers, counts and
  outcomes — never an agent's answer, never a document's text, never a blocked input. A webhook
  endpoint lives outside this platform's trust boundary and outside the tenant's own console
  auth; a run's answer may contain material from their private corpus, and a blocked input is by
  definition something a guardrail judged hostile. Subscribers get an identifier and fetch the
  content through the authenticated API if they are entitled to it.
* **The success/failure rule is one rule.** ``run.completed`` versus ``run.failed`` is decided
  by :data:`SUCCESSFUL_TERMINATIONS` here, so the single-agent and multi-agent routers cannot
  classify the same outcome differently.

Every function is fire-and-forget by contract: the emitter never raises, and these add nothing
that could. They are called as background tasks or post-stream hooks, never inline.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.emitter import Webhook_Emitter

#: Terminal reasons that count as a run producing what it was asked for. Everything else —
#: an iteration or round limit, a rejected or aborted plan — is reported as ``run.failed``,
#: because from the caller's side the run did not deliver an accepted result. A run that raised
#: an exception emits nothing: the caller already received a 5xx, and there is no completed run
#: to describe.
SUCCESSFUL_TERMINATIONS: Final[frozenset[str]] = frozenset(
    {
        "final-answer",  # agent.state.TerminationReason.FINAL_ANSWER
        "completed",  # multiagent.models.Termination_Reason.COMPLETED
    }
)

#: The kinds of run that can be reported, so a consumer can route by one field instead of
#: inferring from which optional keys are present.
RUN_KIND_SINGLE: Final[str] = "single_agent"
RUN_KIND_MULTI: Final[str] = "multi_agent"


def emit_run_outcome(
    emitter: Webhook_Emitter,
    org_id: UUID,
    *,
    run_id: str,
    kind: str,
    termination_reason: str,
    conversation_id: str | None = None,
    citation_count: int | None = None,
) -> None:
    """Emit ``run.completed`` or ``run.failed`` for a finished run.

    ``termination_reason`` is passed through verbatim so a consumer can tell an iteration limit
    from a rejected plan — the event name is the coarse signal, the reason is the detail.
    """
    event = (
        Webhook_Event.RUN_COMPLETED
        if termination_reason in SUCCESSFUL_TERMINATIONS
        else Webhook_Event.RUN_FAILED
    )
    data: dict[str, object] = {
        "run_id": run_id,
        "kind": kind,
        "termination_reason": termination_reason,
    }
    if conversation_id is not None:
        data["conversation_id"] = conversation_id
    if citation_count is not None:
        # How well-grounded the answer was, without shipping the answer or the sources.
        data["citation_count"] = citation_count
    emitter.emit(org_id, event, data)


def emit_document_ingested(
    emitter: Webhook_Emitter,
    org_id: UUID,
    *,
    document_id: str,
    filename: str,
    chunk_count: int,
    duplicate: bool,
) -> None:
    """Emit ``document.ingested`` for a document that finished ingestion.

    ``duplicate`` is included because it changes what the event means: the corpus did not
    grow, and a consumer that indexes new documents downstream should skip this one. Without
    the flag they would have to diff their own state to find out.
    """
    emitter.emit(
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
    """Emit ``guardrail.blocked`` when an input was refused by a guardrail.

    ``surface`` is the endpoint that refused it (``"agent.run"``, ``"query"``, …), which is what
    a security team correlates on. ``reason`` is the guardrail's own short explanation — never
    the offending input, which is precisely the content a guardrail exists to keep from being
    passed on.
    """
    emitter.emit(
        org_id,
        Webhook_Event.GUARDRAIL_BLOCKED,
        {"stage": "input", "surface": surface, "reason": reason},
    )
