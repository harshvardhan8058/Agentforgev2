"""Vector_Store interface and StoredMatch (Pluggable Seam 2).

The Vector_Store persists embeddings and returns the most similar embeddings for a
query. The service layer depends only on this abstract contract; concrete
implementations (``Chroma_Store`` local, ``Pgvector_Store`` production) live in
sibling modules and are selected by ``config/container.py`` (Req 1.2, 10.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass
class StoredMatch:
    """A single query result: a stored chunk and its similarity score."""

    chunk_id: str
    document_id: str
    score: float  # similarity, higher == more similar


class Vector_Store(ABC):
    """Abstract contract for storing and querying embeddings."""

    @abstractmethod
    def upsert(self, chunk_id: str, document_id: str, embedding: list[float]) -> None:
        """Persist an embedding associated with its originating chunk (Req 10.4)."""
        raise NotImplementedError

    def upsert_for_org(
        self,
        chunk_id: str,
        document_id: str,
        embedding: list[float],
        org_id: UUID,
    ) -> None:
        """Persist an org-owned embedding, defaulting to the legacy global write."""
        self.upsert(chunk_id, document_id, embedding)

    @abstractmethod
    def query(self, embedding: list[float], k: int) -> list[StoredMatch]:
        """Return at most ``k`` matches ordered by descending similarity.

        Post-conditions (Req 10.5, 10.6):
            * ``len(result) <= k``
            * if ``count() < k`` then ``len(result) == count()``
            * results are ordered by non-increasing similarity score.
        """
        raise NotImplementedError

    def query_for_org(
        self, embedding: list[float], k: int, org_id: UUID
    ) -> list[StoredMatch]:
        """Query an org's vectors, defaulting to the legacy global query.

        Built-in multi-tenant adapters override this method to filter before applying
        ``k``. The concrete default keeps existing third-party subclasses source
        compatible; the Retriever's scoped text source still drops foreign matches.
        """
        return self.query(embedding, k)

    @abstractmethod
    def delete_document(self, document_id: str) -> None:
        """Remove all embeddings belonging to a document."""
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        """Return the total number of stored embeddings."""
        raise NotImplementedError
