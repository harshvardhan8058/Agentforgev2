# AgentForge — Future Roadmap

> Forward-looking plan across three horizons. v1.0 (Phases 1–9) is complete and merged to `main`. This roadmap is directional and non-binding; items may shift as priorities evolve. Every proposed change must preserve the platform's core invariants: keyless-by-default development, deterministic tests, single composition root (`config/container.py`), `org_id` tenancy (cross-tenant → 404), `SecretStr` secrets, the uniform `AppError` envelope, and additive-only migrations.

## v1.1 — Hardening & polish (near-term)

Goal: reduce operational friction and close the small gaps left open in v1.0, without new
problem domains. Status is tracked per item; `docs/PROJECT_STATE.md` holds the same list in
machine-readable form.

**Done** (on `feat/v1.1-admin-crud-and-cost-defaults`, [PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2)):

- ~~**Admin CRUD completion:**~~ list/update/remove members, list/delete teams, team-member
  list/remove, plus the UI. Also enforced a last-owner invariant and closed a cross-tenant
  team-membership write.
- ~~**Analytics cost defaults:**~~ named per-model rate presets (`COST_RATE_PRESET`,
  shipping `groq-public-2026-07`), `GROQ_MODEL` so every priced model is selectable, and
  `GET /analytics/cost-rates` + a pricing panel so a zero total is explained rather than
  presented as a real figure.
- ~~**Integrations management UI:**~~ per-org **non-secret** connection config over
  `/integrations/connections` behind a new `manage_integrations` permission. Enablement
  deliberately stays a server-credential decision, so there is no in-app "toggle" — the UI
  reports enablement and manages configuration. This also gave the Phase 8
  `Integration_Connection` store its first HTTP surface.

**Already delivered earlier** (the entries below predated production hardening B6):

- ~~**OpenAPI contract refresh:**~~ `frontend/openapi.json` is regenerated and both
  `scripts/check_openapi.py` (server side) and `frontend/scripts/check-codegen.mjs` (client
  side) fail CI on drift.

**Remaining:**

- **CPU-slim backend image:** the shipped image is already CPU-only (no CUDA/NVIDIA packages,
  CI-gated at ≤ 4 GB). Going materially smaller means serving embeddings from outside the
  image — a design change rather than a packaging tweak.
- **Trace export polish:** graceful UI when tracing is NoOp (today a client cannot tell
  "tracing is off" from "no traces yet"); optional OpenTelemetry exporter behind the existing
  `Tracing_Exporter` seam, alongside LangSmith.
- **Docs & DX:** expand `DEPLOYMENT.md` rollback runbooks, add a quickstart, and document the
  integration-lane test suite (credential-free, but needs a `pgvector` database).

## v2.0 — Real integrations & production scale

Goal: move from deterministic stand-ins to real external connectivity and cloud-native operations.

- **Live connectors:** real HTTP + OAuth 2.0 flows for Slack, Gmail, Google Drive, and GitHub, with token refresh, webhooks/event ingestion, and per-org credential vaulting.
- **Kubernetes/Helm:** first-class Helm charts, horizontal pod autoscaling, readiness-gated rollouts, and blue/green or canary deploy strategies (superseding compose for production).
- **Advanced guardrails:** pluggable ML/classifier-based moderation (toxicity, PII, jailbreak detection) behind the existing Guardrail_Pipeline interface, keeping the deterministic default available.
- **Evaluation expansion:** LLM-as-judge evaluators, regression gating in CI, and dataset versioning.
- **Vector store scale:** managed pgvector/dedicated vector DB options, hybrid (BM25 + dense) retrieval, and re-ranking.
- **Multi-region & HA:** stateless backend replicas, read-replica DB support, and Redis clustering.
- **Observability:** full OpenTelemetry traces/metrics/logs, dashboards, and SLO alerting.

## v3.0 — Platform & ecosystem (vision)

Goal: turn AgentForge into an extensible enterprise platform, not just an application.

- **Agent & tool marketplace:** a plugin SDK letting teams publish and install custom agents, tools, and connectors.
- **Custom model support:** bring-your-own-model, fine-tuning workflows, and on-prem / air-gapped deployment profiles.
- **Workflow builder:** a visual multi-agent workflow designer on top of the existing supervisor/role orchestration.
- **Enterprise governance:** SOC 2 / audit-log tooling, data-residency controls, fine-grained ABAC on top of RBAC, and per-org compliance policies.
- **Collaboration:** shared workspaces, run sharing, annotations, and human-in-the-loop review queues at scale.
- **Cost governance:** budgets, quotas, chargeback reporting, and automated model-tier routing by cost/quality.

## Invariants that must survive every horizon

1. Keyless-by-default: the platform must always boot and run a full demo with zero credentials.
2. Deterministic tests: the fast keyless lane stays deterministic and credential-free.
3. Additive migrations only: never rewrite or destructively alter existing migrations.
4. Tenancy safety: cross-tenant access returns 404, never 403.
5. Single composition root: concrete wiring stays in `config/container.py`; call sites depend on seams/interfaces.
6. Secret hygiene: all secrets typed as `SecretStr`; never logged or serialized.
