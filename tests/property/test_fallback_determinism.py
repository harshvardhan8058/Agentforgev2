"""Property-based test: fallback generation is deterministic and grounded.

Feature: agentforge-foundation-rag, Property 13: For any set of retrieved Chunks and
any query, the Fallback_Provider produces an answer that is a deterministic function of
its inputs (identical inputs yield identical output) derived solely from the retrieved
Chunks, without any external call, while still obeying the grounding rules.

Validates: Requirements 11.4, 12.6
"""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.llm.base import GenerationResult
from agentforge.llm.fallback_provider import Fallback_Provider

_WHITESPACE = re.compile(r"\s+")

# Smart generator: build a grounding-only prompt from a query plus 1..6 chunk texts,
# covering Unicode, whitespace, and short/empty fragments.
_chunk_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
    min_size=0,
    max_size=200,
)
_prompts = st.builds(
    lambda query, chunks: (
        f"Answer the question using only the context.\n"
        f"Question: {query}\n"
        f"Context:\n" + "\n".join(chunks)
    ),
    query=st.text(min_size=0, max_size=80),
    chunks=st.lists(_chunk_text, min_size=1, max_size=6),
)


@hyp_settings(max_examples=100)
@given(prompt=_prompts)
def test_fallback_is_deterministic_and_grounded(prompt):
    provider = Fallback_Provider()

    first = provider.generate(prompt)
    second = provider.generate(prompt)

    # Deterministic: identical inputs yield identical output.
    assert isinstance(first, GenerationResult)
    assert first.text == second.text
    assert first.provider == "fallback"

    # Grounded: everything after the fixed preamble is derived solely from the prompt.
    preamble = "Based on the provided context:"
    assert first.text.startswith(preamble)
    grounded_part = first.text[len(preamble):].strip()

    normalized_prompt = _WHITESPACE.sub(" ", prompt).strip()
    # The grounded portion must be content taken verbatim from the (normalized) prompt,
    # i.e. no fabricated content originating outside the retrieved-chunk context.
    assert grounded_part in normalized_prompt
