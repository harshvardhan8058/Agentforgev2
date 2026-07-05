"""Property-based test for Cost_Model totality with a default rate (Task 2.1).

Feature: agentforge-observability, Property 5: Cost_Model is total with a default rate.
For any provider name, model name, and Token_Count — including provider/model pairs that
have no configured rate — ``Cost_Model.cost_for(...)`` returns a defined, non-negative
Cost without raising, applying the configured default rate when the pair is unlisted.

Validates: Requirements 2.5
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.observability.cost import Default_Cost_Model, Rate
from agentforge.observability.models import Token_Count

# Non-negative per-1K rates as exact Decimals (money never uses float).
_rates = st.builds(
    Rate,
    prompt_per_1k=st.decimals(
        min_value=Decimal("0"), max_value=Decimal("1000"), places=8,
        allow_nan=False, allow_infinity=False,
    ),
    completion_per_1k=st.decimals(
        min_value=Decimal("0"), max_value=Decimal("1000"), places=8,
        allow_nan=False, allow_infinity=False,
    ),
)
_names = st.text(min_size=0, max_size=40)
_tokens = st.builds(
    Token_Count,
    prompt=st.integers(min_value=0, max_value=10_000_000),
    completion=st.integers(min_value=0, max_value=10_000_000),
)
# A rate table keyed by arbitrary (provider, model) pairs.
_rate_tables = st.dictionaries(
    keys=st.tuples(_names, _names), values=_rates, max_size=8
)


# Feature: agentforge-observability, Property 5: Cost_Model is total with a default rate.
@hyp_settings(max_examples=200, deadline=None)
@given(
    rates=_rate_tables,
    default_rate=_rates,
    provider=_names,
    model=_names,
    tokens=_tokens,
)
def test_cost_model_is_total_with_default_rate(rates, default_rate, provider, model, tokens):
    model_ = Default_Cost_Model(rates=rates, default_rate=default_rate)

    # Defined for every input, never raising, and non-negative (rates/tokens >= 0).
    cost = model_.cost_for(provider, model, tokens)
    assert isinstance(cost, Decimal)
    assert cost >= 0

    # When the (provider, model) pair is unlisted, the default rate is applied exactly.
    if (provider, model) not in rates:
        expected = (
            Decimal(tokens.prompt) / Decimal(1000) * default_rate.prompt_per_1k
            + Decimal(tokens.completion) / Decimal(1000) * default_rate.completion_per_1k
        )
        assert cost == expected
