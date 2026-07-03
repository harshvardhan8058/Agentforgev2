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
    """Relational persistence port for documents and their chunks."""

    def persist(self, document: Document, chunks: list[Chunk]) -> None:
        """Atomically persist a document and its chunks."""
        ...

    def get_chunk_texts(self, chunk_ids: list[str]) -> dict[str, str]:
        """Return a mapping of ``chunk_id -> content`` for the given ids."""
        ...

    def list_documents(self) -> list[DocumentListing]:
        """Return a summary of all stored documents."""
        ...

    def get_document(self, document_id: str) -> Document | None:
        """Return a document by id, or ``None`` if unknown."""
        ...

    def delete_document(self, document_id: str) -> None:
        """Delete a document and cascade to its chunks."""
        ...
