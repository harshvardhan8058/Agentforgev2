"""Property-based test for Usage_Record correctness/determinism/token invariant (Task 4.5).

Feature: agentforge-observability, Property 4: Usage_Record correctness, determinism, and
token invariant. For any generate call routed through the Instrumented_Provider over the
Fallback_Provider with a given acting org_id/user_id, the emitted Usage_Record captures
that org_id, user_id, provider name, and model name, its total_tokens == prompt_tokens +
completion_tokens, its stored cost equals Cost_Model.cost_for(provider, model, tokens), and
repeating the identical call produces an identical Usage_Record in its token fields and
cost (deterministic on the keyless path).

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.7
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.enterprise.tenancy import set_current_org, set_current_user
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.observability.cost import Default_Cost_Model, Rate
from agentforge.observability.usage.instrumented_provider import (
    Instrumented_Provider,
    deterministic_token_count,
)
from agentforge.observability.usage.recorder import Usage_Recorder
from agentforge.observability.usage.sink import Recording_Usage_Sink
from agentforge.observability.usage.store import InMemory_Usage_Store

_MIN = datetime.min.replace(tzinfo=timezone.utc)
_MAX = datetime.max.replace(tzinfo=timezone.utc)


def _build(cost_model):
    store = InMemory_Usage_Store()
    recorder = Usage_Recorder(store, cost_model)
    sink = Recording_Usage_Sink(recorder)
    provider = Instrumented_Provider(Fallback_Provider(), sink)
    return store, provider


# Feature: agentforge-observability, Property 4: Usage_Record correctness, determinism,
# and token invariant.
@hyp_settings(max_examples=100, deadline=None)
@given(
    prompt=st.text(max_size=400),
    org_id=st.uuids(),
    user_id=st.none() | st.uuids(),
)
def test_usage_record_correctness_and_determinism(prompt, org_id, user_id):
    cost_model = Default_Cost_Model(
        default_rate=Rate(Decimal("0.10"), Decimal("0.20"))
    )
    store, provider = _build(cost_model)

    set_current_org(org_id)
    set_current_user(user_id)

    result = provider.generate(prompt)

    records = store.list_for_org(
        org_id, start=_MIN, end=_MAX
    )
    assert len(records) == 1
    record = records[0]

    # Attribution + provider/model capture.
    assert record.org_id == org_id
    assert record.user_id == user_id
    assert record.provider == result.provider == "fallback"
    assert record.model == result.provider  # model == provider name in current contract

    # Token invariant.
    assert record.total_tokens == record.prompt_tokens + record.completion_tokens

    # Cost equals the Cost_Model's computation for the emitted tokens.
    tokens = deterministic_token_count(prompt, result)
    assert record.cost == cost_model.cost_for("fallback", "fallback", tokens)

    # Determinism: an identical call yields identical token fields + cost.
    store2, provider2 = _build(cost_model)
    set_current_org(org_id)
    set_current_user(user_id)
    provider2.generate(prompt)
    record2 = store2.list_for_org(org_id, start=_MIN, end=_MAX)[0]
    assert (record2.prompt_tokens, record2.completion_tokens, record2.total_tokens) == (
        record.prompt_tokens,
        record.completion_tokens,
        record.total_tokens,
    )
    assert record2.cost == record.cost
