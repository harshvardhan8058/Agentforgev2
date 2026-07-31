"""Re-uploading the same file must not create a second copy of it.

Ingestion had no notion of document identity beyond the generated id. Uploading the same
file twice therefore produced two complete copies — two document rows, two full sets of
chunks, two sets of embeddings — and the corpus listing showed the same filename
repeatedly, which reads as a defect rather than as a faithful record of two uploads.

The cost was not only cosmetic: the second upload re-extracted, re-chunked and re-embedded
identical bytes. Embedding is the most expensive step in the pipeline, so the duplicate
check is placed *before* it; these tests assert that ordering rather than merely asserting
the end state, because a check that ran after embedding would fix the listing while
keeping the waste.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from agentforge.chunking.chunker import Chunker
from agentforge.ingestion.service import Ingestion_Service
from agentforge.models.domain import Document
from agentforge.storage.memory_store import InMemoryDocumentStore

from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8
_ORG = uuid.uuid4()
_OTHER_ORG = uuid.uuid4()
_CONTENT = b"New engineers receive a laptop and a display on day one."


class _CountingEmbeddings(DeterministicFakeEmbeddings):
    """Counts embedding calls so the test can prove work was skipped, not repeated."""

    def __init__(self, dimension: int) -> None:
        super().__init__(dimension=dimension)
        self.batches = 0

    def embed_batch(self, texts):  # type: ignore[no-untyped-def]
        self.batches += 1
        return super().embed_batch(texts)


class _RecordingVectorStore:
    """A minimal Vector_Store double that records upserts."""

    def __init__(self) -> None:
        self.upserts: list[str] = []
        self.deleted: list[str] = []

    def upsert(self, chunk_id: str, document_id: str, vector) -> None:  # noqa: ANN001
        self.upserts.append(chunk_id)

    def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


@pytest.fixture
def service_parts():
    """Return ``(service, store, embeddings, vectors)`` over keyless in-memory doubles."""
    store = InMemoryDocumentStore()
    embeddings = _CountingEmbeddings(dimension=_DIM)
    vectors = _RecordingVectorStore()
    service = Ingestion_Service(
        chunker=Chunker(chunk_max_chars=200, chunk_overlap_chars=0),
        embedding_provider=embeddings,
        vector_store=vectors,
        sink=store,
        max_document_bytes=1_000_000,
        extraction_timeout_seconds=10,
    )
    return service, store, embeddings, vectors


def _ingest(service, data=_CONTENT, filename="policy.txt", org_id=_ORG):
    return service.ingest(filename, "text/plain", data, org_id=org_id)


class TestSameBytesTwice:
    def test_the_second_upload_returns_the_first_document(self, service_parts):
        service, _store, _emb, _vec = service_parts

        first = _ingest(service)
        second = _ingest(service)

        assert second.document_id == first.document_id
        assert second.duplicate is True
        assert first.duplicate is False

    def test_the_corpus_still_holds_exactly_one_document(self, service_parts):
        service, store, _emb, _vec = service_parts

        _ingest(service)
        _ingest(service)

        assert len(store.list_documents(_ORG)) == 1

    def test_the_duplicate_is_not_re_embedded(self, service_parts):
        # The whole point of checking before the expensive steps.
        service, _store, embeddings, _vec = service_parts

        _ingest(service)
        assert embeddings.batches == 1

        _ingest(service)
        assert embeddings.batches == 1

    def test_the_duplicate_writes_no_vectors(self, service_parts):
        service, _store, _emb, vectors = service_parts

        _ingest(service)
        after_first = len(vectors.upserts)
        _ingest(service)

        assert len(vectors.upserts) == after_first

    def test_the_duplicate_reports_the_existing_chunk_count(self, service_parts):
        service, _store, _emb, _vec = service_parts

        first = _ingest(service)
        second = _ingest(service)

        assert second.chunk_count == first.chunk_count
        assert second.chunk_count > 0


class TestIdentityIsContentNotFilename:
    def test_the_same_bytes_under_a_different_name_is_a_duplicate(self, service_parts):
        # Uploading "report.txt" and "report-final.txt" with identical contents is one
        # document; naming is not identity.
        service, store, _emb, _vec = service_parts

        first = _ingest(service, filename="report.txt")
        second = _ingest(service, filename="report-final.txt")

        assert second.duplicate is True
        assert second.document_id == first.document_id
        assert len(store.list_documents(_ORG)) == 1

    def test_different_bytes_under_the_same_name_are_two_documents(self, service_parts):
        # The converse: a revised file reusing its name is genuinely new content.
        service, store, _emb, _vec = service_parts

        first = _ingest(service, data=b"Version one of the policy text.")
        second = _ingest(service, data=b"Version two of the policy text.")

        assert second.duplicate is False
        assert second.document_id != first.document_id
        assert len(store.list_documents(_ORG)) == 2


class TestTenantIsolation:
    def test_another_orgs_identical_file_is_not_a_duplicate(self, service_parts):
        # Each tenant's corpus is independent; one org's upload must never be
        # short-circuited by another org's document, which it cannot even read.
        service, store, _emb, _vec = service_parts

        mine = _ingest(service, org_id=_ORG)
        theirs = _ingest(service, org_id=_OTHER_ORG)

        assert theirs.duplicate is False
        assert theirs.document_id != mine.document_id
        assert len(store.list_documents(_ORG)) == 1
        assert len(store.list_documents(_OTHER_ORG)) == 1


class TestStoreLookup:
    def test_a_document_records_its_content_hash(self, service_parts):
        service, store, _emb, _vec = service_parts

        result = _ingest(service)
        document = store.get_document(_ORG, result.document_id)

        assert document is not None
        assert document.content_hash is not None
        # Hex SHA-256.
        assert len(document.content_hash) == 64

    def test_find_by_content_hash_misses_an_unknown_hash(self, service_parts):
        _service, store, _emb, _vec = service_parts

        assert store.find_by_content_hash(_ORG, "0" * 64) is None

    def test_a_pre_existing_document_without_a_hash_never_matches(self, service_parts):
        """Documents ingested before hashing carry NULL and cannot be backfilled.

        The raw bytes are not retained after extraction, so such a row is simply never
        matched — a re-upload creates one new, hashed document rather than failing.
        """
        service, store, _emb, _vec = service_parts
        store.persist(
            _ORG,
            Document(
                id=str(uuid.uuid4()),
                filename="legacy.txt",
                content_type="text/plain",
                size_bytes=len(_CONTENT),
                status="ingested",
                created_at=datetime.now(timezone.utc),
                content_hash=None,
            ),
            [],
        )

        result = _ingest(service)

        assert result.duplicate is False
        assert len(store.list_documents(_ORG)) == 2


def test_a_sink_without_the_lookup_still_ingests(service_parts):
    """The duplicate check is optional, so an older sink keeps working."""
    _service, _store, embeddings, vectors = service_parts

    class _MinimalSink:
        def __init__(self) -> None:
            self.persisted = 0

        def persist(self, org_id, document, chunks) -> None:  # noqa: ANN001
            self.persisted += 1

    sink = _MinimalSink()
    service = Ingestion_Service(
        chunker=Chunker(chunk_max_chars=200, chunk_overlap_chars=0),
        embedding_provider=embeddings,
        vector_store=vectors,
        sink=sink,
        max_document_bytes=1_000_000,
        extraction_timeout_seconds=10,
    )

    first = service.ingest("a.txt", "text/plain", _CONTENT, org_id=_ORG)
    second = service.ingest("a.txt", "text/plain", _CONTENT, org_id=_ORG)

    # No lookup available, so no duplicate is detected and both are ingested.
    assert first.duplicate is False
    assert second.duplicate is False
    assert sink.persisted == 2
