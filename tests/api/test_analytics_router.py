"""Unit tests for the analytics router auth surface (Task 12.1).

Drive the real FastAPI app through ``TestClient`` with only keyless in-memory contexts
wired on ``app.state`` (an ``EnterpriseContext`` for auth + an ``ObservabilityContext``
holding an in-memory ``Usage_Store``). No Postgres, Redis, or external credential is
required.

Covered (Req 3.1, 3.5, 3.6, 10.5):

* no credential -> 401 ``unauthorized``;
* authenticated but lacking ``read`` -> 403 ``forbidden``;
* a ``read`` principal receives a report scoped to its own org only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agentforge.api.deps import get_current_principal
from agentforge.config.container import build_observability_context
from agentforge.config.settings import Settings
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Role
from agentforge.main import create_app
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.store import InMemory_Usage_Store

from tests.enterprise_helpers import install_enterprise_auth


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )


def _usage_record(org_id, *, provider="fallback", model="fallback", tokens=10, cost="0"):
    now = datetime.now(timezone.utc)
    return Usage_Record(
        id=uuid4(),
        org_id=org_id,
        user_id=None,
        provider=provider,
        model=model,
        prompt_tokens=tokens,
        completion_tokens=tokens,
        total_tokens=tokens * 2,
        cost=Decimal(cost),
        created_at=now,
    )


@pytest.fixture
def wired():
    """Return ``(app, client, headers, org_id, usage_store)`` for a READ-capable owner."""
    settings = _make_settings()
    app = create_app(settings)
    usage_store = InMemory_Usage_Store()
    app.state.observability_context = build_observability_context(
        settings, usage_store=usage_store
    )
    headers, org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, raise_server_exceptions=False)
    return app, client, headers, org_id, usage_store


def test_no_credential_is_401(wired):
    _app, client, _headers, _org_id, _store = wired
    resp = client.get("/analytics/usage")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_authenticated_without_read_is_403(wired):
    app, client, headers, org_id, _store = wired

    # Override the principal with one whose permission set does NOT include READ, so the
    # endpoint's require_permission(READ) rejects it with 403 (Req 3.6).
    def _no_read_principal() -> Principal:
        return Principal(
            kind=PrincipalKind.USER.value,
            user_id=uuid4(),
            key_id=None,
            org_id=org_id,
            role=Role.VIEWER,
            permissions=frozenset(),
        )

    app.dependency_overrides[get_current_principal] = _no_read_principal
    try:
        resp = client.get("/analytics/usage", headers=headers)
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    assert resp.json()["error"]["details"]["required"] == "read"


def test_read_principal_gets_own_org_report_only(wired):
    _app, client, headers, org_id, store = wired
    # Two records for the caller's org and one for a DIFFERENT org.
    store.add(_usage_record(org_id, provider="fallback", tokens=10))
    store.add(_usage_record(org_id, provider="groq", tokens=5))
    store.add(_usage_record(uuid4(), provider="fallback", tokens=100))

    resp = client.get("/analytics/usage", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] == str(org_id)
    # Only the caller's two records contribute: (10+10) + (5+5) = 30 tokens.
    assert body["total_tokens"] == 30
    # The provider breakdown partitions exactly the caller's records.
    by_provider = {e["key"]: e["total_tokens"] for e in body["by_provider"]}
    assert by_provider == {"fallback": 20, "groq": 10}
    assert sum(e["total_tokens"] for e in body["by_provider"]) == body["total_tokens"]



# --- cost_rates_configured -------------------------------------------------------
#
# Costs default to zero (Req 2.4, 2.5), so a report reading `0` is ambiguous: either
# nothing was spent, or the deployment never priced its tokens. The console showed the
# latter as a confident "$0.00" beside a five-figure token count, which reads as a broken
# cost feature rather than an unconfigured one. The flag lets a client tell them apart.


def _app_with_settings(settings, usage_store):
    """Build an app whose Settings drive the cost model, returning ``(client, headers)``."""
    app = create_app(settings)
    app.state.observability_context = build_observability_context(
        settings, usage_store=usage_store
    )
    headers, org_id, _ctx = install_enterprise_auth(app, settings)
    return TestClient(app, raise_server_exceptions=False), headers, org_id


def test_rates_not_configured_is_reported_on_the_keyless_default():
    store = InMemory_Usage_Store()
    client, headers, org_id = _app_with_settings(_make_settings(), store)
    store.add(_usage_record(org_id, tokens=100))

    body = client.get("/analytics/usage", headers=headers).json()

    assert body["total_tokens"] > 0
    assert body["total_cost"] == "0"
    assert body["cost_rates_configured"] is False


def test_a_non_zero_default_rate_counts_as_configured():
    settings = _make_settings()
    settings.cost_default_prompt_per_1k = "0.05"
    client, headers, _org = _app_with_settings(settings, InMemory_Usage_Store())

    body = client.get("/analytics/usage", headers=headers).json()

    assert body["cost_rates_configured"] is True


def test_a_per_model_rate_table_counts_as_configured():
    settings = _make_settings()
    settings.cost_rate_table_json = (
        '{"groq:llama-3.1-8b-instant": {"prompt": "0.05", "completion": "0.08"}}'
    )
    client, headers, _org = _app_with_settings(settings, InMemory_Usage_Store())

    body = client.get("/analytics/usage", headers=headers).json()

    assert body["cost_rates_configured"] is True


def test_an_all_zero_rate_table_is_reported_as_not_configured():
    """A table that prices everything at zero cannot produce a cost, so say so."""
    settings = _make_settings()
    settings.cost_rate_table_json = (
        '{"groq:llama-3.1-8b-instant": {"prompt": "0", "completion": "0"}}'
    )
    client, headers, _org = _app_with_settings(settings, InMemory_Usage_Store())

    body = client.get("/analytics/usage", headers=headers).json()

    assert body["cost_rates_configured"] is False



# --- GET /analytics/cost-rates ----------------------------------------------------
#
# A cost total is only interpretable next to the rates that produced it. This endpoint
# reports the effective pricing, so the console can explain a zero total and an auditor
# can check a non-zero one.

PRESET = "groq-public-2026-07"


def test_cost_rates_requires_authentication():
    client, _headers, _org = _app_with_settings(_make_settings(), InMemory_Usage_Store())
    resp = client.get("/analytics/cost-rates")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_cost_rates_without_read_is_403(wired):
    """Pricing is deployment configuration, but still gated on ``read`` (Req 3.6)."""
    app, client, headers, org_id, _store = wired

    def _no_read_principal() -> Principal:
        return Principal(
            kind=PrincipalKind.USER.value,
            user_id=uuid4(),
            key_id=None,
            org_id=org_id,
            role=Role.VIEWER,
            permissions=frozenset(),
        )

    app.dependency_overrides[get_current_principal] = _no_read_principal
    try:
        resp = client.get("/analytics/cost-rates", headers=headers)
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["required"] == "read"


def test_cost_rates_on_the_keyless_default_reports_no_pricing():
    client, headers, _org = _app_with_settings(_make_settings(), InMemory_Usage_Store())

    body = client.get("/analytics/cost-rates", headers=headers).json()

    assert body["preset"] is None
    assert body["rates"] == []
    assert body["configured"] is False
    assert body["default_prompt_per_1k"] == "0.0"
    assert body["default_completion_per_1k"] == "0.0"
    # The alternatives are named, so a client need not hard-code them.
    assert PRESET in body["available_presets"]


def test_cost_rates_reports_the_selected_preset():
    settings = _make_settings()
    settings.cost_rate_preset = PRESET
    client, headers, _org = _app_with_settings(settings, InMemory_Usage_Store())

    body = client.get("/analytics/cost-rates", headers=headers).json()

    assert body["preset"] == PRESET
    assert body["configured"] is True
    assert len(body["rates"]) >= 2
    entry = next(r for r in body["rates"] if r["model"] == "llama-3.1-8b-instant")
    assert entry["provider"] == "groq"
    assert entry["source"] == "preset"
    # Exact decimal strings, never floats: $0.05 per 1M prompt tokens.
    assert entry["prompt_per_1k"] == "0.00005"
    assert entry["completion_per_1k"] == "0.00008"
    # Sorted by (provider, model) for a stable presentation.
    assert body["rates"] == sorted(body["rates"], key=lambda r: (r["provider"], r["model"]))


def test_cost_rates_marks_explicit_overrides_and_prices_the_report_with_them():
    """The reported rate and the charged rate come from one resolution, so they agree."""
    settings = _make_settings()
    settings.cost_rate_preset = PRESET
    settings.cost_rate_table_json = (
        '{"groq:llama-3.1-8b-instant": {"prompt": "1", "completion": "3"}}'
    )
    store = InMemory_Usage_Store()
    client, headers, org_id = _app_with_settings(settings, store)

    body = client.get("/analytics/cost-rates", headers=headers).json()
    by_model = {r["model"]: r for r in body["rates"]}

    assert by_model["llama-3.1-8b-instant"]["source"] == "override"
    assert by_model["llama-3.1-8b-instant"]["prompt_per_1k"] == "1"
    assert by_model["llama-3.3-70b-versatile"]["source"] == "preset"

    # And the usage report agrees that this deployment is priced.
    store.add(_usage_record(org_id, provider="groq", model="llama-3.1-8b-instant"))
    usage = client.get("/analytics/usage", headers=headers).json()
    assert usage["cost_rates_configured"] is True
