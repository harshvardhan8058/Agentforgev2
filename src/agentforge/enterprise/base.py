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
from uuid import UUID

from agentforge.enterprise.models import (
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

    # --- teams (org-scoped) + team memberships ---
    @abstractmethod
    def create_team(self, org_id: UUID, name: str) -> Team:
        """Persist a Team associated with ``org_id`` (Req 2.3)."""
        raise NotImplementedError

    @abstractmethod
    def add_team_member(self, team_id: UUID, user_id: UUID) -> Team_Membership:
        """Add a User to a Team, requiring a Membership in the Team's org.

        Raises ``AppError("org_mismatch", 400)`` when the User holds no Membership in
        the Team's Organization (Req 2.5).
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


class Rate_Limiter(ABC):
    """Per-principal request limiter contract (Req 6.1)."""

    @abstractmethod
    def check(self, principal_key: str) -> None:
        """Count a request for ``principal_key``; raise on overflow.

        Raises ``AppError("rate_limited", 429)`` when the Principal has exceeded
        Rate_Limit_Max within the current Rate_Limit_Window (Req 6.3).
        """
        raise NotImplementedError
