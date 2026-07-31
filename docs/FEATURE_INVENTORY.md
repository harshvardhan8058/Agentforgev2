# AgentForge v1.0 — Feature Inventory

> Scope: all implemented capabilities across Phases 1–9, consolidated on `feat/agentforge-deployment` (PR #17).
>
> **Global keyless note:** the platform runs with zero credentials. The one cross-cutting caveat is the LLM: with no `GROQ_API_KEY` the system uses a deterministic **Fallback provider**, so generated answer text is a deterministic stub (real generation needs the optional key). Embeddings run locally (sentence-transformers, CPU; first use downloads the ~90 MB model over the network, no key).

## 1. Authentication

**Login / Self-Registration / Session**
- **Purpose:** Authenticate operators; issue/refresh JWTs; establish org+role session.
- **Backend modules:** `enterprise/auth`, `enterprise/principal`, `api/routers/auth.py`, `api/deps.py`, `config/settings` (jwt_secret, argon2id).
- **Frontend:** `features/auth/LoginView`, `RegisterView`, `AuthLayout`; `auth/SessionProvider`, `tokenStore`, `useSession`; `routing/ProtectedRoute`; API auth-middleware (bearer + 401 refresh-once).
- **Endpoints:** `POST /auth/login`, `POST /auth/register-self`, `POST /auth/refresh`.
- **User workflow:** Register org/owner → JWT stored → protected routes unlocked → auto-refresh on 401 → logout clears session.
- **Status:** Fully working.
- **Keyless:** Yes (dev signing secret auto-generated locally; production requires `JWT_SECRET`).
- **Optional credentials:** None.
- **Limitations:** Production boot aborts if `JWT_SECRET` missing (by design).

## 2. RAG (Retrieval-Augmented Generation)

**Grounded Query with Citations**
- **Purpose:** Answer questions grounded in the org's ingested documents, with citations + guardrail flags.
- **Backend modules:** `rag`, `retrieval`, `embeddings`, `vectorstore` (Chroma local / pgvector prod), `chunking`, `llm`, `api/routers/query.py`; guardrail pipeline wraps it.
- **Frontend:** `features/query/RagQueryView` (streaming answer, `components/markdown` with inline citations, grounded/ungrounded indicator, flags).
- **Endpoints:** `POST /query` (`{query, top_k}` → `{answer, grounded, provider, citations[], flags[]}`).
- **User workflow:** Type query → answer renders with `[n]` citations → guardrail-blocked shows reason and withholds answer.
- **Status:** Fully working.
- **Keyless:** Yes (answer text is deterministic fallback without `GROQ_API_KEY`; retrieval/citations are real).
- **Optional credentials:** `GROQ_API_KEY` (real LLM), `HOSTED_EMBEDDING_API_KEY` (hosted embeddings).
- **Limitations:** Grounded answer quality limited by fallback LLM in keyless mode.

## 3. Single Agent

**Bounded reason→act→observe Agent + Trace**
- **Purpose:** Run a single agent with a tool loop (RAG/web tools), stream reasoning, view an ordered trace.
- **Backend modules:** `agent/orchestrator`, `agent/graph` (LangGraph, bounded iterations), `tools` (registry, `rag_tool`, `web_search_tool`), `memory`, `conversation`, `streaming/sse`, `tracing`, `api/routers/agent.py`.
- **Frontend:** `features/agent/SingleAgentRunView`, `TraceTimeline`/`TraceView`, `useSseRun`, `api/sse` transport + `singleAgentReducer`; StreamingCursor + markdown/citations.
- **Endpoints:** `POST /agent/run`, `POST /agent/stream` (SSE), `GET /agent/runs/{run_id}/trace`.
- **User workflow:** Submit task → live token stream (step/tool_call/delta) → completion (answer+citations+termination_reason) → open trace timeline; cancel supported.
- **Status:** Fully working.
- **Keyless:** Yes (deterministic fallback reasoning; Web Search tool disabled without key).
- **Optional credentials:** `GROQ_API_KEY`, `SEARCH_API_KEY` (enables Web Search tool).
- **Limitations:** Trace detail marked "unavailable" when tracing is NoOp; web tool absent keyless.

## 4. Multi-Agent

**Supervisor Planner→Researcher→Writer→Critic + Human Approval**
- **Purpose:** Orchestrate a multi-role collaboration with bounded rounds/revisions and an interactive approval checkpoint.
- **Backend modules:** `multiagent/orchestrator`, `multiagent/roles/*`, `multiagent/streaming`, reuses `agent` + `tools` + `tracing`; `api/routers/multi_agent.py`.
- **Frontend:** `features/multiAgent/MultiAgentRunView`, `WorkflowVisualizer` (animated role nodes, per-role accents), `ApprovalPanel` (approve/reject/edit), `MultiAgentRunResult`; `multiAgentReducer` (role_id/sequence, `approval_required` non-terminal).
- **Endpoints:** `POST /multi-agent/runs`, `POST /multi-agent/runs/{id}/stream` (SSE), `POST /multi-agent/runs/{id}/approval`, `GET /multi-agent/runs/{id}`.
- **User workflow:** Start run → animated role transitions stream → `approval_required` pauses for approve/reject/edit → completion renders final output+citations; `409` if not awaiting approval.
- **Status:** Fully working.
- **Keyless:** Yes (approval policy auto-approves in keyless via `approval_policy=auto`; deterministic outputs).
- **Optional credentials:** `GROQ_API_KEY`; `approval_policy=human` for a real gate.
- **Limitations:** Human-gate is opt-in; content deterministic without LLM key.

## 5. Documents

**Corpus Ingestion & Management**
- **Purpose:** Upload/list/delete documents that RAG draws from (text/PDF/MD → chunk → embed → vector store).
- **Backend modules:** `ingestion`, `chunking`, `embeddings`, `vectorstore`, `api/routers/documents.py` (+ `ingest` router/pipeline).
- **Frontend:** `features/documents/DocumentListView`, `UploadControl` (drag-drop + progress, skeletons, optimistic delete, mobile cards).
- **Endpoints:** `GET /documents`, `POST /documents` (multipart), `DELETE /documents/{document_id}` (+ ingestion pipeline).
- **User workflow:** Drag-drop upload → shows `document_id/filename/chunk_count/status` → listed with metadata → delete removes row on 204.
- **Status:** Fully working.
- **Keyless:** Yes (local embeddings).
- **Optional credentials:** `HOSTED_EMBEDDING_API_KEY` (optional).
- **Limitations:** Upload error envelopes surfaced (413/415/400/422/500); large files bounded by `max_document_bytes`.

## 6. Prompt Registry

**Immutable Versioned Prompts + Prompt Studio**
- **Purpose:** Browse/create immutable prompt versions, diff versions, render with variables.
- **Backend modules:** `observability` prompt registry, `api/routers/prompts.py`, migrations.
- **Frontend:** `features/prompts/PromptRegistryView`, `PromptStudio` (Monaco editor + `DiffEditor`, lazy-loaded/mocked in tests), `RenderPromptForm`.
- **Endpoints:** `GET /prompts`, `GET /prompts/{name}/versions`, `GET /prompts/{name}?version=N`, `POST /prompts`, `POST /prompts/{name}/render`.
- **User workflow:** List templates → pick version (body/vars/created-at) → diff → render with variables (blocks on missing vars; `400 missing_variable` shows names) → append new immutable version.
- **Status:** Fully working.
- **Keyless:** Yes.
- **Optional credentials:** None.
- **Limitations:** Version-create gated behind `ingest_documents` permission.

## 7. Analytics

**Usage & Cost Dashboard**
- **Purpose:** Org-scoped token/cost usage with time-range and by-provider/model/user breakdowns.
- **Backend modules:** `observability` (Instrumented_Provider usage capture, Cost_Model with Decimal, analytics store), `api/routers/analytics.py`, migrations.
- **Frontend:** `features/analytics/UsageDashboardView`, lazy `UsageCharts` (Recharts), per-breakdown error boundaries; cost strings rendered verbatim.
- **Endpoints:** `GET /analytics/usage?start&end`.
- **User workflow:** Open dashboard → totals + breakdowns + charts → set time range → empty state when no records.
- **Status:** Fully working.
- **Keyless:** Yes (costs default to `0.0`; usage recorded from runs).
- **Optional credentials:** None (real cost figures require configuring `cost_rate_table_json`).
- **Limitations:** Costs are 0 unless a rate table is set; meaningful volume requires runs.

## 8. Guardrails

**Guardrail Config + Evaluate**
- **Purpose:** Inspect the active guardrail pipeline and evaluate content (allow/flag/block).
- **Backend modules:** `observability` Guardrail_Pipeline (wraps query/agent/multi-agent), `api/routers/guardrails.py`.
- **Frontend:** `features/guardrails/GuardrailsView` (ordered config cards; allow/flag/block states).
- **Endpoints:** `GET /guardrails/config`, `POST /guardrails/evaluate`.
- **User workflow:** View ordered guardrails (name/kind) → submit content → decision (flag shows flags+reason; block shows reason); empty → no-active-guardrails state.
- **Status:** Fully working.
- **Keyless:** Yes (deterministic default guardrails: max-input-length + optional static blocklist).
- **Optional credentials:** None.
- **Limitations:** Default guardrails are deterministic/simple (length + blocklist), not ML-based.

## 9. Evaluations

**Datasets + Deterministic Evaluation Runs**
- **Purpose:** Create datasets, run evaluators, view aggregate + per-item scores.
- **Backend modules:** `observability` Evaluation_Framework (deterministic evaluators), `api/routers/evaluations.py`, migrations.
- **Frontend:** `features/evaluations/EvaluationsView`, `ScoreBars`.
- **Endpoints:** `POST /evaluations/datasets`, `GET /evaluations/datasets`, `POST /evaluations/runs`, `GET /evaluations/runs/{run_id}`.
- **User workflow:** Create dataset → run named evaluators over it → aggregate + per-item scores; `404` for missing dataset/run.
- **Status:** Fully working.
- **Keyless:** Yes (deterministic evaluators).
- **Optional credentials:** None.
- **Limitations:** Create dataset/run gated behind `run_agents`; evaluators are deterministic.

## 10. Integrations (Phase 8)

**Slack / Gmail / Google Drive / GitHub tools + status**
- **Purpose:** Expose third-party services as pluggable agent tools behind the Tool interface.
- **Backend modules:** `integrations/base` (Integration_Tool, Connector ABC, error vocabulary), `integrations/{slack,gmail,google_drive,github}` (Disabled/Keyed/Mock connectors), `integrations/status`, `integrations/connection` (+ migration 0011), `integrations/governance`; wired in `config/container`; `api/routers/integrations.py`.
- **Frontend:** No dedicated UI page in v1 (backend + status API only). Enabled tools become available to agent/multi-agent runs.
- **Endpoints:** `GET /integrations/status` (RBAC-gated, org-scoped, `{name, enabled}`).
- **Tools/actions:** Slack (read_channel/post_message), Gmail (search/read/send), Drive (list/search/read — read-only), GitHub (search_code/search_issues/read_repo/create_issue).
- **User workflow:** Set the integration's `SecretStr` token → tool auto-registers → agents can invoke it; `/integrations/status` shows which are enabled.
- **Status:** Disabled by default.
- **Keyless:** Runs (all disabled — never invoked, no network).
- **Optional credentials required to enable:** `SLACK_BOT_TOKEN`, `GMAIL_TOKEN`, `GOOGLE_DRIVE_TOKEN`, `GITHUB_TOKEN` (+ per-integration enable toggles).
- **Limitations:** No frontend management UI in v1; connectors are deterministic stand-ins for real HTTP in this build; bounded timeout + result cap; single-write actions gated by `run_agents`; OAuth flows/webhooks out of scope; org connection config is non-secret only.

## 11. Admin (Enterprise controls)

**Orgs, Teams, Members, API Keys, RBAC, Tenancy, Rate Limiting**
- **Purpose:** Multi-tenant org management, role-based access, org-scoped API keys, per-principal rate limiting.
- **Backend modules:** `enterprise/{principal,rbac,tenancy,models}`, auth service, Redis rate limiter, `api/routers/orgs.py`, migrations.
- **Frontend:** `features/orgs/MembersView` (roster with role reassignment + member removal, team list/create/delete, team-member add/remove — all confirmed for destructive actions), `ApiKeysView` (list/create/revoke, one-time secret + copy); `Can` RBAC gate; `OrgContextBadge`, `OrgSwitcher`.
- **Endpoints:** `POST /orgs`; members — `GET/POST /orgs/{org_id}/members`, `PATCH/DELETE /orgs/{org_id}/members/{user_id}`; teams — `GET/POST /orgs/{org_id}/teams`, `DELETE /orgs/{org_id}/teams/{team_id}`, `GET/POST /orgs/{org_id}/teams/{team_id}/members`, `DELETE /orgs/{org_id}/teams/{team_id}/members/{user_id}`; API keys — `GET/POST /orgs/{org_id}/api-keys`, `DELETE /orgs/{org_id}/api-keys/{key_id}`.
- **RBAC:** roles owner ⊇ admin ⊇ member ⊇ viewer over `read`, `run_agents`, `ingest_documents`, `manage_api_keys`, `manage_members`. Cross-tenant access → 404 (never 403).
- **Status:** Fully working.
- **Keyless:** Yes (rate limiting NoOp without Redis-enabled; Redis present in compose).
- **Optional credentials:** None.
- **Invariants:** an organization always retains at least one `owner` — a demotion or removal that would remove the last one is refused with `last_owner` (400), checked inside the writing transaction; removing a member also drops their team memberships in that org only; every team read/write is scoped by `org_id`, so another tenant's team is 404.
- **Limitations:** roles are the fixed set `owner|admin|member|viewer` (no custom roles); there is no invite flow — a user must already exist before being added by email; `manage_members` is granted to `owner` only; API-key secret shown once, never persisted client-side.

## 12. Deployment (Phase 9)

**One-command Docker stack, production overlay, CI/CD**
- **Purpose:** Package the whole platform (frontend + backend + postgres + redis behind nginx) for local and production, with CI/CD.
- **Backend/infra modules:** root `Dockerfile` (multi-stage, non-root), `frontend/Dockerfile`, `nginx/` (proxy, SSE-safe, TLS/HTTP, security headers), `docker-compose.yml`, `docker-compose.production.yml`, `.env.production.example`, `scripts/scan_secrets.py`, `.github/workflows/ci-cd.yml` (test→build→publish→deploy), migration runner (auto on startup + one-shot `migrate`).
- **Frontend:** runtime `config.js` + `resolveConfig` (build-once/run-anywhere).
- **Ops endpoints:** `GET /health/live`, `GET /health/ready` (via proxy).
- **User workflow:** `docker compose up --build` → full platform at http://localhost, keyless, migrations auto-applied; production overlay injects secrets + TLS + GHCR images; rollback by pinning a prior immutable image tag.
- **Status:** Fully working locally (one-command).
- **Keyless:** Yes.
- **Optional credentials (production):** `JWT_SECRET` (required), DB creds, TLS certs, optional provider keys.
- **Limitations:** Backend image is large (~11–12 GB, CUDA torch) because the CPU-wheel CDN is unreachable in CI — CI relocates Docker storage to `/mnt` to build it; CPU-slim image deferred. Compose-smoke + migration-idempotence properties (2 & 3) are integration-lane/runtime-gated. No Kubernetes/managed-cloud/DNS/real-cert-issuance in v1 (documented as external).

## Cross-cutting capabilities

- **Uniform error envelope** `AppError { error: {code, message, details} }` across all APIs; frontend normalizes via `mapError`/`ErrorBanner`.
- **SSE streaming** with exactly-one-terminal invariant (single & multi-agent).
- **Conversation context** (`POST /conversations`, `GET /conversations/{id}`) threading `conversation_id` into agent + multi-agent runs.
- **Premium frontend platform:** dark/light theming (design tokens, no-FOWT), command palette (⌘K, RBAC-gated), keyboard shortcuts, responsive app shell, skeleton/empty/error states, markdown+citations, Monaco, charts — all lazy-loaded.
- **Observability everywhere:** trace recorder + pluggable exporter (NoOp keyless / LangSmith with key), never changes run outcomes.
- **Testing posture:** backend keyless lane (472 tests) + Hypothesis properties; frontend `npm run ci`; deterministic, keyless.

## Known v1.0 limitations / open items

- LLM output deterministic without `GROQ_API_KEY`; tracing export NoOp without `LANGSMITH_API_KEY`; web search & all integrations disabled without their keys.
- No frontend UI for integrations management yet (status API only).
- `frontend/openapi.json` predates Phase 8's `/integrations/status` (contract-freshness gap; the SPA doesn't call that endpoint) — optional regen.
- Manual final checkpoints (frontend Task 30, deployment Task 13) left unchecked for human sign-off; deployment Properties 2 & 3 run only in the integration lane / real Docker host.
- Backend container image size (CUDA torch) — CPU-slim optimization deferred.
