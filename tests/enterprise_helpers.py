"""Shared keyless enterprise-auth helpers for the test suite.

Phase 5 makes every existing endpoint require authentication and scopes every
tenant-owned resource to an organization. These helpers build a fully **keyless**
:class:`EnterpriseContext` — an in-memory Identity_Store + API-key store, a ``NoOp``
rate limiter (selected because no Redis client is supplied), and a dev-generated
``jwt_secret`` from a local-profile ``Settings`` — register an org + user with a role,
issue a JWT, and return the ``Authorization`` header plus the ``org_id`` so a
``TestClient`` can authenticate every request as that principal.

Existing ``TestClient`` fixtures use :func:`install_enterprise_auth` to inject the
context onto ``app.state`` and obtain default auth headers; tenant-owned resources they
create through the API are automatically scoped to the returned ``org_id``.
"""

from __future__ import annotations

from uuid import UUID

from agentforge.config.container import EnterpriseContext, build_enterprise_context
from agentforge.config.settings import Settings
from agentforge.enterprise.rbac import Role


def install_enterprise_auth(
    app,
    settings: Settings,
    *,
    role: Role = Role.OWNER,
    org_name: str = "Test Org",
    email: str = "user@example.com",
    password: str = "correct horse battery staple",
) -> tuple[dict[str, str], UUID, EnterpriseContext]:
    """Wire a keyless enterprise context onto ``app`` and return ``(headers, org_id, ctx)``.

    Registers one Organization and one User holding ``role`` in it, issues a JWT for that
    principal, assigns the context to ``app.state.enterprise_context``, and returns the
    Bearer ``Authorization`` header, the ``org_id`` the principal is scoped to, and the
    context itself (so a test can register additional orgs/users for cross-tenant cases).
    """
    ctx = build_enterprise_context(settings, redis=None)
    headers, org_id = issue_principal_headers(
        ctx, role=role, org_name=org_name, email=email, password=password
    )
    app.state.enterprise_context = ctx
    return headers, org_id, ctx


def issue_principal_headers(
    ctx: EnterpriseContext,
    *,
    role: Role = Role.OWNER,
    org_name: str = "Test Org",
    email: str = "user@example.com",
    password: str = "correct horse battery staple",
) -> tuple[dict[str, str], UUID]:
    """Register an org + user with ``role`` in ``ctx`` and return ``(headers, org_id)``."""
    org = ctx.identity_store.create_organization(org_name)
    user = ctx.identity_store.create_user(email, ctx.auth_service.hash_password(password))
    ctx.identity_store.add_membership(user.id, org.id, role)
    token = ctx.auth_service.issue(user.id, org.id, role)
    return {"Authorization": f"Bearer {token}"}, org.id
