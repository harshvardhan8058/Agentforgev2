"""API tests: the webhook emission points are actually wired to real endpoints.

This file exists because of a defect this repository has already produced once: a complete,
well-tested abstraction (``Tracing_Exporter``) that **nothing called**. Unit tests on
``Webhook_Emitter`` prove it delivers when invoked; only these tests prove it is invoked.

Each case drives a real endpoint through the real app and asserts on the delivery log:

* ``POST /agent/run`` and ``POST /agent/stream`` → ``run.completed`` (or ``run.failed``);
* ``POST /multi-agent/runs`` → ``run.completed`` for the multi-agent kind;
* ``POST /documents`` → ``document.ingested``;
* a guardrail refusal on ``POST /query``, ``/agent/run`` and ``/multi-agent/runs`` →
  ``guardrail.blocked``, even though the caller receives a 400 (the emission is deferred onto
  the error response, which is the whole reason ``defer_after_error`` exists);
* a subscriber who did not ask for an event never receives it, and neither does another tenant.

``TestClient`` runs FastAPI background tasks synchronously before returning, so an assertion
made after the call sees the emission the production path performs after the response.
"""

from __future__ import annotations

import json
import uuid

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
from agentforge.multiagent.approval import Auto_Approve_Policy
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.observability.guardrails.base import (
    Guardrail,
    Guardrail_Decision,
    Guardrail_Pipeline,
    Guardrail_Result,
)
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store
from agentforge.webhooks.emitter import SIGNATURE_HEADER, Webhook_Emitter
from agentforge.webhooks.security import verify_signature
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8
_BLOCK_TOKEN = "BLOCKME"
SECRET = "whsec_emission_test"

ALL_EVENTS = (
    "run.completed",
    "run.failed",
    "document.ingested",
    "guardrail.blocked",
)


class _Block_Guardrail(Guardrail):
    """Blocks content containing the sentinel, with a reason a subscriber should receive."""

    @property
    def name(self) -> str:
        return "test_block"

    def check(self, content: str) -> Guardrail_Result:
        if _BLOCK_TOKEN in content:
            return Guardrail_Result(Guardrail_Decision.BLOCK, reason="contains blocked token")
        return Guardrail_Result(Guardrail_Decision.ALLOW)


class Wired:
    def __init__(self, client, headers, org_id, ctx, transport, subscriptions, deliveries):
        self.client = client
        self.headers = headers
        self.org_id = org_id
        self.ctx = ctx
        self.transport = transport
        self.subscriptions = subscriptions
        self.deliveries = deliveries

    def subscribe(self, *events: str, org_id=None):
        return self.subscriptions.create(
            org_id or self.org_id,
            url="http://localhost:9100/hook",
            events=events or ALL_EVENTS,
            secret=SECRET,
        )

    def delivered(self, subscription) -> list:
        return self.deliveries.list_for_subscription(
            subscription.org_id, subscription.id, limit=50
        )

    def events_seen(self, subscription) -> list[str]:
        return [d.event_type for d in self.delivered(subscription)]

    def bodies(self) -> list[dict]:
        return [json.loads(call["body"]) for call in self.transport.calls]


@pytest.fixture
def wired() -> Wired:
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
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
    # Paired, so deleting a subscription sweeps its delivery log exactly as migration 0015's
    # ON DELETE CASCADE does. An unpaired fake would let a test assert the documented behaviour
    # and pass while the real store did something else.
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    transport = Recording_Webhook_Transport()
    app = create_app(settings)
    app.state.settings = settings
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = build_multi_agent_context(
        settings,
        agent=agent_ctx,
        run_store=InMemory_Multi_Agent_Run_Store(),
        approval_policy=Auto_Approve_Policy(),
    )
    app.state.observability_context = build_observability_context(
        settings,
        app=app_ctx,
        trace_recorder=InMemory_Trace_Recorder(),
        guardrail_pipeline=Guardrail_Pipeline([_Block_Guardrail()]),
        webhook_subscription_store=subscriptions,
        webhook_delivery_store=deliveries,
        webhook_transport=transport,
        webhook_emitter=Webhook_Emitter(
            subscriptions, deliveries, transport, sleep=lambda _s: None
        ),
    )
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    client = TestClient(app, raise_server_exceptions=False)
    return Wired(client, headers, org_id, ctx, transport, subscriptions, deliveries)


# --- runs --------------------------------------------------------------------------


def test_a_completed_single_agent_run_is_reported(wired: Wired):
    subscription = wired.subscribe("run.completed")

    response = wired.client.post(
        "/agent/run", json={"message": "hello"}, headers=wired.headers
    )

    assert response.status_code == 200
    assert wired.events_seen(subscription) == ["run.completed"]
    (body,) = wired.bodies()
    assert body["event"] == "run.completed"
    assert body["data"]["run_id"] == response.json()["run_id"]
    assert body["data"]["kind"] == "single_agent"
    assert body["data"]["conversation_id"] == response.json()["conversation_id"]
    assert body["data"]["termination_reason"] == response.json()["termination_reason"]
    assert body["data"]["citation_count"] == len(response.json()["citations"])


def test_the_run_payload_carries_no_answer_text(wired: Wired):
    """A webhook endpoint is outside the trust boundary; an answer may quote a private corpus."""
    wired.subscribe("run.completed")

    response = wired.client.post(
        "/agent/run", json={"message": "hello"}, headers=wired.headers
    )

    (body,) = wired.bodies()
    answer = response.json()["answer"]
    assert "answer" not in body["data"]
    assert answer and answer not in json.dumps(body)


def test_a_run_delivery_is_signed_with_the_subscription_secret(wired: Wired):
    wired.subscribe("run.completed")

    wired.client.post("/agent/run", json={"message": "hello"}, headers=wired.headers)

    call = wired.transport.calls[0]
    assert verify_signature(SECRET, call["body"], call["headers"][SIGNATURE_HEADER]) is True


def test_a_streamed_run_is_reported_after_the_terminal_frame(wired: Wired):
    """A stream has no response to attach a background task to, so it uses the completion hook."""
    subscription = wired.subscribe("run.completed")

    with wired.client.stream(
        "POST", "/agent/stream", json={"message": "hello"}, headers=wired.headers
    ) as response:
        assert response.status_code == 200
        frames = "".join(response.iter_text())

    assert "event: completion" in frames
    assert wired.events_seen(subscription) == ["run.completed"]
    assert wired.bodies()[0]["data"]["kind"] == "single_agent"


def test_a_completed_multi_agent_run_is_reported(wired: Wired):
    subscription = wired.subscribe("run.completed")

    response = wired.client.post(
        "/multi-agent/runs", json={"task": "summarise the corpus"}, headers=wired.headers
    )

    assert response.status_code == 201
    assert wired.events_seen(subscription) == ["run.completed"]
    (body,) = wired.bodies()
    assert body["data"]["kind"] == "multi_agent"
    assert body["data"]["run_id"] == response.json()["run_id"]
    assert body["data"]["termination_reason"] == "completed"


def test_a_subscriber_who_wants_only_failures_hears_nothing_from_a_success(wired: Wired):
    subscription = wired.subscribe("run.failed")

    wired.client.post("/agent/run", json={"message": "hello"}, headers=wired.headers)

    assert wired.events_seen(subscription) == []
    assert wired.transport.calls == []


def test_the_success_rule_is_one_rule_across_both_run_kinds(wired: Wired):
    """`final-answer` and `completed` are the two accepted terminal reasons; nothing else is."""
    from agentforge.webhooks.events import SUCCESSFUL_TERMINATIONS

    assert SUCCESSFUL_TERMINATIONS == frozenset({"final-answer", "completed"})


# --- documents ---------------------------------------------------------------------


def test_an_ingested_document_is_reported(wired: Wired):
    subscription = wired.subscribe("document.ingested")

    response = wired.client.post(
        "/documents",
        files={"file": ("notes.md", b"# Heading\n\nSome ingestible prose.", "text/markdown")},
        headers=wired.headers,
    )

    assert response.status_code == 201
    assert wired.events_seen(subscription) == ["document.ingested"]
    (body,) = wired.bodies()
    assert body["data"]["document_id"] == response.json()["document_id"]
    assert body["data"]["filename"] == "notes.md"
    assert body["data"]["chunk_count"] == response.json()["chunk_count"]
    assert body["data"]["duplicate"] is False


def test_a_duplicate_upload_says_so_in_the_payload(wired: Wired):
    """The corpus did not grow, so a downstream indexer should skip it."""
    subscription = wired.subscribe("document.ingested")
    upload = {"file": ("notes.md", b"# Heading\n\nSome ingestible prose.", "text/markdown")}

    wired.client.post("/documents", files=upload, headers=wired.headers)
    wired.client.post("/documents", files=upload, headers=wired.headers)

    assert wired.events_seen(subscription) == ["document.ingested"] * 2
    assert [b["data"]["duplicate"] for b in wired.bodies()] == [False, True]


def test_a_rejected_upload_reports_nothing(wired: Wired):
    subscription = wired.subscribe("document.ingested")

    response = wired.client.post(
        "/documents",
        files={"file": ("empty.md", b"", "text/markdown")},
        headers=wired.headers,
    )

    assert response.status_code == 400
    assert wired.events_seen(subscription) == []


# --- guardrail blocks --------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "payload", "surface"),
    [
        ("/query", {"query": f"do {_BLOCK_TOKEN}"}, "query"),
        ("/agent/run", {"message": f"do {_BLOCK_TOKEN}"}, "agent.run"),
        ("/multi-agent/runs", {"task": f"do {_BLOCK_TOKEN}"}, "multi_agent.run"),
    ],
)
def test_a_guardrail_block_is_reported_even_though_the_caller_gets_a_400(
    wired: Wired, path: str, payload: dict, surface: str
):
    """The emission is deferred onto the error response — the reason defer_after_error exists."""
    subscription = wired.subscribe("guardrail.blocked")

    response = wired.client.post(path, json=payload, headers=wired.headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "guardrail_blocked"
    assert wired.events_seen(subscription) == ["guardrail.blocked"]
    (body,) = wired.bodies()
    assert body["data"] == {
        "stage": "input",
        "surface": surface,
        "reason": "contains blocked token",
    }


def test_the_blocked_payload_never_carries_the_offending_input(wired: Wired):
    """The input is exactly the content a guardrail exists to keep from being passed on."""
    wired.subscribe("guardrail.blocked")

    wired.client.post(
        "/query", json={"query": f"leak {_BLOCK_TOKEN} my secrets"}, headers=wired.headers
    )

    assert _BLOCK_TOKEN not in json.dumps(wired.bodies())


def test_an_allowed_request_reports_no_block(wired: Wired):
    subscription = wired.subscribe("guardrail.blocked")

    wired.client.post("/query", json={"query": "perfectly fine"}, headers=wired.headers)

    assert wired.events_seen(subscription) == []


# --- tenancy and the quiet path ---------------------------------------------------


def test_another_tenant_never_receives_this_org_s_run(wired: Wired):
    other_headers, other_org = issue_principal_headers(
        wired.ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )
    outsider = wired.subscribe("run.completed", org_id=other_org)
    insider = wired.subscribe("run.completed")

    wired.client.post("/agent/run", json={"message": "hello"}, headers=wired.headers)

    assert wired.events_seen(insider) == ["run.completed"]
    assert wired.events_seen(outsider) == []
    assert other_headers  # the other principal exists; it simply hears nothing


def test_with_no_subscription_a_run_sends_nothing(wired: Wired):
    """The common case: webhooks configured by nobody must add no outbound work."""
    response = wired.client.post(
        "/agent/run", json={"message": "hello"}, headers=wired.headers
    )

    assert response.status_code == 200
    assert wired.transport.calls == []


def test_a_failing_endpoint_does_not_fail_the_run(wired: Wired):
    """A finished run is finished; a webhook problem cannot retroactively break it."""
    subscription = wired.subscribe("run.completed")
    wired.transport.status = 500

    response = wired.client.post(
        "/agent/run", json={"message": "hello"}, headers=wired.headers
    )

    assert response.status_code == 200
    (delivery,) = wired.delivered(subscription)
    assert delivery.status == "failed"
    assert delivery.attempts == 3


def test_an_unwired_observability_graph_does_not_break_a_run():
    """The degrading accessor: a partially-wired app must still run agents."""
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    app = create_app(settings)
    app.state.settings = settings
    app.state.app_context = app_ctx
    app.state.agent_context = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    # Deliberately no observability_context at all.
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/agent/run", json={"message": "hi"}, headers=headers).status_code == 200


def test_a_delivery_id_is_unique_per_delivery(wired: Wired):
    """Consumers deduplicate on it, so two deliveries must never share one."""
    first = wired.subscribe("run.completed")
    second = wired.subscribe("run.completed")

    wired.client.post("/agent/run", json={"message": "hello"}, headers=wired.headers)

    ids = {d.id for d in wired.delivered(first)} | {d.id for d in wired.delivered(second)}
    assert len(ids) == 2
    assert {uuid.UUID(b["id"]) for b in wired.bodies()} == ids



# --- one event name, one payload shape --------------------------------------------
#
# `webhooks/events.py` exists so routers cannot classify the same outcome differently. That has
# to cover the payload as well as the event name: a key omitted when its value is unknown would
# make one event carry different shapes depending on which router produced it, and would force a
# consumer to distinguish "no citations" from "not reported".

RUN_PAYLOAD_KEYS = {
    "run_id",
    "kind",
    "termination_reason",
    "conversation_id",
    "citation_count",
}


def test_the_run_payload_has_the_same_keys_from_every_emission_point(wired: Wired):
    wired.subscribe("run.completed")

    wired.client.post("/agent/run", json={"message": "hello"}, headers=wired.headers)
    wired.client.post(
        "/multi-agent/runs", json={"task": "summarise"}, headers=wired.headers
    )
    with wired.client.stream(
        "POST", "/agent/stream", json={"message": "hello"}, headers=wired.headers
    ) as response:
        "".join(response.iter_text())

    bodies = wired.bodies()
    assert len(bodies) == 3
    for body in bodies:
        assert set(body["data"]) == RUN_PAYLOAD_KEYS, body["data"]


def test_an_unknown_citation_count_is_an_explicit_null_not_a_missing_key(wired: Wired):
    from agentforge.webhooks.events import RUN_KIND_MULTI, emit_run_outcome

    subscription = wired.subscribe("run.completed")
    emitter = wired.client.app.state.observability_context.webhook_emitter

    emit_run_outcome(
        emitter,
        wired.org_id,
        run_id="r1",
        kind=RUN_KIND_MULTI,
        termination_reason="completed",
    )

    assert wired.events_seen(subscription) == ["run.completed"]
    (body,) = wired.bodies()
    assert set(body["data"]) == RUN_PAYLOAD_KEYS
    assert body["data"]["citation_count"] is None
    assert body["data"]["conversation_id"] is None
