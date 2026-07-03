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
