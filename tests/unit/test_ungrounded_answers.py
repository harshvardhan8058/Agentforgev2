"""RAG_Service: the opt-in ungrounded (general-knowledge) no-grounding path.

By default, zero retrieved chunks must produce the fixed no-grounding message with no
LLM call at all (Req 12.5). A deployment may opt in to `allow_ungrounded`, which
answers that specific case from the model's general knowledge instead — but such an
answer must still be reported as ungrounded with zero citations, and must be built
from the separate general template so it can never be mistaken for a document-backed
answer.
"""

from __future__ import annotations

from uuid import uuid4

from agentforge.llm.base import GenerationResult, LLM_Provider
from agentforge.rag.prompt import GENERAL_PROMPT_HEADER, PROMPT_HEADER
from agentforge.rag.service import NO_GROUNDING_MESSAGE, RAG_Service
from agentforge.retrieval.retriever import RetrievedChunk


class RecordingProvider(LLM_Provider):
    """Captures every prompt it is asked to generate from."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "recording"

    def generate(self, prompt: str) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(text="generated answer", provider=self.name)


class StubRetriever:
    """Returns a fixed chunk list regardless of query."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    def retrieve(self, query, k, *, org_id=None):  # noqa: ANN001, ARG002
        return self._chunks


def _service(chunks: list[RetrievedChunk], *, allow_ungrounded: bool):
    provider = RecordingProvider()
    service = RAG_Service(
        retriever=StubRetriever(chunks),
        llm_provider=provider,
        top_k_default=4,
        allow_ungrounded=allow_ungrounded,
    )
    return service, provider


def test_default_refuses_and_never_calls_the_llm() -> None:
    service, provider = _service([], allow_ungrounded=False)

    answer = service.answer("who won the 1998 world cup", org_id=uuid4())

    assert answer.text == NO_GROUNDING_MESSAGE
    assert answer.grounded is False
    assert answer.citations == []
    # The safe default must not spend a model call at all.
    assert provider.prompts == []


def test_opt_in_answers_from_general_knowledge_but_stays_ungrounded() -> None:
    service, provider = _service([], allow_ungrounded=True)

    answer = service.answer("who won the 1998 world cup", org_id=uuid4())

    assert answer.text == "generated answer"
    # Crucially: still ungrounded, still zero citations.
    assert answer.grounded is False
    assert answer.citations == []

    # Built from the general template, never the grounding-only one.
    assert len(provider.prompts) == 1
    assert provider.prompts[0].startswith(GENERAL_PROMPT_HEADER)
    assert PROMPT_HEADER not in provider.prompts[0]
    assert "Context:" not in provider.prompts[0]


def test_opt_in_does_not_affect_the_grounded_path() -> None:
    chunk = RetrievedChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        content="The stipend is 25000 per month.",
        score=0.9,
    )
    service, provider = _service([chunk], allow_ungrounded=True)

    answer = service.answer("what is the stipend", org_id=uuid4())

    # Retrieval succeeded, so the grounded, cited path is used unchanged.
    assert answer.grounded is True
    assert len(answer.citations) == 1
    assert answer.citations[0].chunk_id == chunk.chunk_id
    assert provider.prompts[0].startswith(PROMPT_HEADER)
    assert chunk.content in provider.prompts[0]
