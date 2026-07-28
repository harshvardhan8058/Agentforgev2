---
# AgentForge — machine-readable project state.
# Keep this file current at the end of every phase so a fresh session can resume
# without re-deriving context. YAML front-matter is the source of truth; the
# markdown body below is a human-readable mirror.

current_phase: "v1.0 COMPLETE — Phases 1-9 + Production Hardening all merged to main. Production-ready in code; pending runtime validation on a real Docker host."
current_branch: main
open_prs: none
last_merged_pr:
  number: 22
  base: main
  merge_commit: 1d7a15e
  merged_at: "2026-07-09"
  title: "Production Hardening (B1-B6): persistent keyless stores, SSE proxy, CPU image, contract drift check"

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
  - id: 9
    name: Cloud Deployment & Production Infrastructure

remaining_phases: []   # v1.0 feature scope complete

post_v1_hardening:
  pr: 22
  status: merged
  items:
    - "B1: split persistence from profile via Settings.use_database + persist_domain_stores(); local stack (USE_DATABASE=true) persists to Postgres, keyless. No new migrations."
    - "B2: documented keyless<->production config boundary (docs/CONFIGURATION.md, .env.production.example)."
    - "B3: nginx SSE — proxy_http_version 1.1 + X-Accel-Buffering no (with existing buffering/cache off + 3600s timeouts)."
    - "B4: CPU-only torch installed before requirements (image target <=4 GB; CI size gate + CUDA-absence assert)."
    - "B5: removed stray Dockerfile.verify."
    - "B6: regenerated frontend/openapi.json (+schema.d.ts) to include GET /integrations/status; added keyless scripts/check_openapi.py drift check in CI."
    - "Also merged (PRs #19-#21): asyncpg simple-protocol migration runner; .gitattributes LF + Dockerfile CRLF-strip for the entrypoint; healthcheck via 127.0.0.1; Redis_Rate_Limiter uses a SYNC redis client; RATE_LIMIT_ENABLED=false default locally."

merged_pr_index:
  "1-2": "Phases 1-2 Foundation + Core RAG"
  "3,5": "Phase 3 Agentic Layer"
  "6,9": "Phase 4 Multi-Agent"
  "8,10": "Phase 5 Enterprise"
  "11,12": "Phase 6 Observability"
  "14,15": "Phase 7 Frontend"
  "16": "Phase 8 Integrations"
  "17": "Phase 9 Deployment (+ consolidation of Phases 1-8)"
  "18": "docs (limitations/roadmap/architecture)"
  "19,20,21": "production runtime fixes (migrations, CRLF entrypoint, IPv6 healthcheck)"
  "22": "Production Hardening B1-B6"

test_status:
  backend:
    keyless_lane: "pytest -m 'not integration' -q"
    tests_passing: 484
    result: pass
    note: "Deterministic + credential-free. Integration lane (-m integration) requires a pgvector Postgres and is run on a Docker host."
  frontend:
    command: "cd frontend && npm run ci"
    ci_stages: [codegen:check, typecheck, test, build, scan:bundle]
    result: pass
  contract:
    command: "python scripts/check_openapi.py"
    result: pass

not_yet_verified_on_docker_host:
  - "docker compose build — esp. B4 PyTorch CPU index (download.pytorch.org/whl/cpu) reachability + image <=4 GB."
  - "docker compose up — all 5 services healthy; live migrations incl. CREATE EXTENSION vector."
  - "B1 persistence live — nine Pg_* stores' first real run; data survives docker compose restart."
  - "B3 SSE incremental delivery through nginx; long-lived timeouts."
  - "Auth / RAG / single-agent / multi-agent / integrations-status live; production overlay boot with secrets."
  - "Unchecked sign-off tasks: production-hardening Task 12, deployment Task 13, frontend Task 30."

architectural_constraints:
  backend:
    - "Single composition root (config/container.py) is the ONLY module naming concrete implementations; everything else depends on interface seams (Clean/Hexagonal)."
    - "Keyless by default: deterministic Fallback_Provider + local SentenceTransformer embeddings + Chroma vectors + in-memory domain stores; no credential is ever required to boot or test."
    - "Persistence is independent of profile: persist_domain_stores() = use_database OR profile==production. Local stack sets USE_DATABASE=true (keyless, DSN only) to use the nine Pg_* stores."
    - "Pg_* domain stores are synchronous psycopg, invoked via run_in_threadpool; the async engine is reserved for migrations + health checks."
    - "Credentials always optional and typed as SecretStr; only non-secret settings (database_url, redis_url) are required at startup; production also requires JWT_SECRET (guarded by load_settings)."
    - "Atomic ingestion; grounding-only prompt construction; citations verifiable."
    - "Iteration/round/revision bounds enforced structurally; SSE with exactly one terminal event per stream."
    - "RBAC is a pure function of a static role->permission map (viewer subset member subset admin subset owner); every role grants read."
    - "Tenant isolation at the data-access layer: org_id is a required store parameter; cross-tenant access is 404, never 403."
    - "Additive migrations only (0001-0011); tracked by schema_migrations; runner uses asyncpg simple query protocol for multi-statement scripts."
    - "Cost is Decimal end-to-end; Cost_Model total with a default rate."
  frontend:
    - "UI-only: consume shipped contracts; omit any affordance lacking a contract."
    - "Types generated from the backend OpenAPI schema; codegen:check + scripts/check_openapi.py fail on drift."
    - "RBAC gating omits unauthorized controls from the DOM (not merely disabled)."
    - "One total AppError->ClientError normalizer; 401 refresh-once-then-retry; cross-tenant 404 presented as 'not found'."
    - "Fetch-based SSE with pure reducers and an exactly-one-terminal invariant; approval_required is non-terminal."
    - "Runtime config via /config.js (window.__AGENTFORGE_CONFIG__.apiBaseUrl); talks to the API same-origin through nginx. No secret material in the bundle (scan:bundle)."

infrastructure_summary:
  entry_point: "nginx — sole published service (host :80 -> container :8080); routes / -> frontend:8080 and API prefixes (+SSE) -> api:8000."
  services: [nginx, frontend, api, postgres (pgvector), redis]
  images: "agentforge-backend (root Dockerfile), agentforge-frontend (frontend/Dockerfile), agentforge-proxy (nginx/Dockerfile) — all multi-stage, non-root."
  local: "docker compose up  (keyless, PROFILE=local, USE_DATABASE=true, RATE_LIMIT_ENABLED=false)."
  production: "docker-compose.production.yml overlay (PROFILE=production, GHCR images, secrets from Secret_Source, TLS, one-shot migrate)."

resume_checkpoint:
  state: "v1.0 complete and merged to main (Phases 1-9 + Production Hardening PR #22). Code green: backend keyless lane 484, frontend npm run ci, scripts/check_openapi.py. NOT yet validated on a real Docker host."
  next: "Run the Docker validation checklist on a host (see docs/SESSION_HANDOFF.md): docker compose build (watch B4 torch step) -> up -> health -> register+restart persistence -> RAG/agent/multi-agent/SSE -> pytest -m integration. Then optionally begin the (unstarted) Premium UI redesign after a visual-identity conversation."
  do_not_auto_start: true
  see_also: docs/SESSION_HANDOFF.md
---

# AgentForge — Project State

**Status:** **v1.0 COMPLETE.** Phases 1–9 and the Production Hardening pass (PR #22) are all
merged to `main`. `main` is the production-ready source of truth. **No open PRs.** The code
is green (backend keyless lane **484**, frontend `npm run ci`, `scripts/check_openapi.py`);
the remaining gate is **runtime validation on a real Docker host**.

> See `docs/SESSION_HANDOFF.md` for the full, self-contained handoff (merged-PR index,
> Docker validation checklist, risks, and prioritized next steps).

## Completed phases (all merged to `main`)

1. Foundation
2. Core RAG
3. Agentic Layer
4. Multi-Agent Collaboration & Human Approval
5. Enterprise Controls (auth, RBAC, multi-tenancy, API keys, rate limiting)
6. Production Observability (tracing export, cost analytics, prompt registry, guardrails, evaluation)
7. React Web Frontend
8. Third-party Integrations (Slack, Gmail, Drive, GitHub)
9. Cloud Deployment & Production Infrastructure

## Post-v1.0 hardening (PR #22, merged)

- **B1 — persistence:** `Settings.use_database` + `persist_domain_stores()`; the local stack
  (`USE_DATABASE=true`) now persists to Postgres via the nine `Pg_*` stores, **keyless** (DSN
  only). No new migrations — tables `0001`–`0011` already exist. Default `use_database=False`
  keeps the unit lane in-memory/deterministic.
- **B2** — documented keyless↔production config boundary (`docs/CONFIGURATION.md`,
  `.env.production.example`).
- **B3** — nginx SSE: `proxy_http_version 1.1` + `X-Accel-Buffering no`.
- **B4** — CPU-only torch before requirements (image target ≤4 GB; CI size gate).
- **B5** — removed stray `Dockerfile.verify`.
- **B6** — regenerated `frontend/openapi.json` (+`schema.d.ts`) for `GET /integrations/status`;
  keyless `scripts/check_openapi.py` drift check in CI.
- Earlier fixes (PRs #19–#21): asyncpg simple-protocol migration runner; `.gitattributes` LF +
  Dockerfile CRLF-strip for the entrypoint; healthcheck via `127.0.0.1`; sync Redis rate-limiter
  client; `RATE_LIMIT_ENABLED=false` default locally.

## Test status

- **Backend (keyless lane):** `pytest -m 'not integration' -q` → **484 passed**, deterministic,
  credential-free. The integration lane (`-m integration`) needs a pgvector Postgres and runs on
  a Docker host.
- **Frontend:** `cd frontend && npm run ci` → `codegen:check → typecheck → test → build →
  scan:bundle`, all green.
- **Contract:** `python scripts/check_openapi.py` → committed OpenAPI matches the mounted routes.

## Not yet verified on a real Docker host

- `docker compose build` — esp. **B4**: PyTorch CPU index reachability + image ≤4 GB.
- `docker compose up` — all 5 services healthy; live migrations incl. `CREATE EXTENSION vector`.
- **B1** persistence live — the nine `Pg_*` stores' first real run; data survives
  `docker compose restart`.
- **B3** SSE incremental delivery through nginx.
- Auth / RAG / single-agent / multi-agent / integrations-status live; production overlay boot.
- Unchecked sign-off tasks: production-hardening **Task 12**, deployment **Task 13**, frontend
  **Task 30**.

## Architecture summary

FastAPI backend (`agentforge.main:create_app`); `lifespan` loads `Settings`, opens the async DB
engine + async Redis, runs migrations, then builds nine context graphs via the single
composition root `config/container.py`. 14 routers. Keyless defaults (Fallback LLM,
SentenceTransformer embeddings, Chroma vectors, in-memory stores) unless `USE_DATABASE=true`/
production selects the `Pg_*` stores. `org_id` tenancy → 404; uniform `AppError` envelope;
`SecretStr` secrets; additive migrations `0001`–`0011`. React 19 + Vite SPA served behind nginx,
which is the sole published entry point (`:80→:8080`) routing `/`→frontend and API prefixes
(+SSE)→api. Postgres+pgvector and Redis complete the stack; the production overlay adds TLS,
GHCR images, secrets, and a one-shot migrate service.

## Resume checkpoint

**v1.0 is complete and merged to `main`.** Code is green; the outstanding activity is **runtime
validation on a real Docker host** (see the checklist in `docs/SESSION_HANDOFF.md`): build
(watch the B4 torch step) → up → health → register + `docker compose restart` persistence →
RAG / agent / multi-agent / SSE → `pytest -m integration`. After that's green, the next feature
initiative is the (unstarted) **Premium UI redesign**, which needs a short visual-identity
conversation before any implementation. Do not auto-start work.
