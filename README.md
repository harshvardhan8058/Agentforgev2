# AgentForge
AgentForge: Enterprise Multi-Agent AI Platform

## Foundation (Phase 1)

This repository currently implements the **Foundation** phase: a FastAPI skeleton,
environment-based configuration, a PostgreSQL + pgvector database with schema
migrations, health checks, and a Docker-based local development environment. The
platform runs **keyless** by default (no paid API key required).

### Requirements

- Python 3.11+
- Docker + Docker Compose (for the full local stack)

### Local install (without Docker)

```bash
# From the repository root
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure the environment

All settings are loaded from environment variables (no secrets are committed).
Copy the example file and adjust as needed:

```bash
cp .env.example .env
```

Required non-secret settings are `DATABASE_URL` and `REDIS_URL`. Every credential
(`GROQ_API_KEY`, `HOSTED_EMBEDDING_API_KEY`) is **optional** — leave them blank to
run keyless. If a required setting is missing, startup aborts and names the missing
setting.

### Run the full stack with Docker

```bash
docker compose up
```

This starts three services — `api`, `postgres` (pgvector), and `redis`. The API
becomes reachable on the documented local port **http://localhost:8000** (override
with `API_PORT`). Schema migrations run automatically on first startup. If a
service fails to start, Docker Compose reports it by name (e.g. `agentforge-api`,
`agentforge-postgres`, `agentforge-redis`).

Verify readiness once the stack is up:

```bash
curl http://localhost:8000/health/ready
# -> {"status":"ready","dependencies":{"database":"up","redis":"up"}}
```

Liveness is available at `http://localhost:8000/health/live`.

### Run the tests

The unit and property suites run standalone without any external infrastructure or
credentials:

```bash
pytest
```

Infrastructure-dependent integration tests (Postgres/Redis/Docker) are marked with
the `integration` marker and are excluded by default. To run them with the stack up:

```bash
pytest -m integration
```


## Web Frontend (Phase 7)

A React + Vite + TypeScript operator console lives in [`/frontend`](./frontend). It is a
**UI-only** client over the already-shipped Backend_API (Phases 1–6): it consumes the
stable HTTP/SSE contracts and introduces **no new backend capability and no backend
contract change**. Its typed API surface is generated from the backend's OpenAPI schema,
so the client can never drift from the shipped contracts.

The console runs **keyless** in test — the full suite is mocked (MSW) and deterministic,
requiring no live backend and no credentials. See
[`frontend/README.md`](./frontend/README.md) for the full details on configuration
(`VITE_API_BASE_URL`, no secrets), the design system, and the pure-logic / feature-view
layering.

### Frontend scripts

```bash
cd frontend
npm install         # install dependencies
npm run dev         # start the Vite dev server with HMR
npm run build       # type-check then produce the production bundle
npm run test        # run the full keyless test suite once (property + component/integration)
npm run typecheck   # tsc --noEmit contract-fidelity type-check
npm run ci          # full local gate: codegen:check -> typecheck -> test -> build -> scan:bundle
```

## Third-Party Integrations (Phase 8)

Phase 8 adds **Slack, Gmail, Google Drive, and GitHub** to AgentForge as pluggable
tools that the agentic (Phase 3) and multi-agent (Phase 4) layers discover through the
existing tool registry. Each integration is an ordinary tool behind the unchanged
`Tool_Interface` — no orchestrator change is required to add them.

| Integration    | Tool name       | Actions                                                        |
|----------------|-----------------|----------------------------------------------------------------|
| Slack          | `slack`         | `read_channel`, `post_message`                                 |
| Gmail          | `gmail`         | `search_messages`, `read_message`, `send_message`              |
| Google Drive   | `google_drive`  | `list_files`, `search_files`, `read_file` (read-only)          |
| GitHub         | `github`        | `search_code`, `search_issues`, `read_repo`, `create_issue`    |

### Keyless-disabled by default

Every integration is **Disabled** unless its credential is supplied, and the platform
runs and passes its entire test suite with **zero integration credentials** — no
outbound network call is ever made for a Disabled integration. This preserves the
keyless promise upheld by every prior phase: existing `RAG_Tool` / `Web_Search_Tool`
and agent / multi-agent behavior are unchanged when no integration is configured.

### Env-only `SecretStr` credentials + enable-toggles

Each integration is enabled by providing its token through an environment-only
`SecretStr` setting (redacted from logs, `repr`, and serialized output, never
persisted). A separate non-secret enable-toggle (default `true`) lets an operator hold
an integration Disabled even when its token is present. An integration is **Enabled**
only when its credential is present **and** its enable-toggle is not `false`:

```bash
# In .env — leave blank (the default) to keep an integration Disabled.
SLACK_BOT_TOKEN=          # enables the Slack tool
GMAIL_TOKEN=              # enables the Gmail tool
GOOGLE_DRIVE_TOKEN=       # enables the read-only Google Drive tool
GITHUB_TOKEN=             # enables the GitHub tool

# Per-integration enable toggles (default true; set false to force Disabled).
SLACK_ENABLED=true
GMAIL_ENABLED=true
GOOGLE_DRIVE_ENABLED=true
GITHUB_ENABLED=true

# Bounded, keyless-safe execution limits shared by every integration tool.
INTEGRATION_TIMEOUT_SECONDS=10
INTEGRATION_MAX_RESULTS=20
```

See `.env.example` for the full list with keyless-safe defaults.

### Introspecting which integrations are enabled

An org-scoped, RBAC-gated endpoint reports each integration's enablement without ever
exposing a credential value:

```bash
# Requires an authenticated principal with the `read` permission.
curl http://localhost:8000/integrations/status
# -> {"integrations":[{"name":"slack","enabled":false}, ... ]}
```

A request with no valid principal is rejected with `401`, and a principal lacking the
`read` permission with `403`, both rendered through the uniform error envelope.


## Deployment & Infrastructure (Phase 9)

Phase 9 packages the whole platform — the FastAPI backend, the Vite/React frontend,
PostgreSQL (pgvector), and Redis — into a production-grade, container-based deployment
behind a single nginx reverse proxy. It is **infrastructure only**: it adds no
application capability and changes no HTTP/SSE API contract, database-schema semantics,
or business logic.

### One-command local start (keyless)

Bring up the **entire** platform — frontend, backend, PostgreSQL, and Redis behind the
nginx entry point — with a single command and **zero credentials**:

```bash
docker compose up --build
```

Everything is reachable same-origin through the proxy at **http://localhost** — the SPA
at `/` and the API/SSE under their route prefixes (`/health`, `/auth`, `/agent`,
`/query`, …). No credential is required or committed: the stack runs under the keyless
`local` profile (deterministic Fallback LLM, local embeddings, disabled web search, NoOp
tracing). Schema migrations run automatically on backend startup, and the proxy only
begins serving after every service reports healthy.

Verify readiness through the proxy once it is up:

```bash
curl http://localhost/health/ready
# -> {"status":"ready","dependencies":{"database":"up","redis":"up"}}
```

> The legacy `docker compose up` backend-only workflow (`http://localhost:8000`,
> described under *Foundation* above) still works for backend-only development; the
> command above is the full-platform one-command start.

### Production, HTTPS, images, and rollback

Production runs the same images under a Compose overlay
(`docker-compose.production.yml`) that selects the `production` profile, injects secrets
from a Secret_Source at runtime, hardens credentials and restart policies, and terminates
TLS at nginx. Images are published to GHCR under a three-tag strategy (`latest` + git SHA
+ semver) so a deploy pins an immutable tag and a rollback is a single tag change plus
`pull` + `up -d`.

Full operator guides:

- **[docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)** — local start, production deploy under
  the `production` profile, enabling HTTPS (mounting certificates), the frontend
  Runtime_Config mechanism, the image-tag strategy, deployment verification, and the
  rollback procedure.
- **[docs/INFRASTRUCTURE.md](./docs/INFRASTRUCTURE.md)** — deployment topology, the
  service list and ports, the env-var matrix (local vs. production), the
  healthcheck/startup-ordering chain, the three images and their GHCR tags, and the
  four-job CI/CD pipeline.
