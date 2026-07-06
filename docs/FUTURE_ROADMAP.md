# AgentForge — Future Roadmap

> Forward-looking plan across three horizons. v1.0 (Phases 1–9) is complete and merged to `main`. This roadmap is directional and non-binding; items may shift as priorities evolve. Every proposed change must preserve the platform's core invariants: keyless-by-default development, deterministic tests, single composition root (`config/container.py`), `org_id` tenancy (cross-tenant → 404), `SecretStr` secrets, the uniform `AppError` envelope, and additive-only migrations.

## v1.1 — Hardening & polish (near-term)

Goal: reduce operational friction and close the small gaps left open in v1.0, without new problem domains.

- **CPU-slim backend image:** publish a ~3.5 GB CPU-only image variant alongside the CUDA image; make the default runtime image lighter for cloud deploys.
- **Integrations management UI:** a frontend page to view `/integrations/status`, toggle enablement, and manage per-integration connection config (non-secret fields).
- **OpenAPI contract refresh:** regenerate `frontend/openapi.json` to include `/integrations/status` and wire a CI freshness check.
- **Admin CRUD completion:** add list/update/remove endpoints for members and list/delete for teams, plus the matching UI, closing the create/add-only gap.
- **Analytics cost defaults:** ship a starter `cost_rate_table_json` and per-model rate presets so cost dashboards are meaningful out of the box.
- **Trace export polish:** graceful UI when tracing is NoOp; optional OpenTelemetry exporter in addition to LangSmith.
- **Docs & DX:** expand `DEPLOYMENT.md` rollback runbooks, add a quickstart, and document the integration-lane test suite.

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
