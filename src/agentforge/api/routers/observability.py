"""Observability router: what this deployment does with the telemetry it produces.

``GET /observability/status`` answers a question a client could not previously ask: are the
traces it is looking at going anywhere? Traces are always *recorded* (the Trace_Recorder is
never optional), but *export* to an external destination depends on a credential, so a
trace surface has no way to distinguish "export is off" from "this run had no steps" — the
ambiguity this endpoint removes.

It follows the ``GET /analytics/cost-rates`` precedent exactly: deployment-wide (identical
for every org), credential-free (a boolean, an exporter name, and a non-secret project
label), and gated on ``read`` — an unauthenticated caller has no reason to learn how a
deployment is instrumented.

The status is derived from the wired Trace_Export_Service rather than from ``Settings``, so
it reports what the process will *actually* do: a configured exporter with no recorder to
read traces from is reported as disabled, because that is the truth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentforge.api.deps import get_settings, get_trace_export_service, require_permission
from agentforge.api.schemas import ObservabilityStatusResponse, TraceExportStatus
from agentforge.config.settings import Settings
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.trace_export import Trace_Export_Service

router = APIRouter(tags=["observability"])


@router.get("/observability/status", response_model=ObservabilityStatusResponse)
async def get_observability_status(
    trace_export: Trace_Export_Service = Depends(get_trace_export_service),
    settings: Settings = Depends(get_settings),
    _principal: Principal = Depends(require_permission(Permission.READ)),
) -> ObservabilityStatusResponse:
    """Report how this deployment handles run telemetry (Req 1.2, 10.2).

    ``trace_export.enabled`` is the authoritative signal: it is false for the keyless NoOp
    exporter and false if a real exporter was configured without a trace recorder, so a
    client can never be told export is on while nothing leaves the process.
    """
    exporter = trace_export.exporter_name
    # The destination label is only meaningful for an exporter that has one, and is a
    # non-secret project name — never a credential (Req 10.1).
    destination = settings.langsmith_project if exporter == "langsmith" else None
    return ObservabilityStatusResponse(
        trace_export=TraceExportStatus(
            enabled=trace_export.enabled,
            exporter=exporter,
            destination=destination,
        )
    )
