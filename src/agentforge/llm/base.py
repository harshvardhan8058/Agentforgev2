"""LLM_Provider interface, GenerationResult, and LLMProviderError (Pluggable Seam 3).

The LLM_Provider generates text completions from a prompt. The RAG_Service depends
only on this abstract contract, so a new provider can be added by implementing this
interface and registering it in ``config/container.py`` without modifying the
RAG_Service (Req 1.2, 11.1, 11.6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMProviderError(RuntimeError):
    """Raised when an LLM_Provider fails to generate a completion (Req 11.5).

    The message identifies the provider that failed.
    """


@dataclass
class GenerationResult:
    """The outcome of a generation request."""

    text: str
    provider: str
    # The concrete model that served the call, when the provider knows it.
    # Optional and defaulted so implementations that cannot report a model — and
    # every existing caller constructing this by position — are unaffected.
    # Usage analytics groups by this, and without it the "by model" breakdown
    # could only repeat the provider name.
    model: str | None = None


class LLM_Provider(ABC):
    """Abstract contract for generating text completions from a prompt."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for this provider (e.g. ``"groq"``, ``"fallback"``)."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str) -> GenerationResult:
        """Generate a completion for ``prompt``.

        Raises:
            LLMProviderError: on provider failure, identifying the provider (Req 11.5).
        """
        raise NotImplementedError
