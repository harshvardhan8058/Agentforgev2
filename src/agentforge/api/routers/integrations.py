"""Integrations router: enablement status + per-org non-secret connection config.

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

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_audit_service,
    get_integration_connection_store,
    get_integration_status_service,
    require_permission,
)
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    CreateIntegrationConnectionRequest,
    IntegrationConnectionResponse,
    IntegrationStatusEntry,
    IntegrationStatusResponse,
    UpdateIntegrationConnectionRequest,
)
from agentforge.enterprise.audit import Audit_Action, Audit_Service
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.integrations import INTEGRATION_NAMES
from agentforge.integrations.config_policy import validate_connection_config
from agentforge.integrations.connection import (
    Integration_Connection,
    Integration_Connection_Store,
)
from agentforge.integrations.status import Integration_Status_Service

router = APIRouter(tags=["integrations"])


def _to_response(connection: Integration_Connection) -> IntegrationConnectionResponse:
    """Render a stored connection as its API response (non-secret fields only)."""
    return IntegrationConnectionResponse(
        connection_id=connection.id,
        integration=connection.integration,
        config=connection.config,
        created_at=connection.created_at,
    )


# An audit metadata value is bounded; the config admission policy allows up to 20 keys of 64
# characters, whose joined names would blow past that. The count is the fact worth recording,
# and the names are a best-effort detail, so the count is always exact and the list is what
# fits.
_MAX_AUDITED_SETTING_NAMES = 8


def _settings_metadata(integration: str, config: dict) -> dict[str, object]:
    """Audit metadata for a connection write: which integration, and which settings."""
    names = sorted(config)
    shown = names[:_MAX_AUDITED_SETTING_NAMES]
    return {
        "integration": integration,
        "setting_count": len(names),
        "settings": (
            ", ".join(shown) + (", …" if len(names) > len(shown) else "") or None
        ),
    }


def _not_found(connection_id: UUID) -> AppError:
    """Build the uniform 404 for an unknown or cross-tenant connection (Req 11.2)."""
    return AppError(
        "not_found",
        "Integration connection not found.",
        status.HTTP_404_NOT_FOUND,
        {"connection_id": str(connection_id)},
    )


def _validated_config(config: dict) -> dict:
    """Apply the non-secret admission policy, mapping a refusal onto a 400 (Req 11.4)."""
    try:
        return validate_connection_config(config)
    except ValueError as exc:
        raise AppError(
            "invalid_config",
            str(exc),
            status.HTTP_400_BAD_REQUEST,
            {"field": "config"},
        ) from exc


def _known_integration(name: str) -> str:
    """Return ``name`` iff it is one of the platform's integrations, else raise 400.

    Refused rather than stored, because a connection for an integration that does not exist
    can never be read by anything and would sit in the table forever looking like config.
    """
    if name not in INTEGRATION_NAMES:
        raise AppError(
            "unknown_integration",
            f"Unknown integration {name!r}.",
            status.HTTP_400_BAD_REQUEST,
            {"field": "integration", "known": list(INTEGRATION_NAMES)},
        )
    return name


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


@router.get("/integrations/connections", response_model=list[IntegrationConnectionResponse])
async def list_integration_connections(
    store: Integration_Connection_Store = Depends(get_integration_connection_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> list[IntegrationConnectionResponse]:
    """Return the caller org's stored connection configs, oldest first (Req 11.1).

    ``read`` is sufficient: the records are non-secret by construction, and seeing that (say)
    a default Slack channel is set is ordinary context for anybody who can use the platform.
    Mutating them requires ``manage_integrations``.
    """
    connections = await run_in_threadpool(store.list_for_org, principal.org_id)
    return [_to_response(c) for c in connections]


@router.post(
    "/integrations/connections",
    response_model=IntegrationConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration_connection(
    payload: CreateIntegrationConnectionRequest,
    store: Integration_Connection_Store = Depends(get_integration_connection_store),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(
        require_permission(Permission.MANAGE_INTEGRATIONS)
    ),
) -> IntegrationConnectionResponse:
    """Store non-secret config for one integration, scoped to the caller's org (Req 11.1).

    The integration name must be one the platform ships, and the config must satisfy the
    non-secret admission policy; both refusals are 400s naming the offending field. The
    record does not affect enablement — that stays a pure function of ``Settings``
    (Req 11.5) — so writing config never grants an integration any capability.
    """
    integration = _known_integration(payload.integration)
    config = _validated_config(payload.config)
    connection = await run_in_threadpool(
        store.create, principal.org_id, integration, config
    )
    # The settings' KEYS are recorded, not their values: which fields were configured is the
    # auditable fact, and a value could be operationally sensitive even when it is not a
    # credential (the admission policy already refused those).
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.INTEGRATION_CONNECTION_CREATED,
        target_type="integration_connection",
        target_id=str(connection.id),
        metadata=_settings_metadata(connection.integration, config),
    )
    return _to_response(connection)


@router.get(
    "/integrations/connections/{connection_id}",
    response_model=IntegrationConnectionResponse,
)
async def get_integration_connection(
    connection_id: UUID,
    store: Integration_Connection_Store = Depends(get_integration_connection_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> IntegrationConnectionResponse:
    """Return one connection owned by the caller's org; unknown/cross-tenant is 404."""
    connection = await run_in_threadpool(store.get, principal.org_id, connection_id)
    if connection is None:
        raise _not_found(connection_id)
    return _to_response(connection)


@router.patch(
    "/integrations/connections/{connection_id}",
    response_model=IntegrationConnectionResponse,
)
async def update_integration_connection(
    connection_id: UUID,
    payload: UpdateIntegrationConnectionRequest,
    store: Integration_Connection_Store = Depends(get_integration_connection_store),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(
        require_permission(Permission.MANAGE_INTEGRATIONS)
    ),
) -> IntegrationConnectionResponse:
    """Replace a connection's config; unknown/cross-tenant is 404, bad config is 400."""
    config = _validated_config(payload.config)
    updated = await run_in_threadpool(
        store.update_config, principal.org_id, connection_id, config
    )
    if updated is None:
        raise _not_found(connection_id)
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.INTEGRATION_CONNECTION_UPDATED,
        target_type="integration_connection",
        target_id=str(connection_id),
        metadata=_settings_metadata(updated.integration, config),
    )
    return _to_response(updated)


@router.delete(
    "/integrations/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_integration_connection(
    connection_id: UUID,
    store: Integration_Connection_Store = Depends(get_integration_connection_store),
    audit: Audit_Service = Depends(get_audit_service),
    principal: Principal = Depends(
        require_permission(Permission.MANAGE_INTEGRATIONS)
    ),
) -> Response:
    """Delete a connection owned by the caller's org; unknown/cross-tenant is 404."""
    doomed = await run_in_threadpool(store.get, principal.org_id, connection_id)
    deleted = await run_in_threadpool(store.delete, principal.org_id, connection_id)
    if not deleted:
        raise _not_found(connection_id)
    await run_in_threadpool(
        audit.record,
        principal,
        Audit_Action.INTEGRATION_CONNECTION_DELETED,
        target_type="integration_connection",
        target_id=str(connection_id),
        metadata={"integration": doomed.integration if doomed is not None else None},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
