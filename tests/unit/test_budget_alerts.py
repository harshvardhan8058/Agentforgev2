"""Unit tests for budget threshold notifications.

The property under test throughout is **at most once per organization per period per
threshold**, because a budget threshold is a condition rather than an event: it stays true for
every request after it first becomes true, so anything that emits on the condition sends a
webhook per request for the rest of the month.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentforge.observability.budget import Budget_Status
from agentforge.observability.budget_alerts import (
    BUDGET_THRESHOLDS,
    Budget_Alert_Service,
    InMemory_Budget_Notification_Store,
    crossed_thresholds,
)
from agentforge.webhooks.base import Webhook_Event
from agentforge.webhooks.emitter import Webhook_Emitter
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)
from agentforge.webhooks.transport import Recording_Webhook_Transport

ORG = uuid.uuid4()
PERIOD_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _status(
    *,
    spent: str,
    limit: str | None = "100",
    action: str | None = "warn",
    org_id=ORG,
    period_start: datetime = PERIOD_START,
) -> Budget_Status:
    limit_amount = Decimal(limit) if limit is not None else None
    spent_amount = Decimal(spent)
    exceeded = limit_amount is not None and spent_amount >= limit_amount
    return Budget_Status(
        org_id=org_id,
        period_start=period_start,
        period_end=period_start + timedelta(days=31),
        spent=spent_amount,
        limit_amount=limit_amount,
        action=action,
        exceeded=exceeded,
        blocked=exceeded and action == "block",
    )


@pytest.fixture
def wired():
    """Return ``(service, claims, transport, subscriptions)`` with one subscriber."""
    claims = InMemory_Budget_Notification_Store()
    deliveries = InMemory_Webhook_Delivery_Store()
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    transport = Recording_Webhook_Transport()
    emitter = Webhook_Emitter(subscriptions, deliveries, transport, max_attempts=1)
    subscriptions.create(
        ORG,
        url="https://hooks.example.com/budget",
        secret="k",
        events=(Webhook_Event.BUDGET_THRESHOLD_CROSSED,),
    )
    return Budget_Alert_Service(claims, emitter), claims, transport, subscriptions


# --- the pure classification ------------------------------------------------------


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (None, ()),  # no budget: nothing to cross
        (Decimal("0"), ()),
        (Decimal("79.99"), ()),
        (Decimal("80"), (80,)),
        (Decimal("99.9"), (80,)),
        (Decimal("100"), (80, 100)),
        (Decimal("450"), (80, 100)),
    ],
)
def test_crossed_thresholds(percent, expected):
    assert crossed_thresholds(percent) == expected


def test_the_threshold_vocabulary_is_ascending_and_bounded():
    """Ascending matters: a jump past both reports the lower one too, which runbooks key on."""
    assert BUDGET_THRESHOLDS == tuple(sorted(BUDGET_THRESHOLDS))
    assert all(0 < t for t in BUDGET_THRESHOLDS)


def test_pending_performs_no_io(wired):
    """The request path calls this on every budgeted request; it must be free."""
    service, claims, transport, _subs = wired
    assert service.pending(_status(spent="85")) == (80,)
    assert claims.claimed(ORG, PERIOD_START) == ()
    assert transport.attempts == 0


# --- announcing -------------------------------------------------------------------


def test_crossing_a_threshold_emits_once_and_then_never_again(wired):
    service, claims, transport, _subs = wired

    service.announce(_status(spent="85"))
    assert transport.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)

    # Every subsequent request in the period still *observes* the crossing, and says nothing.
    for spent in ("86", "90", "99"):
        service.announce(_status(spent=spent))
    assert transport.attempts == 1


def test_the_payload_carries_the_exact_numbers_and_the_blocked_flag(wired):
    import json

    service, _claims, transport, _subs = wired
    service.announce(_status(spent="100.00000001", limit="100", action="block"))

    envelope = json.loads(transport.calls[0][1])
    assert envelope["event"] == "budget.threshold_crossed"
    data = envelope["data"]
    assert data["threshold_percent"] == 80
    # Exact decimal strings, never floats.
    assert data["spent"] == "100.00000001"
    assert data["limit_amount"] == "100"
    assert data["period_start"] == PERIOD_START.isoformat()
    assert data["period_end"] == (PERIOD_START + timedelta(days=31)).isoformat()
    # So a consumer can tell "you are being warned" from "your runs are refused".
    assert data["blocked"] is True


def test_jumping_past_both_thresholds_announces_both(wired):
    service, claims, transport, _subs = wired
    service.announce(_status(spent="150"))
    assert claims.claimed(ORG, PERIOD_START) == (80, 100)
    assert transport.attempts == 2


def test_reaching_the_second_threshold_later_announces_only_it(wired):
    import json

    service, claims, transport, _subs = wired
    service.announce(_status(spent="85"))
    service.announce(_status(spent="120"))

    assert claims.claimed(ORG, PERIOD_START) == (80, 100)
    assert transport.attempts == 2
    thresholds = [
        json.loads(body)["data"]["threshold_percent"] for _url, body, _h in transport.calls
    ]
    assert thresholds == [80, 100]


def test_an_unbudgeted_organization_is_never_notified(wired):
    service, claims, transport, _subs = wired
    service.announce(_status(spent="9999", limit=None, action=None))
    assert claims.claimed(ORG, PERIOD_START) == ()
    assert transport.attempts == 0


def test_a_new_period_starts_from_a_clean_slate(wired):
    """The period is part of the claim key, so no scheduled job rolls it over."""
    service, claims, transport, _subs = wired
    service.announce(_status(spent="85"))
    service.announce(_status(spent="85", period_start=datetime(2026, 9, 1, tzinfo=timezone.utc)))

    assert transport.attempts == 2
    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert claims.claimed(ORG, datetime(2026, 9, 1, tzinfo=timezone.utc)) == (80,)


def test_another_organizations_crossing_is_a_separate_claim(wired):
    service, claims, transport, subscriptions = wired
    other = uuid.uuid4()
    subscriptions.create(
        other,
        url="https://hooks.example.com/other",
        secret="k",
        events=(Webhook_Event.BUDGET_THRESHOLD_CROSSED,),
    )

    service.announce(_status(spent="85"))
    service.announce(_status(spent="85", org_id=other))

    assert transport.attempts == 2
    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert claims.claimed(other, PERIOD_START) == (80,)


# --- failure handling -------------------------------------------------------------


def test_a_failed_delivery_releases_the_claim_so_it_is_retried(wired):
    """A delivery outage must not consume the one notification the org was going to get."""
    service, claims, transport, _subs = wired
    service._emitter._transport = Recording_Webhook_Transport(succeed_from_attempt=None)

    service.announce(_status(spent="85"))
    assert claims.claimed(ORG, PERIOD_START) == ()

    # The next request that observes the crossing tries again, and this time it lands.
    service._emitter._transport = transport
    service.announce(_status(spent="85"))
    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert transport.attempts == 1


def test_no_subscribers_keeps_the_claim(wired):
    """Nothing failed — there was simply nobody to tell, and that is not worth retrying."""
    claims = InMemory_Budget_Notification_Store()
    deliveries = InMemory_Webhook_Delivery_Store()
    subscriptions = InMemory_Webhook_Subscription_Store(deliveries)
    transport = Recording_Webhook_Transport()
    service = Budget_Alert_Service(
        claims, Webhook_Emitter(subscriptions, deliveries, transport, max_attempts=1)
    )

    service.announce(_status(spent="85"))

    assert transport.attempts == 0
    assert claims.claimed(ORG, PERIOD_START) == (80,)


def test_a_broken_claim_store_never_reaches_the_caller(wired):
    service, _claims, transport, _subs = wired

    class _Broken:
        def claim(self, *args, **kwargs):
            raise RuntimeError("store down")

    service._store = _Broken()
    service.announce(_status(spent="150"))  # must not raise
    assert transport.attempts == 0


def test_a_broken_emitter_never_reaches_the_caller(wired):
    service, _claims, _transport, _subs = wired

    class _Broken:
        def emit(self, *args, **kwargs):
            raise RuntimeError("emitter down")

    service._emitter = _Broken()
    service.announce(_status(spent="85"))  # must not raise


# --- reconciling on a ceiling change ----------------------------------------------


def test_raising_the_ceiling_drops_claims_that_no_longer_apply(wired):
    """Otherwise the next genuine crossing is silent, because the old claim still stands."""
    service, claims, transport, _subs = wired
    service.announce(_status(spent="85", limit="100"))
    assert claims.claimed(ORG, PERIOD_START) == (80,)

    # The owner raises the ceiling tenfold: 85 of 1000 is 8.5%, nothing is crossed.
    dropped = service.reconcile(_status(spent="85", limit="1000"))
    assert dropped == 1
    assert claims.claimed(ORG, PERIOD_START) == ()

    # And crossing 80% of the NEW ceiling notifies again.
    service.announce(_status(spent="850", limit="1000"))
    assert transport.attempts == 2


def test_reconciling_keeps_claims_that_still_apply(wired):
    service, claims, _transport, _subs = wired
    service.announce(_status(spent="150", limit="100"))
    assert claims.claimed(ORG, PERIOD_START) == (80, 100)

    # Lowering the ceiling leaves both crossed, so nothing is dropped and nothing re-announces.
    assert service.reconcile(_status(spent="150", limit="50")) == 0
    assert claims.claimed(ORG, PERIOD_START) == (80, 100)


def test_removing_the_budget_drops_every_claim(wired):
    service, claims, _transport, _subs = wired
    service.announce(_status(spent="150", limit="100"))

    assert service.reconcile(_status(spent="150", limit=None, action=None)) == 2
    assert claims.claimed(ORG, PERIOD_START) == ()


def test_a_broken_store_makes_reconcile_a_no_op_rather_than_a_failure(wired):
    service, _claims, _transport, _subs = wired

    class _Broken:
        def release_except(self, *args, **kwargs):
            raise RuntimeError("store down")

    service._store = _Broken()
    assert service.reconcile(_status(spent="85")) == 0


# --- the claim store itself -------------------------------------------------------


def test_only_the_first_claim_wins():
    store = InMemory_Budget_Notification_Store()
    assert store.claim(ORG, PERIOD_START, 80) is True
    assert store.claim(ORG, PERIOD_START, 80) is False
    assert store.claim(ORG, PERIOD_START, 100) is True
    assert store.claim(ORG, PERIOD_END, 80) is True


def test_release_reports_whether_anything_was_removed():
    store = InMemory_Budget_Notification_Store()
    store.claim(ORG, PERIOD_START, 80)
    assert store.release(ORG, PERIOD_START, 80) is True
    assert store.release(ORG, PERIOD_START, 80) is False


def test_release_except_is_scoped_to_one_org_and_period():
    store = InMemory_Budget_Notification_Store()
    other = uuid.uuid4()
    for org in (ORG, other):
        store.claim(org, PERIOD_START, 80)
        store.claim(org, PERIOD_START, 100)
    store.claim(ORG, PERIOD_END, 80)

    assert store.release_except(ORG, PERIOD_START, (100,)) == 1

    assert store.claimed(ORG, PERIOD_START) == (100,)
    assert store.claimed(other, PERIOD_START) == (80, 100)
    assert store.claimed(ORG, PERIOD_END) == (80,)
