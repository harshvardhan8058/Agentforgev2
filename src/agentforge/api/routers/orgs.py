"""Organizations router: orgs, members, teams, and API keys (Task 12).

Every ``/orgs/{id}/...`` handler declares only ``Depends(require_permission(...))`` and
threads ``principal.org_id`` — no bespoke authorization logic lives here (Req 7.6, 7.7).
Cross-tenant access (the caller's ``org_id`` differs from the ``{id}`` in the path) is
surfaced as ``AppError("not_found", 404)`` so existence is never leaked (Req 4.3, 5.7),
consistent with the design's "cross-tenant is 404, never 403" rule.

Endpoint → permission map (design § "Applying auth + tenancy to existing endpoints"):

* ``POST /orgs`` — any authenticated principal (creates a NEW org they own).
* ``GET|POST /orgs/{id}/members`` and ``PATCH|DELETE /orgs/{id}/members/{user_id}`` —
  ``manage_members``.
* ``GET|POST /orgs/{id}/teams``, ``DELETE /orgs/{id}/teams/{tid}``,
  ``GET|POST /orgs/{id}/teams/{tid}/members`` and
  ``DELETE /orgs/{id}/teams/{tid}/members/{user_id}`` — ``manage_members``.
* ``POST|GET|DELETE /orgs/{id}/api-keys`` — ``manage_api_keys``.

The membership mutations preserve one domain invariant beyond RBAC: an Organization must
always retain at least one ``OWNER``, so a demotion or removal that would remove the last
one is refused with ``AppError("last_owner", 400)``. The check lives in the Identity_Store
(next to the write, inside the same transaction for the Postgres implementation) rather
than here, so it cannot be bypassed by a future call site.

The Identity_Store / API_Key_Service are synchronous, so their calls run in a worker
thread to avoid blocking the event loop.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_api_key_service,
    get_current_principal,
    get_identity_store,
    require_permission,
)
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    AddMemberRequest,
    AddMemberResponse,
    AddTeamMemberRequest,
    AddTeamMemberResponse,
    ApiKeyMetadata,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    CreateOrgRequest,
    CreateOrgResponse,
    CreateTeamRequest,
    CreateTeamResponse,
    MemberSummary,
    TeamMemberSummary,
    TeamSummary,
    UpdateMemberRoleRequest,
)
from agentforge.enterprise.api_keys import API_Key_Service
from agentforge.enterprise.base import Identity_Store
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission, Role

router = APIRouter(tags=["orgs"])


def _ensure_same_org(principal: Principal, org_id: UUID) -> None:
    """Raise a uniform 404 when ``org_id`` is not the caller's tenant (Req 4.3, 5.7)."""
    if principal.org_id != org_id:
        raise AppError(
            "not_found",
            "Organization not found.",
            status.HTTP_404_NOT_FOUND,
            {"org_id": str(org_id)},
        )


def _not_found_user(email: str) -> AppError:
    """Build the uniform 404 for an unknown user referenced by email."""
    return AppError(
        "not_found",
        "User not found.",
        status.HTTP_404_NOT_FOUND,
        {"email": email},
    )


def _not_found_member(user_id: UUID) -> AppError:
    """Build the uniform 404 for a member absent from the caller's organization."""
    return AppError(
        "not_found",
        "Member not found.",
        status.HTTP_404_NOT_FOUND,
        {"user_id": str(user_id)},
    )


def _not_found_team(team_id: UUID) -> AppError:
    """Build the uniform 404 for a team absent from the caller's organization."""
    return AppError(
        "not_found",
        "Team not found.",
        status.HTTP_404_NOT_FOUND,
        {"team_id": str(team_id)},
    )


async def _emails_for(
    identity: Identity_Store, user_ids: list[UUID]
) -> dict[UUID, str]:
    """Return a ``user_id -> email`` map resolved in a single store call."""
    if not user_ids:
        return {}
    users = await run_in_threadpool(identity.list_users_by_ids, user_ids)
    return {u.id: u.email for u in users}


@router.post(
    "/orgs",
    response_model=CreateOrgResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_org(
    payload: CreateOrgRequest,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(get_current_principal),
) -> CreateOrgResponse:
    """Create a NEW Organization owned by the caller (Req 2.1, 2.2).

    Any authenticated principal may create an org; a User principal is added as its
    ``OWNER`` so they can immediately manage it.
    """
    org = await run_in_threadpool(identity.create_organization, payload.name)
    if principal.user_id is not None:
        await run_in_threadpool(
            identity.add_membership, principal.user_id, org.id, Role.OWNER
        )
    return CreateOrgResponse(org_id=org.id)


@router.post(
    "/orgs/{org_id}/members",
    response_model=AddMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    org_id: UUID,
    payload: AddMemberRequest,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> AddMemberResponse:
    """Add an existing user (by email) to ``org_id`` under a Role (Req 2.2)."""
    _ensure_same_org(principal, org_id)
    user = await run_in_threadpool(identity.get_user_by_email, payload.email)
    if user is None:
        raise _not_found_user(payload.email)
    membership = await run_in_threadpool(
        identity.add_membership, user.id, org_id, payload.role
    )
    return AddMemberResponse(
        user_id=membership.user_id, org_id=membership.org_id, role=membership.role
    )


@router.get("/orgs/{org_id}/members", response_model=list[MemberSummary])
async def list_members(
    org_id: UUID,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> list[MemberSummary]:
    """Return every Membership in ``org_id`` with its User's email (Req 2.6, 4.4).

    The store filters by ``org_id``, so another tenant's roster is structurally
    unreachable; emails are resolved in one batched call rather than per row.
    """
    _ensure_same_org(principal, org_id)
    memberships = await run_in_threadpool(identity.list_org_members, org_id)
    emails = await _emails_for(identity, [m.user_id for m in memberships])
    return [
        MemberSummary(
            user_id=m.user_id,
            email=emails.get(m.user_id),
            role=m.role,
            created_at=m.created_at,
        )
        for m in memberships
    ]


@router.patch("/orgs/{org_id}/members/{user_id}", response_model=MemberSummary)
async def update_member_role(
    org_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> MemberSummary:
    """Reassign a member's Role within ``org_id`` (Req 2.2, 3.4).

    An unknown member — or one belonging to another tenant — is a uniform 404. Demoting
    the organization's last owner raises ``AppError("last_owner", 400)``.
    """
    _ensure_same_org(principal, org_id)
    membership = await run_in_threadpool(
        identity.update_membership_role, user_id, org_id, payload.role
    )
    if membership is None:
        raise _not_found_member(user_id)
    user = await run_in_threadpool(identity.get_user, user_id)
    return MemberSummary(
        user_id=membership.user_id,
        email=user.email if user is not None else None,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete(
    "/orgs/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    org_id: UUID,
    user_id: UUID,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> Response:
    """Remove a member from ``org_id``, together with their Team_Memberships (Req 2.5).

    An unknown or cross-tenant member is a uniform 404; removing the last owner raises
    ``AppError("last_owner", 400)``.
    """
    _ensure_same_org(principal, org_id)
    removed = await run_in_threadpool(identity.remove_membership, user_id, org_id)
    if not removed:
        raise _not_found_member(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/teams",
    response_model=CreateTeamResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_team(
    org_id: UUID,
    payload: CreateTeamRequest,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> CreateTeamResponse:
    """Create an org-scoped Team within ``org_id`` (Req 2.3)."""
    _ensure_same_org(principal, org_id)
    team = await run_in_threadpool(identity.create_team, org_id, payload.name)
    return CreateTeamResponse(
        team_id=team.id, name=team.name, created_at=team.created_at
    )


@router.get("/orgs/{org_id}/teams", response_model=list[TeamSummary])
async def list_teams(
    org_id: UUID,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> list[TeamSummary]:
    """Return every Team in ``org_id``, oldest first (Req 2.3, 4.4)."""
    _ensure_same_org(principal, org_id)
    teams = await run_in_threadpool(identity.list_teams, org_id)
    return [
        TeamSummary(team_id=t.id, name=t.name, created_at=t.created_at) for t in teams
    ]


@router.delete(
    "/orgs/{org_id}/teams/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_team(
    org_id: UUID,
    team_id: UUID,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> Response:
    """Delete a Team from ``org_id`` with its Team_Memberships; unknown/cross-org is 404."""
    _ensure_same_org(principal, org_id)
    deleted = await run_in_threadpool(identity.delete_team, org_id, team_id)
    if not deleted:
        raise _not_found_team(team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/teams/{team_id}/members",
    response_model=AddTeamMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_team_member(
    org_id: UUID,
    team_id: UUID,
    payload: AddTeamMemberRequest,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> AddTeamMemberResponse:
    """Add a user (by email) to a Team (Req 2.4, 2.5).

    The Team is resolved **within the caller's org first**: a Team belonging to another
    tenant is a uniform 404, never an attempt that the store might accept. (Without that
    lookup, a user who happens to hold memberships in both organizations would satisfy the
    store's cross-org guard and be added to a foreign tenant's Team — Req 4.3, 5.7.)

    A user holding no Membership in the team's Organization propagates
    ``AppError("org_mismatch", 400)`` from the Identity_Store.
    """
    _ensure_same_org(principal, org_id)
    if await run_in_threadpool(identity.get_team, org_id, team_id) is None:
        raise _not_found_team(team_id)
    user = await run_in_threadpool(identity.get_user_by_email, payload.email)
    if user is None:
        raise _not_found_user(payload.email)
    membership = await run_in_threadpool(identity.add_team_member, team_id, user.id)
    return AddTeamMemberResponse(
        team_id=membership.team_id, user_id=membership.user_id
    )


@router.get(
    "/orgs/{org_id}/teams/{team_id}/members",
    response_model=list[TeamMemberSummary],
)
async def list_team_members(
    org_id: UUID,
    team_id: UUID,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> list[TeamMemberSummary]:
    """Return a Team's members with their emails; unknown/cross-org Team is 404."""
    _ensure_same_org(principal, org_id)
    if await run_in_threadpool(identity.get_team, org_id, team_id) is None:
        raise _not_found_team(team_id)
    members = await run_in_threadpool(identity.list_team_members, org_id, team_id)
    emails = await _emails_for(identity, [m.user_id for m in members])
    return [
        TeamMemberSummary(
            user_id=m.user_id,
            email=emails.get(m.user_id),
            created_at=m.created_at,
        )
        for m in members
    ]


@router.delete(
    "/orgs/{org_id}/teams/{team_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_team_member(
    org_id: UUID,
    team_id: UUID,
    user_id: UUID,
    identity: Identity_Store = Depends(get_identity_store),
    principal: Principal = Depends(require_permission(Permission.MANAGE_MEMBERS)),
) -> Response:
    """Remove a User from a Team within ``org_id``; unknown/cross-org target is 404.

    The member keeps their Organization Membership — only the Team association is removed.
    """
    _ensure_same_org(principal, org_id)
    removed = await run_in_threadpool(
        identity.remove_team_member, org_id, team_id, user_id
    )
    if not removed:
        # Distinguish the two "nothing was removed" causes for the operator, without
        # leaking anything across tenants: both are 404, only the details differ.
        team = await run_in_threadpool(identity.get_team, org_id, team_id)
        if team is None:
            raise _not_found_team(team_id)
        raise _not_found_member(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/api-keys",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    org_id: UUID,
    payload: CreateApiKeyRequest,
    keys: API_Key_Service = Depends(get_api_key_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_API_KEYS)),
) -> CreateApiKeyResponse:
    """Issue an org-scoped API key; return the plaintext secret **once** (Req 5.1, 5.2)."""
    _ensure_same_org(principal, org_id)
    key, secret = await run_in_threadpool(keys.create, org_id, payload.role)
    return CreateApiKeyResponse(
        api_key_id=key.id,
        secret=secret,
        role=key.role,
        key_prefix=key.key_prefix,
    )


@router.get("/orgs/{org_id}/api-keys", response_model=list[ApiKeyMetadata])
async def list_api_keys(
    org_id: UUID,
    keys: API_Key_Service = Depends(get_api_key_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_API_KEYS)),
) -> list[ApiKeyMetadata]:
    """Return metadata for every API key in ``org_id`` — never a hash or secret (Req 5.4)."""
    _ensure_same_org(principal, org_id)
    stored = await run_in_threadpool(keys.list, org_id)
    return [
        ApiKeyMetadata(
            id=k.id,
            org_id=k.org_id,
            role=k.role,
            key_prefix=k.key_prefix,
            revoked_at=k.revoked_at,
            created_at=k.created_at,
        )
        for k in stored
    ]


@router.delete(
    "/orgs/{org_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    org_id: UUID,
    key_id: UUID,
    keys: API_Key_Service = Depends(get_api_key_service),
    principal: Principal = Depends(require_permission(Permission.MANAGE_API_KEYS)),
) -> Response:
    """Revoke an API key; an unknown or cross-org key is a 404 (Req 5.5, 5.7)."""
    _ensure_same_org(principal, org_id)
    revoked = await run_in_threadpool(keys.revoke, org_id, key_id)
    if revoked is None:
        raise AppError(
            "not_found",
            "API key not found.",
            status.HTTP_404_NOT_FOUND,
            {"key_id": str(key_id)},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
