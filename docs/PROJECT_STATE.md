---
# AgentForge — machine-readable project state.
# Keep this file current at the end of every session so a fresh session can resume without
# re-deriving context. YAML front-matter is the source of truth; the markdown body below is
# a human-readable mirror.

current_phase: "v1.1 in progress. v1.0 (Phases 1-9 + production hardening) is merged to main. The v1.1 roadmap list is complete on a branch, plus three enterprise capabilities the audit ranked above the leftovers (audit trail, spend budgets, outbound webhooks). Open as PR #2."
current_branch: feat/v1.1-admin-crud-and-cost-defaults
base_branch: main
open_prs:
  - number: 2
    title: "v1.1: complete member/team administration + named cost-rate presets"
    branch: feat/v1.1-admin-crud-and-cost-defaults
    head_sha: d3d9e8f
    state: open
    contains:
      - "member/team admin CRUD (store + 7 endpoints + MembersView) incl. a cross-tenant write fix"
      - "named cost-rate presets + GET /analytics/cost-rates + CostRatesPanel"
      - "self-review fixes (8 findings, each with a regression test)"
      - "trace-export self-review fixes (6 fixed with tests, 4 documented as bounds)"
      - "integration connection config API + UI + manage_integrations permission"
      - "trace export made real (the Tracing_Exporter seam had no caller), GET /observability/status, OTLP exporter"
      - "enterprise audit trail (migration 0013): Audit_Log seam, GET /audit-events, owner-only read_audit_log, console page, 18 audited actions"
      - "spend budgets (migration 0014): monthly ceiling per org, 402 enforcement on spending endpoints only, Budget card on Analytics"
      - "outbound webhooks (migration 0015): webhooks/ package, 6 endpoints behind manage_webhooks, signed delivery with SSRF-hardened URL admission, delivery log, emission from all four run paths + ingest + guardrails, WebhooksView, docs/WEBHOOKS.md"
      - "webhook self-review fixes (12 defects fixed with tests; the architectural bounds documented instead)"
      - "Pg_Budget_Store integration test (it shipped without one)"
    migrations_required: "0013, 0014, 0015 (all additive + idempotent)"

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
    - "Enterprise audit trail - the top-ranked MISSING enterprise capability, not a roadmap leftover: nothing answered 'who changed this'. Append-only Audit_Log seam (in-memory + Pg), Audit_Service, GET /audit-events (owner-only read_audit_log), 18 audited actions across members/teams/API keys/integration connections/budgets/webhooks, console page whose filter vocabulary is generated from the contract, and a configurable fail-open/fail-closed posture (503 audit_unavailable when required)."
    - "Spend budgets - cost observability became cost control. PUT/GET/DELETE /budget (manage_budget, owner-only), calendar-month period computed per request, 402 budget_exceeded on the five spending endpoints only, warn-vs-block postures, Decimal end to end, enforcement cached (BUDGET_CACHE_SECONDS) with documented bounded overshoot, budget changes audited."
    - "Outbound webhooks - the platform could SHOW that something happened and could not TELL anyone. webhooks/ package (base/security/store/transport/emitter/events), 6 endpoints behind manage_webhooks (admin+), migration 0015, signed HMAC delivery with a replay-resistant timestamp, allow-list URL admission (only globally routable unicast, re-checked per attempt, redirects off), a per-endpoint delivery log with keyset pagination, a test-send endpoint, and emission from all four run paths + ingest + every guardrail entry point. Console page at /webhooks. Consumer guide at docs/WEBHOOKS.md."
    - "Trace export polish - AND trace export itself: the Tracing_Exporter seam had no caller in src/, so LANGSMITH_API_KEY exported nothing. A Trace_Export_Service now runs on all four run paths off the critical path; GET /observability/status plus a console notice distinguish 'export off' from 'no traces yet'; an OTLP exporter makes the seam vendor-neutral (optional 'otel' extra)."
    - "Admin CRUD completion - list/update/remove members, list/delete teams, team-member list/remove, plus the UI."
    - "Analytics cost defaults - named presets (groq-public-2026-07), GROQ_MODEL, GET /analytics/cost-rates, pricing panel."
    - "Integrations management UI - per-org NON-SECRET connection config over /integrations/connections (this also gave the Phase 8 Integration_Connection store its first HTTP surface; it previously had none)."
  already_done_earlier:
    - "OpenAPI contract refresh + CI freshness check (production hardening B6)."
    - "Integrations status page (docs claiming no integrations UI were stale)."
  not_started:
    - "Budget threshold notifications: the delivery seam now EXISTS (webhooks), so what remains is threshold state - persist 'this org has been told about crossing 80%/100% this period', then emit budget.threshold_crossed once per threshold per period. Being over budget is a standing condition, so it cannot be a plain event: it would fire on every request that observed it. Small, and now unblocked; this is the recommended next task."
    - "Webhook follow-ups, in value order: (1) automatic disabling + alerting after sustained delivery failure, so a permanently broken endpoint is not just a growing pile of failed rows nobody looks at; (2) manual redelivery of a recorded delivery (the log already holds the data); (3) secret rotation with an overlap window where both the old and new secret verify; (4) retention on webhook_deliveries, the fastest-growing table in the schema; (5) a dedicated bounded executor for outbound delivery so webhook work cannot consume the worker threads that serve requests."
    - "Audit export + retention: a SIEM/CSV export and a retention policy are what an auditor asks for after 'do you have a trail'; the keyset cursor they need already exists."
    - "Export durability: trace export is fire-and-forget (no retry/queue), so a collector that is down during a run loses that run's export; and exactly one destination can be active (no fan-out). Both are documented limitations, not bugs."
    - "CPU-slim backend image (~1 GB) - would require serving embeddings from outside the image; the current image is CPU-only and CI-gated at <= 4 GB."
    - "Docs & DX - DEPLOYMENT.md rollback runbooks, a quickstart, documenting the integration lane."

test_status:
  backend:
    command: "pytest -m 'not integration' -q"
    tests_passing: 1083
    result: pass
    note: "Deterministic + credential-free. ~3 min. Loads the real embedding model once (test_embedding_dimension), so the first run downloads ~90 MB."
  frontend:
    command: "cd frontend && npm run ci"
    stages: [codegen:check, lint, typecheck, test, build, scan:bundle]
    tests_passing: 490
    result: pass
  e2e:
    command: "cd frontend && npm run e2e"
    tests_passing: 28
    result: pass
    note: "Playwright chromium against the REAL production build with the API mocked at the network layer; includes full-page axe WCAG 2.1 AA scans of /members, /audit and /webhooks."
  contract:
    command: "python scripts/check_openapi.py"
    result: pass
  secrets:
    command: "python scripts/scan_secrets.py"
    result: pass
  integration:
    command: "pytest -m integration"
    result: not_run
    reason: "No PostgreSQL could be started in the authoring sandbox (containers exit immediately: crun/cgroup). Runs in CI against an ephemeral pgvector service container."
    newly_added_and_never_executed:
      - "tests/integration/test_enterprise_identity_integration.py::test_pg_admin_crud_parity"
      - "tests/integration/test_integration_connection_store_integration.py::test_pg_connection_update_and_delete_are_org_scoped"
      - "tests/integration/test_audit_log_integration.py (migration 0013, JSONB metadata, composed filters, keyset cursor, ON DELETE SET NULL, org cascade)"
      - "tests/integration/test_budget_store_integration.py (migration 0014, exact NUMERIC round-trips incl. no scientific notation, ON CONFLICT upsert preserving created_at, both CHECKs, one-row-per-org key, org cascade)"
      - "tests/integration/test_webhook_store_integration.py (migration 0015, the TEXT[] `:event = ANY(events)` emission query, the COALESCE partial update, the (created_at, id) keyset page across rows sharing a timestamp, both CHECKs, subscription + org cascades)"

architectural_constraints:
  backend:
    - "Single composition root (config/container.py) is the ONLY module naming concrete implementations; everything else depends on interface seams (Clean/Hexagonal). Two property tests enforce it for the observability and webhook seams."
    - "Keyless by default: deterministic Fallback_Provider + local SentenceTransformer embeddings + Chroma vectors + in-memory domain stores; no credential is ever required to boot or test."
    - "Persistence is independent of profile: persist_domain_stores() = use_database OR profile == production. The local stack sets USE_DATABASE=true (keyless, DSN only)."
    - "Pg_* domain stores are synchronous psycopg/SQLAlchemy, invoked via run_in_threadpool; the async engine is reserved for migrations + health checks."
    - "An in-memory store must behave like its Postgres counterpart, including cascades: the keyless webhook pair is wired together in the container so deleting a subscription sweeps its delivery log, matching migration 0015's ON DELETE CASCADE. A fake that outlives what it stands for lets a test assert documented behaviour and pass for the wrong reason."
    - "Credentials always optional and typed as SecretStr; only non-secret settings (database_url, redis_url) are required at startup; production also requires JWT_SECRET."
    - "Empty/whitespace optional string settings mean UNSET (Settings._blank_is_unset), because env config cannot distinguish absent from present-but-empty."
    - "A setting that IS a safety mechanism carries an enforced range, not a documented one (see webhook_max_attempts / webhook_timeout_seconds / webhook_backoff_seconds)."
    - "RBAC is a pure function of a static role->permission map (viewer subset member subset admin subset owner); every role grants read. Adding a permission is a single-file edit in enterprise/rbac.py PLUS the client mirror, and tests/property/test_rbac_client_mirror.py enforces that pairing."
    - "Tenant isolation at the data-access layer: org_id is a required store parameter and appears in the query, not in a post-filter; cross-tenant access is 404, never 403."
    - "Domain invariants live next to the write (Identity_Store), not in the router: last_owner and the Req 2.5 team-membership rule are enforced inside the writing transaction."
    - "Additive migrations only (0001-0015), tracked by schema_migrations; the runner uses the asyncpg simple query protocol for multi-statement scripts."
    - "Cost is Decimal end-to-end and crosses the API as exact strings; pricing resolves default rates -> named preset -> explicit table."
    - "Governance side channels must never fail the work they govern: an audit write is fail-open by default (fail-closed reports 503 audit_unavailable on an APPLIED change rather than pretending to roll it back), a budget check that cannot compute spend allows the run, a Webhook_Emitter never raises, and all of them degrade to no-ops when their context is unwired."
    - "Observability side channels must never affect the work they observe: trace export and webhook emission run after the response (background task) or after the SSE terminal event (completion hook), swallow every failure, short-circuit before any store read when off, and their DI accessors degrade to a disabled service rather than 500-ing a run when no observability context is wired."
    - "Work that is owed regardless of the response status uses api/errors.defer_after_error, which is honoured for a HANDLED AppError only - an unhandled exception means the process is in an unknown state and is no place to run further side effects."
    - "Outbound HTTP to a tenant-supplied URL passes one seam (Webhook_Transport) with every bound in one place: allow-list URL admission re-checked per attempt, redirects disabled, response body never read, a bounded timeout, and failure expressed as a result rather than an exception."
    - "Integration enablement is a pure function of Settings; stored connection config never grants a capability and never holds a credential."
  frontend:
    - "UI-only: consume shipped contracts; omit any affordance lacking a contract."
    - "Types generated from the backend OpenAPI schema; codegen:check + scripts/check_openapi.py fail on drift."
    - "A closed server-side vocabulary is consumed as a Record over the GENERATED union (audit actions in AuditLogView, subscribable webhook events in WebhooksView), so extending it server-side fails tsc rather than silently dropping an option."
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
  egress: "The API makes outbound HTTPS requests to tenant-supplied webhook URLs. A deployment behind an egress proxy or a restrictive security group must allow that, and the transport deliberately sets trust_env=False so it does NOT pick up HTTP(S)_PROXY from the environment."

not_yet_verified_on_a_real_docker_host:
  - "docker compose build / up — all 5 services healthy; live migrations incl. CREATE EXTENSION vector."
  - "The Pg_* domain stores against a live database, including the five newly added suites."
  - "SSE incremental delivery through nginx; long-lived timeouts."
  - "Production overlay boot with real secrets."
  - "A real outbound webhook delivery over the network (the unit/API lanes use a recording transport; only the URL-admission policy is exercised against real DNS/IDNA behaviour)."

resume_checkpoint:
  state: "v1.0 on main; v1.1 work complete and pushed on feat/v1.1-admin-crud-and-cost-defaults (PR #2), now including three enterprise capabilities beyond the original list (audit trail, spend budgets, outbound webhooks). All local gates green: backend 1083, frontend 490, e2e 28, contract + secret scans clean. Migrations 0013, 0014 and 0015 are additive and idempotent; their live-Postgres behaviour has NOT been executed (no database available in the authoring sandbox)."
  next: "1) Land PR #2 (watch the integration lane in CI - it is the first execution of five Pg suites). 2) Recommended next feature: budget threshold notifications over the new webhook seam - it is the smallest remaining item with real enterprise value, and the only reason it was not done in this cycle is that a standing condition needs threshold state rather than a plain event. 3) Then the webhook follow-ups in v1_1_roadmap_status.not_started, in the order listed. 4) The Docker-host validation checklist in docs/SESSION_HANDOFF.md is still the gate on calling the stack runtime-verified."
  see_also: docs/SESSION_HANDOFF.md
---

# AgentForge — Project State

**Status:** v1.0 (Phases 1–9 + production hardening) is merged to `main`. **v1.1 is in
progress** on `feat/v1.1-admin-crud-and-cost-defaults`, open as
[PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2). The branch adds migrations
`0013`, `0014` and `0015` — all additive and idempotent.

> `docs/SESSION_HANDOFF.md` is the self-contained handoff (what changed, how to verify it,
> what is still unverified, and what to do next). `CHANGELOG.md` records the v1.1 changes
> individually. `docs/WEBHOOKS.md` is the consumer-facing webhook guide.

## What landed in v1.1 so far

The original v1.1 list was three items of polish. An audit at the start of each session
re-ranked the remaining work, and three times the highest-value task turned out to be a
**missing enterprise capability** rather than a leftover — so those were built instead of
saved.

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
4. **Trace export that actually exports.** The `Tracing_Exporter` seam shipped in Phase 6
   with two implementations, a factory, a DI accessor and its own tests — and **no caller
   anywhere in `src/`**. Every completed run now goes through a `Trace_Export_Service`;
   `GET /observability/status` and a console notice remove the "export off vs no traces yet"
   ambiguity; an OTLP exporter makes the seam vendor-neutral.
5. **An append-only audit trail.** The first question of every compliance review — "who
   changed this, and when" — had no answer. 18 administrative actions are now recorded
   org-scoped and credential-free, readable at `GET /audit-events` by an owner, with the
   failure posture (fail open, or `503 audit_unavailable`) left to the operator.
6. **Spend budgets.** Cost was measurable and unlimitable. An owner sets a monthly ceiling
   that either warns or refuses new work with `402 budget_exceeded`, enforced in front of the
   five spending endpoints and never in front of a read or an approval decision.
7. **Outbound webhooks.** The platform could *show* that a run finished, a document was
   ingested, or a guardrail refused an input, and could not *tell* anybody. Signed,
   org-scoped delivery of four events from every path that produces them, with a per-endpoint
   delivery log, an allow-list SSRF policy over subscriber URLs, and a test-send endpoint so a
   consumer can verify their signature handling before real traffic depends on it.

## Test status

| Lane | Command | Result |
|---|---|---|
| Backend (keyless) | `pytest -m 'not integration' -q` | **1083 passed** |
| Frontend | `cd frontend && npm run ci` | **490 passed** |
| Browser | `cd frontend && npm run e2e` | **28 passed** |
| Contract | `python scripts/check_openapi.py` | pass |
| Secrets | `python scripts/scan_secrets.py` | pass |
| Live PostgreSQL | `pytest -m integration` | **not run locally** — runs in CI |

The integration lane could not run in the authoring sandbox (no database would stay up), so
five Postgres suites have never executed against real SQL — the two admin/connection cases,
plus the audit-log, budget and webhook store suites. That is the first thing to watch when
PR #2's CI runs.

## Architecture summary

FastAPI backend (`agentforge.main:create_app`); `lifespan` loads `Settings`, opens the async
DB engine + async Redis, runs migrations, then builds the context graphs through the single
composition root `config/container.py`. 18 routers. Keyless defaults (Fallback LLM,
SentenceTransformer embeddings, Chroma vectors, in-memory stores) unless `USE_DATABASE=true`
or the production profile selects the `Pg_*` stores. `org_id` tenancy is enforced in the
query, so cross-tenant access is 404. Uniform `AppError` envelope; `SecretStr` secrets;
additive migrations `0001`–`0015`. React 18 + Vite SPA behind nginx, which is the sole
published entry point (`:80→:8080`) routing `/`→frontend and API prefixes (+SSE)→api.
Postgres+pgvector and Redis complete the stack; the production overlay adds TLS, GHCR
images, secrets, and a one-shot migrate service.

Three governance/observability side channels now hang off the completed-work paths — trace
export, usage metering, and webhook emission — and all three obey the same rule: they run
after the response, they swallow their own failures, and they cost nothing when unconfigured.

## Resume checkpoint

Land PR #2 first (its CI run is the first execution of five Postgres suites). The
recommended next feature is **budget threshold notifications** over the new webhook seam:
being over budget is a standing condition rather than an event, so it needs threshold state
("this org has already been told about crossing 80% this period") — which is the only reason
it was not part of the webhook work. After that, the webhook follow-ups in the front-matter,
in the order given. Runtime validation on a real Docker host remains the gate on calling the
stack verified end to end; the checklist is in `docs/SESSION_HANDOFF.md`.
