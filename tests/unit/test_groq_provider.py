"""Unit tests for Groq_Provider failure handling (Req 11.5).

These use a MOCKED client injected into the provider so no live network call occurs and
no API key is required. A failing API call must surface as an ``LLMProviderError`` whose
message identifies the ``groq`` provider.
"""

from __future__ import annotations

import pytest

from agentforge.llm.base import GenerationResult, LLMProviderError
from agentforge.llm.groq_provider import Groq_Provider


class _FailingCompletions:
    def create(self, *args, **kwargs):
        raise RuntimeError("upstream 503 from Groq")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingClient:
    """Mocked Groq client whose chat.completions.create always fails."""

    chat = _FailingChat()


class _OKMessage:
    content = "grounded answer"


class _OKChoice:
    message = _OKMessage()


class _OKCompletion:
    choices = [_OKChoice()]


class _OKCompletions:
    def __init__(self):
        self.calls = []

    def create(self, *args, **kwargs):
        self.calls.append(kwargs)
        return _OKCompletion()


class _OKChat:
    def __init__(self):
        self.completions = _OKCompletions()


class _OKClient:
    def __init__(self):
        self.chat = _OKChat()


def test_groq_failure_raises_llm_provider_error_identifying_provider():
    provider = Groq_Provider(api_key="unused-in-test", client=_FailingClient())

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate("some grounding-only prompt")

    # The error identifies the failing provider (Req 11.5).
    assert "groq" in str(exc_info.value).lower()


def test_groq_provider_name_is_groq():
    provider = Groq_Provider(api_key="unused", client=_OKClient())
    assert provider.name == "groq"


def test_groq_success_returns_generation_result_from_mock():
    client = _OKClient()
    provider = Groq_Provider(api_key="unused", client=client)

    result = provider.generate("prompt text")

    assert isinstance(result, GenerationResult)
    assert result.provider == "groq"
    assert result.text == "grounded answer"
    # The mocked client was called (no live network).
    assert len(client.chat.completions.calls) == 1
