---
# AgentForge — machine-readable project state.
# Keep this file current at the end of every phase so a fresh session can resume
# without re-deriving context. YAML front-matter is the source of truth; the
# markdown body below is a human-readable mirror.

current_phase: "Phase 7 — React Frontend (COMPLETE, in review)"
current_branch: feat/agentforge-frontend
current_pr:
  number: 14
  base: main
  state: open
  title: "Phase 7 — React Web Frontend"

completed_phases:
  - id: 1
    name: Foundation
  - id: 2
    name: Core RAG
  - id: 3
    name: Agentic Layer
  - id: 4
    name: Multi-Agent Collaboration & Human Approval
  - id: 5
    name: Enterprise Controls (Auth, RBAC, Multi-Tenancy, API Keys, Rate Limiting)
  - id: 6
    name: Production Observability (Tracing, Cost Analytics, Prompt Registry, Guardrails, Evaluation)
  - id: 7
    name: React Web Frontend

remaining_phases:
  - id: 8
    name: Third-party Integrations (Slack, Gmail, Drive, GitHub)
    status: not_started
  - id: 9
    name: Cloud Deployment
    status: not_started

# IMPORTANT STATE CORRECTION (recorded so future sessions do NOT assume the old
# unmerged Phase 3-6 PR stack still exists):
#   - The Phase 3-6 PR stack appears ALREADY MERGED to `main`.
#   - At the time of writing, `main` was at cfd8204
#     ("Merge pull request #12 from harshvardhan8058/feat/agentforge-enterprise").
#   - `feat/agentforge-observability` was NOT present on the remote.
#   - Therefore `feat/agentforge-frontend` is based directly off `main`
#     (NOT off the old observability branch).
branch_topology:
  main_head_at_frontend_branch_point: cfd8204
  main_head_commit_subject: "Merge pull request #12 from harshvardhan8058/feat/agentforge-enterprise"
  phase_3_6_stack: merged_to_main
  observability_branch_on_remote: false
  frontend_branch_base: main

test_status:
  backend:
    keyless_lane: "pytest -m 'not integration' -q"
    note: "UI-only phase — backend behavior unchanged; integration lane (Postgres/Redis/Docker) not run this session."
  frontend:
    command: "cd frontend && npm run ci"
    ci_stages: [codegen:check, typecheck, test, build, scan:bundle]
    result: pass
    tests_passing: 168
    test_files: 37
    properties: "15/15 (fast-check, >=100 iterations each)"
    bundle_secret_scan: pass

frontend_summary:
  location: /frontend
  stack: "React 18 + Vite + TypeScript"
  scope: "UI-only over the shipped Phase 1-6 HTTP/SSE contracts (no backend capability or contract change)"
  testing: "keyless + deterministic (MSW mocks, fast-check properties, Monaco/charts lazy + mocked)"
  design: "premium design-system console (Tailwind + Radix + Framer Motion + cmdk + Monaco + react-markdown + Recharts/visx)"
  tasks_total: 30
  tasks_open: [30]
  task_30: "Final Phase Completion checkpoint — manual, left for the user"

architectural_constraints:
  backend:
    - "Interfaces at exactly three seams (LLM_Provider, Embedding_Provider, Vector_Store); service layer depends only on abstract contracts."
    - "Keyless by default: deterministic Fallback_Provider + local embeddings; no credential is ever required to boot or test."
    - "Credentials always optional and typed as SecretStr; only non-secret settings (database_url, redis_url) are required at startup."
    - "Atomic ingestion: relational + vector writes commit only after the full extract->chunk->embed->store pipeline succeeds."
    - "Grounding-only prompt construction; citations verifiable (enforced as a correctness property)."
    - "Iteration/round/revision bounds enforced structurally with exactly-one-termination-reason invariants."
    - "SSE over WebSockets; exactly one terminal event (completion XOR error) per stream."
    - "RBAC is a pure function of a static role->permission map (viewer subset member subset admin subset owner); every role grants read."
    - "Tenant isolation enforced at the data-access layer: org_id is a required store parameter; cross-tenant access is 404, never 403."
    - "Immutable, monotonically-versioned prompts backed by a DB uniqueness constraint; render fails closed on missing variables."
    - "Cost is Decimal end-to-end; Cost_Model is total over its input space with a default rate."
  frontend:
    - "UI-only: consume shipped contracts; omit any affordance lacking a contract (no backend change)."
    - "Types generated from the backend OpenAPI schema (openapi-typescript -> schema.d.ts); codegen:check fails on drift."
    - "RBAC gating is a pure function mirroring enterprise/rbac.py; unauthorized controls are OMITTED from the DOM, not disabled."
    - "One total AppError -> ClientError normalizer; never throws, always a non-empty user-presentable message."
    - "401 refresh-once-then-retry (at most one refresh, at most two attempts); cross-tenant 404 presented as 'not found'."
    - "Fetch-based SSE (POST + ReadableStream) with pure reducers and an exactly-one-terminal invariant; approval_required is non-terminal."
    - "Verbatim cost rendering: cost strings shown exactly as the backend returns them (no parse/round/reformat)."
    - "No secret material in the bundle (enforced by the scan:bundle check)."

resume_checkpoint:
  state: "Phase 7 complete on PR #14 (base main); 168 keyless frontend tests + 15/15 properties green; bundle-secret scan clean."
  next: "Phase 8 — Third-party Integrations (Slack/Gmail/Drive/GitHub), PENDING user approval."
  do_not_auto_start: true
---

# AgentForge — Project State

**Current phase:** Phase 7 — React Frontend (**COMPLETE, in review**).
**Branch:** `feat/agentforge-frontend` · **PR:** #14 (base `main`).

## Completed phases

1. Foundation
2. Core RAG
3. Agentic Layer
4. Multi-Agent Collaboration & Human Approval
5. Enterprise Controls (auth, RBAC, multi-tenancy, API keys, rate limiting)
6. Production Observability (tracing export, cost analytics, prompt registry, guardrails, evaluation)
7. React Web Frontend

## Remaining phases

8. Third-party Integrations (Slack, Gmail, Drive, GitHub) — *not started*
9. Cloud Deployment — *not started*

## State correction — the Phase 3–6 PR stack is merged

A prior session may have assumed an unmerged Phase 3–6 PR stack (with a
`feat/agentforge-observability` branch). That is **no longer the case**:

- `main` was at **cfd8204** — *"Merge pull request #12 … feat/agentforge-enterprise"* —
  when `feat/agentforge-frontend` was branched.
- `feat/agentforge-observability` was **not present on the remote**.
- Therefore **`feat/agentforge-frontend` is based directly off `main`**, and the
  Phase 3–6 work is already on `main`. Future sessions should not look for or rebase
  onto the old stack.

## Test status

- **Backend (keyless lane):** `pytest -m 'not integration' -q`. Phase 7 is UI-only, so
  backend behavior is unchanged; the integration lane (Postgres/Redis/Docker) was not
  run this session.
- **Frontend:** `cd frontend && npm run ci` → `codegen:check → typecheck → test → build →
  scan:bundle`. **168 tests passing** across 37 files, **15/15 correctness properties**
  (fast-check, ≥100 iterations each), bundle-secret scan clean.

## Frontend summary

`/frontend` is a React 18 + Vite + TypeScript SPA, **UI-only** over the shipped Phase 1–6
contracts, **keyless + deterministic** in test (MSW, Monaco/charts lazy + mocked), with a
premium design-system console. 30 tasks total; **task 30 (the final manual checkpoint) is
left for the user**.

## Resume checkpoint

Phase 7 is complete on PR #14. The next step is **Phase 8 (third-party integrations)**,
**pending explicit user approval** — do **not** auto-start it.
