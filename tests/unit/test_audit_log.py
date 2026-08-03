"""Unit tests for the audit trail: the store, the service, and the metadata policy.

An audit trail is only worth having if three things hold, and each is tested here:

1. **It cannot be edited or lose a tenant boundary.** The seam has no update or delete, and
   every read is filtered by ``org_id``.
2. **It cannot become a place a credential ends up.** ``metadata`` admits non-secret scalars
   only — an audit row records *that* an API key was created, never its secret.
3. **Its failure posture is a deployment decision.** Fail open by default (an audit store
   outage must not become a platform outage), fail closed when the operator says so.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agentforge.enterprise.audit import (
    MAX_METADATA_KEYS,
    MAX_METADATA_VALUE_LENGTH,
    Audit_Action,
    Audit_Service,
    InMemory_Audit_Log,
    admit_metadata,
)
from agentforge.enterprise.base import Audit_Log
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Role

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _user_principal(org_id=ORG, user_id=None) -> Principal:
    return Principal(
        kind=PrincipalKind.USER.value,
        user_id=user_id or uuid.uuid4(),
        key_id=None,
        org_id=org_id,
        role=Role.OWNER,
        permissions=frozenset(),
    )


def _key_principal(org_id=ORG) -> Principal:
    return Principal(
        kind=PrincipalKind.API_KEY.value,
        user_id=None,
        key_id=uuid.uuid4(),
        org_id=org_id,
        role=Role.ADMIN,
        permissions=frozenset(),
    )


# --- the seam ---------------------------------------------------------------------


def test_the_seam_offers_no_way_to_change_or_erase_an_event():
    """An audit trail that can be edited answers no compliance question."""
    surface = {name for name in vars(Audit_Log) if not name.startswith("_")}
    assert surface == {"record", "list_for_org"}


def test_events_are_returned_newest_first():
    log = InMemory_Audit_Log()
    principal = _user_principal()
    service = Audit_Service(log)

    first = service.record(principal, Audit_Action.TEAM_CREATED, target_type="team")
    second = service.record(principal, Audit_Action.MEMBER_ADDED, target_type="member")

    listed = log.list_for_org(ORG)
    assert [event.id for event in listed] == [second.id, first.id]


def test_equal_timestamps_are_ordered_deterministically():
    """Two writes in one request share a timestamp; a page boundary must not be arbitrary."""
    log = InMemory_Audit_Log()
    principal = _user_principal()
    for _ in range(6):
        event = Audit_Service(log).record(
            principal, Audit_Action.MEMBER_ADDED, target_type="member"
        )
        object.__setattr__(event, "created_at", NOW)  # force an exact tie

    first_page = [e.id for e in log.list_for_org(ORG, limit=3)]
    assert first_page == [e.id for e in log.list_for_org(ORG, limit=3)]
    assert len(set(first_page)) == 3


def test_reads_are_scoped_to_one_org():
    log = InMemory_Audit_Log()
    Audit_Service(log).record(
        _user_principal(ORG), Audit_Action.MEMBER_ADDED, target_type="member"
    )
    Audit_Service(log).record(
        _user_principal(OTHER_ORG), Audit_Action.MEMBER_REMOVED, target_type="member"
    )

    assert [e.action for e in log.list_for_org(ORG)] == ["member.added"]
    assert [e.action for e in log.list_for_org(OTHER_ORG)] == ["member.removed"]
    assert log.list_for_org(uuid.uuid4()) == []


def test_filters_compose():
    log = InMemory_Audit_Log()
    actor = uuid.uuid4()
    other_actor = uuid.uuid4()
    service = Audit_Service(log)
    service.record(
        _user_principal(user_id=actor), Audit_Action.MEMBER_ADDED, target_type="member"
    )
    service.record(
        _user_principal(user_id=other_actor),
        Audit_Action.MEMBER_ADDED,
        target_type="member",
    )
    service.record(
        _user_principal(user_id=actor), Audit_Action.TEAM_CREATED, target_type="team"
    )

    assert len(log.list_for_org(ORG, actions=["member.added"])) == 2
    assert len(log.list_for_org(ORG, actor_id=actor)) == 2
    assert len(log.list_for_org(ORG, actions=["member.added"], actor_id=actor)) == 1
    assert log.list_for_org(ORG, limit=1) == log.list_for_org(ORG, limit=1)
    assert len(log.list_for_org(ORG, limit=2)) == 2


def test_time_window_filters_are_inclusive():
    log = InMemory_Audit_Log()
    event = Audit_Service(log).record(
        _user_principal(), Audit_Action.MEMBER_ADDED, target_type="member"
    )
    object.__setattr__(event, "created_at", NOW)

    assert log.list_for_org(ORG, start=NOW, end=NOW)
    assert not log.list_for_org(ORG, start=NOW + timedelta(seconds=1))
    assert not log.list_for_org(ORG, end=NOW - timedelta(seconds=1))


# --- the service ------------------------------------------------------------------


def test_a_user_actor_is_recorded_by_id_and_kind():
    log = InMemory_Audit_Log()
    principal = _user_principal()

    event = Audit_Service(log).record(
        principal,
        Audit_Action.MEMBER_ADDED,
        target_type="member",
        target_id="target-1",
        metadata={"email": "new@example.com", "role": "member"},
    )

    assert event is not None
    assert event.org_id == ORG
    assert event.actor_kind == "user"
    assert event.actor_user_id == principal.user_id
    assert event.actor_key_id is None
    assert event.action == "member.added"
    assert event.target_type == "member"
    assert event.target_id == "target-1"
    assert event.metadata == {"email": "new@example.com", "role": "member"}
    assert event.created_at.tzinfo is not None


def test_an_api_key_actor_is_recorded_by_key_id():
    log = InMemory_Audit_Log()
    principal = _key_principal()

    event = Audit_Service(log).record(
        principal, Audit_Action.API_KEY_CREATED, target_type="api_key"
    )

    assert event.actor_kind == "api_key"
    assert event.actor_key_id == principal.key_id
    assert event.actor_user_id is None


def test_an_event_cannot_be_written_into_another_tenants_trail():
    """There is no org parameter: the tenant is always the acting principal's."""
    log = InMemory_Audit_Log()
    Audit_Service(log).record(
        _user_principal(OTHER_ORG), Audit_Action.MEMBER_ADDED, target_type="member"
    )
    assert log.list_for_org(ORG) == []


# --- failure posture --------------------------------------------------------------


class _BrokenLog(Audit_Log):
    def record(self, event):
        raise RuntimeError("audit store is down")

    def list_for_org(self, org_id, **kwargs):  # pragma: no cover - unused
        return []


def test_fail_open_is_the_default_and_is_logged_as_an_error(caplog):
    """An audit store outage must not become a platform outage — but it is not silent."""
    import logging

    service = Audit_Service(_BrokenLog())
    with caplog.at_level(logging.ERROR, logger="agentforge.enterprise.audit"):
        result = service.record(
            _user_principal(), Audit_Action.MEMBER_ADDED, target_type="member"
        )

    assert result is None
    assert service.required is False
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, "a gap in an audit trail must be reported at ERROR"


def test_fail_closed_propagates_when_the_operator_requires_auditing():
    from agentforge.enterprise.audit import AuditUnavailableError

    service = Audit_Service(_BrokenLog(), required=True)

    assert service.required is True
    with pytest.raises(AuditUnavailableError) as excinfo:
        service.record(_user_principal(), Audit_Action.MEMBER_ADDED, target_type="member")
    # The error names the change that went unrecorded, so the response can too.
    assert excinfo.value.action == "member.added"
    assert "could not be recorded" in str(excinfo.value)


def test_an_event_can_be_recorded_into_a_freshly_created_org():
    """The one action whose subject is a different tenant than the caller's current one."""
    log = InMemory_Audit_Log()
    new_org = uuid.uuid4()

    event = Audit_Service(log).record(
        _user_principal(ORG),
        Audit_Action.ORG_CREATED,
        target_type="organization",
        org_id=new_org,
    )

    assert event.org_id == new_org
    assert log.list_for_org(new_org)
    assert log.list_for_org(ORG) == []


def test_the_failure_posture_comes_from_settings():
    from agentforge.config.container import build_enterprise_context
    from agentforge.config.settings import Settings

    def _settings(**overrides):
        return Settings(
            profile="local",
            database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
            redis_url="redis://localhost:6379/0",
            **overrides,
        )

    assert build_enterprise_context(_settings()).audit_service.required is False
    assert (
        build_enterprise_context(_settings(audit_log_required=True))
        .audit_service.required
        is True
    )


# --- metadata admission -----------------------------------------------------------


def test_scalar_metadata_is_admitted_as_a_copy():
    submitted = {"email": "a@example.com", "count": 2, "ok": True, "note": None}
    admitted = admit_metadata(submitted)

    assert admitted == submitted
    admitted["email"] = "changed"
    assert submitted["email"] == "a@example.com"


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "api_key",
        "secret",
        "client_secret",
        "password",
        "authorization",
        "bearer",
        "signature",
        # A hash is not a secret, but publishing one invites offline cracking and it is
        # never the auditable fact.
        "password_hash",
    ],
)
def test_credential_named_metadata_is_refused(key: str):
    with pytest.raises(ValueError) as excinfo:
        admit_metadata({key: "whatever"})
    assert key in str(excinfo.value)


@pytest.mark.parametrize("value", [{"nested": 1}, ["a"], object()])
def test_non_scalar_metadata_is_refused(value):
    with pytest.raises(ValueError):
        admit_metadata({"detail": value})


def test_too_many_keys_is_a_call_site_error_and_raises():
    """A key count is fixed by the call site, so exceeding it is a programming error."""
    with pytest.raises(ValueError):
        admit_metadata({f"k{i}": "v" for i in range(MAX_METADATA_KEYS + 1)})
    assert admit_metadata({f"k{i}": "v" for i in range(MAX_METADATA_KEYS)})


def test_an_over_long_value_is_truncated_not_refused():
    """A long value comes from request data the API accepted; refusing to record the action
    because a name was long would be the trail failing at its one job. It is truncated
    visibly instead, so a reader can tell."""
    admitted = admit_metadata({"note": "x" * (MAX_METADATA_VALUE_LENGTH + 50)})

    value = admitted["note"]
    assert len(value) == MAX_METADATA_VALUE_LENGTH
    assert value.endswith("\u2026")
    # A value at the bound is untouched.
    exact = "y" * MAX_METADATA_VALUE_LENGTH
    assert admit_metadata({"note": exact})["note"] == exact


def test_an_admission_failure_follows_the_configured_posture(caplog):
    """It must not escape as an unhandled error: the audited action has already happened."""
    import logging

    log = InMemory_Audit_Log()
    principal = _user_principal()

    # A non-scalar value is a call-site error; fail-open still must not raise at the caller.
    with caplog.at_level(logging.ERROR, logger="agentforge.enterprise.audit"):
        assert (
            Audit_Service(log).record(
                principal,
                Audit_Action.MEMBER_ADDED,
                target_type="member",
                metadata={"nested": {"a": 1}},
            )
            is None
        )
    assert [r for r in caplog.records if r.levelno == logging.ERROR]
    assert log.list_for_org(ORG) == []

    # Fail closed reports it as an audit failure, not as a generic error.
    from agentforge.enterprise.audit import AuditUnavailableError

    with pytest.raises(AuditUnavailableError):
        Audit_Service(log, required=True).record(
            principal,
            Audit_Action.MEMBER_ADDED,
            target_type="member",
            metadata={"nested": {"a": 1}},
        )


def test_empty_metadata_is_admitted():
    assert admit_metadata(None) == {}
    assert admit_metadata({}) == {}


def test_the_recorded_action_vocabulary_is_stable():
    """These strings are persisted and queried; renaming one silently breaks history."""
    assert {action.value for action in Audit_Action} == {
        "org.created",
        "member.added",
        "member.role_changed",
        "member.removed",
        "team.created",
        "team.deleted",
        "team_member.added",
        "team_member.removed",
        "api_key.created",
        "api_key.revoked",
        "budget.set",
        "budget.removed",
        "integration_connection.created",
        "integration_connection.updated",
        "integration_connection.deleted",
        "webhook.created",
        "webhook.updated",
        "webhook.deleted",
        "webhook.redelivered",
    }


# --- keyset pagination ------------------------------------------------------------
#
# `limit` alone cannot walk a trail: an org past one page has older history that is simply
# unreachable, and a client that tries to page by moving `end` backwards repeats or skips
# rows wherever two events share a timestamp — which two writes in one request always do.


def test_before_is_a_keyset_cursor_that_walks_the_whole_trail():
    log = InMemory_Audit_Log()
    principal = _user_principal()
    service = Audit_Service(log)
    recorded = [
        service.record(principal, Audit_Action.MEMBER_ADDED, target_type="member")
        for _ in range(7)
    ]
    # Force an exact timestamp tie across every event: the hard case for a cursor.
    for event in recorded:
        object.__setattr__(event, "created_at", NOW)

    walked: list = []
    cursor = None
    while True:
        page = log.list_for_org(ORG, before=cursor, limit=3)
        if not page:
            break
        walked.extend(page)
        last = page[-1]
        cursor = (last.created_at, last.id)

    # Every event exactly once, in the same order a single large page would have given.
    assert [e.id for e in walked] == [
        e.id for e in log.list_for_org(ORG, limit=100)
    ]
    assert len({e.id for e in walked}) == len(recorded)


def test_the_actor_filter_matches_a_key_actor_too():
    """The API reports one actor id per row, so the filter must accept what it reported."""
    log = InMemory_Audit_Log()
    key_principal = _key_principal()
    Audit_Service(log).record(
        key_principal, Audit_Action.API_KEY_CREATED, target_type="api_key"
    )
    Audit_Service(log).record(
        _user_principal(), Audit_Action.MEMBER_ADDED, target_type="member"
    )

    matched = log.list_for_org(ORG, actor_id=key_principal.key_id)

    assert [e.action for e in matched] == ["api_key.created"]
