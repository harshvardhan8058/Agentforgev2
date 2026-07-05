"""Evaluation_Store implementations: ``InMemory_Evaluation_Store`` / ``Pg_Evaluation_Store``.

Every method constrains by ``org_id`` so a cross-tenant read is structurally ``None``/
empty; child rows (items, results) carry FKs to their parents (Req 6.8, 8.3, 10.3). The
synchronous ``Pg_Evaluation_Store`` mirrors the Phase 5/6 ``Pg_*`` stores and maps onto the
``evaluation_datasets`` / ``evaluation_items`` / ``evaluation_runs`` / ``evaluation_results``
tables from migration ``0010``.
"""

from __future__ import annotations

import copy
import uuid
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agentforge.conversation.store import _to_sqlalchemy_sync_dsn
from agentforge.observability.evaluation.base import Evaluation_Store
from agentforge.observability.models import (
    Evaluation_Dataset,
    Evaluation_Item,
    Evaluation_Result,
    Evaluation_Run,
)


class InMemory_Evaluation_Store(Evaluation_Store):
    """Keyless/test in-memory Evaluation_Store scoped by ``org_id`` (Req 6.8, 10.3)."""

    def __init__(self) -> None:
        self._datasets: list[Evaluation_Dataset] = []
        self._items: list[Evaluation_Item] = []
        self._runs: list[Evaluation_Run] = []

    def add_dataset(self, dataset: Evaluation_Dataset) -> Evaluation_Dataset:
        self._datasets.append(dataset)
        return dataset

    def get_dataset(self, org_id: UUID, dataset_id: UUID) -> Evaluation_Dataset | None:
        for dataset in self._datasets:
            if dataset.org_id == org_id and dataset.id == dataset_id:
                return dataset
        return None

    def list_datasets(self, org_id: UUID) -> list[Evaluation_Dataset]:
        return [d for d in self._datasets if d.org_id == org_id]

    def add_item(self, item: Evaluation_Item) -> Evaluation_Item:
        self._items.append(item)
        return item

    def list_items(self, org_id: UUID, dataset_id: UUID) -> list[Evaluation_Item]:
        return [
            item
            for item in self._items
            if item.org_id == org_id and item.dataset_id == dataset_id
        ]

    def add_run(self, run: Evaluation_Run) -> Evaluation_Run:
        # Deep-copy so the persisted run (and its results) can't be mutated by the caller.
        self._runs.append(copy.deepcopy(run))
        return run

    def get_run(self, org_id: UUID, run_id: UUID) -> Evaluation_Run | None:
        for run in self._runs:
            if run.org_id == org_id and run.id == run_id:
                return copy.deepcopy(run)
        return None


class Pg_Evaluation_Store(Evaluation_Store):
    """Synchronous Postgres-backed Evaluation_Store; SQL scoped by ``org_id``.

    Maps onto the ``evaluation_*`` tables from migration ``0010``. Every query constrains
    by ``WHERE org_id = :org_id`` so a cross-org read matches zero rows and can never
    return another tenant's evaluation state (Req 6.8, 10.3, 10.4).
    """

    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(
            _to_sqlalchemy_sync_dsn(database_url), future=True, pool_pre_ping=True
        )

    def add_dataset(self, dataset: Evaluation_Dataset) -> Evaluation_Dataset:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO evaluation_datasets (id, org_id, name, created_at)
                    VALUES (:id, :org_id, :name, :created_at)
                    """
                ),
                {
                    "id": str(dataset.id),
                    "org_id": str(dataset.org_id),
                    "name": dataset.name,
                    "created_at": dataset.created_at,
                },
            )
        return dataset

    def get_dataset(self, org_id: UUID, dataset_id: UUID) -> Evaluation_Dataset | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, org_id, name, created_at
                    FROM evaluation_datasets
                    WHERE org_id = :org_id AND id = :id
                    """
                ),
                {"org_id": str(org_id), "id": str(dataset_id)},
            ).first()
        return self._row_to_dataset(row) if row is not None else None

    def list_datasets(self, org_id: UUID) -> list[Evaluation_Dataset]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, org_id, name, created_at
                    FROM evaluation_datasets
                    WHERE org_id = :org_id
                    ORDER BY created_at ASC
                    """
                ),
                {"org_id": str(org_id)},
            ).fetchall()
        return [self._row_to_dataset(r) for r in rows]

    def add_item(self, item: Evaluation_Item) -> Evaluation_Item:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO evaluation_items
                        (id, org_id, dataset_id, input, expected)
                    VALUES (:id, :org_id, :dataset_id, :input, :expected)
                    """
                ),
                {
                    "id": str(item.id),
                    "org_id": str(item.org_id),
                    "dataset_id": str(item.dataset_id),
                    "input": item.input,
                    "expected": item.expected,
                },
            )
        return item

    def list_items(self, org_id: UUID, dataset_id: UUID) -> list[Evaluation_Item]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, org_id, dataset_id, input, expected
                    FROM evaluation_items
                    WHERE org_id = :org_id AND dataset_id = :dataset_id
                    ORDER BY id ASC
                    """
                ),
                {"org_id": str(org_id), "dataset_id": str(dataset_id)},
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def add_run(self, run: Evaluation_Run) -> Evaluation_Run:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO evaluation_runs
                        (id, org_id, dataset_id, aggregate_score, created_at)
                    VALUES (:id, :org_id, :dataset_id, :aggregate_score, :created_at)
                    """
                ),
                {
                    "id": str(run.id),
                    "org_id": str(run.org_id),
                    "dataset_id": str(run.dataset_id),
                    "aggregate_score": run.aggregate_score,
                    "created_at": run.created_at,
                },
            )
            for result in run.results:
                conn.execute(
                    text(
                        """
                        INSERT INTO evaluation_results
                            (id, org_id, run_id, item_id, evaluator, score)
                        VALUES
                            (:id, :org_id, :run_id, :item_id, :evaluator, :score)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": str(run.org_id),
                        "run_id": str(run.id),
                        "item_id": str(result.item_id),
                        "evaluator": result.evaluator,
                        "score": result.score,
                    },
                )
        return run

    def get_run(self, org_id: UUID, run_id: UUID) -> Evaluation_Run | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, org_id, dataset_id, aggregate_score, created_at
                    FROM evaluation_runs
                    WHERE org_id = :org_id AND id = :id
                    """
                ),
                {"org_id": str(org_id), "id": str(run_id)},
            ).first()
            if row is None:
                return None
            result_rows = conn.execute(
                text(
                    """
                    SELECT item_id, evaluator, score
                    FROM evaluation_results
                    WHERE org_id = :org_id AND run_id = :run_id
                    ORDER BY item_id ASC, evaluator ASC
                    """
                ),
                {"org_id": str(org_id), "run_id": str(run_id)},
            ).fetchall()
        results = [
            Evaluation_Result(
                item_id=UUID(str(r[0])), evaluator=r[1], score=float(r[2])
            )
            for r in result_rows
        ]
        return Evaluation_Run(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            dataset_id=UUID(str(row[2])),
            aggregate_score=float(row[3]),
            results=results,
            created_at=row[4],
        )

    @staticmethod
    def _row_to_dataset(row) -> Evaluation_Dataset:
        return Evaluation_Dataset(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            name=row[2],
            created_at=row[3],
        )

    @staticmethod
    def _row_to_item(row) -> Evaluation_Item:
        return Evaluation_Item(
            id=UUID(str(row[0])),
            org_id=UUID(str(row[1])),
            dataset_id=UUID(str(row[2])),
            input=row[3],
            expected=row[4],
        )
