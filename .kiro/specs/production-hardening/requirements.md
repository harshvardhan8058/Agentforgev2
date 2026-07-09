# Requirements Document

## Introduction

AgentForge is an enterprise multi-agent RAG platform (a FastAPI backend and a React SPA,
backed by PostgreSQL/pgvector and Redis, fronted by an nginx reverse proxy, and packaged
with Docker Compose). The platform boots keyless: `docker compose up` brings up the full
stack with zero credentials. Five deployment bugs have already been fixed on the branch
`fix/production-runtime-issues` (multi-statement migrations, entrypoint CRLF, healthcheck
IPv6 target, frontend same-origin API base URL, and the async rate-limiter client).

This spec is a **production-hardening remediation initiative**. It closes the remaining
backend and infrastructure production-readiness gaps found in an audit (labeled B1–B6). It
introduces **no new product feature** and makes **no breaking API change**. The
frontend/UX redesign is explicitly **out of scope** and will be handled by a separate
spec.

Each requirement below is framed as a desired outcome with testable acceptance criteria,
not as a prescribed implementation. The remediation must respect the platform's existing
architecture: a single composition root (`config/container.py`) is the only place that
names concrete implementations; provider selection happens through dependency-injection
seams; secrets are typed as `SecretStr`; multi-tenancy is enforced by `org_id` (a
cross-tenant access resolves to 404, never 403); errors are returned through the uniform
`AppError` envelope; and database migrations are additive-only. The keyless-by-default
boot and the deterministic keyless unit test lane (currently 472 tests) must remain
intact.

## Glossary

- **Platform**: The complete AgentForge system — the Backend_Service, the Frontend_Client,
  PostgreSQL (pgvector), and Redis, fronted by the Reverse_Proxy.
- **Backend_Service**: The FastAPI application served by uvicorn (`agentforge.main:app`).
- **Frontend_Client**: The React single-page application in `/frontend`.
- **Reverse_Proxy**: The nginx-based single entry point that routes browser traffic to the
  Frontend_Client and the Backend_Service (API + SSE).
- **Composition_Root**: The single module `config/container.py` — the only place concrete
  provider implementations are named and wired through dependency-injection seams.
- **Environment_Profile**: A named deployment configuration; the two profiles are `local`
  (keyless development) and `production`, aligned with the existing `Settings.profile`.
- **Local_Stack**: The default one-command stack (`docker compose up`) that runs under the
  `local` Environment_Profile with `PROFILE=local` and zero credentials.
- **Production_Stack**: The stack run with the production Compose overlay under the
  `production` Environment_Profile with credentials supplied from a Secret_Source.
- **Persistent_Store**: A data store whose contents survive a container restart because
  they are held in the running PostgreSQL database rather than in process memory.
- **Domain_Store**: Any of the application data stores currently gated behind the
  `production` profile — identity, API keys, conversations, traces, usage, prompts,
  evaluations, multi-agent runs, and integration connections.
- **Secret_Source**: The runtime origin of a credential (an environment variable injected
  from an operator-managed environment file or an orchestrator secret store); credentials
  are never baked into images or committed to version control.
- **Token_Signing_Secret**: The JWT signing secret (`JWT_SECRET`), typed as `SecretStr`.
- **SSE_Route**: A Backend_Service route that emits Server-Sent Events — `/agent/stream`
  and the `/multi-agent/*/stream` routes.
- **Backend_Image**: The container image that packages the Backend_Service, built from the
  root `Dockerfile`.
- **API_Contract**: The committed OpenAPI description of the Backend_Service routes
  (`frontend/openapi.json`) used by the Frontend_Client codegen.
- **Keyless_Unit_Lane**: The deterministic backend test lane run without credentials
  (`pytest -m 'not integration'`), currently 472 tests.

## Requirements

### Requirement 1: Default local stack persists data across restarts

**User Story:** As a developer running the default stack, I want my users, organizations,
prompts, and other application data to survive a restart, so that the platform behaves
like a real deployment without requiring any credentials.

**Root cause (B1):** The one-command stack runs `PROFILE=local`, and the Composition_Root
gates every Domain_Store behind `profile == "production"`. Under `local`, the identity,
API-key, conversation, trace, usage, prompt, evaluation, multi-agent-run, and
integration-connection stores are held in process memory and are lost on restart, while a
fully-migrated PostgreSQL is used only for documents and vectors.

#### Acceptance Criteria

1. WHEN the Local_Stack starts, THE Backend_Service SHALL select a Persistent_Store backed
   by the running PostgreSQL for each of the ten Domain_Stores — identity, API-key,
   conversation, trace, usage, prompt, evaluation, multi-agent-run, integration-connection,
   and any remaining audited store — and SHALL NOT select any process-memory backing for
   them on the Local_Stack.
2. WHEN application data is written through a Domain_Store and the Local_Stack is then
   restarted with `docker compose restart`, THE Backend_Service SHALL, on a read within the
   same `org_id` context, return field values identical to those written before the
   restart.
3. THE Backend_Service SHALL select the persistent Domain_Store backing on the Local_Stack
   without requiring any credential to be supplied.
4. WHEN a Domain_Store is accessed on the Local_Stack, THE Backend_Service SHALL enforce
   `org_id` tenancy so that a cross-tenant read of another `org_id`'s record resolves to a
   404 response and SHALL NOT return a 403 response or the record's contents.
5. THE Local_Stack SHALL continue to reach a serving state — with the Frontend_Client,
   Backend_Service, PostgreSQL, and Redis each reporting a healthy health-check status
   within 180 seconds — using only `docker compose up` and no credentials.
6. THE store-selection change SHALL be confined to the Composition_Root seams and SHALL
   NOT modify the service layer, router layer, or any Domain_Store interface.

### Requirement 2: Coherent keyless-to-production configuration boundary

**User Story:** As a platform operator, I want the production profile to boot
deterministically with secrets supplied through the production overlay, so that a
production deployment starts predictably and the keyless-versus-production boundary is
explicit.

**Root cause (B2):** In the `production` profile, `load_settings` aborts when `JWT_SECRET`
is absent. The boundary between the keyless `local` profile and the credentialed
`production` profile must be coherent and documented.

#### Acceptance Criteria

1. WHEN the Production_Stack starts with the Token_Signing_Secret and the required
   non-secret settings — those documented as required for the `production` Environment_Profile —
   supplied from a Secret_Source, THE Backend_Service SHALL boot deterministically to a
   health-based serving state in which the Backend_Service, PostgreSQL, and Redis are
   healthy and accepting API requests, reproducible across repeated boots with identical
   supplied settings.
2. WHERE the `production` Environment_Profile is selected, THE Backend_Service SHALL
   consume the Token_Signing_Secret as a `SecretStr` sourced at runtime and SHALL NOT read
   it from any version-controlled file.
3. IF the `production` Environment_Profile is selected and the Token_Signing_Secret is
   absent, THEN THE Backend_Service SHALL abort before serving, serve no requests, and
   report the missing setting by name through the existing configuration error path.
4. WHEN the `local` Environment_Profile is selected with no credentials, THE
   Backend_Service SHALL boot keyless using the existing per-boot development secret path,
   requiring no secret to be supplied.
5. THE Platform SHALL document, per setting and by name, which settings are required and
   which are optional in the `production` Environment_Profile and in the `local`
   Environment_Profile.
6. IF the `production` Environment_Profile is selected and any documented required
   non-secret setting is absent, THEN THE Backend_Service SHALL abort startup and report
   the missing setting by name.
7. WHERE the `production` Environment_Profile is selected, THE Backend_Service SHALL NOT
   fall back to the per-boot development secret path.

### Requirement 3: Server-Sent Events stream correctly through the proxy

**User Story:** As an end user, I want streamed agent and multi-agent responses to arrive
incrementally, so that streaming does not stall or arrive only after the response
completes.

**Root cause (B3):** SSE responses on the SSE_Routes must reach the client unbuffered
through the Reverse_Proxy, with read timeouts long enough to sustain a live stream.

#### Acceptance Criteria

1. WHEN the Backend_Service emits an SSE event on an SSE_Route, THE Reverse_Proxy SHALL
   forward that event to the client within 1 second of receiving it, without waiting for
   the overall SSE response to complete and without combining multiple events into a single
   transmission to the client.
2. WHILE an SSE connection is open on an SSE_Route, THE Reverse_Proxy SHALL keep the
   connection open across inactivity intervals of up to at least 300 seconds between
   consecutive events and SHALL NOT close the connection due to such inactivity while the
   Backend_Service connection remains open.
3. WHILE an SSE connection is open on an SSE_Route, THE Reverse_Proxy SHALL sustain a
   single connection for a total duration of at least 3600 seconds without closing it,
   provided the Backend_Service connection remains open.
4. THE Reverse_Proxy SHALL forward each SSE event and each JSON response body byte-for-byte
   identical to what the Backend_Service emitted, and SHALL preserve the original order of
   SSE events, so that request and response payloads are not altered in transit.
5. WHEN the Backend_Service emits a non-streaming JSON response, THE Reverse_Proxy SHALL
   forward the complete response body byte-for-byte identical to the Backend_Service
   output, so that non-streaming routes are unaffected.
6. IF the Backend_Service closes the SSE connection or the upstream connection fails, THEN
   THE Reverse_Proxy SHALL close the corresponding client connection and SHALL retain all
   events already forwarded to the client without altering or replaying them.

### Requirement 4: Reduced backend image size

**User Story:** As a platform operator, I want a substantially smaller Backend_Image, so
that builds and deploys are fast and inexpensive.

**Root cause (B4):** The Backend_Image is approximately 17.8 GB because it bundles the
CUDA build of torch, causing build times around 20 minutes and heavy deploys.

#### Acceptance Criteria

1. THE Backend_Image SHALL install a CPU-only torch build path, such that the built image
   contains no CUDA or GPU-specific runtime libraries or drivers.
2. THE Backend_Image SHALL have a built (uncompressed) image size of no more than 4 GB,
   measured from the produced image.
3. WHEN the Keyless_Unit_Lane is executed against the Backend_Image, THE Backend_Service
   SHALL produce pass/fail test outcomes identical to those produced by the pre-reduction
   baseline image.
4. WHEN identical API requests are issued to the Backend_Service running from the
   Backend_Image, THE Backend_Service SHALL return responses equivalent in structure and
   payload values to those returned by the pre-reduction baseline image for the same
   inputs.
5. THE Backend_Image SHALL complete both build and startup to a ready-to-serve state
   without any credential, secret, or authentication environment variable being supplied.
6. WHEN the Backend_Image is run, THE Backend_Service SHALL execute as a non-root user and
   listen on the configured port value.

### Requirement 5: No dangling build artifacts in the repository

**User Story:** As a maintainer, I want the repository free of stray, untracked build
artifacts, so that the build inputs are unambiguous and reproducible.

**Root cause (B5):** A stray untracked `Dockerfile.verify` exists in the repository root.

#### Acceptance Criteria

1. THE Platform repository version-control status SHALL report zero untracked entries for
   the `Dockerfile.verify` path at the repository root.
2. WHERE the verification Dockerfile serves an ongoing purpose — meaning it is referenced
   by at least one tracked build or CI configuration file — THE Platform SHALL track it in
   version control.
3. IF the verification Dockerfile is referenced by no tracked build or CI configuration
   file, THEN THE Platform SHALL remove it such that version-control status reports it as
   neither tracked nor untracked.
4. WHEN a maintainer runs a version-control status check, THE check SHALL report zero
   untracked build-artifact files at the repository root.

### Requirement 6: Committed API contract matches the mounted routes

**User Story:** As a frontend developer, I want the committed API contract to match the
routes the Backend_Service actually mounts, so that generated clients are accurate and do
not drift from the server.

**Root cause (B6):** The committed `frontend/openapi.json` is stale — it is missing
`GET /integrations/status`, which the Backend_Service mounts.

#### Acceptance Criteria

1. THE API_Contract SHALL include, for every route mounted by the Backend_Service —
   including `GET /integrations/status` — a matching path, HTTP method, and operation
   definition (parameters, request body schema, and response schema) with no route or
   operation definition missing relative to the schema generated from the mounted routes.
2. THE API_Contract SHALL contain no path, HTTP method, or operation definition
   (parameters, request body schema, or response schema) that is extra relative to the
   schema generated from the mounted Backend_Service routes.
3. WHEN the committed API_Contract matches the schema generated from the mounted
   Backend_Service routes, THE automated drift check SHALL report success.
4. IF the committed API_Contract differs from the schema generated from the mounted
   Backend_Service routes, THEN THE automated drift check SHALL report failure and identify
   each differing route.
5. WHEN the automated drift check runs in the keyless environment, THE check SHALL complete
   without requiring or reading any credential, and SHALL produce the same result on
   repeated runs given unchanged inputs.

### Requirement 7: No new features and no breaking API changes (guardrail)

**User Story:** As the platform owner, I want this initiative to remediate only, so that no
new product capability is introduced and no consumer of the API is broken.

#### Acceptance Criteria

1. THE production-hardening changes SHALL NOT introduce any new product feature.
2. THE Backend_Service HTTP and SSE API contract SHALL remain backward compatible, so that
   an existing client continues to function without modification.
3. THE production-hardening changes SHALL NOT remove or rename any existing route,
   request field, or response field relied upon by an existing client.

### Requirement 8: Architecture preservation (guardrail)

**User Story:** As a maintainer, I want the existing architecture preserved, so that
remediation does not erode the seams that keep the platform maintainable.

#### Acceptance Criteria

1. THE Composition_Root SHALL remain the only module that names concrete provider
   implementations.
2. THE production-hardening changes SHALL wire provider and store selection through the
   existing dependency-injection seams and SHALL NOT bypass them.
3. THE production-hardening changes SHALL NOT rewrite working service-layer or
   router-layer code beyond what a remediation requires.
4. THE production-hardening changes SHALL preserve the uniform `AppError` error envelope,
   the `org_id` multi-tenancy behavior (a cross-tenant access resolves to 404, never 403),
   and `SecretStr` credential typing.

### Requirement 9: Keyless-by-default boot preservation (guardrail)

**User Story:** As a new developer, I want the keyless promise preserved, so that I can run
the full Platform with zero credentials.

#### Acceptance Criteria

1. WHEN `docker compose up` is run against the Local_Stack with no credentials, THE
   Platform SHALL reach a serving state with the Frontend_Client, Backend_Service,
   PostgreSQL, and Redis all healthy.
2. THE Local_Stack SHALL keep every integration, external LLM, and tracing capability
   disabled by default so that no external network call is made without a credential.
3. THE production-hardening changes SHALL NOT introduce any credential requirement into the
   default `docker compose up` boot.

### Requirement 10: Deterministic keyless test preservation (guardrail)

**User Story:** As a maintainer, I want the deterministic keyless test lane kept green, so
that CI results remain reproducible without credentials.

#### Acceptance Criteria

1. THE production-hardening changes SHALL keep the Keyless_Unit_Lane passing, preserving
   the currently green suite of 472 tests.
2. THE production-hardening changes SHALL NOT introduce any credential requirement into the
   Keyless_Unit_Lane.
3. WHEN the Keyless_Unit_Lane runs, THE results SHALL be reproducible because no external
   service is contacted without a credential.

### Requirement 11: Additive-only migrations (guardrail)

**User Story:** As a platform operator, I want migrations to remain additive, so that
existing deployments upgrade safely without destructive schema changes.

#### Acceptance Criteria

1. THE production-hardening changes SHALL add only additive database migrations.
2. THE production-hardening changes SHALL NOT rewrite or delete any existing migration.
3. WHERE a new migration is required, THE migration SHALL be tracked by the existing
   migration runner so that re-running is safe and idempotent.

### Requirement 12: Minimal, production-ready remediation (guardrail)

**User Story:** As the platform owner, I want each fix to be minimal and production-ready,
so that no temporary workaround or hack is introduced.

#### Acceptance Criteria

1. THE production-hardening changes SHALL implement each fix as a minimal, production-ready
   change rather than a temporary workaround.
2. THE production-hardening changes SHALL NOT introduce a hack, stub, or placeholder that
   would require later rework to reach production quality.

## Scope Boundaries (Out of Scope)

The following are explicitly **not** part of this production-hardening initiative:

- **The frontend/UX redesign.** A separate spec will cover Frontend_Client visual and
  interaction changes.
- **New product features of any kind.** This initiative is remediation only (see
  Requirement 7).
- **Breaking API changes**, including route removals, renames, or incompatible schema
  changes (see Requirement 7).
- **Re-architecting the Composition_Root or the dependency-injection seams.** The existing
  architecture is preserved (see Requirement 8).
- **Destructive or non-additive database migrations** (see Requirement 11).
