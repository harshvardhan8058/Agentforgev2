# AgentForge

**AgentForge is an enterprise, multi-tenant, multi-agent AI platform** — a
grounded RAG engine, single- and multi-agent orchestration with live streaming,
third-party tool integrations, a prompt registry, guardrails, evaluations, and
usage analytics, all behind enterprise authentication and strict per-organization
isolation, with a premium React operator console.

It runs **keyless by default**: the entire platform — and its full test suite —
boots and passes with **zero credentials and zero external API calls** (a
deterministic fallback LLM, local embeddings, an in-process vector store, and
disabled integrations). Supply real credentials only when you want to enable a
hosted model or a specific integration.

- New here? Jump to **[Quick start](#quick-start-one-command-keyless)**.
- Building on it? See **[Local development](#local-development)** and the
  **[Architecture overview](docs/ARCHITECTURE_OVERVIEW.md)**.
- Shipping it? See **[Deployment](docs/DEPLOYMENT.md)** and
  **[Infrastructure](docs/INFRASTRUCTURE.md)**.

---

## Highlights

| Capability | What it does |
|---|---|
| **Grounded RAG** | Document ingestion → chunking → embeddings → pgvector retrieval → cited, grounded answers. Never fabricates a source. |
| **Single-agent runs** | A bounded reason → act → observe loop over a pluggable tool registry, streamed live over SSE with a full trace. |
| **Multi-agent orchestration** | A Planner → Researcher → Writer → Critic collaboration with per-role streaming and human-approval checkpoints. |
| **Integrations** | Slack, Gmail, Google Drive, and GitHub as pluggable tools — **disabled unless a credential is supplied**, so keyless stays keyless. |
| **Prompt registry** | An immutable, versioned prompt store with diffing and safe variable rendering. |
| **Guardrails** | A safety pipeline applied to every answer, with transparent flags. |
| **Evaluations** | Curated datasets and evaluators to measure answer quality over time. |
| **Analytics** | Per-organization token usage and cost, verbatim and provider-attributed. |
| **Enterprise auth & tenancy** | JWT + API keys, an RBAC map (owner ⊇ admin ⊇ member ⊇ viewer), and **strict per-`org_id` isolation** enforced at the data-access layer. |
| **Operator console** | A React + TypeScript SPA (Linear/Vercel-class UX) — command palette, dark/light themes, WCAG 2.1 AA, and route-level code splitting. |

A per-feature breakdown lives in **[docs/FEATURE_INVENTORY.md](docs/FEATURE_INVENTORY.md)**.

## Architecture

AgentForge follows **Clean / Hexagonal Architecture**: business logic depends
only on abstract ports (LLM provider, vector store, embedding provider, document
store, identity/API-key stores, tool interface), and concrete adapters are
selected by a single composition root. The keyless `local` profile and the
`production` profile wire the same seams to different adapters, so the app is
fully runnable and testable without external services.

```
┌──────────────┐   HTTP + SSE    ┌─────────────────────────────────────────┐
│  React SPA   │ ───────────────▶│  FastAPI backend                        │
│ (operator    │                 │  auth · RAG · agents · multi-agent ·     │
│  console)    │◀─────────────── │  integrations · prompts · guardrails ·  │
└──────────────┘   typed client  │  evaluations · analytics                │
                                  └───────────────┬─────────────────────────┘
                                     ┌────────────┴───────────┐
                                     ▼                        ▼
                              PostgreSQL + pgvector        Redis
                              (documents, chunks,          (rate limiting,
                               embeddings, tenancy)         ephemeral state)
```

The React client is **UI-only**: its typed API surface is generated from the
backend's OpenAPI schema, so it can never drift from the shipped contracts.
Full detail: **[docs/ARCHITECTURE_OVERVIEW.md](docs/ARCHITECTURE_OVERVIEW.md)**.

## Requirements

- **Docker + Docker Compose** — for the one-command full-platform start.
- **Python 3.11+** — for backend development without Docker.
- **Node.js 22+** — for frontend development.

## Quick start (one command, keyless)

Bring up the **entire platform** — frontend, backend, PostgreSQL (pgvector), and
Redis behind an nginx entry point — with a single command and **no credentials**:

```bash
docker compose up --build
```

Everything is reachable same-origin through the proxy at **http://localhost**:
the SPA at `/`, and the API/SSE under their route prefixes (`/health`, `/auth`,
`/query`, `/agent`, …). Schema migrations run automatically on backend startup,
and the proxy only begins serving once every service reports healthy.

Verify readiness through the proxy:

```bash
curl http://localhost/health/ready
# -> {"status":"ready","dependencies":{"database":"up","redis":"up"}}
```

Then open **http://localhost**, create an organization on the register screen,
and you are in the console — no API key required.

> Liveness is at `http://localhost/health/live`. In this stack the API is reached
> **through the proxy** (`http://localhost/...`); it is not published directly on
> the host. For direct API access during development, run the backend outside
> Docker (see [Local development](#local-development)).

## Local development

### Backend (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # keyless defaults; no secrets required
uvicorn agentforge.main:app --reload --port 8000
```

Required non-secret settings are `DATABASE_URL` and `REDIS_URL`; every credential
(`GROQ_API_KEY`, `HOSTED_EMBEDDING_API_KEY`, integration tokens) is **optional** —
leave it blank to run keyless. If a required setting is missing, startup aborts
and names the missing setting. Full matrix: **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

### Frontend

```bash
cd frontend
npm install
npm run dev                   # Vite dev server with HMR, defaults to the API at :8000
```

The only client configuration is the non-secret Backend_API base URL
(`VITE_API_BASE_URL`, default `http://localhost:8000`). No credential is ever
read by or embedded in the client. See **[frontend/README.md](frontend/README.md)**
for the design system, layering, and full script list.

## Testing & quality gates

Both lanes are **keyless and deterministic** — no external service or credential.

### Backend

```bash
pytest -m 'not integration' -q      # unit + property suites (the default gate)
python scripts/check_openapi.py     # OpenAPI contract-drift check
python scripts/scan_secrets.py      # repo-wide secret scan
pytest -m integration               # Postgres/Redis/Docker-backed tests (stack up)
```

### Frontend

```bash
cd frontend
npm run ci      # codegen-check → lint → typecheck → unit tests → build → bundle-secret scan
npm run e2e     # Playwright E2E in a real browser (see note below)
```

- **Unit / component / property** — Vitest + React Testing Library + MSW +
  fast-check.
- **Lint** — ESLint 9 (typescript-eslint + React Hooks + jsx-a11y).
- **E2E** — Playwright drives the real production build in headless Chromium with
  the API mocked at the network layer (auth, navigation, RAG, documents,
  responsive, and WCAG 2.1 AA axe scans). First run:
  `npx playwright install --with-deps chromium`.

### Continuous integration

`.github/workflows/ci-cd.yml` runs a strictly-chained pipeline —
**test → e2e → build → publish → deploy** — where the keyless `test` and `e2e`
gates must be green before any image is built, published, or deployed. See
**[docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md)** for the pipeline detail.

## Integrations (optional, disabled by default)

Slack, Gmail, Google Drive, and GitHub are pluggable tools that the agent and
multi-agent layers discover through the tool registry. Each is **Disabled** until
its credential is supplied — no outbound call is ever made for a disabled
integration — so the keyless promise holds. Enable one by setting its env-only
token (e.g. `SLACK_BOT_TOKEN`) in `.env`; introspect enablement (RBAC-gated,
never exposing a value) via `GET /integrations/status`.

## Deployment

Production runs the same images under a Compose overlay
(`docker-compose.production.yml`) that selects the `production` profile, injects
secrets at runtime, hardens restart policies, and terminates TLS at nginx. Images
publish to GHCR under a three-tag strategy (`latest` + immutable git SHA +
semver), so a deploy pins an immutable tag and a rollback is a single tag change
plus `pull` + `up -d`.

- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — production deploy, HTTPS, the
  frontend runtime-config mechanism, image tags, verification, and rollback.
- **[docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md)** — topology, services/ports,
  the env-var matrix, healthcheck/startup ordering, and the CI/CD pipeline.

## Repository layout

```
.
├── src/agentforge/        # Backend: FastAPI app, RAG, agents, multi-agent,
│                          #   integrations, enterprise auth/tenancy, adapters
├── migrations/            # Additive SQL schema migrations (run on startup)
├── scripts/               # OpenAPI drift check, secret scan, e2e verification
├── frontend/              # React + Vite + TypeScript operator console
│   ├── src/               #   pure-logic layer, typed API client, feature views
│   └── e2e/               #   Playwright end-to-end suite
├── nginx/                 # Reverse proxy image (same-origin SPA + API)
├── docs/                  # Architecture, configuration, deployment, roadmap
├── docker-compose.yml     # One-command full-platform (keyless) stack
├── docker-compose.production.yml  # Production overlay (secrets, TLS, hardening)
└── .github/workflows/     # CI/CD (test → e2e → build → publish → deploy)
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `docker compose up` exits naming a service (e.g. `agentforge-postgres`) | That container failed its healthcheck. `docker compose logs <service>` shows why; the proxy waits for all services to be healthy before serving. |
| `/health/ready` returns `503` / a dependency `down` | PostgreSQL or Redis is not reachable yet. Wait for startup, or check `DATABASE_URL` / `REDIS_URL`. |
| Backend aborts on startup naming a missing setting | A required non-secret setting (`DATABASE_URL` / `REDIS_URL`) is unset. Copy `.env.example` to `.env`. |
| Login/registration shows **"Unable to reach the server"** | The browser cannot reach the API. In the Docker stack the SPA calls the API **same-origin** through the proxy, so open the app at the proxy's own origin (`http://localhost`), not a different one. If you build the frontend image yourself, set `API_BASE_URL=/` (same-origin) — a hardcoded `http://localhost` breaks when the app is opened via `127.0.0.1`, a LAN IP, or a domain (cross-origin → CORS). Also confirm the `api` container is healthy (`docker compose ps`). |
| Frontend (dev) shows a network error on every call | `npm run dev` targets `http://localhost:8000` by default; start the backend there, or set `VITE_API_BASE_URL` to your API origin. |
| `npm run e2e` fails to launch a browser | Run `npx playwright install --with-deps chromium` once to fetch the browser and OS libraries. |
| An integration seems inactive | It is Disabled until its token is set **and** its enable-toggle is not `false`. Check `GET /integrations/status`. |

## Security posture

- **Keyless by default** — no credential is required to run or test; no secret is
  committed. Every credential is an env-only `SecretStr`, redacted from logs and
  serialized output.
- **Automated secret scanning** — `scripts/scan_secrets.py` (sources, `.env`
  examples, rendered config, and built image layers) and the frontend
  `scan:bundle` (production bundle) both run in CI and must find nothing.
- **Strict tenant isolation** — every tenant-owned store filters by `org_id`;
  cross-tenant reads uniformly return `404`, never another org's data.

## Documentation index

- [Architecture overview](docs/ARCHITECTURE_OVERVIEW.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Feature inventory](docs/FEATURE_INVENTORY.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Infrastructure & CI/CD](docs/INFRASTRUCTURE.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Future roadmap](docs/FUTURE_ROADMAP.md)
- [Frontend guide](frontend/README.md)
