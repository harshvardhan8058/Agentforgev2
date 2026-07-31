"""Unit tests for the evaluations router (Task 15.1).

Drive the real FastAPI app through ``TestClient`` with only keyless in-memory contexts
wired on ``app.state`` (an ``EnterpriseContext`` for auth + an ``ObservabilityContext``
holding an in-memory ``Evaluation_Store`` and a deterministic keyless ``pipeline_runner``).
No Postgres, Redis, or external credential is required.

Covered (Req 6.1, 6.2, 6.5, 6.8, 6.9):

* create-dataset;
* list-datasets (own org only);
* run-then-get, with the persisted aggregate equal to the mean of the per-item scores;
* cross-org dataset run -> 404 and cross-org run get -> 404.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import build_observability_context
from agentforge.config.settings import Settings
from agentforge.enterprise.rbac import Role
from agentforge.main import create_app

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )


def _runner(text: str, org_id) -> str:
    """A deterministic keyless pipeline runner: echoes the item input as the actual output."""
    return text


@pytest.fixture
def wired():
    """Return ``(client, headers, org_id, ctx)`` for an OWNER principal (run_agents + read)."""
    settings = _make_settings()
    app = create_app(settings)
    app.state.observability_context = build_observability_context(
        settings, pipeline_runner=_runner
    )
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    client = TestClient(app, raise_server_exceptions=False)
    return client, headers, org_id, ctx


def _create_dataset(client, headers, name, items):
    return client.post(
        "/evaluations/datasets",
        json={"name": name, "items": items},
        headers=headers,
    )


def test_create_dataset(wired):
    client, headers, _org_id, _ctx = wired
    resp = _create_dataset(
        client,
        headers,
        "greetings",
        [{"input": "hello", "expected": "hello"}],
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "greetings"
    assert body["dataset_id"]


def test_list_datasets_scoped_to_own_org(wired):
    client, headers, _org_id, ctx = wired
    _create_dataset(client, headers, "ds-a", [{"input": "x", "expected": "x"}])
    _create_dataset(client, headers, "ds-b", [{"input": "y", "expected": "y"}])

    resp = client.get("/evaluations/datasets", headers=headers)
    assert resp.status_code == 200
    names = {d["name"] for d in resp.json()}
    assert names == {"ds-a", "ds-b"}

    # A principal in a DIFFERENT org sees none of them.
    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    other_resp = client.get("/evaluations/datasets", headers=other_headers)
    assert other_resp.status_code == 200
    assert other_resp.json() == []


def test_run_then_get_aggregate_is_mean_of_item_scores(wired):
    client, headers, _org_id, _ctx = wired
    # Two items: the runner echoes the input, so exact_match scores 1.0 when input==expected.
    created = _create_dataset(
        client,
        headers,
        "mixed",
        [
            {"input": "match", "expected": "match"},  # exact_match -> 1.0
            {"input": "actual", "expected": "different"},  # exact_match -> 0.0
        ],
    )
    dataset_id = created.json()["dataset_id"]

    run_resp = client.post(
        "/evaluations/runs",
        json={"dataset_id": dataset_id, "evaluators": ["exact_match"]},
        headers=headers,
    )
    assert run_resp.status_code == 200
    run = run_resp.json()
    scores = [r["score"] for r in run["results"]]
    assert sorted(scores) == [0.0, 1.0]
    # Aggregate is the mean of the per-item scores (Req 6.4, 6.9).
    assert run["aggregate_score"] == pytest.approx(sum(scores) / len(scores))
    assert run["aggregate_score"] == pytest.approx(0.5)

    # GET the persisted run returns the same aggregate + per-item scores.
    got = client.get(f"/evaluations/runs/{run['run_id']}", headers=headers)
    assert got.status_code == 200
    got_body = got.json()
    assert got_body["aggregate_score"] == pytest.approx(0.5)
    assert got_body["run_id"] == run["run_id"]
    assert len(got_body["results"]) == 2


def test_cross_org_dataset_run_is_404(wired):
    client, headers, _org_id, ctx = wired
    created = _create_dataset(client, headers, "secret-ds", [{"input": "a", "expected": "a"}])
    dataset_id = created.json()["dataset_id"]

    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    resp = client.post(
        "/evaluations/runs",
        json={"dataset_id": dataset_id, "evaluators": ["exact_match"]},
        headers=other_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_cross_org_run_get_is_404(wired):
    client, headers, _org_id, ctx = wired
    created = _create_dataset(client, headers, "ds", [{"input": "a", "expected": "a"}])
    dataset_id = created.json()["dataset_id"]
    run = client.post(
        "/evaluations/runs",
        json={"dataset_id": dataset_id, "evaluators": ["exact_match"]},
        headers=headers,
    ).json()

    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    resp = client.get(f"/evaluations/runs/{run['run_id']}", headers=other_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"



def test_list_datasets_reports_the_item_count(wired):
    """The list carries each dataset's item count (an additive response field).

    A run scores every item in the dataset, so a dataset with no items produces
    no results and an aggregate of exactly 0. Without a count, that dataset is
    indistinguishable from a usable one until a run has already been wasted on
    it, so the count is surfaced in the listing.
    """
    client, headers, _org_id, _ctx = wired
    _create_dataset(
        client,
        headers,
        "two-items",
        [{"input": "a", "expected": "a"}, {"input": "b", "expected": "b"}],
    )
    _create_dataset(client, headers, "no-items", [])

    resp = client.get("/evaluations/datasets", headers=headers)

    assert resp.status_code == 200
    counts = {d["name"]: d["item_count"] for d in resp.json()}
    assert counts == {"two-items": 2, "no-items": 0}


def test_item_count_is_scoped_to_the_callers_org(wired):
    """Another org's items never contribute to this org's counts (Req 6.8)."""
    client, headers, _org_id, ctx = wired
    _create_dataset(client, headers, "mine", [{"input": "a", "expected": "a"}])

    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Counting Org", email="counting@ex.com"
    )
    _create_dataset(
        client,
        other_headers,
        "theirs",
        [{"input": "b", "expected": "b"}, {"input": "c", "expected": "c"}],
    )

    resp = client.get("/evaluations/datasets", headers=headers)

    assert [(d["name"], d["item_count"]) for d in resp.json()] == [("mine", 1)]
