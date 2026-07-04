"""DocumentStore port and the DocumentListing view model.

The ``DocumentStore`` unifies three narrow responsibilities the platform needs from
relational storage:

* **persist** — save a document and its chunks atomically (the Ingestion_Service's
  ``DocumentSink`` port).
* **get_chunk_texts** — load chunk text by id (the Retriever's ``Chunk_Text_Source``
  port), so retrieved matches can be turned into grounding context.
* **catalog operations** — ``list_documents`` / ``get_document`` / ``delete_document``
  for the documents router.

Keeping these behind one port lets the composition root swap an in-memory store (for
keyless standalone runs / tests) for a DB-backed adapter (production) without touching
the service layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agentforge.models.domain import Chunk, Document


@dataclass
class DocumentListing:
    """A summary row for the ``GET /documents`` listing."""

    document_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    chunk_count: int
    created_at: str  # ISO-8601 timestamp


class DocumentStore(Protocol):
    """Relational persistence port for documents and their chunks.

    Every method is tenant-scoped: the leading ``org_id`` constrains the query so a
    document (and its chunks, via the parent FK) can only ever be read or mutated within
    its owning organization. Cross-tenant reads return ``None`` / empty and cross-tenant
    mutations affect zero rows, so the router surfaces ``404`` — never a leak (Req 4.5, 4.6).
    """

    def persist(self, org_id: UUID, document: Document, chunks: list[Chunk]) -> None:
        """Atomically persist a document (owned by ``org_id``) and its chunks (Req 4.4)."""
        ...

    def get_chunk_texts(self, org_id: UUID, chunk_ids: list[str]) -> dict[str, str]:
        """Return ``chunk_id -> content`` for chunks whose parent document is ``org_id``'s."""
        ...

    def list_documents(self, org_id: UUID) -> list[DocumentListing]:
        """Return a summary of ``org_id``'s documents only (Req 4.2)."""
        ...

    def get_document(self, org_id: UUID, document_id: str) -> Document | None:
        """Return ``org_id``'s document by id, or ``None`` (incl. cross-tenant) (Req 4.3)."""
        ...

    def delete_document(self, org_id: UUID, document_id: str) -> None:
        """Delete the document iff it belongs to ``org_id`` (else a no-op) (Req 4.3)."""
        ...
