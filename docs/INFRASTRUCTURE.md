# AgentForge — Infrastructure Reference

This document describes the Phase 9 deployment infrastructure: the topology, the service
list and ports, the environment-variable matrix, the healthcheck/startup-ordering chain,
the container images and their GHCR tags, and the CI/CD pipeline. It is **infrastructure
only** — no application behavior or API contract changes. For the operator procedures
(local start, production deploy, HTTPS, verification, rollback) see
[DEPLOYMENT.md](./DEPLOYMENT.md).

---

## Deployment topology

The browser reaches the platform through a single nginx reverse proxy, which is the sole
external entry point and the TLS termination point. Everything else communicates on an
internal Docker network and publishes no host port.

```
                           ┌──────────────────────────────────────────┐
   Browser  ──HTTP 80 /────▶  Reverse_Proxy (nginx, non-root uid 101)  │
            HTTPS 443       │  sole entry point · TLS termination       │
                           │  security headers · unbuffered SSE        │
                           └───────┬───────────────────────┬──────────┘
                                   │ location /             │ /health,/auth,/agent,
                                   │ (static SPA)           │ /query,... (+ SSE)
                                   ▼                        ▼
                    ┌─────────────────────┐     ┌───────────────────────────┐
                    │  Frontend_Image     │     │  Backend_Image            │
                    │  nginx (non-root)   │     │  uvicorn agentforge.main  │
                    │  static SPA +       │     │  :8000 (API_PORT)         │
                    │  /config.js :8080   │     │  /health/live,/ready      │
                    └─────────────────────┘     └───────┬───────────┬───────┘
                                                        │ asyncpg   │ redis.asyncio
                                                        ▼           ▼
                                             ┌──────────────┐  ┌──────────┐
                                             │ postgres     │  │ redis    │
                                             │ pgvector:pg16│  │ 7-alpine │
                                             │ :5432        │  │ :6379    │
                                             └──────────────┘  └──────────┘
```

Only the Reverse_Proxy publishes a host port. This satisfies the single-entry-point
requirement and makes the proxy the single TLS termination point. Request/response and SSE
bodies are forwarded byte-for-byte, so the HTTP/SSE contract and the `AppError` envelope are
preserved through the proxy.

---

## Service list and ports

| Service | Image / build | Role | Internal port | Host published |
|---|---|---|---|---|
| `nginx` | `nginx/Dockerfile` (`nginxinc/nginx-unprivileged:alpine`) | Reverse_Proxy — sole entry point, TLS termination, security headers, SSE | 8080 (HTTP), 8443 (TLS) | **80** (local); **443** + optional **80** (production) |
| `frontend` | `frontend/Dockerfile` (Node 22 build → non-root nginx) | Static SPA + runtime `/config.js` | 8080 | none (internal) |
| `api` | root `Dockerfile` (multi-stage python:3.11-slim → non-root) | Backend_Service (uvicorn `agentforge.main:app`) | 8000 (`API_PORT`) | none (internal) |
| `postgres` | `pgvector/pgvector:pg16` | Relational + vector store | 5432 | none (internal) |
| `redis` | `redis:7-alpine` | Cache / rate-limit backend | 6379 | none (internal) |
| `migrate` | Backend_Image (production overlay only) | Optional one-shot migration runner (scale-out) | — | none |

Every runtime container runs **non-root**: the backend uses a dedicated `appuser`; the
frontend and proxy use `nginxinc/nginx-unprivileged` (uid 101) listening on the
non-privileged port 8080 (and 8443 for TLS). The container runtime maps the published host
ports (80/443) to those non-root container ports; no process inside any container binds a
privileged port as root.

---

## Environment-variable matrix (local vs. production)

| Variable | Local | Production | Notes |
|---|---|---|---|
| `PROFILE` | `local` | `production` | Existing `Settings.profile`. |
| `API_PORT` | 8000 | 8000 | Backend listen port (default 8000). |
| `DATABASE_URL` | bundled `agentforge:agentforge@postgres` | Secret_Source, non-default creds | Required non-secret DSN. |
| `REDIS_URL` | `redis://redis:6379/0` | Secret_Source | Required non-secret DSN. |
| `JWT_SECRET` | unset (dev secret generated) | **required**, Secret_Source | Production guard aborts boot if missing. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `agentforge` defaults | non-default, Secret_Source | Postgres container credentials. |
| `EMBEDDING_DIMENSION` | 384 | 384 | Must match the migrated vector-column dimension. |
| `API_BASE_URL` (frontend, **new runtime var**) | unset → documented default (same-origin via proxy) | e.g. `https://<host>` or `/` | Consumed by the frontend Runtime_Config `/config.js`; non-secret. |
| `AGENTFORGE_IMAGE_TAG` | n/a (local `build:`) | immutable tag pulled from GHCR | Selects the deployed/rolled-back image set. |
| `GROQ_API_KEY` / `HOSTED_EMBEDDING_API_KEY` / `SEARCH_API_KEY` / `LANGSMITH_API_KEY` | unset (keyless) | optional, Secret_Source | `SecretStr`; keyless-safe defaults; leave blank to keep that capability disabled. |
| `TLS_CERT_PATH` / `TLS_KEY_PATH` | n/a (plain HTTP) | host paths, mounted read-only | Certificate material; never baked into an image. |

All required non-secret settings and optional credentials flow through the existing
`Configuration_Manager` env loading — no separate configuration mechanism is introduced.
Every credential is injected at runtime as an environment variable from a Secret_Source and
is redacted by the existing `SecretStr` typing. Example env files (`.env.example`,
`frontend/.env.example`, `.env.production.example`) enumerate every setting with
**placeholder values only** and contain no real credential.

---

## Healthchecks & startup ordering

Every service defines a Docker healthcheck with explicit `interval`, `timeout`, `retries`,
and `start_period`, and dependent services wait on `depends_on: condition: service_healthy`
so the platform reaches a serving state without race-condition failures.

| Service | Healthcheck | interval / timeout / retries / start_period | Depends on (healthy) |
|---|---|---|---|
| postgres | `pg_isready -U <user> -d <db>` | 10s / 5s / 5 / 10s | — |
| redis | `redis-cli ping` | 10s / 3s / 5 / 5s | — |
| api (backend) | stdlib urllib probe of `/health/live` | 10s / 5s / 5 / **40s** | postgres, redis |
| frontend | `wget -qO- /healthz` | 10s / 3s / 5 / 5s | — |
| nginx (proxy) | `wget -qO- /healthz` | 10s / 3s / 5 / 10s | api, frontend |

- The backend's generous **40s `start_period`** covers on-startup migrations and dependency
  warm-up so a slow first boot does not flap to `unhealthy`.
- The backend starts only after **postgres and redis** are healthy; the proxy starts only
  after the **backend and frontend** are healthy — so the public entry point is unreachable
  until the whole stack has completed startup.
- The container-level backend healthcheck uses `/health/live` (process up). Operators and
  the deployment verification use `/health/ready`, which additionally verifies Postgres and
  Redis and returns **503** listing any down dependency — the "unavailable dependency ⇒ not
  healthy" rule.
- If a dependency never becomes healthy within its retry budget, Compose does not start the
  dependent service.

---

## Container images and GHCR tags

Three images are built from multi-stage, non-root Dockerfiles:

- **`agentforge-backend`** (root `Dockerfile`) — a builder stage installs runtime
  dependencies into a venv before copying `src/` (so a source-only change reuses the cached
  dependency layer); the slim runtime stage carries only the venv + application and runs as
  `appuser`. No build toolchain or dev/test tooling is present.
- **`agentforge-frontend`** (`frontend/Dockerfile`) — a Node 22 stage runs `npm run build`;
  the runtime stage serves only the compiled `dist/` from non-root nginx with the SPA
  fallback, `/healthz`, and the runtime `/config.js` entrypoint. No Node toolchain or
  `node_modules` in the final image.
- **`agentforge-proxy`** (`nginx/Dockerfile`) — non-root nginx carrying the routing/security
  config and SSE-safe proxy behavior; TLS material is mounted at runtime, never baked in.

Images are published to **GHCR** under a **three-tag strategy**: `latest` (moving) and the
full `<git-sha>` (immutable) on every publish, plus `<semver>` (immutable) only on a `v*`
release tag. Production Compose pulls by `${AGENTFORGE_IMAGE_TAG:-latest}`; rollback pins a
prior immutable tag.

### Backend image size — torch installed from PyPI

The backend image installs `torch` / `sentence-transformers` for the default local embedding
provider. `torch` is installed as an ordinary transitive dependency of
`sentence-transformers==5.6.1` **from PyPI** (`files.pythonhosted.org`) during the single
constrained `pip install -r requirements.txt -c constraints.txt` step in the builder stage.

The image does **not** use the PyTorch CPU wheel index
(`--index-url https://download.pytorch.org/whl/cpu`): its wheel downloads redirect to the R2
CDN (`download-r2.pytorch.org`), which is **not reliably reachable from the CI runner** and
fails the TLS handshake (`SSLV3_ALERT_HANDSHAKE_FAILURE`). PyPI is a reliable host, so torch
resolves cleanly there. The trade-off is a **large image**: the PyPI Linux `torch` build
bundles the multi-GB CUDA/NVIDIA (`nvidia-cu13-*`) wheels, which overflow the runner's small
~14 GB root filesystem during layer extraction. To accommodate it, the CI `build` and
`publish` jobs first **free disk space** on `/` and then **relocate Docker's `data-root` to
the runner's large ~65 GB `/mnt` scratch volume** (before buildx is set up) so buildkit has
room for the CUDA-sized layers.

The resolve is kept deterministic and fast by a build-time `constraints.txt` that bounds the
heavy transitive `transformers` dependency to a compatible **range** (never an exact pin that
might not exist upstream), preventing pip's pathological backtracking. This is a
**build-only** change — `pyproject.toml` `[project].dependencies` and all application behavior
are unchanged.

> **Future work:** a CPU-slim `torch` (smaller image, no CUDA payload) is deferred until a
> reliably reachable CPU wheel source is available from the CI runner. Until then the image
> installs the standard PyPI build and CI frees runner disk to accommodate it.

---

## CI/CD pipeline (`.github/workflows/ci-cd.yml`)

The pipeline is four jobs chained with `needs:` so each stage only runs after the prior
stage is green: **`test` → `build` → `publish` → `deploy`**. A failure at any stage stops
all later stages, so nothing is built, published, or deployed for a run whose tests failed.

1. **`test`** (keyless, credential-free) — runs both keyless lanes: the backend
   `pytest -m 'not integration' -q` and the frontend `npm run ci` (codegen check, typecheck,
   tests, build, bundle-secret scan), plus the repo-wide secret scan
   (`scripts/scan_secrets.py`). No secrets are configured in this job.
2. **`build`** (`needs: test`) — builds all three images (backend, frontend, proxy) via the
   multi-stage Dockerfiles with `push: false` to verify they build, then runs the
   image-layer secret scan (`docker save` + `scan_secrets.py --image-tar`) on each built
   image. Runs on every trigger.
3. **`publish`** (`needs: build`) — guarded to run only on the publish trigger (push to
   `main` and `v*` tags); logs in to GHCR and pushes all three images with the three-tag
   strategy.
4. **`deploy`** (`needs: publish`) — guarded and gated on the `production` GitHub Environment
   (manual approval / required reviewers); wraps the rollback-capable
   `compose pull && up -d` promotion command shape. No live infrastructure credentials are
   stored in the repository.

The keyless test lanes never require a credential and are never modified by Phase 9, so CI
results are reproducible without secrets.
