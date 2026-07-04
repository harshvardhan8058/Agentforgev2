"""Enterprise domain models: plain, framework-agnostic dataclasses.

Consistent with the Phase 3/4 domain models. **No model ever holds a plaintext password
or a plaintext API-key secret** — only the irreversible hash crosses the boundary
(Req 1.1, 5.2, 8.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from agentforge.enterprise.rbac import Permission, Role


@dataclass
class Organization:
    """A tenant that owns resources and contains Teams and Memberships (Req 2.1)."""

    id: UUID
    name: str
    created_at: datetime


@dataclass
class User:
    """A person with an identity, holding a hashed password credential (Req 1.1)."""

    id: UUID
    email: str  # UNIQUE
    password_hash: str  # argon2id; never plaintext (Req 1.1, 8.5)
    created_at: datetime


@dataclass
class Membership:
    """Associates a User with an Organization and carries the User's Role (Req 2.2)."""

    user_id: UUID
    org_id: UUID
    role: Role
    created_at: datetime
    # UNIQUE (user_id, org_id): at most one membership per (user, org) (Req 2.7).


@dataclass
class Team:
    """A named group within an Organization (Req 2.3)."""

    id: UUID
    org_id: UUID
    name: str
    created_at: datetime


@dataclass
class Team_Membership:
    """Associates a User with a Team within an Organization (Req 2.4)."""

    team_id: UUID
    user_id: UUID
    created_at: datetime
    # UNIQUE (team_id, user_id).


@dataclass
class API_Key:
    """An org-scoped credential for programmatic access; hashed at rest (Req 5.1, 5.2)."""

    id: UUID
    org_id: UUID
    role: Role
    key_prefix: str  # first chars of the secret, indexed for O(1) candidate lookup
    key_hash: str  # argon2id hash of the secret; never the plaintext (Req 5.2, 8.5)
    revoked_at: datetime | None  # None => active
    created_at: datetime


@dataclass(frozen=True)
class Access_Token_Claims:
    """The decoded, validated claims carried by an Access_Token (Req 1.2, 1.4)."""

    sub: UUID  # user_id
    org_id: UUID
    role: Role
    exp: int  # unix seconds


@dataclass(frozen=True)
class Principal:
    """The authenticated identity making a request (Req 1.4, 5.3).

    Resolved from either an Access_Token (``kind == "user"``) or an API_Key
    (``kind == "api_key"``). ``permissions`` is derived once from ``role`` via the
    ``RBAC_Policy`` so authorization checks never re-consult the store.
    """

    kind: Literal["user", "api_key"]
    user_id: UUID | None  # set iff kind == "user"
    key_id: UUID | None  # set iff kind == "api_key"
    org_id: UUID
    role: Role
    permissions: frozenset[Permission] = field(default_factory=frozenset)
