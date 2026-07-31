---
# AgentForge — machine-readable project state.
# Keep this file current at the end of every session so a fresh session can resume without
# re-deriving context. YAML front-matter is the source of truth; the markdown body below is
# a human-readable mirror.

current_phase: "v1.1 in progress. v1.0 (Phases 1-9 + production hardening) is merged to main. Three v1.1 roadmap items are complete on a branch and open as PR #2."
current_branch: feat/v1.1-admin-crud-and-cost-defaults
base_branch: main
open_prs:
  - number: 2
    title: "v1.1: complete member/team administration + named cost-rate presets"
    branch: feat/v1.1-admin-crud-and-cost-defaults
    head_sha: 43093b2
    state: open
    contains:
      - "member/team admin CRUD (store + 7 endpoints + MembersView) incl. a cross-tenant write fix"
      - "named cost-rate presets + GET /analytics/cost-rates + CostRatesPanel"
      - "self-review fixes (8 findings, each with a regression test)"
      - "integration connection config API + UI + manage_integrations permission"
    migrations_required: none

completed_phases:
  - {id: 1, name: Foundation}
  - {id: 2, name: Core RAG}
  - {id: 3, name: Agentic Layer}
  - {id: 4, name: "Multi-Agent Collaboration & Human Approval"}
  - {id: 5, name: "Enterprise Controls (Auth, RBAC, Multi-Tenancy, API Keys, Rate Limiting)"}
  - {id: 6, name: "Production Observability (Tracing, Cost Analytics, Prompt Registry, Guardrails, Evaluation)"}
  - {id: 7, name: "React Web Frontend"}
  - {id: 8, name: "Third-party Integrations (Slack, Gmail, Drive, GitHub)"}
  - {id: 9, name: "Cloud Deployment & Production Infrastructure"}
  - {id: "post-v1.0", name: "Production hardening B1-B6 (persistent keyless stores, config boundary, nginx SSE, CPU-only image, OpenAPI drift check)"}

v1_1_roadmap_status:
  done_on_branch:
    - "Admin CRUD completion — list/update/remove members, list/delete teams, team-member list/remove, plus the UI."
    - "Analytics cost defaults — named presets (groq-public-2026-07), GROQ_MODEL, GET /analytics/cost-rates, pricing panel."
    - "Integrations management UI — per-org NON-SECRET connection config over /integrations/connections (this also gave the Phase 8 Integration_Connection store its first HTTP surface; it previously had none)."
  already_done_earlier:
    - "OpenAPI contract refresh + CI freshness check (production hardening B6)."
    - "Integrations status page (docs claiming no integrations UI were stale)."
  not_started:
    - "CPU-slim backend image (~1 GB) — would require serving embeddings from outside the image; the current image is CPU-only and CI-gated at <= 4 GB."
    - "Trace export polish — graceful UI when tracing is NoOp; optional OpenTelemetry exporter alongside LangSmith."
    - "Docs & DX — DEPLOYMENT.md rollback runbooks, a quickstart, documenting the integration lane."

test_status:
  backend:
    command: "pytest -m 'not integration' -q"
    tests_passing: 711
    result: pass
    note: "Deterministic + credential-free. ~2 min. Loads the real embedding model once (test_embedding_dimension), so the first run downloads ~90 MB."
  frontend:
    command: "cd frontend && npm run ci"
    stages: [codegen:check, lint, typecheck, test, build, scan:bundle]
    tests_passing: 439
    result: pass
  e2e:
    command: "cd frontend && npm run e2e"
    tests_passing: 20
    result: pass
    note: "Playwright chromium against the REAL production build with the API mocked at the network layer; includes full-page axe WCAG 2.1 AA scans."
  contract:
    command: "python scripts/check_openapi.py"
    result: pass
  secrets:
    command: "python scripts/scan_secrets.py"
    result: pass
  integration:
    command: "pytest -m integration"
    result: not_run
    reason: "No PostgreSQL could be started in the authoring sandbox (containers exit immediately). Runs in CI against an ephemeral pgvector service container."
    newly_added_and_never_executed:
      - "tests/integration/test_enterprise_identity_integration.py::test_pg_admin_crud_parity"
      - "tests/integration/test_integration_connection_store_integration.py::test_pg_connection_update_and_delete_are_org_scoped"

architectural_constraints:
  backend:
    - "Single composition root (config/container.py) is the ONLY module naming concrete implementations; everything else depends on interface seams (Clean/Hexagonal)."
    - "Keyless by default: deterministic Fallback_Provider + local SentenceTransformer embeddings + Chroma vectors + in-memory domain stores; no credential is ever required to boot or test."
    - "Persistence is independent of profile: persist_domain_stores() = use_database OR profile == production. The local stack sets USE_DATABASE=true (keyless, DSN only)."
    - "Pg_* domain stores are synchronous psycopg/SQLAlchemy, invoked via run_in_threadpool; the async engine is reserved for migrations + health checks."
    - "Credentials always optional and typed as SecretStr; only non-secret settings (database_url, redis_url) are required at startup; production also requires JWT_SECRET."
    - "Empty/whitespace optional string settings mean UNSET (Settings._blank_is_unset), because env config cannot distinguish absent from present-but-empty."
    - "RBAC is a pure function of a static role->permission map (viewer subset member subset admin subset owner); every role grants read. Adding a permission is a single-file edit in enterprise/rbac.py PLUS the client mirror, and tests/property/test_rbac_client_mirror.py now enforces that pairing."
    - "Tenant isolation at the data-access layer: org_id is a required store parameter and appears in the query, not in a post-filter; cross-tenant access is 404, never 403."
    - "Domain invariants live next to the write (Identity_Store), not in the router: last_owner and the Req 2.5 team-membership rule are enforced inside the writing transaction."
    - "Additive migrations only (0001-0012), tracked by schema_migrations; the runner uses the asyncpg simple query protocol for multi-statement scripts."
    - "Cost is Decimal end-to-end and crosses the API as exact strings; pricing resolves default rates -> named preset -> explicit table."
    - "Integration enablement is a pure function of Settings; stored connection config never grants a capability and never holds a credential."
  frontend:
    - "UI-only: consume shipped contracts; omit any affordance lacking a contract."
    - "Types generated from the backend OpenAPI schema; codegen:check + scripts/check_openapi.py fail on drift."
    - "RBAC gating omits unauthorized controls from the DOM (not merely disabled)."
    - "One total AppError->ClientError normalizer; 401 refresh-once-then-retry; cross-tenant 404 presented as 'not found'."
    - "Server state is keyed through orgScopedKey so switching org re-scopes every list."
    - "Server-side policies (e.g. the credential-shaped-config rule) are surfaced verbatim, never re-implemented client-side."
    - "Fetch-based SSE with pure reducers and an exactly-one-terminal invariant; approval_required is non-terminal."
    - "Runtime config via /config.js (window.__AGENTFORGE_CONFIG__.apiBaseUrl); same-origin through nginx. No secret material in the bundle (scan:bundle)."

infrastructure_summary:
  entry_point: "nginx — sole published service (host :80 -> container :8080); routes / -> frontend:8080 and API prefixes (+SSE) -> api:8000."
  services: [nginx, frontend, api, "postgres (pgvector)", redis]
  images: "agentforge-backend (root Dockerfile, CPU-only torch, CI-gated <= 4 GB with no CUDA packages), agentforge-frontend, agentforge-proxy — all multi-stage, non-root."
  local: "docker compose up  (keyless, PROFILE=local, USE_DATABASE=true, RATE_LIMIT_ENABLED=false)."
  production: "docker-compose.production.yml overlay (PROFILE=production, GHCR images, secrets from Secret_Source, TLS, one-shot migrate)."
  ci: "preflight (secret scan + change detection) -> backend | frontend (Node 22 + 24) | e2e | integration (pgvector service container) -> image (build once, assert size + no CUDA, scan layers, then push) -> deploy (gated environment) -> ci (aggregate gate)."

not_yet_verified_on_a_real_docker_host:
  - "docker compose build / up — all 5 services healthy; live migrations incl. CREATE EXTENSION vector."
  - "The Pg_* domain stores against a live database, including the two new admin/connection suites."
  - "SSE incremental delivery through nginx; long-lived timeouts."
  - "Production overlay boot with real secrets."

resume_checkpoint:
  state: "v1.0 on main; v1.1 work complete and pushed on feat/v1.1-admin-crud-and-cost-defaults (PR #2). All local gates green: backend 711, frontend 439, e2e 20, contract + secret scans clean. No migration needed."
  next: "1) Land PR #2 (watch the integration lane in CI — it is the first execution of the two new Pg suites). 2) Then pick from v1_1_roadmap_status.not_started; trace-export polish is the cheapest real feature, DEPLOYMENT rollback runbooks the cheapest docs win. 3) The Docker-host validation checklist in docs/SESSION_HANDOFF.md is still the gate on calling the stack runtime-verified."
  see_also: docs/SESSION_HANDOFF.md
---

# AgentForge — Project State

**Status:** v1.0 (Phases 1–9 + production hardening) is merged to `main`. **v1.1 is in
progress**: three roadmap items are complete on `feat/v1.1-admin-crud-and-cost-defaults` and
open as [PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2). No migration is
required by that work.

> `docs/SESSION_HANDOFF.md` is the self-contained handoff (what changed, how to verify it,
> what is still unverified, and what to do next). `CHANGELOG.md` records the v1.1 changes
> individually.

## What landed in v1.1 so far

1. **Member and team administration.** The org surface was create-and-add only. It now
   supports listing the roster, reassigning roles, removing members, listing and deleting
   teams, and listing/removing team members — with a last-owner invariant enforced inside
   the writing transaction, and a fix for a cross-tenant write that was possible when a user
   held memberships in two organizations.
2. **Cost pricing that means something out of the box.** `COST_RATE_PRESET` selects a shipped
   table of published per-model prices; `GET /analytics/cost-rates` reports the effective
   rates and their source; the Analytics page explains a zero total instead of presenting it
   as a real figure.
3. **Integration connection configuration.** The Phase 8 `Integration_Connection` store,
   its Postgres implementation and migration `0011` had **no HTTP surface at all**; they now
   back a real API and UI, behind a new `manage_integrations` permission, with an admission
   policy that keeps credential-shaped values out of a free-form JSON column.

## Test status

| Lane | Command | Result |
|---|---|---|
| Backend (keyless) | `pytest -m 'not integration' -q` | **711 passed** |
| Frontend | `cd frontend && npm run ci` | **439 passed** |
| Browser | `cd frontend && npm run e2e` | **20 passed** |
| Contract | `python scripts/check_openapi.py` | pass |
| Secrets | `python scripts/scan_secrets.py` | pass |
| Live PostgreSQL | `pytest -m integration` | **not run locally** — runs in CI |

The integration lane could not run in the authoring sandbox (no database would stay up), so
the two newly added Postgres suites — `test_pg_admin_crud_parity` and
`test_pg_connection_update_and_delete_are_org_scoped` — have never executed against real
SQL. That is the first thing to watch when PR #2's CI runs.

## Architecture summary

FastAPI backend (`agentforge.main:create_app`); `lifespan` loads `Settings`, opens the async
DB engine + async Redis, runs migrations, then builds the context graphs through the single
composition root `config/container.py`. 14 routers. Keyless defaults (Fallback LLM,
SentenceTransformer embeddings, Chroma vectors, in-memory stores) unless `USE_DATABASE=true`
or the production profile selects the `Pg_*` stores. `org_id` tenancy is enforced in the
query, so cross-tenant access is 404. Uniform `AppError` envelope; `SecretStr` secrets;
additive migrations `0001`–`0012`. React 18 + Vite SPA behind nginx, which is the sole
published entry point (`:80→:8080`) routing `/`→frontend and API prefixes (+SSE)→api.
Postgres+pgvector and Redis complete the stack; the production overlay adds TLS, GHCR
images, secrets, and a one-shot migrate service.

## Resume checkpoint

Land PR #2 first (its CI run is the first execution of the two new Postgres suites). After
that, the unstarted v1.1 items are trace-export polish, a CPU-slim image, and the deployment
docs/DX work — see the front-matter for the specifics. Runtime validation on a real Docker
host remains the gate on calling the stack verified end to end; the checklist is in
`docs/SESSION_HANDOFF.md`.
