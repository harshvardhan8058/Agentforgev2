"""Embedding_Provider interface (Pluggable Seam 1).

The Embedding_Provider converts text into fixed-length numeric vectors. The service
layer (Retriever, Ingestion_Service) depends only on this abstract contract; concrete
implementations (``SentenceTransformer_Embeddings``, ``Hosted_Embeddings``) live in
sibling modules and are referenced solely by ``config/container.py`` (Req 1.2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingError(RuntimeError):
    """Raised when the Embedding_Provider cannot generate an embedding (Req 9.4).

    When raised, no partial embedding is stored by callers: the ingestion pipeline
    is atomic and rolls back on any failure.
    """


class Embedding_Provider(ABC):
    """Abstract contract for converting text into embedding vectors."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Fixed vector dimension; surfaced via Configuration_Manager (Req 9.2)."""
        raise NotImplementedError

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Return a vector of length ``dimension``.

        Raises:
            EmbeddingError: if the embedding cannot be generated (Req 9.4).
        """
        raise NotImplementedError

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts; each result has length ``dimension``.

        Raises:
            EmbeddingError: if any embedding cannot be generated (Req 9.4). No
                partial result is returned on failure.
        """
        raise NotImplementedError
