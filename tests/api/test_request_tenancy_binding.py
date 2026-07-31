"""Usage must be attributed to the principal that caused it.

``enterprise/tenancy`` exists so consumers that cannot widen their own contract can still
tell who is acting: the ``RAG_Tool``, trace writes, and the ``Instrumented_Provider`` that
emits one usage record per completion. Two halves of that were never wired:

* ``set_current_user`` was defined and documented but **never called outside tests**, so
  every usage record was written with ``user_id=None``. The analytics "by user" breakdown
  groups on that field, so it collapsed to a single blank key holding the org's entire
  token count — the per-user cost attribution story was silently dead.
* Only the orchestrator entry points published the *org*. ``POST /query`` answers without
  entering an orchestrator, so it published neither, and its usage was recorded against
  ``NIL_ORG_ID`` — invisible in the caller's analytics even though the tokens were spent.

Both are now bound once, for every authorized route, in ``bind_request_tenancy``. These
tests drive the real app through ``TestClient`` so they exercise the actual dependency
graph: a unit test of the provider could not have caught either defect, because both were
failures to *establish* the context rather than to read it.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
from agentforge.enterprise.tenancy import NIL_ORG_ID
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.observability.usage.store import InMemory_Usage_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8
_MIN = datetime.min.replace(tzinfo=timezone.utc)
_MAX = datetime.max.replace(tzinfo=timezone.utc)


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


@pytest.fixture
def wired():
    """Return ``(client, headers, org_id, user_id, usage_store)`` for an OWNER principal.

    The usage store is shared between the ``Instrumented_Provider`` (via the app context)
    and the observability context, mirroring how ``main`` wires them, so a record emitted
    by a completion is the same record analytics would read.
    """
    settings = _make_settings()
    usage_store = InMemory_Usage_Store()

    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
        usage_store=usage_store,
    )
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    multi_ctx = build_multi_agent_context(
        settings, agent=agent_ctx, run_store=InMemory_Multi_Agent_Run_Store()
    )

    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = multi_ctx
    app.state.observability_context = build_observability_context(
        settings, app=app_ctx, usage_store=usage_store
    )
    headers, org_id, ctx = install_enterprise_auth(app, settings, role=Role.OWNER)

    # The helper does not surface the user id; recover it from the issued token so the
    # assertion compares against the real acting principal rather than a guess.
    claims = ctx.auth_service.verify(headers["Authorization"].split()[1])
    assert claims is not None
    user_id = claims.sub

    client = TestClient(app, raise_server_exceptions=False)

    # A corpus is required for any of these paths to reach the model at all: with nothing
    # retrieved, the RAG service refuses rather than generating (ungrounded answers are
    # opt-in), so no completion happens and no usage is emitted. The agent paths reach the
    # model the same way, through the RAG tool, because the keyless Fallback_Provider
    # selects the deterministic strategy which never calls the model for reasoning.
    ingested = client.post(
        "/documents",
        files={
            "file": (
                "policy.txt",
                b"New engineers receive a laptop and a display on day one.",
                "text/plain",
            )
        },
        headers=headers,
    )
    assert ingested.status_code == 201, ingested.text

    return client, headers, org_id, user_id, usage_store


def _records(usage_store, org_id):
    return usage_store.list_for_org(org_id, start=_MIN, end=_MAX)


class TestQueryAttribution:
    """``POST /query`` never enters an orchestrator, so it bound no tenancy at all."""

    def test_usage_is_attributed_to_the_callers_org(self, wired):
        client, headers, org_id, _user_id, usage_store = wired

        assert client.post("/query", json={"query": "what equipment do new engineers get"}, headers=headers).status_code == 200

        records = _records(usage_store, org_id)
        assert len(records) >= 1
        assert all(r.org_id == org_id for r in records)

    def test_usage_is_not_attributed_to_the_nil_org(self, wired):
        # The previous behaviour: tokens were spent but landed under NIL_ORG_ID, so the
        # analytics report for the real org showed nothing.
        client, headers, org_id, _user_id, usage_store = wired
        assert org_id != NIL_ORG_ID

        client.post("/query", json={"query": "what equipment do new engineers get"}, headers=headers)

        assert _records(usage_store, NIL_ORG_ID) == []

    def test_usage_is_attributed_to_the_acting_user(self, wired):
        client, headers, org_id, user_id, usage_store = wired

        client.post("/query", json={"query": "what equipment do new engineers get"}, headers=headers)

        records = _records(usage_store, org_id)
        assert all(r.user_id == user_id for r in records)
        # The specific symptom: a blank "by user" key.
        assert all(r.user_id is not None for r in records)

    def test_the_analytics_by_user_breakdown_is_no_longer_blank(self, wired):
        """The end-to-end symptom from the console: one breakdown row with no key."""
        client, headers, _org_id, user_id, _usage_store = wired
        client.post("/query", json={"query": "what equipment do new engineers get"}, headers=headers)

        report = client.get("/analytics/usage", headers=headers).json()

        assert report["total_tokens"] > 0
        keys = [row["key"] for row in report["by_user"]]
        assert keys == [str(user_id)]
        assert "" not in keys


class TestAgentRunAttribution:
    """The orchestrators bound the org; the user was still missing."""

    def test_agent_run_usage_carries_both_org_and_user(self, wired):
        client, headers, org_id, user_id, usage_store = wired

        assert (
            client.post("/agent/run", json={"message": "what equipment do new engineers get"}, headers=headers).status_code
            == 200
        )

        records = _records(usage_store, org_id)
        assert len(records) >= 1
        assert all(r.org_id == org_id and r.user_id == user_id for r in records)

    def test_multi_agent_run_usage_carries_both_org_and_user(self, wired):
        client, headers, org_id, user_id, usage_store = wired

        started = client.post(
            "/multi-agent/runs",
            json={"task": "what equipment do new engineers get"},
            headers=headers,
        )
        assert started.status_code == 201, started.text

        records = _records(usage_store, org_id)
        assert len(records) >= 1
        assert all(r.org_id == org_id and r.user_id == user_id for r in records)


class TestApiKeyPrincipal:
    """An API key is an unattributed caller; the org must still be right."""

    def test_api_key_usage_has_an_org_but_no_user(self, wired):
        client, headers, org_id, _user_id, usage_store = wired

        created = client.post(
            f"/orgs/{org_id}/api-keys", json={"role": "member"}, headers=headers
        )
        assert created.status_code == 201, created.text
        secret = created.json()["secret"]

        assert (
            client.post(
                "/query", json={"query": "what equipment do new engineers get"}, headers={"X-API-Key": secret}
            ).status_code
            == 200
        )

        records = _records(usage_store, org_id)
        assert len(records) >= 1
        # Right tenant, and honestly unattributed rather than blamed on a user.
        assert all(r.org_id == org_id for r in records)
        assert any(r.user_id is None for r in records)
