"""Every hosted-LLM call must be bounded, and the work budgets must be finite.

Regression tests for an observed hang: with a real provider configured, starting a
multi-agent run left the UI spinning indefinitely with no output.

The mechanism was compounding, not a single bug:

* A single agent run issues up to ``iteration_limit`` sequential completions.
* A multi-agent run nests that across its roles, rounds and revision cycles, so the
  code-level safety ceilings (10 / 6 / 3) permit well over a hundred sequential
  completions for ONE synchronous HTTP request.
* The Groq client was constructed with no ``timeout`` and no ``max_retries``, so a
  single stalled upstream call had no deadline at all.

These tests pin the two invariants that keep a run finite: every provider call carries
an explicit timeout and a bounded retry count, and the work budgets resolve to finite
numbers. No network call is made and no API key is required.
"""

from __future__ import annotations

import sys
import types

import pytest

from agentforge.config.settings import Settings
from agentforge.llm.base import LLMProviderError
from agentforge.llm.groq_provider import (
    _DEFAULT_MAX_RETRIES,
    _DEFAULT_TIMEOUT_SECONDS,
    Groq_Provider,
)


class _RecordingGroq:
    """Stands in for ``groq.Groq``, capturing the constructor kwargs."""

    instances: list[dict] = []

    def __init__(self, **kwargs) -> None:
        type(self).instances.append(kwargs)
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **_: None)
        )


@pytest.fixture
def fake_groq_module(monkeypatch):
    """Install a fake ``groq`` module so no real SDK or key is needed."""
    _RecordingGroq.instances = []
    module = types.ModuleType("groq")
    module.Groq = _RecordingGroq  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "groq", module)
    return _RecordingGroq


# --- every call is bounded ---------------------------------------------------------


def test_client_is_constructed_with_a_timeout_and_bounded_retries(fake_groq_module):
    provider = Groq_Provider(api_key="k", timeout_seconds=12.5, max_retries=1)

    provider._get_client()

    assert len(fake_groq_module.instances) == 1
    kwargs = fake_groq_module.instances[0]
    # Without these two, one stalled upstream call has no deadline whatsoever.
    assert kwargs["timeout"] == 12.5
    assert kwargs["max_retries"] == 1
    assert kwargs["api_key"] == "k"


def test_defaults_are_finite_and_positive(fake_groq_module):
    Groq_Provider(api_key="k")._get_client()

    kwargs = fake_groq_module.instances[0]
    assert 0 < kwargs["timeout"] < float("inf")
    assert isinstance(kwargs["max_retries"], int)
    # Retries must be bounded: an unbounded policy turns one slow call into an
    # unbounded one, which is the failure mode being guarded against.
    assert 0 <= kwargs["max_retries"] <= 5
    assert kwargs["timeout"] == _DEFAULT_TIMEOUT_SECONDS
    assert kwargs["max_retries"] == _DEFAULT_MAX_RETRIES


def test_client_is_built_once_and_reused(fake_groq_module):
    provider = Groq_Provider(api_key="k")

    provider._get_client()
    provider._get_client()

    # Re-creating a client per completion would multiply connection setup across the
    # many sequential calls an agent run makes.
    assert len(fake_groq_module.instances) == 1


def test_injected_client_bypasses_construction_entirely(fake_groq_module):
    sentinel = object()
    provider = Groq_Provider(api_key="k", client=sentinel)

    assert provider._get_client() is sentinel
    assert fake_groq_module.instances == []


# --- the settings that feed those bounds ------------------------------------------


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
    }
    base.update(overrides)
    return Settings(**base)


def test_settings_expose_finite_llm_budgets_by_default():
    settings = _settings()

    assert settings.llm_timeout_seconds > 0
    assert settings.llm_max_retries >= 0
    assert settings.llm_timeout_seconds < float("inf")


def test_llm_budgets_are_operator_overridable():
    settings = _settings(llm_timeout_seconds=5, llm_max_retries=0)

    assert settings.llm_timeout_seconds == 5
    assert settings.llm_max_retries == 0


# --- work budgets stay finite ------------------------------------------------------


def test_unset_work_budgets_resolve_to_finite_bounded_defaults():
    """`None` must mean "use the bounded default", never "unbounded"."""
    from agentforge.agent.state import resolve_iteration_limit
    from agentforge.multiagent.state import resolve_max_revisions, resolve_max_rounds

    settings = _settings()

    # Declared optional so a keyless boot needs no configuration...
    assert settings.iteration_limit is None
    assert settings.max_rounds is None
    assert settings.max_revisions is None

    # ...but each resolves to a finite ceiling, which is what makes a run terminate.
    iterations, _ = resolve_iteration_limit(settings.iteration_limit)
    rounds, _ = resolve_max_rounds(settings.max_rounds)
    revisions, _ = resolve_max_revisions(settings.max_revisions)

    for value, upper in ((iterations, 100), (rounds, 50), (revisions, 20)):
        assert isinstance(value, int)
        assert 1 <= value <= upper


def test_worst_case_completion_count_is_finite_and_knowable():
    """The nested budgets bound total LLM calls — the hang was cost, not an infinite loop.

    This is what makes the local compose values (4 / 2 / 1) a deliberate choice rather
    than an arbitrary one: the ceilings multiply, so the defaults permit an interactively
    unusable number of sequential calls even though every run is finite.
    """
    from agentforge.agent.state import resolve_iteration_limit
    from agentforge.multiagent.state import resolve_max_revisions, resolve_max_rounds

    iterations, _ = resolve_iteration_limit(None)
    rounds, _ = resolve_max_rounds(None)
    revisions, _ = resolve_max_revisions(None)

    roles = 4  # planner -> researcher -> writer -> critic
    worst_case = roles * (iterations + 1) * rounds * (revisions + 1)

    assert worst_case < float("inf")
    # Finite, but far too many sequential hosted calls for one synchronous request —
    # which is exactly why compose pins smaller interactive budgets.
    assert worst_case > 100


def test_configured_work_budgets_are_honoured():
    settings = _settings(iteration_limit=3, max_rounds=2, max_revisions=1)

    assert settings.iteration_limit == 3
    assert settings.max_rounds == 2
    assert settings.max_revisions == 1


# --- failure handling is unchanged -------------------------------------------------


def test_a_timed_out_call_still_surfaces_as_an_identified_provider_error():
    class _Timeout(Exception):
        pass

    class _Client:
        chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=lambda **_: (_ for _ in ()).throw(_Timeout("request timed out"))
            )
        )

    provider = Groq_Provider(api_key="k", client=_Client())

    with pytest.raises(LLMProviderError) as exc:
        provider.generate("prompt")

    # A deadline being hit must be reported as a provider failure, not swallowed.
    assert "groq" in str(exc.value).lower()
    assert "timed out" in str(exc.value).lower()
