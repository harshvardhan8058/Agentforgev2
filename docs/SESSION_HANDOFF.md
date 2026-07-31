# AgentForge — Session Handoff

**Repo:** `harshvardhan8058/Agentforgev2` · **Branch of record:** `main` ·
**Work in flight:** `feat/v1.1-admin-crud-and-cost-defaults` ([PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2)) ·
**Last updated:** 2026-07-31 (session 4)

> Self-contained: a new session can continue from this file alone. Treat git/PR history as
> truth over prose. `docs/PROJECT_STATE.md` holds the same state in machine-readable form;
> `CHANGELOG.md` lists the v1.1 changes individually.

## 0. What session 4 added (read this first)

Session 4 built the capability the previous handoff ranked #1 and three features were waiting
for: **an outbound webhook framework**. The platform could *show* that a run finished, a
document was ingested, or a guardrail refused an input, and could not *tell* anybody — the only
alternative was polling `GET /agent/runs`, which costs a request per interval per tenant to
learn nothing most of the time.

`aa7517b` (feature) + `d3d9e8f` (review fixes):

- **`webhooks/` package** with three seams — subscription store, delivery store, transport —
  and one application service. `base.py` holds the event vocabulary and records, `security.py`
  everything a hostile input reaches (URL admission + HMAC signing), `store.py` the in-memory and
  Postgres pairs, `transport.py` the single outbound-HTTP chokepoint, `emitter.py` the
  match/sign/retry/record service, `events.py` every payload in one place.
- **Six endpoints** behind a new `manage_webhooks` permission (**admin** and above — webhook
  configuration is administrative and discloses no credential, unlike the owner-only audit trail
  and budget): list, register, patch, delete, test-send, and a keyset-paginated delivery log.
  Migration `0015`.
- **Real emission points, in all six places that produce these facts.** This is the part that
  matters: `run.completed`/`run.failed` from single-agent sync *and* stream, multi-agent sync
  *and* stream, *and* the approval decision that terminates a run; `document.ingested` from the
  ingest endpoint; `guardrail.blocked` from every guardrail entry point.
  `tests/api/test_webhook_emission.py` drives the real app end to end so this cannot decay into
  another well-tested abstraction nobody calls.
- **`defer_after_error`** (`api/errors.py`) — a narrow new seam. A guardrail refusal is a
  reportable security event but it *raises*, and FastAPI's background tasks attach to the
  response an endpoint *returns*. Work registered on `request.state` is now run as a background
  task on the `AppError` response. Deliberately narrow: only a **handled** domain error carries
  deferred work, because an unhandled exception means the process is in an unknown state.
- **`Completed_Run`** replaces the bare run id in the SSE completion hook. Post-stream work went
  from one consumer that needed only the id to two; a record lets the next fact be added without
  changing every hook's signature.
- **`docs/WEBHOOKS.md`** — the consumer guide, with the signature-verification recipe in Python
  and Node. `verify_signature()` ships and is tested, so the documented recipe is executable
  rather than prose and the header format cannot drift from the wire.
- **Two things found while building the above:** `Pg_Budget_Store` had shipped with **no
  integration test** (the in-memory store proved the interface; the SQL holding a customer's
  spend ceiling was untested), and the light theme's `--color-success` was at 3.3:1 on white —
  below WCAG AA for text under 18pt, affecting every small success label in the product. Both
  fixed here.

**The self-review found twelve real defects in the feature commit**, all fixed in `d3d9e8f`
with tests. The four worth carrying forward as lessons:

1. **A stdlib call can leak an exception type your error contract does not cover.**
   `urlsplit().port` raises `ValueError` for `:99999`; `getaddrinfo` raises `UnicodeError` for a
   DNS label over 63 characters. Both were reachable with a one-line body and both became a
   `500` for an input the caller could have fixed. If a function's contract is "raises exactly
   `X`", the stdlib calls inside it have to be wrapped.
2. **A docstring is not an implementation.** `transport.py` said the response body is never
   read; `httpx.Client.post` is the *non-streaming* API and buffers the whole thing. Claims
   about resource use need to be checked against the API actually called.
3. **"An org only has a handful of these" is not a bound.** Nothing capped subscriptions per
   org, and every event fans out to all of them serially, so any principal holding `run_agents`
   could make their own runs pay for unbounded outbound HTTP. Now 20, enforced, plus enforced
   ranges on the three delivery settings that the docs described as *the* safety mechanism.
4. **A fake that outlives what it stands for lets a test pass for the wrong reason.** The
   in-memory stores did not mirror migration 0015's cascade, so "deleting a webhook removes its
   delivery log" was assertable and true only in Postgres. The composition root now wires the
   keyless pair together, and a container test asserts the equivalence.

**The audit techniques that keep paying** (each one found a real defect in a different
session): ask *who calls this seam* (session 2: `Tracing_Exporter` had zero callers); ask *what
HTTP surface does this store have* (session 1: `Integration_Connection` had none); ask *what do
comparable products have that this does not* (session 3: no audit trail, no budgets; session 4:
nothing could notify). Session 5 should re-run all three, and add a fourth: **ask which
in-memory store disagrees with its Postgres counterpart.**

## 0b. What session 3 added


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

## 0c. What session 2 added

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
- **PR #2 is open** with the whole v1.1 roadmap list **plus three enterprise capabilities the
  audit ranked above the leftovers** (audit trail, spend budgets, outbound webhooks) — thirteen
  commits, head `d3d9e8f`. It carries migrations `0013`, `0014` and `0015`, all additive and
  idempotent; every earlier commit needed none. All local gates are green:
  backend **1083**, frontend **490**, Playwright **28**, `check_openapi.py`, `scan_secrets.py`.
- The **live-PostgreSQL lane was not run locally** (see §4). PR #2's CI run is its first
  execution, and **five** of its suites are brand new.

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

**e. Enterprise audit trail** (`enterprise/audit.py`, migration `0013`, `GET /audit-events`,
`AuditLogView`)

Usage records answered what a run cost and traces answered what an agent did; nothing answered
**who changed the organization**. 18 administrative actions are now appended org-scoped and
credential-free — the vocabulary is a server-side enum published through OpenAPI, so the
console's filter options are generated rather than hardcoded. Append-only by construction (the
seam has no update or delete); `metadata` admits non-secret scalars only and refuses
credential-named keys; only *successful* actions are recorded; keyset-paginated on
`(created_at, id)`. `read_audit_log` is **owner-only**, matching the owner-only member roster the
trail's metadata would otherwise expose. The failure posture is the operator's:
`AUDIT_LOG_REQUIRED=false` logs at ERROR and lets the action succeed, `true` reports an applied
but unrecorded change as `503 audit_unavailable` — a refusal to *acknowledge*, explicitly not a
rollback, because the mutation and its audit row are separate transactions.

**f. Spend budgets** (`observability/budget.py`, migration `0014`, `/budget`, Budget card)

Cost was measurable and unlimitable. An owner sets a monthly ceiling (`manage_budget`,
owner-only) that either warns or refuses new work with `402 budget_exceeded`. The period is a
calendar month computed from the request's own timestamp — no stored period, no rollover job,
which is where this kind of feature usually breaks. Only the five *spending* endpoints are
gated: reads are never blocked (hiding the data that explains an overage would be perverse) and
neither is an approval decision, because a paused run has already spent most of what it will
spend. Enforcement reads a total cached for `BUDGET_CACHE_SECONDS`, so the overshoot is bounded
and documented rather than discovered; metering fails **open**, because an analytics outage must
not become a total outage.

**g. Outbound webhooks** (`webhooks/`, `routers/webhooks.py`, migration `0015`,
`WebhooksView`, `docs/WEBHOOKS.md`)

Three features produced facts somebody outside the console needed to hear about, and no seam
carried them. Now: subscriptions, HMAC-signed delivery, a per-endpoint delivery log, and a
test-send endpoint, all `manage_webhooks` and all org-scoped in SQL.

The parts a reviewer should look at first:

- **URL admission** (`webhooks/security.py`) is the security-critical half. A webhook URL is
  attacker-controlled by construction — a principal supplies it and the platform then makes a
  request to it from inside its own network — so admission is an **allow-list**: only a globally
  routable unicast address passes, checked over *every* answer the name resolves to, re-checked
  before each delivery attempt (DNS is mutable), with redirects disabled and non-standard ports,
  credentials and fragments refused. The allow-list formulation is the point: a deny-list of
  remembered ranges misses RFC 6598 shared space (`100.64.0.0/10`, used internally by several
  cloud providers), and `is_global` also handles `::ffff:10.0.0.1` so an IPv4-mapped address
  cannot launder an internal target.
- **The emitter's contract** is what makes it safe to call from finished work: it never raises,
  it costs one indexed read when nobody is subscribed, it always runs off the request path, and
  every attempt lands in `webhook_deliveries` with the attempt count, response status, a bounded
  diagnostic and the endpoint-only duration.
- **The signing secret is stored as-is** and returned exactly once. That asymmetry with API keys
  is deliberate: a key is *verified* against an argon2 hash so the original is never needed,
  while a signature must be *produced*. `WebhookSubscriptionResponse` has no `secret` field at
  all, so it cannot leak from a listing or a read-back — by shape, not by handler discipline.
  `KNOWN_LIMITATIONS.md` states plainly that a database compromise discloses these.
- **Payloads carry identifiers and counts, never content** — no answer text, no document text,
  no blocked input. The endpoint is outside this platform's trust boundary and outside the
  tenant's own console auth.

**h. Self-review fixes** — every feature above was reviewed behaviourally after it verified
green, and each review's findings are a separate commit with regression tests. Worth knowing
about, because each is a *class* of defect rather than a typo:

- From (a)/(b): `COST_RATE_PRESET=` (shipped empty in `.env.production.example`) made
  `load_settings` abort, so the production template was unbootable; and the last-owner predicate
  froze an *already* ownerless organization, refusing even the removal of an unrelated member.
- From (d): the status endpoint reported `enabled: true` for an OTLP destination whose optional
  extra was missing — the same "configured but does nothing" defect being recreated *inside its
  own fix*.
- From (e): the metadata admission policy escaped its own failure guard, and `read_audit_log`
  exposed the owner-only roster to admins.
- From (g): twelve defects, summarised with their lessons in §0 — a stdlib call leaking an
  exception type the error contract did not cover, a docstring that the implementation
  contradicted, an unbounded fan-out justified by "an org only has a handful", and an in-memory
  fake that did not mirror its Postgres counterpart's cascade.

## 3. How to verify it (all keyless, no credential)

```bash
python -m venv .venv && . .venv/bin/activate       # Python 3.11
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1"
pip install -e ".[dev]" -c constraints.txt
pytest -m "not integration" -q                      # expect 1083 passed, ~3 min

cd frontend && npm ci
npm run ci                                          # expect 490 passed
npx playwright install chromium && npm run e2e       # expect 28 passed
cd .. && python scripts/check_openapi.py && python scripts/scan_secrets.py
```

Install CPU torch **first**: otherwise `sentence-transformers` resolves the CUDA build and
drags in multi-GB `nvidia-cu*` wheels the runtime never loads. The backend lane loads the real
embedding model once, so its first run downloads ~90 MB.

## 4. What is NOT verified

1. **The live-PostgreSQL lane (`pytest -m integration`).** No database could be started in the
   authoring sandbox — a `pgvector` container was pulled and started but the postmaster exited
   immediately (cgroup/crun limits), so this was deferred. **Five** suites in PR #2 have
   therefore **never executed against real SQL**: `test_pg_admin_crud_parity`,
   `test_pg_connection_update_and_delete_are_org_scoped`, `test_audit_log_integration.py`,
   `test_budget_store_integration.py` and `test_webhook_store_integration.py`.
   They are the first thing to check in CI. Highest-risk constructs in them:
   `= ANY(CAST(:ids AS uuid[]))`, `CAST(:events AS text[])` with `:event = ANY(events)`,
   `COALESCE(:param, column)` partial updates, `(created_at, id) < (:at, CAST(:id AS uuid))`
   row-value keyset comparison, `NUMERIC(20,8)` exactness, `UPDATE … RETURNING`,
   `SELECT … FOR UPDATE/FOR SHARE`, `rowcount` read after the transaction block, and JSONB
   replacement.
2. **Concurrency behaviour.** The `FOR UPDATE` / `FOR SHARE` / lock-ordering choices are
   reasoned from PostgreSQL semantics, not exercised by a concurrent test.
3. **A real Docker host.** `docker compose build` / `up`, all five services healthy, live
   migrations including `CREATE EXTENSION vector`, persistence across `docker compose
   restart`, SSE incremental delivery through nginx, and the production overlay booting with
   real secrets. Unchanged from the previous handoff.
4. **Real integration traffic.** The four connectors are deterministic stand-ins; no OAuth or
   live HTTP exists yet. Stored connection config is operator-facing and is not yet read by
   the connectors themselves.
5. **A real outbound webhook delivery.** Every lane uses a recording transport, so no HTTP
   request has ever left this code for a subscriber. The URL-admission policy *is* exercised
   against real DNS/IDNA behaviour (the malformed-host cases deliberately do not mock the
   resolver), and `Httpx_Webhook_Transport` is covered for the refuse-before-connecting path.
   What is unproven is the wire: point a subscription at a local listener with
   `WEBHOOK_*` defaults (outside the production profile a loopback `http://` URL is admitted for
   exactly this purpose) and check the signature verifies with the recipe in `docs/WEBHOOKS.md`.
6. **Preset rate keys against a live provider response.** A usage record stores the model the
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
   covered by 1083 passing tests. The PR is thirteen commits across the whole v1.1 list plus
   three enterprise capabilities; splitting it is possible but the commits are independently
   reviewable and the branch is green as a whole.
2. **Budget threshold notifications** — the smallest remaining item with real enterprise value,
   and now unblocked. The delivery seam exists; what is missing is *threshold state*. Being over
   budget is a condition that stays **true**, so it cannot be a plain event — it would fire on
   every request that observed it. Design: persist "this org has been told about crossing 80% /
   100% in this period" (a small table keyed by `(org_id, period_start, threshold)`), have the
   `Budget_Guard` compare the crossed thresholds against it, and emit a new
   `budget.threshold_crossed` webhook once per threshold per period from the same off-request-path
   attachment points. Add the event to `Webhook_Event` **and** `Subscribable_Event`, extend
   `EVENT_DESCRIPTIONS` in `WebhooksView.tsx` (a `Record` over the generated union, so `tsc`
   will tell you), and regenerate the contract.
3. **Webhook follow-ups**, in value order: automatic disabling plus alerting after sustained
   delivery failure (today a permanently broken endpoint is a growing pile of `failed` rows
   nobody looks at); manual redelivery of a recorded delivery (the log already holds the data);
   secret rotation with an overlap window where both the old and new secret verify; retention on
   `webhook_deliveries`, the fastest-growing table in the schema; and a dedicated bounded
   executor for outbound delivery, so webhook work cannot consume the worker threads that serve
   requests (a per-org cap and enforced setting ranges hold that line today, which is a bound
   rather than an isolation).
4. **Audit export + retention** — a SIEM/CSV export and a retention policy are what an auditor
   asks for immediately after "do you have a trail"; the cursor they need already exists.
5. **Export durability** (from the trace-export work). Export is
   fire-and-forget: a collector that is down during a run loses that run's export, and only
   one destination can be active. A bounded retry, a "re-export this run" endpoint, or a
   fan-out composite exporter are all small, well-bounded additions behind the existing seam.
6. **Deployment DX** (unstarted): rollback runbooks in `DEPLOYMENT.md`, a quickstart, and
   documentation of the integration lane (it is credential-free but needs `pgvector`).
7. **CPU-slim image** (unstarted): the image is already CPU-only and CI-gated at ≤ 4 GB;
   getting materially smaller means serving embeddings from outside the image, which is a
   design change, not a packaging tweak.
8. **Runtime validation on a Docker host** — the standing gate on calling the stack verified:

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
#  Webhooks: register http://host.docker.internal:9000/hook (loopback http is admitted
#    outside the production profile), Send test -> the listener receives a signed
#    webhook.ping; then run an agent and confirm run.completed arrives and the delivery
#    log shows both. Try https://169.254.169.254/ -> refused with invalid_webhook_url.
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
- Long commit messages go through a file (`git commit -F /tmp/msg.txt`); an inline `-m` with
  backticks and em dashes hung the shell once.
- Delete `semantic-review/`, `frontend/test-results/` and `frontend/playwright-report/` before
  staging — the review tool and Playwright both write into the working tree.
- Two guards fail loudly if a new server-side vocabulary member is added without its client
  mirror: `tests/property/test_rbac_client_mirror.py` parses `frontend/src/auth/rbac.ts`, so a
  new `Permission` must also be added there **and** to `rbac.test.ts` and `Can.test.tsx`; and
  `ACTION_META` in `AuditLogView.tsx` is a `Record` over the generated `Audit_Action` union, so
  a new audit action fails `tsc` until it is described. `EVENT_DESCRIPTIONS` in
  `WebhooksView.tsx` works the same way for subscribable webhook events.
- MSW component tests run with `onUnhandledRequest: "error"`, so a view that fetches a new
  collection needs a default handler; `frontend/e2e/helpers.ts` `mockCommon` needs the same
  route for the Playwright nav sweep.

## 7. Architecture summary (unchanged)

- **Backend:** FastAPI (`agentforge.main:create_app`). `lifespan` loads `Settings`, opens the
  async DB engine + async Redis, runs migrations, then builds the context graphs via the
  single composition root `config/container.py` — the only module naming concrete
  implementations. 18 routers.
- **Keyless defaults:** Fallback LLM, local SentenceTransformer embeddings, Chroma vectors,
  in-memory domain stores — unless `USE_DATABASE=true` / the production profile selects the
  `Pg_*` stores.
- **Data access:** `Pg_*` stores are synchronous, called via `run_in_threadpool`; the async
  engine is reserved for migrations and health checks. Additive migrations `0001`–`0015`.
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
