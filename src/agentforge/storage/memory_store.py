"""InMemoryDocumentStore: a dependency-free DocumentStore implementation.

Backs keyless, standalone runs (the ``scripts/verify_e2e.py`` check) and the keyless
API integration tests. It keeps documents and chunks in process memory and honors the
same ``DocumentStore`` contract as the DB-backed adapter, so calling code is identical.

Tenancy is enforced structurally: documents are keyed by ``(org_id, document_id)`` and
chunk text is retrievable only for chunks whose parent document belongs to the querying
``org_id``. A cross-tenant ``get`` returns ``None``, a cross-tenant ``list`` returns
``[]``, and a cross-tenant ``delete`` is a no-op (Req 4.2, 4.3, 4.6).
"""

from __future__ import annotations

from uuid import UUID

from agentforge.models.domain import Chunk, Document
from agentforge.storage.base import DocumentListing


class InMemoryDocumentStore:
    """Process-memory document/chunk store implementing the DocumentStore port."""

    def __init__(self) -> None:
        # Keyed by (org_id, document_id) so cross-tenant access is structurally impossible.
        self._documents: dict[tuple[UUID, str], Document] = {}
        self._chunks: dict[tuple[UUID, str], list[Chunk]] = {}
        # chunk_id -> (org_id, content) so get_chunk_texts can filter by tenant.
        self._chunk_text: dict[str, tuple[UUID, str]] = {}

    def persist(self, org_id: UUID, document: Document, chunks: list[Chunk]) -> None:
        self._documents[(org_id, document.id)] = document
        self._chunks[(org_id, document.id)] = list(chunks)
        for chunk in chunks:
            self._chunk_text[chunk.id] = (org_id, chunk.content)

    def get_chunk_texts(self, org_id: UUID, chunk_ids: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for cid in chunk_ids:
            entry = self._chunk_text.get(cid)
            if entry is not None and entry[0] == org_id:
                result[cid] = entry[1]
        return result

    def list_documents(self, org_id: UUID) -> list[DocumentListing]:
        listings: list[DocumentListing] = []
        for (owner, doc_id), doc in self._documents.items():
            if owner != org_id:
                continue
            listings.append(
                DocumentListing(
                    document_id=doc.id,
                    filename=doc.filename,
                    content_type=doc.content_type,
                    size_bytes=doc.size_bytes,
                    status=doc.status,
                    chunk_count=len(self._chunks.get((owner, doc_id), [])),
                    created_at=doc.created_at.isoformat(),
                )
            )
        return listings

    def get_document(self, org_id: UUID, document_id: str) -> Document | None:
        return self._documents.get((org_id, document_id))

    def find_by_content_hash(
        self, org_id: UUID, content_hash: str
    ) -> DocumentListing | None:
        """Return this org's document with the given content hash, if one exists."""
        for listing in self.list_documents(org_id):
            document = self._documents.get((org_id, listing.document_id))
            if document is not None and document.content_hash == content_hash:
                return listing
        return None

    def delete_document(self, org_id: UUID, document_id: str) -> None:
        self._documents.pop((org_id, document_id), None)
        removed = self._chunks.pop((org_id, document_id), [])
        for chunk in removed:
            self._chunk_text.pop(chunk.id, None)
