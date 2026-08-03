"""API tests: a budget threshold actually notifies, from a real spending request.

The unit tests pin the claim logic; these prove the seam has callers. A threshold notification
that only worked when called directly would be the same defect class this codebase has already
produced once (a trace exporter nothing invoked), so every assertion here goes through an
endpoint an operator's traffic would hit — including the ``402`` path, where the notification has
to survive the request *raising*.
"""

from __future__ import annotations

import json
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
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.store import InMemory_Usage_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store
from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.dispatcher import Webhook_Dispatcher
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.outbox import InMemory_Webhook_Outbox
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport
from agentforge.webhooks.worker import Webhook_Delivery_Worker

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


@pytest.fixture
def wired():
    """Return ``(client, headers, org_id, usage_store, subscriptions, transport)``."""
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
        # No spend cache, so a test's seeded usage is visible to the very next request.
        budget_cache_seconds=0.0,
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
    usage_store = InMemory_Usage_Store()
    deliveries = InMemory_Webhook_Delivery_Store()
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    outbox = InMemory_Webhook_Outbox()
    transport = Recording_Webhook_Transport()
    emitter = Webhook_Emitter(deliveries, transport)
    app = create_app(settings)
    app.state.settings = settings
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = build_multi_agent_context(settings, agent=agent_ctx)
    app.state.observability_context = build_observability_context(
        settings,
        app=app_ctx,
        usage_store=usage_store,
        trace_recorder=InMemory_Trace_Recorder(),
        webhook_subscription_store=subscriptions,
        webhook_delivery_store=deliveries,
        webhook_outbox=outbox,
        webhook_transport=transport,
        webhook_emitter=emitter,
        webhook_dispatcher=Webhook_Dispatcher(subscriptions, outbox),
        webhook_worker=Webhook_Delivery_Worker(
            outbox, subscriptions, emitter, batch_size=50
        ),
    )
    headers, org_id, _ctx = install_enterprise_auth(
        app, settings, email="owner@example.com"
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, headers, org_id, usage_store, subscriptions, transport


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


def _subscribe(subscriptions, org_id):
    return subscriptions.create(
        org_id,
        url="http://localhost:9111/budget",
        secret="signing-key",
        events=(Webhook_Event.BUDGET_THRESHOLD_CROSSED,),
        description=None,
        active=True,
    )


def _drain(client) -> None:
    """Settle both asynchronous hops: the off-band announcement, then the delivery worker.

    Announcing is dispatched off-band (so the request never waits on it) and *delivering* is the
    worker's job (so nothing waits on a consumer). Both are deliberate, which is exactly why a test
    has to join them rather than assert into a race.
    """
    ctx = client.app.state.observability_context
    ctx.budget_alert_service.drain()
    for _ in range(10):
        if ctx.webhook_worker.run_once() == 0:
            return


def _announced(transport) -> list[dict]:
    """The payload of every budget notification the transport saw."""
    out = []
    for _url, body, _headers in transport.calls:
        envelope = json.loads(body)
        if envelope["event"] == "budget.threshold_crossed":
            out.append(envelope["data"])
    return out


def _set_budget(client, headers, limit: str, action: str = "warn"):
    return client.put(
        "/budget", headers=headers, json={"limit_amount": limit, "action": action}
    )


def test_crossing_a_threshold_on_a_spending_request_notifies_once(wired):
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    assert _set_budget(client, headers, "100").status_code == 200
    _spend(usage_store, org_id, "85")

    first = client.post("/query", headers=headers, json={"query": "hello"})
    assert first.status_code == 200

    _drain(client)
    announced = _announced(transport)
    assert [a["threshold_percent"] for a in announced] == [80]
    assert announced[0]["spent"] == "85"
    assert announced[0]["limit_amount"] == "100"
    assert announced[0]["blocked"] is False

    # Every later request still observes the crossing, and says nothing more.
    for _ in range(3):
        assert client.post("/query", headers=headers, json={"query": "again"}).status_code == 200
    _drain(client)
    assert len(_announced(transport)) == 1


def test_an_agent_run_also_notifies(wired):
    """Every spending endpoint shares the enforcement dependency, so all of them notify."""
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "90")

    assert client.post("/agent/run", headers=headers, json={"message": "hi"}).status_code == 200
    _drain(client)
    assert [a["threshold_percent"] for a in _announced(transport)] == [80]


def test_a_blocked_request_still_notifies_after_the_refusal(wired):
    """The 402 is raised, so this rides the deferred-work seam rather than a background task."""
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100", action="block")
    _spend(usage_store, org_id, "120")

    refused = client.post("/query", headers=headers, json={"query": "hello"})
    assert refused.status_code == 402
    assert refused.json()["error"]["code"] == "budget_exceeded"

    _drain(client)
    announced = _announced(transport)
    assert [a["threshold_percent"] for a in announced] == [80, 100]
    # Both carry the fact that traffic is actually being refused, not merely warned about.
    assert all(a["blocked"] is True for a in announced)


def test_no_notification_below_the_first_threshold(wired):
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "40")

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert _announced(transport) == []


def test_no_notification_without_a_budget(wired):
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _spend(usage_store, org_id, "9999")

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert _announced(transport) == []


def test_a_request_with_no_subscriber_is_unaffected(wired):
    client, headers, org_id, usage_store, _subscriptions, transport = wired
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "150")

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert transport.attempts == 0


def test_another_organizations_subscriber_is_never_told(wired):
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, uuid.uuid4())
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "150")

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert transport.attempts == 0


def test_raising_the_ceiling_lets_the_next_crossing_notify_again(wired):
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "85")
    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert len(_announced(transport)) == 1

    # The owner raises the ceiling: 85 of 1000 is 8.5%, so the old claim no longer applies.
    assert _set_budget(client, headers, "1000").status_code == 200
    _spend(usage_store, org_id, "800")  # 885 of 1000 = 88.5%

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    announced = _announced(transport)
    assert [a["threshold_percent"] for a in announced] == [80, 80]
    assert announced[1]["limit_amount"] == "1000"


def test_removing_the_budget_resets_the_notification_history(wired):
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "85")
    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert len(_announced(transport)) == 1

    assert client.delete("/budget", headers=headers).status_code == 204
    _set_budget(client, headers, "100")

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert len(_announced(transport)) == 2


def test_the_notification_is_signed_like_every_other_event(wired):
    from agentforge.webhooks.security import SIGNATURE_HEADER, verify_signature

    client, headers, org_id, usage_store, subscriptions, transport = wired
    subscription = _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "85")

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200

    _drain(client)
    _url, body, sent_headers = transport.calls[0]
    assert verify_signature(subscription.secret, body, sent_headers[SIGNATURE_HEADER])


def test_a_failing_subscriber_is_retried_by_the_worker_not_by_the_next_request(wired):
    """Durable delivery makes the announcement a one-time act; the queue owns the retrying.

    Before the outbox this needed a cooldown and an attempt cap, because a failed delivery had to
    release the claim and every subsequent request re-announced and re-dialled. Now the row is
    durable: announced once, retried on a schedule, and no amount of tenant traffic changes that.
    """
    import datetime as dt

    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "85")

    ctx = client.app.state.observability_context
    broken = Recording_Webhook_Transport(succeed_from_attempt=None)
    ctx.webhook_emitter._transport = broken

    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert broken.attempts == 1
    entry = ctx.webhook_outbox.list_for_org(org_id)[0]
    assert entry.status == "pending"  # kept, not lost

    # More traffic changes nothing: the threshold is claimed and the queue is already holding it.
    for _ in range(3):
        assert client.post("/query", headers=headers, json={"query": "x"}).status_code == 200
    _drain(client)
    assert broken.attempts == 1

    # The consumer is fixed. The worker's next scheduled attempt delivers what was owed.
    ctx.webhook_emitter._transport = transport
    ctx.webhook_worker._clock = lambda: dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    ctx.webhook_worker.run_once()

    assert [a["threshold_percent"] for a in _announced(transport)] == [80]
    assert ctx.webhook_outbox.list_for_org(org_id)[0].status == "delivered"


def test_a_streamed_run_also_notifies_without_holding_the_stream(wired):
    """The two surfaces whose post-response mechanics the off-band dispatch protects.

    A streamed response has no background-task slot of its own until the body drains, so an
    announcement attached to it would arrive late AND keep the client's connection open for a
    subscriber's timeout. Dispatching off-band, into a durable queue, means the notification is
    already recorded while the stream is still being read.
    """
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "85")

    with client.stream(
        "POST", "/agent/stream", headers=headers, json={"message": "hello"}
    ) as response:
        assert response.status_code == 200
        frames = "".join(response.iter_text())
    assert "completion" in frames

    _drain(client)
    assert [a["threshold_percent"] for a in _announced(transport)] == [80]


def test_a_metering_failure_does_not_erase_the_notification_history(wired):
    """`reconcile` is the destructive operation, and the guard fabricates a zero when blind."""
    client, headers, org_id, usage_store, subscriptions, transport = wired
    _subscribe(subscriptions, org_id)
    _set_budget(client, headers, "100")
    _spend(usage_store, org_id, "85")
    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert len(_announced(transport)) == 1

    # Metering goes down, and the owner edits the budget while it is down.
    guard = client.app.state.observability_context.budget_guard

    class _BrokenAnalytics:
        def usage_report(self, *args, **kwargs):
            raise RuntimeError("analytics down")

    guard._analytics = _BrokenAnalytics()
    guard.invalidate(org_id)
    assert _set_budget(client, headers, "100").status_code == 200

    # The claim survived, so the org is not told about the same crossing twice.
    guard._analytics = client.app.state.observability_context.analytics_service
    guard.invalidate(org_id)
    assert client.post("/query", headers=headers, json={"query": "hello"}).status_code == 200
    _drain(client)
    assert len(_announced(transport)) == 1
