# Architectural Decision Record — AgentForge Phases 1–2

This document records the rationale for the major architectural decisions in the
Foundation (Phase 1) and Core RAG (Phase 2) of AgentForge, per Requirement 14.3. It
mirrors the "Design Decisions & Why" section of the design document so the reasoning is
discoverable from the repository itself.

## 1. Interfaces at exactly three seams (LLM, Embedding, Vector store)

These are the parts most likely to change as the platform grows or as cost/quality
trade-offs shift. Abstracting **only** these three seams — `LLM_Provider`,
`Embedding_Provider`, and `Vector_Store` — keeps the design simple while guaranteeing
that later phases can swap providers without touching the RAG pipeline. The service
layer depends only on the abstract contracts (`*/base.py`); concrete implementations are
referenced solely by the composition root (`config/container.py`).

_Validates: Requirements 1.2, 11.6._

## 2. Fallback_Provider as the default LLM

The platform owner's guiding constraint is that the system must run and be verifiable
locally **before** any agentic capability is added. A deterministic, network-free
`Fallback_Provider` makes the whole system — and its entire test suite — runnable with
zero credentials. Its determinism also makes it ideal for property-based tests, since
identical inputs always yield identical output.

_Validates: Requirements 11.3, 11.4, 13.3, 14.4._

## 3. Local sentence-transformers embeddings by default (`all-MiniLM-L6-v2`, 384-dim)

The default embedder is free, CPU-friendly, and good enough for retrieval quality in
development. Critically, the pgvector column is sized to the **configured** embedding
dimension, so upgrading to a hosted embedder later is a configuration + migration
change, not a code change. The model loads lazily on first use so importing and
constructing the provider stays cheap and side-effect free.

_Validates: Requirements 4.3, 9.1, 14.4._

## 4. Two profiles (Chroma local / pgvector production), one code path

Chroma removes infrastructure friction for local development, while pgvector
consolidates relational and vector data in one production database. Because both sit
behind the `Vector_Store` interface, the calling code is identical across profiles; the
composition root selects the implementation from the active profile.

_Validates: Requirements 10.1, 10.2, 10.3._

## 5. Credentials always optional; only non-secret settings are required

This makes the system "secure and runnable by default": nothing sensitive is ever
required to boot, and no secret is committed or logged. Credentials are typed as
`SecretStr` so pydantic redacts them from `repr`, `str`, `model_dump`, and logging
output. Required non-secret settings (`database_url`, `redis_url`) are validated at
startup, and a missing one aborts boot while naming the offending key.

_Validates: Requirements 3.2, 3.4, 3.6._

## 6. Character-based chunker with recorded per-boundary overlap

Storing the exact overlap used at each boundary makes the round-trip reconstruction
property unambiguous, even when the final chunk is shorter than the configured overlap —
a subtle case that a naive "subtract a constant overlap" approach gets wrong.
Concatenating the chunks in order while removing the recorded overlap reconstructs the
original chunker-input text exactly.

_Validates: Requirements 8.5, 13.4._

## 7. Markdown: strip by default, preserve optionally

**Decision:** normalize Markdown to plain text before chunking by default
(`markdown_mode=strip`).

**Why:** Markdown markup (`#`, `*`, link syntax, tables) adds tokens that dilute
embedding quality and can fragment semantically related text, so stripping generally
improves retrieval relevance.

**Trade-off:** structure that carries meaning (headings as section labels, code fences)
is lost, and the round-trip property is then defined against the normalized text rather
than the raw bytes. For documents where structure matters, `markdown_mode=preserve`
keeps the raw Markdown and the round-trip holds against the raw input. Making this a
configurable switch lets the platform owner experiment and learn the trade-off directly
rather than baking in one answer.

_Validates: Requirement 8 (chunking), configurable per deployment._

## 8. Grounding-only prompt construction

Building the prompt exclusively from the retrieved chunks (plus a fixed template and the
query) is what makes answers trustworthy and citations verifiable. No content from
outside the retrieved chunks is ever introduced. This is enforced as a correctness
property (Property 11) rather than left to convention.

_Validates: Requirement 12.4._

## 9. Atomic ingestion

The ingestion pipeline commits relational records and vector writes **only after** the
full extract → chunk → embed → store pipeline succeeds. Embeddings are generated before
any store write, and a late write failure rolls back the vector writes. This guarantees
the "persist no Chunks on rejection" requirements and prevents orphaned embeddings.

_Validates: Requirements 7.4–7.6, 9.4._

---

_Scope note:_ this record intentionally covers only Phase 1 (Foundation) and Phase 2
(Core RAG). The agentic layer, multi-agent orchestration, enterprise auth/RBAC,
observability, frontend, integrations, and cloud deployment are reserved for later
phases and are enabled — but not designed — by the modular seams established here.
