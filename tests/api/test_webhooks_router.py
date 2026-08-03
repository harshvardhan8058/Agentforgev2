"""API tests for the webhook management surface.

Driven through the real app, because the interesting properties are transport-level: the secret
appears in exactly one response and never again, RBAC refuses a member, another tenant's id is a
404 rather than a 403, the per-org cap is enforced, a failed audit write does not leave an
unverifiable endpoint behind, and the delivery log pages with a keyset cursor.
"""

from __future__ import annotations

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
from agentforge.enterprise.audit import Audit_Action
from agentforge.enterprise.rbac import Role
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store
from agentforge.webhooks.dispatcher import Webhook_Dispatcher
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.outbox import InMemory_Webhook_Outbox
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport
from agentforge.webhooks.worker import Webhook_Delivery_Worker

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8

# Loopback is admissible in the local profile, so tests can register a destination without
# resolving anything on the network.
_URL = "http://localhost:9111/hook"
_OTHER_URL = "http://localhost:9222/hook"


def _make_settings(**overrides) -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
        **overrides,
    )


def _wire(settings: Settings, *, transport=None, **enterprise_overrides):
    """Build the app with keyless graphs and a recording webhook transport."""
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
    recording = transport or Recording_Webhook_Transport()
    emitter = Webhook_Emitter(deliveries, recording)
    app = create_app(settings)
    app.state.settings = settings
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = build_multi_agent_context(settings, agent=agent_ctx)
    app.state.observability_context = build_observability_context(
        settings,
        app=app_ctx,
        trace_recorder=InMemory_Trace_Recorder(),
        webhook_subscription_store=subscriptions,
        webhook_delivery_store=deliveries,
        webhook_outbox=outbox,
        webhook_transport=recording,
        webhook_emitter=emitter,
        webhook_dispatcher=Webhook_Dispatcher(subscriptions, outbox),
        # Driven by hand where a test needs it; never started, so no thread races an assertion.
        webhook_worker=Webhook_Delivery_Worker(
            outbox, subscriptions, emitter, batch_size=50
        ),
    )
    headers, org_id, ctx = install_enterprise_auth(
        app, settings, email="owner@example.com", **enterprise_overrides
    )
    client = TestClient(app, raise_server_exceptions=False)
    return client, headers, org_id, ctx, subscriptions, deliveries, recording


@pytest.fixture
def wired():
    """``(client, headers, org_id, ctx, subscriptions, deliveries, transport)`` as an OWNER."""
    return _wire(_make_settings())


def _register(client, headers, *, url=_URL, events=("run.completed",), **extra):
    return client.post(
        "/webhooks",
        headers=headers,
        json={"url": url, "events": list(events), **extra},
    )


# --- registration -----------------------------------------------------------------


def test_registering_returns_the_secret_exactly_once(wired):
    client, headers, _org, _ctx, _subs, _deliveries, _transport = wired

    created = _register(client, headers, description="Ops channel")
    assert created.status_code == 201
    body = created.json()
    secret = body["secret"]
    assert secret and len(secret) >= 40
    assert "cannot be retrieved again" in body["secret_note"]
    webhook_id = body["webhook"]["webhook_id"]
    assert body["webhook"]["events"] == ["run.completed"]
    assert body["webhook"]["active"] is True
    assert body["webhook"]["description"] == "Ops channel"
    # The subscription object in the creation response has no secret field of its own.
    assert "secret" not in body["webhook"]

    listed = client.get("/webhooks", headers=headers)
    assert listed.status_code == 200
    assert secret not in listed.text
    assert all("secret" not in row for row in listed.json())

    # And no other read path produces it either.
    deliveries = client.get(f"/webhooks/{webhook_id}/deliveries", headers=headers)
    assert secret not in deliveries.text
    patched = client.patch(
        f"/webhooks/{webhook_id}", headers=headers, json={"active": False}
    )
    assert secret not in patched.text


def test_duplicate_event_names_are_normalised(wired):
    client, headers, _org, *_rest = wired
    created = _register(
        client, headers, events=["run.completed", "run.completed", "run.failed"]
    )
    assert created.status_code == 201
    assert created.json()["webhook"]["events"] == ["run.completed", "run.failed"]


def test_the_ping_event_cannot_be_subscribed_to(wired):
    """Nothing emits it spontaneously, so the contract refuses it."""
    client, headers, _org, *_rest = wired
    refused = _register(client, headers, events=["webhook.ping"])
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_error"


def test_an_empty_event_list_is_refused(wired):
    client, headers, _org, *_rest = wired
    assert _register(client, headers, events=[]).status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/hook",  # private, and http
        "https://10.0.0.5/hook",  # private
        "ftp://example.com/hook",
        "https://user:pass@localhost:9111/hook",
        "https://localhost:9111/hook#@evil.example.com",
        "https://localhost:80/hook",
        "https://localhost:99999/hook",  # unparseable port: a 400, never a 500
    ],
)
def test_an_inadmissible_url_is_refused_with_a_400(wired, url):
    client, headers, _org, *_rest = wired
    refused = _register(client, headers, url=url)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "invalid_webhook_url"
    assert refused.json()["error"]["details"]["field"] == "url"


def test_an_unresolvable_idn_label_is_refused_with_a_400(wired):
    """A 250-character DNS label makes the resolver raise; it must still be a 400."""
    client, headers, _org, *_rest = wired
    refused = _register(client, headers, url="https://" + "a" * 250 + ".example.com/h")
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "invalid_webhook_url"


def test_the_per_org_subscription_cap_is_enforced(wired):
    """Bounds the fan-out of one event, which is the only unbounded quantity in delivery."""
    client, headers, _org, _ctx, _subs, _deliveries, _transport = _wire(
        _make_settings(webhook_max_per_org=2)
    )
    assert _register(client, headers).status_code == 201
    assert _register(client, headers, url=_OTHER_URL).status_code == 201
    refused = _register(client, headers, url="http://localhost:9333/hook")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "webhook_limit_reached"
    assert refused.json()["error"]["details"]["limit"] == 2


# --- audit ------------------------------------------------------------------------


def test_registration_is_audited_without_recording_the_full_url(wired):
    """A webhook URL's path or query is routinely the credential; the origin is not."""
    client, headers, org_id, ctx, *_rest = wired
    created = _register(client, headers, url="http://localhost:9111/hook/s3cret-path")
    assert created.status_code == 201

    events = ctx.audit_log.list_for_org(org_id)
    assert [e.action for e in events] == [Audit_Action.WEBHOOK_CREATED.value]
    metadata = events[0].metadata
    assert metadata["destination"] == "http://localhost:9111"
    assert "s3cret-path" not in str(metadata)
    assert metadata["events"] == "run.completed"
    assert metadata["event_count"] == 1
    assert created.json()["secret"] not in str(metadata)


def test_update_and_delete_are_audited(wired):
    client, headers, org_id, ctx, *_rest = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]

    client.patch(f"/webhooks/{webhook_id}", headers=headers, json={"active": False})
    client.delete(f"/webhooks/{webhook_id}", headers=headers)

    actions = [e.action for e in ctx.audit_log.list_for_org(org_id)]
    assert Audit_Action.WEBHOOK_UPDATED.value in actions
    assert Audit_Action.WEBHOOK_DELETED.value in actions
    updated = next(
        e
        for e in ctx.audit_log.list_for_org(org_id)
        if e.action == Audit_Action.WEBHOOK_UPDATED.value
    )
    assert updated.metadata["fields"] == "active"
    assert updated.metadata["active"] is False


def test_a_required_audit_failure_rolls_the_subscription_back(wired):
    """The caller never got the secret and no read path can produce it, so the row must go."""

    class _BrokenAuditLog:
        def record(self, event):
            raise RuntimeError("audit store down")

        def list_for_org(self, *args, **kwargs):
            return []

    settings = _make_settings(audit_log_required=True)
    client, headers, _org, _ctx, subscriptions, _deliveries, _transport = _wire(
        settings, audit_log=_BrokenAuditLog()
    )

    refused = _register(client, headers)

    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "audit_unavailable"
    # Nothing was left behind for the tenant to discover later.
    assert client.get("/webhooks", headers=headers).json() == []


# --- reading, updating, deleting --------------------------------------------------


def test_listing_returns_the_orgs_subscriptions_oldest_first(wired):
    client, headers, _org, *_rest = wired
    first = _register(client, headers).json()["webhook"]["webhook_id"]
    second = _register(client, headers, url=_OTHER_URL).json()["webhook"]["webhook_id"]
    rows = client.get("/webhooks", headers=headers).json()
    assert [r["webhook_id"] for r in rows] == [first, second]


def test_a_patch_applies_only_the_supplied_fields(wired):
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers, description="Ops").json()["webhook"][
        "webhook_id"
    ]

    paused = client.patch(
        f"/webhooks/{webhook_id}", headers=headers, json={"active": False}
    )
    assert paused.status_code == 200
    assert paused.json()["active"] is False
    assert paused.json()["description"] == "Ops"
    assert paused.json()["events"] == ["run.completed"]


def test_a_null_description_clears_it_rather_than_being_ignored(wired):
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers, description="Ops").json()["webhook"][
        "webhook_id"
    ]
    cleared = client.patch(
        f"/webhooks/{webhook_id}", headers=headers, json={"description": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None


def test_an_empty_patch_is_refused_with_the_standard_validation_shape(wired):
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    refused = client.patch(f"/webhooks/{webhook_id}", headers=headers, json={})
    assert refused.status_code == 422
    body = refused.json()["error"]
    assert body["code"] == "validation_error"
    # Same envelope shape as the framework's own validation errors, so one client parser works.
    assert body["details"]["errors"][0]["loc"] == ["body"]


def test_patching_an_inadmissible_url_is_refused_and_changes_nothing(wired):
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    refused = client.patch(
        f"/webhooks/{webhook_id}", headers=headers, json={"url": "https://10.0.0.9/h"}
    )
    assert refused.status_code == 400
    assert client.get("/webhooks", headers=headers).json()[0]["url"] == _URL


def test_deleting_removes_the_subscription_and_its_delivery_log(wired):
    client, headers, _org, _ctx, _subs, _deliveries, _transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    client.post(f"/webhooks/{webhook_id}/test", headers=headers)

    assert client.delete(f"/webhooks/{webhook_id}", headers=headers).status_code == 204
    assert client.get("/webhooks", headers=headers).json() == []
    # The log went with it, and reading it is now a 404 rather than an empty page.
    assert (
        client.get(f"/webhooks/{webhook_id}/deliveries", headers=headers).status_code
        == 404
    )


def test_deleting_an_unknown_subscription_is_a_404(wired):
    client, headers, _org, *_rest = wired
    missing = client.delete(f"/webhooks/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


# --- test sends -------------------------------------------------------------------


def test_a_test_send_delivers_a_ping_and_reports_the_result(wired):
    client, headers, _org, _ctx, _subs, _deliveries, transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]

    result = client.post(f"/webhooks/{webhook_id}/test", headers=headers)

    assert result.status_code == 200
    body = result.json()
    assert body["event"] == "webhook.ping"
    assert body["status"] == "delivered"
    assert body["attempts"] == 1
    assert body["response_status"] == 200
    assert body["webhook_id"] == webhook_id
    assert transport.attempts == 1


def test_a_failing_test_send_is_reported_as_data_not_as_an_error(wired):
    """The request succeeded; the endpoint did not. Those are different answers."""
    client, headers, _org, _ctx, _subs, _deliveries, transport = _wire(
        _make_settings(), transport=Recording_Webhook_Transport(succeed_from_attempt=None)
    )
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]

    result = client.post(f"/webhooks/{webhook_id}/test", headers=headers)

    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    # One attempt only: a human is waiting on this response.
    assert result.json()["attempts"] == 1
    assert transport.attempts == 1


def test_a_paused_subscription_can_still_be_tested(wired):
    """Verifying an endpoint before activating it is exactly the workflow."""
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers, active=False).json()["webhook"]["webhook_id"]
    assert client.post(f"/webhooks/{webhook_id}/test", headers=headers).status_code == 200


def test_testing_an_unknown_subscription_is_a_404(wired):
    client, headers, _org, *_rest = wired
    assert (
        client.post(f"/webhooks/{uuid.uuid4()}/test", headers=headers).status_code == 404
    )


# --- the delivery log -------------------------------------------------------------


def test_the_delivery_log_lists_newest_first_and_pages_by_keyset(wired):
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    for _ in range(3):
        client.post(f"/webhooks/{webhook_id}/test", headers=headers)

    page = client.get(
        f"/webhooks/{webhook_id}/deliveries?limit=2", headers=headers
    ).json()
    assert len(page) == 2
    assert page[0]["created_at"] >= page[1]["created_at"]

    cursor = page[-1]
    second = client.get(
        f"/webhooks/{webhook_id}/deliveries",
        headers=headers,
        params={
            "limit": 2,
            "before": cursor["created_at"],
            "before_id": cursor["delivery_id"],
        },
    ).json()
    assert len(second) == 1
    seen = {row["delivery_id"] for row in page} | {row["delivery_id"] for row in second}
    assert len(seen) == 3


def test_half_a_keyset_cursor_is_refused(wired):
    client, headers, _org, *_rest = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    refused = client.get(
        f"/webhooks/{webhook_id}/deliveries?before=2026-07-01T00:00:00Z",
        headers=headers,
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_error"


def test_the_delivery_log_of_an_unknown_subscription_is_a_404_not_an_empty_page(wired):
    client, headers, _org, *_rest = wired
    missing = client.get(f"/webhooks/{uuid.uuid4()}/deliveries", headers=headers)
    assert missing.status_code == 404


# --- RBAC and tenancy -------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.MEMBER, Role.VIEWER])
def test_managing_webhooks_requires_manage_webhooks(wired, role):
    client, _owner_headers, _org, ctx, *_rest = wired
    headers, _org_id = issue_principal_headers(
        ctx, role=role, org_name=f"{role.value} org", email=f"{role.value}@example.com"
    )

    for response in (
        client.get("/webhooks", headers=headers),
        _register(client, headers),
        client.patch(f"/webhooks/{uuid.uuid4()}", headers=headers, json={"active": True}),
        client.delete(f"/webhooks/{uuid.uuid4()}", headers=headers),
        client.post(f"/webhooks/{uuid.uuid4()}/test", headers=headers),
        client.get(f"/webhooks/{uuid.uuid4()}/deliveries", headers=headers),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["error"]["details"]["required"] == "manage_webhooks"


def test_an_admin_can_manage_webhooks(wired):
    client, _owner_headers, _org, ctx, *_rest = wired
    headers, _org_id = issue_principal_headers(
        ctx, role=Role.ADMIN, org_name="Admin org", email="admin@example.com"
    )
    assert _register(client, headers).status_code == 201
    assert client.get("/webhooks", headers=headers).status_code == 200


def test_another_orgs_subscription_is_a_404_and_not_a_403(wired):
    """A 403 would confirm the id exists somewhere — a disclosure through the status code."""
    client, headers, _org, ctx, *_rest = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]

    other_headers, _other_org = issue_principal_headers(
        ctx, role=Role.OWNER, org_name="Other org", email="other@example.com"
    )

    assert client.get("/webhooks", headers=other_headers).json() == []
    for response in (
        client.patch(
            f"/webhooks/{webhook_id}", headers=other_headers, json={"active": False}
        ),
        client.delete(f"/webhooks/{webhook_id}", headers=other_headers),
        client.post(f"/webhooks/{webhook_id}/test", headers=other_headers),
        client.get(f"/webhooks/{webhook_id}/deliveries", headers=other_headers),
    ):
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "not_found"

    # And the original is untouched.
    assert client.get("/webhooks", headers=headers).json()[0]["active"] is True


def test_an_unauthenticated_caller_is_refused(wired):
    client, *_rest = wired
    assert client.get("/webhooks").status_code == 401
    assert client.post("/webhooks", json={"url": _URL, "events": ["run.completed"]}).status_code == 401



# --- the delivery queue -----------------------------------------------------------
#
# Durable delivery is only half a feature without a way to see it: before the outbox, "my webhook
# never arrived" had no answer an operator could reach themselves.


def test_the_queue_is_empty_when_nothing_is_outstanding(wired):
    client, headers, _org, *_rest = wired
    body = client.get("/webhooks/queue", headers=headers).json()
    assert body == {"pending": 0, "abandoned": 0, "entries": []}


def test_the_queue_reports_pending_and_abandoned_with_honest_totals(wired):
    client, headers, org_id, _ctx, _subs, _deliveries, _transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    ctx = client.app.state.observability_context

    from agentforge.webhooks.base import Webhook_Event
    from agentforge.webhooks.outbox import Outbox_Entry

    def _row(event=Webhook_Event.RUN_COMPLETED):
        return ctx.webhook_outbox.enqueue(
            Outbox_Entry.new(
                org_id=org_id,
                subscription_id=uuid.UUID(webhook_id),
                event=event,
                payload={"run_id": "r1"},
                idempotency_key="run.completed:r1",
            )
        )

    pending = _row()
    gone = _row(Webhook_Event.RUN_FAILED)
    delivered = _row()
    ctx.webhook_outbox.abandon(gone.id, attempts=8, error="endpoint returned HTTP 500")
    ctx.webhook_outbox.mark_delivered(delivered.id, attempts=1)

    body = client.get("/webhooks/queue", headers=headers).json()

    assert body["pending"] == 1
    assert body["abandoned"] == 1
    # Delivered rows are not listed: what arrived is the delivery log's job to report.
    assert {e["entry_id"] for e in body["entries"]} == {str(pending.id), str(gone.id)}
    abandoned_entry = next(e for e in body["entries"] if e["entry_id"] == str(gone.id))
    assert abandoned_entry["status"] == "abandoned"
    assert abandoned_entry["attempts"] == 8
    assert abandoned_entry["last_error"] == "endpoint returned HTTP 500"
    assert abandoned_entry["event"] == "run.failed"
    assert abandoned_entry["idempotency_key"] == "run.completed:r1"


def test_the_queue_can_be_filtered_by_status(wired):
    client, headers, org_id, _ctx, _subs, _deliveries, _transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    ctx = client.app.state.observability_context

    from agentforge.webhooks.base import Webhook_Event
    from agentforge.webhooks.outbox import Outbox_Entry

    pending = ctx.webhook_outbox.enqueue(
        Outbox_Entry.new(
            org_id=org_id,
            subscription_id=uuid.UUID(webhook_id),
            event=Webhook_Event.RUN_COMPLETED,
            payload={},
        )
    )
    gone = ctx.webhook_outbox.enqueue(
        Outbox_Entry.new(
            org_id=org_id,
            subscription_id=uuid.UUID(webhook_id),
            event=Webhook_Event.RUN_COMPLETED,
            payload={},
        )
    )
    ctx.webhook_outbox.abandon(gone.id, attempts=8, error="gone")

    only_abandoned = client.get(
        "/webhooks/queue?status=abandoned", headers=headers
    ).json()
    assert [e["entry_id"] for e in only_abandoned["entries"]] == [str(gone.id)]
    # The counts stay whole-queue even when the page is filtered.
    assert only_abandoned["pending"] == 1

    only_pending = client.get("/webhooks/queue?status=pending", headers=headers).json()
    assert [e["entry_id"] for e in only_pending["entries"]] == [str(pending.id)]


def test_an_abandoned_entry_can_be_redelivered(wired):
    client, headers, org_id, ctx_enterprise, _subs, _deliveries, transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    ctx = client.app.state.observability_context

    from agentforge.webhooks.base import Webhook_Event
    from agentforge.webhooks.outbox import Outbox_Entry

    entry = ctx.webhook_outbox.enqueue(
        Outbox_Entry.new(
            org_id=org_id,
            subscription_id=uuid.UUID(webhook_id),
            event=Webhook_Event.RUN_COMPLETED,
            payload={"run_id": "r1"},
        )
    )
    ctx.webhook_outbox.abandon(entry.id, attempts=8, error="endpoint returned HTTP 500")

    response = client.post(
        f"/webhooks/queue/{entry.id}/redeliver", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    # A fresh schedule, not a continuation of the one that gave up.
    assert response.json()["attempts"] == 0

    # And it really is deliverable again.
    assert ctx.webhook_worker.run_once() == 1
    assert transport.attempts == 1
    assert ctx.webhook_outbox.get(org_id, entry.id).status == "delivered"

    # Audited: a human chose to re-send something the platform had given up on.
    actions = [e.action for e in ctx_enterprise.audit_log.list_for_org(org_id)]
    assert Audit_Action.WEBHOOK_REDELIVERED.value in actions


def test_a_pending_entry_cannot_be_redelivered(wired):
    """It is already scheduled, so requeueing would ask for the same event twice."""
    client, headers, org_id, _ctx, _subs, _deliveries, _transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    ctx = client.app.state.observability_context

    from agentforge.webhooks.base import Webhook_Event
    from agentforge.webhooks.outbox import Outbox_Entry

    entry = ctx.webhook_outbox.enqueue(
        Outbox_Entry.new(
            org_id=org_id,
            subscription_id=uuid.UUID(webhook_id),
            event=Webhook_Event.RUN_COMPLETED,
            payload={},
        )
    )

    refused = client.post(f"/webhooks/queue/{entry.id}/redeliver", headers=headers)

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "not_redeliverable"
    assert refused.json()["error"]["details"]["status"] == "pending"


def test_redelivering_an_unknown_entry_is_a_404(wired):
    client, headers, _org, *_rest = wired
    missing = client.post(f"/webhooks/queue/{uuid.uuid4()}/redeliver", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_another_orgs_queue_entry_is_invisible_and_not_redeliverable(wired):
    client, headers, org_id, ctx_enterprise, _subs, _deliveries, _transport = wired
    webhook_id = _register(client, headers).json()["webhook"]["webhook_id"]
    ctx = client.app.state.observability_context

    from agentforge.webhooks.base import Webhook_Event
    from agentforge.webhooks.outbox import Outbox_Entry

    entry = ctx.webhook_outbox.enqueue(
        Outbox_Entry.new(
            org_id=org_id,
            subscription_id=uuid.UUID(webhook_id),
            event=Webhook_Event.RUN_COMPLETED,
            payload={},
        )
    )
    ctx.webhook_outbox.abandon(entry.id, attempts=8, error="gone")

    other_headers, _other_org = issue_principal_headers(
        ctx_enterprise, role=Role.OWNER, org_name="Other queue org", email="oq@example.com"
    )

    assert client.get("/webhooks/queue", headers=other_headers).json()["entries"] == []
    refused = client.post(
        f"/webhooks/queue/{entry.id}/redeliver", headers=other_headers
    )
    assert refused.status_code == 404


@pytest.mark.parametrize("role", [Role.MEMBER, Role.VIEWER])
def test_the_queue_requires_manage_webhooks(wired, role):
    client, _owner_headers, _org, ctx_enterprise, *_rest = wired
    headers, _org_id = issue_principal_headers(
        ctx_enterprise,
        role=role,
        org_name=f"{role.value} queue org",
        email=f"q-{role.value}@example.com",
    )

    for response in (
        client.get("/webhooks/queue", headers=headers),
        client.post(f"/webhooks/queue/{uuid.uuid4()}/redeliver", headers=headers),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required"] == "manage_webhooks"
