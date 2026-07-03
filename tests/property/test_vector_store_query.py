"""Property-based tests for the Vector_Store (Chroma_Store) query contract.

Covers Property 7 (bound + ordering) and Property 8 (chunk association). Both run
against the in-memory Chroma_Store with synthetic embeddings — no model download.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.vectorstore.chroma_store import Chroma_Store

_DIM = 8

# A single finite float component.
_component = st.floats(
    min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
)


def _nonzero_vector(values: list[float]) -> list[float]:
    """Ensure a vector has non-zero norm so cosine distance is well-defined."""
    if all(v == 0.0 for v in values):
        values = list(values)
        values[0] = 1.0
    return values


_vector = st.lists(_component, min_size=_DIM, max_size=_DIM).map(_nonzero_vector)

# A populated store: 1..15 chunks, each with a document id drawn from a small set.
_records = st.lists(
    st.tuples(st.sampled_from(["docA", "docB", "docC"]), _vector),
    min_size=1,
    max_size=15,
)


def _build_store(records):
    store = Chroma_Store(dim=_DIM)
    stored = {}  # chunk_id -> document_id
    for i, (doc_id, vec) in enumerate(records):
        chunk_id = f"chunk-{i}"
        store.upsert(chunk_id=chunk_id, document_id=doc_id, embedding=vec)
        stored[chunk_id] = doc_id
    return store, stored


@hyp_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(records=_records, query=_vector, k=st.integers(min_value=0, max_value=20))
def test_vector_store_bound_and_ordering(records, query, k):
    """Feature: agentforge-foundation-rag, Property 7: For any populated Vector_Store,
    any query embedding, and any requested count K, the query returns exactly
    min(K, stored_count) matches ordered by non-increasing similarity.

    Validates: Requirements 10.5, 10.6
    """
    store, stored = _build_store(records)
    count = store.count()

    matches = store.query(query, k)

    # Bound: exactly min(K, stored_count) results (Req 10.5, 10.6).
    assert len(matches) == min(max(k, 0), count)

    # Ordering: non-increasing similarity score.
    scores = [m.score for m in matches]
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


@hyp_settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(records=_records, query=_vector, k=st.integers(min_value=1, max_value=20))
def test_stored_embedding_chunk_association(records, query, k):
    """Feature: agentforge-foundation-rag, Property 8: For any set of Chunks stored in
    the Vector_Store, every match returned by a query carries the Chunk identifier
    (and document identifier) under which it was stored, and no unknown identifier is
    ever returned.

    Validates: Requirements 10.4
    """
    store, stored = _build_store(records)

    matches = store.query(query, k)

    returned_ids = [m.chunk_id for m in matches]
    # No duplicate ids and every id is one that was stored.
    assert len(returned_ids) == len(set(returned_ids))
    for match in matches:
        assert match.chunk_id in stored
        # The document id must match the one it was stored under (Req 10.4).
        assert match.document_id == stored[match.chunk_id]
