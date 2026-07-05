"""Abstract usage seams: ``Usage_Sink`` and ``Usage_Store``.

The ``Instrumented_Provider`` forwards usage through the ``Usage_Sink`` (wired via the
composition root); the ``Usage_Recorder`` persists ``Usage_Record``s through the
``Usage_Store``. Both are constrained by ``org_id`` at the data-access layer so a
cross-org read is structurally empty (Req 2.3, 3.3, 10.3). Concrete implementations
(``Recording_Usage_Sink`` / ``NoOp_Usage_Sink`` / ``InMemory_Usage_Store`` /
``Pg_Usage_Store``) live in sibling modules and are named only by the composition root.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from agentforge.observability.models import Token_Count, Usage_Record


class Usage_Sink(ABC):
    """Seam the Instrumented_Provider forwards usage through (Req 2.1, 7.2)."""

    @abstractmethod
    def record(
        self,
        *,
        provider: str,
        model: str,
        tokens: Token_Count,
        org_id: UUID,
        user_id: UUID | None,
    ) -> None:
        """Forward usage for a single LLM_Provider call to the Usage_Recorder."""
        raise NotImplementedError


class Usage_Store(ABC):
    """Persistence seam for Usage_Records, scoped by ``org_id`` (Req 2.3, 10.3)."""

    @abstractmethod
    def add(self, record: Usage_Record) -> Usage_Record:
        """Persist a Usage_Record (scoped to its ``org_id``) and return it (Req 2.3)."""
        raise NotImplementedError

    @abstractmethod
    def list_for_org(
        self, org_id: UUID, *, start: datetime, end: datetime
    ) -> list[Usage_Record]:
        """Return ``org_id``'s Usage_Records within ``[start, end]``; never cross-org (Req 3.3)."""
        raise NotImplementedError
