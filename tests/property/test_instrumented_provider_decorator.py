"""Property-based test for the transparent, safe Instrumented_Provider (Task 4.4).

Feature: agentforge-observability, Property 3: Instrumented_Provider is a transparent,
safe decorator. For any wrapped LLM_Provider and any prompt, generate(prompt) returns a
GenerationResult equal to what the wrapped provider returns and exposes the wrapped
provider's name, delegates to the wrapped provider exactly once, and forwards exactly one
usage emission to the Usage_Sink; moreover, for any Usage_Sink that raises, generate still
returns exactly the wrapped provider's result unchanged.

Validates: Requirements 2.1, 7.1, 7.2, 7.7
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.llm.base import GenerationResult, LLM_Provider
from agentforge.observability.usage.base import Usage_Sink
from agentforge.observability.usage.instrumented_provider import Instrumented_Provider


class _FakeProvider(LLM_Provider):
    """Wrapped provider returning a fixed result and counting its generate calls."""

    def __init__(self, name: str, text: str) -> None:
        self._name = name
        self._text = text
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def generate(self, prompt: str) -> GenerationResult:
        self.calls += 1
        return GenerationResult(text=self._text, provider=self._name)


class _CountingSink(Usage_Sink):
    def __init__(self) -> None:
        self.calls = 0

    def record(self, *, provider, model, tokens, org_id, user_id) -> None:
        self.calls += 1


class _RaisingSink(Usage_Sink):
    def record(self, *, provider, model, tokens, org_id, user_id) -> None:
        raise RuntimeError("sink is down")


# Feature: agentforge-observability, Property 3: Instrumented_Provider is a transparent,
# safe decorator.
@hyp_settings(max_examples=100, deadline=None)
@given(
    name=st.text(min_size=1, max_size=16),
    text=st.text(max_size=200),
    prompt=st.text(max_size=200),
)
def test_instrumented_provider_transparent_and_safe(name, text, prompt):
    wrapped = _FakeProvider(name, text)
    sink = _CountingSink()
    provider = Instrumented_Provider(wrapped, sink)

    # Transparent identity + equal result.
    assert provider.name == name
    result = provider.generate(prompt)
    expected = GenerationResult(text=text, provider=name)
    assert result == expected

    # Exactly-once delegation and exactly-one emission.
    assert wrapped.calls == 1
    assert sink.calls == 1

    # Safe: a raising sink never changes the wrapped provider's returned result.
    raising_wrapped = _FakeProvider(name, text)
    safe_provider = Instrumented_Provider(raising_wrapped, _RaisingSink())
    safe_result = safe_provider.generate(prompt)
    assert safe_result == expected
    assert raising_wrapped.calls == 1
