# Implementation Plan: AgentForge Foundation & Core RAG (Phases 1–2)

## Overview

This plan converts the design into an incremental, test-driven coding sequence that
respects the platform owner's ordering constraint: **build Phase 1 (Foundation) to a
locally runnable state first, verify it with a readiness check, then build Phase 2
(Core RAG)**. Every step builds on the previous ones and ends by wiring components
together — no orphaned code.

Language: **Python** (as specified by the design: FastAPI, Pydantic, SQLAlchemy async,
sentence-transformers, Chroma, pgvector, Hypothesis).

Ordering strategy:
- **Phase 1** — scaffolding → config → domain models → database + migrations → FastAPI
  skeleton + error envelope + health → Docker Compose. Ends at a **verifiable
  checkpoint** (readiness returns 200 locally).
- **Phase 2** — interfaces first (`Embedding_Provider`, `Vector_Store`, `LLM_Provider`)
  → keyless local defaults (`Fallback_Provider`, `SentenceTransformer_Embeddings`,
  `Chroma_Store`) → chunking → ingestion → composition root/provider selection →
  retrieval + `RAG_Service` (grounding/citations) → production providers (`Groq_Provider`,
  `Pgvector_Store`) → API endpoint wiring → documentation + end-to-end verification.

Property-based tests (Hypothesis) implement the 14 correctness properties from the
design and run **keyless** via the `Fallback_Provider` and `SentenceTransformer_Embeddings`.

Sub-tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.

## Tasks

- [ ] 1. Project scaffolding and foundation configuration
  - [ ] 1.1 Create repository layout and pinned dependency manifest
    - Create the module tree exactly as in the design's "Repository / Module Layout"
      under `src/agentforge/` (`main.py`, `config/`, `api/`, `api/routers/`, `ingestion/`,
      `chunking/`, `embeddings/`, `vectorstore/`, `llm/`, `retrieval/`, `rag/`, `db/`,
      `models/`) plus top-level `migrations/`, `scripts/`, `docs/`, and `tests/unit/` +
      `tests/property/`, each with the empty modules/`__init__.py` referenced by the design
    - Add `pyproject.toml` as the dependency manifest with **pinned versions** for
      fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, asyncpg, psycopg,
      pgvector, chromadb, sentence-transformers, redis, pypdf, markdown, hypothesis,
      pytest, and httpx; configure the documented `pytest` test command (Req 13.2)
    - Add `.env.example` enumerating every setting name from `Settings` with placeholder
      values and no real credentials (Req 3.5)
    - _Requirements: 1.1, 1.3, 3.5, 13.2_

  - [ ] 1.2 Implement domain models
    - Implement `models/domain.py` with `Document`, `Chunk`, `Embedding`, `Citation`,
      and `Grounded_Answer` dataclasses exactly as specified in the "Domain Models"
      section (including `Chunk.overlap_prev` and `Grounded_Answer.grounded`)
    - _Requirements: 1.1_

  - [ ] 1.3 Implement Configuration_Manager
    - Implement `config/settings.py` `Settings` (pydantic-settings `BaseSettings`) loading
      all values from environment variables, with the profile/chunking/embedding/
      retrieval/ingestion-limit fields and defaults from the design
    - Treat every credential (`groq_api_key`, `hosted_embedding_api_key`) as optional
      `SecretStr`; validate required non-secret settings (`database_url`, `redis_url`) at
      startup and abort naming the missing key; expose `embedding_dimension`,
      `active_llm()`, and `active_vector_store()`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 4.5, 9.2_

  - [ ]* 1.4 Write unit tests for configuration loading and validation
    - Cover env loading, required-setting validation, missing-setting abort with the
      offending name, and optional-credential behavior
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.5_

  - [ ]* 1.5 Write property test for secret non-exposure
    - **Property 14: Secret values are never exposed**
    - **Validates: Requirements 3.6**

- [ ] 2. Database engine, repositories, and schema migrations
  - [ ] 2.1 Implement async DB engine and repositories
    - Implement `db/engine.py` (async engine/session from `database_url`) and
      `db/repositories.py` for `documents` and `chunks` persistence (associating each
      chunk with its `document_id`)
    - _Requirements: 4.5, 7.3_

  - [ ] 2.2 Implement SQL migrations and migration runner
    - Add `migrations/0001_enable_pgvector.sql` and `migrations/0002_create_core_tables.sql`
      per the design schema; template the `chunk_embeddings.embedding vector(N)` column to
      the configured `embedding_dimension`; add the HNSW index
    - Implement a migration runner that applies migrations on first startup, halts on
      failure, and reports the failing migration identifier
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 2.3 Write integration test for pgvector extension and migrations
    - Verify the extension is enabled, tables are created, and the vector column matches
      the configured dimension; verify a forced migration failure reports its id
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 3. FastAPI skeleton, error handling, and health checks
  - [ ] 3.2 Implement error envelope and exception handlers
    - Implement `api/errors.py` with the uniform `{ "error": { code, message, details } }`
      envelope, a catch-all handler returning HTTP 500 without leaking stack traces, and
      a 404 handler for unknown routes
    - _Requirements: 2.2, 2.5_

  - [ ] 3.3 Implement typed request/response schemas
    - Implement `api/schemas.py` Pydantic models for ingest, query, documents, and health
      responses used by every endpoint
    - _Requirements: 2.3_

  - [ ] 3.4 Implement health endpoints
    - Implement `api/routers/health.py`: `GET /health/live` (always 200, no dependency
      checks) and `GET /health/ready` (checks Database + Redis connectivity, 200 when all
      up, 503 listing each unavailable dependency)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ] 3.1 Implement FastAPI app factory and router registration
    - Implement `src/agentforge/main.py` app factory with lifespan startup (config load +
      migration run), exception-handler registration from `api/errors.py`, and health
      router registration so all routes are registered before serving
    - _Requirements: 2.1, 2.4_

  - [ ]* 3.5 Write unit tests for 404 and 500 error envelope
    - Assert unknown routes return 404 and forced unhandled exceptions return the 500
      structured envelope with no stack trace
    - _Requirements: 2.2, 2.5_

  - [ ]* 3.6 Write unit tests for health endpoints
    - Assert liveness 200; readiness 200 when deps up and 503 listing unavailable deps
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 4. Docker-based local development environment
  - [ ] 4.1 Create Dockerfile and Docker Compose stack
    - Add the API `Dockerfile` and `docker-compose.yml` defining `api`, `postgres`
      (pgvector image), and `redis` services, wired to `Configuration_Manager` settings,
      exposing the documented local API port and reporting a failed service by name
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 4.2 Write README with local install/configure/run instructions
    - Document dependency install, `.env` setup, the single `docker compose up` command,
      the local port, and the test command
    - _Requirements: 1.4_

  - [ ]* 4.3 Write integration test for Compose startup and reachability
    - Verify services start and the API becomes reachable within the documented window
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 14.1_

- [ ] 5. Checkpoint — Foundation is locally runnable
  - Bring up the stack and confirm `GET /health/ready` returns HTTP 200 locally, all
    Phase 1 tests pass, and the app boots with zero credentials. Ensure all tests pass,
    ask the user if questions arise.

- [ ] 6. Define pluggable interfaces (Phase 2 seams)
  - [ ] 6.1 Define the Embedding_Provider interface
    - Implement `embeddings/base.py` abstract `Embedding_Provider` with `dimension`,
      `embed_text`, and `embed_batch`, plus an `EmbeddingError`
    - _Requirements: 1.2, 9.1_

  - [ ] 6.2 Define the Vector_Store interface
    - Implement `vectorstore/base.py` abstract `Vector_Store` (`upsert`, `query`,
      `delete_document`, `count`) and the `StoredMatch` dataclass
    - _Requirements: 1.2, 10.1_

  - [ ] 6.3 Define the LLM_Provider interface
    - Implement `llm/base.py` abstract `LLM_Provider` with `name` and `generate`, the
      `GenerationResult` dataclass, and an `LLMProviderError`
    - _Requirements: 1.2, 11.1_

  - [ ]* 6.4 Write smoke tests asserting interfaces are abstract
    - Assert each base class cannot be instantiated and defines the required abstract
      methods
    - _Requirements: 1.2, 10.1, 11.1_

- [ ] 7. Implement keyless local default providers
  - [ ] 7.1 Implement the Fallback_Provider
    - Implement `llm/fallback_provider.py` producing a deterministic answer assembled
      purely from the retrieved chunks with no external call
    - _Requirements: 11.3, 11.4_

  - [ ]* 7.2 Write property test for fallback determinism and grounding
    - **Property 13: Fallback generation is deterministic and grounded**
    - **Validates: Requirements 11.4, 12.6**

  - [ ] 7.3 Implement SentenceTransformer_Embeddings (default local embeddings)
    - Implement `embeddings/sentence_transformer.py` wrapping
      `sentence-transformers/all-MiniLM-L6-v2` (`dimension == 384`), running on CPU with
      no key; raise `EmbeddingError` on failure without storing a partial embedding
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 14.4_

  - [ ]* 7.4 Write property test for embedding dimension stability
    - **Property 6: Embedding dimension is fixed and stable**
    - **Validates: Requirements 9.1, 9.3**

  - [ ]* 7.5 Write unit test for embedding generation failure
    - Assert failure raises `EmbeddingError` and stores no partial embedding
    - _Requirements: 9.4_

  - [ ] 7.6 Implement the Chroma_Store (local vector store)
    - Implement `vectorstore/chroma_store.py` over an embedded Chroma collection,
      associating each embedding with its chunk/document id and honoring the `query`
      bound/ordering post-conditions
    - _Requirements: 10.2, 10.4, 10.5, 10.6_

  - [ ]* 7.7 Write property test for vector store bound and ordering
    - **Property 7: Vector store bound and ordering**
    - **Validates: Requirements 10.5, 10.6**

  - [ ]* 7.8 Write property test for stored-embedding chunk association
    - **Property 8: Stored embedding is associated with its originating Chunk**
    - **Validates: Requirements 10.4**

- [ ] 8. Implement text chunking
  - [ ] 8.1 Implement the Chunker
    - Implement `chunking/chunker.py` as a character-based sliding-window chunker with
      configurable `chunk_max_chars` and `chunk_overlap_chars`, recording per-boundary
      `overlap_prev`, preserving `document_id` and ordinal `index`, and producing exactly
      one chunk when input length <= `chunk_max_chars`; support `markdown_mode`
      strip/preserve normalization of the input text
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 8.2 Write property test for chunk maximum-size invariant
    - **Property 1: Chunk maximum-size invariant**
    - **Validates: Requirements 8.1, 8.4**

  - [ ]* 8.3 Write property test for chunk overlap invariant
    - **Property 2: Chunk overlap invariant**
    - **Validates: Requirements 8.2**

  - [ ]* 8.4 Write property test for chunk round-trip reconstruction
    - **Property 3: Chunk round-trip reconstruction**
    - **Validates: Requirements 8.5, 13.4**

- [ ] 9. Implement document ingestion
  - [ ] 9.1 Implement text extractors
    - Implement `ingestion/extractors.py` for plain text, PDF, and Markdown extraction
      with the 30-second extraction budget and `markdown_mode` handling
    - _Requirements: 7.1, 7.2_

  - [ ] 9.2 Implement the Ingestion_Service orchestration
    - Implement `ingestion/service.py` orchestrating validate → extract → chunk → embed →
      store vectors → persist document + chunk records; enforce 50 MB size limit and
      text/PDF/Markdown allow-list; reject empty/unsupported/corrupt/oversized/timed-out
      inputs; commit atomically so rejections persist no chunks
    - _Requirements: 7.1, 7.3, 7.4, 7.5, 7.6, 7.7, 9.4_

  - [ ]* 9.3 Write property test for chunk–document reference invariant
    - **Property 4: Chunk–document reference invariant**
    - **Validates: Requirements 7.3, 8.3**

  - [ ]* 9.4 Write property test for rejection of invalid inputs
    - **Property 5: Ingestion rejects invalid inputs with no persisted Chunks**
    - **Validates: Requirements 7.4, 7.5**

  - [ ]* 9.5 Write unit tests for extraction failure, size, and timeout errors
    - Assert corrupt-file extraction failure, >50 MB size-limit rejection, and extraction
      timeout each report the correct error and persist no chunks
    - _Requirements: 7.6, 7.7, 7.1_

- [ ] 10. Implement composition root and provider selection
  - [ ] 10.1 Implement the container/composition root
    - Implement `config/container.py` `build_llm_provider`, `build_embedding_provider`,
      and `build_vector_store` selecting implementations by credential presence and
      profile (fallback + sentence-transformer + Chroma by default), never requiring a key
    - _Requirements: 10.2, 10.3, 11.2, 11.3, 11.6_

  - [ ]* 10.2 Write unit tests for provider-selection logic
    - Assert local vs production and key-present vs keyless selection, and that a new
      LLM_Provider can be registered without changing the RAG_Service
    - _Requirements: 10.2, 10.3, 11.2, 11.3, 11.6_

- [ ] 11. Implement retrieval and grounded RAG
  - [ ] 11.1 Implement the Retriever
    - Implement `retrieval/retriever.py` embedding the query, calling
      `Vector_Store.query(vec, k)` with `k` clamped to `[1, 10]`, and loading matched
      chunk text from the DB; never return more than `k` matches
    - _Requirements: 10.5, 12.1_

  - [ ] 11.2 Implement grounding-only prompt construction
    - Implement `rag/prompt.py` building the prompt from only a fixed template, the query,
      and retrieved chunk text
    - _Requirements: 12.4_

  - [ ] 11.3 Implement the RAG_Service
    - Implement `rag/service.py` resolving `k` (clamped, default `top_k_default`),
      retrieving top-K chunks, returning a no-grounding answer with empty citations when
      none are found, otherwise building the grounding-only prompt, calling the active
      `LLM_Provider`, and attaching exactly one citation per used chunk — identical logic
      for Groq and fallback providers
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ]* 11.4 Write property test for top-K clamping
    - **Property 9: Top-K is clamped into the valid range**
    - **Validates: Requirements 12.1**

  - [ ]* 11.5 Write property test for one citation per used chunk
    - **Property 10: One valid Citation per used Chunk**
    - **Validates: Requirements 12.2, 12.3**

  - [ ]* 11.6 Write property test for grounding-only prompt construction
    - **Property 11: Grounding-only prompt construction**
    - **Validates: Requirements 12.4**

  - [ ]* 11.7 Write property test for empty-retrieval no-fabrication behavior
    - **Property 12: Empty retrieval yields no fabricated answer**
    - **Validates: Requirements 12.5**

- [ ] 12. Implement production providers
  - [ ] 12.1 Implement the Groq_Provider
    - Implement `llm/groq_provider.py` active only when `groq_api_key` is set; on API
      failure raise `LLMProviderError` identifying the provider
    - _Requirements: 11.2, 11.5_

  - [ ]* 12.2 Write unit test for Groq failure handling
    - With a mocked failing Groq call, assert an `llm_provider_error` identifying the
      provider (no live network call)
    - _Requirements: 11.5_

  - [ ] 12.3 Implement the Pgvector_Store
    - Implement `vectorstore/pgvector_store.py` using pgvector distance operators on
      `chunk_embeddings`, associating each embedding with its chunk/document id and
      honoring the `query` bound/ordering post-conditions
    - _Requirements: 10.3, 10.4, 10.5, 10.6_

  - [ ]* 12.4 Write integration test for Pgvector_Store ordering and bounds
    - Assert descending-similarity ordering and `min(K, count)` result size
    - _Requirements: 10.3, 10.5, 10.6_

- [ ] 13. Wire the API endpoints
  - [ ] 13.1 Implement the ingest router
    - Implement `api/routers/ingest.py` `POST /documents` (multipart) calling the
      Ingestion_Service, returning 201 on success and the mapped 400/415/422/413 error
      codes on rejection
    - _Requirements: 2.3, 7.4, 7.5, 7.6, 7.7_

  - [ ] 13.2 Implement the query router
    - Implement `api/routers/query.py` `POST /query` calling the RAG_Service, returning
      the grounded answer with citations, the no-context 200 case, and 502
      `llm_provider_error` on Groq failure
    - _Requirements: 2.3, 12.1, 12.2, 12.5, 11.5_

  - [ ] 13.3 Implement the documents router
    - Implement `api/routers/documents.py` `GET /documents` (list) and
      `DELETE /documents/{id}` (cascade delete relational + vector-store entries; 404 on
      unknown id)
    - _Requirements: 2.3_

  - [ ] 13.4 Register Phase 2 routers in the app factory
    - Update `src/agentforge/main.py` to register the ingest, query, and documents routers
      (wired through the composition root) so all routes are registered before serving
    - _Requirements: 2.1, 2.4_

  - [ ]* 13.5 Write integration tests for the API endpoints (keyless)
    - Exercise ingest → query → list → delete end to end via the app using the
      Fallback_Provider and SentenceTransformer_Embeddings
    - _Requirements: 2.3, 13.1, 13.2, 13.3_

- [ ] 14. Documentation and end-to-end verification
  - [ ] 14.1 Write the architectural decision record
    - Create `docs/decisions.md` capturing the rationale from the design's "Design
      Decisions & Why" (seams, fallback default, local embeddings, two profiles, optional
      credentials, chunker overlap, Markdown strip/preserve, grounding-only prompt, atomic
      ingestion)
    - _Requirements: 14.3_

  - [ ] 14.2 Implement the end-to-end verification script
    - Implement `scripts/verify_e2e.py` that ingests a sample document and returns a
      Grounded_Answer using the Fallback_Provider (no credentials required)
    - _Requirements: 14.2, 14.4_

  - [ ]* 14.3 Write integration test for the documented end-to-end flow
    - Assert the readiness check passes and the ingest→answer flow returns a grounded,
      cited answer keyless
    - _Requirements: 14.1, 14.2_

- [ ] 15. Final checkpoint — full keyless suite green
  - Run the complete unit, property, and integration suite with no external LLM
    credential and confirm all 14 property tests pass. Ensure all tests pass, ask the
    user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP;
  all non-`*` sub-tasks are core implementation and must be built.
- Each task references the specific requirement clauses it implements for traceability,
  and each property test names the exact design property and the requirements it validates.
- The 14 property-based tests are implemented with Hypothesis (min. 100 iterations each,
  one test per property) and run keyless via the Fallback_Provider and
  SentenceTransformer_Embeddings, satisfying Req 13.1–13.4 and 14.4.
- Ordering enforces early runnability: Phase 1 completes and is verified at the Task 5
  checkpoint (readiness 200 locally) before any Phase 2 work begins; Phase 2 builds
  interfaces before implementations and keyless defaults before hosted providers.
- Scope is strictly Phases 1–2: no agentic layer, multi-agent orchestration, auth/RBAC,
  observability, frontend, integrations, or deployment tasks are included.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5", "2.1", "2.2", "3.2", "3.3"] },
    { "id": 3, "tasks": ["2.3", "3.4", "4.1", "4.2"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.5", "3.6", "4.3"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 7, "tasks": ["6.4", "7.1", "7.3", "7.6", "8.1", "9.1"] },
    { "id": 8, "tasks": ["7.2", "7.4", "7.5", "7.7", "7.8", "8.2", "8.3", "8.4", "9.2", "10.1"] },
    { "id": 9, "tasks": ["9.3", "9.4", "9.5", "10.2", "11.1", "11.2"] },
    { "id": 10, "tasks": ["11.3", "12.1", "12.3"] },
    { "id": 11, "tasks": ["11.4", "11.5", "11.6", "11.7", "12.2", "12.4"] },
    { "id": 12, "tasks": ["13.1", "13.2", "13.3"] },
    { "id": 13, "tasks": ["13.4", "14.1", "14.2"] },
    { "id": 14, "tasks": ["13.5", "14.3"] }
  ]
}
```
