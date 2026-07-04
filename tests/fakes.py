"""Test doubles used across the AgentForge test suite.

The ``DeterministicFakeEmbeddings`` provider is a fast, dependency-free stand-in for
``SentenceTransformer_Embeddings`` used by chunker / ingestion / vector-store property
tests so they don't need to download or run a real model. It honors the
``Embedding_Provider`` contract: a fixed dimension and deterministic vectors for
identical inputs. At least one dedicated test still exercises the real provider's
dimension.
"""

from __future__ import annotations

import hashlib

from agentforge.embeddings.base import Embedding_Provider, EmbeddingError


class DeterministicFakeEmbeddings(Embedding_Provider):
    """A deterministic, hash-seeded embedding provider for tests."""

    def __init__(self, dimension: int = 8, fail_on: str | None = None) -> None:
        self._dimension = dimension
        # If set, embedding this exact text raises EmbeddingError (failure simulation).
        self._fail_on = fail_on

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_text(self, text: str) -> list[float]:
        if self._fail_on is not None and text == self._fail_on:
            raise EmbeddingError(f"Simulated embedding failure for {text!r}")
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Map bytes deterministically into a fixed-length float vector in [0, 1).
        return [digest[i % len(digest)] / 255.0 for i in range(self._dimension)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]



from agentforge.models.domain import Chunk, Document  # noqa: E402


class InMemorySink:
    """In-memory DocumentSink for ingestion tests.

    Records persisted documents and chunks so tests can assert the atomicity and
    chunk-association guarantees without a real database.
    """

    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.chunks: dict[str, list[Chunk]] = {}
        self.org_ids: dict[str, object] = {}

    def persist(self, org_id, document: Document, chunks: list[Chunk]) -> None:
        self.documents[document.id] = document
        self.chunks[document.id] = list(chunks)
        self.org_ids[document.id] = org_id

    def chunk_count(self, document_id: str) -> int:
        return len(self.chunks.get(document_id, []))

    def total_chunks(self) -> int:
        return sum(len(v) for v in self.chunks.values())
