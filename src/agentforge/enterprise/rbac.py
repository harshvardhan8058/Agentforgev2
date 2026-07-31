"""RBAC_Policy: the static Role -> Permission map and its pure authorization function.

The policy is a pure function of the :data:`ROLE_PERMISSIONS` mapping. Endpoints declare
``require_permission(Permission.X)`` and never touch the map, so adding a new Role or
Permission is a **single-file edit** here and requires no endpoint changes (Req 3.6).

The mapping is constructed so the permission sets nest strictly
``viewer ⊆ member ⊆ admin ⊆ owner`` and every Role grants :attr:`Permission.READ`
(Req 3.2, 3.5).

Adding a Permission here is intentionally the whole change: ``frontend/src/auth/rbac.ts``
mirrors this map for UI gating, and the two are kept honest by the frontend's own
nesting/READ properties plus the fact that the client can only ever hide affordances the
server would refuse anyway.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """A named set of Permissions assigned to a Membership or API_Key."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(str, Enum):
    """A named capability that authorizes an Action."""

    MANAGE_MEMBERS = "manage_members"
    MANAGE_API_KEYS = "manage_api_keys"
    MANAGE_INTEGRATIONS = "manage_integrations"
    READ_AUDIT_LOG = "read_audit_log"
    MANAGE_BUDGET = "manage_budget"
    INGEST_DOCUMENTS = "ingest_documents"
    RUN_AGENTS = "run_agents"
    READ = "read"


# Static role -> permission map. Sets nest viewer ⊆ member ⊆ admin ⊆ owner and every
# role includes READ (Req 3.1, 3.2, 3.5). Built incrementally so the nesting is explicit
# and cannot silently drift.
_VIEWER: frozenset[Permission] = frozenset({Permission.READ})
_MEMBER: frozenset[Permission] = _VIEWER | {
    Permission.RUN_AGENTS,
    Permission.INGEST_DOCUMENTS,
}
# Integration connection configuration is administrative deployment-shaped work, granted
# alongside API-key management: both configure how the org reaches the outside world, and
# neither can disclose a credential (integration config is non-secret by construction).
_ADMIN: frozenset[Permission] = _MEMBER | {
    Permission.MANAGE_API_KEYS,
    Permission.MANAGE_INTEGRATIONS,
}
# Setting a spend ceiling is OWNER-only for the same reason as the audit trail: it is a
# financial control, and the role that owns the organization is the one that owns its budget.
# READING the budget needs only `read` — a member who is about to be blocked should be able to
# see why, and the numbers are the same ones /analytics/usage already shows them.
#
# Reading the audit trail is OWNER-only, deliberately matching the roster it exposes: the
# trail's member events carry emails and role assignments, and `GET /orgs/{id}/members` is
# gated on `manage_members`, which only an owner holds. Granting trail access to admins would
# have handed them, through a side door, exactly the roster the direct endpoint withholds.
_OWNER: frozenset[Permission] = _ADMIN | {Permission.MANAGE_MEMBERS, Permission.READ_AUDIT_LOG, Permission.MANAGE_BUDGET}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.MEMBER: _MEMBER,
    Role.ADMIN: _ADMIN,
    Role.OWNER: _OWNER,
}


class RBAC_Policy:
    """Maps Roles to Permissions and decides authorization as a pure function."""

    def is_authorized(self, role: Role, permission: Permission) -> bool:
        """Return True iff ``permission`` is granted by ``role`` (Req 3.3)."""
        return permission in ROLE_PERMISSIONS[role]

    def permissions_for(self, role: Role) -> frozenset[Permission]:
        """Return the immutable set of Permissions granted to ``role``."""
        return ROLE_PERMISSIONS[role]
