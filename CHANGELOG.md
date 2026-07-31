# Changelog

All notable changes to AgentForge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely: one section per release,
newest first, grouped by the kind of change. Dates are the date the work landed on `main`.

This file starts at v1.1. Everything before it is v1.0 — Phases 1–9 plus the
production-hardening pass — and is documented per phase in `docs/FEATURE_INVENTORY.md`
with the merged-PR index in `docs/SESSION_HANDOFF.md`.

## [Unreleased] — v1.1 work in progress

Branch `feat/v1.1-admin-crud-and-cost-defaults` ([PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2)).
Closes the v1.1 roadmap items plus the higher-ranked gaps the audit surfaced. Migrations `0013`
(audit events), `0014` (spend budgets) and `0015` (webhooks) are new; every other change reuses
the existing tables.

### Added

- **Outbound webhook framework.** The platform could *show* that a run finished, a document was
  ingested, or a guardrail refused an input — and could not *tell* anybody. Polling
  `GET /agent/runs` was the only alternative, and it costs a request per interval per tenant to
  learn nothing most of the time. New `webhooks/` package with three seams (subscription store,
  delivery store, transport), six endpoints behind a new `manage_webhooks` permission
  (admin-and-above), and migration `0015`:
  - **Events:** `run.completed`, `run.failed`, `document.ingested`, `guardrail.blocked`, plus a
    `webhook.ping` sent only by `POST /webhooks/{id}/test` and deliberately not subscribable.
    Emitted from **all four run paths** (single sync + streamed, multi sync + streamed, and the
    approval decision that terminates a run), the ingest endpoint, and every guardrail entry
    point — so the seam has real callers, not just tests.
  - **Signed deliveries.** `X-AgentForge-Signature: t=<unix>,v1=HMAC-SHA256(secret, "t.body")`,
    Stripe-style so consumers already know it, with the timestamp inside the signed material so
    a captured delivery cannot be replayed. `verify_signature()` ships and is tested, which
    makes the documented verification recipe executable rather than prose.
  - **SSRF-hardened URL admission.** A webhook URL is attacker-controlled by construction, so:
    https-only, no credentials or fragment, default ports, and the host is resolved and refused
    unless **every** answer is globally routable unicast. That is an allow-list, not a
    deny-list — which is what excludes RFC 6598 CGNAT space (`100.64.0.0/10`, used internally by
    several cloud providers) that a hand-written list of "private" ranges misses. Re-validated at
    delivery time because DNS is mutable, redirects never followed, response bodies never read.
  - **Bounded, recorded delivery.** Up to `WEBHOOK_MAX_ATTEMPTS` attempts with exponential
    backoff and a per-attempt timeout; one `webhook_deliveries` row per (event, subscription)
    carrying the attempt count, response status, a bounded diagnostic and the duration.
    `attempts > 1` with `delivered` is how an operator spots a flaky consumer.
  - **The emitter cannot fail the work that triggered it.** It never raises, it costs one indexed
    read when nobody is subscribed, and it always runs off the request path. Payloads carry
    identifiers and counts — never answer text, document text, or the blocked input, because a
    webhook endpoint sits outside this platform's trust boundary.
  - **The signing secret is returned exactly once**, by `POST /webhooks`. No other response model
    has the field, so it cannot leak from a listing or a read-back. Create, update and delete are
    audited (`webhook.created`, `webhook.updated`, `webhook.deleted`); a test send is not.
- **Webhooks console page** (`manage_webhooks`-gated): register, pause/resume, delete, send a test
  delivery, and expand a per-endpoint delivery log that loads only when opened. The event
  checklist is generated from the contract's `Subscribable_Event`, so publishing a new event
  server-side fails the frontend type check rather than silently missing a checkbox. A refused
  test send renders as the *outcome* (status code + diagnostic), not as an application error —
  the consumer's endpoint is what refused.
- **`docs/WEBHOOKS.md`** — the consumer guide: event table, delivery envelope, the
  signature-verification recipe in Python and Node, what an endpoint should do, and the URL
  admission policy stated plainly.
- **`defer_after_error`** in `api/errors.py` — a narrow seam for work that is owed regardless of
  the response status. FastAPI's background tasks attach to the response an endpoint *returns*,
  so an endpoint that raises loses them; a guardrail refusal is a real, reportable security event
  whose subscribers must not be dropped merely because the caller received a 400. Only a handled
  `AppError` carries deferred work — an unhandled exception means the process is in an unknown
  state and is no place to run further side effects.
- **`Pg_Budget_Store` integration test.** It shipped in this cycle without one: the in-memory
  store proved the interface, and the SQL that holds a customer's spend ceiling had no test at
  all. Now covers migration `0014`, exact `NUMERIC` money round-trips (including that a limit
  never returns in scientific notation, which the API renders with `str()`), the `ON CONFLICT`
  upsert preserving `created_at`, both CHECK constraints, the one-budget-per-org primary key,
  and the org cascade.

- **Enterprise audit trail.** The platform could say what a run cost and what an agent did, and
  nothing about **who changed the organization** — the first question of every compliance
  review and access-related ticket. New `Audit_Log` seam (in-memory + Postgres, migration
  `0013`), an `Audit_Service` that records for the acting principal, and `GET /audit-events`
  behind a new owner-only `read_audit_log`. Fifteen actions are recorded across members, teams,
  API keys, integration connections and budgets. Append-only by construction (the seam has no
  update or delete); nothing recorded can be a credential (credential-named metadata keys are
  refused, an API-key event carries the key *prefix*); only successful actions are recorded;
  keyset-paginated on `(created_at, id)`; and the failure posture is the operator's choice —
  fail-open with an ERROR log by default, or `AUDIT_LOG_REQUIRED=true` to report an applied but
  unrecorded change as `503 audit_unavailable`.
- **Audit Log console page** (`read_audit_log`-gated) with action and page-size filters, whose
  option list is generated from the server's own vocabulary through OpenAPI — adding a server
  action fails the frontend type check rather than silently missing a filter.
- **Spend budgets with enforcement.** Cost *observability* became cost *control*: an owner sets
  a monthly ceiling (`PUT /budget`, owner-only `manage_budget`) that either warns or refuses new
  work with `402 budget_exceeded`. The period is a calendar month computed per request (no
  stored period, no rollover job); the enforced total is exactly what `/analytics/usage` shows;
  reads and approval decisions are never blocked; money stays `Decimal` end to end. Enforcement
  is cached for `BUDGET_CACHE_SECONDS` to keep a `SUM` off the request path, with the resulting
  bounded overshoot documented rather than discovered. Migration `0014`.
- **Budget card on the Analytics page** — spent/limit/remaining verbatim, a native `<progress>`,
  a `role="alert"` notice while blocking, owner-only controls, axe-clean.

- **Trace export actually happens.** The `Tracing_Exporter` seam shipped in Phase 6 with a
  NoOp implementation, a LangSmith implementation, a settings-driven factory, a DI accessor
  and its own tests — and **no caller anywhere in `src/`**. Setting `LANGSMITH_API_KEY`
  changed one startup log line and exported nothing. A new `Trace_Export_Service` bridges the
  exporter to the `Trace_Recorder` that owns the traces, and every completed run now goes
  through it: `POST /agent/run`, `POST /agent/stream`, `POST /multi-agent/runs`,
  `POST /multi-agent/runs/{id}/stream`, and the approval decision that terminates a run.
  Export attaches as a background task (after the response is sent) or as the stream's
  completion hook (after the single terminal event), so it adds no latency and cannot change
  a run's outcome; with no destination configured it short-circuits before even reading the
  trace store.
- **`GET /observability/status`** (`read`) reporting whether trace export is on, which
  exporter is active, and its destination label — derived from the wired service, so a
  destination configured without a recorder behind it reports `enabled: false` rather than
  claiming to work. A notice beneath every trace in the console states the same thing, which
  is what removes the "export is off" vs "no traces yet" ambiguity the v1.1 roadmap named.
- **OTLP trace exporter** (`OTEL_EXPORTER_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_HEADERS`)
  behind the same seam, so traces can reach any OpenTelemetry collector instead of one SaaS
  vendor. One span per run with one child span per trace entry, carrying only structural
  attributes — the trace `detail` payload, which can hold prompt and observation text, is
  never exported. The OpenTelemetry SDK is an optional `otel` extra, imported lazily; without
  it the exporter logs once and exports nothing rather than failing runs. LangSmith keeps
  precedence when both are configured, so an existing deployment is never silently
  re-pointed.
- **Member and team administration.** The org surface was create-and-add only; there was no
  way to see who was in an organization, change a role, or remove anybody. Added
  `GET /orgs/{id}/members`, `PATCH|DELETE /orgs/{id}/members/{user_id}`,
  `GET /orgs/{id}/teams`, `DELETE /orgs/{id}/teams/{team_id}`,
  `GET /orgs/{id}/teams/{tid}/members` and
  `DELETE /orgs/{id}/teams/{tid}/members/{user_id}`, all under `manage_members`, with the
  matching `Identity_Store` methods on both the in-memory and Postgres implementations, and
  a fully server-backed `MembersView`.
- **Last-owner invariant.** A demotion or removal that would leave an organization with
  nobody holding `owner` is refused with `last_owner` (400), evaluated over a
  `SELECT … FOR UPDATE` roster inside the writing transaction so concurrent requests cannot
  both slip through.
- **Named cost-rate presets.** `COST_RATE_PRESET` selects a shipped table of published
  per-model prices (`groq-public-2026-07`), so a deployment holding a provider key reports
  real costs without hand-authoring JSON. `COST_RATE_TABLE_JSON` still overrides it pair by
  pair, and `GROQ_MODEL` makes every priced model selectable.
- **`GET /analytics/cost-rates`** (`read`) reporting the effective preset, the per-model
  rates with each entry's source, the default rates, and whether the deployment prices
  anything — resolved through the same function that builds the `Cost_Model`, so reported
  and charged rates cannot drift. Surfaced as a Cost rates panel on the Analytics page.
- **Integration connection configuration.** `Integration_Connection`, its Postgres store and
  migration `0011` shipped in Phase 8 with no HTTP surface at all. Added
  `GET|POST /integrations/connections` and
  `GET|PATCH|DELETE /integrations/connections/{connection_id}` (`read` to list, the new
  `manage_integrations` permission to mutate), `update_config`/`delete` on both store
  implementations, and a Connection settings panel on the Integrations page.
- **Non-secret admission policy** for connection config
  (`integrations/config_policy.py`): credential-shaped keys, recognisable credential values
  (`xoxb-`, `ghp_`, `sk-`, `ya29.`, …), nested structures and oversized payloads are refused
  with `invalid_config` (400), and a refusal never echoes the submitted value.
- **`manage_integrations` permission**, granted from `admin` upwards, plus a property test
  that parses `frontend/src/auth/rbac.ts` and asserts the client RBAC mirror matches
  `enterprise/rbac.py` exactly. Drift there is silent in the worst direction: a permission
  the server grants but the client omits hides a control the caller is authorized to use.
- **Accessibility coverage** for the administration surfaces: axe in jsdom for the populated
  member/team and API-key views, plus a full-page Playwright axe scan of `/members`.

### Changed

- `POST /agent/stream` gained an internal completion hook on the streaming service
  (`on_complete`), invoked after the terminal event. A hook failure is swallowed: emitting a
  second terminal event because a side effect failed would break the single-terminal guarantee
  the stream contract rests on. The hook now receives a `Completed_Run` record (run id,
  termination reason, conversation id, citation count) rather than a bare run id — post-stream
  work grew from one consumer that needed only the id to two, and a record lets the next fact be
  added without changing every hook's signature.
- `apply_input_guardrail` gained an `on_block` callback, invoked with the guardrail's reason
  immediately before the refusal is raised. It is given the *reason*, never the content, because
  the content is exactly what a guardrail decided must not be passed on.
- **`text-success` is darker in the light theme** (`#16a34a` → `#136c33`). At green-600 every
  small success label — the success `Badge`, the "loaded" and "created" confirmations — sat at
  3.3:1 on white, below the 4.5:1 WCAG AA threshold for text under 18pt; a Playwright axe scan
  of the new Webhooks page is what surfaced it. Now 6.5:1 on white and 5.2:1 on the badge's own
  tinted fill, matching the contrast discipline the warning/danger/info roles already had.
- `httpx` moved from a dev dependency to a runtime one: delivering a webhook is product
  behaviour, not test scaffolding.
- Validation errors no longer echo the submitted value (see below), and
  `active_tracing_exporter()` now resolves three destinations instead of two.

### Fixed

- **A malformed webhook URL returned 500 instead of 400.** `urlsplit().port` raises a bare
  `ValueError` for `:99999` or `:abc`, and `getaddrinfo` raises `UnicodeError` for a DNS label
  over 63 characters — both reachable with a one-line request body, both landing in the
  unhandled-exception handler because the router catches only `WebhookUrlRejected`. Admission now
  raises that and nothing else, which also restores the delivery transport's documented
  "MUST NOT raise" contract.
- **`https://host:80` was admitted** while the refusal message claimed to check "the default port
  for its scheme": the allowed ports were pooled rather than paired with a scheme.
- **The webhook transport buffered the whole untrusted response body** despite documenting that it
  never reads one — `httpx.Client.post` is the non-streaming API. It now uses `client.stream` and
  closes without touching the body, so an endpoint returning a multi-gigabyte response cannot
  cost this process that memory.
- **Nothing capped webhook subscriptions per organization.** Every emitted event fans out to all
  of them, serially, each with its own retry budget, so any principal holding `run_agents` could
  make their own runs pay for an unbounded amount of outbound HTTP. Capped at 20 with
  `409 webhook_limit_reached`, and the three `WEBHOOK_*` delivery bounds — presented in the
  documentation as the mechanism that keeps a pathological consumer cheap — now have enforced
  ranges instead of accepting `WEBHOOK_MAX_ATTEMPTS=1000` with a 600-second timeout.
- **A failed audit write could orphan a webhook whose secret nobody held.** Under
  `AUDIT_LOG_REQUIRED=true` the registration raised *after* the subscription existed and was
  signing, so the caller got a 503 and never saw the secret — which no endpoint returns twice and
  no endpoint can rotate. The subscription is now deleted again before the error propagates.
- **The audit trail recorded the full webhook URL**, query string included. `admit_metadata`
  screens credential-shaped *key names*, and a webhook URL is frequently itself a bearer
  credential (`?token=…`, a Slack `services/T…/B…/…` endpoint), so the whole value was landing in
  the table read by every auditor an organization invites. Only scheme, host and path are recorded
  now — which is what answers "who pointed a webhook where" anyway.
- **`run.completed` carried a different shape depending on which router emitted it.** The
  approval path omitted `citation_count` and any unknown value was dropped rather than sent as
  `null`, in a module whose stated purpose is that routers cannot classify the same outcome
  differently. Every key is now always present.
- **`duration_ms` included AgentForge's own retry backoff** and was rendered under a column headed
  "Took", so a fast endpoint that returned `500` three times reported ~13 seconds. It now sums
  only the time spent talking to the endpoint.
- **`PATCH /webhooks/{id}` accepted `{"description": null}` as a no-op**: it cleared the
  "supply at least one field" guard, changed nothing (both stores read `None` as "leave alone"),
  returned the old value, and wrote an audit row claiming the field had changed. Refused now, with
  the empty string offered as the way to clear it. The empty-body refusal also carries a `details`
  payload, like every other `validation_error` in this API.
- **The in-memory webhook stores did not mirror migration 0015's cascade**, so deleting a
  subscription left its delivery log behind in the keyless lane while Postgres removed it — a fake
  disagreeing with the thing it stands for, and a test could have asserted the documented
  behaviour and passed for the wrong reason. The composition root now wires the pair together.
- **An index nothing read** (`webhook_deliveries_org_time_idx`) was created on the
  fastest-growing table in the schema; every query filters on `org_id` alongside
  `subscription_id`, which the remaining index already serves.
- **The delivery log could not be paged or refreshed in the console** — it fetched 25 rows once
  and pointed the operator at the API's `before`/`before_id` cursor, shipping the server's
  pagination as a dead end on the one screen that needs it. Now paged with that cursor, with a
  refresh control, and the one-time secret card can be dismissed rather than lingering until
  navigation.
- **Cross-tenant write through team membership (security).**
  `POST /orgs/{id}/teams/{tid}/members` resolved the team only through the store's
  "is the user a member of the team's org?" guard, which a user holding memberships in
  **both** organizations satisfied — so a caller could add a member to a foreign tenant's
  team. The team is now resolved within the caller's org first; a foreign team is a 404.
- **Heading order (WCAG 1.3.1)** in `MembersView` and `ApiKeysView`: card titles are `h3`,
  so with no `h2` above them the document jumped `h1 → h3`.
- **Unordered rosters.** `list_org_members` had no `ORDER BY`, so the roster a client
  rendered could change order between calls; both store implementations now return
  oldest-first, identically.
- **`add_team_member` was not idempotent** across implementations: the in-memory store
  replaced `created_at` while Postgres kept the original row. Both now return the original.
- **Blank optional settings were treated as invalid.** `COST_RATE_PRESET=` (as shipped in
  `.env.production.example`) made `load_settings` abort, because pydantic-settings yields
  `""` rather than `None` — an unbootable production template. Empty and whitespace-only
  values for `COST_RATE_PRESET`, `COST_RATE_TABLE_JSON` and `GROQ_MODEL` now mean "unset".
  A genuinely misspelled preset still aborts startup, naming the setting.
- **Ownerless organizations were frozen.** The last-owner predicate decided on the
  post-state, so an organization that already held no owner refused every removal and
  demotion — including of an unrelated member — under an error that misstated the cause. The
  rule is now about the transition: an organization with no owner cannot lose one.
- **Wrong-team writes after creating a team.** `MembersView` fell back to the first team
  whenever the selected id was absent from the cached list — exactly the state a fresh
  create produces — so the detail card and its "Add to team" write could target a different
  team, and a failed refetch left it that way behind a success toast.
- **Stale team rosters after removing a member.** Removal drops the user from every team in
  the organization, but only the visible team's cache was invalidated.
- **Concurrency hardening in `Pg_Identity_Store`** (reasoned, not yet exercised against a
  live database): `add_team_member`'s membership guard takes `FOR SHARE` so it cannot commit
  alongside a concurrent `remove_membership` and orphan a team membership, and the roster
  lock read is `ORDER BY user_id` so two mutations in one organization cannot deadlock by
  locking the same rows in opposite orders.

### Changed

- `POST /orgs/{id}/teams` now returns `created_at`, so a client can place the created team
  into its list without inventing a timestamp.
- Connection config values are declared as JSON **scalars** in the contract rather than an
  opaque object: it states what the server accepts, rejects nesting at the transport layer,
  and gives generated clients a usable type.
- The client error normalizer classifies the domain 400 refusals (`last_owner`,
  `org_mismatch`, the uniqueness conflicts) as validation-class.
- Documentation corrected where it had drifted from the code: the backend image ships
  CPU-only torch under a CI-enforced 4 GB budget (not ~11–12 GB of CUDA), the committed
  OpenAPI contract is drift-checked in CI rather than "slightly stale", and the integrations
  management UI exists.

- **Credential shapes the connection-config policy missed.** It matched key names by
  substring and values by case-sensitive vendor prefix, so a Slack incoming-webhook URL, a
  DSN with an embedded password, a bare JWT, a lowercase `bearer …` value, an uppercase
  `XOXB-…` and keys named `pat`/`cookie`/`ssh_key` were all accepted — and, because listing
  needs only `read`, then readable by every member of the org. Values are now matched by
  shape (case-folded prefixes, JWTs, PEM blocks, URLs with userinfo, known webhook hosts) and
  key markers are matched per segment, so `folder_path` and `keyboard_shortcut` still pass.
- **Validation failures echoed the submitted value.** The 422 handler returned pydantic's
  error entries verbatim, including the offending `input`, so a credential in a field that
  failed type validation came back in the response body. The handler now allow-lists
  `type`/`loc`/`msg`.
- **`PATCH /integrations/connections/{id}` with no `config` erased every setting** and
  returned 200; `config` is now required, and clearing is done by sending `{}` explicitly.
- **A non-scalar config value would have 500'd the whole list.** The store rejected only
  `SecretStr` while the response model declares scalars, so one unrepresentable row would
  have failed response validation for the entire organization's list. The store now refuses
  non-scalar values.
- **The connection editor rewrote value types.** Rendering with `String(value)` and
  submitting strings turned an untouched `notify: true` into `"true"`; untouched values now
  round-trip with the type they arrived with.

### Known bounds of the audit trail and spend budgets

Documented in `docs/KNOWN_LIMITATIONS.md` rather than implied. Audit: append-only is an
application property (a deployment that must *prove* immutability should revoke
`UPDATE`/`DELETE` on the table); authentication events and IP addresses are not recorded (the
latter deliberately — behind the bundled proxy `X-Forwarded-For` is client-controllable, and
recording a spoofable value an auditor would read as authoritative is worse than recording
none); no retention policy or SIEM export; an actor's identity does not survive a user
deletion. Budgets: one ceiling per org, calendar months only, bounded overshoot within the
cache window, metering fails open, no notifications, and a ceiling can only bite where pricing
is configured.

A self-review of both features fixed, before merge: metadata admission raising *outside* the
failure-posture guard (which turned three ordinary inputs into a 500 on an already-applied
mutation with nothing in the trail); `audit_log_required` claiming to fail closed while keeping
the side effect; `read_audit_log` at admin level exposing the owner-only member roster through
a side door; organization creation leaving no evidence in the acting tenant's trail; a
documented-but-absent keyset cursor; an `actor_id` filter that silently returned nothing for
key actors; an unbounded audit-store connection on the critical path of an applied mutation;
and a frontend "destructive action" list that would have badged the next `*.deleted` action as
benign.

### Known bounds of the new trace-export surface

Documented rather than fixed, and recorded in `docs/KNOWN_LIMITATIONS.md`: "enabled" means
configured **and importable**, not reachable (no health probe); a streamed run the client
aborts is not exported; re-streaming a multi-agent run exports again under the same run id;
and every tenant's spans go to one deployment-wide destination tagged with `org_id`, with no
per-org destination or opt-out.

A self-review of the export work also fixed, before merge: an untimed `force_flush` that
could hold a streamed response open for the SDK's 30-second default after the terminal event
had already been delivered; a status surface that reported `enabled: true` for an OTLP
endpoint configured without the `otel` extra (the exact "configured but does nothing" defect
class this feature set out to remove) — the seam gained an `available()` probe that `enabled`
now consults; a missing-dependency warning logged once per run instead of once, because the
failed provider build was not memoised; an unsynchronised lazy build that could orphan a
`BatchSpanProcessor` thread; the OpenTelemetry spec's own `OTEL_EXPORTER_OTLP_ENDPOINT` /
`OTEL_EXPORTER_OTLP_HEADERS` variable names not being accepted, so a pod with a collector
sidecar's standard variables injected would have exported nothing and warned about nothing;
and a notice with no `aria-live` region, which a screen reader would never announce.

### Known bounds of the new integration-config surface

Documented rather than fixed, and recorded in `docs/KNOWN_LIMITATIONS.md`: the credential
policy is a heuristic (a credential with no recognisable shape under an innocent key name
would be accepted, and the field is org-readable); nothing enforces one connection per
`(org_id, integration)` and there is no per-org row cap; and config replacement is
last-writer-wins with no version or ETag. `manage_integrations` is granted to the `admin`
role, and permissions derive from the role at authentication, so **already-issued API keys
with `role=admin` gain the capability on deploy**.

### Verification

Every gate below was run on the branch: backend `pytest -m 'not integration' -q` → **891
passed**; `cd frontend && npm run ci` → **467 passed**; `cd frontend && npm run e2e` →
**21 passed**; `python scripts/check_openapi.py` and `python scripts/scan_secrets.py` clean.

The live-PostgreSQL lane (`pytest -m integration`) was **not** run: no database could be
started in the authoring environment. New Postgres store behaviour is covered by
`test_pg_admin_crud_parity` and `test_pg_connection_update_and_delete_are_org_scoped`, which
have not yet executed against real SQL.

## v1.0 — 2026-07-09

Phases 1–9 (foundation, core RAG, agentic layer, multi-agent collaboration with human
approval, enterprise controls, production observability, React frontend, third-party
integrations, cloud deployment) plus the production-hardening pass: persistent keyless
domain stores, the documented keyless↔production configuration boundary, SSE through nginx,
a CPU-only backend image under a CI-enforced size budget, and an OpenAPI drift check.

See `docs/FEATURE_INVENTORY.md` for the per-feature inventory and
`docs/SESSION_HANDOFF.md` for the merged-PR index.
