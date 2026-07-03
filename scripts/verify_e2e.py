#!/usr/bin/env python
"""Documented end-to-end verification (Req 14.2, 14.4).

Ingests a sample document and prints the resulting ``Grounded_Answer`` — its text and
its citations — produced by the keyless ``Fallback_Provider``. It requires **no
credentials and no Docker**: it wires an in-memory document store, an in-process
``Chroma_Store``, and the ``Fallback_Provider`` through the same composition root the
application uses, so the exercised code path is identical to production wiring.

By default it uses the real local ``SentenceTransformer_Embeddings`` (free-tier, CPU,
no key). If that model cannot be loaded (e.g. no network to download it), or when run
with ``--fake-embeddings``, it transparently falls back to a small deterministic
in-script embedder so the check always completes offline.

Usage:
    python scripts/verify_e2e.py [--fake-embeddings]
"""

from __future__ import annotations

import argparse
import hashlib
import sys

from agentforge.config.container import build_app_context
from agentforge.config.settings import Settings
from agentforge.embeddings.base import Embedding_Provider
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.vectorstore.chroma_store import Chroma_Store

SAMPLE_DOCUMENT = (
    "AgentForge is an enterprise AI agent platform. Its Core RAG pipeline ingests "
    "documents, splits them into overlapping chunks, embeds those chunks, and stores "
    "the embeddings in a vector store. When a question is asked, AgentForge retrieves "
    "the most similar chunks and produces a grounded answer with a citation for every "
    "chunk it used. With no credentials configured, the deterministic Fallback_Provider "
    "generates the answer entirely offline."
)
SAMPLE_QUERY = "How does AgentForge produce grounded answers?"

_FAKE_DIM = 16


class _DeterministicEmbeddings(Embedding_Provider):
    """A tiny hash-seeded embedder so the check runs fully offline when needed."""

    def __init__(self, dimension: int = _FAKE_DIM) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_text(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self._dimension)]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


def _build_embeddings(use_fake: bool) -> Embedding_Provider:
    """Return the real local embedder, falling back to the deterministic one."""
    if use_fake:
        return _DeterministicEmbeddings()
    try:
        from agentforge.embeddings.sentence_transformer import (
            SentenceTransformer_Embeddings,
        )

        provider = SentenceTransformer_Embeddings()
        provider.embed_text("warm up")  # force model load now so we can fall back
        return provider
    except Exception as exc:  # noqa: BLE001 - any load failure -> offline fallback
        print(f"[verify_e2e] Local model unavailable ({exc}); using fake embedder.")
        return _DeterministicEmbeddings()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentForge end-to-end verification")
    parser.add_argument(
        "--fake-embeddings",
        action="store_true",
        help="Use a deterministic in-script embedder instead of the local model.",
    )
    args = parser.parse_args(argv)

    embeddings = _build_embeddings(args.fake_embeddings)

    # database_url / redis_url are placeholders: the injected in-memory store and Chroma
    # mean no external infrastructure is ever contacted.
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://placeholder/agentforge",
        redis_url="redis://placeholder:6379/0",
        embedding_dimension=embeddings.dimension,
    )

    ctx = build_app_context(
        settings,
        embedding_provider=embeddings,
        vector_store=Chroma_Store(dim=embeddings.dimension),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )

    print("[verify_e2e] Ingesting sample document...")
    result = ctx.ingestion_service.ingest(
        "sample.txt", "text/plain", SAMPLE_DOCUMENT.encode("utf-8")
    )
    print(
        f"[verify_e2e] Ingested document {result.document_id} "
        f"({result.chunk_count} chunk(s), status={result.status})."
    )

    print(f"[verify_e2e] Query: {SAMPLE_QUERY}")
    answer = ctx.rag_service.answer(SAMPLE_QUERY)

    print("\n===== Grounded Answer =====")
    print(f"provider : {answer.provider}")
    print(f"grounded : {answer.grounded}")
    print(f"answer   : {answer.text}")
    print("citations:")
    for citation in answer.citations:
        print(f"  - document={citation.document_id} chunk={citation.chunk_id}")
    print("===========================\n")

    # A successful verification is grounded and carries at least one citation.
    if not answer.grounded or not answer.citations:
        print("[verify_e2e] FAILED: expected a grounded answer with citations.")
        return 1

    print("[verify_e2e] OK: grounded answer with citations produced keyless.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
