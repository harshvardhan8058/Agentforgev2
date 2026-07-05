"""Unit tests for the deterministic evaluators and Evaluation_Framework (Task 8.2/8.3).

Covers each evaluator's specific scoring behaviour, the framework's aggregate == mean of
per-item scores, the 404 on an unknown dataset, and the 404 on an unknown evaluator name.

Requirements: 6.3, 6.4, 6.8, 6.9
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from agentforge.api.errors import AppError
from agentforge.observability.evaluation.evaluators import (
    Contains_Evaluator,
    Exact_Match_Evaluator,
    Heuristic_Evaluator,
)
from agentforge.observability.evaluation.framework import Evaluation_Framework
from agentforge.observability.evaluation.store import InMemory_Evaluation_Store
from agentforge.observability.models import Evaluation_Dataset, Evaluation_Item


def test_exact_match_scores():
    ev = Exact_Match_Evaluator()
    assert ev.score(input="q", expected="hello", actual="hello") == 1.0
    assert ev.score(input="q", expected="hello", actual="world") == 0.0
    assert ev.score(input="q", expected=None, actual="hello") == 0.0


def test_contains_scores():
    ev = Contains_Evaluator()
    assert ev.score(input="q", expected="ell", actual="hello") == 1.0
    assert ev.score(input="q", expected="xyz", actual="hello") == 0.0
    assert ev.score(input="q", expected=None, actual="hello") == 0.0


def test_heuristic_jaccard_scores():
    ev = Heuristic_Evaluator()
    assert ev.score(input="q", expected="a b c", actual="a b c") == 1.0
    assert ev.score(input="q", expected="", actual="") == 1.0
    # Jaccard of {a,b} and {b,c} = 1/3.
    assert abs(ev.score(input="q", expected="a b", actual="b c") - (1 / 3)) < 1e-9


def _store_with_items(org, dataset_id, items):
    store = InMemory_Evaluation_Store()
    store.add_dataset(
        Evaluation_Dataset(
            id=dataset_id, org_id=org, name="ds", created_at=datetime.now(timezone.utc)
        )
    )
    for text_in, expected in items:
        store.add_item(
            Evaluation_Item(
                id=uuid.uuid4(),
                dataset_id=dataset_id,
                org_id=org,
                input=text_in,
                expected=expected,
            )
        )
    return store


def test_framework_aggregate_is_mean_of_per_item_scores():
    org = uuid.uuid4()
    dataset_id = uuid.uuid4()
    # Runner echoes the expected for the first item and something else for the second.
    store = _store_with_items(org, dataset_id, [("q1", "match"), ("q2", "expected2")])

    def runner(inp, org_id):
        return "match" if inp == "q1" else "different"

    fw = Evaluation_Framework(store, runner, {"exact_match": Exact_Match_Evaluator()})
    run = fw.run(org, dataset_id, ["exact_match"])
    # One 1.0 and one 0.0 -> mean 0.5.
    assert run.aggregate_score == 0.5
    assert len(run.results) == 2


def test_framework_unknown_dataset_raises_404():
    org = uuid.uuid4()
    fw = Evaluation_Framework(
        InMemory_Evaluation_Store(), lambda i, o: "x", {"exact_match": Exact_Match_Evaluator()}
    )
    with pytest.raises(AppError) as excinfo:
        fw.run(org, uuid.uuid4(), ["exact_match"])
    assert excinfo.value.status_code == 404


def test_framework_unknown_evaluator_raises_404():
    org = uuid.uuid4()
    dataset_id = uuid.uuid4()
    store = _store_with_items(org, dataset_id, [("q", "a")])
    fw = Evaluation_Framework(store, lambda i, o: "a", {"exact_match": Exact_Match_Evaluator()})
    with pytest.raises(AppError) as excinfo:
        fw.run(org, dataset_id, ["nonexistent"])
    assert excinfo.value.status_code == 404
