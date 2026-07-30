"""Groq_Provider: hosted LLM provider backed by the Groq API.

Active **only** when a ``groq_api_key`` is configured (Req 11.2); otherwise the
composition root selects the ``Fallback_Provider`` instead. On any API failure this
provider raises ``LLMProviderError`` whose message identifies the provider so callers
can surface a ``502 llm_provider_error`` (Req 11.5).

The ``groq`` SDK is imported lazily inside ``_get_client`` so the default keyless path
(and the entire fast test suite) never requires the package to be installed. Tests
inject a fake client via the ``client`` constructor argument and never touch the
network.
"""

from __future__ import annotations

import re
import time
from typing import Any

from agentforge.llm.base import GenerationResult, LLM_Provider, LLMProviderError

_DEFAULT_MODEL = "llama-3.1-8b-instant"

# Per-completion budget. Every call is bounded so a stalled upstream request cannot
# block the agent loop indefinitely; retries are bounded for the same reason (an
# unbounded retry policy turns one slow call into an unbounded one).
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 2

# Total time this provider may spend *waiting out* rate limits within one call. Free
# Groq tiers meter tokens per minute, and a multi-role run trips that limit routinely;
# the limit clears in seconds, so a short bounded wait turns a dead run into a slow
# one. Bounded because an agent run issues many completions in sequence.
_DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS = 8.0

# A single retry never sleeps longer than this, even if the server asks for more —
# a request that would wait a full minute should fail fast with a clear message.
_MAX_SINGLE_SLEEP_SECONDS = 5.0

# Groq reports the cool-off inside the error message, e.g. "Please try again in 2.42s"
# or "try again in 1m2.404s". Both forms are read so the wait matches the server's own
# instruction instead of a guess.
_RETRY_HINT = re.compile(
    r"try again in\s+(?:(?P<minutes>\d+(?:\.\d+)?)m)?(?P<seconds>\d+(?:\.\d+)?)s",
    re.IGNORECASE,
)


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Return True when ``exc`` represents an upstream rate-limit (HTTP 429).

    Duck-typed on purpose: the ``groq`` SDK is an optional dependency, so its exception
    classes cannot be imported here. Status code is checked first and the message is a
    fallback for transports that surface the code only in text.
    """
    if getattr(exc, "status_code", None) == 429:
        return True
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True
    text = str(exc)
    return "rate_limit_exceeded" in text or "429" in text and "rate limit" in text.lower()


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Extract the cool-off the server asked for, preferring the Retry-After header."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        for key in ("retry-after", "Retry-After", "x-ratelimit-reset-tokens"):
            try:
                raw = headers.get(key)
            except AttributeError:  # pragma: no cover - non-mapping headers
                raw = None
            if raw:
                parsed = _parse_duration(str(raw))
                if parsed is not None:
                    return parsed
    match = _RETRY_HINT.search(str(exc))
    if match is None:
        return None
    minutes = float(match.group("minutes") or 0.0)
    return minutes * 60.0 + float(match.group("seconds"))


def _parse_duration(raw: str) -> float | None:
    """Parse a Retry-After style value: bare seconds, or Groq's ``1m2.4s`` form."""
    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        pass
    match = _RETRY_HINT.search(f"try again in {raw}")
    if match is None:
        return None
    minutes = float(match.group("minutes") or 0.0)
    return minutes * 60.0 + float(match.group("seconds"))


class Groq_Provider(LLM_Provider):
    """LLM provider that generates completions via the Groq chat API."""

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        client: Any | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        rate_limit_max_wait_seconds: float = _DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS,
        sleep: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client  # injectable for tests; lazily created otherwise
        self._rate_limit_max_wait_seconds = max(0.0, rate_limit_max_wait_seconds)
        # Injectable so tests can assert the wait policy without real delays.
        self._sleep = sleep or time.sleep
        # Bounded so a single stalled HTTP call cannot hang the request that owns it.
        # An agent run issues many completions in sequence, and a multi-agent run
        # multiplies that by its roles and rounds, so one unbounded call is enough to
        # make the whole synchronous request appear to hang forever.
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    @property
    def name(self) -> str:
        return "groq"

    def _get_client(self) -> Any:
        """Return the Groq client, constructing it lazily on first use."""
        if self._client is None:
            try:
                from groq import Groq  # local import by design (keyless path is free)
            except ImportError as exc:  # pragma: no cover - exercised only without dep
                raise LLMProviderError(
                    "groq provider failed: the 'groq' package is not installed"
                ) from exc
            self._client = Groq(
                api_key=self._api_key,
                timeout=self._timeout_seconds,
                max_retries=self._max_retries,
            )
        return self._client

    def generate(self, prompt: str) -> GenerationResult:
        """Generate a completion for ``prompt`` via Groq.

        A rate-limited call (HTTP 429) is retried after the cool-off the server asks
        for, within a bounded total wait. Any other failure fails immediately.

        Raises:
            LLMProviderError: identifying the ``groq`` provider on any failure (Req 11.5).
        """
        client = self._get_client()
        waited = 0.0
        while True:
            try:
                completion = client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = completion.choices[0].message.content or ""
                return GenerationResult(text=text, provider=self.name)
            except LLMProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 - any SDK error is a provider failure
                if not _is_rate_limit_error(exc):
                    raise LLMProviderError(f"groq provider failed: {exc}") from exc
                delay = _retry_after_seconds(exc) or 1.0
                # Add a small margin: sleeping the exact reported cool-off tends to
                # land right on the boundary and trip the limit a second time.
                delay = min(delay + 0.25, _MAX_SINGLE_SLEEP_SECONDS)
                if waited + delay > self._rate_limit_max_wait_seconds:
                    raise LLMProviderError(_rate_limit_message(exc)) from exc
                self._sleep(delay)
                waited += delay


def _rate_limit_message(exc: BaseException) -> str:
    """Build an actionable message for an exhausted rate-limit budget (Req 11.5).

    The raw SDK error is a JSON blob naming the organization and token counters; it
    reaches operators through the run's error event, so it is replaced with a summary
    that says what happened and what to do about it.
    """
    hint = _retry_after_seconds(exc)
    retry_phrase = f" It asked to retry in {hint:.1f}s." if hint else ""
    return (
        "groq provider failed: the Groq API rate limit was reached and did not clear "
        f"within the allowed wait.{retry_phrase} Retry in a moment, shorten the task, "
        "or raise the LLM_RATE_LIMIT_MAX_WAIT_SECONDS budget. Free Groq tiers meter "
        "tokens per minute, which a multi-role run can exhaust on its own."
    )
