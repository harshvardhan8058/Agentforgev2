# Requirements Document

## Introduction

This spec covers **Phase 5 (Enterprise Controls)** of the AgentForge platform. Phases 1
(Foundation), 2 (Core RAG), 3 (Agentic Layer), and 4 (Multi-Agent Collaboration) are
already built and provide the reusable, pluggable seams this phase builds on and MUST NOT
reimplement: an async FastAPI `API_Service` with a uniform error envelope
(`{ "error": { code, message, details } }`) and typed request/response schemas; a
`Configuration_Manager` (`Settings`) that loads settings exclusively from environment
variables, treats every credential as optional, and keeps the platform bootable with no
external credentials; a composition root (`config/container.py`) that wires the object
graph behind abstract interfaces and is the only place concrete implementations are named;
Postgres with pgvector plus a versioned SQL migration runner (`db/migrations.py`); Redis;
the Phase 2 RAG pipeline persisting `documents` and `chunks`; the Phase 3 agentic layer
persisting `conversations`, `messages`, `agent_runs`, and `trace_entries`; the Phase 4
multi-agent layer persisting `multi_agent_runs`, `approval_decisions`, and
`run_checkpoints`; a pluggable `LLM_Provider` with a deterministic keyless
`Fallback_Provider`; and long-term memory backed by the `Embedding_Provider` and
`Vector_Store`. Every prior phase runs and tests fully **keyless** by default, and Phase 5
MUST preserve that promise.

Phase 5 adds **enterprise controls** that make the platform safe for multiple tenants:
a local **Authentication** mechanism (JWT bearer tokens issued after password
verification, passwords hashed at rest); **Organizations and Teams** with membership; a
**Role-Based Access Control (RBAC)** model mapping roles to permissions and permissions to
actions; strict **Multi-Tenancy** so every tenant-owned resource is scoped to an
organization and no principal can ever read or mutate another organization's data;
organization-scoped **API keys** (hashed at rest, creatable, listable, and revocable);
per-principal **Rate limiting** backed by Redis; and the application of authentication,
tenant scoping, and authorization to the **existing** ingest, query, documents,
conversations, agent, and multi-agent endpoints. Enforcement MUST be delivered through
reusable FastAPI dependencies (a current-principal dependency and a tenant-scoping /
authorization dependency) so new endpoints adopt it without bespoke logic, and adding a
new role or permission MUST NOT require rewriting endpoints. Tenant isolation MUST be
enforced at the data-access layer, not only in request handlers. New persistence
(`users`, `organizations`, `teams`, `memberships`, `api_keys`, and role/permission data)
arrives via new additive migrations, and an `org_id` tenant column is added to every
existing tenant-owned table.

Explicitly OUT OF SCOPE for this spec (reserved for later phases): production
observability (LangSmith tracing, cost/token analytics, prompt versioning, evaluation
frameworks, guardrails); the React frontend; third-party integrations; and cloud
deployment. Single-sign-on and OAuth social login are also out of scope — this phase
delivers JWT plus a local credential store only. The authentication mechanism MUST remain
modular behind a clean seam so an external identity provider can be added in a later phase
without rewriting endpoints.

## Glossary

- **Enterprise_Layer**: The Phase 5 subsystem delivered by this spec, composed of the
  Auth_Service, the Identity_Store (Users, Organizations, Teams, Memberships), the
  RBAC_Policy, the API_Key_Service, the Rate_Limiter, and the reusable Principal and
  Authorization FastAPI dependencies, together with the Phase 5 extensions to the
  API_Service, Configuration_Manager, and Database.
- **Auth_Service**: The component that verifies user credentials, issues Access_Tokens,
  and resolves an Access_Token or an API_Key back to an authenticated Principal.
- **User**: A person with an identity in the platform, identified by a unique identifier
  and a unique email, holding a hashed password credential.
- **Password_Hash**: The irreversibly hashed representation of a User's password, stored at
  rest; the plaintext password is never persisted.
- **Access_Token**: A signed JSON Web Token (JWT) bearer token issued by the Auth_Service
  after successful credential verification, carrying the authenticated User's identity,
  active Organization, and expiry.
- **Token_Signing_Secret**: The secret used to sign and verify Access_Tokens, supplied by
  the Configuration_Manager; optional with a generated development default and required in
  the production profile.
- **Organization**: A tenant that owns resources and contains Teams and Memberships; the
  unit of data isolation. Also referred to as a tenant.
- **Org_Id**: The identifier of the Organization that owns a tenant-owned resource; the
  tenant scoping key.
- **Team**: A named group within an Organization to which Users may belong.
- **Membership**: The association of a User with an Organization that carries the User's
  Role within that Organization.
- **Team_Membership**: The association of a User with a Team within an Organization.
- **Role**: A named set of Permissions assigned to a Membership, drawn from {owner, admin,
  member, viewer}.
- **Permission**: A named capability that authorizes an Action, drawn from {manage_members,
  manage_api_keys, ingest_documents, run_agents, read}.
- **Action**: An operation exposed by the API_Service that requires a specific Permission
  to perform.
- **RBAC_Policy**: The component that maps each Role to its Permissions and determines
  whether a Principal is authorized to perform an Action.
- **Principal**: The authenticated identity making a request, resolved from either an
  Access_Token (a User Principal) or an API_Key (an API-key Principal), carrying an Org_Id,
  a Role, and the resulting effective Permissions.
- **API_Key**: A credential issued by an Organization for programmatic access, scoped to
  that Organization and to a Role or Permission set, presented on requests to authenticate
  as an API-key Principal.
- **API_Key_Secret**: The plaintext secret value of an API_Key, returned only once at
  creation time and never persisted in plaintext.
- **API_Key_Hash**: The irreversibly hashed representation of an API_Key stored at rest and
  compared against a presented API_Key_Secret.
- **API_Key_Service**: The component that creates, lists, and revokes API_Keys and resolves
  a presented API_Key_Secret to an API-key Principal.
- **Rate_Limiter**: The component that limits the number of requests a Principal may make
  within a configured time window, backed by Redis.
- **Rate_Limit_Window**: The configured time span over which the Rate_Limiter counts a
  Principal's requests.
- **Rate_Limit_Max**: The configured maximum number of requests a Principal may make within
  a single Rate_Limit_Window.
- **Principal_Dependency**: The reusable FastAPI dependency that resolves the current
  Principal from an Access_Token or an API_Key for a request.
- **Authorization_Dependency**: The reusable FastAPI dependency that enforces tenant
  scoping and the Permission required for an Action.
- **Tenant_Scoped_Resource**: Any resource owned by an Organization — a Document, Chunk,
  Conversation, Message, Agent_Run, Trace entry, Multi_Agent_Run, Approval_Decision,
  Run_Checkpoint, or long-term memory record — carrying an Org_Id.
- **Identity_Store**: The persistence component for Users, Organizations, Teams,
  Memberships, and API_Keys.
- **API_Service**: The existing FastAPI application that exposes HTTP endpoints using the
  uniform error envelope.
- **Configuration_Manager**: The existing component that loads and validates settings and
  secrets from environment variables.
- **Database**: The existing PostgreSQL instance with pgvector, extended by additive
  Phase 5 migrations applied through the existing migration runner.
- **Error_Envelope**: The existing uniform error response body of the form
  `{ "error": { code, message, details } }`.
- **Keyless_Mode**: The default operating mode in which no external credential is
  configured and the platform, including the full Phase 5 test suite, runs deterministically.

## Requirements

### Requirement 1: User Authentication with JWT and Hashed Passwords

**User Story:** As a platform user, I want to register and log in with a password and
receive a bearer token, so that my identity is verified without an external identity
provider.

#### Acceptance Criteria

1. WHEN a User is registered with an email and a password, THE Auth_Service SHALL store a Password_Hash produced by the configured password hashing algorithm and SHALL NOT persist the plaintext password.
2. WHEN a login request presents an email and a password that match a stored User and Password_Hash, THE Auth_Service SHALL issue an Access_Token signed with the Token_Signing_Secret that carries the User identity, the active Org_Id, and an expiry timestamp.
3. IF a login request presents an email that has no matching User or a password that does not match the stored Password_Hash, THEN THE Auth_Service SHALL reject the request, return an authentication-failed response using the Error_Envelope with HTTP status 401, and SHALL NOT issue an Access_Token.
4. WHEN the Principal_Dependency receives a request bearing a valid, unexpired Access_Token, THE Auth_Service SHALL resolve the Access_Token to a User Principal carrying the User identity, the Org_Id, and the Role recorded in the token.
5. IF a request presents an Access_Token whose signature is invalid or whose expiry timestamp has passed, THEN THE Principal_Dependency SHALL reject the request with HTTP status 401 using the Error_Envelope and SHALL NOT resolve a Principal.
6. THE Auth_Service SHALL compare a presented password against the stored Password_Hash using only the hashing algorithm's verification function and SHALL NOT compare plaintext passwords directly.
7. WHERE the Configuration_Manager provides no Token_Signing_Secret AND the profile is local, THE Auth_Service SHALL use a generated development Token_Signing_Secret so that Keyless_Mode boot and testing succeed.
8. IF the profile is production AND the Configuration_Manager provides no Token_Signing_Secret, THEN THE Configuration_Manager SHALL prevent startup and report that the Token_Signing_Secret is missing.

### Requirement 2: Organizations, Teams, and Memberships

**User Story:** As an organization owner, I want users organized into organizations and
teams with roles, so that I can structure access to my tenant's resources.

#### Acceptance Criteria

1. WHEN an Organization is created, THE Identity_Store SHALL persist the Organization with a unique Org_Id.
2. WHEN a User is added to an Organization with a Role, THE Identity_Store SHALL persist a Membership associating the User, the Org_Id, and the Role.
3. WHEN a Team is created within an Organization, THE Identity_Store SHALL persist the Team associated with that Org_Id.
4. WHEN a User who holds a Membership in an Organization is added to a Team within that same Organization, THE Identity_Store SHALL persist a Team_Membership associating the User with the Team.
5. IF a request attempts to add a User to a Team of an Organization in which that User holds no Membership, THEN THE Identity_Store SHALL reject the request and return a membership-required error using the Error_Envelope.
6. THE Identity_Store SHALL ensure that every Team and every Membership references exactly one Org_Id, such that no Team or Membership is shared across Organizations.
7. THE Identity_Store SHALL ensure that a User holds at most one Membership per Organization.

### Requirement 3: Role-Based Access Control

**User Story:** As an administrator, I want roles to grant defined permissions and actions
to be authorized by permission, so that access reflects each user's responsibilities.

#### Acceptance Criteria

1. THE RBAC_Policy SHALL define the Roles {owner, admin, member, viewer} and the Permissions {manage_members, manage_api_keys, ingest_documents, run_agents, read}.
2. THE RBAC_Policy SHALL map each Role to a fixed set of Permissions such that the Permissions of a viewer are a subset of the Permissions of a member, the Permissions of a member are a subset of the Permissions of an admin, and the Permissions of an admin are a subset of the Permissions of an owner.
3. WHEN the Authorization_Dependency evaluates a Principal against an Action that requires a Permission, THE RBAC_Policy SHALL authorize the Action if and only if the Principal's Role grants the required Permission.
4. IF a Principal whose Role does not grant the required Permission attempts an Action, THEN THE Authorization_Dependency SHALL reject the request with HTTP status 403 using the Error_Envelope and SHALL NOT perform the Action.
5. THE RBAC_Policy SHALL grant the read Permission to every defined Role.
6. THE Enterprise_Layer SHALL allow a new Role or a new Permission to be added by extending the RBAC_Policy mapping without modifying any endpoint handler or the Authorization_Dependency.

### Requirement 4: Multi-Tenant Data Isolation

**User Story:** As an organization owner, I want my organization's data strictly isolated
from every other organization, so that no other tenant can ever read or change my data.

#### Acceptance Criteria

1. THE Enterprise_Layer SHALL associate every Tenant_Scoped_Resource with the Org_Id of the Organization that owns it.
2. WHEN a Principal requests a set of Tenant_Scoped_Resources, THE Enterprise_Layer SHALL return only resources whose Org_Id equals the Principal's Org_Id.
3. IF a Principal requests or attempts to mutate a Tenant_Scoped_Resource whose Org_Id differs from the Principal's Org_Id, THEN THE Enterprise_Layer SHALL deny access by returning HTTP status 404 using the Error_Envelope and SHALL NOT read or modify that resource.
4. WHEN a Tenant_Scoped_Resource is created by a Principal, THE Enterprise_Layer SHALL set the resource's Org_Id to the Principal's Org_Id.
5. THE Enterprise_Layer SHALL enforce tenant scoping at the data-access layer by constraining every query and mutation of a Tenant_Scoped_Resource by Org_Id, independently of any check performed in a request handler.
6. THE Enterprise_Layer SHALL ensure that no operation on Tenant_Scoped_Resources returns or modifies a resource whose Org_Id differs from the requesting Principal's Org_Id, across all resource types {Document, Chunk, Conversation, Message, Agent_Run, Trace entry, Multi_Agent_Run, Approval_Decision, Run_Checkpoint, long-term memory record}.

### Requirement 5: Organization-Scoped API Keys

**User Story:** As an administrator, I want to issue, list, and revoke API keys scoped to
my organization, so that programmatic clients can authenticate without a user login.

#### Acceptance Criteria

1. WHEN a Principal holding the manage_api_keys Permission requests creation of an API_Key for the Principal's Organization, THE API_Key_Service SHALL generate an API_Key_Secret, persist only its API_Key_Hash scoped to the Org_Id and a Role or Permission set, and return the API_Key_Secret exactly once in the creation response.
2. THE API_Key_Service SHALL store only the API_Key_Hash at rest and SHALL NOT persist the API_Key_Secret in plaintext.
3. WHEN a request presents a valid, non-revoked API_Key_Secret, THE Auth_Service SHALL resolve it to an API-key Principal carrying the API_Key's Org_Id and its associated Permissions.
4. WHEN a Principal holding the manage_api_keys Permission requests the list of API_Keys for the Principal's Organization, THE API_Key_Service SHALL return each API_Key's metadata scoped to that Org_Id and SHALL NOT include any API_Key_Secret or API_Key_Hash.
5. WHEN a Principal holding the manage_api_keys Permission revokes an API_Key belonging to the Principal's Organization, THE API_Key_Service SHALL mark the API_Key as revoked.
6. IF a request presents an API_Key_Secret that is revoked, unknown, or whose API_Key_Hash does not match any stored API_Key_Hash, THEN THE Auth_Service SHALL reject the request with HTTP status 401 using the Error_Envelope and SHALL NOT resolve a Principal.
7. IF a Principal attempts to list or revoke an API_Key whose Org_Id differs from the Principal's Org_Id, THEN THE API_Key_Service SHALL deny the operation by returning HTTP status 404 using the Error_Envelope.

### Requirement 6: Per-Principal Rate Limiting

**User Story:** As an operator, I want per-principal rate limiting backed by Redis, so that
no single user, organization, or API key can overwhelm the platform.

#### Acceptance Criteria

1. WHEN a Principal makes a request WHILE the Rate_Limiter is enabled, THE Rate_Limiter SHALL count the request against that Principal within the current Rate_Limit_Window using Redis.
2. WHILE a Principal has made fewer than Rate_Limit_Max requests within the current Rate_Limit_Window, THE Rate_Limiter SHALL permit the request.
3. IF a Principal has already made Rate_Limit_Max requests within the current Rate_Limit_Window, THEN THE Rate_Limiter SHALL reject the request with HTTP status 429 using the Error_Envelope and SHALL NOT process the Action.
4. THE Rate_Limiter SHALL obtain Rate_Limit_Max and Rate_Limit_Window from the Configuration_Manager, applying bounded default values when no configured values are provided.
5. WHERE Keyless_Mode or a test mode is active, THE Rate_Limiter SHALL be disabled or use a deterministic fake clock and limiter so that the automated test suite produces deterministic results.
6. THE Rate_Limiter SHALL count requests independently per Principal so that one Principal reaching Rate_Limit_Max does not affect the request count of any other Principal.

### Requirement 7: Authentication and Tenancy Applied to Existing Endpoints

**User Story:** As an organization owner, I want the existing ingest, query, documents,
conversations, agent, and multi-agent endpoints to require authentication and enforce my
organization's boundary, so that prior phases become tenant-safe without being rewritten.

#### Acceptance Criteria

1. WHEN a request is made to an existing ingest, query, documents, conversations, agent, or multi-agent endpoint WITHOUT a valid Access_Token or API_Key, THE API_Service SHALL reject the request with HTTP status 401 using the Error_Envelope.
2. WHEN an authenticated Principal makes a request to an existing endpoint WITHOUT the Permission required by that endpoint's Action, THE API_Service SHALL reject the request with HTTP status 403 using the Error_Envelope.
3. WHEN an authenticated Principal ingests a document, creates a conversation, starts an agent run, or starts a multi-agent run, THE API_Service SHALL create the resulting Tenant_Scoped_Resource with the Principal's Org_Id.
4. WHEN an authenticated Principal queries, reads, or streams a Tenant_Scoped_Resource whose Org_Id equals the Principal's Org_Id AND the Principal holds the required Permission, THE API_Service SHALL perform the Action.
5. IF an authenticated Principal requests a Tenant_Scoped_Resource whose Org_Id differs from the Principal's Org_Id, THEN THE API_Service SHALL respond with HTTP status 404 using the Error_Envelope, consistent with Requirement 4.3.
6. THE API_Service SHALL enforce authentication, tenant scoping, and Permission checks on the existing endpoints by applying the Principal_Dependency and the Authorization_Dependency and SHALL reuse the existing Error_Envelope.
7. THE Enterprise_Layer SHALL enable a new endpoint to adopt authentication, tenant scoping, and authorization by declaring the Principal_Dependency and the Authorization_Dependency without introducing bespoke authorization logic in the endpoint handler.

### Requirement 8: Enterprise Persistence and Additive Migrations

**User Story:** As a developer, I want identity, tenancy, and API-key data persisted and an
org_id added to existing tables, so that the platform stores enterprise state without
disrupting prior phases.

#### Acceptance Criteria

1. THE Enterprise_Layer SHALL add new database migrations, applied through the existing migration runner, that create tables for Users, Organizations, Teams, Memberships, Team_Memberships, and API_Keys.
2. THE Enterprise_Layer SHALL add an Org_Id column with a foreign key to the Organizations table on every existing Tenant_Scoped_Resource table, including documents, chunks, conversations, messages, agent_runs, trace_entries, multi_agent_runs, approval_decisions, and run_checkpoints.
3. WHEN the Phase 5 migrations run through the existing migration runner, THE Database SHALL apply them additively without dropping or altering the meaning of any column created by a prior phase.
4. IF a Phase 5 migration fails, THEN THE migration runner SHALL halt on the failing migration and report the failing migration identifier, consistent with the existing runner behavior.
5. THE Enterprise_Layer SHALL persist the Password_Hash and the API_Key_Hash in the Database and SHALL NOT persist any plaintext password or API_Key_Secret.
6. THE Enterprise_Layer SHALL document the migration and backfill approach for the added Org_Id columns, noting that no production data exists so a straightforward additive migration is applied.

### Requirement 9: Reuse of Existing Platform Seams

**User Story:** As a developer, I want the enterprise layer to reuse the existing platform
seams, so that behavior stays consistent and no prior-phase component is reimplemented.

#### Acceptance Criteria

1. THE Enterprise_Layer SHALL expose all Phase 5 endpoints through the existing API_Service and SHALL reuse the existing Error_Envelope for every response.
2. THE Enterprise_Layer SHALL source all settings and secrets, including the Token_Signing_Secret, the Rate_Limit_Max, and the Rate_Limit_Window, through the existing Configuration_Manager and SHALL NOT introduce a separate configuration mechanism.
3. THE Enterprise_Layer SHALL persist enterprise state in the existing Postgres Database using the existing migration runner and SHALL NOT introduce a separate persistence mechanism.
4. THE Enterprise_Layer SHALL back the Rate_Limiter with the existing Redis instance and SHALL NOT introduce a separate rate-limiting store.
5. THE Enterprise_Layer SHALL wire the Auth_Service, Identity_Store, RBAC_Policy, API_Key_Service, and Rate_Limiter through the existing composition root and SHALL NOT reimplement the existing RAG, agentic, or multi-agent components.
6. THE Enterprise_Layer SHALL keep the authentication mechanism behind a clean seam so that an external identity provider can be added later without modifying endpoint handlers.

### Requirement 10: Keyless Runnability and Deterministic Testing

**User Story:** As a developer, I want the enterprise layer runnable and testable with no
external credentials, so that I can verify authentication, tenancy, and authorization
locally and deterministically.

#### Acceptance Criteria

1. WHERE no external credential is configured, THE Enterprise_Layer SHALL boot and run using a local Identity_Store, a generated development Token_Signing_Secret, and a disabled or deterministic Rate_Limiter, preserving Keyless_Mode.
2. THE Enterprise_Layer SHALL include automated tests for credential verification and Access_Token issuance, RBAC authorization, tenant isolation across resource types, API_Key creation and revocation, and Rate_Limiter behavior.
3. WHEN a developer runs the documented test command with no external credentials configured AND the automated test suite successfully executes, THE Enterprise_Layer SHALL report a pass or fail result reflecting the executed tests.
4. THE Enterprise_Layer SHALL provide an automated test verifying that no authenticated Principal can read or mutate a Tenant_Scoped_Resource whose Org_Id differs from the Principal's Org_Id.
5. THE Enterprise_Layer SHALL provide an automated test verifying that an Action is permitted if and only if the Principal's Role grants the required Permission.
6. THE Enterprise_Layer SHALL provide an automated test verifying that a revoked API_Key never resolves to a Principal.
7. THE Enterprise_Layer SHALL provide an automated test verifying that the Rate_Limiter permits at most Rate_Limit_Max requests per Rate_Limit_Window for a single Principal using a deterministic clock.

### Requirement 11: Documented Design Decisions

**User Story:** As a developer learning the stack, I want the enterprise layer's design
decisions documented, so that I understand why it is built this way and how to extend it.

#### Acceptance Criteria

1. THE Enterprise_Layer SHALL document the rationale for each major architectural decision of the enterprise layer in a written record within the repository.
2. THE Enterprise_Layer SHALL document how the RBAC_Policy maps Roles to Permissions and Permissions to Actions, and how a new Role or Permission is added without rewriting endpoints.
3. THE Enterprise_Layer SHALL document how tenant isolation is enforced at the data-access layer and how the Principal_Dependency and Authorization_Dependency are adopted by new endpoints.
4. THE Enterprise_Layer SHALL document the chosen password hashing algorithm and the API_Key hashing approach, and how secrets are supplied through the Configuration_Manager while preserving keyless development boot.
