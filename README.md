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
