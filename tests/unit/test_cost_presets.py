"""Unit tests for the named cost-rate presets and their resolution order.

The presets exist so a deployment that configures a real LLM provider reports real costs
without hand-authoring a JSON rate table. These tests pin the three things that make that
safe:

1. **Keyless is still free.** With no preset selected, every pair costs ``Decimal("0")``.
2. **Precedence.** ``cost_rate_table_json`` overrides a preset entry pair by pair, and the
   default rate still covers pairs neither lists.
3. **A typo fails loudly.** An unknown preset name raises rather than silently unpricing
   the deployment — through both :func:`resolve_rate_table` and ``load_settings``.

Rate *values* are asserted through arithmetic on a known token count rather than by
restating the table, so the assertion checks the model's behaviour rather than mirroring
its data.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agentforge.config.settings import ConfigError, Settings, load_settings
from agentforge.observability.cost import Rate, build_default_cost_model
from agentforge.observability.cost_presets import (
    RATE_PRESETS,
    preset_names,
    preset_rates,
    resolve_rate_table,
)
from agentforge.observability.models import Token_Count

PRESET = "groq-public-2026-07"
_ONE_MILLION = Token_Count(prompt=1_000_000, completion=1_000_000)


def _settings(**overrides) -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        **overrides,
    )


def test_shipped_preset_is_registered_and_named():
    assert PRESET in RATE_PRESETS
    assert preset_names() == sorted(RATE_PRESETS)


def test_every_shipped_preset_rate_is_non_negative_and_priced():
    """A preset that priced something at zero would be indistinguishable from none."""
    for name, table in RATE_PRESETS.items():
        assert table, f"preset {name} is empty"
        for (provider, model), rate in table.items():
            assert provider and model
            assert rate.prompt_per_1k > 0, (name, provider, model)
            assert rate.completion_per_1k > 0, (name, provider, model)


def test_preset_rates_returns_a_copy():
    """Mutating a returned table must not corrupt the shipped catalogue."""
    table = preset_rates(PRESET)
    table[("groq", "injected")] = Rate(Decimal("9"), Decimal("9"))
    assert ("groq", "injected") not in RATE_PRESETS[PRESET]


def test_keyless_default_prices_every_pair_at_zero():
    model = build_default_cost_model(_settings())
    assert model.cost_for("groq", "llama-3.1-8b-instant", _ONE_MILLION) == Decimal(0)
    assert model.cost_for("fallback", "deterministic", _ONE_MILLION) == Decimal(0)


def test_preset_prices_the_providers_default_model():
    """The Groq_Provider's default model must be priced, or the preset misses the case
    that matters: the model a deployment gets simply by setting ``GROQ_API_KEY``."""
    from agentforge.llm.groq_provider import _DEFAULT_MODEL

    assert ("groq", _DEFAULT_MODEL) in RATE_PRESETS[PRESET]

    model = build_default_cost_model(_settings(cost_rate_preset=PRESET))
    cost = model.cost_for("groq", _DEFAULT_MODEL, _ONE_MILLION)
    # Published on-demand list price: $0.05 per 1M prompt + $0.08 per 1M completion.
    assert cost == Decimal("0.13")


def test_preset_prices_the_larger_model_higher():
    model = build_default_cost_model(_settings(cost_rate_preset=PRESET))
    small = model.cost_for("groq", "llama-3.1-8b-instant", _ONE_MILLION)
    large = model.cost_for("groq", "llama-3.3-70b-versatile", _ONE_MILLION)
    assert large > small > 0


def test_unlisted_pair_still_falls_back_to_the_default_rate():
    model = build_default_cost_model(
        _settings(cost_rate_preset=PRESET, cost_default_prompt_per_1k="0.01")
    )
    # 1M prompt tokens at 0.01 per 1K = 10.
    assert model.cost_for("other", "model-x", _ONE_MILLION) == Decimal(10)


def test_explicit_table_overrides_the_preset_pair_by_pair():
    table = resolve_rate_table(
        PRESET,
        '{"groq:llama-3.1-8b-instant": {"prompt": "1", "completion": "2"}}',
    )
    assert table[("groq", "llama-3.1-8b-instant")] == Rate(Decimal("1"), Decimal("2"))
    # The pair that was NOT overridden keeps the preset's rate.
    assert table[("groq", "llama-3.3-70b-versatile")] == RATE_PRESETS[PRESET][
        ("groq", "llama-3.3-70b-versatile")
    ]


def test_resolve_rate_table_without_preset_is_the_explicit_table_only():
    assert resolve_rate_table(None, None) == {}
    assert resolve_rate_table(
        None, '{"groq:m": {"prompt": "1", "completion": "2"}}'
    ) == {("groq", "m"): Rate(Decimal("1"), Decimal("2"))}


def test_unknown_preset_raises_with_the_known_names():
    with pytest.raises(ValueError) as excinfo:
        resolve_rate_table("does-not-exist", None)
    assert "does-not-exist" in str(excinfo.value)
    assert PRESET in str(excinfo.value)


def test_unknown_preset_aborts_startup_naming_the_setting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/a")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("COST_RATE_PRESET", "not-a-preset")

    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "cost_rate_preset" in str(excinfo.value)


def test_known_preset_loads_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/a")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("COST_RATE_PRESET", PRESET)

    assert load_settings().cost_rate_preset == PRESET



# --- empty values mean "unset", not "misspelled" ----------------------------------
#
# Environment configuration cannot distinguish absent from present-but-empty: a blank
# line in an `.env` template, Compose `${VAR}` interpolation with the variable unset,
# `--env-file` and CI all deliver `""`. Validating that as an unknown preset name made
# shipping the setting in a template with no value ship an unbootable deployment.


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_preset_is_treated_as_unset(monkeypatch, blank: str):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/a")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("COST_RATE_PRESET", blank)
    monkeypatch.setenv("COST_RATE_TABLE_JSON", blank)

    settings = load_settings()

    assert settings.cost_rate_preset is None
    assert settings.cost_rate_table_json is None
    # And the model that is built from it prices everything at zero, as when unset.
    model = build_default_cost_model(settings)
    assert model.cost_for("groq", "llama-3.1-8b-instant", _ONE_MILLION) == Decimal(0)


def test_blank_groq_model_is_treated_as_unset(monkeypatch):
    """The same rule applies to the model name, which is passed through to the provider."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/a")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("GROQ_MODEL", "  ")

    assert load_settings().groq_model is None


def test_configured_groq_model_reaches_the_provider():
    """Every preset-priced model must be selectable, or its rate is documentation."""
    from agentforge.config.container import _build_groq

    priced_models = [model for (provider, model) in RATE_PRESETS[PRESET] if provider == "groq"]
    assert len(priced_models) > 1  # otherwise this test proves nothing

    for model_name in priced_models:
        provider = _build_groq(
            _settings(groq_api_key="test-key-not-a-real-credential", groq_model=model_name)
        )
        assert provider._model == model_name


def test_unset_groq_model_keeps_the_providers_own_default():
    from agentforge.config.container import _build_groq
    from agentforge.llm.groq_provider import _DEFAULT_MODEL

    provider = _build_groq(_settings(groq_api_key="test-key-not-a-real-credential"))
    assert provider._model == _DEFAULT_MODEL
