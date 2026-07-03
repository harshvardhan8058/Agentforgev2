# Implementation Plan: AgentForge Agentic Layer (Phase 3)

## Overview

This plan converts the Phase 3 design into an incremental, test-driven coding sequence
that **builds on the already-implemented Phases 1–2** in `src/agentforge/`. Phase 3
**reuses — never recreates** the existing `LLM_Provider` (Groq + keyless
`Fallback_Provider`), `RAG_Service`, `Embedding_Provider`, `Vector_Store`, the
`API_Service` uniform error envelope, Postgres/pgvector, Redis, the composition root
(`config/container.py`), and the migration runner (`db/migrations.py`). Every task
extends these seams; none reimplements them.

Language: **Python** (as specified by the design: FastAPI, Pydantic, SQLAlchemy async,
LangGraph, sentence-transformers, Chroma/pgvector, Hypothesis).

Ordering strategy (interfaces before implementations, keyless defaults first, each step
builds on the previous and ends by wiring into the graph — no orphaned code):

1. Settings extensions + module scaffolding (`agent/`, `tools/`, `memory/`,
   `conversation/`, `streaming/`, `tracing/` packages with `base.py` contracts).
2. `Tool_Interface` + `Tool_Registry` (duplicate rejection, resolve, `list_specs`).
3. `AgentState` + `Iteration_Limit` resolution.
4. Tool-call parsing + deterministic fallback `Selection_Strategy`.
5. `RAG_Tool` (wraps existing `RAG_Service`).
6. `Web_Search_Tool` + `Search_Provider` (`Disabled_Search_Provider` default).
7. `Agent_Orchestrator` LangGraph graph (reason/act/observe, conditional routing, bound
   enforcement) — reaches a **keyless-testable checkpoint**.
8. Short-term memory (`Size_Budget` FIFO).
9. Long-term memory (existing `Embedding_Provider` + `Vector_Store`).
10. `Conversation_Store` (Postgres) + migration `0003`.
11. `Trace_Recorder` (in-memory + Postgres) + migration `0004`.
12. `Streaming_Service` (SSE, typed events, single terminal event).
13. Fallback determinism (end-to-end).
14. Composition root extension (`build_agent_context`) + provider/tool wiring.
15. API endpoints + `main.py` router registration + keyless integration tests.
16. `docs/decisions.md` for the agentic layer (+ checkpoint).
17. Final full-suite checkpoint (left unchecked for the user to verify).

The **19 correctness properties** from the design are each implemented by a **single**
Hypothesis property test (minimum **100 iterations**), placed next to the implementation
it validates, and tagged `Feature: agentforge-agentic-layer, Property {n}: {text}`. The
**entire suite runs keyless** via the `Fallback_Provider` and the
`Disabled_Search_Provider`.

Sub-tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.

## Tasks

- [x] 1. Settings extensions and Phase 3 module scaffolding
  - [x] 1.1 Extend Settings for the agentic layer
    - Extend `config/settings.py` `Settings` with `iteration_limit: int | None = None`,
      `memory_size_budget: int | None = None`,
      `search_provider: Literal["disabled", ...] = "disabled"`, and
      `search_api_key: SecretStr | None = None`, plus the `active_search()` helper that
      returns `"disabled"` when no `search_api_key` is present — all optional/defaulted so
      keyless boot is preserved
    - Add every new setting name to `.env.example` with placeholder values only
    - _Requirements: 1.5, 1.6, 6.2, 5.2, 5.4, 13.1_
    - _Design: New Settings (`config/settings.py`)_

  - [x] 1.2 Create the Phase 3 package layout with interface stubs
    - Create the module tree exactly as in the design's "Repository / Module Layout"
      under `src/agentforge/`: `agent/` (`state.py`, `orchestrator.py`, `graph.py`,
      `selection.py`), `tools/` (`base.py`, `registry.py`, `rag_tool.py`,
      `web_search_tool.py`, `search/base.py`, `search/disabled.py`), `memory/`
      (`base.py`, `short_term.py`, `long_term.py`), `conversation/` (`base.py`,
      `store.py`), `streaming/` (`base.py`, `sse.py`), and `tracing/` (`base.py`,
      `recorder.py`), each with `__init__.py`
    - Add `tests/unit/` and `tests/property/` module files for the Phase 3 suites
    - Leave concrete files as minimal stubs; only `base.py` contracts are fleshed out in
      later tasks — the agent core will import solely from `base.py` modules
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
    - _Design: Repository / Module Layout; Layering and Dependency Rule_

- [ ] 2. Tool interface and registry
  - [ ] 2.1 Implement the Tool interface and value types
    - Implement `tools/base.py` with `Tool_Spec`, `Tool_Call`, `Tool_Result`,
      `ToolError`, and the abstract `Tool_Interface` (`name`, `description`,
      `input_schema`, `available` defaulting to `True`, and `invoke`)
    - _Requirements: 2.1_
    - _Design: Tool_Interface, Tool_Call, Tool_Result (`tools/base.py`)_

  - [ ] 2.2 Implement the Tool_Registry
    - Implement `tools/registry.py` `Tool_Registry` with `register` (unique-name, raising
      `DuplicateToolNameError` on collision without overwriting), `resolve` (returns the
      tool or `None`), and `list_specs` (returns name/description/input_schema of
      **available** tools only)
    - _Requirements: 2.2, 2.3, 2.4, 2.5_
    - _Design: Tool_Registry (`tools/registry.py`)_

  - [ ]* 2.3 Write property test for registry register/resolve/list round-trip
    - **Property 5: Tool registry register/resolve/list round-trip**
    - **Validates: Requirements 2.2, 2.3**

  - [ ]* 2.4 Write property test for duplicate tool-name rejection
    - **Property 6: Duplicate tool-name registration is rejected**
    - **Validates: Requirements 2.4**

  - [ ]* 2.5 Write smoke test asserting the Tool interface is abstract
    - Assert `Tool_Interface` cannot be instantiated and declares the required abstract
      members
    - _Requirements: 2.1_

- [ ] 3. Agent run state and Iteration_Limit resolution
  - [ ] 3.1 Implement AgentState and termination types
    - Implement `agent/state.py` with `TerminationReason` enum, `Observation`, and the
      `AgentState` dataclass/`TypedDict` (`run_id`, `conversation_id`, `user_request`,
      `conversation_context`, `observations`, `iteration_count=0`, `iteration_limit`,
      `pending_tool_call`, `final_answer`, `termination_reason`, `invalid_limit_flagged`)
    - _Requirements: 1.2, 1.7_
    - _Design: AgentState (`agent/state.py`)_

  - [ ] 3.2 Implement Iteration_Limit resolution
    - Implement `resolve_iteration_limit(configured)` returning `(limit, invalid_flag)`:
      pass through integers in `[1, 100]`; `None` → default 10 with no flag;
      non-integer/boolean/out-of-range → default 10 with the invalid flag set
    - _Requirements: 1.5, 1.6_
    - _Design: Iteration_Limit resolution (Req 1.5, 1.6)_

  - [ ]* 3.3 Write property test for Iteration_Limit resolution
    - **Property 4: Iteration_Limit resolution**
    - **Validates: Requirements 1.5, 1.6**

- [ ] 4. Tool-call parsing and deterministic fallback selection
  - [ ] 4.1 Implement decision parsing and the Selection_Strategy seam
    - Implement `agent/selection.py`: prompt construction that serializes available
      `Tool_Spec`s plus the fixed decision-shape instruction; `parse_decision(text)`
      extracting the first well-formed `{"action":"tool"|"final", ...}` JSON object
      (defaulting to a final answer using the raw text when none is parseable); and a
      `Selection_Strategy` seam
    - Implement the deterministic fallback strategy as a pure function of run state:
      first step selects `RAG_Tool` with `{"query": user_request}` when available; after a
      RAG observation, select final answer; select final immediately when no tools are
      available
    - _Requirements: 3.1, 3.5, 1.8_
    - _Design: Tool selection with a text LLM (`agent/selection.py`)_

  - [ ]* 4.2 Write unit test for decision parsing and fallback selection
    - Cover tool-decision JSON, final-decision JSON, unparseable text falling back to a
      final answer, and the deterministic fallback tool choice on the first step
    - _Requirements: 3.1, 3.5_

- [ ] 5. Built-in RAG retrieval tool
  - [ ] 5.1 Implement the RAG_Tool
    - Implement `tools/rag_tool.py` `RAG_Tool` implementing `Tool_Interface` with an input
      schema accepting `query` (required) and optional `top_k`; `invoke` delegates to the
      injected existing `RAG_Service` and returns a `Tool_Result` whose content is the
      answer text and whose `data` carries the citations, `grounded`, and `provider` —
      with no reimplementation of retrieval or generation
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 12.2_
    - _Design: RAG_Tool (`tools/rag_tool.py`)_

  - [ ]* 5.2 Write property test for RAG_Tool answer/citation mirroring
    - **Property 12: RAG_Tool mirrors the RAG_Service answer and citations**
    - **Validates: Requirements 4.3**

  - [ ]* 5.3 Write unit test that RAG_Tool delegates to RAG_Service
    - With a stub `RAG_Service`, assert `invoke` calls it once and does not perform its own
      retrieval/generation
    - _Requirements: 4.2, 12.2_

- [ ] 6. Built-in web search tool with graceful degradation
  - [ ] 6.1 Implement the Search_Provider interface and disabled default
    - Implement `tools/search/base.py` (`Search_Provider` ABC with `available` and
      `search`, plus `SearchResult`) and `tools/search/disabled.py`
      (`Disabled_Search_Provider` with `available = False` that never performs a network
      request)
    - _Requirements: 5.2, 5.4_
    - _Design: Web_Search_Tool and Search_Provider (`tools/search/`)_

  - [ ] 6.2 Implement the Web_Search_Tool
    - Implement `tools/web_search_tool.py` `Web_Search_Tool` implementing `Tool_Interface`
      with a `query` input schema; `available` mirrors the provider; `invoke` returns a
      `Tool_Result` indicating web search is unavailable when the provider is disabled
      (performing no network call), otherwise formats provider results
    - _Requirements: 5.1, 5.2, 5.4, 5.5_
    - _Design: Web_Search_Tool and Search_Provider (`tools/search/`)_

  - [ ]* 6.3 Write property test for disabled web search
    - **Property 11: Disabled web search returns an unavailable result without network access**
    - **Validates: Requirements 5.4, 5.5**

- [ ] 7. Agent orchestrator LangGraph graph
  - [ ] 7.1 Implement the reason/act/observe nodes and edge routing
    - Implement `agent/graph.py`: the **reason** node (presents `list_specs()` + state to
      the `LLM_Provider` via the `Selection_Strategy`, parses a decision); the **act**
      node (validates `Tool_Call` arguments against the resolved tool's input schema, then
      invokes via the `Tool_Registry`); the **observe** node (records the observation,
      increments `iteration_count` by exactly 1, loops back); and the conditional edges
      that route `reason→finalize` (final answer), `reason→act` (tool call),
      `act→observe`, and `observe→reason`/`observe→finalize_limit` when
      `iteration_count == iteration_limit`
    - Contain in-loop failures as observations: unregistered tool → `tool-not-found`;
      invalid args → `validation-error` (tool not invoked); `ToolError` →
      `tool-execution-error`; each continues the loop
    - _Requirements: 1.1, 1.3, 1.4, 3.2, 3.3, 3.4, 11.1, 11.2, 11.3, 11.4_
    - _Design: Nodes and Edges (`agent/graph.py`, `agent/orchestrator.py`)_

  - [ ] 7.2 Implement the Agent_Orchestrator
    - Implement `agent/orchestrator.py` `Agent_Orchestrator` that builds and runs the
      LangGraph `StateGraph` over `AgentState`, depends only on the abstract
      `LLM_Provider`, `Tool_Registry`, `Memory_Manager`, and `Trace_Recorder` seams,
      applies the resolved `iteration_limit` (and LangGraph `recursion_limit` as a
      defensive backstop), and always terminates with exactly one `termination_reason`
      returning the most recent available answer on the limit branch
    - _Requirements: 1.1, 1.2, 1.4, 1.7, 1.8, 3.5, 11.1, 12.1_
    - _Design: Agent_Orchestrator and the LangGraph State Graph (`agent/`)_

  - [ ]* 7.3 Write property test for the bounded loop upper bound
    - **Property 1: Bounded loop never exceeds the Iteration_Limit**
    - **Validates: Requirements 1.1, 1.4, 11.1**

  - [ ]* 7.4 Write property test for iteration-counter monotonicity
    - **Property 2: Iteration counter is monotonic and increments by exactly one**
    - **Validates: Requirements 1.2**

  - [ ]* 7.5 Write property test for exactly-one termination reason
    - **Property 3: Every run terminates with exactly one termination reason**
    - **Validates: Requirements 1.3, 1.7**

  - [ ]* 7.6 Write property test for successful tool dispatch
    - **Property 7: Successful tool dispatch records an observation and continues**
    - **Validates: Requirements 3.2, 3.3**

  - [ ]* 7.7 Write property test for unregistered tool containment
    - **Property 8: Unregistered tool calls are contained**
    - **Validates: Requirements 3.4**

  - [ ]* 7.8 Write property test for argument-validation gating of invocation
    - **Property 9: A tool is invoked if and only if its arguments conform to the schema**
    - **Validates: Requirements 11.2, 11.4**

  - [ ]* 7.9 Write property test for tool-execution-error containment
    - **Property 10: Tool execution errors are contained**
    - **Validates: Requirements 11.3**

- [ ] 8. Checkpoint — orchestrator loop is testable keyless
  - Confirm the `Agent_Orchestrator` runs end-to-end under the `Fallback_Provider` with
    the `RAG_Tool` registered and web search disabled, and that Properties 1–12 pass.
    Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Short-term memory
  - [ ] 9.1 Implement the Memory_Manager interface and short-term memory
    - Implement `memory/base.py` (`Memory_Manager` ABC, `MemoryError`, `MemoryEntry`) and
      `memory/short_term.py`: `init_short_term` validates the `Size_Budget` (rejecting
      absent/non-numeric/`<= 0` with `MemoryError`, maintaining no memory); `add_short_term`
      FIFO-evicts oldest-first excluding the current user request until total size
      `<= Size_Budget`; the current user request is always retained; if the request alone
      exceeds the budget after evicting everything else, retain it and emit the
      budget-cannot-be-satisfied `MemoryError`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
    - _Design: Memory_Manager (`memory/`) — short-term memory_

  - [ ]* 9.2 Write property test for the short-term size invariant + FIFO + retention
    - **Property 13: Short-term memory size invariant with request retention and FIFO eviction**
    - **Validates: Requirements 6.4, 6.5, 6.6**

  - [ ]* 9.3 Write property test for invalid Size_Budget rejection
    - **Property 14: Invalid Size_Budget is rejected**
    - **Validates: Requirements 6.3**

- [ ] 10. Long-term memory
  - [ ] 10.1 Implement long-term memory over existing seams
    - Implement `memory/long_term.py`: `persist_long_term` embeds text via the existing
      `Embedding_Provider` and upserts into the existing `Vector_Store` under an
      `ltm:<conversation_id>` namespace; `retrieve_long_term(query, k)` embeds the query,
      calls `Vector_Store.query(vec, k)`, and returns at most `min(K, stored_count)`
      `MemoryEntry` records ordered by descending similarity (empty when none stored) —
      with no reimplementation of embedding or vector storage
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 12.3_
    - _Design: Memory_Manager (`memory/`) — long-term memory_

  - [ ]* 10.2 Write property test for long-term top-K bound and ordering
    - **Property 15: Long-term memory top-K bound and ordering**
    - **Validates: Requirements 7.2, 7.3, 7.4**

- [ ] 11. Persistent conversation history
  - [ ] 11.1 Add the conversations migration
    - Add `migrations/0003_create_conversations.sql` creating the `conversations` and
      `messages` tables (with `role`, `content`, `position`, the
      `UNIQUE (conversation_id, position)` constraint and the ordering index) using the
      existing migration runner and templating conventions
    - _Requirements: 8.1, 8.2, 8.3_
    - _Design: PostgreSQL Schema (0003_create_conversations.sql)_

  - [ ] 11.2 Implement the Conversation_Store
    - Implement `conversation/base.py` (`Conversation_Store` ABC, `Conversation`,
      `Message`) and `conversation/store.py` `PgConversation_Store`: `create` inserts a
      UUID conversation; `append` computes the next ordinal `max(position)+1`, persists
      role/content/position, and auto-creates the conversation when the id is unknown;
      `history` returns messages in ascending ordinal order
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
    - _Design: Conversation_Store (`conversation/`)_

  - [ ]* 11.3 Write property test for conversation append/history ordering with auto-create
    - **Property 16: Conversation append/history ordering with auto-create**
    - **Validates: Requirements 8.2, 8.3, 8.4**

  - [ ]* 11.4 Write unit tests for conversation-id uniqueness and final-message persistence
    - Assert `create` yields unique ids and that a completed run appends the final
      assistant message
    - _Requirements: 8.1, 8.5_

- [ ] 12. Observability tracing of agent steps
  - [ ] 12.1 Add the agent-traces migration
    - Add `migrations/0004_create_agent_traces.sql` creating the `agent_runs` and
      `trace_entries` tables (with `ordinal`, `step_type`, `tool_name`, `outcome`,
      `detail`, the `UNIQUE (run_id, ordinal)` constraint and ordering index) via the
      existing migration runner
    - _Requirements: 10.1, 10.2, 10.3_
    - _Design: PostgreSQL Schema (0004_create_agent_traces.sql)_

  - [ ] 12.2 Implement the Trace_Recorder
    - Implement `tracing/base.py` (`Trace_Recorder` ABC, `Trace`, `Trace_Entry`) and
      `tracing/recorder.py` with an in-memory recorder (keyless default) and a
      Postgres-backed recorder: `record` appends an entry with the next ordinal, step
      type, run id, and (for tool calls) tool name and outcome; `get_trace` returns
      entries ordered by ordinal; wire recording into the orchestrator nodes
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
    - _Design: Trace_Recorder (`tracing/`)_

  - [ ]* 12.3 Write property test for trace completeness and ordering
    - **Property 18: Trace is complete and ordered by ordinal**
    - **Validates: Requirements 10.1, 10.2, 10.3**

- [ ] 13. Streaming responses (SSE)
  - [ ] 13.1 Implement the Streaming_Service
    - Implement `streaming/base.py` (`Streaming_Service` ABC, `StreamEvent`,
      `StreamEventType` = {step, tool_call, delta, completion, error}) and `streaming/sse.py`
      `SSE_Streaming_Service`: drive events from the orchestrator node callbacks in
      production order with a monotonic `sequence`, emit an initial `step` event
      immediately, serialize each event as an SSE frame, and guarantee **exactly one**
      terminal event (`completion` xor `error`) before closing — translating any
      underlying exception into a single `error` event
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8, 9.9_
    - _Design: Streaming_Service (`streaming/`)_

  - [ ]* 13.2 Write property test for streaming terminal-event and ordering guarantees
    - **Property 17: Streaming emits exactly one terminal event and preserves order**
    - **Validates: Requirements 9.3, 9.4, 9.5, 9.6, 9.8, 9.9**

  - [ ]* 13.3 Write integration test for SSE first-event timing and incremental emission
    - Assert the first event arrives within 5 s and events are emitted incrementally
      before run completion, keyless under the Fallback_Provider
    - _Requirements: 9.1, 9.2_

- [ ] 14. Fallback determinism (end-to-end)
  - [ ]* 14.1 Write property test for fallback determinism of answer and event sequence
    - **Property 19: Fallback determinism of answer and event sequence**
    - **Validates: Requirements 1.8, 3.5, 9.7**

- [ ] 15. Composition root extension and wiring
  - [ ] 15.1 Implement build_agent_context and provider/tool wiring
    - Extend `config/container.py` with `build_search_provider(settings)` (returns
      `Disabled_Search_Provider` by default) and `build_agent_context(settings, app, ...)`
      that reuses the existing `AppContext`, registers the `RAG_Tool` (always) and the
      `Web_Search_Tool` only when a search credential is present, builds the memory
      manager over the existing `Embedding_Provider` + `Vector_Store`, and constructs the
      `Agent_Orchestrator`, `Conversation_Store`, `Trace_Recorder`, and `Streaming_Service`
      with all collaborators injectable
    - _Requirements: 5.3, 7.5, 12.1, 12.2, 12.3, 12.4_
    - _Design: Composition Root Extension (`config/container.py`)_

  - [ ]* 15.2 Write unit tests for search registration policy and seam-only dependencies
    - Assert the `Web_Search_Tool` is registered only when a search key is present and not
      registered/offered when absent, and that the orchestrator depends solely on the
      abstract seams (no concrete providers)
    - _Requirements: 5.2, 5.3, 12.1, 12.3_

- [ ] 16. API endpoints and router registration
  - [ ] 16.1 Implement the conversations router and schemas
    - Add the conversation request/response models to `api/schemas.py` and implement
      `api/routers/conversations.py`: `POST /conversations` (201 `{conversation_id}`),
      `POST /conversations/{id}/messages` (201 persisted message, auto-create on unknown
      id), and `GET /conversations/{id}` (200 history ordered by position; 404 unknown)
      using the existing error envelope
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 12.4_
    - _Design: API Endpoints (conversations)_

  - [ ] 16.2 Implement the agent router and schemas
    - Add the agent request/response models to `api/schemas.py` and implement
      `api/routers/agent.py`: `POST /agent/run` (append user message, run bounded
      `Agent_Run`, persist final assistant message, return
      `run_id`/`conversation_id`/`answer`/`termination_reason`/`citations`),
      `POST /agent/stream` (`text/event-stream` via `StreamingResponse`), and
      `GET /agent/runs/{run_id}/trace` (200 ordered entries; 404 unknown) using the
      existing error envelope
    - _Requirements: 1.7, 8.5, 9.1, 9.3, 9.6, 10.3, 10.4, 12.4_
    - _Design: API Endpoints (agent-run / agent-stream / trace)_

  - [ ] 16.3 Register Phase 3 routers in the app factory
    - Extend `src/agentforge/main.py` to build the `AgentContext` at startup (respecting a
      pre-injected context for tests) and register the conversations and agent routers so
      all routes are registered before serving
    - _Requirements: 12.4_
    - _Design: Composition Root Extension; API Endpoints_

  - [ ]* 16.4 Write keyless integration tests for /agent/run and /agent/stream
    - Exercise `/agent/run` and `/agent/stream` end-to-end through the app under the
      `Fallback_Provider` with web search disabled, asserting a grounded answer with a
      single termination reason and an SSE stream ending in exactly one terminal event
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [ ]* 16.5 Write unit test for the error-envelope shape on agent error paths
    - Assert unknown conversation/run ids return `404 not_found` through the existing
      envelope
    - _Requirements: 12.4_

- [ ] 17. Documentation of agentic-layer design decisions
  - [ ] 17.1 Write the agentic-layer decision record
    - Extend `docs/decisions.md` with the rationale from the design's "Design Decisions &
      Why" (LangGraph loop, structural bound enforcement, tools behind interface +
      registry, seam reuse, text-LLM selection + deterministic fallback, short vs
      long-term memory, SSE over WebSockets), **including a step-by-step guide on how to
      add a new Tool and a new agent node type without modifying the Agent_Orchestrator**
    - _Requirements: 14.1, 14.2_
    - _Design: Design Decisions & Why_

- [ ] 18. Checkpoint — documentation and integration verified
  - Confirm the agentic-layer decisions doc is present (including the add-a-tool /
    add-a-node guide) and the keyless integration tests pass. Ensure all tests pass, ask
    the user if questions arise.

- [ ] 19. Final checkpoint — full keyless suite green
  - Run the complete Phase 3 unit, property, and integration suite with **no external LLM
    credential and no search credential** and confirm all 19 property tests pass and the
    bounded-loop termination behavior is exercised under the `Fallback_Provider`. Ensure
    all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP; all
  non-`*` sub-tasks are core implementation and must be built.
- Each task references the specific requirement clauses it implements and the relevant
  design section/component for traceability; each property test names the exact design
  property and the requirements it validates.
- The 19 property-based tests are implemented with Hypothesis (minimum 100 iterations
  each, one test per property, tagged
  `Feature: agentforge-agentic-layer, Property {n}: {text}`) and run **keyless** via the
  `Fallback_Provider` and `Disabled_Search_Provider`, satisfying Req 13.1–13.4.
- Phase 3 **reuses** the existing `LLM_Provider`, `RAG_Service`, `Embedding_Provider`,
  `Vector_Store`, API error envelope, Postgres/pgvector, Redis, composition root, and
  migration runner — no seam is reimplemented.
- Ordering enforces early runnability: the orchestrator loop reaches a keyless-testable
  checkpoint at Task 8 before memory/persistence/streaming are layered on; interfaces
  precede implementations and keyless defaults precede any keyed provider.
- Scope is strictly Phase 3: no multi-agent orchestration, human-approval workflows,
  auth/RBAC/multi-tenancy, cost/token analytics, frontend, third-party integrations, or
  cloud deployment tasks are included.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "3.1", "3.2"] },
    { "id": 2, "tasks": ["2.2", "2.5", "3.3", "4.1"] },
    { "id": 3, "tasks": ["2.3", "2.4", "4.2", "5.1", "6.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.2"] },
    { "id": 5, "tasks": ["6.3", "7.1"] },
    { "id": 6, "tasks": ["7.2"] },
    { "id": 7, "tasks": ["7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9"] },
    { "id": 8, "tasks": ["8"] },
    { "id": 9, "tasks": ["9.1", "10.1", "11.1", "12.1"] },
    { "id": 10, "tasks": ["9.2", "9.3", "10.2", "11.2", "12.2"] },
    { "id": 11, "tasks": ["11.3", "11.4", "12.3", "13.1"] },
    { "id": 12, "tasks": ["13.2", "13.3", "14.1", "15.1"] },
    { "id": 13, "tasks": ["15.2", "16.1", "16.2"] },
    { "id": 14, "tasks": ["16.3"] },
    { "id": 15, "tasks": ["16.4", "16.5", "17.1"] },
    { "id": 16, "tasks": ["18"] },
    { "id": 17, "tasks": ["19"] }
  ]
}
```
