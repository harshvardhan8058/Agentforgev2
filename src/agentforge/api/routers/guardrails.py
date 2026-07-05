"""Guardrails router: config + evaluate (Task 14.1).

Endpoints (design § "API endpoints — guardrails rows"):

* ``GET /guardrails/config`` — ``read``; the ordered list of active guardrail names +
  kinds (Req 5.1).
* ``POST /guardrails/evaluate`` — ``run_agents``; run content through the pipeline and
  return its allow / flag / block decision (Req 5.2-5.5).

Both handlers declare only ``Depends(require_permission(...))`` and read the wired
:class:`Guardrail_Pipeline` from the observability context, so the transport layer never
constructs the pipeline itself; every error renders through the existing envelope
(Req 7.4, 7.5, 9.4). The pipeline evaluation is a pure, deterministic function of its
content on the keyless path (Req 5.7), so no worker thread is required.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentforge.api.deps import get_guardrail_pipeline, require_permission
from agentforge.api.schemas import (
    GuardrailConfigResponse,
    GuardrailEvaluateRequest,
    GuardrailEvaluateResponse,
    GuardrailInfo,
)
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.guardrails.base import Guardrail_Pipeline

router = APIRouter(tags=["guardrails"])


@router.get("/guardrails/config", response_model=GuardrailConfigResponse)
async def get_guardrail_config(
    pipeline: Guardrail_Pipeline = Depends(get_guardrail_pipeline),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> GuardrailConfigResponse:
    """Return the ordered active guardrails (stable ``name`` + ``kind``) (Req 5.1).

    ``kind`` is the guardrail's implementation type name; the ordering mirrors the
    pipeline's stable configured evaluation order.
    """
    return GuardrailConfigResponse(
        guardrails=[
            GuardrailInfo(name=guardrail.name, kind=type(guardrail).__name__)
            for guardrail in pipeline.guardrails
        ]
    )


@router.post("/guardrails/evaluate", response_model=GuardrailEvaluateResponse)
async def evaluate_guardrails(
    payload: GuardrailEvaluateRequest,
    pipeline: Guardrail_Pipeline = Depends(get_guardrail_pipeline),
    principal: Principal = Depends(require_permission(Permission.RUN_AGENTS)),
) -> GuardrailEvaluateResponse:
    """Run ``content`` through the pipeline and return allow / flag / block (Req 5.2-5.5)."""
    result = pipeline.evaluate(payload.content)
    return GuardrailEvaluateResponse(
        decision=result.decision.value,
        flags=list(result.flags),
        reason=result.reason,
    )
