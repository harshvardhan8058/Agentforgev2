# Requirements Document

## Introduction

This spec covers **Phase 8 (Third-Party Integrations)** of the AgentForge platform. Phases 1
(Foundation), 2 (Core RAG), 3 (Agentic Layer), 4 (Multi-Agent Collaboration), 5 (Enterprise
Controls), and 6 (Production Observability) are already built and merged, and Phase 7 (React
Web Frontend) is complete in review on PR #14. These phases provide the reusable, pluggable
seams this phase builds on and MUST NOT reimplement:

- The **Tool seam**: an abstract `Tool_Interface` (`tools/base.py`) exposing `name`,
  `description`, `input_schema`, an `available` flag, and `invoke(arguments) -> Tool_Result`,
  plus `Tool_Result` / `Tool_Call` / `ToolError` value types; and a `Tool_Registry`
  (`tools/registry.py`) that registers a tool under its unique name (rejecting duplicates),
  resolves a tool by name, and lists the specs of only the **available** tools so a disabled
  tool is never offered to the agent. The built-in `RAG_Tool` and the `Web_Search_Tool`
  (backed by a pluggable `Search_Provider` with a keyless `Disabled_Search_Provider` default
  and a credentialed `Keyed_Search_Provider`) are the reference patterns this phase mirrors.
- The **agent seams**: the Phase 3 `Agent_Orchestrator` and its `act` graph node, which
  resolve, validate arguments against `input_schema`, and invoke tools purely through the
  `Tool_Registry` — containing a missing tool, invalid arguments, or a raised `ToolError` as a
  bounded observation without crashing the run; and the Phase 4 `Multi_Agent_Orchestrator`,
  whose roles reuse the same `Agent_Orchestrator` and therefore the same `Tool_Registry`.
- The **Configuration_Manager** (`config/settings.py`): a `Settings` object loaded exclusively
  from environment variables, where every credential is an optional `SecretStr` redacted from
  logs / `repr` / `model_dump`, and `active_*()` helpers select a concrete implementation from
  credential presence so the platform boots and tests with zero credentials.
- The **composition root** (`config/container.py`): the ONLY module that names concrete
  implementations, including `build_tool_registry`, which always registers the `RAG_Tool` and
  registers the `Web_Search_Tool` only when its provider is available.
- The **uniform error envelope** (`api/errors.py`): `AppError(code, message, status_code,
  details)` rendered as `{ "error": { code, message, details } }`.
- The **enterprise layer** (Phase 5): a `Principal` (org_id, user_id/key_id, role), the
  `get_current_principal` / `require_permission` FastAPI dependencies, the static `RBAC_Policy`
  (roles owner/admin/member/viewer over permissions manage_members / manage_api_keys /
  ingest_documents / run_agents / read), strict multi-tenancy enforced at the data-access layer
  (cross-tenant access resolves to 404, never 403), the request-scoped tenancy context
  (`enterprise/tenancy.py`) that publishes the acting `org_id` for tools to read without
  widening the `Tool_Interface`, Redis-backed per-principal rate limiting, and the additive
  versioned SQL migration runner.
- The **observability layer** (Phase 6): the `Trace_Recorder`/`Tracing_Exporter` seams and the
  ordered `Guardrail_Pipeline` (`apply_input_guardrail`) whose failures never change a run's
  outcome.

Phase 8 adds **Slack, Gmail, Google Drive, and GitHub as pluggable Tools behind the existing
Tool seam**, available to the Phase 3 agentic and Phase 4 multi-agent layers. It is primarily a
**backend** phase. Each integration is a `Tool_Interface` implementation whose real network
work sits behind a per-integration **Connector** transport seam (mirroring the
`Search_Provider` pattern), so each integration is DISABLED when its credential is absent, is
registered only in the composition root, maps its failures onto the uniform `AppError` code
vocabulary, executes under a bounded timeout with no unbounded side effects, and is fully
testable keyless with a mockable Connector requiring no real credentials and no network. The
platform MUST continue to run and pass its entire suite with zero integration credentials, and
existing `RAG_Tool` / `Web_Search_Tool` and agent / multi-agent behavior MUST be unchanged when
no integration is configured.

### In Scope

- A generic mechanism by which each integration is a Tool that self-registers (in the
  composition root), is discoverable by agents through the existing `Tool_Registry`, and is
  gated on configuration so it is enabled only when its credential is present.
- Per-integration enablement via optional `SecretStr` env-only `Settings`, a keyless default
  where all integrations are disabled, and an org-scoped, RBAC-gated way to introspect which
  integrations are enabled.
- The Slack, Gmail, Google Drive, and GitHub tools, each with declared parameters,
  enabled/disabled behavior, a token-based auth model via `SecretStr`, and error mapping.
- Safety and governance reusing Phase 5 RBAC and Phase 6 guardrails: permission gating for tool
  use, rate-limit handling, bounded timeouts, and the guarantee that a disabled or unauthorized
  tool is never invoked.
- Determinism and keyless testability through a mockable Connector seam per integration.
- Backward compatibility of all pre-Phase-8 behavior.
- Optional additive-only persistence of per-organization integration connection records
  (non-secret configuration such as default channel / repository and per-org enablement),
  enforced at the data-access layer.

### Out of Scope (Deferred to a Later Phase)

- Interactive **OAuth authorization UI flows** and per-user OAuth consent screens. Phase 8
  authenticates each integration with a pre-provisioned token/credential supplied through
  env-only `Settings`; browser-based OAuth grant/refresh flows are deferred.
- **Per-organization storage of secret credential material** in the database. Secret material
  in Phase 8 is deployment-level env-only `SecretStr`; only non-secret per-org connection
  configuration is persisted. Org-scoped secret vaulting is deferred.
- New **frontend UI** for managing integrations. Phase 8 delivers the backend tools and the
  introspection API a later frontend phase will consume.
- **Cloud deployment** and provider-specific infrastructure provisioning.
- Streaming / webhook / event-subscription ingestion from the third-party providers (e.g. Slack
  Events API push, Gmail push notifications). Phase 8 covers request-scoped tool invocations
  only.

## Glossary

- **Integration_Layer**: The Phase 8 subsystem delivered by this spec, composed of the four
  Integration_Tools (Slack, Gmail, Google Drive, GitHub), their Connectors, the per-integration
  Settings, the composition-root registration policy, the Integration_Status introspection
  capability, and any org-scoped Integration_Connection persistence.
- **Integration**: A named third-party service AgentForge can act against through a Tool — one
  of `slack`, `gmail`, `google_drive`, or `github`.
- **Integration_Tool**: A concrete `Tool_Interface` implementation that exposes one
  Integration's capabilities to the agent layers. It declares a unique `name`, a `description`,
  an `input_schema`, an `available` flag reflecting its Credential, and an `invoke` operation.
- **Tool_Interface**: The existing abstract Tool contract (`tools/base.py`); the sole seam every
  Integration_Tool implements. Phase 8 MUST NOT fork or extend it.
- **Tool_Registry**: The existing registry (`tools/registry.py`) that holds registered Tools,
  rejects duplicate names, resolves by name, and lists specs of only the available Tools. Phase
  8 MUST reuse it and MUST NOT introduce a parallel registry.
- **Tool_Result**: The existing value type returned by `invoke`, carrying `tool_name`, an `ok`
  flag, human-readable `content`, and a structured `data` payload.
- **ToolError**: The existing exception a Tool raises on execution failure; the orchestrator
  contains it as a bounded observation and continues the run.
- **Connector**: The per-integration transport seam (one abstract contract per Integration,
  mirroring `Search_Provider`) that performs the actual outbound calls to the third-party
  service. Each Integration provides a `Disabled_<Integration>_Connector` (keyless default,
  reports itself unavailable, performs no network call) and a credentialed
  `Keyed_<Integration>_Connector` constructed only when a Credential is present. A test injects
  a Mock_Connector to exercise the Integration_Tool with no network and no credential.
- **Credential**: The optional secret enabling an Integration — a token (or token bundle)
  supplied through the Configuration_Manager as a `SecretStr`, absent by default.
- **Enable_Setting**: An optional per-integration non-secret `Settings` toggle (default `true`,
  mirroring the Phase 6 `tracing_export_enabled` master-toggle pattern) that allows an operator
  to hold an Integration Disabled even when its Credential is present.
- **Enabled**: The state of an Integration whose Credential is present AND whose Enable_Setting
  is not `false`, and whose Connector reports itself available; an Enabled Integration_Tool is
  registered in the Tool_Registry and discoverable by agents. Credential presence and the
  Enable_Setting are separate conditions — a present Credential alone does not force enablement
  when the Enable_Setting is `false`.
- **Disabled**: The state of an Integration whose Credential is absent OR whose Enable_Setting is
  `false`; a Disabled Integration_Tool is not registered, is never offered to the agent, and
  performs no network call.
- **Integration_Status**: The org-scoped, RBAC-gated view reporting, for each Integration, its
  name and whether it is Enabled, without exposing any Credential value.
- **Integration_Connection**: An optional persisted, org-scoped record of non-secret
  per-organization integration configuration (e.g. a default Slack channel or GitHub
  repository) enforced at the data-access layer; it MUST NOT store secret Credential material.
- **Configuration_Manager**: The existing `Settings` loader (`config/settings.py`).
- **Composition_Root**: The existing `config/container.py`; the only module that names concrete
  Connectors and registers Integration_Tools.
- **Principal**: The existing Phase 5 authenticated caller carrying `org_id`, identity, and
  `role`.
- **Guardrail_Pipeline**: The existing Phase 6 ordered input/output validation seam.
- **Timeout_Budget**: The bounded maximum duration a single Integration_Tool invocation may run
  before it is aborted with a timeout error.

## Requirements

### Requirement 1: Integration_Tool implements the existing Tool seam

**User Story:** As a platform engineer, I want each integration to be an ordinary Tool behind
the existing interface, so that integrations are added without forking the tool abstraction or
editing the orchestrator.

#### Acceptance Criteria

1. THE Integration_Layer SHALL implement each Integration_Tool as a concrete subclass of the
   existing `Tool_Interface` exposing `name`, `description`, `input_schema`, `available`, and
   `invoke`.
2. THE Integration_Layer SHALL NOT define a Tool base class, a Tool registry, or a
   `Tool_Result` type separate from the existing `tools/base.py` and `tools/registry.py`.
3. THE Integration_Layer SHALL assign each Integration_Tool a unique, stable `name` that is
   distinct from every other registered Tool name.
4. WHEN an Integration_Tool completes an invocation successfully, THE Integration_Tool SHALL
   return a `Tool_Result` whose `ok` field is `true` and whose `content` and `data` carry the
   invocation outcome.
5. THE Agent_Orchestrator and the Multi_Agent_Orchestrator SHALL remain unmodified by the
   addition of the Integration_Layer, discovering every Integration_Tool solely through the
   existing `Tool_Registry`.

### Requirement 2: Registration and discovery through the composition root

**User Story:** As a platform engineer, I want integrations registered only in the composition
root and discovered through the existing registry, so that the single wiring seam stays
authoritative and agents see integrations automatically.

#### Acceptance Criteria

1. THE Composition_Root SHALL be the only module that constructs a concrete Connector and
   registers an Integration_Tool.
2. WHERE an Integration is Enabled, THE Composition_Root SHALL register that Integration_Tool
   in the `Tool_Registry` built by `build_tool_registry`.
3. WHERE an Integration is Disabled, THE Composition_Root SHALL NOT register that
   Integration_Tool.
4. WHEN a duplicate Integration_Tool name is registered, THE Tool_Registry SHALL raise the
   existing `DuplicateToolNameError` and leave the previously registered Tool unchanged.
5. WHEN an agent requests the list of available tool specs, THE Tool_Registry SHALL include
   every Enabled Integration_Tool and exclude every Disabled Integration_Tool.
6. IF the Composition_Root fails to register an Enabled Integration_Tool due to a configuration
   or construction error, THEN THE Composition_Root SHALL abort startup with an `AppError`-shaped
   error naming the offending Integration and SHALL NOT start the platform in a partially
   registered state.

### Requirement 3: Keyless default and credential-driven enablement

**User Story:** As a platform operator, I want all integrations disabled by default and enabled
only by supplying a credential, so that the platform runs and tests with zero credentials.

#### Acceptance Criteria

1. WHERE no integration Credential is configured, THE Integration_Layer SHALL leave every
   Integration disabled.
2. WHILE an Integration is Disabled, THE Integration_Layer SHALL perform no outbound network
   call for that Integration.
3. THE Configuration_Manager SHALL expose each integration Credential as an optional `SecretStr`
   sourced exclusively from environment variables, defaulting to absent.
4. WHEN an Integration's Credential is absent, THE Integration_Layer SHALL treat that Integration
   as Disabled regardless of any other setting.
5. THE Configuration_Manager SHALL expose a per-integration Enable_Setting as an optional
   non-secret setting defaulting to `true`, kept separate from Credential presence.
6. WHERE an Integration's Credential is present AND the Integration's Enable_Setting is not
   `false`, THE Integration_Layer SHALL treat that Integration as Enabled.
7. WHERE an Integration's Credential is present AND the Integration's Enable_Setting is `false`,
   THE Integration_Layer SHALL treat that Integration as Disabled and SHALL perform no outbound
   network call for that Integration.
8. WHEN the platform boots with zero integration Credentials, THE Integration_Layer SHALL allow
   startup to complete successfully.

### Requirement 4: Secret handling and redaction

**User Story:** As a security reviewer, I want integration credentials treated as redacted
secrets that are never persisted or logged, so that credential material cannot leak.

#### Acceptance Criteria

1. THE Integration_Layer SHALL store each integration Credential only as a `SecretStr` obtained
   from the Configuration_Manager.
2. THE Integration_Layer SHALL exclude every Credential value from log output, exception
   messages, `repr` output, and serialized model output.
3. THE Integration_Layer SHALL NOT write any Credential value to the database or to any
   Integration_Connection record.
4. WHERE an Integration_Tool reports Integration_Status or returns a `Tool_Result`, THE
   Integration_Tool SHALL exclude every Credential value from the reported content and data.

### Requirement 5: Connector transport seam and keyless testability

**User Story:** As a developer, I want each integration's network calls behind a mockable
Connector seam, so that the whole suite runs deterministically with no real credential and no
network.

#### Acceptance Criteria

1. THE Integration_Layer SHALL define, for each Integration, an abstract Connector contract that
   exposes an `available` flag and the operations the Integration_Tool invokes.
2. THE Integration_Layer SHALL provide, for each Integration, a disabled Connector that reports
   `available` as `false` and performs no network call, selected as the keyless default.
3. THE Integration_Layer SHALL provide, for each Integration, a credentialed Connector that is
   constructed by the Composition_Root only when the Integration's Credential is present.
4. THE Integration_Layer SHALL allow a test to inject a mock Connector into an Integration_Tool
   so that the Integration_Tool is exercisable with no Credential and no network call.
5. WHEN an Integration_Tool's Connector reports `available` as `false`, THE Integration_Tool
   SHALL report its own `available` as `false`.

### Requirement 6: Bounded, safe tool execution

**User Story:** As a platform operator, I want every integration invocation bounded and free of
unbounded side effects, so that a slow or misbehaving provider cannot hang or overload the
platform.

#### Acceptance Criteria

1. WHEN an Integration_Tool invokes its Connector, THE Integration_Tool SHALL enforce a
   configured Timeout_Budget on the invocation.
2. IF an Integration_Tool invocation exceeds its Timeout_Budget, THEN THE Integration_Tool SHALL
   abort the invocation and return a `Tool_Result` whose `ok` field is `false` carrying the
   `integration_timeout` error code.
3. THE Integration_Layer SHALL bound the volume of data returned by a single Integration_Tool
   invocation to a configured maximum result count.
4. THE Configuration_Manager SHALL expose the Timeout_Budget and the maximum result count as
   optional non-secret settings with bounded, keyless-safe defaults.
5. WHEN an Integration_Tool performs a write action against a third-party service, THE
   Integration_Tool SHALL perform exactly the single declared action described by the validated
   arguments and no additional side effect.

### Requirement 7: Uniform error mapping

**User Story:** As an API consumer, I want every integration failure mapped onto the uniform
error vocabulary, so that failures are handled consistently regardless of provider.

#### Acceptance Criteria

1. IF an Integration_Tool is invoked while Disabled, THEN THE Integration_Tool SHALL return a
   `Tool_Result` whose `ok` field is `false` carrying the `integration_disabled` error code and
   SHALL perform no network call.
2. IF a Connector reports that the third-party service rejected the Credential, THEN THE
   Integration_Tool SHALL surface the `integration_unauthorized` error code.
3. IF a Connector reports that the third-party service applied a rate limit, THEN THE
   Integration_Tool SHALL surface the `integration_rate_limited` error code.
4. IF a Connector reports an upstream error from the third-party service, THEN THE
   Integration_Tool SHALL surface the `integration_upstream_error` error code.
5. WHEN an Integration_Tool surfaces an error to the Integration_Status API or any HTTP surface,
   THE Integration_Layer SHALL render the error using the existing `AppError` envelope
   `{ "error": { code, message, details } }`.
6. THE Integration_Layer SHALL exclude BOTH internal stack traces AND Credential values from
   every error message surfaced to a caller; any surfaced error that exposes either an internal
   stack trace or a Credential value SHALL be treated as a violation of this requirement.

### Requirement 8: Argument validation and contained failure

**User Story:** As a developer, I want malformed tool calls and provider failures contained as
observations, so that an integration error never crashes an agent run.

#### Acceptance Criteria

1. WHEN the agent `act` node receives a Tool_Call for an Integration_Tool, THE agent SHALL
   validate the arguments against the Integration_Tool's `input_schema` before invocation.
2. IF the arguments violate the `input_schema`, THEN THE agent SHALL record a `validation_error`
   observation and SHALL NOT invoke the Integration_Tool.
3. IF an Integration_Tool raises `ToolError` during invocation, THEN THE agent SHALL record a
   `tool_execution_error` observation and continue the run.
4. WHEN an Integration_Tool invocation fails for any mapped reason, THE agent run SHALL continue
   to a bounded termination rather than terminating abnormally.

### Requirement 9: Integration_Status introspection

**User Story:** As an operator, I want to see which integrations are enabled for my
organization, so that I can understand available capabilities without exposing secrets.

#### Acceptance Criteria

1. WHEN an authenticated Principal requests Integration_Status, THE Integration_Layer SHALL
   return, for each Integration, the Integration name and whether the Integration is Enabled.
2. THE Integration_Layer SHALL exclude every Credential value from the Integration_Status
   response.
3. WHERE the requesting Principal lacks the `read` permission, THE Integration_Layer SHALL deny
   the Integration_Status request with an `AppError` carrying the `forbidden` code and HTTP
   status 403.
4. IF an Integration_Status request presents no valid Principal, THEN THE Integration_Layer
   SHALL deny the request with an `AppError` carrying the `unauthorized` code and HTTP status
   401.
5. THE Integration_Status response SHALL reflect the enablement state derived from the
   configured Credentials and Enable_Settings at request time.

### Requirement 10: RBAC and guardrail gating of tool use

**User Story:** As a security owner, I want integration tool use governed by the existing RBAC
and guardrail seams, so that unauthorized or unsafe invocations never reach a provider.

#### Acceptance Criteria

1. WHERE a Principal lacks the `run_agents` permission, THE Integration_Layer SHALL prevent that
   Principal from initiating an agent run that could invoke an Integration_Tool.
2. WHEN the Integration_Layer blocks a Principal that lacks the required permission from driving
   an Integration_Tool invocation, THE Integration_Layer SHALL record a security audit event
   identifying the acting Principal, the target Integration, and the denied action.
3. WHEN an agent run applies the input Guardrail_Pipeline and the pipeline blocks the input, THE
   Integration_Layer SHALL ensure no Integration_Tool is invoked for that input.
4. THE Integration_Layer SHALL apply the existing per-Principal rate limiting to requests that
   drive Integration_Tool invocations.
5. THE Integration_Layer SHALL NOT invoke any Disabled Integration_Tool.
6. WHERE an Integration_Tool declares a write action, THE Integration_Layer SHALL gate that
   action behind the same permission model that governs agent runs.

### Requirement 11: Organization-scoped Integration_Connection persistence

**User Story:** As a multi-tenant operator, I want any stored per-org integration configuration
isolated per organization, so that one organization's settings are never visible to another.

#### Acceptance Criteria

1. WHERE an Integration_Connection record is persisted, THE Integration_Layer SHALL store the
   record with a required `org_id` and enforce tenant isolation at the data-access layer.
2. WHEN a Principal reads or mutates an Integration_Connection belonging to another
   organization, THE Integration_Layer SHALL resolve the request to an `AppError` carrying the
   `not_found` code and HTTP status 404.
3. WHERE the platform adds database schema for Integration_Connection records, THE
   Integration_Layer SHALL apply only additive migrations using `CREATE ... IF NOT EXISTS` and
   SHALL NOT alter or drop any pre-existing column.
4. THE Integration_Layer SHALL exclude Credential material from every Integration_Connection
   record.
5. WHERE no Integration_Connection persistence is configured, THE Integration_Layer SHALL derive
   enablement solely from the configured Credentials and remain fully functional.

### Requirement 12: Slack Integration_Tool

**User Story:** As an agent user, I want an agent to read a Slack channel and post a message, so
that the agent can retrieve and share workspace context.

#### Acceptance Criteria

1. THE Slack Integration_Tool SHALL declare an `input_schema` accepting an `action` selecting
   `read_channel` or `post_message`, a `channel` identifier, an optional message `text` required
   for `post_message`, and an optional `limit` for `read_channel`.
2. WHERE the Slack Credential (a Slack bot token) is present, THE Composition_Root SHALL register
   the Slack Integration_Tool as Enabled.
3. WHERE the Slack Credential is absent, THE Slack Integration_Tool SHALL be Disabled and SHALL
   NOT be registered.
4. WHEN the Slack Integration_Tool performs `read_channel` while Enabled, THE Slack
   Integration_Tool SHALL return up to the requested `limit` of recent messages in a
   `Tool_Result`.
5. WHEN the Slack Integration_Tool performs `post_message` while Enabled, THE Slack
   Integration_Tool SHALL post exactly one message with the provided `text` to the specified
   `channel`.
6. IF the Slack provider rejects the Credential or applies a rate limit, THEN THE Slack
   Integration_Tool SHALL surface the `integration_unauthorized` or `integration_rate_limited`
   error code respectively.

### Requirement 13: Gmail Integration_Tool

**User Story:** As an agent user, I want an agent to search, read, and send Gmail messages, so
that the agent can act on email context.

#### Acceptance Criteria

1. THE Gmail Integration_Tool SHALL declare an `input_schema` accepting an `action` selecting
   `search_messages`, `read_message`, or `send_message`; a `query` required for
   `search_messages`; a `message_id` required for `read_message`; and `to`, `subject`, and
   `body` required for `send_message`.
2. WHERE the Gmail Credential is present, THE Composition_Root SHALL register the Gmail
   Integration_Tool as Enabled, and WHERE the Gmail Credential is absent THE Gmail
   Integration_Tool SHALL be Disabled and unregistered.
3. WHEN the Gmail Integration_Tool performs `search_messages` while Enabled, THE Gmail
   Integration_Tool SHALL return up to the configured maximum result count of matching message
   references in a `Tool_Result`.
4. WHEN the Gmail Integration_Tool performs `read_message` while Enabled, THE Gmail
   Integration_Tool SHALL return the message identified by `message_id`.
5. WHEN the Gmail Integration_Tool performs `send_message` while Enabled, THE Gmail
   Integration_Tool SHALL send exactly one message to the specified `to` recipient.
6. WHERE the `send_message` action is invoked, THE Integration_Layer SHALL gate the action
   behind the same permission model that governs agent runs.

### Requirement 14: Google Drive Integration_Tool

**User Story:** As an agent user, I want an agent to list, search, and read Google Drive files,
so that the agent can retrieve document context.

#### Acceptance Criteria

1. THE Google Drive Integration_Tool SHALL declare an `input_schema` accepting an `action`
   selecting `list_files`, `search_files`, or `read_file`; an optional `query` required for
   `search_files`; and a `file_id` required for `read_file`.
2. WHERE the Google Drive Credential is present, THE Composition_Root SHALL register the Google
   Drive Integration_Tool as Enabled, and WHERE the Credential is absent THE Google Drive
   Integration_Tool SHALL be Disabled and unregistered.
3. WHEN the Google Drive Integration_Tool performs `list_files` or `search_files` while Enabled,
   THE Google Drive Integration_Tool SHALL return up to the configured maximum result count of
   file references in a `Tool_Result`.
4. WHEN the Google Drive Integration_Tool performs `read_file` while Enabled, THE Google Drive
   Integration_Tool SHALL return the content or metadata of the file identified by `file_id`.
5. THE Google Drive Integration_Tool SHALL perform only read operations and SHALL NOT modify or
   delete any file.

### Requirement 15: GitHub Integration_Tool

**User Story:** As an agent user, I want an agent to search code and issues, read a repository,
and create an issue, so that the agent can act on repository context.

#### Acceptance Criteria

1. THE GitHub Integration_Tool SHALL declare an `input_schema` accepting an `action` selecting
   `search_code`, `search_issues`, `read_repo`, or `create_issue`; a `query` required for the
   search actions; `owner` and `repo` required for `read_repo` and `create_issue`; and `title`
   with an optional `body` required for `create_issue`.
2. WHERE the GitHub Credential (a GitHub token) is present, THE Composition_Root SHALL register
   the GitHub Integration_Tool as Enabled, and WHERE the Credential is absent THE GitHub
   Integration_Tool SHALL be Disabled and unregistered.
3. WHEN the GitHub Integration_Tool performs `search_code` or `search_issues` while Enabled, THE
   GitHub Integration_Tool SHALL return up to the configured maximum result count of matching
   results in a `Tool_Result`.
4. WHEN the GitHub Integration_Tool performs `read_repo` while Enabled, THE GitHub
   Integration_Tool SHALL return the metadata of the repository identified by `owner` and
   `repo`.
5. WHEN the GitHub Integration_Tool performs `create_issue` while Enabled, THE GitHub
   Integration_Tool SHALL create exactly one issue in the specified repository with the provided
   `title`.
6. WHERE the `create_issue` action is invoked, THE Integration_Layer SHALL gate the action
   behind the same permission model that governs agent runs.

### Requirement 16: Observability without changing run outcomes

**User Story:** As an operator, I want integration invocations observable through the existing
tracing seams, so that I can troubleshoot without integrations altering run results.

#### Acceptance Criteria

1. WHEN an Integration_Tool is invoked within an agent run, THE Integration_Layer SHALL record
   the tool-call step in the existing `Trace` scoped to the acting `org_id`.
2. THE Integration_Layer SHALL exclude every Credential value from all recorded trace and
   exported observability data.
3. IF the observability recording or export fails, THEN THE Integration_Layer SHALL leave the
   Integration_Tool invocation outcome unchanged.
4. THE Integration_Layer SHALL rely on the existing tracing and observability seams and SHALL
   NOT introduce a separate observability mechanism.

### Requirement 17: Backward compatibility

**User Story:** As a maintainer, I want the platform to behave exactly as before when no
integration is configured, so that Phase 8 introduces no regressions.

#### Acceptance Criteria

1. WHERE no integration Credential is configured, THE Tool_Registry SHALL expose exactly the set
   of tools it exposed before Phase 8 (the `RAG_Tool`, and the `Web_Search_Tool` when its own
   Credential is present).
2. WHERE no integration Credential is configured, THE Agent_Orchestrator and the
   Multi_Agent_Orchestrator SHALL produce the same run behavior they produced before Phase 8 for
   identical inputs.
3. THE Integration_Layer SHALL NOT alter the `input_schema`, `name`, or behavior of the existing
   `RAG_Tool` or `Web_Search_Tool`.
4. THE Integration_Layer SHALL NOT change the existing `Tool_Interface`, `Tool_Registry`,
   `Tool_Result`, or `AppError` contracts.
5. WHEN the platform runs its test suite with zero integration Credentials, THE Integration_Layer
   SHALL allow the suite to pass without any real credential or network access.
