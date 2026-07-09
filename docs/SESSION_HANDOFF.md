# AgentForge — Session Handoff

**Repo:** `harshvardhan8058/AgentForge` · **Branch of record:** `main` · **Last updated:** 2026-07-09

> Self-contained handoff: a new session can continue from this file alone. Treat git/PR history as truth over the older docs (some are stale).

## 1. Current repository state (actual `main`)
- `main` is the complete, production-ready source of truth. Phases 1–9 + production hardening are all merged. **No open PRs.**
- Last significant merge: **PR #22 (Production Hardening)** → merge commit `1d7a15e`, 2026-07-09.
- Stale docs: `docs/PROJECT_STATE.md` still says "Phase 9 in progress / PR #17 anticipated" (predates merges). Always `git checkout main && git pull` before working.

## 2. Merged PRs and what each introduced
- **#1–#2** — Phases 1–2: FastAPI skeleton, config (all creds optional), Postgres+pgvector, Docker Compose, health checks, core RAG (chunk→embed→retrieve→grounded answer w/ citations), keyless Fallback LLM.
- **#3/#5** — Phase 3 agentic layer: bounded LangGraph agent loop, Tool interface+registry, memory, conversations, SSE streaming, tracing.
- **#6/#9** — Phase 4 multi-agent: supervisor Planner→Researcher→Writer→Critic, bounded rounds/revisions, human-approval gate (auto-approve keyless).
- **#8/#10** — Phase 5 enterprise: argon2+JWT auth, orgs/teams, RBAC, `org_id` multi-tenancy (cross-tenant→404), API keys, Redis rate limiting.
- **#11/#12** — Phase 6 observability: tracing exporter (NoOp/LangSmith), usage/cost, analytics, prompt registry, guardrails, evaluations.
- **#14/#15** — Phase 7 React SPA ("AI-OS console").
- **#16** — Phase 8 integrations: Slack/Gmail/Drive/GitHub pluggable tools (disabled keyless).
- **#17** — Phase 9 deployment: multi-stage non-root images, nginx reverse proxy, unified keyless `docker-compose.yml` + `docker-compose.production.yml`, auto migrations, 4-job CI/CD (GHCR).
- **#18** — docs (limitations/roadmap/architecture).
- **#19** — runtime fixes: `.gitattributes` LF (fixes CRLF entrypoint `exec: no such file`); migration runner uses asyncpg simple query protocol (fixes "cannot insert multiple commands").
- **#20** — Dockerfile strips CRLF from entrypoint at build.
- **#21** — nginx/frontend healthcheck uses `127.0.0.1` (IPv4) not `localhost` (IPv6 `::1` was failing).
- **#22 — Production Hardening (B1–B6):**
  - B1 persistence: `Settings.use_database` + `persist_domain_stores()`; nine store builders DB-backed when `USE_DATABASE=true` OR production; `docker-compose.yml` sets `USE_DATABASE=true` → local stack persists to Postgres, keyless. No new migrations.
  - B2 documented keyless↔production config boundary (`docs/CONFIGURATION.md`, `.env.production.example`).
  - B3 nginx SSE: `proxy_http_version 1.1` + `X-Accel-Buffering no` (+ existing buffering/cache off, 3600s timeouts).
  - B4 CPU-only torch installed before requirements (image target ≤4 GB; CI size gate + CUDA-absence assert).
  - B5 removed stray `Dockerfile.verify`.
  - B6 regenerated `frontend/openapi.json` (+`schema.d.ts`) to include `GET /integrations/status`; added keyless `scripts/check_openapi.py` drift check in CI.
  - Also merged: `Redis_Rate_Limiter` uses a sync redis client (async client caused 500 on every authed endpoint); `RATE_LIMIT_ENABLED=false` default locally.

## 3. Current production-readiness status
- Code complete. Keyless unit lane **484 passed**; frontend `npm run ci` green; `scripts/check_openapi.py` passes; migrations 0001–0011 intact.
- Static audit clean (interface parity, schema match, tenancy for all nine `Pg_*` stores; torch/sentence-transformers version compat).
- NOT yet validated on a real Docker host (see §5). This is the gating item for "verified production ready."

## 4. Remaining known limitations
- LLM answers are deterministic stub without `GROQ_API_KEY`.
- Embeddings download the ~90 MB model on first use (needs network at runtime).
- Web search + all four integrations disabled without keys; tracing export NoOp without `LANGSMITH_API_KEY`.
- Local vector embeddings (Chroma) are ephemeral — NOT one of the ten persisted domain stores; re-ingestion regenerates them. pgvector is used in production profile.
- Member/team management is create/add-only (no list/update/remove endpoints).
- Analytics costs are `0.0` until a rate table is configured.
- Docs stale (see §1).

## 5. Not yet verified on a real Docker host
All require Docker/Postgres (unavailable in the assistant sandbox):
- `docker compose build` — esp. B4: PyTorch CPU index (`download.pytorch.org/whl/cpu`) reachability and image ≤4 GB.
- `docker compose up` → all 5 healthy; live migrations incl. `CREATE EXTENSION vector`.
- B1 persistence live — nine `Pg_*` stores' first real run; data survives `docker compose restart`.
- B3 SSE incremental delivery through nginx; long-lived timeouts.
- Auth / RAG / single-agent / multi-agent / integrations-status live; production overlay boot with secrets.
- Left unchecked for sign-off: production-hardening Task 12, deployment Task 13, frontend Task 30.

## 6. Assumptions made in previous sessions
- B4 CPU CDN reachable from the build environment. History: it once failed in CI with `SSLV3_ALERT_HANDSHAKE_FAILURE`, which led to a temporary CUDA/PyPI build; B4 deliberately returns to the CPU index. Unverified in the user's current environment.
- The nine `Pg_*` stores are correct — verified statically only, never run against a live DB.
- Sandbox has no Docker/Postgres → all runtime checks deferred to the user's host.
- User runs Windows + Docker Desktop (WSL2); PowerShell (no `&&`, no `curl`/`grep`/`head` — use `curl.exe`, `Select-String`).
- Raw `git push`/`fetch` is blocked in the assistant environment; git ops go through the GitHub power tools; pushes go to a branch + PR.

## 7. Docker validation checklist (run on host, from `main`)
```
git checkout main && git pull
docker compose build                                      # B4 risk point
docker image inspect agentforge-api --format '{{.Size}}'  # < ~4e9
docker compose up -d && docker compose ps                 # all 5 healthy
curl.exe http://localhost/health/live
curl.exe http://localhost/health/ready                    # database:up, redis:up
# Browser @ http://localhost:
#  - register + login (Pg_Identity_Store)
#  - docker compose restart -> user still exists (B1 core proof)
#  - Documents: upload -> Query -> grounded answer + citations
#  - Agent Run (streaming) -> live SSE (B3)
#  - Multi-Agent run -> completes
#  - GET /integrations/status (bearer) -> all enabled:false
# On host, close the integration lane:
#  pytest -m integration        # needs a pgvector Postgres
```

## 8. Architecture summary
- Backend: FastAPI (`agentforge.main:create_app`). `lifespan` loads `Settings`, opens async DB engine + async Redis, runs migrations, then builds nine context graphs via the single composition root `config/container.py` — the only place concrete implementations are named; everything else depends on interface seams (Clean/Hexagonal).
- 14 routers: health, ingest, query, documents, conversations, agent, multi_agent, auth, orgs, analytics, prompts, guardrails, evaluations, integrations.
- Keyless defaults: Fallback LLM, SentenceTransformer embeddings, Chroma vectors, in-memory domain stores — unless `USE_DATABASE=true`/production (→ `Pg_*` stores) and credentials present.
- DB access: `Pg_*` domain stores are sync psycopg, called via `run_in_threadpool`; async engine reserved for migrations/health. Additive migrations `0001–0011`. `org_id` tenancy → cross-tenant resolves to 404. Uniform `AppError` envelope. Secrets typed `SecretStr`.
- Frontend: React 18 + Vite SPA; runtime config via `/config.js` (`window.__AGENTFORGE_CONFIG__.apiBaseUrl`); talks to API same-origin through nginx.
- Infra: nginx is the sole published entry (`:80→:8080`), routes `/`→frontend:8080 and API prefixes (+SSE)→api:8000; Postgres+pgvector; Redis. Production overlay adds TLS, GHCR images, secrets, one-shot migrate.

## 9. Known risks
1. B4 build — CPU-torch CDN unreachable from the build network would fail `docker compose build` (highest-likelihood blocker). Fix only if it actually fails.
2. `Pg_*` stores at runtime — first live exercise; a store-specific SQL/serialization quirk could surface only against real Postgres (auth, persistence, prompts, analytics, evaluations, api-keys are the paths to watch).
3. Model download at first embedding requires runtime network egress.
4. Rate limiting is off locally by default; enabling it relies on the sync-redis-client fix (already merged).

## 10. Recommended next steps (priority order)
1. Build on the host and confirm B4 (`docker compose build`); if it fails at torch, that's the one expected fix.
2. `docker compose up` + health; confirm all 5 healthy and migrations applied.
3. Validate B1 persistence (register → restart → still logged-in) and the full runtime matrix (§7).
4. Run the integration lane (`pytest -m integration`) on the host to close Task 12/13/30.
5. Refresh stale docs (`PROJECT_STATE.md` → mark all phases + PR #22 merged; note the three PR #18 docs live on `main`) — docs-only.
6. If all green: the outstanding feature initiative is the Premium UI redesign (unstarted; needs a short visual-identity conversation first — palette/typography/motion/iconography — before any implementation).

## Quick reference
- Env toggles: `PROFILE` (local|production), `USE_DATABASE` (true locally), `RATE_LIMIT_ENABLED` (false locally), `API_BASE_URL` (frontend; `http://localhost` locally), `JWT_SECRET` (required in production, SecretStr from overlay), optional `GROQ_API_KEY`/`SEARCH_API_KEY`/`HOSTED_EMBEDDING_API_KEY`/`LANGSMITH_API_KEY`/integration tokens.
- Keyless backend lane: `pytest -m "not integration" -q` (expect 484). Frontend: `cd frontend && npm run ci`. Contract: `python scripts/check_openapi.py`.

## End of handoff.
