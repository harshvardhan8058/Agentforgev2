"""Auth router: self-registration, login, and token refresh (Task 11).

All three endpoints are **anonymous** — they carry no ``Depends(get_current_principal)``
because they exist to *establish* a principal (or renew its token). They render every
error through the existing uniform envelope (Req 9.1):

* ``POST /auth/register-self`` bootstraps a new Organization and an owner User, then
  returns a freshly-issued Access_Token. A weak password or a duplicate email is rejected
  with ``AppError("validation_error", 400)`` naming the failing field; the argon2 hash is
  never computed on the duplicate-email branch (Req 1.1).
* ``POST /auth/login`` verifies credentials and returns a token; an unknown email or a
  wrong password yields ``AppError("auth_failed", 401)`` (Req 1.2, 1.3).
* ``POST /auth/refresh`` re-issues a token from a still-valid, non-expired bearer token;
  an invalid or expired token yields ``AppError("unauthorized", 401)`` (Req 1.5).

The Identity_Store and Auth_Service are synchronous, so their calls run in a worker
thread to avoid blocking the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_auth_service, get_enterprise_context
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    LoginRequest,
    RegisterSelfRequest,
    TokenResponse,
)
from agentforge.config.container import EnterpriseContext
from agentforge.enterprise.auth import Auth_Service
from agentforge.enterprise.rbac import Role

router = APIRouter(tags=["auth"])

# Minimum acceptable password length; a shorter password is rejected before hashing.
MIN_PASSWORD_LENGTH = 8


def _extract_bearer(request: Request) -> str | None:
    """Return the token from an ``Authorization: Bearer <jwt>`` header, else ``None``."""
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


@router.post(
    "/auth/register-self",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_self(
    payload: RegisterSelfRequest,
    ctx: EnterpriseContext = Depends(get_enterprise_context),
) -> TokenResponse:
    """Create an Organization + owner User and return an Access_Token (Req 1.1, 1.2).

    Validates password strength and email uniqueness first; the duplicate-email branch
    returns before any hash is computed.
    """
    if len(payload.password) < MIN_PASSWORD_LENGTH:
        raise AppError(
            "validation_error",
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            status.HTTP_400_BAD_REQUEST,
            {"field": "password"},
        )

    identity = ctx.identity_store
    auth = ctx.auth_service

    # Reject a duplicate email *before* computing an argon2 hash (Req 1.1 error branch).
    existing = await run_in_threadpool(identity.get_user_by_email, payload.email)
    if existing is not None:
        raise AppError(
            "validation_error",
            "A user with this email already exists.",
            status.HTTP_400_BAD_REQUEST,
            {"field": "email"},
        )

    org = await run_in_threadpool(identity.create_organization, payload.org_name)
    user = await run_in_threadpool(
        auth.register, payload.email, payload.password, org.id, Role.OWNER
    )
    token = await run_in_threadpool(auth.issue, user.id, org.id, Role.OWNER)
    return TokenResponse(access_token=token)


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    auth: Auth_Service = Depends(get_auth_service),
) -> TokenResponse:
    """Verify credentials and return a bearer Access_Token (Req 1.2, 1.3).

    An unknown email or a password mismatch raises ``AppError("auth_failed", 401)``.
    """
    token = await run_in_threadpool(auth.login, payload.email, payload.password)
    return TokenResponse(access_token=token)


@router.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    auth: Auth_Service = Depends(get_auth_service),
) -> TokenResponse:
    """Re-issue a token from a still-valid, non-expired bearer token (Req 1.5).

    An absent, malformed, wrong-secret, or expired token yields 401 — the same uniform
    ``unauthorized`` envelope produced by the Principal_Dependency.
    """
    token = _extract_bearer(request)
    claims = auth.verify(token) if token is not None else None
    if claims is None:
        raise AppError(
            "unauthorized",
            "Authentication is required.",
            status.HTTP_401_UNAUTHORIZED,
        )
    fresh = await run_in_threadpool(auth.issue, claims.sub, claims.org_id, claims.role)
    return TokenResponse(access_token=fresh)
