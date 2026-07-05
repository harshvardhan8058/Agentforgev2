"""Abstract evaluation seams: ``Evaluator`` and ``Evaluation_Store``.

An ``Evaluator`` is a deterministic scoring function of ``(input, expected, actual)``
(Req 6.3). The ``Evaluation_Store`` persists datasets, items, runs, and per-item results,
every method constrained by ``org_id`` so cross-tenant access is structurally empty
(Req 6.1, 6.5, 6.8, 10.3). Concrete evaluators / stores live in sibling modules and are
named only by the composition root.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from agentforge.observability.models import (
    Evaluation_Dataset,
    Evaluation_Item,
    Evaluation_Run,
)


class Evaluator(ABC):
    """Abstract deterministic scoring function over (input, expected, actual)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for this evaluator."""
        raise NotImplementedError

    @abstractmethod
    def score(self, *, input: str, expected: str | None, actual: str) -> float:
        """Return a deterministic Item_Score; a pure function of its inputs (Req 6.3)."""
        raise NotImplementedError


class Evaluation_Store(ABC):
    """Persistence contract for datasets, items, runs, and results (all org-scoped)."""

    @abstractmethod
    def add_dataset(self, dataset: Evaluation_Dataset) -> Evaluation_Dataset:
        """Persist an org-scoped Evaluation_Dataset and return it (Req 6.1)."""
        raise NotImplementedError

    @abstractmethod
    def get_dataset(self, org_id: UUID, dataset_id: UUID) -> Evaluation_Dataset | None:
        """Return the dataset iff it belongs to ``org_id``, else ``None`` (Req 6.8)."""
        raise NotImplementedError

    @abstractmethod
    def list_datasets(self, org_id: UUID) -> list[Evaluation_Dataset]:
        """Return every dataset scoped to ``org_id``."""
        raise NotImplementedError

    @abstractmethod
    def add_item(self, item: Evaluation_Item) -> Evaluation_Item:
        """Persist an Evaluation_Item under its parent dataset (Req 8.3)."""
        raise NotImplementedError

    @abstractmethod
    def list_items(self, org_id: UUID, dataset_id: UUID) -> list[Evaluation_Item]:
        """Return ``org_id``'s items for ``dataset_id``; never cross-org (Req 6.8)."""
        raise NotImplementedError

    @abstractmethod
    def add_run(self, run: Evaluation_Run) -> Evaluation_Run:
        """Persist an Evaluation_Run and its per-item results scoped to ``org_id`` (Req 6.5)."""
        raise NotImplementedError

    @abstractmethod
    def get_run(self, org_id: UUID, run_id: UUID) -> Evaluation_Run | None:
        """Return the run iff it belongs to ``org_id``, else ``None`` (Req 6.8)."""
        raise NotImplementedError
