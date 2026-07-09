"""Property 3 (production-hardening, Task 4.2): cross-tenant reads never leak.

Runs fully keyless against the in-memory reference implementation of each newly-persistent
Domain_Store (cross-tenant scoping is identical across the in-memory and ``Pg_*``
implementations behind each seam). For any two distinct ``org_id`` values and any record
created under org A, a read of that record's id under org B returns ``None`` / empty — which
the router surfaces as HTTP 404 — and never the record's contents and never a 403. The owner
(org A) still reads its own record unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.api_keys import InMemory_API_Key_Store
from agentforge.enterprise.identity import InMemory_Identity_Store
from agentforge.enterprise.models import API_Key
from agentforge.enterprise.rbac import Role
from agentforge.integrations.connection import InMemory_Integration_Connection_Store
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.observability.evaluation.store import InMemory_Evaluation_Store
from agentforge.observability.models import (
    Evaluation_Dataset,
    Prompt_Version,
    Usage_Record,
)
from agentforge.observability.prompt_registry.store import InMemory_Prompt_Store
from agentforge.observability.usage.store import InMemory_Usage_Store
from agentforge.tracing.recorder import InMemory_Trace_Recorder


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _window():
    now = _now()
    return now - timedelta(days=1), now + timedelta(days=1)


def _conversation_case(org_a, org_b) -> None:
    store = InMemory_Conversation_Store()
    cid = store.create(org_a)
    store.append(org_a, cid, "user", "secret-content")
    # Cross-tenant reads return nothing (never the contents).
    assert store.exists(org_b, cid) is False
    assert store.history(org_b, cid) == []
    # Owner still sees its message unchanged.
    assert [m.content for m in store.history(org_a, cid)] == ["secret-content"]


def _trace_case(org_a, org_b) -> None:
    recorder = InMemory_Trace_Recorder()
    recorder.record(org_a, "run-1", "reason", detail={"secret": "x"})
    assert recorder.get_trace(org_b, "run-1").entries == []
    assert len(recorder.get_trace(org_a, "run-1").entries) == 1


def _multi_agent_case(org_a, org_b) -> None:
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(org_a, "conv", "secret-task")
    assert store.get(org_b, run.id) is None
    assert store.messages(org_b, run.id) == []
    assert store.get(org_a, run.id) is not None


def _identity_case(org_a, org_b) -> None:
    store = InMemory_Identity_Store()
    user = store.create_user(f"user-{uuid.uuid4().hex}@example.com", "argon2-hash")
    store.add_membership(user.id, org_a, Role.OWNER)
    # The org-scoped membership read from a different org yields nothing (never a role/403).
    assert store.get_membership(user.id, org_b) is None
    assert store.list_org_members(org_b) == []
    # Owner still sees the membership.
    assert store.get_membership(user.id, org_a).role == Role.OWNER
    assert len(store.list_org_members(org_a)) == 1


def _api_key_case(org_a, org_b) -> None:
    store = InMemory_API_Key_Store()
    key = API_Key(
        id=uuid.uuid4(),
        org_id=org_a,
        role=Role.ADMIN,
        key_prefix="af_abcde",
        key_hash="argon2-hash",
        revoked_at=None,
        created_at=_now(),
    )
    store.create(key)
    assert store.get_for_org(org_b, key.id) is None
    assert store.list_for_org(org_b) == []
    assert store.revoke_for_org(org_b, key.id) is None
    # Owner still sees its (unrevoked) key.
    owner_key = store.get_for_org(org_a, key.id)
    assert owner_key is not None
    assert owner_key.revoked_at is None


def _usage_case(org_a, org_b) -> None:
    store = InMemory_Usage_Store()
    now = _now()
    store.add(
        Usage_Record(
            id=uuid.uuid4(),
            org_id=org_a,
            user_id=None,
            provider="groq",
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cost=Decimal("0"),
            created_at=now,
        )
    )
    start, end = now - timedelta(days=1), now + timedelta(days=1)
    assert store.list_for_org(org_b, start=start, end=end) == []
    assert len(store.list_for_org(org_a, start=start, end=end)) == 1


def _prompt_case(org_a, org_b) -> None:
    store = InMemory_Prompt_Store()
    name = "greeting"
    store.add_version(
        Prompt_Version(
            id=uuid.uuid4(),
            org_id=org_a,
            template_name=name,
            version=1,
            body="secret body {x}",
            variables=("x",),
            created_at=_now(),
        )
    )
    assert store.get_version(org_b, name, 1) is None
    assert store.get_latest(org_b, name) is None
    assert store.list_versions(org_b, name) == []
    assert store.list_template_names(org_b) == []
    # Owner still sees it.
    assert store.get_version(org_a, name, 1).body == "secret body {x}"


def _evaluation_case(org_a, org_b) -> None:
    store = InMemory_Evaluation_Store()
    dataset_id = uuid.uuid4()
    store.add_dataset(
        Evaluation_Dataset(id=dataset_id, org_id=org_a, name="secret-ds", created_at=_now())
    )
    assert store.get_dataset(org_b, dataset_id) is None
    assert store.list_datasets(org_b) == []
    assert store.get_dataset(org_a, dataset_id) is not None


def _integration_connection_case(org_a, org_b) -> None:
    store = InMemory_Integration_Connection_Store()
    connection = store.create(org_a, "slack", {"default_channel": "#secret"})
    assert store.get(org_b, connection.id) is None
    assert store.list_for_org(org_b) == []
    assert store.get(org_a, connection.id) is not None


_DISPATCH = {
    "conversation": _conversation_case,
    "trace": _trace_case,
    "multi_agent_run": _multi_agent_case,
    "identity": _identity_case,
    "api_key": _api_key_case,
    "usage": _usage_case,
    "prompt": _prompt_case,
    "evaluation": _evaluation_case,
    "integration_connection": _integration_connection_case,
}

_org_pairs = st.lists(st.uuids(), min_size=2, max_size=2, unique=True)


# Feature: production-hardening, Property 3: cross-tenant reads never leak (404, never 403 or contents)
@hyp_settings(max_examples=100, deadline=None)
@given(orgs=_org_pairs, kind=st.sampled_from(sorted(_DISPATCH)))
def test_cross_tenant_reads_never_leak(orgs, kind):
    """Feature: production-hardening, Property 3: For any two distinct org_id values and a
    record created under org A, a read of that id under org B returns None/empty (surfaced
    as HTTP 404) and never the record's contents and never a 403 — for every newly-persistent
    Domain_Store.

    Validates: Requirements 1.4, 8.4
    """
    org_a, org_b = orgs
    _DISPATCH[kind](org_a, org_b)
