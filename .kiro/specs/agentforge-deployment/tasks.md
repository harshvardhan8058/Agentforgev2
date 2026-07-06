# Implementation Plan: AgentForge Cloud Deployment & Production Infrastructure (Phase 9)

## Overview

This plan converts the Phase 9 design into an ordered, incremental, verifiable
**infrastructure-only** sequence. Every task builds on the previous one and ends with the
whole stack wired together behind a single nginx entry point, so no artifact is orphaned:
the build-context exclusions + optimized backend image first, then the one small
app-adjacent `resolveConfig()` runtime-config plumbing (the ONLY application-source edit in
the phase), then the frontend image that serves it, then the nginx reverse proxy (routing,
SSE, TLS, security headers), then the unified keyless local `docker-compose.yml`, then the
`production` overlay, then the migration one-shot option, then the four-job CI/CD pipeline,
then the cross-image secret scan, then the documentation — with checkpoints after each
major batch and a final Phase Completion checkpoint left unchecked for the user.

**This phase changes infrastructure only.** It introduces no new application capability and
changes no application behavior, HTTP/SSE API contract, database-schema semantics, or
business logic (Req 19). It reuses — without modifying — the existing `Settings` profile
selection (`local`/`production`), the `container.py` composition root, the additive startup
migration runner (`migrations/0001`–`0010`), the `AppError` envelope, organization tenancy,
`/health/live` + `/health/ready`, and the keyless-by-default deterministic test promise
(Req 19, 20, 21). The **single app-adjacent edit** in the entire phase is the
behavior-preserving `resolveConfig()` runtime-config extension in `frontend/src/config.ts`
(Task 2), which adds a runtime source for the existing non-secret `baseUrl` and touches no
API contract, business logic, or secret handling.

**Verification-first, keyless by default.** Most Phase 9 artifacts are declarative config
verified by lint (`nginx -t`, hadolint-style), build, and smoke checks rather than
property-based tests. Only four genuinely universal invariants get property-style tests,
each tagged `Feature: agentforge-deployment, Property N: ...` and run a minimum of 100
iterations where the input space is non-trivial (Properties 3 and 4):

- **Property 1** — no credential is baked into any image layer, served asset, or committed
  `*.env.example` (extends the existing frontend bundle-secret scan to images).
- **Property 2** — the keyless Local_Compose stack reaches all-healthy with zero credentials.
- **Property 3** — the migration runner is idempotent (`run_migrations` twice ⇒ `[]`, and
  `schema_migrations` unchanged).
- **Property 4** — the frontend image is build-once / run-anywhere (byte-identical hashed
  assets across `API_BASE_URL` values; only the generated `config.js` differs).

The existing keyless lanes stay exactly as they are and are never modified: backend
`pytest -m 'not integration' -q` and frontend `npm run ci` (codegen check, typecheck,
tests, build, bundle-secret scan), plus `npm run codegen:check` as the API-contract
guardrail (Req 14, 19.2, 21).

- Tasks marked with `*` are optional test/verification sub-tasks and can be skipped for a
  faster MVP. Top-level tasks are never optional.
- Each task references the specific requirements (`_Requirements: X.Y_`) and design
  sections (`_Design: <section>_`) it implements; property sub-tasks additionally reference
  the design property they validate.

## Tasks

- [x] 1. Backend build-context exclusions and optimized, non-root Backend_Image
  - [x] 1.1 Add the root `.dockerignore`
    - Create a repository-root `.dockerignore` that excludes `.venv`, `.git`, Python caches
      (`.pytest_cache`, `.ruff_cache`, `.hypothesis`, `__pycache__`), test artifacts, docs,
      the `frontend/` tree (built as its own image), and all local env files (`.env`,
      `.env.*`, keeping only `*.env.example` patterns out of the image) so no credential or
      dev artifact enters the Backend_Image build context.
    - _Requirements: 3.1, 3.3, 10.2, 10.3_
    - _Design: Backend_Image (`Dockerfile`) — `.dockerignore` bullet; Secrets management + environment separation_

  - [x] 1.2 Optimize the root `Dockerfile` (multi-stage, layer-cached deps, non-root, API_PORT)
    - Evolve the existing root `Dockerfile` into an explicit two-stage build: a
      `python:3.11-slim` builder stage that copies dependency manifests (`pyproject.toml`,
      `README.md`) and installs project runtime dependencies **before** copying `src/` (so a
      source-only change reuses the cached dependency layer), producing a wheel/populated
      venv; and a slim `python:3.11-slim` runtime stage that copies only that artifact plus
      the application — carrying no build toolchain, no pip caches, and no `dev`/`test`
      dependency groups.
    - Create a non-root `appuser`, ensure `/app` and the copied venv/wheel are readable by
      it, and set `USER appuser` before `CMD`. Keep
      `CMD uvicorn agentforge.main:app --host 0.0.0.0 --port ${API_PORT:-8000}` and
      `EXPOSE 8000`; do not modify any application source.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.1, 19.1_
    - _Design: Backend_Image (`Dockerfile`)_

  - [x]* 1.3 Verify the Backend_Image builds, runs non-root, and serves `/health/live`
    - Build the image; assert a source-only change reuses the cached dependency layer;
      assert the runtime container's effective user is non-root (`id -u` ≠ 0); start the
      container and assert `GET /health/live` returns 200; assert no build toolchain or
      `dev`/`test` tooling (pytest/ruff/hypothesis) is present in the final image.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_
    - _Design: Testing Strategy — Dockerfile / image checks_

- [x] 2. Frontend Runtime_Config plumbing (the single app-adjacent edit)
  - [x] 2.1 Extend `resolveConfig()` to read runtime → build-time → default
    - Make the minimal, behavior-preserving edit to `frontend/src/config.ts`: add a
      `runtimeBaseUrl()` helper that reads `window.__AGENTFORGE_CONFIG__?.apiBaseUrl` only
      when `window` is defined, and change `resolveConfig` to resolve
      `runtimeBaseUrl() ?? env.VITE_API_BASE_URL` through the existing `normalizeBaseUrl`
      (which already returns `DEFAULT_BASE_URL` for empty/undefined). The resolved surface
      stays the non-secret `baseUrl` + flags only — no secret path is added, and under jsdom
      (global absent) behavior is identical to today.
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 10.2, 19.1_
    - _Design: Runtime_Config (solving the Vite build-time baking); One small app-adjacent change_

  - [x] 2.2 Add the runtime `config.js` template and load it from `index.html`
    - Add the `config.js` template rendered at container start
      (`window.__AGENTFORGE_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };` via `envsubst`,
      emitting an empty/absent value when `API_BASE_URL` is unset), and add
      `<script src="/config.js"></script>` to `frontend/index.html` before the app bundle so
      the global exists before `main.tsx` runs. In Vite dev the missing `/config.js` is
      skipped and the default is preserved. (The entrypoint that renders it ships with the
      Frontend_Image in Task 3.)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
    - _Design: Runtime_Config — Entrypoint generates `config.js`; `index.html` loads it_

  - [x]* 2.3 Write the property test for build-once / run-anywhere
    - **Property 4: Frontend image is build-once / run-anywhere**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - Tag: `Feature: agentforge-deployment, Property 4: Frontend image is build-once / run-anywhere`.
    - Generate varied `API_BASE_URL` values (including unset), render the entrypoint
      `config.js` template for each, and assert the hashed static-asset set is byte-identical
      across renders while `config.js` reflects each supplied value (and the documented
      default when none is supplied). Minimum 100 iterations.
    - _Design: Testing Strategy — Property 4 (build-once/run-anywhere)_

  - [x]* 2.4 Confirm the existing frontend suite still passes unchanged
    - Run `npm run ci` and assert the codegen check, typecheck, existing `config` tests
      (jsdom: `window.__AGENTFORGE_CONFIG__` absent ⇒ default preserved), build, and
      bundle-secret scan all remain green with no test modified, evidencing no behavior
      change (Req 19, 21).
    - _Requirements: 8.4, 19.1, 21.2_
    - _Design: Testing Strategy — Frontend lane, Contract guardrail_

- [x] 3. Frontend build-context exclusions and Frontend_Image
  - [x] 3.1 Add the `frontend/.dockerignore`
    - Create `frontend/.dockerignore` excluding `node_modules`, `dist`, `.git`, test output,
      caches, and local env files (`.env`, `.env.*`) from the Frontend_Image build context so
      they neither slow the build nor leak into any layer.
    - _Requirements: 2.5, 3.2, 3.3, 10.2, 10.3_
    - _Design: Frontend_Image — `.dockerignore` bullet_

  - [x] 3.2 Author the multi-stage `frontend/Dockerfile` with SPA fallback, `/healthz`, and config.js entrypoint
    - Stage 1 (`node:22-alpine`): `npm ci` then `npm run build` producing `/frontend/dist`.
      Stage 2 (non-root nginx runtime — `nginxinc/nginx-unprivileged` or an equivalently
      reconfigured nginx with writable pid/temp paths and a non-root listen port): copy only
      `dist/` to the served root, add the SPA nginx config (`try_files $uri $uri/ /index.html;`),
      a `location = /healthz { return 200; }`, and an entrypoint that runs the Task 2.2
      `envsubst` render of `config.js` before nginx starts. The final image contains no Node
      toolchain, no `node_modules`, and no source, and runs no process as root.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 1.3, 8.1, 8.2_
    - _Design: Frontend_Image (`frontend/Dockerfile`); Runtime_Config entrypoint_

  - [x]* 3.3 Verify the Frontend_Image serves the SPA + `/healthz`, runs non-root, and excludes the toolchain
    - Build the image; assert the final image contains no `node_modules`/Node toolchain;
      start it and assert it serves `index.html`, returns 200 at `/healthz`, and serves a
      generated `/config.js`; assert the effective container user is non-root.
    - _Requirements: 2.2, 2.3, 2.4, 1.3_
    - _Design: Testing Strategy — Dockerfile / image checks_

- [x] 4. Reverse_Proxy nginx configuration (routing, SSE, TLS, security headers)
  - [x] 4.1 Author the routing config (frontend + backend upstreams, SSE unbuffered)
    - Create the `nginx/` config with `frontend` (:80) and `backend` (:8000) upstreams;
      `location /` → frontend; the concrete backend route prefixes from `main.py`
      (`/health`, `/auth`, `/orgs`, `/agent`, `/query`, `/ingest`, `/documents`,
      `/conversations`, `/multi-agent`, `/analytics`, `/prompts`, `/guardrails`,
      `/evaluations`) + any SSE streaming endpoints → backend via `proxy_pass`. Set
      `X-Forwarded-*`; on backend/streaming locations set `proxy_buffering off;`,
      `proxy_cache off;`, `proxy_http_version 1.1;`, a raised `proxy_read_timeout`, and honor
      `X-Accel-Buffering: no`, forwarding request/response bodies unchanged.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 19.2_
    - _Design: Reverse_Proxy (`nginx/`); Request routing_

  - [x] 4.2 Add the TLS server block, HTTP fallback, and non-root proxy
    - Add a `listen 443 ssl` production server block reading cert/key mounted read-only at
      runtime (`/etc/nginx/tls/fullchain.pem`, `/etc/nginx/tls/privkey.pem`) from a
      Secret_Source — never baked into an image — with an optional `listen 80` → 443 redirect;
      keep a plain `listen 80` server for local so One_Command_Startup works with no
      certificate material. Run the proxy unprivileged (nginx-unprivileged or reconfigured
      nginx) so no process runs as root; host ports are mapped by the runtime, not bound by a
      root process.
    - _Requirements: 7.1, 7.2, 7.4, 1.3, 11.5, 10.2_
    - _Design: Reverse_Proxy — TLS server block, HTTP fallback, Non-root_

  - [x] 4.3 Add the hardened response security headers
    - Attach `add_header ... always;` security headers on served responses:
      `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
      `Referrer-Policy: strict-origin-when-cross-origin`, and a tunable
      `Content-Security-Policy` default (`default-src 'self'; connect-src 'self'; img-src
      'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self';
      base-uri 'self'; frame-ancestors 'none'`) that still permits the hashed bundle, the
      runtime `/config.js`, and same-origin API/SSE. Emit `Strict-Transport-Security`
      (`max-age=31536000; includeSubDomains`) **only from the TLS/production server block**,
      never from the plain-HTTP local block. Headers are additive metadata only and must not
      alter response bodies.
    - _Requirements: 6.5, 7.1, 19.2_
    - _Design: Reverse_Proxy — Response security headers_

  - [x]* 4.4 Validate the proxy config and smoke-check security headers
    - Run `nginx -t` (including the security-header and CSP directives); issue a request for
      a proxied response and assert `X-Content-Type-Options: nosniff`,
      `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and a
      `Content-Security-Policy` header are present with expected values; assert
      `Strict-Transport-Security` is present on the TLS block and **absent** on the plain-HTTP
      block; and assert the response body is byte-unchanged (contract preserved).
    - _Requirements: 6.3, 6.5, 7.1, 7.4, 19.2_
    - _Design: Testing Strategy — Security header smoke check; nginx config validation_

- [x] 5. Checkpoint — images and proxy build and validate
  - Ensure both images build (Backend_Image and Frontend_Image), each runs non-root and
    serves its health endpoint, and the nginx config passes `nginx -t` with security headers.
    Ensure all checks pass, ask the user if questions arise.

- [x] 6. Unified one-command keyless local stack (`docker-compose.yml`)
  - [x] 6.1 Add `frontend` and `nginx` services with keyless env
    - Extend the existing `docker-compose.yml` (which already defines `api` + `postgres` +
      `redis`) by adding a `frontend` service (`build: frontend/Dockerfile`) and an `nginx`
      Reverse_Proxy service (the sole published entry point, port 80). Set `PROFILE=local`
      with no credentials; provide the backend the bundled non-secret
      `DATABASE_URL=postgresql+asyncpg://agentforge:agentforge@postgres:5432/agentforge` and
      `REDIS_URL=redis://redis:6379/0`; pass `API_BASE_URL` to the frontend for Runtime_Config.
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.6, 6.4, 20.2, 20.3_
    - _Design: Local_Compose (`docker-compose.yml`); Environment variable matrix_

  - [x] 6.2 Wire healthchecks and dependency-ordered startup
    - Add a Health_Check to every service per the design table (postgres `pg_isready`; redis
      `redis-cli ping`; backend `/health/live`; frontend + nginx `/healthz`) with explicit
      `interval`/`timeout`/`retries`/`start_period` (e.g. backend `start_period: 40s` to cover
      startup migrations). Add `depends_on: condition: service_healthy` chains: backend after
      postgres + redis healthy; nginx after backend + frontend healthy — so the public entry
      point is unreachable until the whole stack has completed startup.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4_
    - _Design: Health checks + startup ordering (concrete); Startup gating (explicit)_

  - [x]* 6.3 Compose smoke + keyless all-healthy property
    - **Property 2: Keyless local stack reaches all-healthy with zero credentials**
    - **Validates: Requirements 4.2, 20.1**
    - Tag: `Feature: agentforge-deployment, Property 2: Keyless local stack reaches all-healthy with zero credentials`.
    - Run `docker compose up --build` with an empty credential environment; assert
      frontend, backend, postgres, and redis all reach healthy and traffic serves through
      nginx; fetch the frontend through the proxy; exercise one SSE endpoint to confirm
      unbuffered streaming; and confirm the proxy became reachable only after backend +
      frontend reported healthy.
    - _Requirements: 4.1, 4.4, 6.3, 6.6, 11, 12, 13.1, 13.3_
    - _Design: Testing Strategy — Compose smoke; Property 2 (keyless all-healthy)_

- [x] 7. Production deployment overlay (`docker-compose.production.yml`)
  - [x] 7.1 Author the production overlay (secrets, hardened creds, restart, TLS, GHCR images)
    - Add `docker-compose.production.yml` applied as an overlay on the base file:
      `PROFILE=production`; all credentials sourced from `env_file`/orchestrator Secret_Source
      with **no credential value committed** (including `JWT_SECRET` and non-default
      `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`); `restart: unless-stopped` on backend,
      frontend, nginx, postgres, redis; no source bind mounts and no reload; nginx TLS block
      active with mounted cert/key; and images referenced by `${AGENTFORGE_IMAGE_TAG:-latest}`
      pulled from GHCR rather than built.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 7.2, 9.3, 10.1, 10.5, 15.x_
    - _Design: Production_Compose (`docker-compose.production.yml`); Local vs. production compose differences_

  - [x] 7.2 Add `.env.production.example` (placeholders only)
    - Add `.env.production.example` enumerating every production-required setting
      (`PROFILE`, `JWT_SECRET`, `DATABASE_URL`, `REDIS_URL`, `POSTGRES_*`, optional
      `SecretStr` provider keys, `API_BASE_URL`, `AGENTFORGE_IMAGE_TAG`) with **placeholder
      values only** and no real credential; keep the existing `.env.example` /
      `frontend/.env.example` templates unchanged as the local references.
    - _Requirements: 9.2, 9.4, 10.3_
    - _Design: Secrets management + environment separation; Environment variable matrix_

  - [x]* 7.3 Verify the production guard aborts on missing `JWT_SECRET`
    - Start the backend under `PROFILE=production` with `JWT_SECRET` absent and assert the
      existing `load_settings` guard raises `ConfigError(["jwt_secret"], ...)`, the container
      exits non-zero before serving, and no credential value is read from any committed file.
    - _Requirements: 5.6, 10.5_
    - _Design: Error Handling — Production missing JWT_SECRET_

- [x] 8. Migration step: on-startup default + optional one-shot service
  - [x] 8.1 Keep on-startup migrations and add the optional one-shot `migrate` service
    - Keep the existing `main.py` lifespan `run_migrations` on-startup path as the default
      (no app change) and document it as the Phase 9 single-replica default. Add an optional
      one-shot `migrate` service in Compose that invokes the existing runner once and exits 0,
      with the backend declaring
      `depends_on: migrate: condition: service_completed_successfully` for the scale-out
      option; the runner stays additive and `schema_migrations`-tracked.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 18.3_
    - _Design: Migration_Step_

  - [x]* 8.2 Write the migration idempotence property test
    - **Property 3: Migration runner is idempotent**
    - **Validates: Requirements 13.2, 18.3**
    - Tag: `Feature: agentforge-deployment, Property 3: Migration runner is idempotent`.
    - Marked `@pytest.mark.integration` (real Postgres). Across varying already-applied
      prefixes, apply the migration set once, then assert a second `run_migrations` returns
      `[]` (no further migrations) and the `schema_migrations` row set is unchanged. Uses the
      existing runner; no app change. Minimum 100 iterations over the generated prefix space.
    - _Design: Testing Strategy — Property 3 (migration idempotence)_

- [x] 9. CI/CD pipeline — four chained jobs (`.github/workflows`)
  - [x] 9.1 Add the keyless `test` job
    - Add the workflow triggered on push and pull request with a `test` job running both
      keyless lanes with **no credentials**: backend `pytest -m 'not integration' -q` and
      frontend `npm ci` + `npm run ci` (codegen check, typecheck, tests, build,
      bundle-secret scan). A failing lane fails the job and blocks all downstream jobs.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 21.1, 21.2, 21.3_
    - _Design: CI/CD — `test` job_

  - [x] 9.2 Add the `build` job (`needs: test`)
    - Add a `build` job gated `needs: test` that builds **both** images via the multi-stage
      Dockerfiles (build-and-verify only; no push), using layer cache; it runs only after both
      keyless lanes are green.
    - _Requirements: 15.1, 14.4, 15.4_
    - _Design: CI/CD — `build` job_

  - [x] 9.3 Add the `publish` job (`needs: build`) with the three-tag GHCR strategy
    - Add a `publish` job gated `needs: build` and guarded by `if:` on `github.ref`/event
      (e.g. push to `main` and version tags) that pushes both images to GHCR applying the
      three-tag strategy: `latest` (moving) and `<git-sha>` (`${{ github.sha }}`, immutable)
      on **every** publish, plus `<semver>` derived from `github.ref_name` **only** when a
      version tag triggers the run.
    - _Requirements: 15.2, 15.3, 15.4_
    - _Design: CI/CD — `publish` job; Image tags (three-tag strategy)_

  - [x] 9.4 Add the guarded `deploy` job (`needs: publish`)
    - Add a `deploy` job gated `needs: publish` and guarded by trigger, implemented as a
      manual-approval GitHub Environment or a `docker compose pull` + `up -d` step against the
      target host, encapsulating the documented rollback command shape (re-point
      `AGENTFORGE_IMAGE_TAG` to a prior immutable tag, pull, up). A failure at any earlier
      stage stops all later stages.
    - _Requirements: 15.4, 18.1, 18.2_
    - _Design: CI/CD — `deploy` job; Rollback plan_

- [x] 10. Cross-image secret scan (extend the existing bundle-secret scan)
  - [x] 10.1 Extend the secret scan across image layers, served assets, and env examples
    - Extend the existing frontend bundle-secret scanner so it iterates over every built
      Backend_Image and Frontend_Image layer, every served static asset (including the
      generated `config.js`), and every committed `*.env.example`, asserting only
      placeholder-shaped values are present and failing on any credential-shaped value. Wire
      it into the CI `test`/`build` stages so a baked secret fails the pipeline.
    - _Requirements: 10.2, 10.3, 3.3, 8.5_
    - _Design: Testing Strategy — Property 1 (no baked secrets)_

  - [x]* 10.2 Write the no-baked-secrets property test
    - **Property 1: No credential is baked into any image or served asset**
    - **Validates: Requirements 10.2, 10.3, 10.5, 3.3, 8.5**
    - Tag: `Feature: agentforge-deployment, Property 1: No credential is baked into any image or served asset`.
    - For all built image layers, all served assets (incl. `config.js`), and all committed
      `*.env.example` files, assert no real credential value is present (only placeholders).
    - _Design: Testing Strategy — Property 1 (no baked secrets)_

- [x] 11. Deployment and infrastructure documentation
  - [x] 11.1 Add the README deployment section
    - Add a Deployment section to `README.md` describing the one-command local start
      (`docker compose up --build`) reaching a serving keyless platform through the proxy.
    - _Requirements: 16.1_
    - _Design: Documentation set — README.md_

  - [x] 11.2 Author `docs/DEPLOYMENT.md`
    - Cover production deploy under the `production` profile and how the Secret_Source
      supplies credentials; the proxy routing, TLS_Termination, and how to enable HTTPS by
      mounting cert material; the Runtime_Config mechanism for the frontend base URL; the
      three-tag Image_Tag strategy and the rollback procedure (previous immutable tag +
      Compose `pull`/`up -d`, additive-migration safety); and verification steps
      (`/health/ready`, frontend-through-proxy, migrations applied) with the "unavailable
      dependency ⇒ not healthy" rule.
    - _Requirements: 16.2, 16.3, 16.4, 16.5, 17.1, 17.2, 17.3, 17.4, 18.1, 18.2, 18.3_
    - _Design: Documentation set — docs/DEPLOYMENT.md; Rollback plan; Deployment verification_

  - [x] 11.3 Author `docs/INFRASTRUCTURE.md`
    - Document the deployment topology, the service list (nginx/frontend/api/postgres/redis
      + optional migrate), network and published ports, the env-var matrix (local vs.
      production), and the four-job CI/CD overview.
    - _Requirements: 16.1, 9.1, 9.5_
    - _Design: Documentation set — docs/INFRASTRUCTURE.md; Compose service list; Environment variable matrix_

  - [x] 11.4 Add a Phase 9 note to `PROJECT_STATE` and `docs/decisions.md`
    - Append a Phase 9 entry to `docs/PROJECT_STATE.md` and a "Phase 9 — Cloud Deployment &
      Production Infrastructure" section to `docs/decisions.md` recording the infra-only
      decisions: multi-stage/non-root images, the nginx single entry point with SSE and
      security headers, the `resolveConfig()` runtime-config plumbing as the sole app-adjacent
      edit, the keyless local vs. production overlay split, the three-tag GHCR strategy,
      additive-migration rollback safety, and observability preservation.
    - _Requirements: 16.5, 19.1, 19.4_
    - _Design: Documentation set; Observability is preserved; Deployment targets_

- [x] 12. Checkpoint — docs and full local stack
  - Ensure the documentation renders, `docker compose up --build` still reaches all-healthy
    keyless through the proxy, and the existing keyless lanes remain green unchanged. Ensure
    all checks pass, ask the user if questions arise.

- [ ] 13. Final Phase Completion checkpoint (leave unchecked for the user)
  - Verify the full infrastructure-only phase end to end: the keyless backend suite is still
    green (`pytest -m 'not integration' -q`); the frontend `npm run ci` is still green;
    `npm run codegen:check` confirms the OpenAPI/HTTP-SSE contract is unchanged; the Compose
    smoke reaches all-healthy with the frontend reachable through the proxy and one SSE
    endpoint unbuffered; the security headers are present with expected values (HSTS on the
    TLS block only); every runtime container (backend, frontend, proxy) runs non-root; all
    four property tests pass (Property 1 no baked secrets, Property 2 keyless all-healthy,
    Property 3 migration idempotence, Property 4 build-once/run-anywhere); and no baked
    secret exists in any image, asset, or committed file — confirming NO application
    behavior or contract change.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test/verification sub-tasks and can be skipped for a
  faster MVP. Top-level tasks are never optional.
- Each task references specific acceptance criteria (`_Requirements: X.Y_`) and the design
  section it implements (`_Design: <section>_`); property sub-tasks additionally reference
  the design property they validate (`**Property N: <text>** ; **Validates: Requirements X.Y**`).
- The four property tests are the primary universal-invariant surface
  (`Feature: agentforge-deployment, Property N: ...`); everything else — Dockerfiles, nginx
  config, Compose files, CI structure, docs — is declarative infrastructure verified by
  lint / build / smoke / CI checks per the design's Testing Strategy.
- This phase is **infrastructure only**: the ONLY application-source edit is the
  behavior-preserving `resolveConfig()` runtime-config plumbing (Task 2). No API contract,
  business logic, database-schema semantics, or observability behavior changes (Req 19, 20,
  21); `npm run codegen:check` is the standing contract guardrail.
- The existing keyless lanes (`pytest -m 'not integration' -q`, `npm run ci`) are never
  modified and never require a credential. Property 3 is `@pytest.mark.integration` (real
  Postgres) and runs outside the default keyless lane.
- Out of scope (per requirements): managed cloud services, Kubernetes/Helm, DNS/domain
  registration, real certificate issuance/renewal, autoscaling, and any application feature
  or branch-consolidation work.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "Root .dockerignore + optimized multi-stage non-root Backend_Image (API_PORT default 8000)."
    },
    {
      "wave": 2,
      "tasks": ["2"],
      "description": "Frontend Runtime_Config plumbing: resolveConfig() extension, config.js template + index.html script (Property 4); existing frontend suite confirmed unchanged."
    },
    {
      "wave": 3,
      "tasks": ["3"],
      "description": "frontend/.dockerignore + multi-stage non-root Frontend_Image (nginx SPA, /healthz, config.js entrypoint) — depends on the Task 2 config.js template."
    },
    {
      "wave": 4,
      "tasks": ["4"],
      "description": "Reverse_Proxy nginx config: routing + unbuffered SSE, TLS block + HTTP fallback + non-root, security headers."
    },
    {
      "wave": 5,
      "tasks": ["5"],
      "description": "Checkpoint — both images build and run non-root; nginx -t passes with security headers."
    },
    {
      "wave": 6,
      "tasks": ["6"],
      "description": "Unified keyless docker-compose.yml: frontend + nginx services, healthchecks, dependency-ordered startup (Property 2)."
    },
    {
      "wave": 7,
      "tasks": ["7"],
      "description": "Production overlay (secrets, hardened creds, restart, TLS, GHCR images) + .env.production.example; production guard verified."
    },
    {
      "wave": 8,
      "tasks": ["8"],
      "description": "Migration step: on-startup default + optional one-shot migrate service (Property 3, integration)."
    },
    {
      "wave": 9,
      "tasks": ["9"],
      "description": "Four-job CI/CD: test -> build -> publish (three-tag GHCR) -> deploy, chained with needs:."
    },
    {
      "wave": 10,
      "tasks": ["10"],
      "description": "Cross-image secret scan extending the bundle-secret scanner to image layers + assets + *.env.example (Property 1)."
    },
    {
      "wave": 11,
      "tasks": ["11"],
      "description": "Documentation: README deployment section, docs/DEPLOYMENT.md, docs/INFRASTRUCTURE.md, PROJECT_STATE + decisions.md Phase 9 note."
    },
    {
      "wave": 12,
      "tasks": ["12"],
      "description": "Checkpoint — docs render, full local stack all-healthy, existing keyless lanes green unchanged."
    },
    {
      "wave": 13,
      "tasks": ["13"],
      "description": "Final Phase Completion checkpoint (left unchecked for the user): all four properties, non-root containers, security headers, keyless suites, codegen:check, no baked secrets."
    }
  ],
  "notes": [
    "Each wave depends on all prior waves; build-context/image artifacts precede the Compose files that consume them, which precede CI that builds/publishes them.",
    "Task 3 (Frontend_Image entrypoint) depends on the config.js template authored in Task 2.2; Task 2 is the only wave touching application source.",
    "Task 6 (Local_Compose) depends on Tasks 1, 3, and 4 (both images + proxy config) to bring the stack up.",
    "Task 7 (production overlay) is an overlay on the Task 6 base graph and reuses the same images.",
    "Task 9 (CI/CD) depends on both Dockerfiles (Tasks 1, 3) existing; the publish job's tag strategy and the deploy job's rollback shape align with Task 11 docs.",
    "Task 10's Property 1 scan depends on both images (Tasks 1, 3) and the served config.js (Tasks 2, 3) being buildable.",
    "Optional (*) verification sub-tasks may be deferred without blocking dependent waves.",
    "Property 3 is @pytest.mark.integration (real Postgres) and runs outside the default keyless lane; Properties 1, 2, 4 exercise images/compose/entrypoint render."
  ]
}
```
