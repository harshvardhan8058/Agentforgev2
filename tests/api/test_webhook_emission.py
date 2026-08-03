"""API tests proving the webhook seam has real callers.

This repository has produced the defect once already — a ``Tracing_Exporter`` that was wired,
documented, and called by nothing — so a new seam is not finished until a test drives the
*endpoint* and observes a delivery. Every emission point is exercised here through the real app:
a run, a streamed run, a multi-agent run, an ingestion, and a guardrail block (whose event has to
survive the request *raising*, which is the interesting one).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_guardrail_pipeline,
    build_multi_agent_context,
    build_observability_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.rbac import Role
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store
from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.security import EVENT_HEADER
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8
_ALL_EVENTS = tuple(
    e for e in Webhook_Event if e is not Webhook_Event.PING
)


def _wire(*, blocklist: list[str] | None = None):
    """Return ``(client, headers, org_id, ctx, subscriptions, transport)``."""
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
        guardrail_blocklist_json=json.dumps(blocklist) if blocklist else None,
    )
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
    deliveries = InMemory_Webhook_Delivery_Store()
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    transport = Recording_Webhook_Transport()
    app = create_app(settings)
    app.state.settings = settings
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = build_multi_agent_context(settings, agent=agent_ctx)
    app.state.observability_context = build_observability_context(
        settings,
        app=app_ctx,
        trace_recorder=InMemory_Trace_Recorder(),
        guardrail_pipeline=build_guardrail_pipeline(settings),
        webhook_subscription_store=subscriptions,
        webhook_delivery_store=deliveries,
        webhook_transport=transport,
        webhook_emitter=Webhook_Emitter(
            subscriptions, deliveries, transport, max_attempts=1
        ),
    )
    headers, org_id, ctx = install_enterprise_auth(
        app, settings, email="owner@example.com"
    )
    return (
        TestClient(app, raise_server_exceptions=False),
        headers,
        org_id,
        ctx,
        subscriptions,
        transport,
    )


def _subscribe(subscriptions, org_id, *, events=_ALL_EVENTS):
    return subscriptions.create(
        org_id,
        url="http://localhost:9111/hook",
        secret="signing-key",
        events=tuple(events),
        description=None,
        active=True,
    )


def _delivered(transport) -> list[tuple[str, dict]]:
    """Return ``(event_name, data)`` for every delivery the transport saw."""
    out = []
    for _url, body, headers in transport.calls:
        envelope = json.loads(body)
        assert headers[EVENT_HEADER] == envelope["event"]
        out.append((envelope["event"], envelope["data"]))
    return out


@pytest.fixture
def wired():
    return _wire()


# --- agent runs -------------------------------------------------------------------


def test_a_completed_agent_run_emits_run_completed(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    response = client.post("/agent/run", headers=headers, json={"message": "hello"})
    assert response.status_code == 200

    events = _delivered(transport)
    assert [name for name, _data in events] == ["run.completed"]
    data = events[0][1]
    assert data["run_id"] == response.json()["run_id"]
    assert data["kind"] == "agent"
    assert data["conversation_id"] == response.json()["conversation_id"]
    assert data["termination_reason"] == response.json()["termination_reason"]
    # Every key is present even when the fact does not apply, so one parser handles the event.
    assert set(data) == {
        "run_id",
        "kind",
        "conversation_id",
        "termination_reason",
        "citation_count",
    }


def test_a_streamed_agent_run_emits_the_same_event_shape(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    with client.stream(
        "POST", "/agent/stream", headers=headers, json={"message": "hello"}
    ) as response:
        assert response.status_code == 200
        frames = "".join(response.iter_text())
    assert "completion" in frames

    events = _delivered(transport)
    assert [name for name, _data in events] == ["run.completed"]
    assert events[0][1]["kind"] == "agent"
    assert set(events[0][1]) == {
        "run_id",
        "kind",
        "conversation_id",
        "termination_reason",
        "citation_count",
    }


def test_a_run_emits_nothing_when_the_org_subscribes_to_another_event(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id, events=(Webhook_Event.DOCUMENT_INGESTED,))
    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200
    assert transport.attempts == 0


def test_a_run_never_reaches_another_organizations_subscription(wired):
    client, headers, _org_id, ctx, subscriptions, transport = wired
    _other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other", email="other@example.com"
    )
    _subscribe(subscriptions, other_org)

    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200
    assert transport.attempts == 0


# --- multi-agent runs -------------------------------------------------------------


def test_a_multi_agent_run_emits_its_outcome(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    response = client.post(
        "/multi-agent/runs", headers=headers, json={"task": "Summarise the corpus"}
    )
    assert response.status_code == 201

    events = _delivered(transport)
    assert len(events) == 1
    name, data = events[0]
    assert name in {"run.completed", "run.failed"}
    assert data["kind"] == "multi_agent"
    assert data["run_id"] == response.json()["run_id"]


# --- ingestion --------------------------------------------------------------------


def test_ingesting_a_document_emits_document_ingested(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("notes.md", b"# Title\n\nSome content here.", "text/markdown")},
    )
    assert response.status_code == 201

    events = _delivered(transport)
    assert [name for name, _data in events] == ["document.ingested"]
    data = events[0][1]
    assert data["document_id"] == response.json()["document_id"]
    assert data["filename"] == "notes.md"
    assert data["chunk_count"] == response.json()["chunk_count"]
    assert data["duplicate"] is False


def test_a_duplicate_upload_still_emits_and_says_so(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    payload = {"file": ("notes.md", b"# Title\n\nSome content.", "text/markdown")}

    assert client.post("/documents", headers=headers, files=payload).status_code == 201
    assert client.post("/documents", headers=headers, files=payload).status_code == 201

    events = _delivered(transport)
    assert [data["duplicate"] for _name, data in events] == [False, True]


def test_a_rejected_upload_emits_nothing(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    refused = client.post(
        "/documents",
        headers=headers,
        files={"file": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")},
    )
    assert refused.status_code == 415
    assert transport.attempts == 0


# --- guardrail blocks (the deferred-work path) ------------------------------------


def test_a_blocked_query_emits_guardrail_blocked_after_the_refusal():
    """The refusal is *raised*, so this event rides the deferred-work seam, not a background task."""
    client, headers, org_id, _ctx, subscriptions, transport = _wire(
        blocklist=["forbidden-term"]
    )
    _subscribe(subscriptions, org_id)

    refused = client.post(
        "/query", headers=headers, json={"query": "tell me the forbidden-term"}
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "guardrail_blocked"

    events = _delivered(transport)
    assert [name for name, _data in events] == ["guardrail.blocked"]
    data = events[0][1]
    assert data["surface"] == "query"
    assert data["reason"] == refused.json()["error"]["details"]["reason"]


def test_a_blocked_agent_run_emits_guardrail_blocked():
    client, headers, org_id, _ctx, subscriptions, transport = _wire(
        blocklist=["forbidden-term"]
    )
    _subscribe(subscriptions, org_id)

    refused = client.post(
        "/agent/run", headers=headers, json={"message": "the forbidden-term again"}
    )
    assert refused.status_code == 400

    events = _delivered(transport)
    assert [name for name, _data in events] == ["guardrail.blocked"]
    assert events[0][1]["surface"] == "agent.run"


def test_a_blocked_multi_agent_run_emits_guardrail_blocked():
    client, headers, org_id, _ctx, subscriptions, transport = _wire(
        blocklist=["forbidden-term"]
    )
    _subscribe(subscriptions, org_id)

    refused = client.post(
        "/multi-agent/runs", headers=headers, json={"task": "do the forbidden-term"}
    )
    assert refused.status_code == 400

    events = _delivered(transport)
    assert [name for name, _data in events] == ["guardrail.blocked"]
    assert events[0][1]["surface"] == "multi_agent.run"


def test_a_blocked_request_emits_nothing_when_nobody_subscribed():
    client, headers, _org_id, _ctx, _subscriptions, transport = _wire(
        blocklist=["forbidden-term"]
    )
    refused = client.post(
        "/query", headers=headers, json={"query": "the forbidden-term"}
    )
    assert refused.status_code == 400
    assert transport.attempts == 0


def test_a_broken_subscriber_endpoint_never_affects_the_run():
    """The whole invariant: a tenant's endpoint cannot fail, slow, or corrupt the work."""
    settings_transport = Recording_Webhook_Transport(succeed_from_attempt=None)
    client, headers, org_id, _ctx, subscriptions, transport = _wire()
    # Swap in a transport that always fails, on the emitter the app actually holds.
    emitter = client.app.state.observability_context.webhook_emitter
    emitter._transport = settings_transport
    _subscribe(subscriptions, org_id)

    response = client.post("/agent/run", headers=headers, json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["answer"]
    assert settings_transport.attempts == 1
    logged = client.app.state.observability_context.webhook_delivery_store
    rows = logged.list_for_subscription(
        org_id, subscriptions.list_for_org(org_id)[0].id
    )
    assert [row.status for row in rows] == ["failed"]
