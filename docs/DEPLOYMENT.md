# AgentForge — Deployment Guide

This guide covers building, configuring, deploying, verifying, and rolling back the
AgentForge platform. Phase 9 is **infrastructure only** — it changes no application
behavior, HTTP/SSE API contract, database-schema semantics, or business logic. The same
container images run unchanged in local development and in production; only the profile,
secrets, TLS material, restart policy, and image source differ.

The platform is composed of three application images plus two data services, all behind a
single nginx reverse proxy that is the sole external entry point:

- **Reverse_Proxy** (nginx) — routing, SSE streaming, TLS termination, security headers.
- **Frontend_Image** — the compiled Vite/React SPA served by non-root nginx.
- **Backend_Image** — the FastAPI app (`agentforge.main:app`) served by uvicorn.
- **PostgreSQL** (pgvector) and **Redis**.

See [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) for the full topology, service list, ports,
and env-var matrix.

---

## 1. Local one-command start (keyless)

Bring up the entire platform with a single command and **no credentials**:

```bash
docker compose up --build
```

This builds and starts the frontend, backend, PostgreSQL, and Redis, then the nginx proxy.
The stack runs under the keyless `local` profile — deterministic Fallback LLM provider,
local sentence-transformer embeddings, disabled web search, and the NoOp tracing exporter
— so no external network call is made without a credential.

- The browser reaches everything **same-origin** through `http://localhost` (host port 80
  → the proxy's non-root container port 8080). The SPA is served at `/`; the API and SSE
  endpoints are served under their route prefixes.
- Database schema migrations run **automatically** on backend startup (the existing
  additive `run_migrations` runner). No manual step is required.
- The proxy only becomes reachable after the backend **and** frontend report healthy (see
  [Startup ordering](./INFRASTRUCTURE.md#healthchecks--startup-ordering)).

Verify readiness through the proxy:

```bash
curl http://localhost/health/ready
# -> {"status":"ready","dependencies":{"database":"up","redis":"up"}}
```

No certificate material is needed locally — the proxy serves plain HTTP so
One_Command_Startup is preserved.

---

## 2. Production deployment (the `production` profile)

Production runs the **same images** under a Compose **overlay** applied on top of the base
file. The overlay (`docker-compose.production.yml`) selects `PROFILE=production`, sources
all credentials from a Secret_Source at runtime, uses non-default database credentials,
adds `restart: unless-stopped` to every long-running service, enables the nginx TLS server
block, and pulls pinned images from GHCR instead of building.

### 2.1 Supply credentials from a Secret_Source

Copy the placeholder template to a real `.env` on the deployment host and fill in the
values there (Docker Compose auto-reads `.env` for `${VAR}` interpolation). **Never commit
the filled-in `.env`.**

```bash
cp .env.production.example .env
# edit .env on the host, filling in real values
```

`.env.production.example` enumerates every production setting with **placeholder values
only** and no real credential:

| Setting | Purpose |
|---|---|
| `PROFILE=production` | Enforces the `JWT_SECRET` guard; disables dev fallbacks. |
| `AGENTFORGE_IMAGE_TAG` | The immutable GHCR tag to deploy (git SHA or semver). |
| `DATABASE_URL` / `REDIS_URL` | Required non-secret DSNs (host-specific). |
| `JWT_SECRET` | **Required** access-token signing secret; boot aborts if missing. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Non-default DB credentials. |
| `EMBEDDING_DIMENSION` | Must match the migrated vector-column dimension (default 384). |
| `API_BASE_URL` | Frontend Runtime_Config base URL (see §4). |
| `TLS_CERT_PATH` / `TLS_KEY_PATH` | Host paths to cert/key, mounted read-only (see §3). |
| `GROQ_API_KEY` / `HOSTED_EMBEDDING_API_KEY` / `SEARCH_API_KEY` / `LANGSMITH_API_KEY` | Optional `SecretStr` provider keys; leave blank to keep that capability keyless. |

Credentials are injected as environment variables at container runtime only — they are
never baked into an image or committed to version control. The existing `SecretStr` typing
keeps every credential redacted in logs, `repr`, and serialized output. If `PROFILE=production`
and `JWT_SECRET` is absent, the backend's `load_settings` guard raises
`ConfigError(["jwt_secret"], …)` and the container exits non-zero **before serving**.

### 2.2 Pull and start under the overlay

```bash
export AGENTFORGE_IMAGE_TAG=<immutable-tag>   # e.g. a git SHA or v1.4.2
docker compose -f docker-compose.yml -f docker-compose.production.yml pull
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
```

The overlay never runs alone — it is always layered on the base `docker-compose.yml` so the
service graph is defined once and production only overrides profile, secrets, TLS, restart
policy, and image source.

### 2.3 Migrations in production

By default, migrations run **on backend startup** (the additive `run_migrations` runner,
tracked in `schema_migrations`, halting startup and naming the failing id on error). This
is the single-replica default and needs no extra step.

For scale-out (multiple backend replicas), the overlay also defines an optional one-shot
`migrate` service that runs the existing runner once and exits 0; the backend then declares
`depends_on: migrate: condition: service_completed_successfully` so replicas never race
concurrent migrations. Either way the runner stays additive and `schema_migrations`-tracked,
so re-runs and rollbacks are safe.

---

## 3. Reverse proxy routing, TLS termination, and enabling HTTPS

### 3.1 Routing and single entry point

The nginx Reverse_Proxy is the **sole external entry point**. Only the proxy publishes a
host port; the frontend, backend, PostgreSQL, and Redis communicate on the internal Docker
network.

- `location /` → the Frontend_Image (SPA static assets, with SPA history fallback).
- The concrete backend route prefixes (`/health`, `/auth`, `/orgs`, `/agent`, `/query`,
  `/ingest`, `/documents`, `/conversations`, `/multi-agent`, `/analytics`, `/prompts`,
  `/guardrails`, `/evaluations`, `/integrations`) and SSE streaming → the Backend_Image.
- SSE responses are streamed **unbuffered** (`proxy_buffering off;`, `proxy_cache off;`,
  `proxy_http_version 1.1;`, a raised `proxy_read_timeout`, honoring `X-Accel-Buffering:
  no`), so event streams reach the client immediately.
- Request/response bodies are forwarded **unchanged**, so the HTTP/SSE contract and the
  `AppError` envelope are byte-preserved in transit.

The proxy also attaches hardened response **security headers** (additive metadata only,
never altering bodies): `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, and a tunable `Content-Security-Policy`.
`Strict-Transport-Security` (HSTS) is emitted **only from the TLS/production server block**,
never from the plain-HTTP local block.

### 3.2 TLS termination is at the proxy

nginx is defined as the single TLS_Termination point. Certificate and private-key material
are **mounted read-only at runtime** from a Secret_Source — never embedded in any image.

### 3.3 Enabling HTTPS

The TLS server block (`nginx/tls/agentforge-tls.conf`) is carried in the proxy image for
reference but is **not auto-loaded**, so a keyless local `nginx -t` passes without any
certificate material. To enable HTTPS in production:

1. Provide the certificate chain and key on the host and point `TLS_CERT_PATH` /
   `TLS_KEY_PATH` at them in your `.env`.
2. The production overlay mounts them read-only into the proxy and enables the TLS block:

   ```yaml
   volumes:
     - ./nginx/tls/agentforge-tls.conf:/etc/nginx/conf.d/agentforge-tls.conf:ro
     - ${TLS_CERT_PATH}:/etc/nginx/tls/fullchain.pem:ro
     - ${TLS_KEY_PATH}:/etc/nginx/tls/privkey.pem:ro
   ```

3. The TLS server listens on the non-root container port **8443**, published to host
   **443** (the overlay publishes `443:8443`, keeping `80:8080` for an optional
   HTTP→HTTPS redirect).

The TLS block negotiates TLS 1.2/1.3 and emits HSTS (`max-age=31536000; includeSubDomains`);
`preload` is left opt-in for operators who have submitted their domain.

> Out of scope for Phase 9: real certificate **issuance/renewal** (e.g. ACME/Let's
> Encrypt). The architecture is HTTPS-ready and certificate mounting is documented;
> issuance is handled externally.

---

## 4. Frontend Runtime_Config (build-once / run-anywhere)

Vite bakes `VITE_API_BASE_URL` at **build time**, but Phase 9 requires the backend base URL
to be chosen at **container start** so one Frontend_Image runs across environments without a
rebuild. The Frontend_Image entrypoint renders a small `/config.js` at start via `envsubst`:

```js
window.__AGENTFORGE_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };
```

- `index.html` loads `/config.js` before the app bundle, so the global exists before the
  app runs. `resolveConfig()` reads the runtime value first, then the build-time value,
  then the documented default.
- When `API_BASE_URL` is **unset**, the entrypoint writes an empty config object and the
  SPA falls back to its documented default (suitable for `local`, where the API is reached
  same-origin through the proxy).
- Set `API_BASE_URL` in production (e.g. a same-origin path `/` or an absolute
  `https://<host>`); the same image serves **byte-identical hashed assets** in every
  environment and differs only in the generated `/config.js`.
- `/config.js` carries the non-secret base URL only — **no credential** is ever embedded in
  the image or the served assets, and `/config.js` is served with `Cache-Control: no-store`
  so a new environment's value is picked up promptly.

This is the single app-adjacent change in Phase 9 (the behavior-preserving `resolveConfig()`
runtime-config plumbing); it touches no API contract, business logic, or secret handling.

---

## 5. Image tags and the registry

Both application images plus the proxy image are published to **GitHub Container Registry
(GHCR)** by the CI pipeline under a **three-tag strategy** applied on publish:

1. **`latest`** — moving; updated on every publish from the mainline. Convenient for pulls,
   **never** used to pin a production rollback.
2. **`<git-sha>`** — the full commit SHA (`${{ github.sha }}`), applied on **every** publish.
   This is the canonical **immutable** reference used by production Compose and rollback.
3. **`<semver>`** — applied **only** when a version tag (`v*`) triggers the run, derived from
   the git tag; omitted on plain branch pushes.

Production Compose references images by `${AGENTFORGE_IMAGE_TAG:-latest}`, so a deploy or a
rollback is a single variable change plus `pull` + `up -d`. Rollback always selects a prior
**immutable** tag (a `<git-sha>` or `<semver>`), never `latest`.

---

## 6. Deployment verification

After a deploy, confirm the platform is healthy through the proxy:

1. **Backend readiness** — confirm `/health/ready` reports ready with all dependencies up:

   ```bash
   curl -fsS https://<host>/health/ready
   # -> {"status":"ready","dependencies":{"database":"up","redis":"up"}}
   ```

2. **Frontend through the proxy** — confirm the SPA is served at the entry point:

   ```bash
   curl -fsS https://<host>/            # returns index.html
   curl -fsS https://<host>/healthz     # proxy/frontend serving status -> 200
   ```

3. **Migrations applied** — the backend runs all pending additive migrations before serving;
   a ready `/health/ready` (database `up`) after startup confirms the schema is current. If
   the one-shot `migrate` service is used, confirm it exited 0
   (`docker compose … ps` / logs) before the backend started.

**Unavailable dependency ⇒ not healthy.** If `/health/ready` reports any dependency as
unavailable, it returns **503** listing the down dependency and the backend healthcheck
reports the container **not ready**. Treat such a deployment as **not healthy** — do not
route production traffic to it; investigate the named dependency and re-verify.

---

## 7. Rollback

Rollback relies on the immutable tag strategy: every published image carries an immutable
`<git-sha>` (and, for releases, a `<semver>`) tag that never moves, so a previous
known-good image set is restored by re-pointing the deployment at that prior tag and
re-pulling. Because all migrations are **additive** and `schema_migrations`-tracked, an
earlier image runs correctly against the current (newer-or-equal) schema — **no database
rollback is required**.

Exact rollback command shape (production overlay, pinning the prior immutable tag):

```bash
# 1. Choose the previous known-good immutable tag (git SHA or semver).
export AGENTFORGE_IMAGE_TAG=<previous-git-sha>   # e.g. 9f3c1a2...  (or v1.4.1)

# 2. Pull that exact image set and restart in place.
docker compose -f docker-compose.yml -f docker-compose.production.yml pull
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d

# 3. Verify the restored deployment is healthy through the proxy.
curl -fsS https://<host>/health/ready
```

The CI `deploy` job wraps this same command shape for automated/approved promotions and
rollbacks. No destructive down-migration is ever needed because the migration runner is
additive.
