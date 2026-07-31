# AgentForge — Session Handoff

**Repo:** `harshvardhan8058/Agentforgev2` · **Branch of record:** `main` ·
**Work in flight:** `feat/v1.1-admin-crud-and-cost-defaults` ([PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2)) ·
**Last updated:** 2026-07-31

> Self-contained: a new session can continue from this file alone. Treat git/PR history as
> truth over prose. `docs/PROJECT_STATE.md` holds the same state in machine-readable form;
> `CHANGELOG.md` lists the v1.1 changes individually.

## 1. Current state

- `main` is v1.0: Phases 1–9 plus the production-hardening pass, all merged.
- **PR #2 is open** with three v1.1 roadmap items complete (head `43093b2`, four commits).
  It requires **no migration**. All local gates are green:
  backend **711**, frontend **439**, Playwright **20**, `check_openapi.py`, `scan_secrets.py`.
- The **live-PostgreSQL lane was not run locally** (see §4). PR #2's CI run is its first
  execution, and two of its suites are brand new.

## 2. What PR #2 contains, and why each piece exists

**a. Member and team administration** (`Identity_Store`, `/orgs/*`, `MembersView`)

Phase 5 shipped members/teams as create-and-add only: no roster, no role change, no removal.
Added eight store methods (both in-memory and Postgres), seven endpoints under
`manage_members`, and a fully server-backed admin UI. Two invariants live next to the write
rather than in the router, so no future call site can bypass them:

- an organization always retains at least one `owner` (`last_owner`, 400) — checked over a
  `SELECT … FOR UPDATE` roster inside the writing transaction;
- a `Team_Membership` may exist only for a member of the team's org (Req 2.5), so removing a
  membership removes that user's team memberships **in that org only**.

**Security fix in the same commit:** `POST /orgs/{id}/teams/{tid}/members` previously relied
on the store's "is this user a member of the team's org?" guard alone. A user holding
memberships in *both* organizations satisfies it, so a caller could add a member to a foreign
tenant's team. The team is now resolved within the caller's org first (404 otherwise).

**b. Cost pricing** (`cost_presets.py`, `GET /analytics/cost-rates`, `CostRatesPanel`)

Costs defaulted to zero, which is right for the keyless stack but meant a deployment with a
real provider key still reported `$0.00` until someone hand-authored a JSON rate table.
Pricing now resolves *default rates → named preset → explicit table*, with the shipped preset
`groq-public-2026-07` carrying published per-model list prices. Keyless is unchanged and
asserted. `GET /analytics/cost-rates` reports the effective rates through the same function
that builds the `Cost_Model`, so what is reported and what was charged cannot drift.

**c. Integration connection configuration** (`/integrations/connections`, `ConnectionsPanel`)

`Integration_Connection`, its Postgres store, migration `0011`, a container builder and a
FastAPI dependency all shipped in Phase 8 **with no HTTP surface**, so the whole store existed
only in tests. It now backs five endpoints (`read` to list, the new `manage_integrations`
permission to mutate) and a UI panel. `integrations/config_policy.py` refuses
credential-shaped keys/values, nesting and oversized payloads — the schema cannot hold a
secret, but nothing stopped an operator pasting a token in under a key like `token`, where
anyone with `read` could then see it.

**d. Self-review fixes** — eight findings from a behavioural review of (a) and (b), each with
a regression test. The two worth knowing about: `COST_RATE_PRESET=` (shipped empty in
`.env.production.example`) made `load_settings` abort, so the production template was
unbootable; and the last-owner predicate froze an *already* ownerless organization, refusing
even the removal of an unrelated member.

## 3. How to verify it (all keyless, no credential)

```bash
python -m venv .venv && . .venv/bin/activate       # Python 3.11
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1"
pip install -e ".[dev]" -c constraints.txt
pytest -m "not integration" -q                      # expect 711 passed, ~2 min

cd frontend && npm ci
npm run ci                                          # expect 439 passed
npx playwright install chromium && npm run e2e       # expect 20 passed
cd .. && python scripts/check_openapi.py && python scripts/scan_secrets.py
```

Install CPU torch **first**: otherwise `sentence-transformers` resolves the CUDA build and
drags in multi-GB `nvidia-cu*` wheels the runtime never loads. The backend lane loads the real
embedding model once, so its first run downloads ~90 MB.

## 4. What is NOT verified

1. **The live-PostgreSQL lane (`pytest -m integration`).** No database could be started in the
   authoring sandbox — a `pgvector` container was pulled and started but the postmaster exited
   immediately (cgroup/crun limits), so this was deferred. Two suites in PR #2 have therefore
   **never executed against real SQL**:
   `test_pg_admin_crud_parity` and `test_pg_connection_update_and_delete_are_org_scoped`.
   They are the first thing to check in CI. Highest-risk constructs in them:
   `= ANY(CAST(:ids AS uuid[]))`, `UPDATE … RETURNING`, `SELECT … FOR UPDATE/FOR SHARE`,
   `rowcount` read after the transaction block, and JSONB replacement.
2. **Concurrency behaviour.** The `FOR UPDATE` / `FOR SHARE` / lock-ordering choices are
   reasoned from PostgreSQL semantics, not exercised by a concurrent test.
3. **A real Docker host.** `docker compose build` / `up`, all five services healthy, live
   migrations including `CREATE EXTENSION vector`, persistence across `docker compose
   restart`, SSE incremental delivery through nginx, and the production overlay booting with
   real secrets. Unchanged from the previous handoff.
4. **Real integration traffic.** The four connectors are deterministic stand-ins; no OAuth or
   live HTTP exists yet. Stored connection config is operator-facing and is not yet read by
   the connectors themselves.
5. **Preset rate keys against a live provider response.** A usage record stores the model the
   provider reports having *served*; if that string differs from the preset key, usage falls
   back to the default (zero) rate while the pricing panel shows a priced table. Worth one
   check with a real `GROQ_API_KEY`.

## 5. Recommended next steps, in order

1. **Land PR #2.** Watch the `integration` lane specifically (§4.1). If a store method fails
   there, it will be a SQL/type detail, not a design problem — the in-memory equivalents are
   covered by 711 passing tests.
2. **Trace-export polish** (unstarted v1.1 item, cheapest real feature). Two halves: the UI
   currently cannot tell "tracing is off" from "no traces yet", and an OpenTelemetry exporter
   alongside the LangSmith one would drop in behind the existing `Tracing_Exporter` seam.
3. **Deployment DX** (unstarted): rollback runbooks in `DEPLOYMENT.md`, a quickstart, and
   documentation of the integration lane (it is credential-free but needs `pgvector`).
4. **CPU-slim image** (unstarted): the image is already CPU-only and CI-gated at ≤ 4 GB;
   getting materially smaller means serving embeddings from outside the image, which is a
   design change, not a packaging tweak.
5. **Runtime validation on a Docker host** — the standing gate on calling the stack verified:

```bash
git checkout main && git pull
docker compose build
docker image inspect agentforge-backend --format '{{.Size}}'   # < 4e9
docker compose up -d && docker compose ps                      # all 5 healthy
curl -fsS http://localhost/health/ready                        # database:up, redis:up
# In the browser at http://localhost:
#  register + login, then `docker compose restart` -> the user still exists (persistence)
#  Documents: upload -> Query -> grounded answer + citations
#  Agent Run (streaming) -> live incremental SSE through nginx
#  Multi-Agent run -> completes
#  Members: roster, role change, remove; Teams: create/delete, add/remove members
#  Integrations: connection settings save/edit/remove; a token-shaped setting is refused
#  Analytics: Cost rates panel reports "prices nothing" (or the preset, if set)
pytest -m integration        # needs the pgvector database
```

## 6. Environment notes for the next session

- Python **3.11**; install CPU torch before the project (§3). The venv used here lives outside
  the repo.
- `docker` exists in the assistant sandbox but **PostgreSQL will not stay up** in it; do not
  spend time retrying the integration lane locally.
- Raw `git push` is blocked in the assistant environment — pushes go through the GitHub power
  tools, to a branch, with a PR.
- Playwright needs `npx playwright install chromium` once (~114 MB); after that
  `npm run e2e` runs the real production build with the API mocked at the network layer.
- The frontend lane is the only place lint runs (`npm run ci` includes `eslint .`); there is
  no Python linter configured in the repo, so match the surrounding style by hand.

## 7. Architecture summary (unchanged)

- **Backend:** FastAPI (`agentforge.main:create_app`). `lifespan` loads `Settings`, opens the
  async DB engine + async Redis, runs migrations, then builds the context graphs via the
  single composition root `config/container.py` — the only module naming concrete
  implementations. 14 routers.
- **Keyless defaults:** Fallback LLM, local SentenceTransformer embeddings, Chroma vectors,
  in-memory domain stores — unless `USE_DATABASE=true` / the production profile selects the
  `Pg_*` stores.
- **Data access:** `Pg_*` stores are synchronous, called via `run_in_threadpool`; the async
  engine is reserved for migrations and health checks. Additive migrations `0001`–`0012`.
  `org_id` is a required store parameter and appears in the query, so cross-tenant access is
  404, never 403. Domain invariants are enforced next to the write.
- **Contracts:** uniform `AppError` envelope; `SecretStr` secrets; `Decimal` money as exact
  strings; `frontend/openapi.json` + `schema.d.ts` drift-checked in CI.
- **Frontend:** React 18 + Vite SPA; runtime config via `/config.js`; RBAC-gated controls are
  omitted from the DOM; server state keyed by `orgScopedKey` so switching org re-scopes every
  list.
- **Infra:** nginx is the sole published entry (`:80→:8080`), routing `/`→frontend and API
  prefixes (+SSE)→api; Postgres+pgvector; Redis. Production overlay adds TLS, GHCR images,
  secrets, one-shot migrate.

## End of handoff.
