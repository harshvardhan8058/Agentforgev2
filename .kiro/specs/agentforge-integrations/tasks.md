# Implementation Plan: AgentForge Third-Party Integrations (Phase 8)

## Overview

This plan converts the Phase 8 design into an ordered, incremental, test-driven coding
sequence. Every task builds on the previous one — the `integrations/` package with the
error-code vocabulary, connector failure classes, the `Integration_Connector` ABC and the
cross-cutting `Integration_Tool` base first; then the optional `Settings`
credentials / enable-toggles / bounded execution limits + the `integration_enabled()`
helper; then the four per-integration modules (Slack, Gmail, Google Drive, GitHub), each a
Connector ABC + `Disabled_`/`Keyed_`/`Mock_` trio and its `Integration_Tool` subclass; then
the composition-root wiring that registers only Enabled integrations through the existing
`build_tool_registry`; then a checkpoint; then the org-scoped `Integration_Status` service +
router; then the optional additive `Integration_Connection` persistence + migration `0011`;
then the RBAC / guardrail / rate-limit / tracing wiring and verification over the reused
seams; then the docs; and finally the full keyless-suite checkpoint — with everything wired
together so no code is orphaned.

The whole layer **reuses, never reimplements** the existing Phase 1–7 seams. It consumes
each exactly as-is and forks none:

- The **Tool seam** — the abstract `Tool_Interface` (`tools/base.py`) with
  `name` / `description` / `input_schema` / `available` / `invoke`, the `Tool_Result` /
  `Tool_Call` / `ToolError` value types, and the `Tool_Registry` (`tools/registry.py`) that
  registers by unique name (rejecting duplicates with `DuplicateToolNameError`), resolves by
  name, and lists specs of only the **available** tools. The `RAG_Tool` and the
  `Web_Search_Tool` (backed by the keyless `Disabled_Search_Provider` / credentialed
  `Keyed_Search_Provider`) are the reference patterns each integration mirrors.
- The **agent seams** — the Phase 3 `Agent_Orchestrator` `act` node (which validates
  arguments against `input_schema` and contains a raised `ToolError` as a bounded
  observation) and the Phase 4 `Multi_Agent_Orchestrator`; both remain **unmodified** and
  discover every integration solely through the `Tool_Registry`.
- `Settings` + `load_settings` (`config/settings.py`) — every credential an optional
  `SecretStr` redacted from `repr` / `str` / `model_dump` / logs, sourced only from the
  environment, absent by default.
- The **composition root** (`config/container.py`) — the ONLY module that names concrete
  Connectors and registers Integration_Tools, extending the existing `build_tool_registry`.
- The uniform `AppError` envelope (`api/errors.py`) `{ "error": { code, message, details } }`.
- The Phase 5 enterprise layer — `Principal`, `get_current_principal` /
  `require_permission` / `get_org_id` (`api/deps.py`), the static `RBAC_Policy`, the
  request-scoped tenancy context (`enterprise/tenancy.py`), per-principal rate limiting, the
  404-never-403 data-access rule, and the additive versioned migration runner.
- The Phase 6 observability layer — the `Trace_Recorder` written by the `act` node and the
  ordered `Guardrail_Pipeline` (`apply_input_guardrail`) whose failures never change a run
  outcome.

New code lives under `src/agentforge/integrations/` (a sibling of `tools/`), one new router
under `src/agentforge/api/routers/integrations.py`, and one additive SQL migration
(`0011`). No file under `tools/`, `agent/`, `multiagent/`, or `enterprise/` is modified; the
`Tool_Interface`, `Tool_Registry`, `Tool_Result`, and `AppError` contracts and the existing
tools' behavior are untouched.

**Keyless-first, deterministic testing.** All 10 correctness properties from the design are
implemented as **Hypothesis** property tests (minimum 100 examples each, one test per
property, each tagged `Feature: agentforge-integrations, Property {n}: {text}`), placed next
to the code they validate. Unit tests cover schema shapes, retrieval-by-id actions, and the
reused enterprise / guardrail / tracing integration points; integration tests marked
`@pytest.mark.integration` cover the real Postgres migration/round-trip. The default lane
runs KEYLESS and DETERMINISTIC with **zero** integration credentials and **no** network:
every integration is Disabled by default, and the property/unit suite injects
`Mock_<Integration>_Connector`s throughout so no real credential and no network is ever
required.

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Top-level tasks are never optional.
- Each task references the specific requirements and design components it implements.

## Tasks

- [x] 1. Scaffold the `integrations/` package and implement `integrations/base.py`
  - Create the `src/agentforge/integrations/` package with `__init__.py` and stubbed modules
    matching the design's Module/Directory Layout: `base.py`, `slack.py`, `gmail.py`,
    `google_drive.py`, `github.py`, `status.py`, `connection.py`; declare the
    `INTEGRATION_NAMES = ("slack", "gmail", "google_drive", "github")` constant used across
    the subsystem.
  - _Requirements: 1.2, 5.1_
  - _Design: Module / directory layout_

  - [x] 1.1 Implement the error-code vocabulary, connector failure classes, and `Integration_Connector` ABC
    - Define `IntegrationErrorCode(str, Enum)` with the closed set `integration_disabled`,
      `integration_unauthorized`, `integration_rate_limited`, `integration_upstream_error`,
      `integration_timeout`; define `ConnectorError(RuntimeError)` and its subclasses
      `Unauthorized_Error`, `Rate_Limited_Error`, `Upstream_Error`, constructing every
      message to carry no credential value and no internal stack trace; define the shared
      `Integration_Connector(ABC)` marker exposing the abstract `available: bool` property
      that each Tool mirrors.
    - _Requirements: 5.1, 7.2, 7.3, 7.4, 7.6_
    - _Design: Integration error-code vocabulary and connector failure classes; `Integration_Connector` ABC_

  - [x] 1.2 Implement the `Integration_Tool` base (`Tool_Interface` subclass)
    - Implement `Integration_Tool(Tool_Interface)` taking `(connector, *, timeout_seconds,
      max_results)`: `available` mirrors `connector.available` (Req 5.5); `invoke` performs
      the Disabled short-circuit returning `Tool_Result(ok=False)` with `integration_disabled`
      and **no** connector call (Req 7.1, 3.2); wraps the dispatched connector call in a
      bounded timeout executor mapping expiry to `integration_timeout` (Req 6.1, 6.2); maps
      each connector failure class onto the fixed vocabulary (Req 7.2–7.4); caps any returned
      collection to `max_results` (Req 6.3); builds `content` / `data` from outcome fields
      only so no credential is ever placed in a `Tool_Result` (Req 4.2, 4.4); dispatches a
      write action to exactly one connector write call and no other side effect (Req 6.5);
      and returns `Tool_Result(ok=True, ...)` on success (Req 1.4). Subclasses supply
      `name` / `description` / `input_schema` and `_dispatch(arguments, connector)`.
    - _Requirements: 1.1, 1.4, 3.2, 4.2, 4.4, 5.5, 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.3, 7.4_
    - _Design: `Integration_Tool` base class (`integrations/base.py`)_

  - [x]* 1.3 Write property test for the Disabled short-circuit
    - **Property 3: A Disabled tool invoked directly returns `integration_disabled` with no connector call**
    - **Validates: Requirements 7.1, 3.2, 5.5, 10.5**
    - Hypothesis over arbitrary argument dictionaries against a spying unavailable
      `Mock_Connector`: assert `invoke` returns `Tool_Result(ok=False)` carrying
      `integration_disabled` and that the connector's operations were called zero times.

  - [x]* 1.4 Write property test for total connector-failure mapping
    - **Property 4: Connector failure mapping is total over the failure vocabulary**
    - **Validates: Requirements 7.2, 7.3, 7.4, 12.6**
    - Hypothesis over each connector failure class (`Unauthorized_Error` /
      `Rate_Limited_Error` / `Upstream_Error` / other `ConnectorError`) injected into an
      available `Mock_Connector`: assert `invoke` returns `ok=False` with exactly the
      corresponding fixed error code and never raises.

  - [x]* 1.5 Write property test for the Timeout_Budget guarantee
    - **Property 5: Exceeding the Timeout_Budget always yields `integration_timeout`**
    - **Validates: Requirements 6.1, 6.2**
    - Hypothesis over injected latencies exceeding a small configured `timeout_seconds`
      against a `Mock_Connector`: assert `invoke` aborts and returns `ok=False` carrying
      `integration_timeout`.

  - [x]* 1.6 Write property test for the result cap
    - **Property 6: A single invocation never returns more than the configured result cap**
    - **Validates: Requirements 6.3, 12.4, 13.3, 14.3, 15.3**
    - Hypothesis over a configured cap `C` and a `Mock_Connector` returning `N` items:
      assert the read/search/list `Tool_Result` contains exactly `min(N, C)` items.

  - [x]* 1.7 Write unit tests for the base helpers
    - Cover the success-result shape (`ok=True`, populated `content`/`data`), the
      error-result shape (`ok=False`, `data["error_code"]`), and that `available` tracks the
      connector's flag both true and false.
    - _Requirements: 1.4, 5.5_

- [x] 2. Extend `Settings` with the Phase 8 integration configuration and update `.env.example`
  - [x] 2.1 Add optional credentials, enable-toggles, bounded limits, and the `integration_enabled()` helper
    - Extend `config/settings.py` `Settings` (all optional / defaulted so keyless boot is
      preserved): `slack_bot_token` / `gmail_token` / `google_drive_token` / `github_token`
      as `SecretStr | None = None`; `slack_enabled` / `gmail_enabled` / `google_drive_enabled`
      / `github_enabled` as `bool = True` (mirroring `tracing_export_enabled`);
      `integration_timeout_seconds: int = 10` and `integration_max_results: int = 20`
      resolved within bounded, keyless-safe ranges. Add
      `integration_enabled(name) -> bool` returning `credential present AND enable-toggle is
      not False` (mirroring `active_search()`), used by both the composition root and the
      status service.
    - _Requirements: 3.3, 3.5, 3.6, 3.7, 4.1, 6.4_
    - _Design: Settings additions (`config/settings.py`); How enablement is derived_

  - [x] 2.2 Update `.env.example`
    - Add every new variable (the four credentials, the four enable-toggles, the timeout and
      the result cap) with commented-out / keyless-safe defaults so the platform continues to
      boot with zero integration credentials.
    - _Requirements: 3.1, 3.8, 17.5_
    - _Design: Settings additions (`.env.example`)_

  - [x]* 2.3 Write property test for enablement equivalence
    - **Property 1: Enablement equivalence (total over the configuration space)**
    - **Validates: Requirements 3.1, 3.4, 3.6, 3.7, 5.3, 11.5, 12.2, 13.2, 14.2, 15.2**
    - Hypothesis over each integration × (Credential present/absent) × (enable-toggle
      `true`/`false`/unset): assert `integration_enabled(name)` is `True` **iff** the
      Credential is present AND the toggle is not `False`, and `False` otherwise —
      independent of any persistence.

  - [x]* 2.4 Write unit test for credential redaction and keyless defaults
    - Assert each credential field is `SecretStr | None`, is absent by default, and is
      redacted from `repr` / `str` / `model_dump`; assert the timeout and result-cap defaults
      and that `Settings()` with no env vars leaves every integration Disabled.
    - _Requirements: 3.8, 4.2, 6.4_

- [x] 3. Implement the four Integration modules (`slack.py`, `gmail.py`, `google_drive.py`, `github.py`)
  - [x] 3.1 Implement `slack.py`
    - Define `Slack_Connector(Integration_Connector)` with `read_channel(channel, limit)` and
      `post_message(channel, text)`; provide `Disabled_Slack_Connector` (`available=False`,
      operations raise defensively, no network), `Keyed_Slack_Connector(token)` (built only
      with a non-empty token; transport-level timeout; deterministic stand-in), and
      `Mock_Slack_Connector` (available, no network, canned data / injected failures, spies on
      calls). Implement `Slack_Tool` (`name="slack"`) with the `input_schema` (`action` ∈
      {`read_channel`, `post_message`}, `channel`, optional `text` required for
      `post_message`, optional `limit`) and `_dispatch` routing `read_channel` → up to `limit`
      recent messages and `post_message` → exactly one message to `channel`.
    - _Requirements: 1.1, 1.3, 5.1, 5.2, 5.3, 5.4, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_
    - _Design: The four Integration_Tools (Slack_Tool); Connector transport seam_

  - [x] 3.2 Implement `gmail.py`
    - Define `Gmail_Connector` with `search_messages(query)`, `read_message(message_id)`,
      `send_message(to, subject, body)`; provide the `Disabled_`/`Keyed_`/`Mock_` trio.
      Implement `Gmail_Tool` (`name="gmail"`) with the `input_schema` (`action` ∈
      {`search_messages`, `read_message`, `send_message`}; `query` required for search;
      `message_id` required for read; `to` / `subject` / `body` required for send) and
      `_dispatch` routing search → up to the max result count of references, read → the
      identified message, send → exactly one message to `to` (single write).
    - _Requirements: 1.1, 1.3, 5.1, 5.2, 5.3, 5.4, 13.1, 13.2, 13.3, 13.4, 13.5_
    - _Design: The four Integration_Tools (Gmail_Tool)_

  - [x] 3.3 Implement `google_drive.py`
    - Define `Google_Drive_Connector` with **read-only** operations `list_files()`,
      `search_files(query)`, `read_file(file_id)` (no mutate/delete on the contract);
      provide the `Disabled_`/`Keyed_`/`Mock_` trio. Implement `Google_Drive_Tool`
      (`name="google_drive"`) with the `input_schema` (`action` ∈ {`list_files`,
      `search_files`, `read_file`}; `query` required for search; `file_id` required for read)
      and `_dispatch` routing list/search → up to the max result count of file references and
      read → content/metadata of `file_id`.
    - _Requirements: 1.1, 1.3, 5.1, 5.2, 5.3, 5.4, 14.1, 14.2, 14.3, 14.4, 14.5_
    - _Design: The four Integration_Tools (Google_Drive_Tool)_

  - [x] 3.4 Implement `github.py`
    - Define `GitHub_Connector` with `search_code(query)`, `search_issues(query)`,
      `read_repo(owner, repo)`, `create_issue(owner, repo, title, body)`; provide the
      `Disabled_`/`Keyed_`/`Mock_` trio. Implement `GitHub_Tool` (`name="github"`) with the
      `input_schema` (`action` ∈ {`search_code`, `search_issues`, `read_repo`,
      `create_issue`}; `query` required for search; `owner` / `repo` required for read/create;
      `title` required and `body` optional for `create_issue`) and `_dispatch` routing search
      → up to the max result count, read → repo metadata, create → exactly one issue (single
      write).
    - _Requirements: 1.1, 1.3, 5.1, 5.2, 5.3, 5.4, 15.1, 15.2, 15.3, 15.4, 15.5_
    - _Design: The four Integration_Tools (GitHub_Tool)_

  - [x]* 3.5 Write property test for single-write dispatch and Drive read-only
    - **Property 7: A write action performs exactly one connector write and no other side effect**
    - **Validates: Requirements 6.5, 12.5, 13.5, 15.5, 14.5**
    - Hypothesis over each write action (`slack.post_message`, `gmail.send_message`,
      `github.create_issue`) with validated arguments against spying `Mock_Connector`s:
      assert exactly one call to the corresponding write op with those arguments and no other
      connector call; and for any Google Drive action assert zero write/mutate/delete calls.

  - [x]* 3.6 Write unit tests for per-action schema shape and retrieval-by-id actions
    - Cover each tool's per-action required fields (Req 12.1, 13.1, 14.1, 15.1) with
      `additionalProperties: false`, and the retrieval-by-id actions
      `gmail.read_message` / `google_drive.read_file` / `github.read_repo` returning the
      identified resource, plus each tool's unique stable `name`.
    - _Requirements: 1.3, 12.1, 13.1, 13.4, 14.1, 14.4, 15.1, 15.4_

- [x] 4. Wire integrations through the composition root (`config/container.py`) and extend `build_tool_registry`
  - [x] 4.1 Add the per-integration connector builders
    - Add `build_slack_connector` / `build_gmail_connector` / `build_google_drive_connector`
      / `build_github_connector`, each returning the `Disabled_<X>_Connector` unless
      `settings.integration_enabled(name)`, in which case it constructs the
      `Keyed_<X>_Connector` from the `SecretStr` credential's plaintext (obtained here only).
      Concrete Connectors are named ONLY in this module.
    - _Requirements: 2.1, 3.2, 5.2, 5.3_
    - _Design: Composition-root additions (`config/container.py`)_

  - [x] 4.2 Implement `build_integration_tools` and extend `build_tool_registry`
    - Implement `build_integration_tools(settings, *, connectors=None)` iterating the
      `_INTEGRATION_BUILDERS`: build (or accept an injected) connector, and yield the
      `Integration_Tool` subclass (with `timeout_seconds` / `max_results` from settings) only
      when `connector.available` (Enabled ⇒ register; Disabled ⇒ skip, never offered, no
      network). On any construction failure, raise an `AppError`-shaped error naming the
      offending integration and abort startup (never a partially registered state). Extend
      `build_tool_registry` to register each returned tool after `RAG_Tool` /
      `Web_Search_Tool`, surfacing the existing `DuplicateToolNameError` unchanged.
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 3.2_
    - _Design: Composition-root registration policy; Composition-root additions_

  - [x] 4.3 Add the deps accessors
    - Add `build_integration_status_service(settings)` and
      `build_integration_connection_store(settings)` and surface them through `api/deps.py`
      `get_*` accessors mirroring the existing dependency wiring (used by tasks 6 and 7).
    - _Requirements: 2.1, 9.1, 11.5_
    - _Design: Composition-root additions_

  - [x]* 4.4 Write property test for Disabled-never-registered and the availability mirror
    - **Property 2: Disabled integrations are never registered, never listed, and hold no network path**
    - **Validates: Requirements 2.2, 2.3, 2.5, 3.2, 5.2, 5.5, 10.5, 12.3, 13.2, 14.2, 15.2**
    - Hypothesis over arbitrary integration configurations: assert the built `Tool_Registry`
      (and `list_specs()`) equals the baseline tools unioned with exactly the Enabled
      integrations; every Disabled integration is absent, its selected connector reports
      `available == False`, and each tool's `available` equals its connector's.

  - [x]* 4.5 Write property test for backward compatibility with zero credentials
    - **Property 10: Backward compatibility with zero integration credentials**
    - **Validates: Requirements 17.1, 17.2, 3.8, 3.1**
    - Hypothesis over Settings with no integration credential: assert the registry's
      tool-name set equals the pre-Phase-8 baseline (`rag_search`, plus `web_search` iff its
      own search credential is present), and a deterministic keyless agent / multi-agent run
      over identical inputs produces the same result as before Phase 8.

  - [x]* 4.6 Write unit tests for duplicate-name rejection and startup-abort naming the integration
    - Cover a `DuplicateToolNameError` surfacing unchanged on a duplicate registration, and a
      failing Enabled connector construction aborting startup with an `AppError` whose
      `details` name the offending integration.
    - _Requirements: 2.4, 2.6_

- [x] 5. Checkpoint — integration tools discoverable on the keyless path
  - Ensure the base + settings + integration-module + wiring property/unit suite
    (Properties 1–7, 10 plus their unit tests) is green on the keyless path with mock/disabled
    connectors, and that an Enabled integration (via an injected mock connector) is
    discoverable through the **unmodified** orchestrator via the `Tool_Registry`. Ensure all
    tests pass, ask the user if questions arise.

- [x] 6. Implement the `Integration_Status` service and the introspection router
  - [x] 6.1 Implement `Integration_Status_Service` (`integrations/status.py`)
    - Implement the frozen `Integration_Status_Entry(name, enabled)` and
      `Integration_Status_Service(settings)` whose `status()` returns, for each name in
      `INTEGRATION_NAMES`, an entry with `enabled = settings.integration_enabled(name)`
      derived at request time, exposing no credential value.
    - _Requirements: 9.1, 9.2, 9.5_
    - _Design: Integration_Status introspection API (`integrations/status.py`)_

  - [x] 6.2 Implement `api/routers/integrations.py` and its response schema, and mount it
    - Add `GET /integrations/status` declaring only
      `Depends(require_permission(Permission.READ))` (no bespoke authorization), returning an
      `IntegrationStatusResponse` of `{name, enabled}` pairs; no valid Principal → 401 via
      `get_current_principal`, missing `read` → 403 via `require_permission`, rendered through
      the existing `AppError` envelope. Add the response schema to `api/schemas.py` and mount
      the router in `main.py` alongside the existing routers.
    - _Requirements: 7.5, 9.1, 9.2, 9.3, 9.4, 9.5_
    - _Design: Integration_Status introspection API (router); Error Handling (HTTP surfaces)_

  - [x]* 6.3 Write unit tests for the status endpoint auth surface and response shape
    - Cover no-credential → 401, authenticated-without-`read` → 403, a `read` principal
      receiving one `{name, enabled}` entry per integration reflecting current config, and
      that no credential/secret-derived field appears anywhere in the response.
    - _Requirements: 9.2, 9.3, 9.4, 9.5_

- [x] 7. Implement optional org-scoped `Integration_Connection` persistence and migration `0011`
  - [x] 7.1 Implement the model, store ABC, and `InMemory_Integration_Connection_Store` (`integrations/connection.py`)
    - Define the `Integration_Connection` dataclass (`id`, required `org_id`, `integration`,
      non-secret `config` dict, `created_at`) and `Integration_Connection_Store(ABC)` with
      `create(org_id, integration, config)`, `get(org_id, connection_id)`,
      `list_for_org(org_id)` — every method takes `org_id` as a required parameter and the
      store never accepts or persists a `SecretStr` / credential field. Implement the keyless
      default `InMemory_Integration_Connection_Store` keyed by `(org_id, id)` so a cross-org
      `get` returns `None` and `list_for_org` returns `[]`.
    - _Requirements: 4.3, 11.1, 11.2, 11.4, 11.5_
    - _Design: Optional org-scoped Integration_Connection persistence_

  - [x] 7.2 Implement `Pg_Integration_Connection_Store`
    - Use sync SQLAlchemy mirroring the Phase 5/6 `Pg_*` stores; `create` / `get` /
      `list_for_org` all constrain SQL by `WHERE org_id = :org_id`, so a cross-tenant
      read/mutate matches zero rows → `None`/`[]` → the caller raises `AppError("not_found",
      404)`. The store has no column for and never persists credential material.
    - _Requirements: 4.3, 11.1, 11.2, 11.4_
    - _Design: Optional org-scoped Integration_Connection persistence; Integration_Connection row_

  - [x] 7.3 Add migration `migrations/0011_create_integration_connections.sql`
    - Create `integration_connections` with `id UUID PRIMARY KEY`, `org_id UUID NOT NULL
      REFERENCES organizations(id) ON DELETE CASCADE`, `integration TEXT NOT NULL`, `config
      JSONB NOT NULL DEFAULT '{}'::jsonb` (NON-SECRET only — no token/secret column),
      `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`; add
      `integration_connections_org_idx (org_id, integration)`. Strictly additive / idempotent
      via `CREATE ... IF NOT EXISTS`, altering or dropping no pre-existing column.
    - _Requirements: 4.3, 11.1, 11.3, 11.4_
    - _Design: Integration_Connection row + additive migration_

  - [x]* 7.4 Write property test for cross-tenant connection isolation
    - **Property 9: Cross-tenant Integration_Connection access resolves to not_found (404)**
    - **Validates: Requirements 11.1, 11.2**
    - Hypothesis over two distinct orgs and a connection owned by the first against the
      in-memory store: assert a read/mutate with the second org's `org_id` returns no row and
      resolves to `AppError("not_found", 404)` — never the other org's data and never 403.

  - [x]* 7.5 Write an integration test applying migration `0011` (`@pytest.mark.integration`)
    - Apply `0011` through the existing runner; assert it reaches `schema_migrations`, the
      table has no secret column, `Pg_Integration_Connection_Store` round-trips under `org_id`
      scoping with cross-org isolation, and `ON DELETE CASCADE` sweeps an org's rows.
    - _Requirements: 11.1, 11.3, 11.4_

- [x] 8. Wire and verify RBAC, guardrail, rate-limit, and tracing over the reused seams
  - [x] 8.1 Verify permission gating and the write-action gate, and record the denial audit event
    - Confirm a Principal lacking `run_agents` cannot initiate an agent run that could invoke
      an Integration_Tool, and that a declared write action (`slack.post_message`,
      `gmail.send_message`, `github.create_issue`) is gated behind the same agent-run
      permission model; when the layer blocks an under-permissioned Principal, record a
      security audit event identifying the acting Principal, the target Integration, and the
      denied action — reusing the existing enterprise seams with no bespoke authorization
      logic and no Disabled tool ever invoked.
    - _Requirements: 8.1, 8.2, 10.1, 10.2, 10.5, 10.6, 13.6, 15.6_
    - _Design: reuse of enterprise seams; Error Handling_

  - [x] 8.2 Verify guardrail short-circuit and per-principal rate limiting on integration-driving requests
    - Confirm that when `apply_input_guardrail` blocks an input, no Integration_Tool is
      invoked, and that the existing per-Principal rate limiting applies to requests that
      drive Integration_Tool invocations — reusing the Phase 6 guardrail pipeline and the
      Phase 5 limiter unchanged.
    - _Requirements: 10.3, 10.4_
    - _Design: reuse of guardrail + rate-limit seams_

  - [x] 8.3 Verify tracing of the tool-call step and export-failure suppression
    - Confirm the existing `Trace_Recorder` records the Integration_Tool call step scoped to
      the acting `org_id`, that no credential value enters recorded/exported observability
      data, and that a failing observability recording/export leaves the invocation outcome
      unchanged — relying only on the existing tracing seams (no separate mechanism).
    - _Requirements: 16.1, 16.2, 16.3, 16.4_
    - _Design: reuse of observability seams; Error Handling (no secrets, no stack traces)_

  - [x]* 8.4 Write property test for credential non-disclosure across every surface
    - **Property 8: Credential values are never surfaced anywhere**
    - **Validates: Requirements 4.2, 4.3, 4.4, 7.6, 9.2, 11.4, 16.2**
    - Hypothesis over generated credential values: assert the value never appears in a
      `Tool_Result` (`content`/`data`), the Integration_Status response, any surfaced error
      message (which also contains no internal stack trace), recorded/exported trace data, or
      any persisted `Integration_Connection` record.

  - [x]* 8.5 Write unit tests for the reused enterprise / guardrail / tracing integration points
    - Cover `run_agents` gating with the audit event on denial, the write-action permission
      gate, the guardrail-block short-circuit (Integration_Tool not invoked), rate-limit
      application, the argument-validation (`validation_error`) and contained-`ToolError`
      (`tool_execution_error`) observations on the `act` node, a trace entry recorded per
      invocation, and export-failure suppression.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3, 10.4, 10.6, 16.1, 16.3_

- [x] 9. Checkpoint — governance, status, and persistence surfaces
  - Ensure the status, connection, and governance property/unit suite (Properties 8, 9 plus
    their unit tests) is green on the keyless path, the status router renders the `AppError`
    envelope, and migration `0011` parses. Ensure all tests pass, ask the user if questions
    arise.

- [ ] 10. Document the phase (`docs/decisions.md`, top-level `README`, `.env.example`)
  - Append a "Phase 8 — Third-Party Integrations" ADR section to `docs/decisions.md` covering:
    each integration as an ordinary `Tool_Interface` behind the unchanged `Tool_Registry`; the
    per-integration Connector transport seam mirroring `Search_Provider`
    (`Disabled_`/`Keyed_`/`Mock_`); enablement as a pure function of Credential presence +
    Enable_Setting; the composition root as the only wiring seam (register-only-when-Enabled,
    startup-abort naming the integration); the fixed error-code vocabulary mapped onto
    `AppError`; `SecretStr` redaction + no-secret persistence; tenant isolation at the
    data-access layer (404, never 403); observability side-effects never changing outcomes;
    and the "add a fifth integration" how-to (adapter + composition edit only).
  - Update the top-level `README` (and re-confirm `.env.example`) to describe the four
    integrations, their env-only `SecretStr` credentials + enable-toggles, and the
    keyless-disabled default (the platform runs and tests with zero integration credentials).
  - _Requirements: 3.1, 3.8, 4.1, 17.5_
  - _Design: Overview; Extension note; Settings additions (`.env.example`)_

- [ ] 11. Checkpoint — docs + wiring
  - Ensure `docs/decisions.md` and the `README` render correctly,
    `from agentforge.main import app` still imports under the keyless default (every
    integration Disabled), and the fast (property + unit) suite is green. Ensure all tests
    pass, ask the user if questions arise.

- [ ] 12. Final full-suite keyless checkpoint (leave unchecked for the user)
  - Run the full keyless suite `pytest -m 'not integration' -q` with zero integration
    credentials and no network (every integration Disabled; mock connectors injected
    throughout): all 10 Hypothesis property tests (>=100 examples each), all unit tests, and
    the status router tests. Only tests marked `@pytest.mark.integration` (real Postgres)
    remain deselected in this lane.
  - Verify every correctness property (1–10) has a passing property test, confirm all 17
    requirements are covered by implementation/test tasks, confirm no credential/secret value
    or stack trace is surfaced on any surface, and confirm no external credential or network
    was required. Report the pass/fail result.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Each task references specific acceptance criteria for traceability (`_Requirements: X.Y_`)
  and the design section it implements (`_Design: <section>_`); property sub-tasks
  additionally reference the design property they validate
  (`**Property N: <text>** ; **Validates: Requirements X.Y**`).
- The 10 Hypothesis property tests are the primary correctness surface for the integration
  core; unit tests cover schema shapes, retrieval-by-id actions, and the reused enterprise /
  guardrail / tracing integration points; the single integration test
  (`@pytest.mark.integration`) exercises the real Postgres migration `0011` and is excluded
  from the default keyless lane.
- Structural, wiring, RBAC/guardrail/rate-limit/tracing, and documentation criteria are
  covered by unit / integration / smoke tests rather than property tests, per the design's
  Testing Strategy (these do not vary meaningfully with input).
- Everything is KEYLESS + DETERMINISTIC by default: no integration credential and no network
  are ever required to run the full Phase 8 property + unit suite; existing `RAG_Tool` /
  `Web_Search_Tool` and agent / multi-agent behavior are unchanged when no integration is
  configured.
- Scope is strictly Phase 8 backend: no OAuth UI flows, no per-org secret vaulting, no new
  frontend, no cloud deployment, and no streaming/webhook ingestion — this phase ships the
  four pluggable tools, the introspection API, and the optional non-secret persistence.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "integrations/ package scaffold + base.py: error-code vocabulary, connector failure classes, Integration_Connector ABC, and the Integration_Tool base (Properties 3, 4, 5, 6)."
    },
    {
      "wave": 2,
      "tasks": ["2"],
      "description": "Settings additions (credentials + enable-toggles + timeout + result cap + integration_enabled helper) and .env.example (Property 1)."
    },
    {
      "wave": 3,
      "tasks": ["3"],
      "description": "The four Integration modules (slack, gmail, google_drive, github): Connector ABC + Disabled_/Keyed_/Mock_ + Integration_Tool subclass (Property 7)."
    },
    {
      "wave": 4,
      "tasks": ["4"],
      "description": "Composition-root wiring: connector builders + build_integration_tools + build_tool_registry extension + deps accessors (Properties 2, 10)."
    },
    {
      "wave": 5,
      "tasks": ["5"],
      "description": "Checkpoint — integration tools discoverable through the unmodified orchestrator on the keyless path."
    },
    {
      "wave": 6,
      "tasks": ["6", "7"],
      "description": "Integration_Status service + router and optional Integration_Connection persistence + migration 0011 — independent, may run in parallel (Property 9)."
    },
    {
      "wave": 7,
      "tasks": ["8"],
      "description": "RBAC + guardrail + rate-limit + tracing wiring/verification over reused seams; credential non-disclosure (Property 8)."
    },
    {
      "wave": 8,
      "tasks": ["9"],
      "description": "Checkpoint — governance, status, and persistence surfaces green on the keyless path."
    },
    {
      "wave": 9,
      "tasks": ["10", "11"],
      "description": "Documentation (decisions.md ADR + README + .env.example) and docs/wiring checkpoint."
    },
    {
      "wave": 10,
      "tasks": ["12"],
      "description": "Final full-suite keyless checkpoint (left unchecked for the user)."
    }
  ],
  "notes": [
    "Each wave depends on all prior waves; the error vocabulary, ABCs, and the Integration_Tool base precede the concrete integrations, which precede the composition-root wiring.",
    "Wave 6 tasks 6 (status) and 7 (connection persistence + migration 0011) touch distinct modules and may run in parallel.",
    "Optional (*) test sub-tasks may be deferred without blocking dependent waves.",
    "Properties 3-6 attach to task 1 because they are base-level behaviors testable with a mock connector alone (no specific integration required).",
    "Property 1 attaches to task 2 because enablement is a pure function of the Settings configuration.",
    "Property 7 attaches to task 3 because single-write dispatch and Drive read-only require the concrete per-integration connectors.",
    "Properties 2 and 10 attach to task 4 because the Tool_Registry contents and the keyless baseline set are determined by the composition root.",
    "Property 9 attaches to task 7 because the connection store is the cross-tenant enforcement point.",
    "Property 8 (credential non-disclosure) attaches to task 8 because by then every surface exists — Tool_Result, the status response, surfaced errors, recorded traces, and persisted connection records — so it parametrizes across all of them."
  ]
}
```
