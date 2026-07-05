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
