"""API tests: the spend budget is readable, owner-managed, audited, and enforced.

Enforcement is the part that cannot be tested at the unit level — a guard that nobody calls
is the defect class this codebase has produced before — so these drive the real app: set a
blocking budget, spend past it, and assert the *spending* endpoints refuse while the reading
ones keep working. Plus: RBAC, tenancy, that the audit trail records who changed the ceiling,
and that a `warn` budget never refuses anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
    build_observability_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.rbac import Role
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.store import InMemory_Usage_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
        # No cache, so a test's spend is visible to the very next request.
        budget_cache_seconds=0.0,
    )


@pytest.fixture
def wired():
    """Return ``(client, headers, org_id, usage_store, ctx)`` for an OWNER principal."""
    settings = _make_settings()
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    usage_store = InMemory_Usage_Store()
    app = create_app(settings)
    app.state.settings = settings
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = build_multi_agent_context(settings, agent=agent_ctx)
    app.state.observability_context = build_observability_context(
        settings, app=app_ctx, usage_store=usage_store, trace_recorder=InMemory_Trace_Recorder()
    )
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    return TestClient(app, raise_server_exceptions=False), headers, org_id, usage_store, ctx


def _spend(usage_store: InMemory_Usage_Store, org_id, amount: str) -> None:
    usage_store.add(
        Usage_Record(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=None,
            provider="groq",
            model="llama-3.1-8b-instant",
            prompt_tokens=1000,
            completion_tokens=1000,
            total_tokens=2000,
            cost=Decimal(amount),
            created_at=datetime.now(timezone.utc),
        )
    )


# --- reading -----------------------------------------------------------------------


def test_requires_authentication(wired):
    client, _headers, _org, _usage, _ctx = wired
    assert client.get("/budget").status_code == 401
    assert client.put("/budget", json={"limit_amount": "5"}).status_code == 401


def test_an_unbudgeted_org_reports_unlimited(wired):
    client, headers, _org_id, _usage, _ctx = wired

    body = client.get("/budget", headers=headers).json()

    assert body["spent"] == "0"
    assert body["limit_amount"] is None
    assert body["remaining"] is None
    assert body["percent_used"] is None
    assert body["action"] is None
    assert body["exceeded"] is False
    assert body["blocked"] is False
    # The period is a calendar month, so the end is after the start and both are UTC.
    assert body["period_start"] < body["period_end"]


def test_any_member_can_read_the_budget(wired):
    """Someone about to be refused should be able to see why."""
    client, _headers, _org_id, _usage, ctx = wired
    member_headers, _member_org = issue_principal_headers(
        ctx, role=Role.MEMBER, org_name="Member Org", email="member@ex.com"
    )

    assert client.get("/budget", headers=member_headers).status_code == 200


def test_money_crosses_as_exact_strings(wired):
    client, headers, org_id, usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "1.00", "action": "warn"}, headers=headers)
    for cost in ("0.00005", "0.00008"):
        _spend(usage, org_id, cost)

    body = client.get("/budget", headers=headers).json()

    # Verbatim decimals, never floats: 0.00013 would not survive a float round trip.
    assert body["spent"] == "0.00013"
    assert body["limit_amount"] == "1.00"
    assert body["remaining"] == "0.99987"
    assert body["percent_used"] == "0.01"


# --- managing ----------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.VIEWER, Role.MEMBER, Role.ADMIN])
def test_only_an_owner_can_set_or_clear_a_budget(wired, role: Role):
    """A spend ceiling is a financial control; the role that owns the org owns it."""
    client, _headers, _org_id, _usage, ctx = wired
    other_headers, _other_org = issue_principal_headers(
        ctx, role=role, org_name=f"Org {role.value}", email=f"{role.value}@ex.com"
    )

    put = client.put("/budget", json={"limit_amount": "5"}, headers=other_headers)
    delete = client.delete("/budget", headers=other_headers)

    assert [put.status_code, delete.status_code] == [403, 403]
    assert put.json()["error"]["details"]["required"] == "manage_budget"


def test_setting_a_budget_is_idempotent_and_replaces_it(wired):
    client, headers, _org_id, _usage, _ctx = wired

    first = client.put(
        "/budget", json={"limit_amount": "10", "action": "warn"}, headers=headers
    )
    second = client.put(
        "/budget", json={"limit_amount": "20", "action": "block"}, headers=headers
    )

    assert first.status_code == 200
    assert first.json()["action"] == "warn"
    assert second.json()["limit_amount"] == "20"
    assert second.json()["action"] == "block"
    assert client.get("/budget", headers=headers).json()["limit_amount"] == "20"


def test_the_default_action_is_warn(wired):
    """Setting a budget must not silently start refusing a customer's traffic."""
    client, headers, _org_id, _usage, _ctx = wired

    body = client.put("/budget", json={"limit_amount": "10"}, headers=headers).json()

    assert body["action"] == "warn"


def test_a_negative_budget_is_refused(wired):
    client, headers, _org_id, _usage, _ctx = wired
    assert client.put("/budget", json={"limit_amount": "-1"}, headers=headers).status_code == 422
    assert (
        client.put("/budget", json={"limit_amount": "5", "action": "explode"}, headers=headers).status_code
        == 422
    )


def test_removing_a_budget_restores_unlimited_spend_and_is_idempotent(wired):
    client, headers, _org_id, _usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "10", "action": "block"}, headers=headers)

    first = client.delete("/budget", headers=headers)
    second = client.delete("/budget", headers=headers)

    assert first.status_code == 204
    # The desired end state holds either way, so a repeat is not a 404.
    assert second.status_code == 204
    assert client.get("/budget", headers=headers).json()["limit_amount"] is None


def test_budget_changes_are_audited(wired):
    """"Who raised the ceiling, and when" is exactly why the audit trail exists."""
    client, headers, org_id, _usage, _ctx = wired

    client.put("/budget", json={"limit_amount": "42.5", "action": "block"}, headers=headers)
    client.delete("/budget", headers=headers)

    events = client.get("/audit-events", headers=headers).json()
    actions = [e["action"] for e in events]
    assert actions == ["budget.removed", "budget.set"]
    recorded = next(e for e in events if e["action"] == "budget.set")
    assert recorded["metadata"] == {"limit_amount": "42.5", "action": "block"}
    assert recorded["target_type"] == "budget"
    assert recorded["actor_email"] == "owner@ex.com"


def test_another_orgs_budget_is_never_visible_or_writable(wired):
    """There is no org parameter: the budget is always the caller's own."""
    client, headers, _org_id, _usage, ctx = wired
    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )

    client.put("/budget", json={"limit_amount": "99", "action": "block"}, headers=other_headers)

    assert client.get("/budget", headers=headers).json()["limit_amount"] is None
    assert client.get("/budget", headers=other_headers).json()["limit_amount"] == "99"


# --- enforcement -------------------------------------------------------------------


def test_a_blocking_budget_refuses_new_work_with_402(wired):
    client, headers, org_id, usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "1", "action": "block"}, headers=headers)
    _spend(usage, org_id, "5")

    resp = client.post("/agent/run", json={"message": "hello"}, headers=headers)

    # 402: the request was well-formed and authorized; a spending limit stands in its way.
    assert resp.status_code == 402
    body = resp.json()["error"]
    assert body["code"] == "budget_exceeded"
    assert body["details"]["spent"] == "5"
    assert body["details"]["limit_amount"] == "1"
    assert body["details"]["period_end"]


def test_every_spending_entry_point_is_gated(wired):
    client, headers, org_id, usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "1", "action": "block"}, headers=headers)
    _spend(usage, org_id, "5")

    spending = [
        client.post("/query", json={"query": "what is agentforge?"}, headers=headers),
        client.post("/agent/run", json={"message": "hello"}, headers=headers),
        client.post("/agent/stream", json={"message": "hello"}, headers=headers),
        client.post("/multi-agent/runs", json={"task": "plan"}, headers=headers),
    ]

    assert [r.status_code for r in spending] == [402] * 4
    assert {r.json()["error"]["code"] for r in spending} == {"budget_exceeded"}


def test_reading_still_works_while_blocked(wired):
    """Blocking reads would hide the very data that explains the overage."""
    client, headers, org_id, usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "1", "action": "block"}, headers=headers)
    _spend(usage, org_id, "5")

    assert client.get("/budget", headers=headers).status_code == 200
    assert client.get("/analytics/usage", headers=headers).status_code == 200
    assert client.get("/documents", headers=headers).status_code == 200
    assert client.get("/agent/runs", headers=headers).status_code == 200
    assert client.get("/audit-events", headers=headers).status_code == 200


def test_a_warn_budget_never_refuses(wired):
    client, headers, org_id, usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "1", "action": "warn"}, headers=headers)
    _spend(usage, org_id, "5")

    resp = client.post("/agent/run", json={"message": "hello"}, headers=headers)

    assert resp.status_code == 200
    status_ = client.get("/budget", headers=headers).json()
    assert status_["exceeded"] is True
    assert status_["blocked"] is False


def test_raising_the_ceiling_unblocks_immediately(wired):
    client, headers, org_id, usage, _ctx = wired
    client.put("/budget", json={"limit_amount": "1", "action": "block"}, headers=headers)
    _spend(usage, org_id, "5")
    assert client.post("/agent/run", json={"message": "hi"}, headers=headers).status_code == 402

    client.put("/budget", json={"limit_amount": "100", "action": "block"}, headers=headers)

    assert client.post("/agent/run", json={"message": "hi"}, headers=headers).status_code == 200


def test_one_orgs_budget_never_blocks_another(wired):
    client, headers, org_id, usage, ctx = wired
    other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    client.put("/budget", json={"limit_amount": "1", "action": "block"}, headers=headers)
    _spend(usage, org_id, "5")
    # The other org spends nothing and sets no budget.

    assert client.post("/agent/run", json={"message": "hi"}, headers=headers).status_code == 402
    assert (
        client.post("/agent/run", json={"message": "hi"}, headers=other_headers).status_code
        == 200
    )
