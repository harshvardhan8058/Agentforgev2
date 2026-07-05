"""Property-based test for observability tenant isolation (Task 8.6).

Feature: agentforge-observability, Property 10: Observability tenant isolation across
every resource type. For any two distinct organizations A and B, any observability
resource created under A -- a Usage_Record, a Prompt_Template/Prompt_Version, an
Evaluation_Dataset, or an Evaluation_Run -- and any authenticated Principal whose
org_id = B, every read and mutate attempt against that resource returns
AppError("not_found", 404) (or empty for lists) and no response to B ever includes a
resource owned by A; the constraint holds at the data-access layer independently of any
handler check.

Validates: Requirements 2.3, 3.3, 4.8, 6.1, 6.5, 6.8, 7.6, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.api.errors import AppError
from agentforge.observability.evaluation.evaluators import Exact_Match_Evaluator
from agentforge.observability.evaluation.framework import Evaluation_Framework
from agentforge.observability.evaluation.store import InMemory_Evaluation_Store
from agentforge.observability.models import (
    Evaluation_Dataset,
    Evaluation_Item,
    Usage_Record,
)
from agentforge.observability.prompt_registry.registry import Prompt_Registry
from agentforge.observability.prompt_registry.store import InMemory_Prompt_Store
from agentforge.observability.usage.store import InMemory_Usage_Store

_BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)
_START = _BASE - timedelta(days=1)
_END = _BASE + timedelta(days=1)

_RESOURCE_KINDS = ["usage_record", "prompt", "evaluation_dataset", "evaluation_run"]


def _usage_case(org_a, org_b) -> None:
    store = InMemory_Usage_Store()
    store.add(
        Usage_Record(
            id=uuid.uuid4(),
            org_id=org_a,
            user_id=None,
            provider="groq",
            model="m",
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
            cost=Decimal("0.5"),
            created_at=_BASE,
        )
    )
    # Owner sees the record; B sees nothing (Req 2.3, 3.3, 10.3).
    assert len(store.list_for_org(org_a, start=_START, end=_END)) == 1
    assert store.list_for_org(org_b, start=_START, end=_END) == []


def _prompt_case(org_a, org_b) -> None:
    registry = Prompt_Registry(InMemory_Prompt_Store())
    registry.create_version(org_a, "secret", body="owned by A", variables=[])

    # Owner resolves it; B's read is a 404, never a leak (Req 4.8, 10.4).
    assert registry.get(org_a, "secret").body == "owned by A"
    with pytest.raises(AppError) as excinfo:
        registry.get(org_b, "secret")
    assert excinfo.value.code == "not_found"
    assert excinfo.value.status_code == 404
    with pytest.raises(AppError):
        registry.get(org_b, "secret", version=1)


def _dataset_case(org_a, org_b) -> None:
    store = InMemory_Evaluation_Store()
    dataset_id = uuid.uuid4()
    store.add_dataset(
        Evaluation_Dataset(
            id=dataset_id, org_id=org_a, name="ds", created_at=_BASE
        )
    )
    store.add_item(
        Evaluation_Item(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            org_id=org_a,
            input="q",
            expected="a",
        )
    )
    # Owner reads; B reads nothing (Req 6.1, 6.8, 10.4).
    assert store.get_dataset(org_a, dataset_id) is not None
    assert store.get_dataset(org_b, dataset_id) is None
    assert store.list_datasets(org_b) == []
    assert store.list_items(org_b, dataset_id) == []


def _run_case(org_a, org_b) -> None:
    store = InMemory_Evaluation_Store()
    dataset_id = uuid.uuid4()
    store.add_dataset(
        Evaluation_Dataset(
            id=dataset_id, org_id=org_a, name="ds", created_at=_BASE
        )
    )
    store.add_item(
        Evaluation_Item(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            org_id=org_a,
            input="q",
            expected="a",
        )
    )
    fw = Evaluation_Framework(
        store, lambda inp, org: "a", {"exact_match": Exact_Match_Evaluator()}
    )
    run = fw.run(org_a, dataset_id, ["exact_match"])

    # Owner fetches the run; B sees None; and B cannot run over A's dataset (404).
    assert store.get_run(org_a, run.id) is not None
    assert store.get_run(org_b, run.id) is None
    with pytest.raises(AppError) as excinfo:
        fw.run(org_b, dataset_id, ["exact_match"])
    assert excinfo.value.status_code == 404


_DISPATCH = {
    "usage_record": _usage_case,
    "prompt": _prompt_case,
    "evaluation_dataset": _dataset_case,
    "evaluation_run": _run_case,
}

_org_pairs = st.lists(st.uuids(), min_size=2, max_size=2, unique=True)


# Feature: agentforge-observability, Property 10: Observability tenant isolation across
# every resource type.
@hyp_settings(max_examples=100, deadline=None)
@given(orgs=_org_pairs, kind=st.sampled_from(_RESOURCE_KINDS))
def test_observability_tenant_isolation(orgs, kind):
    org_a, org_b = orgs
    _DISPATCH[kind](org_a, org_b)
