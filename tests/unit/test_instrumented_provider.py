"""Unit tests for Instrumented_Provider emission-failure + context attribution (Task 4.6).

Cover a sink that raises (result still returned), a missing tenancy context (NIL org /
None user), the exactly-once delegation/emission counts, and the deterministic token
counter (Req 2.3, 2.4, 2.7, 7.7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agentforge.enterprise.tenancy import (
    NIL_ORG_ID,
    set_current_org,
    set_current_user,
)
from agentforge.llm.base import GenerationResult, LLM_Provider
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.observability.cost import Default_Cost_Model, Rate
from agentforge.observability.models import Token_Count
from agentforge.observability.usage.base import Usage_Sink
from agentforge.observability.usage.instrumented_provider import (
    Instrumented_Provider,
    deterministic_token_count,
)
from agentforge.observability.usage.recorder import Usage_Recorder
from agentforge.observability.usage.sink import NoOp_Usage_Sink, Recording_Usage_Sink
from agentforge.observability.usage.store import InMemory_Usage_Store

_MIN = datetime.min.replace(tzinfo=timezone.utc)
_MAX = datetime.max.replace(tzinfo=timezone.utc)


class _StaticProvider(LLM_Provider):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "static"

    def generate(self, prompt: str) -> GenerationResult:
        self.calls += 1
        return GenerationResult(text="answer", provider="static")


class _RaisingSink(Usage_Sink):
    def __init__(self) -> None:
        self.calls = 0

    def record(self, *, provider, model, tokens, org_id, user_id) -> None:
        self.calls += 1
        raise RuntimeError("sink failure")


def test_sink_failure_still_returns_wrapped_result():
    wrapped = _StaticProvider()
    sink = _RaisingSink()
    provider = Instrumented_Provider(wrapped, sink)

    result = provider.generate("hi there")

    assert result == GenerationResult(text="answer", provider="static")
    assert wrapped.calls == 1  # delegated once
    assert sink.calls == 1  # emission attempted exactly once (then swallowed)


def test_missing_tenancy_context_uses_nil_org_and_none_user():
    # Reset context to defaults.
    set_current_org(NIL_ORG_ID)
    set_current_user(None)

    store = InMemory_Usage_Store()
    recorder = Usage_Recorder(store, Default_Cost_Model())
    provider = Instrumented_Provider(Fallback_Provider(), Recording_Usage_Sink(recorder))

    provider.generate("some prompt text")

    records = store.list_for_org(NIL_ORG_ID, start=_MIN, end=_MAX)
    assert len(records) == 1
    assert records[0].org_id == NIL_ORG_ID
    assert records[0].user_id is None


def test_context_attribution_records_acting_org_and_user():
    org_id = uuid4()
    user_id = uuid4()
    set_current_org(org_id)
    set_current_user(user_id)

    store = InMemory_Usage_Store()
    recorder = Usage_Recorder(store, Default_Cost_Model(default_rate=Rate(Decimal("1"), Decimal("1"))))
    provider = Instrumented_Provider(Fallback_Provider(), Recording_Usage_Sink(recorder))

    provider.generate("attribute me")

    records = store.list_for_org(org_id, start=_MIN, end=_MAX)
    assert len(records) == 1
    assert records[0].org_id == org_id
    assert records[0].user_id == user_id
    # Other orgs see nothing.
    assert store.list_for_org(uuid4(), start=_MIN, end=_MAX) == []


def test_noop_sink_emits_nothing_but_returns_result():
    provider = Instrumented_Provider(Fallback_Provider(), NoOp_Usage_Sink())
    result = provider.generate("prompt")
    assert result.provider == "fallback"


def test_deterministic_token_count_whitespace_and_invariant():
    result = GenerationResult(text="one two three", provider="fallback")
    tokens = deterministic_token_count("hello  world", result)
    assert tokens == Token_Count(prompt=2, completion=3)
    assert tokens.total == tokens.prompt + tokens.completion

    empty = deterministic_token_count("   ", GenerationResult(text="", provider="fallback"))
    assert empty == Token_Count(prompt=0, completion=0)



class _Capturing_Sink(Usage_Sink):
    """Captures the keyword arguments of every emitted usage record."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, *, provider, model, tokens, org_id, user_id) -> None:
        self.records.append(
            {
                "provider": provider,
                "model": model,
                "tokens": tokens,
                "org_id": org_id,
                "user_id": user_id,
            }
        )


class _Model_Reporting_Provider(LLM_Provider):
    """A provider that reports the concrete model that served the call."""

    def __init__(self, model: str | None) -> None:
        self._model = model

    @property
    def name(self) -> str:
        return "groq"

    def generate(self, prompt: str) -> GenerationResult:
        return GenerationResult(text="ok", provider=self.name, model=self._model)


def test_usage_records_the_model_the_provider_reports():
    """The usage record carries the real model, not the provider name.

    ``GenerationResult`` previously had no model field, so this decorator recorded
    the provider name as the model. Every usage row therefore had model ==
    provider, which made the analytics "by model" breakdown an exact duplicate of
    "by provider" — three identical charts for one workspace.
    """
    sink = _Capturing_Sink()
    provider = Instrumented_Provider(
        _Model_Reporting_Provider("llama-3.1-8b-instant"), sink
    )

    provider.generate("hello")

    assert sink.records[0]["provider"] == "groq"
    assert sink.records[0]["model"] == "llama-3.1-8b-instant"


def test_usage_falls_back_to_the_provider_name_without_a_model():
    """A provider that cannot name a model still yields a populated model field.

    The keyless ``Fallback_Provider`` has no model concept, and the usage record
    requires an identifier, so the provider name remains the fallback.
    """
    sink = _Capturing_Sink()
    provider = Instrumented_Provider(_Model_Reporting_Provider(None), sink)

    provider.generate("hello")

    assert sink.records[0]["model"] == "groq"


def test_generation_result_model_defaults_to_none():
    """The new field is additive: positional construction is unchanged."""
    result = GenerationResult("text", "provider")

    assert result.model is None
