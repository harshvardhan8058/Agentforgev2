# AgentForge v1.0 — Known Limitations

> Companion to `FEATURE_INVENTORY.md`. This catalogs the deliberate boundaries and open gaps of the v1.0 release. None of these block the one-command keyless developer experience; they describe where behavior is stubbed, deferred, or opt-in.

## 1. Keyless-mode caveats (cross-cutting)

The platform runs end-to-end with zero credentials. The trade-offs of keyless mode:

| Capability | Keyless behavior | To enable full behavior |
|---|---|---|
| LLM generation | Deterministic **Fallback provider** — answer text is a stable stub, not model-generated prose | `GROQ_API_KEY` |
| Embeddings | Local sentence-transformers (CPU). First run downloads the ~90 MB model over the network | `HOSTED_EMBEDDING_API_KEY` (optional hosted path) |
| Web search tool | Tool is not registered / unavailable to agents | `SEARCH_API_KEY` |
| Integrations (Slack/Gmail/Drive/GitHub) | All disabled — never invoked, no network egress | Per-integration token + enable toggle |
| Tracing export | NoOp exporter (traces recorded in-process, not shipped) | `LANGSMITH_API_KEY` |
| Analytics cost figures | Costs default to `0.0` | Configure `cost_rate_table_json` |
| Rate limiting | NoOp unless Redis-backed limiter is enabled (Redis is present in compose) | `rate_limit_enabled=true` + Redis |

Retrieval, citations, guardrails, RBAC, tenancy, streaming, traces, evaluations, and the full UI are **real** in keyless mode — only the items above degrade to deterministic stand-ins.

## 2. Feature-level limitations

- **RAG:** grounded-answer quality is bounded by the fallback LLM when keyless; retrieval and citation linkage are genuine.
- **Single Agent:** trace detail renders as "unavailable" when the tracing exporter is NoOp; the Web Search tool is absent without `SEARCH_API_KEY`.
- **Multi-Agent:** the human-approval gate is opt-in (`approval_policy=human`); keyless runs auto-approve. Generated content is deterministic without an LLM key.
- **Documents:** upload size is bounded by `max_document_bytes`; error envelopes (413/415/400/422/500) are surfaced but very large corpora are not performance-tuned.
- **Prompt Registry:** prompt-version creation is gated behind the `ingest_documents` permission; versions are immutable by design (no edit/delete).
- **Spend budgets:** an owner can cap monthly spend and have new runs refused, but:
  - **One ceiling per organization.** No per-user, per-team, per-project or per-model budgets,
    and no separate limits for different providers.
  - **Calendar months in UTC only.** No rolling windows and no per-tenant billing anchor;
    both need a billing model the platform does not have.
  - **Bounded overshoot.** Enforcement reads a month-to-date total cached for
    `BUDGET_CACHE_SECONDS` (default 30), so a burst inside that window can exceed the ceiling
    slightly. The alternative — an exact ledger with a lock per run — costs more than it buys.
  - **Metering fails open.** If spend cannot be computed, work proceeds (logged at WARNING),
    because an analytics outage must not become a total outage.
  - **No notifications.** Crossing a threshold is visible on the dashboard and in the API, but
    nothing emails, webhooks, or alerts. Combining this with the audit trail's SIEM export is
    the natural follow-up.
  - **A budget only bites where cost is priced.** With no `COST_RATE_PRESET`/rate table every
    run costs `0`, so a ceiling can never be reached — the Cost rates panel says as much.
  - **Approval decisions are deliberately not gated**, so a paused multi-agent run can always
    be finished even when the org is over budget.

- **Audit trail:** every administrative mutation is recorded and readable at
  `GET /audit-events`, but the bounds are worth knowing before an audit:
  - **Append-only is an application property, not a database grant.** No `UPDATE`/`DELETE`
    statement for `audit_events` exists outside the org cascade, and the seam offers no such
    method — but the application's database role still *could*. A deployment that must prove
    immutability should `REVOKE UPDATE, DELETE ON audit_events` from that role (and, for
    tamper-evidence, ship the rows to a WORM store).
  - **Scope is administrative actions.** Authentication events (login, failed login, token
    refresh), reads, and agent/RAG activity are **not** audited — the last of those is what
    traces and usage records are for. Login auditing is the obvious next addition.
  - **No IP address or user agent is recorded.** Behind the bundled nginx the socket peer is
    the proxy, and `X-Forwarded-For` is client-controllable; recording a spoofable value that
    an auditor would read as authoritative is worse than recording none. Doing this properly
    needs a trusted-proxy configuration, which is deployment-specific.
  - **No retention policy or export.** The trail grows without bound (rows leave only with
    their organization) and there is no CSV/SIEM export yet. Reads *are* paginated — pass the
    last row's `created_at`/`id` back as `before`/`before_id` — but the console renders one
    page at a time and does not follow the cursor yet.
  - **"Fail closed" refuses to acknowledge, it does not roll back.** The audited mutation and
    its audit row are written by different stores in different transactions, and nothing
    spans the two. With `AUDIT_LOG_REQUIRED=true` an unrecordable change is reported as
    `audit_unavailable` (503, `details.applied = true`) *after* the change has been applied,
    which is why the message says not to retry. With the default `false` the action succeeds
    and the entry is lost, logged at ERROR.
  - **An over-long metadata value is truncated, not refused.** A value beyond 256 characters
    (a 320-character email, say) is recorded with a trailing `…`; the alternative — failing an
    already-applied mutation — would be the trail defeating its own purpose.
  - **Actor attribution does not survive a user deletion.** `actor_user_id` is
    `ON DELETE SET NULL` and no label is denormalised onto the event, so an erasure request
    turns that user's rows into an anonymous "Deleted user". Nothing in the product deletes a
    user today, so this is reachable only through a DBA action or a future erasure feature —
    which is exactly the case where attribution matters most.

- **Trace export:** traces are always recorded locally; *export* is off until a destination is configured (`LANGSMITH_API_KEY` or `OTEL_EXPORTER_ENDPOINT`), which `GET /observability/status` and the console both state explicitly. Bounds worth knowing: exactly **one** destination is active (LangSmith wins if both are set — there is no fan-out to several backends); export is fire-and-forget with no retry or queue, so a collector that is down during a run loses that run's export (the trace itself is unaffected, and re-export is not implemented); only structural span attributes are exported, never the trace `detail` payload; and the OTLP path needs the optional `otel` extra, without which it logs once, reports itself unavailable (`GET /observability/status` says `enabled: false`), and exports nothing. Further bounds, all deliberate:
  - **"Enabled" means configured and importable, not reachable.** A wrong collector URL or a revoked key still reports `enabled: true`; deliverability is only discoverable by sending something, and no health probe is implemented.
  - **A streamed run that the client aborts is not exported.** The export hook fires when the consumer asks for the frame after the terminal one, so an abandoned stream skips it. The trace itself is recorded either way.
  - **Re-streaming a multi-agent run exports again** under the same `run_id` (a re-stream re-executes the task), so a backend will show two overlapping span trees for one run id.
  - **One deployment-wide destination for every tenant.** Exported spans are tagged with `org_id`, but all orgs share the operator's single project/collector; there is no per-org destination and no per-org opt-out. Only structural attributes leave (never the trace `detail` payload).
  - **The terminal-approval export path is covered by inspection, not by a test.** Under the keyless stack the orchestrator auto-approves, so `POST /multi-agent/runs` already returns a terminated run and no checkpoint exists for a decision to terminate; the negative side of that condition (a non-terminal decision exports nothing) *is* tested.
- **Analytics:** costs are `0.0` until pricing is configured (`COST_RATE_PRESET`, or `COST_RATE_TABLE_JSON` for per-model rates) — the console says so explicitly rather than presenting an unpriced deployment's `$0.00` as a real total, and `GET /analytics/cost-rates` reports the effective rates. Shipped preset rates are the vendor's public list prices at the date in the preset name, so a deployment with negotiated, batch, or cached-input pricing must override the affected pairs. Meaningful charts require actual run volume.
- **Guardrails:** the default pipeline is deterministic and simple (max-input-length + optional static blocklist) — not ML/classifier-based moderation.
- **Evaluations:** evaluators are deterministic; dataset/run creation is gated behind `run_agents`.
- **Integrations:** connectors are deterministic stand-ins for real HTTP in this build; bounded timeout + result cap; single-write actions gated by `run_agents`; OAuth flows and webhooks are out of scope. Per-org connection config is manageable over `/integrations/connections` (and on the Integrations page) but stores **non-secret fields only** and the connectors do not yet read it; it is operator-facing configuration ahead of the live-connector work. Specific bounds worth knowing:
  - The credential admission policy refuses credential-shaped **keys** (segment- and substring-matched), recognisable credential **values** (vendor prefixes case-folded, JWTs, PEM blocks, URLs with userinfo, known webhook hosts) and non-scalar or oversized values. It is a heuristic, not a proof: a credential with no recognisable shape under an innocent key name (say a bare 32-character hex string as `identifier`) would be accepted, and listing needs only `read`, so treat the field as org-readable configuration.
  - Nothing constrains one connection per `(org_id, integration)`, and there is no per-org row cap. Neither matters while no connector reads the config; both need deciding before one does.
  - Config replacement is last-writer-wins. There is no version/ETag, so two administrators editing the same connection concurrently means the second save silently discards the first's settings.
- **Audit reads are owner-only.** `read_audit_log` is granted to `owner`, not `admin`,
  because the trail's member events carry emails and role assignments and
  `GET /orgs/{id}/members` is itself owner-only — an admin-level trail would have been a side
  door to the roster.

- **Admin:** member and team management is complete (list/add/reassign-role/remove members; list/create/delete teams; list/add/remove team members), but roles are the fixed set `owner|admin|member|viewer` — custom roles and per-resource ACLs are out of scope — and there is **no invite flow**: a user must already exist (self-registered) before being added to an org by email. `manage_members` is granted to `owner` only, so admins cannot administer the roster. An organization always keeps at least one owner (`last_owner`, 400). API-key secrets are shown exactly once and never persisted client-side.

## 3. Deployment & infrastructure limitations

- **Backend image size:** the image carries the local embedding model's dependency tree. It installs **CPU-only torch** from the PyTorch CPU wheel index before the requirements resolve (production hardening B4), and CI asserts the built image is ≤ 4 GB **and** that the venv contains no NVIDIA/CUDA packages. (An earlier build did ship CUDA torch at ~11–12 GB; that is no longer the case.) CI relocates Docker's storage to `/mnt` because the build is multi-GB in flight. A genuinely slim image would require serving embeddings from outside the image.
- **Runtime properties gated:** the compose-smoke and migration-idempotence correctness properties (Properties 2 & 3) run only in the integration lane / against a real Docker host, not in the fast keyless unit lane.
- **No managed-cloud primitives in v1:** Kubernetes/Helm, cloud autoscaling, DNS management, and real TLS certificate issuance are out of scope and documented as external responsibilities. v1 targets `docker compose` (local) and a production compose overlay.

## 4. Contract & testing gaps

- **Contract freshness is enforced, not assumed:** `scripts/check_openapi.py` fails if `frontend/openapi.json` differs from the mounted routes, and `frontend/scripts/check-codegen.mjs` fails if `schema.d.ts` differs from that contract. Both run in CI, so the client cannot reference an endpoint or field the server does not serve.
- **Deterministic test posture:** the keyless backend lane (**793** tests + Hypothesis properties), `frontend npm run ci` (**445**) and the keyless Playwright lane (**20**) are the source of truth. The live-PostgreSQL integration lane (`pytest -m integration`) is credential-free but needs a `pgvector` database, so it runs in CI rather than in the fast local lane.

## 5. Manual sign-off items (intentionally open)

- Frontend Task 30 and Deployment Task 13 are final manual checkpoints left **unchecked** for human sign-off.
- Merging release PRs and closing superseded PRs are human GitHub actions performed outside the automated flow.
