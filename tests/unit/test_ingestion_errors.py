"""Unit tests for ingestion error mapping (Req 7.6, 7.7, 7.1).

Assert that a corrupt-file extraction failure, an oversized document, and an extraction
timeout each raise the correct error and persist zero chunks.
"""

from __future__ import annotations

import time

import pytest

from agentforge.chunking.chunker import Chunker
from agentforge.ingestion.extractors import CONTENT_TYPE_PDF, CONTENT_TYPE_TEXT, ExtractionError
from agentforge.ingestion.service import (
    ExtractionTimeoutError,
    Ingestion_Service,
    SizeLimitError,
)
from agentforge.vectorstore.chroma_store import Chroma_Store
from tests.fakes import DeterministicFakeEmbeddings, InMemorySink


def _build_service(max_document_bytes=50 * 1024 * 1024, extraction_timeout_seconds=30):
    sink = InMemorySink()
    store = Chroma_Store(dim=8)
    service = Ingestion_Service(
        chunker=Chunker(40, 8, markdown_mode="preserve"),
        embedding_provider=DeterministicFakeEmbeddings(dimension=8),
        vector_store=store,
        sink=sink,
        max_document_bytes=max_document_bytes,
        extraction_timeout_seconds=extraction_timeout_seconds,
        markdown_mode="preserve",
    )
    return service, sink, store


def test_corrupt_pdf_raises_extraction_failure_no_chunks():
    """A corrupt PDF is rejected with an extraction failure and persists no chunks (7.6)."""
    service, sink, store = _build_service()
    corrupt = b"%PDF-1.4 this is not a real pdf body"

    with pytest.raises(ExtractionError):
        service.ingest("bad.pdf", CONTENT_TYPE_PDF, corrupt)

    assert sink.total_chunks() == 0
    assert store.count() == 0


def test_oversized_document_raises_size_limit_no_chunks():
    """A document over the size limit is rejected before extraction (7.7)."""
    service, sink, store = _build_service(max_document_bytes=100)
    oversized = b"a" * 101

    with pytest.raises(SizeLimitError):
        service.ingest("big.txt", CONTENT_TYPE_TEXT, oversized)

    assert sink.total_chunks() == 0
    assert store.count() == 0


def test_extraction_timeout_raises_timeout_error_no_chunks(monkeypatch):
    """Extraction exceeding the budget raises a timeout error and persists nothing (7.1)."""
    service, sink, store = _build_service(extraction_timeout_seconds=1)

    def _slow_extract(content_type, data, markdown_mode="strip"):
        time.sleep(5)
        return "should never be reached"

    # Patch the extract symbol used inside the service module.
    monkeypatch.setattr(
        "agentforge.ingestion.service.extract", _slow_extract, raising=True
    )

    with pytest.raises(ExtractionTimeoutError):
        service.ingest("slow.txt", CONTENT_TYPE_TEXT, b"some content")

    assert sink.total_chunks() == 0
    assert store.count() == 0
