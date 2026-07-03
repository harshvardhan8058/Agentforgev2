"""Property-based tests for the Chunker (Properties 1, 2, 3).

All three run against generated text (including empty, whitespace, Unicode, and text
exactly at the boundary) and valid chunker configurations.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.chunking.chunker import Chunker

_DOC_ID = "doc-123"

# Text generator: cover empty, whitespace-only, Unicode, and long inputs.
_texts = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
    min_size=0,
    max_size=400,
)


@st.composite
def _configs(draw):
    """Valid config: 0 <= overlap < max."""
    max_chars = draw(st.integers(min_value=1, max_value=60))
    overlap = draw(st.integers(min_value=0, max_value=max_chars - 1))
    mode = draw(st.sampled_from(["preserve", "strip"]))
    return max_chars, overlap, mode


@hyp_settings(max_examples=100, deadline=None)
@given(text=_texts, config=_configs())
def test_chunk_maximum_size_invariant(text, config):
    """Feature: agentforge-foundation-rag, Property 1: For any document text and any
    valid chunker configuration (chunk_max_chars > chunk_overlap_chars >= 0), every
    Chunk produced by the Chunker has content length at most chunk_max_chars.

    Validates: Requirements 8.1, 8.4
    """
    max_chars, overlap, mode = config
    chunker = Chunker(max_chars, overlap, markdown_mode=mode)

    chunks = chunker.chunk(text, _DOC_ID)

    for chunk in chunks:
        assert len(chunk.content) <= max_chars

    # Req 8.4: normalized input at most max size -> exactly one chunk.
    if len(chunker.normalize(text)) <= max_chars:
        assert len(chunks) == 1


@hyp_settings(max_examples=100, deadline=None)
@given(text=_texts, config=_configs())
def test_chunk_overlap_invariant(text, config):
    """Feature: agentforge-foundation-rag, Property 2: For any document text that
    produces two or more Chunks, each pair of consecutive Chunks shares exactly the
    configured overlap (the last overlap_prev characters of one Chunk equal the first
    overlap_prev characters of the next).

    Validates: Requirements 8.2
    """
    max_chars, overlap, mode = config
    chunker = Chunker(max_chars, overlap, markdown_mode=mode)

    chunks = chunker.chunk(text, _DOC_ID)

    for i in range(1, len(chunks)):
        prev, cur = chunks[i - 1], chunks[i]
        # The recorded per-boundary overlap equals the configured overlap.
        assert cur.overlap_prev == overlap
        if overlap > 0:
            assert prev.content[-overlap:] == cur.content[:overlap]


@hyp_settings(max_examples=100, deadline=None)
@given(text=_texts, config=_configs())
def test_chunk_round_trip_reconstruction(text, config):
    """Feature: agentforge-foundation-rag, Property 3: For any document text and any
    valid chunker configuration, concatenating the Chunks in order while removing the
    recorded overlap between consecutive Chunks reconstructs the original
    chunker-input text exactly.

    Validates: Requirements 8.5, 13.4
    """
    max_chars, overlap, mode = config
    chunker = Chunker(max_chars, overlap, markdown_mode=mode)

    chunks = chunker.chunk(text, _DOC_ID)

    reconstructed = ""
    for i, chunk in enumerate(chunks):
        if i == 0:
            reconstructed = chunk.content
        else:
            reconstructed += chunk.content[chunk.overlap_prev:]

    assert reconstructed == chunker.normalize(text)
    # Every chunk preserves the source document reference and ordinal ordering.
    for i, chunk in enumerate(chunks):
        assert chunk.document_id == _DOC_ID
        assert chunk.index == i
