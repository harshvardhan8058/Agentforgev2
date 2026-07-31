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
- **Analytics:** costs are `0.0` until pricing is configured (`COST_RATE_PRESET`, or `COST_RATE_TABLE_JSON` for per-model rates) — the console says so explicitly rather than presenting an unpriced deployment's `$0.00` as a real total, and `GET /analytics/cost-rates` reports the effective rates. Shipped preset rates are the vendor's public list prices at the date in the preset name, so a deployment with negotiated, batch, or cached-input pricing must override the affected pairs. Meaningful charts require actual run volume.
- **Guardrails:** the default pipeline is deterministic and simple (max-input-length + optional static blocklist) — not ML/classifier-based moderation.
- **Evaluations:** evaluators are deterministic; dataset/run creation is gated behind `run_agents`.
- **Integrations:** connectors are deterministic stand-ins for real HTTP in this build; bounded timeout + result cap; single-write actions gated by `run_agents`; OAuth flows and webhooks are out of scope. Per-org connection config is manageable over `/integrations/connections` (and on the Integrations page) but stores **non-secret fields only** — credential-shaped keys/values are refused — and the connectors do not yet read it; it is operator-facing configuration ahead of the live-connector work.
- **Admin:** member and team management is complete (list/add/reassign-role/remove members; list/create/delete teams; list/add/remove team members), but roles are the fixed set `owner|admin|member|viewer` — custom roles and per-resource ACLs are out of scope — and there is **no invite flow**: a user must already exist (self-registered) before being added to an org by email. `manage_members` is granted to `owner` only, so admins cannot administer the roster. An organization always keeps at least one owner (`last_owner`, 400). API-key secrets are shown exactly once and never persisted client-side.

## 3. Deployment & infrastructure limitations

- **Backend image size:** ~11–12 GB because it ships CUDA-enabled torch. The CPU-only wheel CDN is unreachable from CI, so CI relocates Docker's storage to `/mnt` to build the image. A CPU-slim (~3.5 GB) image is deferred to future work.
- **Runtime properties gated:** the compose-smoke and migration-idempotence correctness properties (Properties 2 & 3) run only in the integration lane / against a real Docker host, not in the fast keyless unit lane.
- **No managed-cloud primitives in v1:** Kubernetes/Helm, cloud autoscaling, DNS management, and real TLS certificate issuance are out of scope and documented as external responsibilities. v1 targets `docker compose` (local) and a production compose overlay.

## 4. Contract & testing gaps

- **`frontend/openapi.json` is slightly stale:** it predates Phase 8's `GET /integrations/status`. This is a contract-freshness gap only — the SPA does not call that endpoint — and a regen is optional.
- **Deterministic test posture:** the keyless backend lane (472 tests + Hypothesis properties) and `frontend npm run ci` are the source of truth. Integration-lane tests require external services/credentials and are not part of the default fast lane.

## 5. Manual sign-off items (intentionally open)

- Frontend Task 30 and Deployment Task 13 are final manual checkpoints left **unchecked** for human sign-off.
- Merging release PRs and closing superseded PRs are human GitHub actions performed outside the automated flow.
