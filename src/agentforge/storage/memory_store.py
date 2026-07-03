"""InMemoryDocumentStore: a dependency-free DocumentStore implementation.

Backs keyless, standalone runs (the ``scripts/verify_e2e.py`` check) and the keyless
API integration tests. It keeps documents and chunks in process memory and honors the
same ``DocumentStore`` contract as the DB-backed adapter, so calling code is identical.
"""

from __future__ import annotations

from agentforge.models.domain import Chunk, Document
from agentforge.storage.base import DocumentListing


class InMemoryDocumentStore:
    """Process-memory document/chunk store implementing the DocumentStore port."""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, list[Chunk]] = {}
        self._chunk_text: dict[str, str] = {}

    def persist(self, document: Document, chunks: list[Chunk]) -> None:
        self._documents[document.id] = document
        self._chunks[document.id] = list(chunks)
        for chunk in chunks:
            self._chunk_text[chunk.id] = chunk.content

    def get_chunk_texts(self, chunk_ids: list[str]) -> dict[str, str]:
        return {
            cid: self._chunk_text[cid] for cid in chunk_ids if cid in self._chunk_text
        }

    def list_documents(self) -> list[DocumentListing]:
        listings: list[DocumentListing] = []
        for doc in self._documents.values():
            listings.append(
                DocumentListing(
                    document_id=doc.id,
                    filename=doc.filename,
                    content_type=doc.content_type,
                    size_bytes=doc.size_bytes,
                    status=doc.status,
                    chunk_count=len(self._chunks.get(doc.id, [])),
                    created_at=doc.created_at.isoformat(),
                )
            )
        return listings

    def get_document(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    def delete_document(self, document_id: str) -> None:
        self._documents.pop(document_id, None)
        removed = self._chunks.pop(document_id, [])
        for chunk in removed:
            self._chunk_text.pop(chunk.id, None)
