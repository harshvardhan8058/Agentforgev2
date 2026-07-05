"""Property-based tests for the RAG_Service (Properties 9, 10, 12).

These run keyless with lightweight spies for the Retriever and LLM_Provider so the
grounding/citation logic is exercised in isolation — no model download, no vector
store, and no network.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.llm.base import GenerationResult, LLM_Provider
from agentforge.rag.service import NO_GROUNDING_MESSAGE, RAG_Service
from agentforge.retrieval.retriever import RetrievedChunk

_TOP_K_DEFAULT = 4
_TOP_K_MIN = 1
_TOP_K_MAX = 10


class _SpyRetriever:
    """Records the K it is asked for and returns a preset chunk list."""

    def __init__(self, chunks, events):
        self._chunks = chunks
        self.events = events
        self.last_k = None

    def retrieve(self, query, k, *, org_id=None):
        self.last_k = k
        self.events.append(("retrieve", k))
        return list(self._chunks)


class _SpyLLM(LLM_Provider):
    """Records generation calls so ordering and invocation can be asserted."""

    def __init__(self, events):
        self.events = events

    @property
    def name(self) -> str:
        return "spy"

    def generate(self, prompt: str) -> GenerationResult:
        self.events.append(("generate", prompt))
        return GenerationResult(text="ANSWER", provider="spy")


def _make_service(chunks, events):
    retriever = _SpyRetriever(chunks, events)
    service = RAG_Service(
        retriever=retriever,
        llm_provider=_SpyLLM(events),
        top_k_default=_TOP_K_DEFAULT,
        top_k_min=_TOP_K_MIN,
        top_k_max=_TOP_K_MAX,
    )
    return service, retriever


# A set of distinct retrieved chunks (unique chunk ids), 1..12 of them.
@st.composite
def _retrieved_chunks(draw):
    n = draw(st.integers(min_value=1, max_value=12))
    chunks = []
    for i in range(n):
        doc = draw(st.sampled_from(["docA", "docB", "docC"]))
        chunks.append(
            RetrievedChunk(
                chunk_id=f"chunk-{i}",
                document_id=doc,
                content=draw(st.text(min_size=0, max_size=60)),
                score=1.0 - i * 0.01,
            )
        )
    return chunks


# top_k values that exercise below-1, in-range, above-10, and absent (None).
_top_k_values = st.one_of(
    st.none(),
    st.integers(min_value=-20, max_value=30),
)


@hyp_settings(max_examples=100, deadline=None)
@given(chunks=_retrieved_chunks(), top_k=_top_k_values, query=st.text(max_size=40))
def test_top_k_clamped_and_retrieval_before_generation(chunks, top_k, query):
    """Feature: agentforge-foundation-rag, Property 9: For any requested top_k value
    (including values below 1, above 10, or absent), the effective retrieval count used
    by the RAG_Service lies within [1, 10], and retrieval is performed before any
    generation call.

    Validates: Requirements 12.1
    """
    events: list = []
    service, retriever = _make_service(chunks, events)

    service.answer(query, top_k)

    # Effective retrieval count is clamped into [1, 10].
    assert retriever.last_k is not None
    assert _TOP_K_MIN <= retriever.last_k <= _TOP_K_MAX

    # Retrieval happens before any generation call.
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "retrieve"
    if "generate" in kinds:
        assert kinds.index("retrieve") < kinds.index("generate")


@hyp_settings(max_examples=100, deadline=None)
@given(chunks=_retrieved_chunks(), query=st.text(max_size=40))
def test_one_citation_per_used_chunk(chunks, query):
    """Feature: agentforge-foundation-rag, Property 10: For any non-empty set of
    retrieved Chunks, the Grounded_Answer contains exactly one Citation per retrieved
    Chunk used, and each Citation identifies a document identifier and Chunk identifier
    drawn from the retrieved set (no duplicates, no invented ids).

    Validates: Requirements 12.2, 12.3
    """
    events: list = []
    service, _ = _make_service(chunks, events)

    answer = service.answer(query, None)

    assert answer.grounded is True
    # Exactly one citation per retrieved chunk.
    assert len(answer.citations) == len(chunks)

    retrieved_pairs = {(c.document_id, c.chunk_id) for c in chunks}
    cited_pairs = [(c.document_id, c.chunk_id) for c in answer.citations]

    # No duplicate citations.
    assert len(cited_pairs) == len(set(cited_pairs))
    # Every citation is drawn from the retrieved set (no invented ids).
    for pair in cited_pairs:
        assert pair in retrieved_pairs
    # Every retrieved chunk is cited exactly once.
    assert set(cited_pairs) == retrieved_pairs


@hyp_settings(max_examples=100, deadline=None)
@given(query=st.text(max_size=60))
def test_empty_retrieval_yields_no_fabricated_answer(query):
    """Feature: agentforge-foundation-rag, Property 12: For any query for which the
    Retriever returns zero Chunks, the RAG_Service responds that no grounding
    information is available, includes no Citation, and produces no fabricated source
    or content.

    Validates: Requirements 12.5
    """
    events: list = []
    service, _ = _make_service([], events)

    answer = service.answer(query, None)

    assert answer.grounded is False
    assert answer.citations == []
    # The fixed no-grounding message, with no fabricated content appended.
    assert answer.text == NO_GROUNDING_MESSAGE
    # The LLM is never called when there is nothing to ground on.
    assert all(kind != "generate" for kind, _ in events)
