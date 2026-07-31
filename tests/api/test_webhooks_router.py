"""API tests: webhook subscriptions are managed, secret-once, org-scoped, and audited.

Covers the contract a consumer and an administrator both depend on:

* the signing secret is returned **exactly once** and by no other endpoint, ever;
* a URL that would reach an internal address is refused with a 400, at create *and* update;
* ``manage_webhooks`` gates all six endpoints, and another tenant's webhook is a 404;
* a test send returns the delivery outcome as a 200 even when the endpoint refuses;
* the delivery log is keyset-paginated and newest-first;
* create/update/delete land in the audit trail, and the secret never does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store
from agentforge.webhooks.base import Webhook_Delivery
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8

# The local profile allows a loopback target (see Settings.allow_loopback_webhooks), so the
# tests can use a URL that needs no DNS resolution and no network.
LOCAL_URL = "http://localhost:9100/hook"
OTHER_LOCAL_URL = "http://127.0.0.1:9101/hook"


class Wired:
    """The wired app plus the seams a test needs to reach into."""

    def __init__(self, client, headers, org_id, ctx, transport, subscriptions, deliveries):
        self.client = client
        self.headers = headers
        self.org_id = org_id
        self.ctx = ctx
        self.transport = transport
        self.subscriptions = subscriptions
        self.deliveries = deliveries

    def create(self, url: str = LOCAL_URL, events=("run.completed",), **extra):
        payload = {"url": url, "events": list(events), **extra}
        return self.client.post("/webhooks", json=payload, headers=self.headers)

    def audit_actions(self) -> list[str]:
        return [e.action for e in self.ctx.audit_log.list_for_org(self.org_id, limit=50)]


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
    app.state.multi_agent_context = build_multi_agent_context(settings, agent=agent_ctx)
    app.state.observability_context = build_observability_context(
        settings,
        app=app_ctx,
        trace_recorder=InMemory_Trace_Recorder(),
        webhook_subscription_store=subscriptions,
        webhook_delivery_store=deliveries,
        webhook_transport=transport,
        # A no-sleep emitter over the same seams: the retry schedule is asserted in the unit
        # tests, and a test suite must not spend real seconds re-proving it.
        webhook_emitter=Webhook_Emitter(
            subscriptions, deliveries, transport, sleep=lambda _s: None
        ),
    )
    headers, org_id, ctx = install_enterprise_auth(app, settings, email="owner@ex.com")
    client = TestClient(app, raise_server_exceptions=False)
    return Wired(client, headers, org_id, ctx, transport, subscriptions, deliveries)


# --- authentication and authorization ----------------------------------------------


def test_every_endpoint_requires_authentication(wired: Wired):
    webhook_id = uuid.uuid4()
    unauthenticated = [
        wired.client.get("/webhooks"),
        wired.client.post("/webhooks", json={"url": LOCAL_URL, "events": ["run.completed"]}),
        wired.client.patch(f"/webhooks/{webhook_id}", json={"active": False}),
        wired.client.delete(f"/webhooks/{webhook_id}"),
        wired.client.post(f"/webhooks/{webhook_id}/test"),
        wired.client.get(f"/webhooks/{webhook_id}/deliveries"),
    ]
    assert [r.status_code for r in unauthenticated] == [401] * 6


@pytest.mark.parametrize("role", [Role.VIEWER, Role.MEMBER])
def test_below_admin_cannot_manage_webhooks(wired: Wired, role: Role):
    headers, _org = issue_principal_headers(
        wired.ctx, role=role, org_name=f"Org {role.value}", email=f"{role.value}@ex.com"
    )

    listing = wired.client.get("/webhooks", headers=headers)
    creation = wired.client.post(
        "/webhooks", json={"url": LOCAL_URL, "events": ["run.completed"]}, headers=headers
    )

    assert [listing.status_code, creation.status_code] == [403, 403]
    assert listing.json()["error"]["details"]["required"] == "manage_webhooks"


def test_an_admin_can_manage_webhooks(wired: Wired):
    """Webhook config is administrative, not owner-only: it discloses no credential."""
    headers, _org = issue_principal_headers(
        wired.ctx, role=Role.ADMIN, org_name="Admin Org", email="admin@ex.com"
    )

    created = wired.client.post(
        "/webhooks", json={"url": LOCAL_URL, "events": ["run.completed"]}, headers=headers
    )

    assert created.status_code == 201


# --- creation and the one-time secret ----------------------------------------------


def test_creating_a_webhook_returns_the_secret_exactly_once(wired: Wired):
    created = wired.create(events=("run.completed", "run.failed"), description="Ops channel")

    assert created.status_code == 201
    body = created.json()
    assert body["secret"].startswith("whsec_")
    assert body["url"] == LOCAL_URL
    assert body["events"] == ["run.completed", "run.failed"]
    assert body["description"] == "Ops channel"
    assert body["active"] is True
    assert body["created_at"] and body["updated_at"]

    # Every other path renders a model with no `secret` field at all.
    listed = wired.client.get("/webhooks", headers=wired.headers).json()
    assert "secret" not in listed[0]
    patched = wired.client.patch(
        f"/webhooks/{body['webhook_id']}", json={"active": False}, headers=wired.headers
    ).json()
    assert "secret" not in patched


def test_the_stored_secret_is_the_one_that_was_returned(wired: Wired):
    """A secret a consumer cannot verify with is worse than no secret at all."""
    secret = wired.create().json()["secret"]

    stored = wired.subscriptions.list_for_org(wired.org_id)[0]

    assert stored.secret == secret


def test_two_webhooks_get_different_secrets(wired: Wired):
    first = wired.create().json()["secret"]
    second = wired.create(url=OTHER_LOCAL_URL).json()["secret"]

    assert first != second


def test_an_empty_event_list_is_refused(wired: Wired):
    """A subscription that wants nothing would never fire; it is a mistake, not a config."""
    assert wired.create(events=()).status_code == 422


def test_an_unknown_or_unsubscribable_event_is_refused(wired: Wired):
    """`webhook.ping` is sent only by the test endpoint, so the contract cannot admit it."""
    assert wired.create(events=("run.exploded",)).status_code == 422
    assert wired.create(events=("webhook.ping",)).status_code == 422


def test_a_duplicated_event_is_normalised_rather_than_refused(wired: Wired):
    body = wired.create(events=("run.completed", "run.completed")).json()

    assert body["events"] == ["run.completed"]


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.5/hook",
        "ftp://example.com/hook",
        "https://user:pass@8.8.8.8/hook",
        "not a url",
    ],
)
def test_a_url_that_must_not_be_reached_is_refused_at_creation(wired: Wired, url: str):
    response = wired.create(url=url)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_webhook_url"
    assert response.json()["error"]["details"]["field"] == "url"
    assert wired.client.get("/webhooks", headers=wired.headers).json() == []


def test_an_over_long_url_or_description_is_refused(wired: Wired):
    assert wired.create(url="http://localhost:9100/" + "a" * 3000).status_code == 422
    assert wired.create(description="d" * 500).status_code == 422


# --- listing -----------------------------------------------------------------------


def test_listing_returns_the_org_s_webhooks_newest_first(wired: Wired):
    first = wired.create().json()["webhook_id"]
    second = wired.create(url=OTHER_LOCAL_URL).json()["webhook_id"]

    listed = wired.client.get("/webhooks", headers=wired.headers).json()

    assert [w["webhook_id"] for w in listed] == [second, first]


def test_another_tenant_s_webhooks_are_invisible(wired: Wired):
    wired.create()
    other_headers, _other_org = issue_principal_headers(
        wired.ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )

    assert wired.client.get("/webhooks", headers=other_headers).json() == []


# --- update ------------------------------------------------------------------------


def test_an_update_changes_only_the_fields_supplied(wired: Wired):
    created = wired.create(events=("run.completed",), description="Ops").json()

    updated = wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"active": False},
        headers=wired.headers,
    ).json()

    assert updated["active"] is False
    assert updated["url"] == LOCAL_URL
    assert updated["events"] == ["run.completed"]
    assert updated["description"] == "Ops"
    assert updated["updated_at"] >= created["updated_at"]


def test_an_update_can_re_point_and_re_subscribe(wired: Wired):
    created = wired.create().json()

    updated = wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"url": OTHER_LOCAL_URL, "events": ["document.ingested", "guardrail.blocked"]},
        headers=wired.headers,
    ).json()

    assert updated["url"] == OTHER_LOCAL_URL
    assert updated["events"] == ["document.ingested", "guardrail.blocked"]


def test_an_update_re_applies_the_url_policy(wired: Wired):
    """Re-pointing at the metadata service must be refused exactly like creating there."""
    created = wired.create().json()

    response = wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"url": "https://169.254.169.254/latest/meta-data/"},
        headers=wired.headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_webhook_url"
    assert wired.subscriptions.list_for_org(wired.org_id)[0].url == LOCAL_URL


def test_an_empty_update_is_refused(wired: Wired):
    created = wired.create().json()

    response = wired.client.patch(
        f"/webhooks/{created['webhook_id']}", json={}, headers=wired.headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_an_update_never_rotates_the_secret(wired: Wired):
    """Silently re-keying would break the consumer with no way for them to notice."""
    created = wired.create().json()

    wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"url": OTHER_LOCAL_URL},
        headers=wired.headers,
    )

    assert wired.subscriptions.list_for_org(wired.org_id)[0].secret == created["secret"]


# --- delete ------------------------------------------------------------------------


def test_deleting_a_webhook_removes_it(wired: Wired):
    created = wired.create().json()

    deleted = wired.client.delete(
        f"/webhooks/{created['webhook_id']}", headers=wired.headers
    )

    assert deleted.status_code == 204
    assert wired.client.get("/webhooks", headers=wired.headers).json() == []


def test_deleting_an_unknown_webhook_is_a_404(wired: Wired):
    """Unlike DELETE /budget, this names a resource: a 204 would hide a typo."""
    response = wired.client.delete(f"/webhooks/{uuid.uuid4()}", headers=wired.headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- tenancy ---------------------------------------------------------------------


def test_another_tenant_s_webhook_is_a_404_on_every_addressed_endpoint(wired: Wired):
    """Indistinguishable from "does not exist", so ids cannot be enumerated."""
    created = wired.create().json()
    webhook_id = created["webhook_id"]
    other_headers, _other_org = issue_principal_headers(
        wired.ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )

    responses = [
        wired.client.patch(
            f"/webhooks/{webhook_id}", json={"active": False}, headers=other_headers
        ),
        wired.client.delete(f"/webhooks/{webhook_id}", headers=other_headers),
        wired.client.post(f"/webhooks/{webhook_id}/test", headers=other_headers),
        wired.client.get(f"/webhooks/{webhook_id}/deliveries", headers=other_headers),
    ]

    assert [r.status_code for r in responses] == [404] * 4
    assert {r.json()["error"]["code"] for r in responses} == {"not_found"}
    # And nothing happened to the real subscription.
    assert wired.subscriptions.get(wired.org_id, uuid.UUID(webhook_id)) is not None


# --- the test send ---------------------------------------------------------------


def test_a_test_send_delivers_a_signed_ping_and_reports_the_outcome(wired: Wired):
    created = wired.create().json()

    response = wired.client.post(
        f"/webhooks/{created['webhook_id']}/test", headers=wired.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event"] == "webhook.ping"
    assert body["status"] == "delivered"
    assert body["attempts"] == 1
    assert body["response_status"] == 200
    assert body["webhook_id"] == created["webhook_id"]
    assert len(wired.transport.calls) == 1
    assert wired.transport.calls[0]["url"] == LOCAL_URL


def test_a_refused_test_send_is_still_a_200_carrying_the_failure(wired: Wired):
    """A 502 here would be indistinguishable from this API being broken."""
    created = wired.create().json()
    wired.transport.status = 500

    response = wired.client.post(
        f"/webhooks/{created['webhook_id']}/test", headers=wired.headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["response_status"] == 500
    # One attempt: the caller is waiting, and retrying would hide what they asked to see.
    assert len(wired.transport.calls) == 1


def test_a_test_send_appears_in_the_delivery_log(wired: Wired):
    created = wired.create().json()

    sent = wired.client.post(
        f"/webhooks/{created['webhook_id']}/test", headers=wired.headers
    ).json()
    logged = wired.client.get(
        f"/webhooks/{created['webhook_id']}/deliveries", headers=wired.headers
    ).json()

    assert [d["delivery_id"] for d in logged] == [sent["delivery_id"]]


def test_a_test_send_works_on_a_paused_webhook(wired: Wired):
    """Verifying an endpoint before resuming it is exactly when this is useful."""
    created = wired.create().json()
    wired.client.patch(
        f"/webhooks/{created['webhook_id']}", json={"active": False}, headers=wired.headers
    )

    response = wired.client.post(
        f"/webhooks/{created['webhook_id']}/test", headers=wired.headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "delivered"


def test_a_test_send_is_not_audited(wired: Wired):
    """It changes nothing, and an audit trail of read-only probes is noise."""
    created = wired.create().json()
    before = wired.audit_actions()

    wired.client.post(f"/webhooks/{created['webhook_id']}/test", headers=wired.headers)

    assert wired.audit_actions() == before


def test_an_undeliverable_envelope_is_reported_as_a_server_fault(wired: Wired, monkeypatch):
    """The emitter declines to send only when the envelope shape itself is broken."""
    created = wired.create().json()
    emitter = wired.client.app.state.observability_context.webhook_emitter
    monkeypatch.setattr(
        emitter, "send_to", lambda *_args, **_kwargs: None
    )

    response = wired.client.post(
        f"/webhooks/{created['webhook_id']}/test", headers=wired.headers
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


# --- the delivery log -------------------------------------------------------------


def _seed_deliveries(wired: Wired, webhook_id: uuid.UUID, count: int) -> list[Webhook_Delivery]:
    """Write ``count`` deliveries with strictly increasing timestamps."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    written = []
    for index in range(count):
        written.append(
            wired.deliveries.record(
                Webhook_Delivery(
                    id=uuid.uuid4(),
                    org_id=wired.org_id,
                    subscription_id=webhook_id,
                    event_type="run.completed",
                    status="delivered" if index % 2 == 0 else "failed",
                    attempts=1 + index % 3,
                    response_status=200 if index % 2 == 0 else 503,
                    error=None if index % 2 == 0 else "endpoint refused",
                    duration_ms=index,
                    created_at=base + timedelta(minutes=index),
                )
            )
        )
    return written


def test_the_delivery_log_is_newest_first_and_keyset_paginated(wired: Wired):
    created = wired.create().json()
    webhook_id = uuid.UUID(created["webhook_id"])
    written = _seed_deliveries(wired, webhook_id, 5)
    newest_first = [str(d.id) for d in reversed(written)]

    page_one = wired.client.get(
        f"/webhooks/{webhook_id}/deliveries?limit=2", headers=wired.headers
    ).json()
    cursor = page_one[-1]
    page_two = wired.client.get(
        f"/webhooks/{webhook_id}/deliveries?limit=2"
        f"&before={cursor['created_at']}&before_id={cursor['delivery_id']}",
        headers=wired.headers,
    ).json()

    assert [d["delivery_id"] for d in page_one] == newest_first[:2]
    assert [d["delivery_id"] for d in page_two] == newest_first[2:4]


def test_a_half_supplied_cursor_is_refused(wired: Wired):
    """A timestamp alone cannot separate deliveries fanned out in one burst."""
    created = wired.create().json()

    response = wired.client.get(
        f"/webhooks/{created['webhook_id']}/deliveries?before=2026-01-01T00:00:00Z",
        headers=wired.headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "before_id"


def test_a_delivery_row_reports_what_an_operator_needs(wired: Wired):
    created = wired.create().json()
    webhook_id = uuid.UUID(created["webhook_id"])
    _seed_deliveries(wired, webhook_id, 2)

    logged = wired.client.get(
        f"/webhooks/{webhook_id}/deliveries", headers=wired.headers
    ).json()

    failed = next(d for d in logged if d["status"] == "failed")
    assert failed["response_status"] == 503
    assert failed["error"] == "endpoint refused"
    assert failed["attempts"] >= 1
    assert failed["duration_ms"] is not None
    assert failed["event"] == "run.completed"


def test_the_delivery_log_of_an_unknown_webhook_is_a_404_not_an_empty_page(wired: Wired):
    """An empty page reads as "delivered nothing", which is a different fact."""
    response = wired.client.get(
        f"/webhooks/{uuid.uuid4()}/deliveries", headers=wired.headers
    )

    assert response.status_code == 404


def test_the_delivery_page_size_is_bounded(wired: Wired):
    created = wired.create().json()

    response = wired.client.get(
        f"/webhooks/{created['webhook_id']}/deliveries?limit=5000", headers=wired.headers
    )

    assert response.status_code == 422


# --- the audit trail --------------------------------------------------------------


def test_create_update_and_delete_are_audited(wired: Wired):
    created = wired.create().json()
    wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"active": False},
        headers=wired.headers,
    )
    wired.client.delete(f"/webhooks/{created['webhook_id']}", headers=wired.headers)

    assert wired.audit_actions() == [
        "webhook.deleted",
        "webhook.updated",
        "webhook.created",
    ]


def test_the_audit_metadata_records_the_url_and_never_the_secret(wired: Wired):
    created = wired.create().json()

    event = wired.ctx.audit_log.list_for_org(wired.org_id, limit=1)[0]

    assert event.target_type == "webhook"
    assert event.target_id == created["webhook_id"]
    assert event.metadata["url"] == LOCAL_URL
    assert event.metadata["events"] == "run.completed"
    assert created["secret"] not in str(event.metadata)


def test_an_update_records_which_fields_were_touched(wired: Wired):
    created = wired.create().json()

    wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"active": False, "url": OTHER_LOCAL_URL},
        headers=wired.headers,
    )

    event = wired.ctx.audit_log.list_for_org(wired.org_id, limit=1)[0]
    assert event.metadata["fields"] == "active, url"
    assert event.metadata["url"] == OTHER_LOCAL_URL
    assert event.metadata["active"] is False


def test_a_refused_write_is_not_audited(wired: Wired):
    """The audit trail records changes that happened, not attempts that were rejected."""
    wired.create(url="https://10.0.0.5/hook")

    assert wired.audit_actions() == []



# --- resource bounds --------------------------------------------------------------


def test_the_number_of_webhooks_per_org_is_capped(wired: Wired):
    """Not a display bound: every emitted event fans out to all of them, serially."""
    from agentforge.api.routers.webhooks import MAX_WEBHOOKS_PER_ORG

    for index in range(MAX_WEBHOOKS_PER_ORG):
        assert wired.create(url=f"http://localhost:9{index:03d}/hook").status_code == 201

    refused = wired.create(url="http://localhost:9999/hook")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "webhook_limit_reached"
    assert refused.json()["error"]["details"]["limit"] == MAX_WEBHOOKS_PER_ORG
    assert len(wired.subscriptions.list_for_org(wired.org_id)) == MAX_WEBHOOKS_PER_ORG


def test_the_cap_is_per_organization_not_global(wired: Wired):
    from agentforge.api.routers.webhooks import MAX_WEBHOOKS_PER_ORG

    for index in range(MAX_WEBHOOKS_PER_ORG):
        wired.create(url=f"http://localhost:9{index:03d}/hook")
    other_headers, _other_org = issue_principal_headers(
        wired.ctx, role=Role.OWNER, org_name="Other Org", email="other@ex.com"
    )

    response = wired.client.post(
        "/webhooks", json={"url": LOCAL_URL, "events": ["run.completed"]}, headers=other_headers
    )

    assert response.status_code == 201


def test_a_malformed_url_is_a_400_not_a_500(wired: Wired):
    """A port over 65535 and an over-long DNS label both used to reach the 500 handler."""
    for url in (
        "https://example.com:99999/hook",
        "https://example.com:abc/hook",
        "https://" + "a" * 250 + ".com/hook",
    ):
        response = wired.create(url=url)
        assert response.status_code == 400, url
        assert response.json()["error"]["code"] == "invalid_webhook_url"


# --- the one-time secret must never be lost ---------------------------------------


def test_a_failed_audit_write_does_not_leave_a_webhook_whose_secret_nobody_holds(wired: Wired):
    """The compensating delete.

    Under `audit_log_required` an audit failure raises *after* the subscription exists and is
    already signing. The caller then never sees the secret — this response is the only place it
    ever appears, and there is no rotation endpoint — so the subscription must not survive.
    """
    from agentforge.enterprise.audit import AuditUnavailableError

    def explode(*_args, **_kwargs):
        raise AuditUnavailableError("webhook.created")

    wired.client.app.state.enterprise_context.audit_service.record = explode

    response = wired.create()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "audit_unavailable"
    # Nothing left behind: no orphaned subscription signing with an undisclosed secret.
    assert wired.subscriptions.list_for_org(wired.org_id) == []


# --- PATCH semantics --------------------------------------------------------------


def test_clearing_a_description_with_null_is_refused_rather_than_silently_ignored(wired: Wired):
    """It used to pass the "supply a field" guard, change nothing, and audit a phantom change."""
    created = wired.create(description="Ops").json()

    response = wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"description": None},
        headers=wired.headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "description"
    assert wired.audit_actions() == ["webhook.created"]


def test_a_description_can_be_cleared_with_an_empty_string(wired: Wired):
    created = wired.create(description="Ops").json()

    updated = wired.client.patch(
        f"/webhooks/{created['webhook_id']}",
        json={"description": ""},
        headers=wired.headers,
    ).json()

    assert updated["description"] == ""


def test_the_empty_update_refusal_names_the_fields_a_client_may_send(wired: Wired):
    """Every other `validation_error` carries `field` or `errors`; this one carried nothing."""
    created = wired.create().json()

    response = wired.client.patch(
        f"/webhooks/{created['webhook_id']}", json={}, headers=wired.headers
    )

    assert response.status_code == 422
    assert set(response.json()["error"]["details"]["fields"]) == {
        "url",
        "events",
        "description",
        "active",
    }


# --- what the audit trail records about a URL -------------------------------------


def test_the_audited_url_drops_the_query_string(wired: Wired):
    """A webhook URL is frequently itself a bearer credential (`?token=…`).

    `admit_metadata` screens credential-shaped key *names*, not values, so the whole URL under
    the key `url` would land in the table the audit module describes as the most widely read one.
    """
    wired.create(url="http://localhost:9100/hook?token=super-secret-value&x=1")

    event = wired.ctx.audit_log.list_for_org(wired.org_id, limit=1)[0]

    assert event.metadata["url"] == "http://localhost:9100/hook"
    assert "super-secret-value" not in str(event.metadata)


def test_the_audited_url_keeps_the_host_and_path(wired: Wired):
    """Which is the whole reason to record anything: "who pointed a webhook where"."""
    wired.create(url="http://127.0.0.1:9101/deep/path")

    event = wired.ctx.audit_log.list_for_org(wired.org_id, limit=1)[0]

    assert event.metadata["url"] == "http://127.0.0.1:9101/deep/path"


def test_deleting_a_webhook_also_removes_its_delivery_log(wired: Wired):
    """Migration 0015 cascades; the keyless store is wired to behave the same way."""
    created = wired.create().json()
    webhook_id = uuid.UUID(created["webhook_id"])
    wired.client.post(f"/webhooks/{webhook_id}/test", headers=wired.headers)
    assert wired.deliveries.list_for_subscription(wired.org_id, webhook_id)

    wired.client.delete(f"/webhooks/{webhook_id}", headers=wired.headers)

    assert wired.deliveries.list_for_subscription(wired.org_id, webhook_id) == []
