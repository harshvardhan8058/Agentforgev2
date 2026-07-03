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

from typing import Any

from agentforge.llm.base import GenerationResult, LLM_Provider, LLMProviderError

_DEFAULT_MODEL = "llama-3.1-8b-instant"


class Groq_Provider(LLM_Provider):
    """LLM provider that generates completions via the Groq chat API."""

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client  # injectable for tests; lazily created otherwise

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
            self._client = Groq(api_key=self._api_key)
        return self._client

    def generate(self, prompt: str) -> GenerationResult:
        """Generate a completion for ``prompt`` via Groq.

        Raises:
            LLMProviderError: identifying the ``groq`` provider on any failure (Req 11.5).
        """
        client = self._get_client()
        try:
            completion = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
            )
            text = completion.choices[0].message.content or ""
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - any SDK/transport error is a provider failure
            raise LLMProviderError(f"groq provider failed: {exc}") from exc

        return GenerationResult(text=text, provider=self.name)
