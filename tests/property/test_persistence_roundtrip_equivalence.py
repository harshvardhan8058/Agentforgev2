"""Property 2 (production-hardening, Task 4.1): persistence round-trip / model equivalence
per Domain_Store.

Runs fully keyless against the in-memory reference implementation of each newly-persistent
Domain_Store (the tenancy / round-trip logic is identical across the in-memory and ``Pg_*``
implementations behind each seam). For any record written through a store under an
``org_id``, reading it back within the same ``org_id`` returns field values equal to those
written — the write→read equivalence a restart preserves. The ``Pg_*`` durability and
model-based equivalence against real Postgres are exercised in the integration lane
(``test_domain_store_persistence_equivalence_integration.py``).
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


def _conversation_roundtrip(org, payload) -> None:
    store = InMemory_Conversation_Store()
    cid = store.create(org)
    store.append(org, cid, "user", payload)
    history = store.history(org, cid)
    assert [m.content for m in history] == [payload]
    assert [m.role for m in history] == ["user"]
    assert store.exists(org, cid) is True


def _trace_roundtrip(org, payload) -> None:
    recorder = InMemory_Trace_Recorder()
    recorder.record(org, "run-1", "reason", detail={"note": payload})
    trace = recorder.get_trace(org, "run-1")
    assert len(trace.entries) == 1
    assert trace.entries[0].step_type == "reason"
    assert trace.entries[0].detail == {"note": payload}


def _multi_agent_roundtrip(org, payload) -> None:
    store = InMemory_Multi_Agent_Run_Store()
    run = store.create(org, "conv", payload)
    got = store.get(org, run.id)
    assert got is not None
    assert got.id == run.id
    assert got.task == payload
    assert got.status == run.status


def _identity_roundtrip(org, payload) -> None:
    store = InMemory_Identity_Store()
    email = f"{payload}-{uuid.uuid4().hex}@example.com"
    user = store.create_user(email, "argon2-hash")
    created_org = store.create_organization(payload or "org")
    store.add_membership(user.id, created_org.id, Role.OWNER)

    assert store.get_user(user.id).email == email
    assert store.get_user_by_email(email).id == user.id
    membership = store.get_membership(user.id, created_org.id)
    assert membership is not None
    assert membership.role == Role.OWNER


def _api_key_roundtrip(org, payload) -> None:
    store = InMemory_API_Key_Store()
    key = API_Key(
        id=uuid.uuid4(),
        org_id=org,
        role=Role.ADMIN,
        key_prefix=f"af_{payload}"[:8],
        key_hash="argon2-hash",
        revoked_at=None,
        created_at=_now(),
    )
    store.create(key)
    got = store.get_for_org(org, key.id)
    assert got is not None
    assert got.id == key.id
    assert got.role == Role.ADMIN
    assert got.key_prefix == key.key_prefix
    assert got.key_hash == key.key_hash


def _usage_roundtrip(org, payload) -> None:
    store = InMemory_Usage_Store()
    now = _now()
    record = Usage_Record(
        id=uuid.uuid4(),
        org_id=org,
        user_id=None,
        provider="groq",
        model=payload or "model",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost=Decimal("0.12500000"),
        created_at=now,
    )
    store.add(record)
    got = store.list_for_org(org, start=now - timedelta(days=1), end=now + timedelta(days=1))
    assert len(got) == 1
    assert got[0].total_tokens == 15
    assert got[0].cost == Decimal("0.12500000")
    assert got[0].model == (payload or "model")


def _prompt_roundtrip(org, payload) -> None:
    store = InMemory_Prompt_Store()
    name = "greeting"
    version = Prompt_Version(
        id=uuid.uuid4(),
        org_id=org,
        template_name=name,
        version=1,
        body=payload or "Hi {who}",
        variables=("who",),
        created_at=_now(),
    )
    store.add_version(version)
    got = store.get_version(org, name, 1)
    assert got is not None
    assert got.body == (payload or "Hi {who}")
    assert got.variables == ("who",)
    assert store.get_latest(org, name).version == 1
    assert store.list_versions(org, name) == [1]


def _evaluation_roundtrip(org, payload) -> None:
    store = InMemory_Evaluation_Store()
    dataset_id = uuid.uuid4()
    store.add_dataset(
        Evaluation_Dataset(
            id=dataset_id, org_id=org, name=payload or "ds", created_at=_now()
        )
    )
    got = store.get_dataset(org, dataset_id)
    assert got is not None
    assert got.name == (payload or "ds")
    assert [d.id for d in store.list_datasets(org)] == [dataset_id]


def _integration_connection_roundtrip(org, payload) -> None:
    store = InMemory_Integration_Connection_Store()
    config = {"default_channel": payload or "#general"}
    connection = store.create(org, "slack", config)
    got = store.get(org, connection.id)
    assert got is not None
    assert got.integration == "slack"
    assert got.config == config


_DISPATCH = {
    "conversation": _conversation_roundtrip,
    "trace": _trace_roundtrip,
    "multi_agent_run": _multi_agent_roundtrip,
    "identity": _identity_roundtrip,
    "api_key": _api_key_roundtrip,
    "usage": _usage_roundtrip,
    "prompt": _prompt_roundtrip,
    "evaluation": _evaluation_roundtrip,
    "integration_connection": _integration_connection_roundtrip,
}


# Feature: production-hardening, Property 2: persistence round-trip / model equivalence per Domain_Store
@hyp_settings(max_examples=100, deadline=None)
@given(
    org=st.uuids(),
    kind=st.sampled_from(sorted(_DISPATCH)),
    payload=st.text(
        alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=0, max_size=40
    ),
)
def test_persistence_roundtrip_equivalence(org, kind, payload):
    """Feature: production-hardening, Property 2: For any record written through a
    newly-persistent Domain_Store under an org_id, a read within the same org_id returns
    field values equal to those written.

    Validates: Requirements 1.2
    """
    _DISPATCH[kind](org, payload)
