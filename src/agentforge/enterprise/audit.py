"""Audit_Log implementations and the Audit_Service that writes to them.

An audit trail is the enterprise capability the platform was missing outright: usage records
answered "what did this cost", traces answered "what did the agent do", and nothing answered
**"who changed this, and when"** — the question every compliance review, incident
postmortem, and "why did my access disappear" support ticket starts with. A logger line was
not enough: it is not queryable per tenant, not retained with the data it describes, and not
visible to the customer who owns the organization.

Design decisions worth stating, because each one is a trade-off:

* **Append-only vocabulary.** :class:`Audit_Action` is a closed set of dotted, past-tense
  names. It is published through the API (so the console's filter is generated from the
  contract rather than hardcoded), and adding an action is an application change, never a
  migration.
* **Never a credential, never free-form nesting.** ``metadata`` accepts only non-secret
  scalars, admitted by :func:`admit_metadata` before the write. The row records *that* an
  API key was created — never its secret. This mirrors the integration-connection admission
  policy, for the same reason: a free-form JSON column is exactly where a token ends up.
* **Actor identity is stored as an id, resolved to a label on read.** Emails are immutable
  in this system, so a read-time batch lookup is equivalent to denormalising a label, one
  fewer write-path store call, and it keeps the audit row minimal. A deleted user's events
  survive with an unresolvable actor rather than being erased or reattributed.
* **Recording must not break the audited action, unless the operator says otherwise.** By
  default a failed audit write is logged as an error and the request succeeds: an audit
  store outage must not become a platform outage. A regulated deployment can set
  ``audit_log_required=true`` to fail closed instead, which is the honest way to offer both
  postures rather than choosing one for everybody.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Final
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.enterprise.base import Audit_Log
from agentforge.enterprise.models import Audit_Event, Principal

logger = logging.getLogger(__name__)


class Audit_Action(str, Enum):
    """The closed vocabulary of audited administrative actions.

    Dotted ``subject.verb`` in the past tense. A ``str`` enum so it serialises as its value
    in the API contract (and therefore reaches the generated client as a union type), while
    still being a single authoritative list on the server.
    """

    ORG_CREATED = "org.created"

    MEMBER_ADDED = "member.added"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"

    TEAM_CREATED = "team.created"
    TEAM_DELETED = "team.deleted"
    TEAM_MEMBER_ADDED = "team_member.added"
    TEAM_MEMBER_REMOVED = "team_member.removed"

    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"

    INTEGRATION_CONNECTION_CREATED = "integration_connection.created"
    INTEGRATION_CONNECTION_UPDATED = "integration_connection.updated"
    INTEGRATION_CONNECTION_DELETED = "integration_connection.deleted"


# --- metadata admission -----------------------------------------------------------

# Substrings that make a metadata KEY inadmissible. An audit row is read by more people
# than any other record (every admin, and every auditor a customer invites), so the bar for
# what may be attached to one is higher than for ordinary configuration.
_CREDENTIAL_KEY_MARKERS: Final[tuple[str, ...]] = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "bearer",
    "signature",
    "hash",
)

MAX_METADATA_KEYS: Final[int] = 12
MAX_METADATA_VALUE_LENGTH: Final[int] = 256

_SCALARS: Final[tuple[type, ...]] = (str, int, float, bool, type(None))


def admit_metadata(metadata: dict | None) -> dict[str, object]:
    """Return metadata safe to persist on an audit row, or raise ``ValueError``.

    Total over its input space: any mapping either returns a copy of itself that holds only
    non-credential-named scalars within the size bounds, or raises. Callers are internal
    (the routers that record events), so a violation is a programming error worth failing
    on rather than silently dropping — every call site is covered by a test.
    """
    admitted: dict[str, object] = dict(metadata or {})
    if len(admitted) > MAX_METADATA_KEYS:
        raise ValueError(
            f"audit metadata holds {len(admitted)} keys; at most {MAX_METADATA_KEYS} allowed"
        )
    for key, value in admitted.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("audit metadata keys must be non-empty strings")
        lowered = key.lower()
        if any(marker in lowered for marker in _CREDENTIAL_KEY_MARKERS):
            raise ValueError(
                f"audit metadata key {key!r} names a credential; an audit row records that "
                "something happened, never the secret involved"
            )
        if not isinstance(value, _SCALARS):
            raise ValueError(
                f"audit metadata value for {key!r} must be a scalar "
                "(string, number, boolean, or null)"
            )
        if isinstance(value, str) and len(value) > MAX_METADATA_VALUE_LENGTH:
            raise ValueError(
                f"audit metadata value for {key!r} exceeds "
                f"{MAX_METADATA_VALUE_LENGTH} characters"
            )
    return admitted


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- the service ------------------------------------------------------------------


class Audit_Service:
    """Records audited actions for the acting Principal.

    Sits between the routers and the :class:`Audit_Log` so a call site names *what
    happened* and nothing else: the actor is derived from the Principal, the tenant from
    ``principal.org_id``, and the failure posture from configuration.
    """

    def __init__(self, log: Audit_Log, *, required: bool = False) -> None:
        self._log = log
        self._required = required

    @property
    def required(self) -> bool:
        """True when a failed audit write must fail the audited request (fail closed)."""
        return self._required

    def record(
        self,
        principal: Principal,
        action: Audit_Action,
        *,
        target_type: str,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> Audit_Event | None:
        """Append an audit event for ``principal``'s action; return it, or None on failure.

        Never raises unless ``required`` is set, in which case the underlying error
        propagates so the caller's transaction/request fails visibly. The tenant is always
        ``principal.org_id`` — an audit event cannot be written into another tenant's trail
        because there is no parameter for it.
        """
        event = Audit_Event(
            id=uuid.uuid4(),
            org_id=principal.org_id,
            actor_kind=principal.kind,
            actor_user_id=principal.user_id,
            actor_key_id=principal.key_id,
            action=action.value,
            target_type=target_type,
            target_id=target_id,
            metadata=admit_metadata(metadata),
            created_at=_utcnow(),
        )
        try:
            return self._log.record(event)
        except Exception:
            if self._required:
                # Fail closed: the operator has declared that an unrecorded action is worse
                # than a failed one.
                raise
            # Fail open, but loudly: ERROR (not warning) because a gap in an audit trail is
            # a compliance problem even when the product kept working.
            logger.error(
                "Failed to record audit event %s for org %s; the action itself succeeded.",
                action.value,
                principal.org_id,
                exc_info=True,
            )
            return None


# --- stores -----------------------------------------------------------------------


class InMemory_Audit_Log(Audit_Log):
    """Keyless/test Audit_Log. Filters every read by ``org_id`` (Req 4.3, 4.4)."""

    def __init__(self) -> None:
        self._events: list[Audit_Event] = []

    def record(self, event: Audit_Event) -> Audit_Event:
        self._events.append(event)
        return event

    def list_for_org(
        self,
        org_id: UUID,
        *,
        actions: list[str] | None = None,
        actor_user_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[Audit_Event]:
        """Return ``org_id``'s events, newest first, matching every supplied filter."""
        selected = [
            event
            for event in self._events
            if event.org_id == org_id
            and (not actions or event.action in actions)
            and (actor_user_id is None or event.actor_user_id == actor_user_id)
            and (start is None or event.created_at >= start)
            and (end is None or event.created_at <= end)
        ]
        # Newest first, with the id as a stable tie-break so equal timestamps (entirely
        # possible for two writes in one request) never order arbitrarily.
        selected.sort(key=lambda e: (e.created_at, str(e.id)), reverse=True)
        return selected[:limit]


class Pg_Audit_Log(Audit_Log):
    """Postgres-backed Audit_Log over the ``audit_events`` table (migration 0013).

    Synchronous SQLAlchemy, mirroring the other ``Pg_*`` stores; every statement is scoped
    by ``org_id`` in SQL, so a cross-tenant read matches zero rows rather than being
    filtered afterwards (Req 4.3).
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def record(self, event: Audit_Event) -> Audit_Event:
        import json

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO audit_events
                        (id, org_id, actor_kind, actor_user_id, actor_key_id, action,
                         target_type, target_id, metadata, created_at)
                    VALUES
                        (:id, :org_id, :actor_kind, :actor_user_id, :actor_key_id, :action,
                         :target_type, :target_id, CAST(:metadata AS JSONB), :created_at)
                    """
                ),
                {
                    "id": str(event.id),
                    "org_id": str(event.org_id),
                    "actor_kind": event.actor_kind,
                    "actor_user_id": (
                        str(event.actor_user_id) if event.actor_user_id else None
                    ),
                    "actor_key_id": (
                        str(event.actor_key_id) if event.actor_key_id else None
                    ),
                    "action": event.action,
                    "target_type": event.target_type,
                    "target_id": event.target_id,
                    "metadata": json.dumps(event.metadata),
                    "created_at": event.created_at,
                },
            )
        return event

    def list_for_org(
        self,
        org_id: UUID,
        *,
        actions: list[str] | None = None,
        actor_user_id: UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[Audit_Event]:
        """Return ``org_id``'s events, newest first, matching every supplied filter.

        Filters are composed into one statement with bound parameters (never string
        interpolation), and the ``ORDER BY`` matches the ``(org_id, created_at DESC, id
        DESC)`` index so the newest page is an index scan rather than a sort.
        """
        clauses = ["org_id = :org_id"]
        params: dict[str, object] = {"org_id": str(org_id), "limit": limit}
        if actions:
            clauses.append("action = ANY(CAST(:actions AS text[]))")
            params["actions"] = list(actions)
        if actor_user_id is not None:
            clauses.append("actor_user_id = :actor_user_id")
            params["actor_user_id"] = str(actor_user_id)
        if start is not None:
            clauses.append("created_at >= :start")
            params["start"] = start
        if end is not None:
            clauses.append("created_at <= :end")
            params["end"] = end

        sql = (
            "SELECT id, org_id, actor_kind, actor_user_id, actor_key_id, action, "
            "target_type, target_id, metadata, created_at FROM audit_events "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row) -> Audit_Event:
        metadata = row[8]
        if isinstance(metadata, str):  # pragma: no cover - driver-dependent
            import json

            metadata = json.loads(metadata)
        return Audit_Event(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            actor_kind=row[2],
            actor_user_id=UUID(str(row[3])) if row[3] is not None else None,
            actor_key_id=UUID(str(row[4])) if row[4] is not None else None,
            action=row[5],
            target_type=row[6],
            target_id=row[7],
            metadata=dict(metadata or {}),
            created_at=row[9],
        )
