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
from agentforge.webhooks.dispatcher import Webhook_Dispatcher
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.outbox import InMemory_Webhook_Outbox
from agentforge.webhooks.security import EVENT_HEADER, IDEMPOTENCY_HEADER
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport
from agentforge.webhooks.worker import Webhook_Delivery_Worker

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
    outbox = InMemory_Webhook_Outbox()
    transport = Recording_Webhook_Transport()
    emitter = Webhook_Emitter(deliveries, transport)
    # The worker is driven by hand (`_drain`) rather than started: delivery is asynchronous now,
    # so a test that asserted straight after the response would be racing its own subject.
    worker = Webhook_Delivery_Worker(outbox, subscriptions, emitter, batch_size=50)
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
        webhook_outbox=outbox,
        webhook_transport=transport,
        webhook_emitter=emitter,
        webhook_dispatcher=Webhook_Dispatcher(subscriptions, outbox),
        webhook_worker=worker,
    )
    headers, org_id, ctx = install_enterprise_auth(
        app, settings, email="owner@example.com"
    )
    app.state.run_migrations_on_startup = False
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


def _drain(client) -> None:
    """Run the delivery worker until the queue is empty.

    Enqueueing is what a request does; *delivering* is what the worker does, later. Draining makes
    the assertion deterministic rather than dependent on a background thread's timing — and it
    exercises the real worker, not a shortcut around it.
    """
    worker = client.app.state.observability_context.webhook_worker
    for _ in range(10):
        if worker.run_once() == 0:
            return


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

    _drain(client)
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

    _drain(client)
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
    _drain(client)
    assert transport.attempts == 0


def test_a_run_never_reaches_another_organizations_subscription(wired):
    client, headers, _org_id, ctx, subscriptions, transport = wired
    _other_headers, other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other", email="other@example.com"
    )
    _subscribe(subscriptions, other_org)

    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200
    _drain(client)
    assert transport.attempts == 0


# --- multi-agent runs -------------------------------------------------------------


def test_a_multi_agent_run_emits_its_outcome(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    response = client.post(
        "/multi-agent/runs", headers=headers, json={"task": "Summarise the corpus"}
    )
    assert response.status_code == 201

    _drain(client)
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

    _drain(client)
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

    _drain(client)
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
    _drain(client)
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

    _drain(client)
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

    _drain(client)
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

    _drain(client)
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
    _drain(client)
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
    # Stronger than before: the request did not dial the endpoint AT ALL. It wrote a durable row
    # and returned, so a subscriber cannot affect the run's latency even in principle.
    assert settings_transport.attempts == 0
    outbox = client.app.state.observability_context.webhook_outbox
    assert outbox.pending_count(org_id) == 1

    # When the worker does run, the failure is recorded and the event is kept for another attempt
    # — the difference between a webhook that is late and one that is lost.
    _drain(client)
    assert settings_transport.attempts == 1
    entry = outbox.list_for_org(org_id)[0]
    assert entry.status == "pending"
    assert entry.attempts == 1
    assert entry.next_attempt_at > entry.created_at

    logged = client.app.state.observability_context.webhook_delivery_store
    rows = logged.list_for_subscription(
        org_id, subscriptions.list_for_org(org_id)[0].id
    )
    assert [row.status for row in rows] == ["failed"]



# --- what durable delivery buys ---------------------------------------------------
#
# These are the properties that were impossible before the outbox, and they are asserted through
# the API because that is where a customer experiences them.


def test_a_run_enqueues_durably_and_returns_before_anything_is_dialled(wired):
    """The request's cost no longer depends on a consumer's latency, at all."""
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200

    outbox = client.app.state.observability_context.webhook_outbox
    assert outbox.pending_count(org_id) == 1
    assert transport.attempts == 0  # nothing dialled on the request path

    _drain(client)
    assert transport.attempts == 1
    assert outbox.list_for_org(org_id)[0].status == "delivered"


def test_an_event_survives_a_restart_between_enqueue_and_delivery(wired):
    """The point of the whole feature: a deploy mid-delivery no longer loses the event.

    Simulated the only way a test can: the row is enqueued, the process that would have delivered
    it never does, and a *new* worker over the same store picks it up and delivers it.
    """
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200

    ctx = client.app.state.observability_context
    assert transport.attempts == 0

    # A different worker instance, as a restarted process would have.
    from agentforge.webhooks.worker import Webhook_Delivery_Worker

    replacement = Webhook_Delivery_Worker(
        ctx.webhook_outbox, ctx.webhook_subscription_store, ctx.webhook_emitter
    )
    assert replacement.run_once() == 1

    assert transport.attempts == 1
    assert ctx.webhook_outbox.list_for_org(org_id)[0].status == "delivered"


def test_a_paused_subscription_receives_what_it_missed_when_it_resumes(wired):
    """Pausing holds events rather than discarding them, which "off-and-on again" depends on."""
    client, headers, org_id, _ctx, subscriptions, transport = wired
    subscription = _subscribe(subscriptions, org_id)

    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200
    subscriptions.update(org_id, subscription.id, active=False)
    _drain(client)
    assert transport.attempts == 0  # held, not delivered — and not dropped either

    subscriptions.update(org_id, subscription.id, active=True)
    # Past the hold's reschedule.
    worker = client.app.state.observability_context.webhook_worker
    worker._clock = lambda: __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ) + __import__("datetime").timedelta(hours=2)
    worker.run_once()

    assert transport.attempts == 1


def test_every_event_carries_the_idempotency_key_a_consumer_deduplicates_on(wired):
    client, headers, org_id, _ctx, subscriptions, transport = wired
    subscription = _subscribe(subscriptions, org_id)

    response = client.post("/agent/run", headers=headers, json={"message": "hi"})
    _drain(client)

    _url, body, headers_sent = transport.calls[0]
    run_id = response.json()["run_id"]
    expected = f"run.completed:{run_id}:{subscription.id}"
    assert headers_sent[IDEMPOTENCY_HEADER] == expected
    assert json.loads(body)["idempotency_key"] == expected


def test_re_streaming_a_multi_agent_run_repeats_one_logical_event(wired):
    """Re-streaming genuinely re-runs, so a consumer needs the two to be recognisably the same."""
    client, headers, org_id, _ctx, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)

    created = client.post(
        "/multi-agent/runs", headers=headers, json={"task": "Summarise the corpus"}
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    with client.stream(
        "POST", f"/multi-agent/runs/{run_id}/stream", headers=headers
    ) as response:
        assert response.status_code == 200
        "".join(response.iter_text())

    _drain(client)

    keys = {h[IDEMPOTENCY_HEADER] for _u, _b, h in transport.calls}
    # Two deliveries, one logical occurrence: a consumer keying on this acts once.
    assert len(transport.calls) == 2
    assert len(keys) == 1
