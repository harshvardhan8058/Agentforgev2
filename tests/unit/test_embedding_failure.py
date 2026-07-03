"""Unit tests for embedding-generation failure handling (Req 9.4).

When the Embedding_Provider cannot generate an embedding it must raise EmbeddingError
and must not return a partial embedding.
"""

from __future__ import annotations

import pytest

from agentforge.embeddings.base import EmbeddingError
from agentforge.embeddings.sentence_transformer import SentenceTransformer_Embeddings


class _RaisingModel:
    """Stub model whose encode always fails."""

    def encode(self, *args, **kwargs):
        raise RuntimeError("model boom")


class _WrongDimModel:
    """Stub model that returns a vector of the wrong dimension."""

    def encode(self, texts, **kwargs):
        return [[0.0, 1.0, 2.0] for _ in texts]  # length 3, not 384


def test_encode_failure_raises_embedding_error():
    provider = SentenceTransformer_Embeddings()
    provider._model = _RaisingModel()  # inject failing model, skip real load

    with pytest.raises(EmbeddingError):
        provider.embed_text("hello")

    with pytest.raises(EmbeddingError):
        provider.embed_batch(["a", "b"])


def test_dimension_mismatch_raises_embedding_error_no_partial():
    provider = SentenceTransformer_Embeddings(dimension=384)
    provider._model = _WrongDimModel()

    with pytest.raises(EmbeddingError):
        provider.embed_batch(["only-one-text"])


def test_null_input_raises_embedding_error():
    provider = SentenceTransformer_Embeddings()
    with pytest.raises(EmbeddingError):
        provider.embed_batch(None)  # type: ignore[arg-type]
