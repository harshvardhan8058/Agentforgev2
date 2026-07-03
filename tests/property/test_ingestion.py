"""Property-based tests for the Ingestion_Service (Properties 4, 5).

These run keyless with a deterministic fake embedder, an in-memory Chroma store, and an
in-memory sink — no model download and no database.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.chunking.chunker import Chunker
from agentforge.ingestion.extractors import (
    CONTENT_TYPE_TEXT,
    SUPPORTED_CONTENT_TYPES,
)
from agentforge.ingestion.service import (
    EmptyDocumentError,
    Ingestion_Service,
    UnsupportedFormatError,
)
from agentforge.vectorstore.chroma_store import Chroma_Store
from tests.fakes import DeterministicFakeEmbeddings, InMemorySink

_MAX_BYTES = 50 * 1024 * 1024
_TIMEOUT = 30


def _build_service():
    sink = InMemorySink()
    store = Chroma_Store(dim=8)
    service = Ingestion_Service(
        chunker=Chunker(chunk_max_chars=40, chunk_overlap_chars=8, markdown_mode="preserve"),
        embedding_provider=DeterministicFakeEmbeddings(dimension=8),
        vector_store=store,
        sink=sink,
        max_document_bytes=_MAX_BYTES,
        extraction_timeout_seconds=_TIMEOUT,
        markdown_mode="preserve",
    )
    return service, sink, store


# Non-empty text: at least one non-whitespace character so it isn't rejected as empty.
_nonempty_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
    min_size=1,
    max_size=300,
).filter(lambda s: s.strip() != "")


@hyp_settings(max_examples=100, deadline=None)
@given(text=_nonempty_text)
def test_chunk_document_reference_invariant(text):
    """Feature: agentforge-foundation-rag, Property 4: For any ingested document, every
    Chunk produced by the Chunker and every persisted Chunk record references that
    document's identifier, and the number of persisted Chunks equals the number
    produced.

    Validates: Requirements 7.3, 8.3
    """
    service, sink, store = _build_service()
    data = text.encode("utf-8")

    result = service.ingest("doc.txt", CONTENT_TYPE_TEXT, data)

    # Expected chunk count is deterministic for the same text + chunker config.
    expected = Chunker(40, 8, markdown_mode="preserve").chunk(text, result.document_id)

    persisted = sink.chunks[result.document_id]
    assert len(persisted) == len(expected)
    assert result.chunk_count == len(expected)
    # Every persisted chunk references the ingested document.
    for chunk in persisted:
        assert chunk.document_id == result.document_id
    # Vector store holds exactly one embedding per persisted chunk.
    assert store.count() == len(persisted)


@st.composite
def _invalid_submissions(draw):
    """Draw an invalid submission: empty/whitespace text, zero bytes, or bad format."""
    kind = draw(st.sampled_from(["empty_text", "zero_bytes", "unsupported"]))
    if kind == "empty_text":
        ws = draw(st.text(alphabet=" \t\n\r", min_size=0, max_size=20))
        return CONTENT_TYPE_TEXT, ws.encode("utf-8"), EmptyDocumentError
    if kind == "zero_bytes":
        ct = draw(st.sampled_from(sorted(SUPPORTED_CONTENT_TYPES)))
        return ct, b"", EmptyDocumentError
    # unsupported content type
    bad_ct = draw(
        st.sampled_from(["application/json", "image/png", "text/html", "application/zip"])
    )
    payload = draw(st.binary(min_size=0, max_size=50))
    return bad_ct, payload, UnsupportedFormatError


@hyp_settings(max_examples=100, deadline=None)
@given(submission=_invalid_submissions())
def test_ingestion_rejects_invalid_inputs_with_no_persisted_chunks(submission):
    """Feature: agentforge-foundation-rag, Property 5: For any submission that has no
    recoverable text or whose content type is outside the supported set, the
    Ingestion_Service rejects the submission with the corresponding error and persists
    zero Chunks for that document.

    Validates: Requirements 7.4, 7.5
    """
    content_type, data, expected_error = submission
    service, sink, store = _build_service()

    try:
        service.ingest("doc", content_type, data)
        raised = None
    except Exception as exc:  # noqa: BLE001 - we assert the exact type below
        raised = exc

    assert isinstance(raised, expected_error)
    # No chunks persisted and no vectors stored (atomic rejection).
    assert sink.total_chunks() == 0
    assert store.count() == 0
