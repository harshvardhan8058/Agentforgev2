"""OpenTelemetry (OTLP) Tracing_Exporter — a vendor-neutral second destination.

LangSmith was the only place a trace could go, which ties the platform's observability to
one SaaS product. OTLP is the industry-standard wire protocol: a deployment already running
Tempo, Jaeger, Honeycomb, Datadog, or an OpenTelemetry Collector can receive AgentForge
traces without either side knowing about the other.

Shape of the export. One OTel **span per run**, with one **child span per trace entry**, so
the run appears in a waterfall exactly as it does in the console's timeline:

    agent.run  (run_id, org_id, user_id)
    ├── agent.reason      (ordinal=0)
    ├── agent.tool_call   (ordinal=1, tool_name=rag_search, outcome=ok)
    └── agent.observe     (ordinal=2)

Only structural attributes are attached — ordinal, step type, tool name, outcome, and the
tenant/user ids. The ``detail`` payload is deliberately **not** exported: it can carry
prompt and observation text, and a trace backend is a different trust boundary from the
database the tenant already owns. ``role_id`` is the one detail key that is forwarded,
because it is the multi-agent attribution the timeline is built around and is not content.

Dependencies. The OpenTelemetry SDK is imported **lazily**, inside the export path, exactly
like the LangSmith client: the keyless stack must boot and run without it, and nothing here
may be constructed at import time. Install it with the ``otel`` extra
(``pip install -e ".[otel]"``). A missing dependency degrades to "no export", never to a
failed run — the same contract every exporter carries (Req 1.5, 1.7) — is reported by
:meth:`OTLP_Tracing_Exporter.available` so no status surface can claim otherwise, and is
logged once rather than once per run.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import UUID

from agentforge.observability.tracing_exporter import Tracing_Exporter
from agentforge.tracing.base import Trace

logger = logging.getLogger(__name__)

OTLP_EXPORTER_NAME = "otlp"

# Upper bound on the per-run flush. The BatchSpanProcessor's default export timeout is 30
# seconds, and this flush runs inside the SSE response body iterator on a streamed run — an
# unreachable collector would hold the client's connection (and the console's "streaming"
# state) open for that whole time, long after the terminal event was delivered. Two seconds
# is enough for a healthy collector; anything slower is left to the processor's own
# scheduled delivery rather than made the caller's problem.
FLUSH_TIMEOUT_MS = 2_000

# Sentinel distinguishing "not built yet" from "cannot be built". Without it a missing
# optional dependency re-attempts the import and re-logs the warning on every completed run.
_UNAVAILABLE = object()

# Span names. Prefixed so they are recognisable in a backend shared with other services.
RUN_SPAN_NAME = "agent.run"
STEP_SPAN_PREFIX = "agent."


class OTLP_Tracing_Exporter(Tracing_Exporter):
    """Export a completed Trace to any OTLP-compatible collector.

    Args:
        endpoint: OTLP/HTTP traces endpoint, e.g. ``http://collector:4318/v1/traces``.
        service_name: value of the ``service.name`` resource attribute.
        headers: optional ``key=value,key2=value2`` header string (an ingest key belongs
            here; it is passed straight to the SDK and never logged).
        span_exporter: optional injected OTel ``SpanExporter``. Supplied by tests so the
            mapping can be asserted against real SDK spans without a network endpoint;
            production leaves it unset and the OTLP/HTTP exporter is built lazily.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        service_name: str = "agentforge",
        headers: str | None = None,
        span_exporter: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._service_name = service_name
        self._headers = headers
        self._span_exporter = span_exporter
        # `None` = not built yet; `_UNAVAILABLE` = build failed permanently (missing
        # dependency). Guarded by a lock because export runs concurrently (several
        # background tasks in the threadpool plus SSE worker threads), and two threads each
        # building a provider would orphan a BatchSpanProcessor thread whose spans are never
        # flushed.
        self._provider: Any = None
        self._build_lock = threading.Lock()

    @property
    def name(self) -> str:
        return OTLP_EXPORTER_NAME

    def available(self) -> bool:
        """True when this exporter can actually deliver spans.

        Overrides the seam's default because an OTLP endpoint can be configured without the
        OpenTelemetry SDK installed, and reporting that deployment as "exporting" would
        recreate the defect this whole feature fixed: a surface claiming a feature works
        while nothing leaves the process. Resolving it means attempting the (cached) SDK
        import, so the answer is exact rather than a guess about configuration.
        """
        return self._get_provider() is not None

    def export(self, trace: Trace, *, org_id: UUID, user_id: UUID | None) -> None:
        """Emit the trace as a span tree. Never propagates a failure (Req 1.5, 1.7)."""
        try:
            tracer = self._get_tracer()
            if tracer is None:
                return
            self._emit(tracer, trace, org_id=org_id, user_id=user_id)
        except Exception:  # noqa: BLE001 - export must never change a run's outcome
            logger.warning(
                "OTLP trace export failed for run %s.", trace.run_id, exc_info=True
            )

    # --- span emission ------------------------------------------------------------
    def _emit(self, tracer: Any, trace: Trace, *, org_id: UUID, user_id: UUID | None):
        """Write the run span and its per-entry children, then flush."""
        with tracer.start_as_current_span(RUN_SPAN_NAME) as run_span:
            run_span.set_attribute("agentforge.run_id", trace.run_id)
            run_span.set_attribute("agentforge.org_id", str(org_id))
            if user_id is not None:
                run_span.set_attribute("agentforge.user_id", str(user_id))
            run_span.set_attribute("agentforge.step_count", len(trace.entries))
            for entry in trace.entries:
                with tracer.start_as_current_span(
                    f"{STEP_SPAN_PREFIX}{entry.step_type}"
                ) as step_span:
                    step_span.set_attribute("agentforge.ordinal", entry.ordinal)
                    step_span.set_attribute("agentforge.step_type", entry.step_type)
                    if entry.tool_name:
                        step_span.set_attribute("agentforge.tool_name", entry.tool_name)
                    if entry.outcome:
                        step_span.set_attribute("agentforge.outcome", entry.outcome)
                    # Only the multi-agent attribution key is forwarded from `detail`;
                    # the rest can hold prompt/observation content.
                    role_id = (entry.detail or {}).get("role_id")
                    if role_id:
                        step_span.set_attribute("agentforge.role_id", str(role_id))
        # Export is invoked per finished run from a background task, not per span, so a
        # synchronous flush is what actually delivers the batch before this returns.
        provider = self._provider
        if provider is not None and hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=FLUSH_TIMEOUT_MS)

    # --- lazy SDK construction ----------------------------------------------------
    def _get_tracer(self) -> Any | None:
        """Return a tracer bound to a private provider, or None if unavailable."""
        provider = self._get_provider()
        if provider is None:
            return None
        return provider.get_tracer("agentforge.trace_export")

    def _get_provider(self) -> Any | None:
        """Build (once) and return the private TracerProvider, or None if unavailable.

        A **private** ``TracerProvider`` is used rather than the global one so that
        installing AgentForge into a host application that already configures
        OpenTelemetry cannot be disturbed by this exporter, and vice versa.

        Built under a lock and memoised in both directions: a successful build is reused,
        and a failed one is remembered so a missing optional dependency logs once instead of
        once per completed run.
        """
        if self._provider is _UNAVAILABLE:
            return None
        if self._provider is not None:
            return self._provider
        with self._build_lock:
            # Re-check inside the lock: another thread may have built it while we waited.
            if self._provider is _UNAVAILABLE:
                return None
            if self._provider is None:
                built = self._build_provider()
                self._provider = built if built is not None else _UNAVAILABLE
            return self._provider if self._provider is not _UNAVAILABLE else None

    def _build_provider(self) -> Any | None:
        """Build the private TracerProvider, or None when the SDK/exporter is absent."""
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            logger.warning(
                "OTLP trace export is configured but the OpenTelemetry SDK is not "
                "installed; install the 'otel' extra. Traces are still recorded locally."
            )
            return None

        span_exporter = self._span_exporter
        if span_exporter is None:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
            except ImportError:
                logger.warning(
                    "OTLP trace export is configured but the OTLP/HTTP exporter is not "
                    "installed; install the 'otel' extra. Traces are still recorded "
                    "locally."
                )
                return None
            span_exporter = OTLPSpanExporter(
                endpoint=self._endpoint,
                headers=self._parse_headers(self._headers),
            )

        provider = TracerProvider(
            resource=Resource.create({"service.name": self._service_name})
        )
        provider.add_span_processor(BatchSpanProcessor(span_exporter))
        return provider

    @staticmethod
    def _parse_headers(raw: str | None) -> dict[str, str] | None:
        """Parse ``k=v,k2=v2`` into a mapping, ignoring malformed pairs.

        The OTLP convention for headers in configuration. Malformed pairs are skipped
        rather than raising, because a header typo must not stop a deployment from booting
        — and the header value may be a credential, so it is never echoed in a message.
        """
        if not raw:
            return None
        headers: dict[str, str] = {}
        for pair in raw.split(","):
            key, separator, value = pair.partition("=")
            if separator and key.strip():
                headers[key.strip()] = value.strip()
        return headers or None
