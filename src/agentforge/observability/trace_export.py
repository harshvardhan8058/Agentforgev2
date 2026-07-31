"""Trace_Export_Service — hands a completed run's Trace to the configured exporter.

The ``Tracing_Exporter`` seam (``observability/tracing_exporter.py``) has existed since
Phase 6 with a NoOp and a LangSmith implementation, a settings-driven factory, a DI
accessor and its own tests — and **nothing ever called it**. Setting ``LANGSMITH_API_KEY``
therefore changed a startup log line and nothing else: no trace was ever exported. This
service is the missing link between a finished run and that seam.

It exists as a service rather than as a call inside the agent loop for three reasons:

* **The exporter must never affect a run.** A run is finished and its result already
  computed (and, for SSE, already delivered) before this is invoked, so an export failure
  cannot change an answer, a termination reason, or a stream's terminal event. Every
  failure — including a failure to *read* the trace — is swallowed here, not just inside
  the exporter (Req 1.7, 10.2).
* **The trace is authoritative in the recorder, not in the run state.** The orchestrator
  never assembles a whole ``Trace``; the recorder does, including the multi-agent
  ``role_id`` detail. Reading it back is the only way to export what the API would serve.
* **Export must cost nothing when it is off.** With the NoOp exporter the service
  short-circuits *before* reading the trace, so the keyless default adds no store round
  trip per run. That check is also what makes ``enabled`` honest for the status surface.

Threading: ``export_run`` is synchronous, like the exporter and the recorder it calls, and
is invoked from a background task or from a worker thread by its callers.
"""

from __future__ import annotations

import logging
from uuid import UUID

from agentforge.observability.tracing_exporter import (
    NOOP_EXPORTER_NAME,
    NoOp_Tracing_Exporter,
    Tracing_Exporter,
)
from agentforge.tracing.base import Trace_Recorder

logger = logging.getLogger(__name__)


class Trace_Export_Service:
    """Best-effort export of a completed run's Trace to an external destination.

    Holds the two seams it bridges and nothing else: a :class:`Tracing_Exporter` (where a
    trace goes) and a :class:`Trace_Recorder` (where it is read from). Both are injected;
    this class never selects an implementation.
    """

    def __init__(
        self,
        exporter: Tracing_Exporter,
        recorder: Trace_Recorder | None = None,
    ) -> None:
        self._exporter = exporter
        self._recorder = recorder
        if recorder is None and exporter.name != NOOP_EXPORTER_NAME:
            # A real exporter with nowhere to read traces from would silently export
            # nothing, which is exactly the class of defect this service exists to fix.
            # It cannot happen through the composition root; it is reachable only from a
            # partially-wired test or an out-of-order build, so it is reported loudly and
            # then treated as "export unavailable" rather than pretending to work.
            logger.warning(
                "Tracing exporter %r is configured but no Trace_Recorder was wired; "
                "trace export is unavailable.",
                exporter.name,
            )

    @property
    def exporter_name(self) -> str:
        """Name of the configured exporter (``"noop"`` when export is off)."""
        return self._exporter.name

    @property
    def enabled(self) -> bool:
        """True when a completed run would actually be exported somewhere.

        False for the NoOp exporter and false when no recorder is wired, so a client
        surface built on this cannot claim export is on while nothing leaves the process.
        """
        return self._exporter.name != NOOP_EXPORTER_NAME and self._recorder is not None

    def export_run(
        self, run_id: str, *, org_id: UUID, user_id: UUID | None = None
    ) -> bool:
        """Read ``run_id``'s trace and hand it to the exporter. Never raises.

        Returns True only when a non-empty trace was handed over, so a caller (or a test)
        can distinguish "exported", "nothing to export", and "export is off" without
        catching anything. The return value is deliberately unused by the run paths: they
        must not branch on export at all.
        """
        if not self.enabled:
            return False
        assert self._recorder is not None  # narrowed by `enabled`
        try:
            trace = self._recorder.get_trace(org_id, run_id)
        except Exception:  # noqa: BLE001 - reading a trace must not fail a finished run
            logger.warning(
                "Could not read trace for run %s; skipping export.", run_id, exc_info=True
            )
            return False

        if not trace.entries:
            # An unknown, cross-tenant, or step-free run. Nothing to send, and no error:
            # the recorder returns an empty trace for all three (Req 4.3).
            return False

        try:
            self._exporter.export(trace, org_id=org_id, user_id=user_id)
        except Exception:  # noqa: BLE001 - the exporter contract already forbids this
            # Reached only if an implementation breaks its own contract. Swallowed here so
            # that a third-party exporter's bug can never surface as a failed run.
            logger.warning(
                "Trace exporter %r raised while exporting run %s.",
                self._exporter.name,
                run_id,
                exc_info=True,
            )
            return False
        return True


def disabled_trace_export_service() -> Trace_Export_Service:
    """Return a permanently-disabled export service (NoOp exporter, no recorder).

    Used by the transport layer when no observability graph is wired, so a run endpoint can
    depend on an export service unconditionally without a missing observability context
    becoming a failed run. It lives here rather than in ``api/deps.py`` because naming a
    concrete implementation is this layer's job, not the transport layer's (Req 7.3, 9.7).

    The instance is shared: it holds no state.
    """
    return _DISABLED


_DISABLED = Trace_Export_Service(NoOp_Tracing_Exporter(), None)
