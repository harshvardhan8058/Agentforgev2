"""Prompts router: the org-scoped Prompt_Registry API (Task 13).

Endpoints (design § "API endpoints — prompts rows"):

* ``POST /prompts`` — ``ingest_documents``; append a new immutable ``Prompt_Version``.
* ``GET /prompts`` — ``read``; list the org's template names.
* ``GET /prompts/{name}/versions`` — ``read``; ascending version numbers.
* ``GET /prompts/{name}`` — ``read``; the latest version, or ``?version=N``.
* ``POST /prompts/{name}/render`` — ``read``; render with supplied variables (a missing
  declared variable → ``400 missing_variable``).

Every handler declares only ``Depends(require_permission(...))`` and threads
``principal.org_id`` into the :class:`Prompt_Registry`, so a cross-tenant lookup matches
zero rows and surfaces as ``404 not_found`` — never a 403 that would leak existence
(Req 4.8, 7.6, 10.4). The registry / store are synchronous, so their calls run in a
worker thread to avoid blocking the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_prompt_registry, require_permission
from agentforge.api.schemas import (
    CreatePromptVersionRequest,
    PromptVersionResponse,
    RenderPromptRequest,
    RenderPromptResponse,
)
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.models import Prompt_Version
from agentforge.observability.prompt_registry.registry import Prompt_Registry

router = APIRouter(tags=["prompts"])


def _to_response(version: Prompt_Version) -> PromptVersionResponse:
    """Map a resolved :class:`Prompt_Version` to its API response envelope."""
    return PromptVersionResponse(
        id=version.id,
        name=version.template_name,
        version=version.version,
        body=version.body,
        variables=list(version.variables),
        created_at=version.created_at,
    )


@router.post(
    "/prompts",
    response_model=PromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_version(
    payload: CreatePromptVersionRequest,
    registry: Prompt_Registry = Depends(get_prompt_registry),
    principal: Principal = Depends(require_permission(Permission.INGEST_DOCUMENTS)),
) -> PromptVersionResponse:
    """Append a new immutable Prompt_Version numbered ``max+1``/``1`` (Req 4.1, 4.9)."""
    version = await run_in_threadpool(
        registry.create_version,
        principal.org_id,
        payload.name,
        payload.body,
        payload.variables,
    )
    return _to_response(version)


@router.get("/prompts", response_model=list[str])
async def list_prompts(
    registry: Prompt_Registry = Depends(get_prompt_registry),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> list[str]:
    """List the caller org's template names (ascending); never cross-org (Req 4.8)."""
    return await run_in_threadpool(registry.list_template_names, principal.org_id)


@router.get("/prompts/{name}/versions", response_model=list[int])
async def list_prompt_versions(
    name: str,
    registry: Prompt_Registry = Depends(get_prompt_registry),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> list[int]:
    """Return the ascending version numbers for ``(org, name)`` (Req 4.5)."""
    return await run_in_threadpool(registry.list_versions, principal.org_id, name)


@router.get("/prompts/{name}", response_model=PromptVersionResponse)
async def get_prompt(
    name: str,
    version: int | None = Query(default=None, ge=1),
    registry: Prompt_Registry = Depends(get_prompt_registry),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> PromptVersionResponse:
    """Return the latest version, or ``?version=N``; 404 if absent (Req 4.3, 4.4, 4.8)."""
    resolved = await run_in_threadpool(
        registry.get, principal.org_id, name, version
    )
    return _to_response(resolved)


@router.post("/prompts/{name}/render", response_model=RenderPromptResponse)
async def render_prompt(
    name: str,
    payload: RenderPromptRequest,
    registry: Prompt_Registry = Depends(get_prompt_registry),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> RenderPromptResponse:
    """Render a resolved version with supplied values; missing variable → 400 (Req 4.6, 4.7).

    Resolves the version (latest or ``payload.version``) org-scoped — an absent template
    or cross-tenant lookup raises ``404 not_found`` — then substitutes every declared
    variable, raising ``400 missing_variable`` (listing the missing names) when any is
    omitted.
    """
    resolved = await run_in_threadpool(
        registry.get, principal.org_id, name, payload.version
    )
    rendered = registry.render(resolved, payload.variables)
    return RenderPromptResponse(
        name=resolved.template_name, version=resolved.version, rendered=rendered
    )
