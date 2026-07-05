"""Property-based test for analytics aggregation + tenant isolation (Task 5.4).

Feature: agentforge-observability, Property 6: Analytics aggregation partitions the org's
records and isolates tenants. For any set of Usage_Records spread across two or more
organizations and any time range, the Usage_Report computed for organization A has
total_tokens equal to the sum of the total_tokens of exactly A's in-range records and
total_cost equal to the sum of their costs; the sum of tokens across the provider
breakdown and the sum across the model breakdown each equal the report's total_tokens; and
no record whose org_id != A appears in or contributes to A's report.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7, 10.5, 11.3, 11.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.observability.analytics import Analytics_Service
from agentforge.observability.models import Usage_Record
from agentforge.observability.usage.store import InMemory_Usage_Store

# Two fixed orgs so records are guaranteed to overlap providers/models/users across
# tenants; A is the org under report, B is the "other" tenant that must never leak.
_ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
_ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")

_BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)
_RANGE_START = _BASE
_RANGE_END = _BASE + timedelta(days=10)

_providers = st.sampled_from(["groq", "fallback", "openai"])
_models = st.sampled_from(["m1", "m2", "m3"])
_users = st.sampled_from(
    [None, uuid.UUID("11111111-1111-1111-1111-111111111111"), uuid.UUID("22222222-2222-2222-2222-222222222222")]
)


def _record(org_id, provider, model, user_id, prompt, completion, cost, day_offset):
    return Usage_Record(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=user_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cost=cost,
        created_at=_BASE + timedelta(days=day_offset),
    )


_record_specs = st.lists(
    st.tuples(
        st.sampled_from([_ORG_A, _ORG_B]),
        _providers,
        _models,
        _users,
        st.integers(min_value=0, max_value=5000),  # prompt tokens
        st.integers(min_value=0, max_value=5000),  # completion tokens
        st.decimals(min_value=Decimal("0"), max_value=Decimal("100"), places=8,
                    allow_nan=False, allow_infinity=False),
        # day offset: within range [0..10] and some outside (up to 20) to test filtering
        st.integers(min_value=0, max_value=20),
    ),
    max_size=40,
)


# Feature: agentforge-observability, Property 6: Analytics aggregation partitions the
# org's records and isolates tenants.
@hyp_settings(max_examples=150, deadline=None)
@given(specs=_record_specs)
def test_analytics_aggregation_partitions_and_isolates(specs):
    store = InMemory_Usage_Store()
    for org_id, provider, model, user_id, prompt, completion, cost, day in specs:
        store.add(_record(org_id, provider, model, user_id, prompt, completion, cost, day))

    service = Analytics_Service(store)
    report = service.usage_report(_ORG_A, start=_RANGE_START, end=_RANGE_END)

    # The set of records that SHOULD contribute: org A, in range.
    expected = [
        (org_id, provider, model, user_id, prompt, completion, cost, day)
        for (org_id, provider, model, user_id, prompt, completion, cost, day) in specs
        if org_id == _ORG_A and 0 <= day <= 10
    ]
    expected_tokens = sum(p + c for (_, _, _, _, p, c, _, _) in expected)
    expected_cost = sum((cost for (_, _, _, _, _, _, cost, _) in expected), Decimal(0))

    # Totals equal the sum over exactly A's in-range records (Req 3.4).
    assert report.total_tokens == expected_tokens
    assert report.total_cost == expected_cost

    # Each breakdown partitions the same record set: token sums equal the report total
    # (Req 3.2, 3.7).
    assert sum(e.total_tokens for e in report.by_provider) == report.total_tokens
    assert sum(e.total_tokens for e in report.by_model) == report.total_tokens
    assert sum(e.total_tokens for e in report.by_user) == report.total_tokens

    # No org_id != A record contributes (isolation): report_org is A only (Req 10.5).
    assert report.org_id == _ORG_A
