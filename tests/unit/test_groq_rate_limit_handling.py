"""A rate-limited Groq call must be waited out, not surfaced as a raw SDK blob.

Regression test for an observed production failure. Midway through a multi-agent run
the Writer died and the run terminated with this error event::

    groq provider failed: Error code: 429 - {'error': {'message': 'Rate limit reached
    for model `llama-3.1-8b-instant` in organization `org_...` service tier
    `on_demand` on tokens per minute (TPM): Limit 6000, Used 4353, Requested 1889.
    Please try again in 2.42s. ...

Two defects in one event:

1. The limit clears in ~2.4s, and the server says so, but the call was abandoned. A
   free tier meters *tokens per minute*, so a Planner → Researcher → Writer → Critic
   run exhausts it on its own; giving up means the run can essentially never finish.
2. The upstream JSON blob — organization id, token counters, billing upsell — was
   shown verbatim as the run's error. That is neither actionable nor ours to display.

The fix waits for the cool-off the server asks for, within a bounded total budget, and
replaces the blob with a summary. The budget matters: an agent run issues many
completions in sequence, so an unbounded wait would just relocate the hang.
"""

from __future__ import annotations

import pytest

from agentforge.llm.base import LLMProviderError
from agentforge.llm.groq_provider import Groq_Provider

# The message text as Groq actually returns it.
OBSERVED_429_MESSAGE = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
    "`llama-3.1-8b-instant` in organization `org_01kxdt9qdxf0war6cbk06m7vad` service "
    "tier `on_demand` on tokens per minute (TPM): Limit 6000, Used 4353, Requested "
    "1889. Please try again in 2.42s. Need more tokens? Upgrade to Dev Tier today at "
    "https://console.groq.com/settings/billing', 'type': 'tokens', 'code': "
    "'rate_limit_exceeded'}}"
)


class _RateLimitError(Exception):
    """Stands in for the SDK's rate-limit exception (an optional dependency)."""

    def __init__(self, message: str = OBSERVED_429_MESSAGE, status_code: int = 429):
        super().__init__(message)
        self.status_code = status_code


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Completion:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _Completions:
    """Fails with the given exceptions in order, then succeeds."""

    def __init__(self, failures: list[Exception], content: str = "ok") -> None:
        self._failures = list(failures)
        self._content = content
        self.calls = 0

    def create(self, **_kwargs: object) -> _Completion:
        self.calls += 1
        if self._failures:
            raise self._failures.pop(0)
        return _Completion(self._content)


class _Client:
    def __init__(self, completions: _Completions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


def _provider(
    failures: list[Exception],
    *,
    budget: float = 8.0,
) -> tuple[Groq_Provider, _Completions, list[float]]:
    completions = _Completions(failures)
    slept: list[float] = []
    provider = Groq_Provider(
        api_key="test-key",
        client=_Client(completions),
        rate_limit_max_wait_seconds=budget,
        sleep=slept.append,
    )
    return provider, completions, slept


class TestObservedRateLimit:
    """The exact observed 429 must be recovered from, not reported."""

    def test_the_call_is_retried_and_succeeds(self) -> None:
        provider, completions, _ = _provider([_RateLimitError()])

        result = provider.generate("draft the answer")

        assert result.text == "ok"
        assert result.provider == "groq"
        assert completions.calls == 2

    def test_it_waits_the_cool_off_the_server_asked_for(self) -> None:
        provider, _, slept = _provider([_RateLimitError()])

        provider.generate("draft the answer")

        # "try again in 2.42s" plus a small margin, so the retry clears the boundary.
        assert len(slept) == 1
        assert 2.42 < slept[0] <= 2.42 + 0.5

    def test_repeated_limits_are_retried_until_the_budget_is_spent(self) -> None:
        provider, completions, slept = _provider(
            [_RateLimitError(), _RateLimitError()]
        )

        assert provider.generate("draft").text == "ok"
        assert completions.calls == 3
        assert sum(slept) <= 8.0


class TestBudgetExhausted:
    """When waiting cannot help, the failure must be clean and actionable."""

    @staticmethod
    def _exhaust() -> LLMProviderError:
        provider, _, _ = _provider([_RateLimitError()] * 10, budget=3.0)
        with pytest.raises(LLMProviderError) as excinfo:
            provider.generate("draft")
        return excinfo.value

    def test_the_wait_stays_within_the_budget(self) -> None:
        provider, _, slept = _provider([_RateLimitError()] * 10, budget=3.0)

        with pytest.raises(LLMProviderError):
            provider.generate("draft")

        assert sum(slept) <= 3.0

    def test_the_message_identifies_the_provider(self) -> None:
        # Req 11.5: the message identifies the provider that failed.
        assert str(self._exhaust()).startswith("groq provider failed:")

    def test_the_message_explains_the_cause_and_the_remedy(self) -> None:
        message = str(self._exhaust())

        assert "rate limit" in message.lower()
        assert "retry" in message.lower()

    def test_the_raw_upstream_blob_is_not_surfaced(self) -> None:
        message = str(self._exhaust())

        # No organization id, token counters, or billing upsell.
        assert "org_01kxdt9qdxf0war6cbk06m7vad" not in message
        assert "Used 4353" not in message
        assert "console.groq.com" not in message
        assert "'code':" not in message

    def test_a_zero_budget_does_not_sleep_at_all(self) -> None:
        provider, completions, slept = _provider([_RateLimitError()], budget=0.0)

        with pytest.raises(LLMProviderError):
            provider.generate("draft")

        assert slept == []
        assert completions.calls == 1


class TestOtherFailuresAreUnaffected:
    """Only rate limits are retried; everything else still fails fast."""

    def test_a_generic_error_is_not_retried(self) -> None:
        provider, completions, slept = _provider([RuntimeError("connection reset")])

        with pytest.raises(LLMProviderError) as excinfo:
            provider.generate("draft")

        assert completions.calls == 1
        assert slept == []
        assert "connection reset" in str(excinfo.value)

    def test_a_successful_call_never_sleeps(self) -> None:
        provider, completions, slept = _provider([])

        assert provider.generate("draft").text == "ok"
        assert completions.calls == 1
        assert slept == []


class TestRetryHintParsing:
    """The cool-off is read from the server rather than guessed."""

    @pytest.mark.parametrize(
        ("message", "low", "high"),
        [
            pytest.param("try again in 2.42s", 2.42, 3.0, id="sub-second-precision"),
            pytest.param("try again in 1m2.404s", 5.0, 5.0, id="minutes-clamped"),
            pytest.param("Rate limit reached", 1.0, 1.5, id="no-hint-default"),
        ],
    )
    def test_the_sleep_follows_the_hint(
        self, message: str, low: float, high: float
    ) -> None:
        provider, _, slept = _provider(
            [_RateLimitError(message)], budget=60.0
        )

        provider.generate("draft")

        assert len(slept) == 1
        assert low <= slept[0] <= high

    def test_a_retry_after_header_takes_precedence(self) -> None:
        error = _RateLimitError("Rate limit reached")
        error.response = type("R", (), {"status_code": 429, "headers": {"retry-after": "3"}})()
        provider, _, slept = _provider([error], budget=60.0)

        provider.generate("draft")

        assert len(slept) == 1
        assert 3.0 <= slept[0] <= 3.5

    def test_a_single_sleep_is_capped(self) -> None:
        # A server asking for a full minute should fail fast, not block the run.
        provider, _, slept = _provider(
            [_RateLimitError("try again in 55s")], budget=60.0
        )

        provider.generate("draft")

        assert slept == [5.0]
