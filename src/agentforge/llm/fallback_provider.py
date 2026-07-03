"""Fallback_Provider: deterministic, network-free default LLM provider.

Active when no external LLM credential is configured (Req 11.3). It produces a
**deterministic** answer that is a pure function of the prompt it receives and calls
**no external service** (Req 11.4). Because the RAG_Service builds a grounding-only
prompt from the retrieved chunks, the answer this provider returns is derived solely
from that grounding context — no outside content is introduced. Its determinism makes
it ideal for property-based tests and lets the whole suite run keyless (Req 13.3).
"""

from __future__ import annotations

import re

from agentforge.llm.base import GenerationResult, LLM_Provider

_WHITESPACE = re.compile(r"\s+")

# A fixed lead-in. This is the ONLY text the provider adds; everything after it is
# derived purely from the prompt, keeping the answer grounded.
_PREAMBLE = "Based on the provided context:"

# Bound the echoed grounding so answers stay concise and deterministic in size.
_MAX_ANSWER_CHARS = 2000


class Fallback_Provider(LLM_Provider):
    """Deterministic LLM provider that grounds its answer in the prompt only."""

    @property
    def name(self) -> str:
        return "fallback"

    def generate(self, prompt: str) -> GenerationResult:
        """Return a deterministic answer composed solely from the prompt.

        The answer is a fixed preamble followed by the whitespace-normalized prompt
        content (truncated to a fixed bound). Identical prompts always yield identical
        output, and every non-preamble token in the answer originates in the prompt.
        """
        normalized = _WHITESPACE.sub(" ", prompt).strip()
        grounded = normalized[:_MAX_ANSWER_CHARS]
        text = f"{_PREAMBLE} {grounded}".strip()
        return GenerationResult(text=text, provider=self.name)
