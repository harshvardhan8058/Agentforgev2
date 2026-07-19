"""Retriever.

Embeds the user query via the ``Embedding_Provider``, clamps ``k`` to ``[1, 10]``
(Req 12.1), and loads matched chunk text from a ``Chunk_Text_Source`` (the DB in
production, an in-memory store in tests). Tenant-capable vector adapters filter before
applying ``k``; other adapters are filtered through the scoped text source. It never
returns more than ``k`` matches (Req 10.5).

The Retriever depends only on the abstract seams (``Embedding_Provider``,
``Vector_Store``) plus a narrow ``Chunk_Text_Source`` port, so it stays independent of
any concrete backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agentforge.embeddings.base import Embedding_Provider
from agentforge.enterprise.tenancy import NIL_ORG_ID
from agentforge.vectorstore.base import Vector_Store

# Hard bounds on the retrieval count (Req 12.1); the effective K always lies in [1, 10].
K_MIN = 1
K_MAX = 10


def clamp_k(k: int, k_min: int = K_MIN, k_max: int = K_MAX) -> int:
    """Clamp a requested retrieval count into ``[k_min, k_max]`` (Req 12.1)."""
    return max(k_min, min(k, k_max))


@dataclass
class RetrievedChunk:
    """A retrieved chunk: its identity, its source document, text, and score."""

    chunk_id: str
    document_id: str
    content: str
    score: float


class Chunk_Text_Source(Protocol):
    """Port for loading chunk text by id (implemented by the DB / in-memory store)."""

    def get_chunk_texts(self, org_id: UUID, chunk_ids: list[str]) -> dict[str, str]:
        """Return a mapping of ``chunk_id -> content`` for ``org_id``'s chunks."""
        ...


class Retriever:
    """Turns a query into the most relevant chunks (with their text)."""

    def __init__(
        self,
        embedding_provider: Embedding_Provider,
        vector_store: Vector_Store,
        chunk_text_source: Chunk_Text_Source,
        k_min: int = K_MIN,
        k_max: int = K_MAX,
    ) -> None:
        self._embeddings = embedding_provider
        self._vector_store = vector_store
        self._chunk_text_source = chunk_text_source
        self._k_min = k_min
        self._k_max = k_max

    def retrieve(
        self, query: str, k: int, *, org_id: UUID = NIL_ORG_ID
    ) -> list[RetrievedChunk]:
        """Return at most ``clamp(k)`` of ``org_id``'s chunks by descending similarity.

        Chunk text is loaded through the org-scoped ``get_chunk_texts``, so a match whose
        parent document belongs to another tenant resolves to no text and is dropped —
        retrieval never crosses a tenant boundary (Req 4.6).
        """
        effective_k = clamp_k(k, self._k_min, self._k_max)

        query_vector = self._embeddings.embed_text(query)
        query_for_org = getattr(self._vector_store, "query_for_org", None)
        if callable(query_for_org):
            matches = query_for_org(query_vector, effective_k, org_id)
        else:
            # Compatibility for older duck-typed adapters that predate the additive
            # tenant-aware method. Foreign matches are still dropped below.
            matches = self._vector_store.query(query_vector, effective_k)

        # The text source independently enforces parent-document tenancy. Dropping any
        # unresolved match protects callers of legacy adapters that inherit the default
        # query_for_org implementation.
        texts = self._chunk_text_source.get_chunk_texts(
            org_id, [m.chunk_id for m in matches]
        )
        return [
            RetrievedChunk(
                chunk_id=m.chunk_id,
                document_id=m.document_id,
                content=texts[m.chunk_id],
                score=m.score,
            )
            for m in matches
            if m.chunk_id in texts
        ][:effective_k]
