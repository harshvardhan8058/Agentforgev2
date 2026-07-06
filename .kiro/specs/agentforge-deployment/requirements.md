# Requirements Document

## Introduction

AgentForge Phase 9 delivers **Cloud Deployment & Production Infrastructure** for the
existing platform. Phases 1–6 (backend: foundation, RAG, agentic, multi-agent,
enterprise, observability) are on `main`; Phase 7 (the React `/frontend` SPA, PR #14) and
Phase 8 (third-party integrations, PR #16) are complete and are being consolidated onto
`main`. Phase 9 packages the whole platform — the FastAPI backend, the Vite/React
frontend, PostgreSQL (pgvector), and Redis — into a production-grade, container-based
deployment that a fresh developer can bring up with a single command and that an operator
can promote to a production environment without rebuilding images.

This phase is **infrastructure only**. It introduces no new application capability and
changes no application behavior, HTTP/SSE API contract, database schema semantics, or
business logic. It works strictly with, and preserves, the architecture already shipped:
the `Configuration_Manager` profile selection (`local` / `production`), env-only
`SecretStr` credentials that are optional by default, the `container.py` composition
root, the additive startup migration runner (`migrations/0001`–`0010`), the uniform
`AppError` envelope, organization tenancy, `/health/live` + `/health/ready`, and the
keyless-by-default, deterministic test promise.

The grounding artifacts for this phase are the existing root `Dockerfile`
(python:3.11-slim, `pip install .`, uvicorn on port 8000), the current
`docker-compose.yml` (services `api` + `postgres` [pgvector/pgvector:pg16] + `redis` with
healthchecks and a `PROFILE` default of `local`), the backend `.env.example` and
`frontend/.env.example` (`VITE_API_BASE_URL`), `src/agentforge/config/settings.py`
(profile selection, required non-secret `database_url` / `redis_url`, optional
`SecretStr` credentials, the production `jwt_secret` requirement, and the `active_*()`
selectors), `src/agentforge/main.py` (lifespan startup that runs migrations
automatically), `src/agentforge/db/migrations.py` (the additive runner keyed by
`schema_migrations`), `src/agentforge/api/routers/health.py`, `frontend/package.json`
(Node ≥ 22, `npm run ci`, `npm run build`), and `frontend/vite.config.ts`.

## Glossary

- **Platform**: The complete AgentForge system comprising the Backend_Service, the
  Frontend_Client, PostgreSQL (pgvector), and Redis.
- **Backend_Service**: The existing FastAPI application served by uvicorn
  (`agentforge.main:app`) listening on port 8000.
- **Frontend_Client**: The existing React + Vite single-page application located in the
  `/frontend` directory, whose compiled output is a set of static assets.
- **Backend_Image**: The container image that packages the Backend_Service, built from the
  root `Dockerfile`.
- **Frontend_Image**: The container image that packages the compiled Frontend_Client
  assets and the web server that serves them, built from a `frontend/Dockerfile`.
- **Reverse_Proxy**: The nginx-based single entry point that routes browser traffic —
  application routes to the Frontend_Client static assets and API/SSE routes to the
  Backend_Service — and serves as the TLS_Termination point.
- **TLS_Termination**: The single component at which inbound HTTPS/TLS connections are
  terminated; in this Platform, the Reverse_Proxy.
- **Runtime_Config**: The mechanism by which the Frontend_Client obtains its
  environment-specific backend base URL at container start time (not at image build
  time), allowing one Frontend_Image to run unchanged across environments.
- **Environment_Profile**: A named deployment configuration; the two profiles are `local`
  (keyless development) and `production`, aligned with the existing `Settings.profile`.
- **Local_Compose**: The unified Docker Compose file (`docker-compose.yml`) that runs the
  full Platform for local development with one command and zero credentials.
- **Production_Compose**: The Docker Compose file (`docker-compose.production.yml`) that
  runs the Platform under the `production` Environment_Profile with injected secrets,
  non-default database credentials, and restart policies.
- **Migration_Step**: The additive database schema migration process (the existing
  `run_migrations` runner over `migrations/0001`–`0010`, tracked in `schema_migrations`),
  executed either automatically on Backend_Service startup or as a dedicated one-shot
  step.
- **Health_Check**: A container-level or orchestrator-level probe. The Backend_Service
  exposes liveness at `GET /health/live` and readiness at `GET /health/ready`; the
  Reverse_Proxy and Frontend_Client expose an HTTP endpoint returning 200 when serving.
- **Image_Tag**: The label applied to a published container image (for example a
  `latest` moving tag and an immutable commit-SHA or semantic-version tag) used for
  deployment selection and rollback.
- **Image_Registry**: The container registry (for example GitHub Container Registry,
  GHCR) to which built images are published.
- **Secret_Source**: The runtime origin of a credential (environment variable injected
  from an operator-managed environment file or an orchestrator secret store); credentials
  are never baked into images or committed to version control.
- **CI_Pipeline**: The GitHub Actions workflow that runs the keyless test lanes, builds
  the images, and publishes them to the Image_Registry.
- **Dockerignore_File**: A `.dockerignore` file (at the repository root and in
  `/frontend`) that excludes non-essential paths from each image build context.
- **Deployment_Documentation**: The written operator-facing documentation describing how
  to build, configure, deploy, verify, and roll back the Platform.
- **One_Command_Startup**: The guarantee that `docker compose up --build` alone brings up
  the full Platform for local development with no additional manual setup.

## Requirements

### Requirement 1: Backend container image optimization

**User Story:** As a platform operator, I want an optimized, secure Backend_Image, so that
production deployments are small, fast to build, and run with least privilege.

#### Acceptance Criteria

1. THE Backend_Image SHALL be built from the existing root `Dockerfile` and SHALL run the
   Backend_Service via uvicorn on port 8000.
2. THE Backend_Image SHALL order its build steps so that dependency installation is cached
   in a layer separate from application source, so that a source-only change reuses the
   cached dependency layer.
3. THE Backend_Image SHALL run the Backend_Service as a non-root user.
4. THE Backend_Image SHALL install only the dependencies required to run the
   Backend_Service and SHALL exclude development-only and test-only tooling.
5. WHERE a build context exclusion file is defined, THE Backend_Image build SHALL exclude
   `.venv`, `.git`, test artifacts, caches, and local environment files from the build
   context.
6. THE Backend_Image SHALL expose the Backend_Service on a port configurable through the
   existing `API_PORT` environment variable with a default of 8000.

### Requirement 2: Frontend container image

**User Story:** As a platform operator, I want the Frontend_Client packaged as a
self-contained image, so that the web UI is served as optimized static assets without a
Node runtime in production.

#### Acceptance Criteria

1. THE Frontend_Image SHALL be built by a multi-stage build in which a Node build stage
   (Node version 22 or greater) compiles the Frontend_Client via `npm run build` and a
   final stage serves the compiled static assets with nginx.
2. THE Frontend_Image final stage SHALL NOT include the Node toolchain or the
   `node_modules` directory.
3. THE Frontend_Image SHALL serve the compiled single-page application and SHALL return
   the application entry point for client-side routes that do not correspond to a static
   asset.
4. THE Frontend_Image SHALL expose an HTTP endpoint that returns status 200 when the web
   server is serving assets.
5. WHERE a build context exclusion file is defined, THE Frontend_Image build SHALL exclude
   `node_modules`, `dist`, `.git`, test artifacts, and local environment files from the
   build context.

### Requirement 3: Build context exclusion files

**User Story:** As a developer, I want `.dockerignore` files, so that image build contexts
stay small and no unnecessary or sensitive files are sent to the image builder.

#### Acceptance Criteria

1. THE Platform SHALL provide a root Dockerignore_File that excludes `.venv`, `.git`,
   Python caches, test artifacts, and local environment files from the Backend_Image build
   context.
2. THE Platform SHALL provide a `/frontend` Dockerignore_File that excludes
   `node_modules`, `dist`, `.git`, and local environment files from the Frontend_Image
   build context.
3. WHERE a local environment file exists in a build context, THE Dockerignore_File SHALL
   exclude that environment file so that no credential is copied into any image.

### Requirement 4: Unified one-command local development stack

**User Story:** As a new developer, I want to start the entire Platform with a single
command and no credentials, so that I can run and evaluate AgentForge locally without
manual setup.

#### Acceptance Criteria

1. WHEN a developer runs `docker compose up --build` against the Local_Compose file, THE
   Local_Compose SHALL build and start the Frontend_Client, the Backend_Service,
   PostgreSQL (pgvector), and Redis.
2. THE Local_Compose SHALL start the Platform under the `local` Environment_Profile with
   no credentials required.
3. WHEN the Local_Compose stack starts with no credentials configured, THE Backend_Service
   SHALL boot using the deterministic keyless defaults (Fallback LLM provider, local
   embeddings, disabled web search, and the NoOp tracing exporter).
4. THE Local_Compose SHALL require no manual step beyond the single
   `docker compose up --build` command to reach a serving Platform.
5. THE Local_Compose SHALL provide the Backend_Service with the required non-secret
   `DATABASE_URL` and `REDIS_URL` values that point at the bundled PostgreSQL and Redis
   services.
6. THE Local_Compose SHALL expose the Frontend_Client to the developer's browser through
   the Reverse_Proxy as a single entry point.

### Requirement 5: Production deployment stack

**User Story:** As a platform operator, I want a production Compose configuration, so that
I can deploy the Platform with real secrets, hardened credentials, and restart policies.

#### Acceptance Criteria

1. THE Production_Compose SHALL start the Platform under the `production` Environment_Profile.
2. THE Production_Compose SHALL source all credentials from a Secret_Source at runtime and
   SHALL NOT contain any credential value in version-controlled files.
3. THE Production_Compose SHALL configure PostgreSQL with non-default database credentials
   supplied from a Secret_Source.
4. THE Production_Compose SHALL define a restart policy for the Backend_Service, the
   Frontend_Client, the Reverse_Proxy, PostgreSQL, and Redis so that a crashed container
   is restarted automatically.
5. THE Production_Compose SHALL NOT expose development-only conveniences such as
   source-code bind mounts or auto-reload.
6. IF the `production` Environment_Profile is selected and the required `JWT_SECRET` is
   absent, THEN THE Backend_Service SHALL abort startup and report the missing setting by
   name, consistent with the existing `load_settings` production guard.

### Requirement 6: Reverse proxy single entry point

**User Story:** As a platform operator, I want an nginx reverse proxy, so that the browser
reaches the frontend and the backend API through one host and port.

#### Acceptance Criteria

1. THE Reverse_Proxy SHALL route application (non-API) requests to the Frontend_Client
   static assets.
2. THE Reverse_Proxy SHALL route API and SSE requests to the Backend_Service.
3. WHEN the Reverse_Proxy forwards a Server-Sent Events response from the Backend_Service,
   THE Reverse_Proxy SHALL stream the response to the client without buffering the event
   stream.
4. THE Reverse_Proxy SHALL present the Platform to the client through a single host and
   port as the sole external entry point.
5. THE Reverse_Proxy SHALL forward the Backend_Service HTTP/SSE contract unchanged, so that
   API request and response payloads are not altered in transit.

### Requirement 7: HTTPS-ready architecture

**User Story:** As a platform operator, I want the architecture ready for HTTPS, so that I
can enable TLS in production by supplying certificates without re-architecting.

#### Acceptance Criteria

1. THE Reverse_Proxy SHALL be defined as the single TLS_Termination point for the Platform.
2. THE Reverse_Proxy SHALL accept TLS certificate and private-key material mounted from a
   Secret_Source at runtime rather than embedded in any image.
3. THE Deployment_Documentation SHALL describe how to supply certificate material and
   enable HTTPS at the Reverse_Proxy.
4. WHERE no certificate material is supplied, THE Platform SHALL still serve over plain HTTP
   for local development so that One_Command_Startup is preserved.

### Requirement 8: Runtime frontend configuration

**User Story:** As a platform operator, I want the frontend backend URL configured at
container start, so that one Frontend_Image runs across environments without a rebuild.

#### Acceptance Criteria

1. THE Frontend_Image SHALL obtain its backend base URL through a Runtime_Config mechanism
   evaluated at container start time rather than only through the build-time
   `VITE_API_BASE_URL` value.
2. WHEN the Frontend_Image container starts with a backend base URL provided as an
   environment variable, THE Runtime_Config SHALL make that value available to the running
   Frontend_Client without rebuilding the image.
3. WHEN the same Frontend_Image is started in two different environments with two different
   backend base URL values, THE Runtime_Config SHALL cause each running container to use
   its own environment's value.
4. WHERE no Runtime_Config value is supplied, THE Frontend_Client SHALL fall back to a
   documented default backend base URL suitable for the `local` Environment_Profile.
5. THE Runtime_Config SHALL NOT embed any credential into the Frontend_Image or the served
   assets.

### Requirement 9: Environment separation

**User Story:** As a platform operator, I want local and production environments clearly
separated, so that development conveniences never leak into production.

#### Acceptance Criteria

1. THE Platform SHALL separate configuration into the `local` and `production`
   Environment_Profiles aligned with the existing `Settings.profile` values.
2. THE Platform SHALL provide example environment files that enumerate every setting with
   placeholder values and contain no real credential.
3. THE Local_Compose SHALL select the `local` Environment_Profile and THE
   Production_Compose SHALL select the `production` Environment_Profile.
4. THE Deployment_Documentation SHALL state which settings are required in the `production`
   Environment_Profile and which are optional in the `local` Environment_Profile.
5. THE Platform SHALL route the required non-secret settings (`DATABASE_URL`, `REDIS_URL`)
   and all optional credentials through the existing `Configuration_Manager` environment
   loading, introducing no separate configuration mechanism.

### Requirement 10: Secrets management

**User Story:** As a security-conscious operator, I want secrets injected at runtime only,
so that no credential is ever built into an image or committed.

#### Acceptance Criteria

1. THE Platform SHALL inject every credential from a Secret_Source as an environment
   variable at container runtime.
2. THE Platform SHALL NOT bake any credential into the Backend_Image or the
   Frontend_Image.
3. THE Platform SHALL NOT commit any real credential to version control, and every
   example environment file SHALL contain only placeholder values.
4. THE Platform SHALL preserve the existing `SecretStr` credential typing so that no
   credential value appears in logs, `repr`, or serialized output.
5. WHERE the `production` Environment_Profile requires the `JWT_SECRET`, THE Secret_Source
   SHALL supply it at runtime and THE Platform SHALL NOT store it in any image or
   version-controlled file.

### Requirement 11: Container health checks

**User Story:** As a platform operator, I want health checks on every service, so that the
orchestrator only routes traffic to healthy containers.

#### Acceptance Criteria

1. THE Local_Compose and THE Production_Compose SHALL define a Health_Check for the
   Backend_Service that queries `GET /health/live`.
2. THE Platform SHALL use `GET /health/ready` to determine when the Backend_Service and its
   PostgreSQL and Redis dependencies are ready to serve traffic.
3. WHEN `GET /health/ready` reports an unavailable dependency, THE Backend_Service
   Health_Check SHALL report the container as not ready.
4. THE Local_Compose and THE Production_Compose SHALL define a Health_Check for PostgreSQL
   and a Health_Check for Redis that report readiness before dependent services start.
5. THE Local_Compose and THE Production_Compose SHALL define a Health_Check for the
   Frontend_Client and the Reverse_Proxy that reports serving status over HTTP.

### Requirement 12: Startup ordering

**User Story:** As a platform operator, I want services to start in dependency order, so
that the Platform reaches a serving state without race-condition failures.

#### Acceptance Criteria

1. THE Backend_Service SHALL start only after PostgreSQL and Redis report healthy through
   their Health_Checks.
2. THE Reverse_Proxy SHALL start only after the Backend_Service and the Frontend_Client
   report healthy through their Health_Checks.
3. IF a dependency does not become healthy within its configured Health_Check retry
   budget, THEN the dependent service SHALL NOT be started.
4. THE Local_Compose and THE Production_Compose SHALL express these startup dependencies
   through Compose service-dependency conditions.

### Requirement 13: Automatic database migrations

**User Story:** As a platform operator, I want database migrations applied automatically,
so that the Platform reaches a correct schema with no manual intervention.

#### Acceptance Criteria

1. WHEN the Platform is deployed, THE Migration_Step SHALL apply all pending additive
   migrations (`migrations/0001`–`0010`) using the existing `run_migrations` runner before
   the Backend_Service begins serving requests.
2. THE Migration_Step SHALL remain additive and SHALL track applied migrations in the
   existing `schema_migrations` table so that re-running is safe.
3. WHEN a One_Command_Startup local deployment is performed, THE Migration_Step SHALL run
   without any manual intervention.
4. IF a migration fails, THEN THE Migration_Step SHALL halt startup and report the failing
   migration identifier, consistent with the existing `MigrationError` behavior.
5. WHERE the Migration_Step is implemented as a dedicated one-shot step rather than on
   Backend_Service startup, THE Backend_Service SHALL begin serving only after the one-shot
   Migration_Step completes successfully.

### Requirement 14: Continuous integration test lanes

**User Story:** As a maintainer, I want CI to run the keyless test lanes, so that every
change is verified deterministically without credentials.

#### Acceptance Criteria

1. WHEN a change is pushed or a pull request is opened, THE CI_Pipeline SHALL run the
   keyless backend test lane `pytest -m 'not integration' -q`.
2. WHEN a change is pushed or a pull request is opened, THE CI_Pipeline SHALL run the
   frontend `npm run ci` lane (codegen check, typecheck, tests, build, and bundle-secret
   scan).
3. THE CI_Pipeline SHALL run both keyless lanes with no credentials configured.
4. IF either keyless test lane fails, THEN THE CI_Pipeline SHALL fail and SHALL NOT publish
   any image for that run.

### Requirement 15: Image build and publish

**User Story:** As a maintainer, I want images built and published to a registry, so that
deployments pull versioned, immutable images.

#### Acceptance Criteria

1. WHEN the keyless test lanes pass on the configured publish trigger, THE CI_Pipeline
   SHALL build the Backend_Image and the Frontend_Image.
2. WHEN the CI_Pipeline builds the images on the configured publish trigger, THE
   CI_Pipeline SHALL publish the Backend_Image and the Frontend_Image to the
   Image_Registry.
3. WHEN the CI_Pipeline publishes an image, THE CI_Pipeline SHALL apply an immutable
   Image_Tag derived from the commit identifier in addition to any moving tag.
4. THE CI_Pipeline SHALL publish images only on the configured publish trigger and SHALL
   NOT publish images for a run whose keyless test lanes failed.

### Requirement 16: Deployment and infrastructure documentation

**User Story:** As an operator, I want deployment documentation, so that I can build,
configure, deploy, and operate the Platform without reverse-engineering the compose files.

#### Acceptance Criteria

1. THE Deployment_Documentation SHALL describe how to start the Platform locally with the
   single `docker compose up --build` command.
2. THE Deployment_Documentation SHALL describe how to deploy the Platform under the
   `production` Environment_Profile, including how the Secret_Source supplies credentials.
3. THE Deployment_Documentation SHALL describe the Reverse_Proxy routing, the
   TLS_Termination point, and how to enable HTTPS.
4. THE Deployment_Documentation SHALL describe the Runtime_Config mechanism for the
   Frontend_Client backend base URL.
5. THE Deployment_Documentation SHALL describe the Image_Tag strategy and the rollback
   procedure.

### Requirement 17: Production deployment verification

**User Story:** As an operator, I want a documented way to verify a deployment, so that I
can confirm the Platform is healthy after deploying.

#### Acceptance Criteria

1. THE Deployment_Documentation SHALL describe how to confirm the Backend_Service reports
   ready via `GET /health/ready` after a deployment.
2. THE Deployment_Documentation SHALL describe how to confirm the Frontend_Client is served
   through the Reverse_Proxy after a deployment.
3. THE Deployment_Documentation SHALL describe how to confirm all pending migrations have
   been applied after a deployment.
4. WHEN a deployment verification is performed and `GET /health/ready` reports an
   unavailable dependency, THE Deployment_Documentation SHALL direct the operator to treat
   the deployment as not healthy.

### Requirement 18: Rollback strategy

**User Story:** As an operator, I want a rollback path, so that I can revert to a known-good
release quickly if a deployment is unhealthy.

#### Acceptance Criteria

1. THE Deployment_Documentation SHALL describe how to redeploy a previous immutable
   Image_Tag to roll back the Backend_Image and the Frontend_Image.
2. THE Deployment_Documentation SHALL describe how to perform a Compose-based rollback to a
   previously published image set.
3. WHERE a rollback is performed to an earlier image set, THE Migration_Step SHALL remain
   additive so that the earlier Backend_Image runs against the current schema without a
   destructive down-migration.

### Requirement 19: Application behavior preservation (guardrail)

**User Story:** As the platform owner, I want Phase 9 to change infrastructure only, so
that no application behavior, API contract, or business logic is altered.

#### Acceptance Criteria

1. THE Phase 9 changes SHALL modify only deployment and infrastructure artifacts and SHALL
   NOT modify application source that changes runtime behavior, the HTTP/SSE API contract,
   or business logic.
2. THE Backend_Service HTTP/SSE API contract SHALL remain unchanged after Phase 9, so that
   the existing OpenAPI schema continues to describe the served endpoints.
3. THE Phase 9 changes SHALL preserve the existing database schema semantics and SHALL add
   no non-additive migration.
4. THE Phase 9 changes SHALL preserve the existing `Configuration_Manager` profiles, the
   `container.py` composition root, the `AppError` envelope, and organization tenancy
   without modification.

### Requirement 20: Keyless development preservation (guardrail)

**User Story:** As a new developer, I want the keyless promise preserved, so that I can run
the full Platform with zero credentials.

#### Acceptance Criteria

1. WHEN `docker compose up --build` is run against the Local_Compose with no credentials,
   THE Platform SHALL reach a serving state with the Frontend_Client, Backend_Service,
   PostgreSQL, and Redis all healthy.
2. THE Local_Compose SHALL keep every integration, external LLM, and tracing capability
   disabled by default so that no external network call is made without a credential.
3. THE Local_Compose SHALL require no manual setup beyond the single
   `docker compose up --build` command.

### Requirement 21: Deterministic test preservation (guardrail)

**User Story:** As a maintainer, I want deterministic tests preserved, so that CI results
are reproducible without credentials.

#### Acceptance Criteria

1. THE CI_Pipeline SHALL run the keyless backend lane `pytest -m 'not integration' -q` and
   the keyless frontend lane `npm run ci` with no credentials.
2. THE Phase 9 changes SHALL NOT introduce a credential requirement into either keyless
   test lane.
3. WHEN the keyless test lanes run in the CI_Pipeline, THE results SHALL be reproducible
   because no external service is contacted without a credential.

## Scope Boundaries (Out of Scope for Phase 9)

The following are explicitly **not** part of Phase 9. They may be referenced in the
Deployment_Documentation as external or future work but are not implemented here:

- **A specific cloud provider's managed infrastructure** (for example managed Kubernetes,
  managed PostgreSQL/Redis services, or provider-specific load balancers). Phase 9
  targets portable container images and Docker Compose.
- **Kubernetes and Helm** manifests or charts. Orchestration in Phase 9 is Docker Compose.
- **DNS and domain registration.** Assigning hostnames and registering domains is external.
- **Real TLS certificate issuance and renewal** (for example an ACME/Let's Encrypt
  automation). Phase 9 makes the architecture HTTPS-ready and documents certificate
  mounting; actual issuance may be deferred or handled externally.
- **Autoscaling, horizontal replica management, and load-based scaling policies.**
- **Application feature work, API contract changes, or business-logic changes** of any
  kind — Phase 9 is infrastructure only (see Requirement 19).
- **Reconciling the Phase 7 and Phase 8 feature branches onto `main`.** Branch
  consolidation is a source-control activity, not a deployment-infrastructure artifact,
  though the Platform packaged here assumes the consolidated codebase.
