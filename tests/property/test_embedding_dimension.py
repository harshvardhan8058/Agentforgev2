"""Property-based test: embedding dimension is fixed and stable.

Feature: agentforge-foundation-rag, Property 6: For any input text, the
Embedding_Provider returns a vector whose length equals the configured embedding
dimension, and repeated calls with identical text return vectors of identical
dimension.

Validates: Requirements 9.1, 9.3

This test exercises the REAL SentenceTransformer_Embeddings provider (the default local
embedder) so the dimension guarantee is validated against the actual model. The model
is loaded once and reused across examples.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.embeddings.sentence_transformer import SentenceTransformer_Embeddings

# Module-scoped provider: load the model once for the whole property run.
_PROVIDER = SentenceTransformer_Embeddings()
_EXPECTED_DIMENSION = 384

# Smart generator: non-empty text (embedders receive chunk text), including Unicode.
_texts = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
    min_size=1,
    max_size=120,
)


@pytest.mark.slow
@hyp_settings(
    max_examples=100,
    deadline=None,  # model inference latency varies; determinism is what we assert
    suppress_health_check=[HealthCheck.too_slow],
)
@given(text=_texts)
def test_embedding_dimension_is_fixed_and_stable(text):
    assert _PROVIDER.dimension == _EXPECTED_DIMENSION

    first = _PROVIDER.embed_text(text)
    second = _PROVIDER.embed_text(text)

    # Length equals the configured dimension on every call (Req 9.1).
    assert len(first) == _EXPECTED_DIMENSION
    assert len(second) == _EXPECTED_DIMENSION
    # Repeated calls with identical text return vectors of identical dimension (Req 9.3).
    assert len(first) == len(second)
