# AgentForge — Session Handoff

**Repo:** `harshvardhan8058/Agentforgev2` · **Branch of record:** `main` ·
**Work in flight:** `feat/v1.1-admin-crud-and-cost-defaults` ([PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2)) ·
**Last updated:** 2026-08-01 (session 3)

> Self-contained: a new session can continue from this file alone. Treat git/PR history as
> truth over prose. `docs/PROJECT_STATE.md` holds the same state in machine-readable form;
> `CHANGELOG.md` lists the v1.1 changes individually.

## 0. What session 3 added (read this first)

Session 3 audited the repository against the products AgentForge is measured by (OpenAI
Platform, Azure AI Foundry, LangSmith, CrewAI Enterprise, Vertex) and ranked **missing
enterprise capabilities** above the remaining v1.1 chores. Two shipped, in dependency order:

1. **An append-only audit trail** (`enterprise/audit.py`, migration `0013`,
   `GET /audit-events`, owner-only `read_audit_log`, console page). Nothing in the platform
   answered *"who changed this?"* — the first question of every compliance review and every
   access-related support ticket. Fifteen administrative actions are now recorded; the trail is
   append-only by construction, cannot hold a credential, records only successful actions, and
   has a configurable fail-open/fail-closed posture.
2. **Spend budgets** (`observability/budget.py`, migration `0014`, `GET/PUT/DELETE /budget`,
   owner-only `manage_budget`, Budget card on Analytics). Cost was measurable and
   *unlimitable*. An owner can now cap monthly spend and have new runs refused with
   `402 budget_exceeded`; budget changes are themselves audited, which is why the trail was
   built first.

Both were reviewed behaviourally after implementation; the audit-trail review found eight real
defects (including metadata admission escaping its own failure guard, and `read_audit_log`
exposing the owner-only roster to admins) which are fixed with regression tests in `d5b50c4`.

**The audit technique that keeps paying:** ask *who calls this*. Session 2 found a seam with
zero callers (`Tracing_Exporter`); session 1 found a store with no HTTP surface
(`Integration_Connection`). Session 3 found the inverse — capabilities with no seam at all —
by listing what comparable products have that this one does not. Both lists are worth
re-running.

## 0b. What session 2 added

Session 2 audited the repo against its own docs and found the same class of defect as
session 1, one level worse: **a seam with no caller at all.**
`grep -rn "\.export(" src` returned zero hits — the `Tracing_Exporter` had a NoOp
implementation, a LangSmith implementation, a factory, a DI accessor, unit tests and two
property tests, and nothing invoked it. `LANGSMITH_API_KEY` changed a log line and exported
nothing, while README/FEATURE_INVENTORY described trace export as working.

That is now real (§2e), reported (`GET /observability/status` + a notice under every trace),
and vendor-neutral (an OTLP exporter behind the same seam). A behavioural review of that work
found ten issues; six were fixed with tests — including a status surface that claimed
`enabled: true` for an OTLP endpoint with the optional extra missing, i.e. the same
"configured but does nothing" defect being recreated inside its own fix — and four are
documented bounds in `docs/KNOWN_LIMITATIONS.md`.

**The audit technique is worth repeating**: for each seam/store/service, ask *who calls it*.
`for f in $(grep -oP '^def \K(get_\w+)' src/agentforge/api/deps.py); do echo "$(grep -rl "$f" src/agentforge/api/routers/ | wc -l) $f"; done | sort -n`
lists DI accessors with no router caller. As of now the remaining zero-caller accessors are
all legitimate (`get_agent_context`, `get_app_context`, `get_observability_context`,
`get_org_id`, `get_rate_limiter`, `get_rbac_policy` are helpers or middleware-level), and
`get_tracing_exporter` is now consumed indirectly through the export service.

## 1. Current state

- `main` is v1.0: Phases 1–9 plus the production-hardening pass, all merged.
- **PR #2 is open** with four v1.1 roadmap items **plus two enterprise capabilities** (audit
  trail, spend budgets) — eleven commits. It carries migrations `0013` and `0014`, both
  additive and idempotent; every earlier commit needed none.
  It requires **no migration**. All local gates are green:
  backend **793**, frontend **445**, Playwright **20**, `check_openapi.py`, `scan_secrets.py`.
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

**d. Trace export — the seam that was never called** (`observability/trace_export.py`,
`routers/observability.py`, `observability/otel_exporter.py`)

The audit that opened this session looked for seams with no HTTP surface (the pattern that
found the integration-connection gap) and found something worse: `grep -rn "\.export(" src`
returned **zero** call sites. The `Tracing_Exporter` seam had a NoOp implementation, a
LangSmith implementation, a settings factory, a DI accessor, unit tests and property tests —
and nothing ever invoked it. `LANGSMITH_API_KEY` changed one startup log line and exported
nothing, while the docs described tracing export as a working, credential-gated feature.

Fixed by a `Trace_Export_Service` that bridges the exporter to the `Trace_Recorder` (the
component that actually owns assembled traces) and is invoked from every run path. The
attachment differs per path so that the run is always finished and its result already
delivered first: a FastAPI background task for the three request/response paths, the
streaming service's new `on_complete` hook for `POST /agent/stream`, and after the frame
iterator for the multi-agent stream. Failures are swallowed at every layer, the path
short-circuits before any store read when export is off, and the DI accessor returns a
*disabled* service when no observability context is wired — an observability concern must
never be able to fail the work it observes.

Then the roadmap's two sub-items: `GET /observability/status` plus a notice under every trace
(so "export is off" is distinguishable from "this run has no steps"), and an OTLP exporter
(one span per run, one child per step, structural attributes only — never the `detail`
payload) behind the same seam, with the OpenTelemetry SDK as an optional `otel` extra.

**e. Self-review fixes** — eight findings from a behavioural review of (a) and (b), each with
a regression test. The two worth knowing about: `COST_RATE_PRESET=` (shipped empty in
`.env.production.example`) made `load_settings` abort, so the production template was
unbootable; and the last-owner predicate froze an *already* ownerless organization, refusing
even the removal of an unrelated member.

## 3. How to verify it (all keyless, no credential)

```bash
python -m venv .venv && . .venv/bin/activate       # Python 3.11
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1"
pip install -e ".[dev]" -c constraints.txt
pytest -m "not integration" -q                      # expect 793 passed, ~2.5 min

cd frontend && npm ci
npm run ci                                          # expect 445 passed
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

## 4b. Notes for whoever runs this next

* **Playwright browsers are not stable across sandboxes.** The pinned Playwright expects
  build `chromium-1228`; a refreshed image shipped `1232`, and every e2e test then failed in
  ~4 ms with "Executable doesn't exist". `npx playwright install chromium` fixes it in a
  couple of minutes — do that before concluding the e2e lane is broken.
* **`npm` may not be on `PATH`** in a fresh shell. Use
  `export PATH="/root/.nvm/versions/node/v22.23.1/bin:$PATH"`.
* **Verify trace export against a real destination.** Everything about the export path is
  covered by tests through the real app with a capturing exporter, but no LangSmith project
  and no OTLP collector has ever received a span from this code. The OTLP mapping is asserted
  against real OpenTelemetry SDK spans via an in-memory exporter, and the LangSmith payload
  by its pre-existing property test, so the risk is in transport/auth, not shape:
  set `OTEL_EXPORTER_ENDPOINT` at a local collector (`docker run otel/opentelemetry-collector`)
  and confirm one `agent.run` span with its children arrives.

## 5. Recommended next steps, in order

1. **Land PR #2.** Watch the `integration` lane specifically (§4.1). If a store method fails
   there, it will be a SQL/type detail, not a design problem — the in-memory equivalents are
   covered by 793 passing tests. The PR is now seven commits and touches four roadmap items;
   splitting it is possible but the commits are independently reviewable and the branch is
   green as a whole.
2. **A notification / webhook seam** — the highest-value next capability, and the one three
   existing features are all waiting for. A budget threshold crossing, a guardrail block, and a
   run completion are the same shape (an org-scoped event that someone outside the console
   needs to hear about), and today all three require somebody to be looking at a page. One
   seam — an org-scoped, RBAC-managed webhook subscription with signed deliveries, bounded
   retries, and a delivery log — serves all of them, and the audit trail already gives it a
   place to record subscription changes. Design note for whoever picks it up: deliveries must
   be off the request path (the trace-export attachment points are the precedent), signatures
   must be HMAC over the raw body with a per-subscription secret that is shown once, and the
   delivery log needs the same keyset pagination the audit trail uses.
3. **Audit export + retention** — a SIEM/CSV export and a retention policy are what an auditor
   asks for immediately after "do you have a trail"; the cursor they need already exists.
4. **Export durability** (from the trace-export work). Export is
   fire-and-forget: a collector that is down during a run loses that run's export, and only
   one destination can be active. A bounded retry, a "re-export this run" endpoint, or a
   fan-out composite exporter are all small, well-bounded additions behind the existing seam.
5. **Deployment DX** (unstarted): rollback runbooks in `DEPLOYMENT.md`, a quickstart, and
   documentation of the integration lane (it is credential-free but needs `pgvector`).
6. **CPU-slim image** (unstarted): the image is already CPU-only and CI-gated at ≤ 4 GB;
   getting materially smaller means serving embeddings from outside the image, which is a
   design change, not a packaging tweak.
7. **Runtime validation on a Docker host** — the standing gate on calling the stack verified:

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
#  Audit Log: every action above appears, newest first, with the actor's email
#  Analytics: set a budget of 0 with action=block -> a new run is refused with 402
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
