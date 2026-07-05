"""Ingestion_Service orchestration.

Orchestrates the ingestion pipeline: **validate -> extract -> chunk -> embed -> store
vectors -> persist document + chunk records** (design Flow 1). It enforces the 50 MB
size limit (Req 7.7), the text/PDF/Markdown allow-list (Req 7.5), and the 30-second
extraction budget (Req 7.1), and rejects empty (Req 7.4), corrupt (Req 7.6), and
embedding-failure (Req 9.4) inputs.

**Atomicity:** every rejection is detected *before* any vector or relational write
occurs, so a rejected document persists **zero** Chunks (Req 7.4-7.6, 9.4). Should a
write fail after embeddings succeed, previously written vectors are rolled back.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from agentforge.chunking.chunker import Chunker
from agentforge.embeddings.base import Embedding_Provider
from agentforge.enterprise.tenancy import NIL_ORG_ID
from agentforge.ingestion.extractors import (
    SUPPORTED_CONTENT_TYPES,
    extract,
)
from agentforge.models.domain import Chunk, Document
from agentforge.vectorstore.base import Vector_Store


class EmptyDocumentError(RuntimeError):
    """A submitted document has no recoverable text content (Req 7.4)."""


class UnsupportedFormatError(RuntimeError):
    """A submitted document uses an unsupported content type (Req 7.5)."""


class ExtractionTimeoutError(RuntimeError):
    """Text extraction exceeded the configured budget (Req 7.1)."""


class SizeLimitError(RuntimeError):
    """A submitted document exceeds the maximum supported size (Req 7.7)."""


class DocumentSink(Protocol):
    """Persistence port for atomically saving a document and its chunks.

    Implemented by an async-DB-backed adapter in production and by an in-memory fake
    in tests, keeping the Ingestion_Service independent of the storage backend.
    """

    def persist(self, org_id: UUID, document: Document, chunks: list[Chunk]) -> None: ...


@dataclass
class IngestionResult:
    """Outcome of a successful ingestion."""

    document_id: str
    filename: str
    chunk_count: int
    status: str


class Ingestion_Service:
    """Coordinates validation, extraction, chunking, embedding, and persistence."""

    def __init__(
        self,
        chunker: Chunker,
        embedding_provider: Embedding_Provider,
        vector_store: Vector_Store,
        sink: DocumentSink,
        max_document_bytes: int,
        extraction_timeout_seconds: int,
        markdown_mode: str = "strip",
    ) -> None:
        self._chunker = chunker
        self._embeddings = embedding_provider
        self._vector_store = vector_store
        self._sink = sink
        self._max_document_bytes = max_document_bytes
        self._extraction_timeout_seconds = extraction_timeout_seconds
        self._markdown_mode = markdown_mode

    def ingest(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        *,
        org_id: UUID = NIL_ORG_ID,
    ) -> IngestionResult:
        """Run the full ingestion pipeline for a single document owned by ``org_id`` (Req 4.4)."""
        # 1. Size limit — enforced before extraction (Req 7.7).
        if len(data) > self._max_document_bytes:
            raise SizeLimitError(
                f"Document exceeds maximum size of {self._max_document_bytes} bytes"
            )

        # 2. Format allow-list (Req 7.5).
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise UnsupportedFormatError(f"Unsupported content type: {content_type!r}")

        # 3. Zero-byte submissions have no recoverable text (Req 7.4), independent of
        #    format, so reject them as empty before attempting extraction.
        if len(data) == 0:
            raise EmptyDocumentError("Document is empty (zero bytes)")

        # 4. Extract text within the budget (Req 7.1, 7.6). ExtractionError propagates.
        text = self._extract_with_timeout(content_type, data)

        # 5. Reject documents with no recoverable text (Req 7.4).
        if not text or not text.strip():
            raise EmptyDocumentError("Document contains no extractable text")

        document_id = str(uuid.uuid4())

        # 6. Chunk. The extractor already applied markdown normalization, so the chunker
        #    runs in identity (preserve) mode to avoid double-normalization.
        chunks = self._chunker.chunk(text, document_id)

        # 7. Embed BEFORE any store write so an embedding failure persists nothing
        #    (Req 9.4). EmbeddingError propagates to the caller.
        vectors = self._embeddings.embed_batch([c.content for c in chunks])

        document = Document(
            id=document_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
            status="ingested",
            created_at=datetime.now(timezone.utc),
        )

        # 8. Commit: write vectors then persist records. Roll back vectors on failure so
        #    the "persist no Chunks" guarantee holds even on a late write error.
        try:
            for chunk, vector in zip(chunks, vectors):
                self._vector_store.upsert(chunk.id, document_id, vector)
            self._sink.persist(org_id, document, chunks)
        except Exception:
            self._vector_store.delete_document(document_id)
            raise

        return IngestionResult(
            document_id=document_id,
            filename=filename,
            chunk_count=len(chunks),
            status="ingested",
        )

    def _extract_with_timeout(self, content_type: str, data: bytes) -> str:
        """Run extraction with the configured timeout budget (Req 7.1)."""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                extract, content_type, data, self._markdown_mode
            )
            try:
                return future.result(timeout=self._extraction_timeout_seconds)
            except FutureTimeoutError as exc:
                raise ExtractionTimeoutError(
                    "Text extraction exceeded the "
                    f"{self._extraction_timeout_seconds}s budget"
                ) from exc
