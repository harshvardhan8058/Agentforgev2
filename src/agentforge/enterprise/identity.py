"""Identity_Store implementations: ``InMemory_Identity_Store`` + ``Pg_Identity_Store``.

Two implementations of the :class:`Identity_Store` seam ship (Task 4):

* :class:`InMemory_Identity_Store` — the dependency-free, keyless double used by the
  property/unit lanes and standalone runs. It keys its dicts by id/email and enforces the
  ``UNIQUE(user_id, org_id)`` membership and ``UNIQUE(org_id, name)`` team invariants and
  the ``add_team_member`` cross-org guard in process.
* :class:`Pg_Identity_Store` — the synchronous SQLAlchemy adapter mirroring
  ``PgConversation_Store``. It maps every ABC method onto the tables created by migration
  ``0006`` and re-enforces the same invariants at the SQL layer (unique constraints +
  the cross-org membership check).

No plaintext password ever crosses the boundary — only the irreversible ``password_hash``
(Req 1.1, 8.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import status
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from agentforge.api.errors import AppError
from agentforge.enterprise.base import Identity_Store
from agentforge.enterprise.models import (
    Membership,
    Organization,
    Team,
    Team_Membership,
    User,
)
from agentforge.enterprise.rbac import Role
from agentforge.vectorstore.pgvector_store import to_sync_dsn


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class InMemory_Identity_Store(Identity_Store):
    """Process-memory Identity_Store — keyless double for tests/standalone runs."""

    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}
        self._users_by_email: dict[str, UUID] = {}
        self._orgs: dict[UUID, Organization] = {}
        self._memberships: dict[tuple[UUID, UUID], Membership] = {}
        self._teams: dict[UUID, Team] = {}
        self._teams_by_org_name: dict[tuple[UUID, str], UUID] = {}
        self._team_memberships: dict[tuple[UUID, UUID], Team_Membership] = {}

    # --- users ---
    def create_user(self, email: str, password_hash: str) -> User:
        """Persist a User with a unique email (Req 1.1)."""
        if email in self._users_by_email:
            raise AppError(
                "email_exists",
                "A user with this email already exists.",
                status.HTTP_400_BAD_REQUEST,
                {"field": "email"},
            )
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            created_at=_utcnow(),
        )
        self._users[user.id] = user
        self._users_by_email[email] = user.id
        return user

    def get_user_by_email(self, email: str) -> User | None:
        """Return the User with ``email`` or ``None``."""
        user_id = self._users_by_email.get(email)
        return self._users.get(user_id) if user_id is not None else None

    def get_user(self, user_id: UUID) -> User | None:
        """Return the User with ``user_id`` or ``None``."""
        return self._users.get(user_id)

    # --- organizations ---
    def create_organization(self, name: str) -> Organization:
        """Persist an Organization with a unique Org_Id (Req 2.1)."""
        org = Organization(id=uuid.uuid4(), name=name, created_at=_utcnow())
        self._orgs[org.id] = org
        return org

    def get_organization(self, org_id: UUID) -> Organization | None:
        """Return the Organization with ``org_id`` or ``None``."""
        return self._orgs.get(org_id)

    # --- memberships (UNIQUE(user_id, org_id)) ---
    def add_membership(self, user_id: UUID, org_id: UUID, role: Role) -> Membership:
        """Associate a User with an Organization under a Role (Req 2.2, 2.7)."""
        key = (user_id, org_id)
        if key in self._memberships:
            raise AppError(
                "membership_exists",
                "The user already holds a membership in this organization.",
                status.HTTP_400_BAD_REQUEST,
                {"user_id": str(user_id), "org_id": str(org_id)},
            )
        membership = Membership(
            user_id=user_id, org_id=org_id, role=role, created_at=_utcnow()
        )
        self._memberships[key] = membership
        return membership

    def get_membership(self, user_id: UUID, org_id: UUID) -> Membership | None:
        """Return the User's Membership in ``org_id`` or ``None``."""
        return self._memberships.get((user_id, org_id))

    def list_org_members(self, org_id: UUID) -> list[Membership]:
        """Return every Membership scoped to ``org_id`` (Req 2.6)."""
        return [m for m in self._memberships.values() if m.org_id == org_id]

    def list_memberships_for_user(self, user_id: UUID) -> list[Membership]:
        """Return every Membership held by ``user_id``."""
        return [m for m in self._memberships.values() if m.user_id == user_id]

    # --- teams (org-scoped) + team memberships ---
    def create_team(self, org_id: UUID, name: str) -> Team:
        """Persist a Team associated with ``org_id`` (Req 2.3), unique per (org, name)."""
        if (org_id, name) in self._teams_by_org_name:
            raise AppError(
                "team_exists",
                "A team with this name already exists in the organization.",
                status.HTTP_400_BAD_REQUEST,
                {"org_id": str(org_id), "name": name},
            )
        team = Team(id=uuid.uuid4(), org_id=org_id, name=name, created_at=_utcnow())
        self._teams[team.id] = team
        self._teams_by_org_name[(org_id, name)] = team.id
        return team

    def add_team_member(self, team_id: UUID, user_id: UUID) -> Team_Membership:
        """Add a User to a Team; require a Membership in the Team's org (Req 2.4, 2.5)."""
        team = self._teams.get(team_id)
        if team is None:
            raise AppError(
                "not_found",
                "Team not found.",
                status.HTTP_404_NOT_FOUND,
                {"team_id": str(team_id)},
            )
        if (user_id, team.org_id) not in self._memberships:
            raise AppError(
                "org_mismatch",
                "The user holds no membership in the team's organization.",
                status.HTTP_400_BAD_REQUEST,
                {"required": "membership"},
            )
        membership = Team_Membership(
            team_id=team_id, user_id=user_id, created_at=_utcnow()
        )
        self._team_memberships[(team_id, user_id)] = membership
        return membership


def _to_sqlalchemy_sync_dsn(database_url: str) -> str:
    """Return a synchronous SQLAlchemy DSN (psycopg driver) for the given URL."""
    libpq = to_sync_dsn(database_url)  # strips +asyncpg / +psycopg -> postgresql://
    return libpq.replace("postgresql://", "postgresql+psycopg://", 1)


class Pg_Identity_Store(Identity_Store):
    """Synchronous Postgres-backed Identity_Store, mirroring ``PgConversation_Store``.

    Maps every ABC method onto the tables created by migration ``0006`` and re-enforces
    the ``UNIQUE(user_id, org_id)`` / ``UNIQUE(org_id, name)`` invariants and the
    ``add_team_member`` cross-org guard at the SQL layer.
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    # --- users ---
    def create_user(self, email: str, password_hash: str) -> User:
        """Persist a User with a unique email (Req 1.1)."""
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            created_at=_utcnow(),
        )
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash, created_at) "
                        "VALUES (:id, :email, :password_hash, :created_at)"
                    ),
                    {
                        "id": str(user.id),
                        "email": user.email,
                        "password_hash": user.password_hash,
                        "created_at": user.created_at,
                    },
                )
        except IntegrityError as exc:
            raise AppError(
                "email_exists",
                "A user with this email already exists.",
                status.HTTP_400_BAD_REQUEST,
                {"field": "email"},
            ) from exc
        return user

    def get_user_by_email(self, email: str) -> User | None:
        """Return the User with ``email`` or ``None``."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, email, password_hash, created_at FROM users "
                    "WHERE email = :email"
                ),
                {"email": email},
            ).first()
        return self._row_to_user(row) if row is not None else None

    def get_user(self, user_id: UUID) -> User | None:
        """Return the User with ``user_id`` or ``None``."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, email, password_hash, created_at FROM users "
                    "WHERE id = :id"
                ),
                {"id": str(user_id)},
            ).first()
        return self._row_to_user(row) if row is not None else None

    # --- organizations ---
    def create_organization(self, name: str) -> Organization:
        """Persist an Organization with a unique Org_Id (Req 2.1)."""
        org = Organization(id=uuid.uuid4(), name=name, created_at=_utcnow())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO organizations (id, name, created_at) "
                    "VALUES (:id, :name, :created_at)"
                ),
                {"id": str(org.id), "name": org.name, "created_at": org.created_at},
            )
        return org

    def get_organization(self, org_id: UUID) -> Organization | None:
        """Return the Organization with ``org_id`` or ``None``."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, name, created_at FROM organizations WHERE id = :id"),
                {"id": str(org_id)},
            ).first()
        if row is None:
            return None
        return Organization(id=UUID(str(row[0])), name=row[1], created_at=row[2])

    # --- memberships (UNIQUE(user_id, org_id)) ---
    def add_membership(self, user_id: UUID, org_id: UUID, role: Role) -> Membership:
        """Associate a User with an Organization under a Role (Req 2.2, 2.7)."""
        membership = Membership(
            user_id=user_id, org_id=org_id, role=role, created_at=_utcnow()
        )
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO memberships (user_id, org_id, role, created_at) "
                        "VALUES (:user_id, :org_id, :role, :created_at)"
                    ),
                    {
                        "user_id": str(user_id),
                        "org_id": str(org_id),
                        "role": role.value,
                        "created_at": membership.created_at,
                    },
                )
        except IntegrityError as exc:
            raise AppError(
                "membership_exists",
                "The user already holds a membership in this organization.",
                status.HTTP_400_BAD_REQUEST,
                {"user_id": str(user_id), "org_id": str(org_id)},
            ) from exc
        return membership

    def get_membership(self, user_id: UUID, org_id: UUID) -> Membership | None:
        """Return the User's Membership in ``org_id`` or ``None``."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT user_id, org_id, role, created_at FROM memberships "
                    "WHERE user_id = :user_id AND org_id = :org_id"
                ),
                {"user_id": str(user_id), "org_id": str(org_id)},
            ).first()
        return self._row_to_membership(row) if row is not None else None

    def list_org_members(self, org_id: UUID) -> list[Membership]:
        """Return every Membership scoped to ``org_id`` (Req 2.6)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT user_id, org_id, role, created_at FROM memberships "
                    "WHERE org_id = :org_id"
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [self._row_to_membership(r) for r in rows]

    def list_memberships_for_user(self, user_id: UUID) -> list[Membership]:
        """Return every Membership held by ``user_id``."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT user_id, org_id, role, created_at FROM memberships "
                    "WHERE user_id = :user_id ORDER BY created_at ASC"
                ),
                {"user_id": str(user_id)},
            ).fetchall()
        return [self._row_to_membership(r) for r in rows]

    # --- teams (org-scoped) + team memberships ---
    def create_team(self, org_id: UUID, name: str) -> Team:
        """Persist a Team associated with ``org_id`` (Req 2.3), unique per (org, name)."""
        team = Team(id=uuid.uuid4(), org_id=org_id, name=name, created_at=_utcnow())
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO teams (id, org_id, name, created_at) "
                        "VALUES (:id, :org_id, :name, :created_at)"
                    ),
                    {
                        "id": str(team.id),
                        "org_id": str(org_id),
                        "name": name,
                        "created_at": team.created_at,
                    },
                )
        except IntegrityError as exc:
            raise AppError(
                "team_exists",
                "A team with this name already exists in the organization.",
                status.HTTP_400_BAD_REQUEST,
                {"org_id": str(org_id), "name": name},
            ) from exc
        return team

    def add_team_member(self, team_id: UUID, user_id: UUID) -> Team_Membership:
        """Add a User to a Team; require a Membership in the Team's org (Req 2.4, 2.5)."""
        membership = Team_Membership(
            team_id=team_id, user_id=user_id, created_at=_utcnow()
        )
        with self._engine.begin() as conn:
            org_row = conn.execute(
                text("SELECT org_id FROM teams WHERE id = :id"),
                {"id": str(team_id)},
            ).first()
            if org_row is None:
                raise AppError(
                    "not_found",
                    "Team not found.",
                    status.HTTP_404_NOT_FOUND,
                    {"team_id": str(team_id)},
                )
            org_id = str(org_row[0])
            member_row = conn.execute(
                text(
                    "SELECT 1 FROM memberships "
                    "WHERE user_id = :user_id AND org_id = :org_id"
                ),
                {"user_id": str(user_id), "org_id": org_id},
            ).first()
            if member_row is None:
                raise AppError(
                    "org_mismatch",
                    "The user holds no membership in the team's organization.",
                    status.HTTP_400_BAD_REQUEST,
                    {"required": "membership"},
                )
            conn.execute(
                text(
                    "INSERT INTO team_memberships (team_id, user_id, created_at) "
                    "VALUES (:team_id, :user_id, :created_at) "
                    "ON CONFLICT (team_id, user_id) DO NOTHING"
                ),
                {
                    "team_id": str(team_id),
                    "user_id": str(user_id),
                    "created_at": membership.created_at,
                },
            )
        return membership

    # --- row mappers ---
    @staticmethod
    def _row_to_user(row) -> User:
        return User(
            id=UUID(str(row[0])),
            email=row[1],
            password_hash=row[2],
            created_at=row[3],
        )

    @staticmethod
    def _row_to_membership(row) -> Membership:
        return Membership(
            user_id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            role=Role(row[2]),
            created_at=row[3],
        )
