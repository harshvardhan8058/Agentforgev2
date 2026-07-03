"""RAG_Service: grounding + citation assembly.

Ties retrieval and generation together (design Flow 2):

1. Resolve ``k`` — the requested ``top_k`` (or ``top_k_default`` when absent) clamped
   into ``[top_k_min, top_k_max]`` (Req 12.1).
2. Retrieve the top-K chunks **before** any generation call (Req 12.1).
3. If **zero** chunks are retrieved, return a "no grounding information available"
   answer with an empty citation list and no fabricated content (Req 12.5).
4. Otherwise build a **grounding-only** prompt from the retrieved chunk texts (Req 12.4),
   call the active ``LLM_Provider``, and attach **exactly one Citation per used chunk**
   (Req 12.2, 12.3).

The logic is provider-agnostic: it runs identically against the ``Groq_Provider`` and
the ``Fallback_Provider`` (Req 12.6).
"""

from __future__ import annotations

from agentforge.llm.base import LLM_Provider
from agentforge.models.domain import Citation, Grounded_Answer
from agentforge.rag.prompt import build_prompt
from agentforge.retrieval.retriever import Retriever, clamp_k

# Fixed message used when nothing relevant is retrieved. It fabricates no source or
# content and includes no citation (Req 12.5).
NO_GROUNDING_MESSAGE = (
    "No grounding information is available to answer this question."
)


class RAG_Service:
    """Produces grounded, cited answers from retrieved chunks."""

    def __init__(
        self,
        retriever: Retriever,
        llm_provider: LLM_Provider,
        top_k_default: int,
        top_k_min: int = 1,
        top_k_max: int = 10,
    ) -> None:
        self._retriever = retriever
        self._llm = llm_provider
        self._top_k_default = top_k_default
        self._top_k_min = top_k_min
        self._top_k_max = top_k_max

    def resolve_k(self, top_k: int | None) -> int:
        """Resolve the effective retrieval count within ``[top_k_min, top_k_max]``."""
        requested = self._top_k_default if top_k is None else top_k
        return clamp_k(requested, self._top_k_min, self._top_k_max)

    def answer(self, query: str, top_k: int | None = None) -> Grounded_Answer:
        """Return a Grounded_Answer for ``query`` using at most K retrieved chunks."""
        k = self.resolve_k(top_k)

        # Retrieval always precedes generation (Req 12.1).
        retrieved = self._retriever.retrieve(query, k)

        # No grounding: do not call the LLM, do not fabricate, no citations (Req 12.5).
        if not retrieved:
            return Grounded_Answer(
                text=NO_GROUNDING_MESSAGE,
                citations=[],
                provider=self._llm.name,
                grounded=False,
            )

        # Grounding-only prompt built solely from the template, query, and chunk texts.
        prompt = build_prompt(query, [c.content for c in retrieved])
        result = self._llm.generate(prompt)

        # Exactly one Citation per used chunk, identifying its document + chunk id
        # (Req 12.2, 12.3). Every retrieved chunk contributes to the grounding prompt,
        # so every retrieved chunk is cited exactly once.
        citations = [
            Citation(document_id=c.document_id, chunk_id=c.chunk_id) for c in retrieved
        ]

        return Grounded_Answer(
            text=result.text,
            citations=citations,
            provider=result.provider,
            grounded=True,
        )
