"""Properties of the audit trail: tenant isolation, append-only, and no credential leakage.

Three invariants that must hold for *any* sequence of recorded events, not just the ones a
hand-written test happens to pick:

1. **Tenant isolation.** A read for one organization returns only that organization's
   events, whatever interleaving of tenants produced them.
2. **Append-only.** Recording never modifies or drops an earlier event; the set of events
   for an org only ever grows, and each id appears exactly once.
3. **No credential leakage.** Whatever metadata a call site passes, an admitted row never
   contains a credential-named key — the admission policy is total over its input space.

Written against ``InMemory_Audit_Log`` so the lane stays keyless; ``Pg_Audit_Log`` parity is
asserted in ``tests/integration/test_audit_log_integration.py``.
"""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from agentforge.enterprise.audit import (
    Audit_Action,
    Audit_Service,
    InMemory_Audit_Log,
    admit_metadata,
)
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Role

_ACTIONS = list(Audit_Action)

# An interleaving of writes across two tenants: (tenant_index, action, target).
_writes = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=1),
        st.sampled_from(_ACTIONS),
        st.text(min_size=0, max_size=12),
    ),
    min_size=1,
    max_size=30,
)


def _principal(org_id: uuid.UUID) -> Principal:
    return Principal(
        kind=PrincipalKind.USER.value,
        user_id=uuid.uuid4(),
        key_id=None,
        org_id=org_id,
        role=Role.OWNER,
        permissions=frozenset(),
    )


@settings(max_examples=150, deadline=None)
@given(writes=_writes)
def test_a_read_never_crosses_a_tenant_boundary(writes) -> None:
    orgs = [uuid.uuid4(), uuid.uuid4()]
    log = InMemory_Audit_Log()
    service = Audit_Service(log)
    expected: dict[uuid.UUID, list[str]] = {orgs[0]: [], orgs[1]: []}

    for tenant_index, action, target in writes:
        org_id = orgs[tenant_index]
        service.record(
            _principal(org_id),
            action,
            target_type="thing",
            target_id=target or None,
        )
        expected[org_id].append(action.value)

    for org_id in orgs:
        # A generous limit so the assertion is about isolation, not pagination.
        events = log.list_for_org(org_id, limit=1000)
        assert all(event.org_id == org_id for event in events)
        # Same multiset of actions, and nothing from the other tenant.
        assert sorted(e.action for e in events) == sorted(expected[org_id])


@settings(max_examples=100, deadline=None)
@given(writes=_writes)
def test_recording_only_ever_appends(writes) -> None:
    org_id = uuid.uuid4()
    log = InMemory_Audit_Log()
    service = Audit_Service(log)
    seen_ids: list[uuid.UUID] = []

    for _tenant_index, action, target in writes:
        before = {e.id: (e.action, e.created_at) for e in log.list_for_org(org_id, limit=1000)}
        event = service.record(
            _principal(org_id), action, target_type="thing", target_id=target or None
        )
        assert event is not None
        seen_ids.append(event.id)

        after = {e.id: (e.action, e.created_at) for e in log.list_for_org(org_id, limit=1000)}
        # Every previously recorded event is still present, unchanged.
        for event_id, snapshot in before.items():
            assert after[event_id] == snapshot
        assert len(after) == len(before) + 1

    # No id is ever reused, so a row can never be silently overwritten.
    assert len(set(seen_ids)) == len(seen_ids)


# Arbitrary metadata a call site might pass: scalar values under arbitrary keys.
_metadata = st.dictionaries(
    st.text(min_size=1, max_size=16),
    st.one_of(
        st.text(max_size=32),
        st.integers(),
        st.booleans(),
        st.none(),
    ),
    max_size=6,
)

_CREDENTIAL_MARKERS = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "bearer",
    "signature",
    "hash",
)


@settings(max_examples=200, deadline=None)
@given(metadata=_metadata)
def test_admitted_metadata_never_contains_a_credential_named_key(metadata) -> None:
    """Total function: either it raises, or the result is free of credential-named keys."""
    try:
        admitted = admit_metadata(metadata)
    except ValueError:
        return  # refusing is always an acceptable outcome
    for key in admitted:
        lowered = key.lower()
        assert not any(marker in lowered for marker in _CREDENTIAL_MARKERS)


@settings(max_examples=100, deadline=None)
@given(metadata=_metadata)
def test_a_recorded_event_carries_exactly_the_admitted_metadata(metadata) -> None:
    org_id = uuid.uuid4()
    log = InMemory_Audit_Log()
    try:
        expected = admit_metadata(metadata)
    except ValueError:
        return
    event = Audit_Service(log).record(
        _principal(org_id), Audit_Action.MEMBER_ADDED, target_type="member", metadata=metadata
    )
    assert event is not None
    assert event.metadata == expected
