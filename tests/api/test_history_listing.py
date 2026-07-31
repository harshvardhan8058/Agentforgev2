"""Past work must be browsable, not merely addressable by an id you already hold.

Conversations, agent runs and multi-agent runs could each be *created* and then *fetched
by id*, but never enumerated. The id was returned once in the creation response, so the
moment it left the screen the thread or run was unreachable: the Conversations page was a
single button with nothing to show, and a finished run could not be reopened.

These tests drive the real app so they cover the routers, the schemas and both store
implementations' contract. Tenant scoping is asserted for each listing, because a list
endpoint is exactly where a missing ``org_id`` filter leaks another tenant's work.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.rbac import Role
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
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
    )


@pytest.fixture
def wired():
    """Return ``(client, headers, ctx)`` for a READ-capable owner over keyless doubles."""
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
    multi_ctx = build_multi_agent_context(
        settings, agent=agent_ctx, run_store=InMemory_Multi_Agent_Run_Store()
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = multi_ctx
    headers, _org_id, ctx = install_enterprise_auth(app, settings, role=Role.OWNER)
    return TestClient(app, raise_server_exceptions=False), headers, ctx


def _other_org_headers(ctx):
    headers, _org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other Org", email="other@example.com"
    )
    return headers


class TestConversationListing:
    def test_an_empty_workspace_lists_nothing(self, wired):
        client, headers, _ctx = wired

        response = client.get("/conversations", headers=headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_a_created_conversation_appears(self, wired):
        client, headers, _ctx = wired
        created = client.post("/conversations", headers=headers).json()

        rows = client.get("/conversations", headers=headers).json()

        assert [r["conversation_id"] for r in rows] == [created["conversation_id"]]
        assert rows[0]["message_count"] == 0

    def test_the_preview_carries_the_first_message(self, wired):
        # A conversation is otherwise identified only by a UUID, which says nothing
        # about which thread it is.
        client, headers, _ctx = wired
        cid = client.post("/conversations", headers=headers).json()["conversation_id"]
        client.post(
            f"/conversations/{cid}/messages",
            json={"role": "user", "content": "What does onboarding provide?"},
            headers=headers,
        )
        client.post(
            f"/conversations/{cid}/messages",
            json={"role": "assistant", "content": "A laptop and a display."},
            headers=headers,
        )

        rows = client.get("/conversations", headers=headers).json()

        assert rows[0]["preview"] == "What does onboarding provide?"
        assert rows[0]["message_count"] == 2

    def test_a_multi_line_preview_is_collapsed_to_one_line(self, wired):
        client, headers, _ctx = wired
        cid = client.post("/conversations", headers=headers).json()["conversation_id"]
        client.post(
            f"/conversations/{cid}/messages",
            json={"role": "user", "content": "first line\n\nsecond line"},
            headers=headers,
        )

        rows = client.get("/conversations", headers=headers).json()

        assert rows[0]["preview"] == "first line second line"

    def test_newest_first(self, wired):
        client, headers, _ctx = wired
        first = client.post("/conversations", headers=headers).json()["conversation_id"]
        second = client.post("/conversations", headers=headers).json()["conversation_id"]

        rows = client.get("/conversations", headers=headers).json()

        assert [r["conversation_id"] for r in rows] == [second, first]

    def test_limit_is_honoured(self, wired):
        client, headers, _ctx = wired
        for _ in range(3):
            client.post("/conversations", headers=headers)

        rows = client.get("/conversations?limit=2", headers=headers).json()

        assert len(rows) == 2

    def test_an_out_of_range_limit_is_rejected(self, wired):
        client, headers, _ctx = wired

        assert client.get("/conversations?limit=0", headers=headers).status_code == 422

    def test_another_orgs_conversations_are_invisible(self, wired):
        client, headers, ctx = wired
        client.post("/conversations", headers=headers)

        rows = client.get("/conversations", headers=_other_org_headers(ctx)).json()

        assert rows == []

    def test_no_credential_is_401(self, wired):
        client, _headers, _ctx = wired

        assert client.get("/conversations").status_code == 401


class TestAgentRunListing:
    def test_an_empty_workspace_lists_nothing(self, wired):
        client, headers, _ctx = wired

        assert client.get("/agent/runs", headers=headers).json() == []

    def test_a_completed_run_appears_with_its_step_counts(self, wired):
        client, headers, _ctx = wired
        client.post(
            "/documents",
            files={"file": ("p.txt", b"Engineers receive a laptop.", "text/plain")},
            headers=headers,
        )
        assert (
            client.post(
                "/agent/run", json={"message": "what do engineers receive"}, headers=headers
            ).status_code
            == 200
        )

        rows = client.get("/agent/runs", headers=headers).json()

        assert len(rows) == 1
        assert rows[0]["step_count"] > 0
        # The keyless agent grounds through the RAG tool, so at least one tool call.
        assert rows[0]["tool_call_count"] >= 1

    def test_the_listed_run_id_resolves_to_its_trace(self, wired):
        # The point of the listing: the id it returns must be usable.
        client, headers, _ctx = wired
        client.post(
            "/documents",
            files={"file": ("p.txt", b"Engineers receive a laptop.", "text/plain")},
            headers=headers,
        )
        client.post("/agent/run", json={"message": "what"}, headers=headers)

        run_id = client.get("/agent/runs", headers=headers).json()[0]["run_id"]
        trace = client.get(f"/agent/runs/{run_id}/trace", headers=headers)

        assert trace.status_code == 200
        assert trace.json()["entries"]

    def test_another_orgs_runs_are_invisible(self, wired):
        client, headers, ctx = wired
        client.post(
            "/documents",
            files={"file": ("p.txt", b"Engineers receive a laptop.", "text/plain")},
            headers=headers,
        )
        client.post("/agent/run", json={"message": "what"}, headers=headers)

        rows = client.get("/agent/runs", headers=_other_org_headers(ctx)).json()

        assert rows == []

    def test_no_credential_is_401(self, wired):
        client, _headers, _ctx = wired

        assert client.get("/agent/runs").status_code == 401


class TestMultiAgentRunListing:
    def test_an_empty_workspace_lists_nothing(self, wired):
        client, headers, _ctx = wired

        assert client.get("/multi-agent/runs", headers=headers).json() == []

    def test_a_started_run_appears_with_its_task(self, wired):
        # The task is what identifies a run to a person; the id is a generated UUID.
        client, headers, _ctx = wired
        started = client.post(
            "/multi-agent/runs", json={"task": "Draft a briefing"}, headers=headers
        )
        assert started.status_code == 201, started.text

        rows = client.get("/multi-agent/runs", headers=headers).json()

        assert len(rows) == 1
        assert rows[0]["task"] == "Draft a briefing"
        assert rows[0]["run_id"] == started.json()["run_id"]
        assert rows[0]["status"]

    def test_the_listed_run_id_resolves_to_its_result(self, wired):
        client, headers, _ctx = wired
        client.post("/multi-agent/runs", json={"task": "Draft"}, headers=headers)

        run_id = client.get("/multi-agent/runs", headers=headers).json()[0]["run_id"]

        assert client.get(f"/multi-agent/runs/{run_id}", headers=headers).status_code == 200

    def test_the_listing_route_is_not_shadowed_by_the_by_id_route(self, wired):
        """``/multi-agent/runs`` must not be captured as ``/multi-agent/runs/{run_id}``."""
        client, headers, _ctx = wired

        response = client.get("/multi-agent/runs", headers=headers)

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_another_orgs_runs_are_invisible(self, wired):
        client, headers, ctx = wired
        client.post("/multi-agent/runs", json={"task": "Draft"}, headers=headers)

        rows = client.get("/multi-agent/runs", headers=_other_org_headers(ctx)).json()

        assert rows == []

    def test_no_credential_is_401(self, wired):
        client, _headers, _ctx = wired

        assert client.get("/multi-agent/runs").status_code == 401
