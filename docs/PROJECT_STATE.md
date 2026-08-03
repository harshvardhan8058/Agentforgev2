---
# AgentForge — machine-readable project state.
# Keep this file current at the end of every session so a fresh session can resume without
# re-deriving context. YAML front-matter is the source of truth; the markdown body below is
# a human-readable mirror.

current_phase: "v1.1 in progress. v1.0 (Phases 1-9 + production hardening) and the first five v1.1 items are merged to main (PR #3). The notification seam - outbound webhooks + budget threshold notifications - is complete on a branch and open as PR #4."
current_branch: feat/v1.1-durable-webhook-delivery
base_branch: main
open_prs:
  - number: 5
    title: "v1.1: durable webhook delivery (migration 0017)"
    branch: feat/v1.1-durable-webhook-delivery
    state: open
    migrations_required: ["0017_create_webhook_outbox"]
    contains:
      - "webhook_outbox: delivery intent persisted in the request that produced the event"
      - "dispatcher (who) / outbox (when) / worker (how) split; the emitter no longer owns a retry loop"
      - "exponential schedule 1m..6h over 8 attempts (~1 day), lease-based claiming (FOR UPDATE SKIP LOCKED) so several instances can drain one queue"
      - "abandoned events surfaced on GET /webhooks/queue + POST /webhooks/queue/{id}/redeliver (audited as webhook.redelivered)"
      - "idempotency_key in every envelope + X-AgentForge-Idempotency-Key / X-AgentForge-Attempt headers"
      - "paused subscriptions HOLD events; deleted subscriptions discard them"
      - "worker prunes delivered outbox rows after 7 days; WEBHOOK_WORKER_ENABLED lets a web tier skip delivery"
      - "Delivery queue panel on the Webhooks page"
      - "zero-ceiling budget alert announces only the 100% threshold"
  - number: 4
    title: "v1.1: outbound webhook framework (migration 0015)"
    branch: feat/v1.1-webhook-framework
    head_sha: b9c0a96
    state: open
    migrations_required: ["0015_create_webhooks", "0016_create_budget_notifications"]
    contains:
      - "outbound webhook framework: src/agentforge/webhooks/ (event vocabulary, SSRF URL admission, HMAC signing, in-memory + Pg stores, httpx transport, bounded emitter, payload builders)"
      - "6 endpoints under /webhooks behind a new manage_webhooks permission (admin+); secret returned exactly once at creation"
      - "emission wired into agent run + stream, multi-agent start/stream/approval, ingestion, and input-guardrail blocks"
      - "defer_after_error seam in api/errors.py so a RAISED refusal can schedule post-response work"
      - "Completed_Run record on the SSE completion hook (was a bare run id)"
      - "budget threshold notifications (migration 0016): claim-per-(org, period, threshold), off-band dispatch, cooldown + attempt cap, reconcile on ceiling change"
      - "Webhooks console page + nav + route + 20 component tests + 5 e2e + axe scan"
      - "self-review round: 14 findings, 3 blocking, all fixed with regression tests (commit 0ec106b)"
      - "fixes: Budget_Guard cache keyed per period; Budget_Status.spend_is_authoritative; --color-success WCAG AA; CardTitle heading level; Pg_Budget_Store integration test (previously recorded gap)"
  - number: 3
    title: "v1.1: admin CRUD, cost defaults, integrations, trace export, audit trail, spend budgets"
    branch: feat/v1.1-admin-crud-and-cost-defaults
    head_sha: f34a6a6
    state: merged
    contains:
      - "member/team admin CRUD (store + 7 endpoints + MembersView) incl. a cross-tenant write fix"
      - "named cost-rate presets + GET /analytics/cost-rates + CostRatesPanel"
      - "self-review fixes (8 findings, each with a regression test)"
      - "trace-export self-review fixes (6 fixed with tests, 4 documented as bounds)"
      - "integration connection config API + UI + manage_integrations permission"
      - "trace export made real (the Tracing_Exporter seam had no caller), GET /observability/status, OTLP exporter"
      - "enterprise audit trail (migration 0013): Audit_Log seam, GET /audit-events, owner-only read_audit_log, console page, 15 audited actions"
      - "spend budgets (migration 0014): monthly ceiling per org, 402 enforcement on spending endpoints only, Budget card on Analytics"
    migrations_required: ["0013_create_audit_events", "0014_create_spend_budgets"]

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
    - "Enterprise audit trail - the top-ranked MISSING enterprise capability, not a roadmap leftover: nothing answered 'who changed this'. Append-only Audit_Log seam (in-memory + Pg), Audit_Service, GET /audit-events (owner-only read_audit_log), 15 audited actions across members/teams/API keys/integration connections/budgets, console page whose filter vocabulary is generated from the contract, and a configurable fail-open/fail-closed posture (503 audit_unavailable when required)."
    - "Spend budgets - cost observability became cost control. PUT/GET/DELETE /budget (manage_budget, owner-only), calendar-month period computed per request, 402 budget_exceeded on the five spending endpoints only, warn-vs-block postures, Decimal end to end, enforcement cached (BUDGET_CACHE_SECONDS) with documented bounded overshoot, budget changes audited."
    - "Trace export polish - AND trace export itself: the Tracing_Exporter seam had no caller in src/, so LANGSMITH_API_KEY exported nothing. A Trace_Export_Service now runs on all four run paths off the critical path; GET /observability/status plus a console notice distinguish 'export off' from 'no traces yet'; an OTLP exporter makes the seam vendor-neutral (optional 'otel' extra)."
    - "Admin CRUD completion — list/update/remove members, list/delete teams, team-member list/remove, plus the UI."
    - "Analytics cost defaults — named presets (groq-public-2026-07), GROQ_MODEL, GET /analytics/cost-rates, pricing panel."
    - "Integrations management UI — per-org NON-SECRET connection config over /integrations/connections (this also gave the Phase 8 Integration_Connection store its first HTTP surface; it previously had none)."
  already_done_earlier:
    - "OpenAPI contract refresh + CI freshness check (production hardening B6)."
    - "Integrations status page (docs claiming no integrations UI were stale)."
  done_on_this_branch:
    - "Outbound webhook framework (migration 0015) - the notification seam three features were waiting for. Closed vocabulary (run.completed, run.failed, document.ingested, guardrail.blocked, budget.threshold_crossed, + a non-subscribable webhook.ping), SSRF URL admission as an allow-list re-checked per attempt, Stripe-style HMAC signing with verify_signature() shipped as platform code, bounded in-process retries, a keyset-paginated delivery log, 6 endpoints behind manage_webhooks (admin+), a console page, and REAL emission from every run/ingest/guardrail path (the defect class this repo produced once with Tracing_Exporter is covered by tests/api/test_webhook_emission.py)."
    - "Budget threshold notifications (migration 0016) - the first consumer of the seam, and the only place a CONDITION is turned into an event. Claim-per-(org, period, threshold) whose primary key IS the claim, off-band dispatch on the service's own pool, release + cooldown + attempt cap on failure, reconcile when the ceiling moves, and suppression when the spend figure is the guard's fail-open placeholder."
  not_started:
    - "Export durability: export is fire-and-forget (no retry/queue), so a collector that is down during a run loses that run's export; and exactly one destination can be active (no fan-out). Both are documented limitations, not bugs."
    - "Webhook durability: delivery is in-process and best-effort (no queue), so a restart mid-delivery loses one and retries are spent in seconds. An outbox table + worker is the single biggest remaining gap vs Stripe/GitHub. ALSO unstarted: delivery-log retention, webhook secret rotation with a dual-verify grace window, and more events (evaluation.completed, prompt.published)."
    - "Audit export + retention: a SIEM/CSV export and a retention policy are what an auditor asks for after 'do you have a trail'; the keyset cursor they need already exists."
    - "CPU-slim backend image (~1 GB) — would require serving embeddings from outside the image; the current image is CPU-only and CI-gated at <= 4 GB."
    - "Docs & DX — DEPLOYMENT.md rollback runbooks, a quickstart, documenting the integration lane."

test_status:
  backend:
    command: "pytest -m 'not integration' -q"
    tests_passing: 1172
    result: pass
    note: "Deterministic + credential-free. ~2 min. Loads the real embedding model once (test_embedding_dimension), so the first run downloads ~90 MB."
  frontend:
    command: "cd frontend && npm run ci"
    stages: [codegen:check, lint, typecheck, test, build, scan:bundle]
    tests_passing: 497
    result: pass
  e2e:
    command: "cd frontend && npm run e2e"
    tests_passing: 27
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
      - "tests/integration/test_audit_log_integration.py (migration 0013, JSONB metadata, composed filters, keyset cursor, ON DELETE SET NULL, org cascade)"
      - "tests/integration/test_budget_store_integration.py (migration 0014, NUMERIC(20,8) Decimal exactness, ON CONFLICT upsert preserving created_at, CHECK constraints, org cascade) - CLOSES the gap recorded by the previous session"
      - "tests/integration/test_webhook_store_integration.py (migration 0015, TEXT[] event round-trip, :event = ANY(events), partial UPDATE clearing a column, keyset cursor with id tie-break, subscription + org cascades, status CHECK)"
      - "tests/integration/test_budget_notification_store_integration.py (migration 0016, INSERT ... ON CONFLICT DO NOTHING claim atomicity ACROSS TWO CONNECTIONS, release_except with an integer[] param, org cascade)"
      - "tests/integration/test_webhook_outbox_integration.py (migration 0017, and the MOST IMPORTANT never-executed suite in the repo: two Pg_Webhook_Outbox instances claiming concurrently must take disjoint rows - that is FOR UPDATE SKIP LOCKED, the property durable delivery rests on, and it cannot be proven in memory)"

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
    - "Additive migrations only (0001-0016), tracked by schema_migrations; the runner uses the asyncpg simple query protocol for multi-statement scripts."
    - "Notification side channels must never affect the work they report on: the REQUEST path only ENQUEUES (one indexed read + one INSERT per subscription, never a dial), and a separate worker delivers. Dispatch runs off the response path anyway - BackgroundTasks for successes, the api/errors.py deferred seam for RAISED refusals, the alert service's own pool for budget thresholds."
    - "Webhook delivery is durable and at-least-once: retry state lives in webhook_outbox, not in a process, so a deploy delays events instead of losing them. Claiming leases a row in ONE statement (FOR UPDATE SKIP LOCKED), so running several application instances is safe. The price is that a repeat can reach a consumer, which is why every envelope carries an idempotency_key - the logical identity of the occurrence, stable across retries AND across a re-stream or a redelivery."
    - "A tenant-supplied URL is only ever dialled through webhooks/security.py: https-only (http for loopback outside production), no credentials/fragment, no scheme/port contradiction, and every RESOLVED address must be globally routable (an allow-list, so an unenumerated special range is still refused). Re-validated per attempt; redirects disabled; the response body is never read."
    - "A webhook signing secret is stored RECOVERABLY (a hash cannot sign) and returned exactly once at creation - the asymmetry with Argon2-hashed API keys is deliberate and documented in KNOWN_LIMITATIONS."
    - "Cost is Decimal end-to-end and crosses the API as exact strings; pricing resolves default rates -> named preset -> explicit table."
    - "Governance side channels must never fail the work they govern: an audit write is fail-open by default (fail-closed reports 503 audit_unavailable on an APPLIED change rather than pretending to roll it back), a budget check that cannot compute spend allows the run, and both degrade to no-ops when their context is unwired."
    - "Observability side channels must never affect the work they observe: trace export runs after the response (background task) or after the SSE terminal event (completion hook), swallows every failure, short-circuits before any store read when off, and its DI accessor degrades to a disabled service rather than 500-ing a run when no observability context is wired."
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
  state: "v1.0 on main; v1.1 work complete and pushed on feat/v1.1-admin-crud-and-cost-defaults (PR #2), now including two enterprise capabilities beyond the original list (audit trail, spend budgets). All local gates green: backend 891, frontend 467, e2e 21, contract + secret scans clean. Migrations 0013 and 0014 are additive and idempotent; their live-Postgres behaviour has NOT been executed (no database available in the authoring sandbox)."
  next: "1) Land PR #4. Watch the integration lane in CI - it is the FIRST EVER execution of tests/integration/test_{webhook_store,budget_store,budget_notification_store}_integration.py, and the Pg claim/atomicity assertions in particular have never run. 2) Then: webhook delivery durability (an outbox table + worker) is the highest-value remaining item - it is what separates this from Stripe/GitHub webhooks, and every other webhook gap (retention, rotation, more events) is smaller. 3) Audit export + retention is the next-best enterprise ask. 4) The Docker-host validation checklist in docs/SESSION_HANDOFF.md is still the gate on calling the stack runtime-verified."
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
| Backend (keyless) | `pytest -m 'not integration' -q` | **891 passed** |
| Frontend | `cd frontend && npm run ci` | **467 passed** |
| Browser | `cd frontend && npm run e2e` | **21 passed** |
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
