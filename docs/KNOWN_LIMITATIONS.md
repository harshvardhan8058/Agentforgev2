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
- **Integrations:** connectors are deterministic stand-ins for real HTTP in this build; bounded timeout + result cap; single-write actions gated by `run_agents`; OAuth flows and webhooks are out of scope. Per-org connection config is manageable over `/integrations/connections` (and on the Integrations page) but stores **non-secret fields only** and the connectors do not yet read it; it is operator-facing configuration ahead of the live-connector work. Specific bounds worth knowing:
  - The credential admission policy refuses credential-shaped **keys** (segment- and substring-matched), recognisable credential **values** (vendor prefixes case-folded, JWTs, PEM blocks, URLs with userinfo, known webhook hosts) and non-scalar or oversized values. It is a heuristic, not a proof: a credential with no recognisable shape under an innocent key name (say a bare 32-character hex string as `identifier`) would be accepted, and listing needs only `read`, so treat the field as org-readable configuration.
  - Nothing constrains one connection per `(org_id, integration)`, and there is no per-org row cap. Neither matters while no connector reads the config; both need deciding before one does.
  - Config replacement is last-writer-wins. There is no version/ETag, so two administrators editing the same connection concurrently means the second save silently discards the first's settings.
- **Admin:** member and team management is complete (list/add/reassign-role/remove members; list/create/delete teams; list/add/remove team members), but roles are the fixed set `owner|admin|member|viewer` — custom roles and per-resource ACLs are out of scope — and there is **no invite flow**: a user must already exist (self-registered) before being added to an org by email. `manage_members` is granted to `owner` only, so admins cannot administer the roster. An organization always keeps at least one owner (`last_owner`, 400). API-key secrets are shown exactly once and never persisted client-side.

## 3. Deployment & infrastructure limitations

- **Backend image size:** the image carries the local embedding model's dependency tree. It installs **CPU-only torch** from the PyTorch CPU wheel index before the requirements resolve (production hardening B4), and CI asserts the built image is ≤ 4 GB **and** that the venv contains no NVIDIA/CUDA packages. (An earlier build did ship CUDA torch at ~11–12 GB; that is no longer the case.) CI relocates Docker's storage to `/mnt` because the build is multi-GB in flight. A genuinely slim image would require serving embeddings from outside the image.
- **Runtime properties gated:** the compose-smoke and migration-idempotence correctness properties (Properties 2 & 3) run only in the integration lane / against a real Docker host, not in the fast keyless unit lane.
- **No managed-cloud primitives in v1:** Kubernetes/Helm, cloud autoscaling, DNS management, and real TLS certificate issuance are out of scope and documented as external responsibilities. v1 targets `docker compose` (local) and a production compose overlay.

## 4. Contract & testing gaps

- **Contract freshness is enforced, not assumed:** `scripts/check_openapi.py` fails if `frontend/openapi.json` differs from the mounted routes, and `frontend/scripts/check-codegen.mjs` fails if `schema.d.ts` differs from that contract. Both run in CI, so the client cannot reference an endpoint or field the server does not serve.
- **Deterministic test posture:** the keyless backend lane (**711** tests + Hypothesis properties), `frontend npm run ci` (**439**) and the keyless Playwright lane (**20**) are the source of truth. The live-PostgreSQL integration lane (`pytest -m integration`) is credential-free but needs a `pgvector` database, so it runs in CI rather than in the fast local lane.

## 5. Manual sign-off items (intentionally open)

- Frontend Task 30 and Deployment Task 13 are final manual checkpoints left **unchecked** for human sign-off.
- Merging release PRs and closing superseded PRs are human GitHub actions performed outside the automated flow.
