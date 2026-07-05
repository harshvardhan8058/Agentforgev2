"""Abstract prompt seam: ``Prompt_Store``.

The ``Prompt_Registry`` depends only on this contract. Every method is constrained by
``org_id`` so a cross-tenant lookup is structurally ``None``/empty (Req 4.8, 10.3).
``add_version`` is append-only (no update path), which — together with the DB
``UNIQUE (template_id, version)`` constraint — makes immutability and a contiguous
``1..N`` version sequence structural rather than conventional (Req 4.1, 4.2, 4.9, 8.6).
Concrete stores (``InMemory_Prompt_Store`` / ``Pg_Prompt_Store``) live in ``store.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from agentforge.observability.models import Prompt_Version


class Prompt_Store(ABC):
    """Persistence contract for immutable, org-scoped Prompt_Versions."""

    @abstractmethod
    def next_version_number(self, org_id: UUID, name: str) -> int:
        """Return ``max(version) + 1`` for ``(org_id, name)``, or ``1`` if none (Req 4.1)."""
        raise NotImplementedError

    @abstractmethod
    def add_version(self, version: Prompt_Version) -> Prompt_Version:
        """Append an immutable Prompt_Version and return it (append-only) (Req 4.2)."""
        raise NotImplementedError

    @abstractmethod
    def get_version(self, org_id: UUID, name: str, version: int) -> Prompt_Version | None:
        """Return the given version for ``(org_id, name)`` or ``None`` (Req 4.4, 4.8)."""
        raise NotImplementedError

    @abstractmethod
    def get_latest(self, org_id: UUID, name: str) -> Prompt_Version | None:
        """Return the highest-numbered version for ``(org_id, name)`` or ``None`` (Req 4.3)."""
        raise NotImplementedError

    @abstractmethod
    def list_versions(self, org_id: UUID, name: str) -> list[int]:
        """Return the version numbers for ``(org_id, name)`` in ascending order (Req 4.5)."""
        raise NotImplementedError

    @abstractmethod
    def list_template_names(self, org_id: UUID) -> list[str]:
        """Return every template name for ``org_id`` (ascending); never cross-org (Req 4.8)."""
        raise NotImplementedError
