"""Property-based test for evaluation scoring + aggregation determinism (Task 8.5).

Feature: agentforge-observability, Property 9: Evaluation scoring and aggregation are
deterministic and consistent. For any Evaluation_Dataset and set of Evaluators run on the
keyless path, each Item_Score is a pure function of the item's (input, expected, actual)
(repeated runs yield identical per-item scores and an identical Aggregate_Score), and the
persisted Aggregate_Score equals the aggregation (mean) of the run's persisted per-item
Item_Scores.

Validates: Requirements 6.3, 6.4, 6.6, 6.9, 11.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.observability.evaluation.evaluators import (
    Contains_Evaluator,
    Exact_Match_Evaluator,
    Heuristic_Evaluator,
)
from agentforge.observability.evaluation.framework import Evaluation_Framework
from agentforge.observability.evaluation.store import InMemory_Evaluation_Store
from agentforge.observability.models import Evaluation_Dataset, Evaluation_Item

_EVALUATORS = {
    "exact_match": Exact_Match_Evaluator(),
    "contains": Contains_Evaluator(),
    "heuristic": Heuristic_Evaluator(),
}


def _keyless_runner(input_text: str, org_id: uuid.UUID) -> str:
    """A deterministic, pure stand-in for the keyless RAG/agent pipeline."""
    return f"answer to: {input_text}"


_item_specs = st.lists(
    st.tuples(
        st.text(max_size=20),  # input
        st.one_of(st.none(), st.text(max_size=20)),  # expected (may be absent)
    ),
    min_size=0,
    max_size=8,
)


def _build_store(org_id, dataset_id, item_specs):
    store = InMemory_Evaluation_Store()
    store.add_dataset(
        Evaluation_Dataset(
            id=dataset_id,
            org_id=org_id,
            name="ds",
            created_at=datetime.now(timezone.utc),
        )
    )
    for text_in, expected in item_specs:
        store.add_item(
            Evaluation_Item(
                id=uuid.uuid4(),
                dataset_id=dataset_id,
                org_id=org_id,
                input=text_in,
                expected=expected,
            )
        )
    return store


# Feature: agentforge-observability, Property 9: Evaluation scoring and aggregation are
# deterministic and consistent.
@hyp_settings(max_examples=100, deadline=None)
@given(
    org_id=st.uuids(),
    item_specs=_item_specs,
    evaluator_names=st.lists(
        st.sampled_from(["exact_match", "contains", "heuristic"]),
        min_size=1,
        max_size=3,
        unique=True,
    ),
)
def test_evaluation_scoring_and_aggregation_deterministic(
    org_id, item_specs, evaluator_names
):
    dataset_id = uuid.uuid4()

    # Two independent stores/frameworks over identical inputs -> identical outputs.
    store1 = _build_store(org_id, dataset_id, item_specs)
    store2 = _build_store(org_id, dataset_id, item_specs)
    fw1 = Evaluation_Framework(store1, _keyless_runner, _EVALUATORS)
    fw2 = Evaluation_Framework(store2, _keyless_runner, _EVALUATORS)

    run1 = fw1.run(org_id, dataset_id, evaluator_names)
    run2 = fw2.run(org_id, dataset_id, evaluator_names)

    # Per-item scores are a pure function of (input, expected, actual): repeated runs
    # yield identical per-(item, evaluator) scores in the same item/evaluator order.
    # (Item ids are independently generated per store, so we compare positionally by the
    # (evaluator, score) sequence — the determinism claim of Req 6.3, 6.6.)
    scores1 = [(r.evaluator, r.score) for r in run1.results]
    scores2 = [(r.evaluator, r.score) for r in run2.results]
    assert scores1 == scores2
    assert run1.aggregate_score == run2.aggregate_score

    # The persisted aggregate equals the mean of the persisted per-item scores (Req 6.9).
    persisted = store1.get_run(org_id, run1.id)
    assert persisted is not None
    if persisted.results:
        expected_mean = sum(r.score for r in persisted.results) / len(persisted.results)
    else:
        expected_mean = 0.0
    assert abs(persisted.aggregate_score - expected_mean) < 1e-9
