"""Property-based test for Long_Term_Memory retrieval (Property 15).

Runs fully keyless against the in-memory ``Chroma_Store`` and the dependency-free
``DeterministicFakeEmbeddings`` double — no model download and no credentials. The
underlying Vector_Store's ordering guarantee is exercised separately; here we assert the
memory layer's top-K bound, empty-store behavior, and faithful order/payload mapping.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.memory.long_term import Long_Term_Memory
from agentforge.vectorstore.chroma_store import Chroma_Store
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


# Feature: agentforge-agentic-layer, Property 15: Long-term memory top-K bound and
# ordering.
@hyp_settings(
    max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
@given(
    texts=st.lists(st.text(min_size=1, max_size=30), max_size=12, unique=True),
    query=st.text(min_size=1, max_size=30),
    k=st.integers(min_value=0, max_value=20),
)
def test_long_term_top_k_bound_and_ordering(texts, query, k):
    """Feature: agentforge-agentic-layer, Property 15: For any set of stored
    Long_Term_Memory entries, any query, and any requested count K, retrieval returns
    exactly min(K, stored_count) entries ordered by non-increasing similarity, and returns
    an empty result when no entries have been stored.

    Validates: Requirements 7.2, 7.3, 7.4
    """
    embeddings = DeterministicFakeEmbeddings(dimension=_DIM)
    store = Chroma_Store(dim=_DIM)
    memory = Long_Term_Memory(embeddings, store)

    for i, text in enumerate(texts):
        memory.persist_long_term(text, {"conversation_id": f"c{i % 3}"})

    stored_count = len(texts)
    result = memory.retrieve_long_term(query, k)

    # Top-K bound: exactly min(K, stored_count) entries (and empty when none stored).
    assert len(result) == min(max(k, 0), stored_count)

    # Ordering + mapping: the memory layer preserves the Vector_Store's descending-
    # similarity order and maps each match to its stored text/metadata payload.
    if k > 0 and stored_count:
        expected = store.query(embeddings.embed_text(query), k)
        assert [e.id for e in result] == [m.chunk_id for m in expected]
    stored_texts = set(texts)
    for entry in result:
        assert entry.text in stored_texts
