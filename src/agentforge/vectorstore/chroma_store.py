"""Chroma_Store: local Vector_Store implementation backed by embedded Chroma.

Used in the ``local`` profile (Req 10.2). It runs fully in-memory with no external
infrastructure. Each embedding is stored under its originating chunk id with its
document id in metadata (Req 10.4). Queries return at most ``k`` matches ordered by
descending similarity, and all stored matches when fewer than ``k`` exist
(Req 10.5, 10.6).
"""

from __future__ import annotations

import uuid

import chromadb
from chromadb.config import Settings as ChromaSettings

from agentforge.vectorstore.base import StoredMatch, Vector_Store


class Chroma_Store(Vector_Store):
    """In-memory Chroma-backed vector store (local development default)."""

    def __init__(self, dim: int, collection_name: str | None = None) -> None:
        self._dim = dim
        self._client = chromadb.EphemeralClient(
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
        )
        # Unique collection name so independent store instances stay isolated.
        name = collection_name or f"agentforge_{uuid.uuid4().hex}"
        self._collection = self._client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunk_id: str, document_id: str, embedding: list[float]) -> None:
        """Persist an embedding associated with its chunk and document (Req 10.4)."""
        self._collection.upsert(
            ids=[chunk_id],
            embeddings=[list(embedding)],
            metadatas=[{"document_id": document_id}],
        )

    def query(self, embedding: list[float], k: int) -> list[StoredMatch]:
        """Return at most ``min(k, count)`` matches, descending similarity."""
        stored = self.count()
        n = min(k, stored)
        if n <= 0:
            return []
        result = self._collection.query(
            query_embeddings=[list(embedding)],
            n_results=n,
            include=["metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        matches: list[StoredMatch] = []
        for chunk_id, meta, distance in zip(ids, metadatas, distances):
            # Cosine distance in [0, 2]; convert to a descending-similarity score.
            score = 1.0 - float(distance)
            document_id = str((meta or {}).get("document_id", ""))
            matches.append(
                StoredMatch(chunk_id=str(chunk_id), document_id=document_id, score=score)
            )
        # Chroma returns ascending distance == descending similarity already; make the
        # ordering explicit and robust regardless of backend behavior.
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    def delete_document(self, document_id: str) -> None:
        """Remove all embeddings belonging to a document."""
        self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return int(self._collection.count())
