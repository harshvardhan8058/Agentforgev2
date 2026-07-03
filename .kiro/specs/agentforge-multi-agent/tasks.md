# Implementation Plan: AgentForge Multi-Agent Collaboration & Human Approval (Phase 4)

## Overview

This plan converts the Phase 4 design into an ordered, incremental, test-driven coding
sequence. Every task builds on the previous one — interfaces and stubs first, then the
typed state/models, then the role interface + registry, then the four roles, then the
orchestrator graph, then approval, streaming, tracing, persistence, composition root, and
finally the API endpoints — with everything wired together so no code is left orphaned.

The whole layer **reuses, never reimplements** the existing Phase 1-3 seams:
`Agent_Orchestrator`, `Tool_Registry`, `RAG_Tool`, `Memory_Manager`, `Conversation_Store`,
`Trace_Recorder`, the SSE `Streaming_Service`, `LLM_Provider`/`Fallback_Provider`, the
`API_Service` uniform error envelope, Postgres/pgvector, the composition root
(`config/container.py`), and the migration runner (`db/migrations.py`). New code lives
under `src/agentforge/multiagent/` and one new migration.

**Keyless-first testing.** All 16 correctness properties from the design are implemented
as **Hypothesis** property tests (minimum 100 iterations each, one test per property,
tagged `Feature: agentforge-multi-agent, Property {n}: {text}`), placed next to their
implementation area under `tests/property/`. Unit tests cover error cases and delegation;
integration tests cover the keyless end-to-end and API paths. Everything runs KEYLESS via
`Fallback_Provider` + disabled `Web_Search_Tool` + `Auto_Approve_Policy`; human-in-the-loop
is exercised with injected `Approval_Decision`s (no real human).

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Top-level tasks are never optional.
- Each task references the specific requirements and design components it implements.

## Tasks

- [ ] 1. Extend settings and scaffold the `multiagent/` package with interfaces and stubs
  - Extend `config/settings.py` `Settings` with `max_rounds: int | None = None`,
    `max_revisions: int | None = None`, and `approval_policy: Literal["auto", "human"] = "auto"`,
    all optional/defaulted to preserve keyless boot (design "New Settings").
  - Create the `src/agentforge/multiagent/` package with `__init__.py` and empty/stubbed
    modules matching the design's Repository/Module Layout: `state.py`, `models.py`,
    `orchestrator.py`, `graph.py`, `approval.py`, `streaming.py`, `store.py`, and the
    `roles/` subpackage (`roles/__init__.py`, `roles/base.py`, `roles/planner.py`,
    `roles/researcher.py`, `roles/writer.py`, `roles/critic.py`).
  - In `roles/base.py`, declare the abstract `Agent_Role_Interface` (ABC) with `role_id`,
    `instructions`, and `act(state) -> Blackboard_State` as abstract members (stub only),
    and an `Agent_Role_Registry` class skeleton — no concrete logic yet.
  - Add empty ABC stubs for `Approval_Policy` (`approval.py`) and `Multi_Agent_Run_Store`
    (`store.py`) so downstream modules can import the seams.
  - _Requirements: 2.5, 3.5, 5.7, 1.1_

- [ ]* 1.1 Write a structural/smoke test for the package layout and interface abstractness
  - Assert `multiagent` submodules import cleanly, that `Agent_Role_Interface`,
    `Approval_Policy`, and `Multi_Agent_Run_Store` are abstract (cannot be instantiated),
    and that the new settings fields exist with keyless defaults.
  - _Requirements: 1.1, 5.7_

- [ ] 2. Implement the domain models, `Blackboard_State`, and bound resolution
  - [ ] 2.1 Implement `multiagent/models.py` domain dataclasses
    - Define `Plan`, `Research_Finding`, `Research_Findings` (with `all_citations()`),
      `Draft`, `Critic_Feedback` (with explicit `revision_required` flag),
      `ApprovalDecisionType` enum, `Approval_Decision`, `Final_Output`,
      `Termination_Reason` enum (`{completed, max-rounds-reached, max-revisions-reached,
      rejected, aborted}`), and `Multi_Agent_Run`.
    - Reuse the existing `Citation` type from `models/domain.py` (do NOT redefine it).
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 2.3, 2.7, 5.3, 5.4, 8.3_

  - [ ] 2.2 Implement `multiagent/state.py` — `Blackboard_State` and bound resolution
    - Define the `Blackboard_State` dataclass with all typed fields from the design
      (task, plan, research_findings, draft, critic_feedback, round_count, revision_count,
      max_rounds, max_revisions, invalid flags, termination_reason, final_output, and the
      approval fields), initializing `round_count`/`revision_count` to 0.
    - Implement `_resolve_bound`, `resolve_max_rounds` (default 6, range [1, 50]), and
      `resolve_max_revisions` (default 3, range [1, 20]) returning `(value, invalid_flag)`;
      reject non-int/bool/out-of-range values to the default with the invalid flag set.
    - _Requirements: 4.1, 4.7, 2.5, 2.6, 3.5, 3.6_

  - [ ]* 2.3 Write property test for Max_Rounds resolution
    - **Property 5: Max_Rounds resolution**
    - **Validates: Requirements 2.5, 2.6**

  - [ ]* 2.4 Write property test for Max_Revisions resolution
    - **Property 6: Max_Revisions resolution**
    - **Validates: Requirements 3.5, 3.6**

  - [ ]* 2.5 Write unit tests for model/state construction edge cases
    - Cover `Research_Findings.all_citations()` flattening, default empty citation lists,
      and `Blackboard_State` zero-initialized counters.
    - _Requirements: 4.1, 4.7_

- [ ] 3. Implement the `Agent_Role_Interface`, registry, and declarative pipeline
  - [ ] 3.1 Implement `roles/base.py` registry and pipeline
    - Complete `Agent_Role_Registry` (`register` rejecting duplicate `role_id`, `resolve`,
      `roles`) and define `DEFAULT_PIPELINE = ["planner", "researcher", "writer", "critic"]`
      as declarative data the orchestrator reads.
    - Finalize the concrete `Agent_Role_Interface` contract used by roles and the graph.
    - _Requirements: 1.1, 1.4, 13.2_

  - [ ]* 3.2 Write property test for the add-a-role interface round-trip
    - **Property 9: Add-a-role interface round-trip**
    - **Validates: Requirements 1.4**

- [ ] 4. Implement the four built-in Agent_Roles over the reused Agent_Orchestrator
  - [ ] 4.1 Implement `Planner_Agent` (`roles/planner.py`)
    - `act` builds a role-scoped request from `instructions` + task, runs the injected
      existing `Agent_Orchestrator`, and parses the final answer into a `Plan`; deterministic
      Fallback step list derived from the task text. Populates `state.plan`.
    - _Requirements: 1.1, 1.2, 1.3, 4.3, 11.1, 11.2_

  - [ ] 4.2 Implement `Researcher_Agent` (`roles/researcher.py`)
    - `act` runs the existing `Agent_Orchestrator` with the `RAG_Tool` available, builds
      `Research_Findings` whose entries carry `Citation`s from `extract_citations(state)`;
      never reimplements retrieval/citation. Web_Search_Tool used only if configured.
    - _Requirements: 1.1, 1.2, 1.3, 4.4, 8.1, 8.4, 11.1, 11.3_

  - [ ] 4.3 Implement `Writer_Agent` (`roles/writer.py`)
    - `act` produces/revises the `Draft` from the Plan + Research_Findings (incorporating
      `Critic_Feedback` on a revision) and **preserves citations**: `Draft.citations` is the
      union of citations of the findings it used, carried forward unchanged across revisions.
    - _Requirements: 1.1, 1.2, 1.3, 3.2, 4.5, 8.2, 11.1_

  - [ ] 4.4 Implement `Critic_Agent` (`roles/critic.py`)
    - `act` emits structured `Critic_Feedback` with an explicit `revision_required` flag +
      comments; deterministic under Fallback (default approves). Populates `state.critic_feedback`.
    - _Requirements: 1.1, 1.2, 1.3, 4.6, 3.7, 11.1_

  - [ ]* 4.5 Write unit tests for role delegation and distinct instructions
    - Verify each role delegates to the injected `Agent_Orchestrator` (and Researcher to the
      `RAG_Tool`) rather than generating text itself, and that the four roles expose distinct
      `role_id`s and distinct `instructions`.
    - _Requirements: 1.2, 1.3, 8.4, 11.1, 11.2, 11.3, 11.4_

- [ ] 5. Implement the Multi_Agent_Orchestrator and LangGraph state graph
  - [ ] 5.1 Implement `multiagent/graph.py` — role nodes and conditional routing
    - Wrap each pipeline `role_id` as a graph node; implement `route_after_critic` enforcing
      the bounds structurally: increment `round_count` by exactly 1 in the Critic node;
      route to `finalize_rounds` when `round_count >= Max_Rounds`; on required revision route
      to Writer incrementing `revision_count` by 1 only while `revision_count < Max_Revisions`,
      else route to `finalize_revs`; on approve route to `finalize_done`.
    - _Requirements: 2.1, 2.2, 2.4, 3.1, 3.3, 3.4_

  - [ ] 5.2 Implement `multiagent/orchestrator.py` — build and run the graph
    - Build the `StateGraph` by iterating `DEFAULT_PIPELINE` and resolving roles from the
      registry (no per-role code in the core); initialize counters to 0; ensure every
      terminal node sets exactly one `Termination_Reason`, with a defensive `aborted` guard
      in `run()`; emit the latest Draft as `Final_Output` on completion.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7, 4.2, 4.7_

  - [ ]* 5.3 Write property test for the round bound
    - **Property 1: Round count is bounded by Max_Rounds and increments by exactly one**
    - **Validates: Requirements 2.2, 2.4, 12.4**

  - [ ]* 5.4 Write property test for the revision bound and exact boundary
    - **Property 2: Revision count is bounded by Max_Revisions with the exact boundary**
    - **Validates: Requirements 3.1, 3.3, 3.4, 12.4**

  - [ ]* 5.5 Write property test for exactly-one termination reason
    - **Property 3: Every run terminates with exactly one Termination_Reason**
    - **Validates: Requirements 2.7**

  - [ ]* 5.6 Write property test for Critic approval completing the run
    - **Property 4: Critic approval completes the run and emits the Draft as Final_Output**
    - **Validates: Requirements 2.3**

  - [ ]* 5.7 Write property test for blackboard accumulation and role activation order
    - **Property 7: Blackboard accumulation and role activation order**
    - **Validates: Requirements 2.1, 4.2, 4.3, 4.4, 4.5, 4.6**

  - [ ]* 5.8 Write property test for citation preservation
    - **Property 8: Citation preservation from research through draft to final output**
    - **Validates: Requirements 3.2, 8.1, 8.2, 8.3**

- [ ] 6. Checkpoint - keyless orchestrator runs end-to-end
  - Ensure the orchestrator completes a run end-to-end under the `Fallback_Provider` with an
    approve Critic (Termination_Reason = completed) and terminates at the revision/round
    bounds with an injected always-revise Critic. Ensure all tests pass, ask the user if
    questions arise.

- [ ] 7. Implement the Approval_Policy seam and Human_Approval_Gate
  - [ ] 7.1 Implement `multiagent/approval.py` policies and gate
    - Implement `ApprovalOutcome`, the `Approval_Policy` ABC, `Auto_Approve_Policy`
      (always CONTINUE, keyless default) and `Human_In_The_Loop_Policy` (always PAUSE).
    - Implement `Human_Approval_Gate` with `at_checkpoint` (pause: set `awaiting_approval`,
      persist a `Run_Checkpoint`, record trace pause entry, emit `approval_required`) and
      `submit(run_id, decision)` handling approve/edit (resume from checkpoint, replacing the
      corresponding field on edit), reject (record as Critic_Feedback and resume as a bounded
      revision, or terminate `rejected` when the bound is reached), and the non-paused-run
      rejection path. Define checkpoints `after_plan` and `before_finalize`; compile the graph
      with `interrupt_before` + a checkpointer keyed by `thread_id = run_id`.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 10.4_

  - [ ]* 7.2 Write property test for approve/edit pause → resume
    - **Property 10: Human-approval pause -> decision -> resume for approve and edit**
    - **Validates: Requirements 5.1, 5.2, 5.4, 10.4, 12.5**

  - [ ]* 7.3 Write property test for bounded reject decisions
    - **Property 11: Reject decision is bounded to revision-or-terminate**
    - **Validates: Requirements 5.3**

  - [ ]* 7.4 Write property test for decisions against non-paused runs
    - **Property 12: A decision to a non-paused run is rejected without state change**
    - **Validates: Requirements 5.5**

  - [ ]* 7.5 Write unit test for default auto-approve policy selection
    - Verify the gate uses `Auto_Approve_Policy` when the Configuration_Manager provides no
      `approval_policy`.
    - _Requirements: 5.7_

- [ ] 8. Implement the Multi_Agent_Streaming_Service
  - [ ] 8.1 Implement `multiagent/streaming.py`
    - Define `MultiAgentStreamEventType` (`agent_started, plan, research, draft,
      critic_feedback, approval_required, completion, error`) and `MA_TERMINAL_EVENT_TYPES`.
    - Implement `Multi_Agent_Streaming_Service` mirroring the existing SSE service: monotonic
      `sequence`, first event within 5s (initial `agent_started` for Planner), forward each
      role contribution as it is produced, identify the acting `role_id` on agent events,
      preserve production order, emit `approval_required` (non-terminal) on human pause, and
      guarantee exactly one terminal event (`completion` with Final_Output xor `error`) then
      close. Reuse the existing `format_sse_frame` serialization shape.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 11.5_

  - [ ]* 8.2 Write property test for streaming terminal/order/attribution guarantees
    - **Property 14: Streaming emits exactly one terminal event, ordered and role-attributed**
    - **Validates: Requirements 7.3, 7.4, 7.6, 7.7, 7.8**

  - [ ]* 8.3 Write property test for auto-approve determinism (output + event sequence)
    - **Property 13: Auto-approve determinism of final output and event sequence**
    - **Validates: Requirements 1.5, 3.7, 5.6, 7.9, 12.1**

  - [ ]* 8.4 Write unit tests for incremental and approval_required emission
    - Verify events are emitted incrementally without waiting for completion (Req 7.2) and
      that `approval_required` is emitted on a human-in-the-loop pause (Req 7.5).
    - _Requirements: 7.2, 7.5_

- [ ] 9. Wire per-agent tracing through the reused Trace_Recorder
  - Attribute each role step by recording a `role:{role_id}` entry with the run id at the
    next ordinal via the existing `Trace_Recorder` (no replacement); record approval
    pause/resume/decision and rejected-attempt entries through the same recorder.
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 11.5_

  - [ ]* 9.1 Write property test for complete, ordered, role-attributed trace
    - **Property 15: Trace is complete, ordered by ordinal, and role-attributed**
    - **Validates: Requirements 6.1, 6.3**

- [ ] 10. Implement persistence: migration and Multi_Agent_Run_Store
  - [ ] 10.1 Add migration `migrations/0005_create_multi_agent_runs.sql`
    - Create `multi_agent_runs`, `approval_decisions`, and `run_checkpoints` tables plus
      indexes exactly as in the design; use the existing runner/templating and reuse the
      existing `conversations`, `messages`, `agent_runs`, and `trace_entries` tables.
    - _Requirements: 10.1, 10.3, 10.4, 10.5, 10.6_

  - [ ] 10.2 Implement `multiagent/store.py` — ABC + InMemory + Pg implementations
    - Complete the `Multi_Agent_Run_Store` ABC (`create`, `append_message`, `record_decision`,
      `save_checkpoint`, `load_checkpoint`, `terminate`, `get`); implement
      `InMemory_Multi_Agent_Run_Store` (keyless default/test double) and
      `Pg_Multi_Agent_Run_Store` (synchronous SQLAlchemy, mirroring `PgConversation_Store`),
      reusing the existing `messages` table for agent messages (role = `role_id`,
      position = ordinal).
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 10.3 Write property test for agent-message persistence round-trip
    - **Property 16: Agent-message persistence round-trip with ordinal and role**
    - **Validates: Requirements 10.2**

  - [ ]* 10.4 Write unit tests for run/decision/final-output persistence on the in-memory store
    - Cover `create`, `record_decision`, and `terminate` round-trips including
      `final_output`/`termination_reason` retrieval.
    - _Requirements: 10.1, 10.3, 10.5_

  - [ ]* 10.5 Write Pg integration test for the migration and store
    - Apply migration 0005 against Postgres reusing existing tables, and round-trip a run
      through `Pg_Multi_Agent_Run_Store`.
    - _Requirements: 10.6_

- [ ] 11. Extend the composition root to wire the multi-agent context
  - Add `build_multi_agent_context`, `build_approval_policy` (Auto_Approve by default), and
    `build_multi_agent_run_store` to `config/container.py`; register the four roles against
    the **same** existing `Agent_Orchestrator` from `AgentContext`, wire the gate,
    orchestrator, and streaming service, and keep every collaborator injectable for keyless
    in-memory test doubles.
  - _Requirements: 5.7, 11.1, 11.2, 11.3, 11.4, 11.5, 12.1_

  - [ ]* 11.1 Write unit tests for the composition root wiring
    - Verify roles share the single existing `Agent_Orchestrator`, auto-approve is the
      default policy, and overrides inject in-memory store/policy.
    - _Requirements: 5.7, 11.1, 12.1_

- [ ] 12. Implement the API endpoints and register the router
  - [ ] 12.1 Extend `api/schemas.py` and `api/deps.py`
    - Add typed Pydantic request/response models for start/stream/approval/result (reusing
      the existing `CitationModel`) and a `get_multi_agent_context` accessor.
    - _Requirements: 9.1, 9.3, 9.4, 9.7_

  - [ ] 12.2 Implement `api/routers/multi_agent.py` and register it in `main.py`
    - Implement `POST /multi-agent/runs` (create + persist, return id, `201`),
      `POST /multi-agent/runs/{id}/stream` (SSE via the streaming service),
      `POST /multi-agent/runs/{id}/approval` (forward to the gate, return run state), and
      `GET /multi-agent/runs/{id}` (ordered trace + Final_Output/Termination_Reason on
      termination). Use the existing uniform error envelope for failures, unavailable data,
      and `404`; run synchronous calls via `run_in_threadpool`. Register the router and build
      the `MultiAgentContext` at startup in `main.py` (respecting a pre-injected context).
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 11.5_

  - [ ]* 12.3 Write keyless API integration tests
    - Cover start -> stream -> `completion` end-to-end; the approval flow
      (start -> stream approval_required -> submit decision -> resume); and error paths
      (`404` unknown id, unavailable-data envelope, non-paused-run rejection).
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 12.1, 12.5_

- [ ] 13. Extend `docs/decisions.md` with the multi-agent design decisions
  - Add the Phase 4 rationale: supervisor/graph over role-nodes, bounding both rounds and
    revisions, the role interface + registry + declarative pipeline **add-a-role guide**, the
    reuse of the Phase 3 orchestrator, and how the `Approval_Policy` seam keeps the approval
    gate testable independently of any real human approver.
  - _Requirements: 13.1, 13.2, 13.3_

  - [ ] 13.1 Checkpoint - docs and wiring review
    - Ensure the decisions doc renders and all wired components import cleanly. Ensure all
      tests pass, ask the user if questions arise.

- [ ] 14. Final full-suite checkpoint (leave unchecked for the user)
  - Run the documented test command with no external credentials configured and confirm all
    16 property tests plus unit/integration tests pass keyless (Fallback_Provider + disabled
    Web_Search_Tool + Auto_Approve_Policy; human-in-the-loop via injected decisions). Ensure
    all tests pass, ask the user if questions arise.
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP;
  core implementation tasks are never optional.
- Each of the 16 correctness properties is implemented by a **single** Hypothesis property
  test (>= 100 iterations), tagged `Feature: agentforge-multi-agent, Property {n}: {text}`,
  placed under `tests/property/` next to the area it validates.
- Structural, reuse, timing, documentation, and CRUD-shape criteria are covered by
  unit/integration/smoke tests rather than property tests, per the design's Testing Strategy.
- Scope is strictly Phase 4: no enterprise auth/RBAC, cost analytics, frontend, third-party
  integrations, or deployment.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "Settings extension + multiagent package scaffolding with base interfaces/stubs."
    },
    {
      "wave": 2,
      "tasks": ["2"],
      "description": "Domain models, Blackboard_State, and bound resolution (Properties 5, 6)."
    },
    {
      "wave": 3,
      "tasks": ["3"],
      "description": "Agent_Role_Interface, registry, declarative pipeline (Property 9)."
    },
    {
      "wave": 4,
      "tasks": ["4"],
      "description": "The four built-in roles over the reused Agent_Orchestrator + RAG_Tool."
    },
    {
      "wave": 5,
      "tasks": ["5"],
      "description": "Orchestrator + graph with structural bounds (Properties 1, 2, 3, 4, 7, 8)."
    },
    {
      "wave": 6,
      "tasks": ["6"],
      "description": "Checkpoint: keyless orchestrator runs end-to-end (approve + always-revise)."
    },
    {
      "wave": 7,
      "tasks": ["7"],
      "description": "Approval_Policy seam + Human_Approval_Gate (Properties 10, 11, 12)."
    },
    {
      "wave": 8,
      "tasks": ["8", "9"],
      "description": "Streaming service (Properties 13, 14) and per-agent tracing (Property 15)."
    },
    {
      "wave": 9,
      "tasks": ["10"],
      "description": "Persistence: migration 0005 + Multi_Agent_Run_Store (Property 16)."
    },
    {
      "wave": 10,
      "tasks": ["11"],
      "description": "Composition root wiring to the same existing Agent_Orchestrator."
    },
    {
      "wave": 11,
      "tasks": ["12"],
      "description": "API endpoints + main.py registration + keyless integration tests."
    },
    {
      "wave": 12,
      "tasks": ["13"],
      "description": "docs/decisions.md extension + docs/wiring checkpoint."
    },
    {
      "wave": 13,
      "tasks": ["14"],
      "description": "Final full-suite keyless checkpoint (left unchecked for the user)."
    }
  ],
  "notes": [
    "Each wave depends on all prior waves; interfaces precede implementations.",
    "Wave 8 tasks 8 and 9 are independent of each other and may run in parallel.",
    "Optional (*) test sub-tasks may be deferred without blocking dependent waves."
  ]
}
```
