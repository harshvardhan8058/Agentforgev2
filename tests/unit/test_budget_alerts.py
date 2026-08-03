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
from agentforge.webhooks.dispatcher import Webhook_Dispatcher
from agentforge.webhooks.outbox import InMemory_Webhook_Outbox
from agentforge.webhooks.store import (
    InMemory_Webhook_Delivery_Store,
    InMemory_Webhook_Subscription_Store,
)

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


class _Clock:
    """Injectable monotonic clock, so the retry cooldown is asserted rather than waited out."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Outbox_Probe:
    """Reads the outbox the way the old tests read a transport: "what went out, in order".

    Announcing now means *enqueueing*, so the assertion that used to be "the endpoint was called"
    is "a durable row exists". The row carries the payload verbatim, so the payload assertions are
    unchanged in substance.
    """

    def __init__(self, outbox: InMemory_Webhook_Outbox) -> None:
        self._outbox = outbox

    @property
    def attempts(self) -> int:
        """Rows enqueued for this org, oldest first — the analogue of "HTTP attempts made"."""
        return len(self.rows)

    @property
    def rows(self):
        return sorted(self._outbox.list_for_org(ORG), key=lambda e: e.created_at)

    @property
    def calls(self):
        """``(url, body, headers)``-shaped, so payload assertions read as they did before."""
        import json

        return [
            (None, json.dumps({"data": row.payload}).encode(), {}) for row in self.rows
        ]

    def keys(self) -> list[str | None]:
        return [row.idempotency_key for row in self.rows]


@pytest.fixture
def wired():
    """Return ``(service, claims, probe, subscriptions, clock)`` with one subscriber."""
    claims = InMemory_Budget_Notification_Store()
    outbox = InMemory_Webhook_Outbox()
    subscriptions = InMemory_Webhook_Subscription_Store(
        InMemory_Webhook_Delivery_Store()
    )
    subscriptions.create(
        ORG,
        url="https://hooks.example.com/budget",
        secret="k",
        events=(Webhook_Event.BUDGET_THRESHOLD_CROSSED,),
    )
    clock = _Clock()
    service = Budget_Alert_Service(
        claims, Webhook_Dispatcher(subscriptions, outbox), clock=clock
    )
    return service, claims, _Outbox_Probe(outbox), subscriptions, clock


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
    service, claims, probe, _subs, clock = wired
    assert service.pending(_status(spent="85")) == (80,)
    assert claims.claimed(ORG, PERIOD_START) == ()
    assert probe.attempts == 0


# --- announcing -------------------------------------------------------------------


def test_crossing_a_threshold_emits_once_and_then_never_again(wired):
    service, claims, probe, _subs, clock = wired

    service.announce(_status(spent="85"))
    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)

    # Every subsequent request in the period still *observes* the crossing, and says nothing.
    for spent in ("86", "90", "99"):
        service.announce(_status(spent=spent))
    assert probe.attempts == 1


def test_the_payload_carries_the_exact_numbers_and_the_blocked_flag(wired):
    import json

    service, _claims, probe, _subs, clock = wired
    service.announce(_status(spent="100.00000001", limit="100", action="block"))

    row = probe.rows[0]
    assert row.event.value == "budget.threshold_crossed"
    data = row.payload
    assert data["threshold_percent"] == 80
    # Exact decimal strings, never floats.
    assert data["spent"] == "100.00000001"
    assert data["limit_amount"] == "100"
    assert data["period_start"] == PERIOD_START.isoformat()
    assert data["period_end"] == (PERIOD_START + timedelta(days=31)).isoformat()
    # So a consumer can tell "you are being warned" from "your runs are refused".
    assert data["blocked"] is True


def test_jumping_past_both_thresholds_announces_both(wired):
    service, claims, probe, _subs, clock = wired
    service.announce(_status(spent="150"))
    assert claims.claimed(ORG, PERIOD_START) == (80, 100)
    assert probe.attempts == 2


def test_reaching_the_second_threshold_later_announces_only_it(wired):
    import json

    service, claims, probe, _subs, clock = wired
    service.announce(_status(spent="85"))
    service.announce(_status(spent="120"))

    assert claims.claimed(ORG, PERIOD_START) == (80, 100)
    assert probe.attempts == 2
    thresholds = [
        json.loads(body)["data"]["threshold_percent"] for _url, body, _h in probe.calls
    ]
    assert thresholds == [80, 100]


def test_an_unbudgeted_organization_is_never_notified(wired):
    service, claims, probe, _subs, clock = wired
    service.announce(_status(spent="9999", limit=None, action=None))
    assert claims.claimed(ORG, PERIOD_START) == ()
    assert probe.attempts == 0


def test_a_new_period_starts_from_a_clean_slate(wired):
    """The period is part of the claim key, so no scheduled job rolls it over."""
    service, claims, probe, _subs, clock = wired
    service.announce(_status(spent="85"))
    service.announce(_status(spent="85", period_start=datetime(2026, 9, 1, tzinfo=timezone.utc)))

    assert probe.attempts == 2
    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert claims.claimed(ORG, datetime(2026, 9, 1, tzinfo=timezone.utc)) == (80,)


def test_another_organizations_crossing_is_a_separate_claim(wired):
    service, claims, probe, subscriptions, clock = wired
    other = uuid.uuid4()
    subscriptions.create(
        other,
        url="https://hooks.example.com/other",
        secret="k",
        events=(Webhook_Event.BUDGET_THRESHOLD_CROSSED,),
    )

    service.announce(_status(spent="85"))
    service.announce(_status(spent="85", org_id=other))

    # One row each, in each org's own queue — the probe is scoped to ORG on purpose.
    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert claims.claimed(other, PERIOD_START) == (80,)


# --- failure handling -------------------------------------------------------------


def test_a_delivery_that_fails_later_does_NOT_release_the_claim(wired):
    """The property durable delivery buys: the outbox owns the retry, so this service need not.

    Before the outbox, a failed delivery had to release the claim (or the notification was lost),
    which meant every request re-announced and re-dialled — and needed a cooldown and an attempt
    cap to stop that becoming an amplifier. Now the row is durable, so announcing once is enough.
    """
    service, claims, probe, _subs, _clock = wired

    service.announce(_status(spent="85"))

    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert probe.attempts == 1

    # Whatever happens to the delivery afterwards is the worker's business; the claim stands and
    # nothing is re-announced.
    service.announce(_status(spent="85"))
    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)


def test_a_subscription_lookup_failure_releases_the_claim_and_retries_at_once(wired):
    """Nothing durable was written, so the notification is still owed.

    Retried immediately rather than after a cooldown, because retrying now costs one indexed read:
    the dialling that once made a retry expensive happens in the worker, not here.
    """
    service, claims, probe, _subs, _clock = wired

    class _BrokenLookup:
        def list_for_event(self, org_id, event):
            raise RuntimeError("subscription store down")

    real_store = service._dispatcher._subscriptions
    service._dispatcher._subscriptions = _BrokenLookup()
    service.announce(_status(spent="85"))
    assert claims.claimed(ORG, PERIOD_START) == ()
    assert probe.attempts == 0

    service._dispatcher._subscriptions = real_store
    service.announce(_status(spent="85"))
    assert claims.claimed(ORG, PERIOD_START) == (80,)
    assert probe.attempts == 1


def test_an_enqueue_failure_releases_the_claim(wired):
    """A subscription matched but its row was not written, so that event is genuinely missing."""
    service, claims, _probe, _subs, _clock = wired

    class _BrokenOutbox:
        def enqueue(self, entry):
            raise RuntimeError("insert failed")

    service._dispatcher._outbox = _BrokenOutbox()
    service.announce(_status(spent="85"))

    assert claims.claimed(ORG, PERIOD_START) == ()


def test_the_announcement_carries_a_deterministic_idempotency_key(wired):
    """So a re-announcement after a released claim is recognisable as the same crossing."""
    service, _claims, probe, subscriptions, _clock = wired

    service.announce(_status(spent="85"))

    subscription_id = subscriptions.list_for_org(ORG)[0].id
    assert probe.keys() == [
        f"budget.threshold_crossed:{ORG}:{PERIOD_START.isoformat()}:80:{subscription_id}"
    ]


def test_no_subscribers_keeps_the_claim_and_enqueues_nothing(wired):
    """Nothing failed — there was simply nobody to tell, and that is not worth retrying."""
    claims = InMemory_Budget_Notification_Store()
    outbox = InMemory_Webhook_Outbox()
    service = Budget_Alert_Service(
        claims,
        Webhook_Dispatcher(
            InMemory_Webhook_Subscription_Store(InMemory_Webhook_Delivery_Store()), outbox
        ),
    )

    service.announce(_status(spent="85"))

    assert outbox.list_for_org(ORG) == []
    assert claims.claimed(ORG, PERIOD_START) == (80,)


def test_a_broken_claim_store_never_reaches_the_caller(wired):
    service, _claims, probe, _subs, _clock = wired

    class _Broken:
        def claim(self, *args, **kwargs):
            raise RuntimeError("store down")

    service._store = _Broken()
    service.announce(_status(spent="150"))  # must not raise
    assert probe.attempts == 0


def test_a_broken_dispatcher_never_reaches_the_caller(wired):
    service, _claims, _probe, _subs, _clock = wired

    class _Broken:
        def dispatch(self, *args, **kwargs):
            raise RuntimeError("dispatcher down")

    service._dispatcher = _Broken()
    service.announce(_status(spent="85"))  # must not raise


# --- a zero ceiling ---------------------------------------------------------------


def test_a_zero_ceiling_announces_only_the_100_percent_threshold():
    """"Spend nothing" is 100% used from the first request; "80% of zero" is not a quantity."""
    assert crossed_thresholds(Decimal("100"), limit_amount=Decimal("0")) == (100,)


def test_a_zero_ceiling_does_not_warn_about_approaching_a_limit_already_reached(wired):
    service, claims, probe, _subs, _clock = wired

    service.announce(_status(spent="0", limit="0"))

    assert claims.claimed(ORG, PERIOD_START) == (100,)
    assert probe.attempts == 1
    import json

    assert json.loads(probe.calls[0][1])["data"]["threshold_percent"] == 100


# --- a spend figure that is not authoritative -------------------------------------
#
# Budget_Guard fails OPEN: when month-to-date spend cannot be computed it reports zero, so a
# metering outage does not become a platform outage. "Spend is zero" and "spend is unknown" are
# then the same value and opposite facts, which matters enormously here — one of them means
# "nothing is crossed", and reconcile deletes every claim when nothing is crossed.


def _unknown_spend(**overrides) -> Budget_Status:
    base = _status(spent="0", **overrides)
    return Budget_Status(
        org_id=base.org_id,
        period_start=base.period_start,
        period_end=base.period_end,
        spent=base.spent,
        limit_amount=base.limit_amount,
        action=base.action,
        exceeded=base.exceeded,
        blocked=base.blocked,
        spend_is_authoritative=False,
    )


def test_nothing_is_announced_when_spend_is_not_authoritative(wired):
    service, claims, probe, _subs, _clock = wired
    service.announce(_unknown_spend())
    assert probe.attempts == 0
    assert claims.claimed(ORG, PERIOD_START) == ()


def test_reconcile_refuses_to_act_on_a_non_authoritative_status(wired):
    """Otherwise a metering blip during a budget edit erases the whole period's history."""
    service, claims, probe, _subs, _clock = wired
    service.announce(_status(spent="150"))
    assert claims.claimed(ORG, PERIOD_START) == (80, 100)

    assert service.reconcile(_unknown_spend()) == 0
    assert claims.claimed(ORG, PERIOD_START) == (80, 100)


# --- a snapshot whose ceiling has moved --------------------------------------------


def test_an_announcement_is_dropped_when_the_ceiling_changed_after_the_snapshot(wired):
    """A status is computed on the request path and announced afterwards, so it can go stale.

    Warning about a ceiling the owner has since raised would be wrong twice: the numbers are
    from the old ceiling, and the claim would silence the genuine crossing of the new one.
    """
    from agentforge.observability.budget import InMemory_Budget_Store

    service, claims, probe, _subs, _clock = wired
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("1000"), action="warn")
    service._budgets = budgets

    # The snapshot was taken while the ceiling was 100; it is 1000 by the time we announce.
    service.announce(_status(spent="85", limit="100"))

    assert probe.attempts == 0
    assert claims.claimed(ORG, PERIOD_START) == ()


def test_an_announcement_proceeds_when_the_ceiling_is_unchanged(wired):
    from agentforge.observability.budget import InMemory_Budget_Store

    service, claims, probe, _subs, _clock = wired
    budgets = InMemory_Budget_Store()
    budgets.upsert(ORG, limit_amount=Decimal("100"), action="warn")
    service._budgets = budgets

    service.announce(_status(spent="85", limit="100"))

    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)


def test_an_unreadable_budget_store_does_not_silence_the_announcement(wired):
    """Failing closed here would let a store blip suppress exactly the alert that matters."""
    service, claims, probe, _subs, _clock = wired

    class _Broken:
        def get(self, org_id):
            raise RuntimeError("budget store down")

    service._budgets = _Broken()
    service.announce(_status(spent="85"))

    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)


# --- the payload's percentage -----------------------------------------------------


def test_percent_used_is_rounded_the_same_way_the_api_rounds_it(wired):
    """The same state must not read 33.33 in the console and 33.333... in the notification."""
    import json

    service, _claims, probe, _subs, _clock = wired
    # 250 of 300 is 83.333...%, which crosses 80 and does not terminate.
    service.announce(_status(spent="250", limit="300"))

    data = json.loads(probe.calls[0][1])["data"]
    assert data["percent_used"] == "83.33"
    # Money is still exact, because money is not a presentation artefact.
    assert data["spent"] == "250"
    assert data["limit_amount"] == "300"


# --- off-band dispatch ------------------------------------------------------------


def test_dispatch_returns_immediately_and_the_work_happens_off_band(wired):
    service, claims, probe, _subs, _clock = wired

    assert service.dispatch(_status(spent="85")) is True
    service.drain()

    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)


def test_dispatch_survives_a_shut_down_executor(wired):
    service, _claims, probe, _subs, _clock = wired
    service._executor.shutdown()

    assert service.dispatch(_status(spent="85")) is False
    assert probe.attempts == 0


# --- concurrency ------------------------------------------------------------------


def test_concurrent_announcements_produce_exactly_one_notification(wired):
    """The property the whole claim design exists for, under the threads that actually run it."""
    import threading

    service, claims, probe, _subs, _clock = wired
    status = _status(spent="85")
    barrier = threading.Barrier(8)

    def _race() -> None:
        barrier.wait()
        service.announce(status)

    threads = [threading.Thread(target=_race) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert probe.attempts == 1
    assert claims.claimed(ORG, PERIOD_START) == (80,)


def test_the_in_memory_claim_store_is_atomic_under_concurrent_claims():
    """An unlocked check-then-set double-claimed in tens of trials out of hundreds."""
    import threading

    store = InMemory_Budget_Notification_Store()
    winners: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(16)

    def _claim() -> None:
        barrier.wait()
        won = store.claim(ORG, PERIOD_START, 80)
        with lock:
            winners.append(won)

    threads = [threading.Thread(target=_claim) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(winners) == 1


def test_reading_claims_while_another_thread_claims_does_not_raise():
    """Iterating the dict during a concurrent insert used to raise RuntimeError."""
    import threading

    store = InMemory_Budget_Notification_Store()
    stop = threading.Event()
    errors: list[BaseException] = []

    def _churn() -> None:
        threshold = 1
        while not stop.is_set():
            store.claim(ORG, PERIOD_START, threshold)
            threshold += 1

    def _read() -> None:
        try:
            while not stop.is_set():
                store.claimed(ORG, PERIOD_START)
                store.release_except(ORG, PERIOD_START, (80,))
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    writer = threading.Thread(target=_churn)
    reader = threading.Thread(target=_read)
    writer.start()
    reader.start()
    threading.Event().wait(0.3)
    stop.set()
    writer.join()
    reader.join()

    assert errors == []
