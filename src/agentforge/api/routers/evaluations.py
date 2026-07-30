"""Evaluations router: the org-scoped Evaluation_Framework API (Task 15).

Endpoints (design § "API endpoints — evaluations rows"):

* ``POST /evaluations/datasets`` — ``run_agents``; create a dataset + its items scoped to
  the caller's org (Req 6.1).
* ``GET /evaluations/datasets`` — ``read``; list the org's datasets (Req 6.5).
* ``POST /evaluations/runs`` — ``run_agents``; execute a run over a dataset with named
  evaluators (Req 6.2, 6.5).
* ``GET /evaluations/runs/{id}`` — ``read``; the persisted aggregate + per-item scores
  (Req 6.9).

Every handler declares only ``Depends(require_permission(...))`` and threads
``principal.org_id`` into the org-scoped :class:`Evaluation_Store` /
:class:`Evaluation_Framework`, so a cross-tenant dataset or run matches zero rows and
surfaces as ``404 not_found`` — never a 403 that would leak existence (Req 6.8, 7.6,
10.4). The store / framework are synchronous, so their calls run in a worker thread to
avoid blocking the event loop.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import (
    get_evaluation_framework,
    get_evaluation_store,
    require_permission,
)
from agentforge.api.errors import AppError
from agentforge.api.schemas import (
    CreateDatasetRequest,
    CreateDatasetResponse,
    DatasetSummary,
    EvaluationItemScore,
    EvaluationRunRequest,
    EvaluationRunResponse,
)
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.observability.evaluation.base import Evaluation_Store
from agentforge.observability.evaluation.framework import Evaluation_Framework
from agentforge.observability.models import (
    Evaluation_Dataset,
    Evaluation_Item,
    Evaluation_Run,
)

router = APIRouter(tags=["evaluations"])


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _run_to_response(run: Evaluation_Run) -> EvaluationRunResponse:
    """Render a persisted Evaluation_Run as its API response envelope (Req 6.9)."""
    return EvaluationRunResponse(
        run_id=run.id,
        dataset_id=run.dataset_id,
        aggregate_score=run.aggregate_score,
        results=[
            EvaluationItemScore(
                item_id=result.item_id,
                evaluator=result.evaluator,
                score=result.score,
            )
            for result in run.results
        ],
    )


@router.post(
    "/evaluations/datasets",
    response_model=CreateDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    payload: CreateDatasetRequest,
    store: Evaluation_Store = Depends(get_evaluation_store),
    principal: Principal = Depends(require_permission(Permission.RUN_AGENTS)),
) -> CreateDatasetResponse:
    """Create an org-scoped Evaluation_Dataset and persist its items (Req 6.1)."""
    org_id = principal.org_id

    def _create() -> Evaluation_Dataset:
        dataset = Evaluation_Dataset(
            id=uuid.uuid4(),
            org_id=org_id,
            name=payload.name,
            created_at=_utcnow(),
        )
        store.add_dataset(dataset)
        for item in payload.items:
            store.add_item(
                Evaluation_Item(
                    id=uuid.uuid4(),
                    dataset_id=dataset.id,
                    org_id=org_id,
                    input=item.input,
                    expected=item.expected,
                )
            )
        return dataset

    dataset = await run_in_threadpool(_create)
    return CreateDatasetResponse(dataset_id=dataset.id, name=dataset.name)


@router.get("/evaluations/datasets", response_model=list[DatasetSummary])
async def list_datasets(
    store: Evaluation_Store = Depends(get_evaluation_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> list[DatasetSummary]:
    """List the caller org's datasets; never cross-org (Req 6.5, 6.8)."""
    org_id = principal.org_id

    def _list() -> list[DatasetSummary]:
        # Counted inside a single threadpool hop rather than awaiting per dataset,
        # so listing N datasets costs one thread switch instead of N + 1.
        return [
            DatasetSummary(
                dataset_id=d.id,
                name=d.name,
                created_at=d.created_at,
                item_count=len(store.list_items(org_id, d.id)),
            )
            for d in store.list_datasets(org_id)
        ]

    return await run_in_threadpool(_list)


@router.post("/evaluations/runs", response_model=EvaluationRunResponse)
async def create_run(
    payload: EvaluationRunRequest,
    framework: Evaluation_Framework = Depends(get_evaluation_framework),
    principal: Principal = Depends(require_permission(Permission.RUN_AGENTS)),
) -> EvaluationRunResponse:
    """Execute a run over the org-scoped dataset with named evaluators (Req 6.2, 6.5, 6.9).

    The framework loads the dataset scoped to ``principal.org_id`` (an absent or
    cross-tenant dataset raises ``404 not_found``), scores every item with each named
    evaluator on the keyless pipeline, and persists the run; the aggregate equals the
    mean of the per-item scores by construction (Req 6.4, 6.9).
    """
    run = await run_in_threadpool(
        framework.run,
        principal.org_id,
        payload.dataset_id,
        payload.evaluators,
    )
    return _run_to_response(run)


@router.get("/evaluations/runs/{run_id}", response_model=EvaluationRunResponse)
async def get_run(
    run_id: uuid.UUID,
    store: Evaluation_Store = Depends(get_evaluation_store),
    principal: Principal = Depends(require_permission(Permission.READ)),
) -> EvaluationRunResponse:
    """Return a persisted run's aggregate + per-item scores; 404 if absent (Req 6.8, 6.9)."""
    run = await run_in_threadpool(store.get_run, principal.org_id, run_id)
    if run is None:
        raise AppError(
            "not_found",
            f"evaluation run {run_id!s} was not found",
            status.HTTP_404_NOT_FOUND,
        )
    return _run_to_response(run)
