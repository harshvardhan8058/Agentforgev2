---
# AgentForge — machine-readable project state.
# Keep this file current at the end of every phase so a fresh session can resume
# without re-deriving context. YAML front-matter is the source of truth; the
# markdown body below is a human-readable mirror.

current_phase: "Phase 9 — Cloud Deployment & Production Infrastructure (IN PROGRESS — completes on PR #17). Phases 1-8 complete and consolidated onto the deployment base."
current_branch: feat/agentforge-deployment
current_pr:
  number: 17
  base: main
  state: anticipated
  title: "Phase 9 — Cloud Deployment & Production Infrastructure"
prior_integrations_pr:
  number: 16
  base: main
  state: open
  title: "Phase 8 — Third-party Integrations (Slack, Gmail, Drive, GitHub)"
# NOTE ON TOPOLOGY: Phase 7 (frontend) and Phase 8 (integrations) were each branched
# directly off `main` (cfd8204) and are NOT merged together. Phase 7 lives on
# `feat/agentforge-frontend` (PR #14); Phase 8 lives on `feat/agentforge-integrations`
# (PR #16). This PROJECT_STATE.md file currently exists only on the frontend branch.
prior_frontend_pr:
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
  - id: 8
    name: Third-party Integrations (Slack, Gmail, Drive, GitHub)

remaining_phases:
  - id: 9
    name: Cloud Deployment & Production Infrastructure
    status: in_progress   # completes on PR #17
    note: >-
      Infrastructure only — no application behavior or API contract change. Adds
      multi-stage non-root images (backend/frontend/proxy), the nginx single entry
      point (routing, unbuffered SSE, TLS termination, security headers), the frontend
      runtime config.js plumbing, the unified keyless docker-compose.yml + production
      overlay, on-startup migrations (+ optional one-shot), a four-job CI/CD pipeline
      publishing to GHCR under a three-tag strategy, and the deployment docs.

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
  state: "Phase 9 (Cloud Deployment & Production Infrastructure) IN PROGRESS on feat/agentforge-deployment, completing on PR #17. Phases 1-8 are consolidated onto the deployment base. Tasks 1-11 done + checkpoint 12 passed; task 13 (final Phase Completion checkpoint) is left UNCHECKED for the user. Backend keyless lane green (pytest -m 'not integration' -q); frontend npm run ci green. Infrastructure only — no application behavior or API contract change."
  next: "Task 13 — the final Phase Completion checkpoint — is left for the user to check off."
  do_not_auto_start: true
---

# AgentForge — Project State

**Current phase:** Phase 8 — Third-party Integrations (**COMPLETE, in review**).
**Branch:** `feat/agentforge-integrations` · **PR:** #16 (base `main`).
Phase 7 (frontend) is also complete and in review on a **parallel** branch
`feat/agentforge-frontend` (PR #14). Both branches were cut from `main` (cfd8204) and are
**not merged together**; this file currently lives only on the frontend branch.

## Completed phases

1. Foundation
2. Core RAG
3. Agentic Layer
4. Multi-Agent Collaboration & Human Approval
5. Enterprise Controls (auth, RBAC, multi-tenancy, API keys, rate limiting)
6. Production Observability (tracing export, cost analytics, prompt registry, guardrails, evaluation)
7. React Web Frontend
8. Third-party Integrations (Slack, Gmail, Drive, GitHub)

## Remaining phases

9. Cloud Deployment & Production Infrastructure — *in progress (completes on PR #17)*

## Phase 9 — Cloud Deployment & Production Infrastructure

**Infrastructure only** — no application behavior, HTTP/SSE API contract, database-schema
semantics, or business logic changes. The single app-adjacent edit is the
behavior-preserving `resolveConfig()` runtime-config plumbing in `frontend/src/config.ts`.

Delivered artifacts:

- Multi-stage, **non-root** images: `agentforge-backend` (root `Dockerfile`),
  `agentforge-frontend` (`frontend/Dockerfile`), `agentforge-proxy` (`nginx/Dockerfile`),
  each with a matching `.dockerignore`.
- **nginx** reverse proxy as the sole entry point: path routing to frontend/backend,
  unbuffered SSE, a production TLS server block (certs mounted at runtime), and hardened
  security headers (HSTS on the TLS block only).
- Frontend **Runtime_Config**: entrypoint renders `/config.js` from `API_BASE_URL` at
  container start (build-once / run-anywhere); default preserved when unset.
- Unified **keyless** `docker-compose.yml` (one-command local start) + a **production
  overlay** (`docker-compose.production.yml`) with injected secrets, hardened creds,
  restart policies, TLS, and GHCR images; plus `.env.production.example` (placeholders).
- Migrations run **on backend startup** by default (additive, `schema_migrations`-tracked),
  with an optional one-shot `migrate` service for scale-out.
- Four-job **CI/CD** (`test → build → publish → deploy`) publishing to GHCR under a
  three-tag strategy (`latest` + git SHA + semver); cross-image secret scan.
- Docs: README Deployment section, `docs/DEPLOYMENT.md`, `docs/INFRASTRUCTURE.md`.

**Verification:** the four correctness properties are present and tagged — Property 1
(no baked secrets, keyless), Properties 2 & 3 (keyless all-healthy; migration idempotence,
both integration-lane, runtime-gated), Property 4 (build-once/run-anywhere, keyless). The
keyless backend lane (`pytest -m 'not integration' -q`) and frontend `npm run ci` remain
green and unmodified; `npm run codegen:check` confirms the API contract is unchanged. Task
13 (the final Phase Completion checkpoint) is intentionally **left for the user**.

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

**Phase 9 (Cloud Deployment & Production Infrastructure)** is **in progress** on
`feat/agentforge-deployment`, completing on **PR #17**. Phases 1–8 are consolidated onto the
deployment base. Tasks 1–11 are done and checkpoint 12 has passed; **task 13 — the final
Phase Completion checkpoint — is left UNCHECKED for the user**. The keyless backend lane
(`pytest -m 'not integration' -q`) and the frontend `npm run ci` are green and unmodified,
and `npm run codegen:check` confirms the API contract is unchanged. Phase 9 is
**infrastructure only** — no application behavior or contract change.
