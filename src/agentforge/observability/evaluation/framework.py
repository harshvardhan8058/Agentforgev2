"""Evaluation_Framework: runs Evaluators over a dataset on the keyless path.

``run`` loads the org-scoped dataset (404 if absent), produces each item's actual output
via the injected keyless ``pipeline_runner`` (RAG/agent on the Fallback_Provider), scores
each item with each named evaluator, computes the ``Aggregate_Score`` as the mean of
per-item scores, and persists the ``Evaluation_Run`` scoped to ``org_id`` (Req 6.2-6.9).
Because the runner and every evaluator are pure functions on the keyless path, repeated
runs over the same dataset + evaluators are identical (Req 6.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from uuid import UUID

from fastapi import status

from agentforge.api.errors import AppError
from agentforge.observability.evaluation.base import Evaluation_Store, Evaluator
from agentforge.observability.models import Evaluation_Result, Evaluation_Run


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _mean(scores: Sequence[float]) -> float:
    """Return the arithmetic mean of ``scores`` (0.0 for an empty sequence) (Req 6.4)."""
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


class Evaluation_Framework:
    """Runs one or more Evaluators over an Evaluation_Dataset and persists the run."""

    def __init__(
        self,
        store: Evaluation_Store,
        pipeline_runner: Callable[[str, UUID], str],
        evaluators: Mapping[str, Evaluator],
    ) -> None:
        self._store = store
        self._runner = pipeline_runner
        self._evaluators = dict(evaluators)

    def run(
        self, org_id: UUID, dataset_id: UUID, evaluator_names: Sequence[str]
    ) -> Evaluation_Run:
        """Score an org-scoped dataset with named evaluators and persist the run."""
        dataset = self._store.get_dataset(org_id, dataset_id)  # org-scoped (Req 6.8)
        if dataset is None:
            raise AppError(
                "not_found",
                "Dataset not found.",
                status.HTTP_404_NOT_FOUND,
            )

        # Fail closed on an unknown evaluator name rather than silently skipping it.
        for ev_name in evaluator_names:
            if ev_name not in self._evaluators:
                raise AppError(
                    "not_found",
                    f"Evaluator not found: {ev_name}.",
                    status.HTTP_404_NOT_FOUND,
                )

        results: list[Evaluation_Result] = []
        for item in self._store.list_items(org_id, dataset_id):
            actual = self._runner(item.input, org_id)  # keyless pipeline (Req 6.2)
            for ev_name in evaluator_names:
                score = self._evaluators[ev_name].score(
                    input=item.input, expected=item.expected, actual=actual
                )  # pure fn of (input, expected, actual) (Req 6.3)
                results.append(
                    Evaluation_Result(
                        item_id=item.id, evaluator=ev_name, score=score
                    )
                )

        aggregate = _mean([r.score for r in results])  # mean of per-item scores (Req 6.4, 6.9)
        run = Evaluation_Run(
            id=uuid.uuid4(),
            org_id=org_id,
            dataset_id=dataset_id,
            aggregate_score=aggregate,
            results=results,
            created_at=_utcnow(),
        )
        return self._store.add_run(run)  # persisted scoped to org_id (Req 6.5)
