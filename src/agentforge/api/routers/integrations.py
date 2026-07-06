"""Integrations router: ``GET /integrations/status`` (Task 6.2).

Returns the org-scoped, read-only Integration_Status view — one ``{name, enabled}`` entry
per integration, with enablement derived at request time from the configured Credentials +
Enable_Settings and **no** credential value ever exposed (Req 9.1, 9.2, 9.5).

The endpoint mirrors the analytics router exactly: it declares only
``Depends(require_permission(Permission.READ))`` and holds **no** bespoke authorization
logic. A missing/invalid credential surfaces as 401 ``unauthorized`` via
``get_current_principal`` and a principal lacking ``read`` as 403 ``forbidden`` via
``require_permission``, both rendered through the existing ``AppError`` envelope
(Req 7.5, 9.3, 9.4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentforge.api.deps import get_integration_status_service, require_permission
from agentforge.api.schemas import IntegrationStatusEntry, IntegrationStatusResponse
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.integrations.status import Integration_Status_Service

router = APIRouter(tags=["integrations"])


@router.get("/integrations/status", response_model=IntegrationStatusResponse)
async def get_integration_status(
    service: Integration_Status_Service = Depends(get_integration_status_service),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> IntegrationStatusResponse:
    """Return each integration's ``{name, enabled}`` status for the caller (Req 9.1, 9.5).

    Enablement is derived at request time from ``Settings.integration_enabled`` — a pure
    function of the configured Credential presence and Enable_Setting — so the response
    reflects current configuration and contains only ``{name, enabled}`` pairs, never a
    credential (Req 9.2). Authorization is enforced entirely by the declared
    ``require_permission(Permission.READ)`` dependency (Req 9.3, 9.4).
    """
    entries = [
        IntegrationStatusEntry(name=entry.name, enabled=entry.enabled)
        for entry in service.status()
    ]
    return IntegrationStatusResponse(integrations=entries)
