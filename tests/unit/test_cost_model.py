"""Unit tests for Default_Cost_Model arithmetic (Task 2.2).

Cover a listed pair using its specific rate, an unlisted pair falling back to the default
rate, the keyless ``0.0`` default producing ``Decimal("0")``, and exact ``Decimal`` (no
float drift) arithmetic (Req 2.2, 2.5).
"""

from __future__ import annotations

from decimal import Decimal

from agentforge.observability.cost import (
    Default_Cost_Model,
    Rate,
    build_default_cost_model,
    parse_rate_table,
)
from agentforge.observability.models import Token_Count


def test_listed_pair_uses_its_specific_rate():
    model = Default_Cost_Model(
        rates={("groq", "llama-3.1-8b"): Rate(Decimal("0.05"), Decimal("0.08"))},
        default_rate=Rate(Decimal("1"), Decimal("1")),
    )
    tokens = Token_Count(prompt=1000, completion=2000)
    # 1000/1000*0.05 + 2000/1000*0.08 = 0.05 + 0.16 = 0.21
    assert model.cost_for("groq", "llama-3.1-8b", tokens) == Decimal("0.21")


def test_unlisted_pair_falls_back_to_default_rate():
    model = Default_Cost_Model(
        rates={("groq", "llama-3.1-8b"): Rate(Decimal("0.05"), Decimal("0.08"))},
        default_rate=Rate(Decimal("0.10"), Decimal("0.20")),
    )
    tokens = Token_Count(prompt=1000, completion=1000)
    # default: 1000/1000*0.10 + 1000/1000*0.20 = 0.30
    assert model.cost_for("openai", "gpt-4", tokens) == Decimal("0.30")


def test_keyless_zero_default_produces_zero():
    model = Default_Cost_Model()  # empty table, Decimal(0) default rate
    tokens = Token_Count(prompt=123, completion=456)
    assert model.cost_for("any", "model", tokens) == Decimal("0")


def test_exact_decimal_no_float_drift():
    model = Default_Cost_Model(
        rates={},
        default_rate=Rate(Decimal("0.0000001"), Decimal("0.0000002")),
    )
    tokens = Token_Count(prompt=1, completion=1)
    # 1/1000*0.0000001 + 1/1000*0.0000002 == 0.0000000003 exactly
    result = model.cost_for("p", "m", tokens)
    assert result == Decimal("1") / Decimal("1000") * Decimal("0.0000001") + Decimal(
        "1"
    ) / Decimal("1000") * Decimal("0.0000002")
    assert isinstance(result, Decimal)


def test_parse_rate_table_reads_provider_model_keys():
    table = parse_rate_table(
        '{"groq:llama-3.1-8b": {"prompt": "0.05", "completion": "0.08"}}'
    )
    assert table[("groq", "llama-3.1-8b")] == Rate(Decimal("0.05"), Decimal("0.08"))


def test_parse_rate_table_empty_or_none():
    assert parse_rate_table(None) == {}
    assert parse_rate_table("") == {}


def test_build_default_cost_model_from_settings(monkeypatch):
    from tests.conftest import apply_base_env

    apply_base_env(monkeypatch)
    monkeypatch.setenv("COST_DEFAULT_PROMPT_PER_1K", "0.10")
    monkeypatch.setenv("COST_DEFAULT_COMPLETION_PER_1K", "0.20")
    monkeypatch.setenv(
        "COST_RATE_TABLE_JSON",
        '{"groq:llama-3.1-8b": {"prompt": "0.05", "completion": "0.08"}}',
    )

    from agentforge.config.settings import load_settings

    model = build_default_cost_model(load_settings())

    listed = model.cost_for("groq", "llama-3.1-8b", Token_Count(1000, 1000))
    assert listed == Decimal("0.05") + Decimal("0.08")
    unlisted = model.cost_for("openai", "gpt-4", Token_Count(1000, 1000))
    assert unlisted == Decimal("0.10") + Decimal("0.20")
