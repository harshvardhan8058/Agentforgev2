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
- **Analytics:** costs are `0.0` until a rate table is configured; meaningful charts require actual run volume.
- **Guardrails:** the default pipeline is deterministic and simple (max-input-length + optional static blocklist) — not ML/classifier-based moderation.
- **Evaluations:** evaluators are deterministic; dataset/run creation is gated behind `run_agents`.
- **Integrations:** no frontend management UI in v1 (status API only); connectors are deterministic stand-ins for real HTTP in this build; bounded timeout + result cap; single-write actions gated by `run_agents`; OAuth flows and webhooks are out of scope; org connection config stores non-secret fields only.
- **Admin:** member/team management is **create/add-only** — there are no list/update/remove-member or list/delete-team endpoints, so the UI intentionally omits those actions. API-key secrets are shown exactly once and never persisted client-side.

## 3. Deployment & infrastructure limitations

- **Backend image size:** the builder installs a **CPU-only** `torch` from the PyTorch CPU wheel index before resolving the app requirements, so the multi-GB `nvidia-cu*` CUDA payload is never pulled and the image stays under the 4 GB budget. CI still relocates Docker's storage to `/mnt` as a safety margin. GPU inference is therefore **not** available in the shipped image — the embedding model runs on CPU by design.
- **Runtime properties gated:** the compose-smoke and migration-idempotence correctness properties (Properties 2 & 3) run only in the integration lane / against a real Docker host, not in the fast keyless unit lane.
- **No managed-cloud primitives in v1:** Kubernetes/Helm, cloud autoscaling, DNS management, and real TLS certificate issuance are out of scope and documented as external responsibilities. v1 targets `docker compose` (local) and a production compose overlay.

## 4. Contract & testing gaps

- **`frontend/openapi.json` freshness is now enforced, not manual:** the committed contract is regenerated from `app.openapi()` and verified by `scripts/check_openapi.py`, which runs as its own CI step and as a property test. Drift fails the build, so the previously-noted staleness gap is closed.
- **Deterministic test posture:** the keyless backend lane (487 tests + Hypothesis properties) and `frontend npm run ci` are the source of truth. Integration-lane tests require external services/credentials and are not part of the default fast lane.
- **Dev-toolchain advisories remain open:** `npm audit` reports 0 vulnerabilities for **production** dependencies, but 8 high-severity findings persist in build-only tooling (`js-yaml` via `openapi-typescript` → `@redocly/openapi-core`, and `brace-expansion`/`minimatch` via `eslint`). Both are CPU-exhaustion DoS classes reachable only by feeding hostile input to a local codegen/lint run, so they do not affect the shipped artifacts. Clearing them requires an `eslint` major bump; see `SECURITY_MAINTENANCE.md`.

## 5. Manual sign-off items (intentionally open)

- Frontend Task 30 and Deployment Task 13 are final manual checkpoints left **unchecked** for human sign-off.
- Merging release PRs and closing superseded PRs are human GitHub actions performed outside the automated flow.
