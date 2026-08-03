"""Unit tests for the in-memory webhook stores.

These are not incidental test doubles — they are the keyless path the platform runs on without
a database — so they are held to the behaviour the Postgres pair has, including the parts that
come from the schema rather than from Python: the delivery-log cascade on delete, and a partial
update that can distinguish "field absent" from "field set to null".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from agentforge.webhooks.base import Webhook_Delivery, Webhook_Event
from agentforge.webhooks.store import (
    UNSET,
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()


def _stores():
    deliveries = InMemory_Webhook_Delivery_Store()
    return InMemory_Webhook_Subscription_Store(deliveries), deliveries


def _subscribe(store, *, org=ORG, events=(Webhook_Event.RUN_COMPLETED,), active=True):
    return store.create(
        org,
        url="https://hooks.example.com/h",
        secret="signing-key",
        events=tuple(events),
        description="initial",
        active=active,
    )


def _delivery(org, subscription_id, *, when: datetime, id_=None) -> Webhook_Delivery:
    return Webhook_Delivery(
        id=id_ or uuid.uuid4(),
        org_id=org,
        subscription_id=subscription_id,
        event=Webhook_Event.RUN_COMPLETED,
        status="delivered",
        attempts=1,
        response_status=200,
        error=None,
        duration_ms=12,
        created_at=when,
    )


# --- tenancy ----------------------------------------------------------------------


def test_a_subscription_is_invisible_to_another_org():
    store, _deliveries = _stores()
    subscription = _subscribe(store)
    assert store.get(OTHER_ORG, subscription.id) is None
    assert store.list_for_org(OTHER_ORG) == []
    assert store.count_for_org(OTHER_ORG) == 0


def test_another_org_cannot_update_or_delete_a_subscription():
    store, _deliveries = _stores()
    subscription = _subscribe(store)
    assert store.update(OTHER_ORG, subscription.id, active=False) is None
    assert store.delete(OTHER_ORG, subscription.id) is False
    assert store.get(ORG, subscription.id).active is True


def test_a_delivery_is_invisible_to_another_org():
    store, deliveries = _stores()
    subscription = _subscribe(store)
    deliveries.record(
        _delivery(ORG, subscription.id, when=datetime.now(timezone.utc))
    )
    assert deliveries.list_for_subscription(OTHER_ORG, subscription.id) == []


# --- listing order and matching ---------------------------------------------------


def test_subscriptions_list_oldest_first():
    store, _deliveries = _stores()
    first = _subscribe(store)
    second = _subscribe(store)
    assert [s.id for s in store.list_for_org(ORG)] == [first.id, second.id]


def test_list_for_event_matches_only_active_subscriptions_that_want_it():
    store, _deliveries = _stores()
    wanted = _subscribe(store, events=(Webhook_Event.RUN_COMPLETED,))
    _subscribe(store, events=(Webhook_Event.RUN_FAILED,))
    _subscribe(store, events=(Webhook_Event.RUN_COMPLETED,), active=False)
    matched = store.list_for_event(ORG, Webhook_Event.RUN_COMPLETED)
    assert [s.id for s in matched] == [wanted.id]


# --- partial update semantics -----------------------------------------------------


def test_an_absent_field_is_left_alone_and_a_null_description_clears_it():
    store, _deliveries = _stores()
    subscription = _subscribe(store)

    paused = store.update(ORG, subscription.id, active=False)
    assert paused.active is False
    assert paused.description == "initial"  # untouched
    assert paused.url == subscription.url

    cleared = store.update(ORG, subscription.id, description=None)
    assert cleared.description is None
    assert cleared.active is False  # the earlier change survives


def test_update_never_changes_the_secret_or_created_at():
    store, _deliveries = _stores()
    subscription = _subscribe(store)
    updated = store.update(
        ORG,
        subscription.id,
        url="https://elsewhere.example.com/h",
        events=(Webhook_Event.GUARDRAIL_BLOCKED,),
    )
    assert updated.secret == subscription.secret
    assert updated.created_at == subscription.created_at
    assert updated.updated_at >= subscription.updated_at
    assert updated.events == (Webhook_Event.GUARDRAIL_BLOCKED,)


def test_an_update_with_every_field_unset_changes_nothing_but_the_timestamp():
    store, _deliveries = _stores()
    subscription = _subscribe(store)
    updated = store.update(
        ORG, subscription.id, url=UNSET, events=UNSET, description=UNSET, active=UNSET
    )
    assert updated.url == subscription.url
    assert updated.events == subscription.events
    assert updated.description == subscription.description
    assert updated.active == subscription.active


# --- the cascade ------------------------------------------------------------------


def test_deleting_a_subscription_deletes_its_delivery_log():
    """Mirrors ON DELETE CASCADE; a fake that kept the rows would hide a real difference."""
    store, deliveries = _stores()
    subscription = _subscribe(store)
    other = _subscribe(store)
    now = datetime.now(timezone.utc)
    deliveries.record(_delivery(ORG, subscription.id, when=now))
    deliveries.record(_delivery(ORG, other.id, when=now))

    assert store.delete(ORG, subscription.id) is True

    assert deliveries.list_for_subscription(ORG, subscription.id) == []
    assert len(deliveries.list_for_subscription(ORG, other.id)) == 1


def test_a_subscription_store_without_a_delivery_log_still_deletes():
    """The pairing is optional wiring, not a requirement of the store."""
    store = InMemory_Webhook_Subscription_Store()
    subscription = _subscribe(store)
    assert store.delete(ORG, subscription.id) is True


# --- delivery-log paging ----------------------------------------------------------


def test_deliveries_are_newest_first_and_the_keyset_cursor_walks_them():
    store, deliveries = _stores()
    subscription = _subscribe(store)
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    made = [
        deliveries.record(
            _delivery(ORG, subscription.id, when=base + timedelta(minutes=i))
        )
        for i in range(5)
    ]

    page = deliveries.list_for_subscription(ORG, subscription.id, limit=2)
    assert [d.id for d in page] == [made[4].id, made[3].id]

    cursor = (page[-1].created_at, page[-1].id)
    second = deliveries.list_for_subscription(
        ORG, subscription.id, before=cursor, limit=2
    )
    assert [d.id for d in second] == [made[2].id, made[1].id]

    cursor = (second[-1].created_at, second[-1].id)
    third = deliveries.list_for_subscription(
        ORG, subscription.id, before=cursor, limit=2
    )
    assert [d.id for d in third] == [made[0].id]


def test_deliveries_sharing_a_timestamp_are_ordered_stably_and_never_repeat():
    """A fan-out writes several rows in one millisecond; the id breaks the tie."""
    store, deliveries = _stores()
    subscription = _subscribe(store)
    when = datetime(2026, 7, 1, tzinfo=timezone.utc)
    made = [
        deliveries.record(_delivery(ORG, subscription.id, when=when)) for _ in range(4)
    ]

    seen = []
    cursor = None
    for _ in range(4):
        page = deliveries.list_for_subscription(
            ORG, subscription.id, before=cursor, limit=1
        )
        assert len(page) == 1
        seen.append(page[0].id)
        cursor = (page[0].created_at, page[0].id)

    assert sorted(str(i) for i in seen) == sorted(str(d.id) for d in made)
    assert len(set(seen)) == 4
