"""Abstract enterprise seams: ``Identity_Store``, ``API_Key_Store``, ``Rate_Limiter``.

The enterprise core (``Auth_Service``, ``API_Key_Service``, the FastAPI dependencies)
depends only on these contracts — never on a concrete store or limiter. Concrete
implementations (``InMemory_*`` / ``Pg_*`` / ``Redis_*`` / ``NoOp_*``) live in sibling
modules and are named only by the composition root, so a new identity backend, key
backend, or rate-limit backend drops in without touching the core (Req 9.5, 9.6).

No plaintext password or plaintext API-key secret ever crosses these boundaries — only
the irreversible ``password_hash`` / ``key_hash`` (Req 1.1, 5.2, 8.5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from agentforge.enterprise.models import (
    Audit_Event,
    API_Key,
    Membership,
    Organization,
    Team,
    Team_Membership,
    User,
)
from agentforge.enterprise.rbac import Role


class Identity_Store(ABC):
    """Persistence contract for Users, Organizations, Teams, and Memberships."""

    # --- users ---
    @abstractmethod
    def create_user(self, email: str, password_hash: str) -> User:
        """Persist a User with a unique email and the given Password_Hash (Req 1.1)."""
        raise NotImplementedError

    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None:
        """Return the User with ``email`` or ``None`` if no such User exists."""
        raise NotImplementedError

    @abstractmethod
    def get_user(self, user_id: UUID) -> User | None:
        """Return the User with ``user_id`` or ``None`` if no such User exists."""
        raise NotImplementedError

    @abstractmethod
    def list_users_by_ids(self, user_ids: Sequence[UUID]) -> list[User]:
        """Return the Users whose ids appear in ``user_ids`` (unknown ids are skipped).

        Exists so a caller resolving a *set* of memberships to display names issues one
        store call instead of one per row. Ordering is unspecified; callers that need a
        particular order index the result by ``User.id``.
        """
        raise NotImplementedError

    # --- organizations ---
    @abstractmethod
    def create_organization(self, name: str) -> Organization:
        """Persist an Organization with a unique Org_Id and return it (Req 2.1)."""
        raise NotImplementedError

    @abstractmethod
    def get_organization(self, org_id: UUID) -> Organization | None:
        """Return the Organization with ``org_id`` or ``None`` if absent."""
        raise NotImplementedError

    # --- memberships (UNIQUE(user_id, org_id)) ---
    @abstractmethod
    def add_membership(self, user_id: UUID, org_id: UUID, role: Role) -> Membership:
        """Associate a User with an Organization under a Role (Req 2.2, 2.7)."""
        raise NotImplementedError

    @abstractmethod
    def get_membership(self, user_id: UUID, org_id: UUID) -> Membership | None:
        """Return the User's Membership in ``org_id`` or ``None`` if absent."""
        raise NotImplementedError

    @abstractmethod
    def list_org_members(self, org_id: UUID) -> list[Membership]:
        """Return every Membership scoped to ``org_id`` (Req 2.6)."""
        raise NotImplementedError

    @abstractmethod
    def list_memberships_for_user(self, user_id: UUID) -> list[Membership]:
        """Return every Membership held by ``user_id`` (used by ``Auth_Service.login``)."""
        raise NotImplementedError

    @abstractmethod
    def update_membership_role(
        self, user_id: UUID, org_id: UUID, role: Role
    ) -> Membership | None:
        """Set the Role on an existing Membership; return it, or ``None`` if absent.

        ``None`` (rather than an error) so the transport layer maps an unknown member —
        including a member of a *different* organization — to the same uniform 404 and
        never discloses existence across tenants (Req 4.3, 5.7).

        Raises ``AppError("last_owner", 400)`` when the change would leave ``org_id``
        with no Membership holding :attr:`Role.OWNER`: an Organization must always
        retain at least one principal that can administer it.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_membership(self, user_id: UUID, org_id: UUID) -> bool:
        """Remove a Membership (and the User's Team_Memberships within ``org_id``).

        Returns ``True`` when a Membership was removed and ``False`` when none existed,
        so an unknown or cross-tenant member is the uniform 404 (Req 4.3, 5.7). Team
        memberships inside ``org_id`` are removed with it, because a Team_Membership may
        only exist for a User holding a Membership in the Team's Organization (Req 2.5).

        Raises ``AppError("last_owner", 400)`` when the removal would leave ``org_id``
        with no Membership holding :attr:`Role.OWNER`.
        """
        raise NotImplementedError

    # --- teams (org-scoped) + team memberships ---
    @abstractmethod
    def create_team(self, org_id: UUID, name: str) -> Team:
        """Persist a Team associated with ``org_id`` (Req 2.3)."""
        raise NotImplementedError

    @abstractmethod
    def get_team(self, org_id: UUID, team_id: UUID) -> Team | None:
        """Return the Team ``team_id`` iff it belongs to ``org_id``, else ``None``.

        ``org_id`` is part of the query, so a Team owned by another tenant is
        structurally invisible rather than filtered after the fact (Req 4.3, 5.7).
        """
        raise NotImplementedError

    @abstractmethod
    def list_teams(self, org_id: UUID) -> list[Team]:
        """Return every Team scoped to ``org_id``, oldest first (Req 2.3, 4.4)."""
        raise NotImplementedError

    @abstractmethod
    def delete_team(self, org_id: UUID, team_id: UUID) -> bool:
        """Delete the Team ``team_id`` iff it belongs to ``org_id``, with its memberships.

        Returns ``True`` when a Team was deleted, ``False`` when none matched, so an
        unknown or cross-tenant Team is the uniform 404 (Req 4.3, 5.7).
        """
        raise NotImplementedError

    @abstractmethod
    def add_team_member(self, team_id: UUID, user_id: UUID) -> Team_Membership:
        """Add a User to a Team, requiring a Membership in the Team's org.

        Raises ``AppError("org_mismatch", 400)`` when the User holds no Membership in
        the Team's Organization (Req 2.5).
        """
        raise NotImplementedError

    @abstractmethod
    def list_team_members(self, org_id: UUID, team_id: UUID) -> list[Team_Membership]:
        """Return the Team_Memberships of ``team_id`` iff it belongs to ``org_id``.

        A Team owned by another tenant yields an empty list, never another tenant's rows
        (Req 4.3, 5.7). Ordered oldest first for a stable presentation.
        """
        raise NotImplementedError

    @abstractmethod
    def remove_team_member(self, org_id: UUID, team_id: UUID, user_id: UUID) -> bool:
        """Remove a User from a Team iff the Team belongs to ``org_id``.

        Returns ``True`` when a Team_Membership was removed and ``False`` otherwise, so
        an unknown or cross-tenant target is the uniform 404 (Req 4.3, 5.7).
        """
        raise NotImplementedError


class API_Key_Store(ABC):
    """Persistence contract for organization-scoped API keys.

    All ``*_for_org`` methods filter by ``org_id`` in the store's own query, so
    cross-org access is structurally ``None``/empty — never a leak (Req 5.7).
    """

    @abstractmethod
    def create(self, api_key: API_Key) -> API_Key:
        """Persist an API_Key row (only the hash, never the secret) and return it."""
        raise NotImplementedError

    @abstractmethod
    def list_active_by_prefix(self, prefix: str) -> list[API_Key]:
        """Return active (non-revoked) keys whose ``key_prefix`` equals ``prefix``."""
        raise NotImplementedError

    @abstractmethod
    def list_for_org(self, org_id: UUID) -> list[API_Key]:
        """Return every API_Key scoped to ``org_id`` (metadata only at the router)."""
        raise NotImplementedError

    @abstractmethod
    def get_for_org(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Return the API_Key ``key_id`` iff it belongs to ``org_id`` (Req 5.7)."""
        raise NotImplementedError

    @abstractmethod
    def revoke_for_org(self, org_id: UUID, key_id: UUID) -> API_Key | None:
        """Mark ``key_id`` revoked iff it belongs to ``org_id``; else ``None`` (Req 5.5, 5.7)."""
        raise NotImplementedError


class Audit_Log(ABC):
    """Append-only, org-scoped store of administrative :class:`Audit_Event`s.

    Deliberately has **no update or delete**: an audit trail that can be edited answers no
    compliance question. Rows leave only with the organization they describe (the ``org_id``
    foreign key cascades), so a tenant deletion still removes them.

    Every read takes ``org_id`` as a query parameter, so another tenant's trail is
    structurally unreachable rather than filtered afterwards (Req 4.3, 4.4).
    """

    @abstractmethod
    def record(self, event: Audit_Event) -> Audit_Event:
        """Append ``event`` and return it. Raises on failure; the caller decides the posture.

        Implementations must not swallow errors: whether a failed audit write should fail the
        audited request is a *deployment* decision, made once in ``Audit_Service`` from
        configuration, not silently in a store.
        """
        raise NotImplementedError

    @abstractmethod
    def list_for_org(
        self,
        org_id: UUID,
        *,
        actions: list[str] | None = None,
        actor_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        before: tuple[datetime, UUID] | None = None,
        limit: int = 50,
    ) -> list[Audit_Event]:
        """Return ``org_id``'s events, **newest first**, matching every supplied filter.

        Newest-first because the question an audit trail answers is almost always "what
        changed recently". ``limit`` bounds the page and ``before`` is a keyset cursor: the
        ``(created_at, id)`` pair of the last row of the previous page. The pair — rather than
        the timestamp alone — is what makes a boundary unable to repeat or skip a row when
        several events share a timestamp, which two writes in one request always do.

        ``actor_id`` matches a user **or** a key actor, because the transport layer reports
        one actor id per row and a filter must accept what it reported.
        """
        raise NotImplementedError


class Rate_Limiter(ABC):
    """Per-principal request limiter contract (Req 6.1)."""

    @abstractmethod
    def check(self, principal_key: str) -> None:
        """Count a request for ``principal_key``; raise on overflow.

        Raises ``AppError("rate_limited", 429)`` when the Principal has exceeded
        Rate_Limit_Max within the current Rate_Limit_Window (Req 6.3).
        """
        raise NotImplementedError
