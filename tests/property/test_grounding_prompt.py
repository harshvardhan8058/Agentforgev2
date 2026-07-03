"""Property-based test: grounding-only prompt construction (Property 11).

Feature: agentforge-foundation-rag, Property 11: For any set of retrieved Chunks and
any query, the generation prompt is composed only of the fixed prompt template, the
query, and the text of the retrieved Chunks — it contains no content originating
outside the retrieved Chunks.

Validates: Requirements 12.4
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.rag.prompt import (
    CHUNK_SEPARATOR,
    CONTEXT_LABEL,
    PROMPT_HEADER,
    QUESTION_LABEL,
    build_prompt,
)

# Chunk text generator: covers empty, whitespace, and Unicode content.
_chunk_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
    min_size=0,
    max_size=120,
)
_chunk_lists = st.lists(_chunk_text, min_size=1, max_size=6)
_queries = st.text(min_size=0, max_size=80)


@hyp_settings(max_examples=100, deadline=None)
@given(query=_queries, chunk_texts=_chunk_lists)
def test_prompt_is_grounding_only(query, chunk_texts):
    prompt = build_prompt(query, chunk_texts)

    # The prompt is EXACTLY the fixed template fragments + query + chunk texts, in
    # order. Equality against a reconstruction built solely from those inputs proves no
    # content originates outside the retrieved chunks (Req 12.4).
    expected = (
        PROMPT_HEADER
        + QUESTION_LABEL
        + query
        + CONTEXT_LABEL
        + CHUNK_SEPARATOR.join(chunk_texts)
    )
    assert prompt == expected

    # The query and every retrieved chunk text appear in the prompt.
    assert query in prompt
    for text in chunk_texts:
        assert text in prompt

    # Removing the fixed template fragments, the query, and every chunk text leaves no
    # foreign residue beyond the structural separators the template itself defines.
    residue = prompt
    for fragment in (PROMPT_HEADER, QUESTION_LABEL, CONTEXT_LABEL):
        residue = residue.replace(fragment, "", 1)
    residue = residue.replace(query, "", 1)
    for text in sorted(chunk_texts, key=len, reverse=True):
        if text:
            residue = residue.replace(text, "")
    # Only chunk separators (part of the fixed template) may remain.
    assert residue.replace(CHUNK_SEPARATOR, "") == ""
