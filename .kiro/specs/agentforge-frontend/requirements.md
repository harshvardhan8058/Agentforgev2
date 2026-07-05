# Requirements Document

## Introduction

AgentForge Phase 7 delivers a **React web frontend** — a single-page application that gives
human operators a browser-based console over the mature, already-shipped AgentForge backend
(Phases 1–6 complete). This phase is **UI-only**: it consumes stable, already-shipped backend
contracts served by an async FastAPI application and introduces **no new backend capability
and no backend contract change**.

The console lets an authenticated operator log in, work within their organization (tenant),
ask grounded RAG questions with citations, run and live-stream single-agent and multi-agent
sessions, act on human-approval checkpoints, and inspect the observability surface
(usage/cost analytics, the immutable prompt registry, guardrail configuration/evaluation, and
the evaluation framework). The UI is RBAC-aware (it reflects the caller's role), renders the
backend's uniform `AppError` envelope faithfully, and degrades gracefully when optional backend
features are disabled (e.g. tracing NoOp, web search disabled) without requiring any backend
change.

The stack is **React + Vite + TypeScript**, located in a `/frontend` subdirectory inside the
existing repository, with a typed API client derived from the backend's FastAPI OpenAPI schema.
Secrets never enter the client bundle; the frontend talks only to the backend API.

### Scope Boundaries (non-negotiable)

- The Web_Client SHALL NOT be designed to require any change to a backend contract; where a UI
  need cannot be met by an existing contract, the requirement is descoped rather than met by a
  backend change. (This is the one intentional negative constraint governing the whole spec.)
- All authentication, authorization, tenancy, and error semantics are defined by the backend;
  the frontend mirrors them and never re-implements or relaxes them.

## Glossary

- **Web_Client**: The React + Vite + TypeScript single-page application built in this phase; the
  system under specification. Runs in the operator's browser and communicates only with the
  Backend_API.
- **Backend_API**: The existing async FastAPI application (AgentForge Phases 1–6) whose HTTP/SSE
  contracts the Web_Client consumes. Its OpenAPI schema is the source of truth for request and
  response shapes.
- **API_Client**: The typed TypeScript client module generated/derived from the Backend_API's
  OpenAPI schema, through which the Web_Client makes all Backend_API calls.
- **Operator**: A human user of the Web_Client, authenticated as a User Principal via a JWT
  Access_Token.
- **Access_Token**: The JWT (HS256) bearer token issued by `POST /auth/login`,
  `POST /auth/register-self`, and `POST /auth/refresh`. Carries claims `sub`, `org_id`, `role`,
  and `exp`. Sent as `Authorization: Bearer <token>`.
- **Session**: The Web_Client's in-memory representation of an authenticated Operator, derived
  from a stored Access_Token and its decoded claims (`org_id`, `role`, `exp`).
- **Org_Context**: The active organization (tenant) the Operator is operating within, identified
  by the `org_id` claim of the current Access_Token; all Backend_API data is scoped to it.
- **Role**: The RBAC role carried in the Access_Token claim — one of `owner`, `admin`, `member`,
  `viewer` — nested `viewer ⊆ member ⊆ admin ⊆ owner`.
- **Permission**: A named capability derived from the Role per the backend RBAC map — one of
  `read`, `run_agents`, `ingest_documents`, `manage_api_keys`, `manage_members`.
- **AppError_Envelope**: The backend's uniform error body `{ "error": { code, message, details } }`
  returned with an HTTP status for every error.
- **SSE_Stream**: A `text/event-stream` Server-Sent-Events response from an agent or multi-agent
  streaming endpoint, ending in exactly one terminal event.
- **Terminal_Event**: The single stream-ending SSE event of type `completion` (success) or
  `error` (failure).
- **Approval_Checkpoint**: A non-terminal `approval_required` SSE event during a multi-agent run
  that pauses the run pending a human Approval_Decision.
- **Approval_Decision**: The Operator's decision on an Approval_Checkpoint — `approve`, `reject`,
  or `edit` — submitted to the multi-agent approval endpoint.
- **Citation**: A `{ document_id, chunk_id }` pair returned with a grounded answer identifying its
  source chunk.
- **Usage_Report**: The org-scoped cost/usage aggregation returned by `GET /analytics/usage`.
- **Prompt_Version**: An immutable, monotonically-versioned prompt template record from the
  prompt registry.
- **Guardrail_Decision**: The `allow` / `flag` / `block` result returned by the guardrails
  evaluate endpoint.
- **Evaluation_Run**: A persisted evaluation execution carrying an aggregate score and per-item
  scores.
- **Optional_Backend_Feature**: A backend capability that may be disabled by deployment
  configuration (e.g. tracing exporter set to NoOp, web search disabled) without changing the
  backend's default keyless/deterministic behavior.

## Requirements

### Requirement 1: Project Scaffolding and Typed API Client

**User Story:** As a frontend developer, I want a React + Vite + TypeScript project with a typed
API client derived from the backend OpenAPI schema, so that all backend calls are type-safe and
consistent with the shipped contracts.

#### Acceptance Criteria

1. THE Web_Client SHALL be implemented as a React + Vite + TypeScript single-page application
   located in the `/frontend` subdirectory of the repository.
2. THE Web_Client SHALL expose all Backend_API calls exclusively through the API_Client module.
3. THE API_Client SHALL derive its request and response types from the Backend_API's FastAPI
   OpenAPI schema.
4. WHEN the API_Client sends a request to the Backend_API, THE API_Client SHALL target the
   Backend_API base URL supplied by build-time or runtime configuration.
5. THE Web_Client SHALL exclude every credential and secret value from the compiled client
   bundle, restricting the bundle to the Backend_API base URL and non-secret configuration.
6. WHERE a UI capability has no corresponding existing Backend_API contract, THE Web_Client SHALL
   omit that capability rather than depend on a new or modified backend contract.

### Requirement 2: Authentication and Login

**User Story:** As an Operator, I want to log in with my email and password, so that I can obtain
an authenticated Session and access the console.

#### Acceptance Criteria

1. WHEN an Operator submits valid credentials to the login form, THE Web_Client SHALL call
   `POST /auth/login` and store the returned Access_Token for the Session.
2. WHEN `POST /auth/login` returns `401 auth_failed`, THE Web_Client SHALL display the
   AppError_Envelope message and keep the Operator on the login view.
3. WHEN an Operator submits the self-registration form, THE Web_Client SHALL call
   `POST /auth/register-self` and, on `201`, store the returned Access_Token for the Session.
4. IF the login or registration form has an empty email or empty password field, THEN THE
   Web_Client SHALL block submission and prompt the Operator to complete the field.
5. WHILE no valid Access_Token is stored — whether absent, expired, or otherwise invalid — THE
   Web_Client SHALL restrict the Operator to unauthenticated views (login and self-registration)
   and route all other views to the login view.
6. WHEN an Access_Token is stored for the Session, THE Web_Client SHALL attach it as an
   `Authorization: Bearer <token>` header on every subsequent authenticated Backend_API request.

### Requirement 3: Session Persistence, Expiry, and Logout

**User Story:** As an Operator, I want my session to be handled securely, refreshed when possible,
and cleared on logout or expiry, so that my access reflects my current authentication state.

#### Acceptance Criteria

1. WHEN an Access_Token is stored, THE Web_Client SHALL decode its `org_id`, `role`, and `exp`
   claims to establish the Session, Org_Context, and Role.
2. WHILE a stored Access_Token has an `exp` in the past, THE Web_Client SHALL treat the Session
   as expired and route the Operator to the login view.
3. WHEN a Backend_API response returns `401 unauthorized` for an authenticated request, THE
   Web_Client SHALL clear the stored Access_Token and route the Operator to the login view.
4. WHEN the Operator activates logout, THE Web_Client SHALL clear the stored Access_Token and all
   derived Session state and route the Operator to the login view.
5. WHEN an authenticated request returns `401 unauthorized` AND a still-valid refresh is possible,
   THE Web_Client SHALL call `POST /auth/refresh` once, and on success replace the stored
   Access_Token and retry the original request one time.
6. IF `POST /auth/refresh` returns `401 unauthorized`, THEN THE Web_Client SHALL clear the stored
   Access_Token and route the Operator to the login view.

### Requirement 4: Organization Context and RBAC-Aware UI

**User Story:** As an Operator, I want the console to reflect my organization and role, so that I
only see and attempt actions permitted to me within my tenant.

#### Acceptance Criteria

1. THE Web_Client SHALL display the active Org_Context and Role derived from the current
   Access_Token in a persistent location of the authenticated layout.
2. WHERE the Session Role lacks the `run_agents` Permission, THE Web_Client SHALL omit the query,
   single-agent run, and multi-agent run submission controls from the rendered DOM.
3. WHERE the Session Role lacks the `ingest_documents` Permission, THE Web_Client SHALL omit
   document-upload and prompt-version-creation controls from the rendered DOM.
4. WHERE the Session Role lacks the `manage_members` Permission, THE Web_Client SHALL omit
   organization member and team management controls from the rendered DOM.
5. WHERE the Session Role lacks the `manage_api_keys` Permission, THE Web_Client SHALL omit
   API-key management controls from the rendered DOM.
6. WHEN the Operator selects a different organization they belong to, THE Web_Client SHALL adopt
   the Access_Token whose `org_id` matches the selected organization as the active Org_Context and
   re-scope all displayed data to that Org_Context.
7. IF a Backend_API request for a resource returns `404 not_found` due to cross-tenant access,
   THEN THE Web_Client SHALL present the resource as not found and SHALL NOT indicate that the
   resource exists in another organization.

### Requirement 5: Uniform Error Envelope Handling (cross-cutting)

**User Story:** As an Operator, I want backend errors surfaced clearly and consistently, so that I
understand what failed and can respond appropriately.

#### Acceptance Criteria

1. WHEN a Backend_API response carries the AppError_Envelope, THE Web_Client SHALL extract
   `error.code` and `error.message` and present the message to the Operator.
2. WHERE an AppError_Envelope includes `error.details`, THE Web_Client SHALL surface the relevant
   detail fields alongside the message.
3. WHEN a Backend_API response returns `422 validation_error`, THE Web_Client SHALL present the
   validation detail against the corresponding form fields.
4. WHEN a Backend_API response returns `429 rate_limited`, THE Web_Client SHALL present a
   rate-limit notice and preserve the Operator's unsubmitted input.
5. WHEN a Backend_API response returns `500 internal_error`, THE Web_Client SHALL present the
   generic envelope message without attempting to display a stack trace.
6. IF a Backend_API request fails at the network layer before an HTTP response is received, THEN
   THE Web_Client SHALL present a connectivity error and offer a retry action.

### Requirement 6: Graceful Degradation for Optional Backend Features (cross-cutting)

**User Story:** As an Operator using a deployment where some optional features are disabled, I
want the console to remain functional and communicate the disabled state, so that I can still use
every enabled capability.

#### Acceptance Criteria

1. WHERE an Optional_Backend_Feature is disabled, THE Web_Client SHALL keep all views backed by
   enabled contracts fully operational.
2. WHEN a data endpoint for an observability view returns an empty result set, THE Web_Client
   SHALL render an explicit empty state for that view.
3. WHERE a run trace contains no exported detail because tracing is configured as NoOp, THE
   Web_Client SHALL render the run's available streamed and persisted data and present the trace
   detail as unavailable.
4. WHERE a guardrail, evaluator, or provider capability is absent from a Backend_API response,
   THE Web_Client SHALL render only the capabilities present in that response.
5. IF a Backend_API response returns `502 llm_provider_error`, THEN THE Web_Client SHALL present
   the provider error message and preserve the Operator's submitted input for retry.

### Requirement 7: RAG Query with Citations

**User Story:** As an Operator, I want to ask grounded questions and see cited answers, so that I
can trust and verify the information returned.

#### Acceptance Criteria

1. WHEN an Operator submits a non-empty query, THE Web_Client SHALL call `POST /query` with the
   query text and any configured `top_k` and display the returned answer.
2. WHEN a query response includes citations, THE Web_Client SHALL display each Citation's
   `document_id` and `chunk_id` alongside the answer.
3. WHEN a query response has `grounded` false with an empty citation list, THE Web_Client SHALL
   indicate that the answer is ungrounded.
4. WHEN a query response includes guardrail `flags`, THE Web_Client SHALL display the flags with
   the answer.
5. IF `POST /query` returns `400 guardrail_blocked`, THEN THE Web_Client SHALL present the block
   reason from the AppError_Envelope details and withhold any answer.
6. THE Web_Client SHALL display the `provider` value returned with the query answer.

### Requirement 8: Document Management

**User Story:** As an Operator with the appropriate role, I want to upload, list, and delete
documents in my organization, so that I can manage the corpus my RAG queries draw from.

#### Acceptance Criteria

1. WHERE the Session Role holds the `ingest_documents` Permission, THE Web_Client SHALL present a
   document-upload control that calls `POST /documents` with a multipart file upload.
2. WHEN a document upload succeeds, THE Web_Client SHALL display the returned `document_id`,
   `filename`, `chunk_count`, and `status`.
3. THE Web_Client SHALL list the Org_Context documents returned by `GET /documents` with their
   filename, content type, size, status, chunk count, and created-at values.
4. WHERE the Session Role holds the `ingest_documents` Permission, THE Web_Client SHALL present a
   delete control that calls `DELETE /documents/{document_id}` and, on `204`, remove the document
   from the displayed list.
5. IF a document upload returns `413 size_limit_exceeded`, `415 unsupported_format`,
   `400 empty_document`, `422 extraction_failure`, `422 extraction_timeout`, or
   `500 embedding_error`, THEN THE Web_Client SHALL present the corresponding AppError_Envelope
   message.

### Requirement 9: Single-Agent Run with Live SSE Streaming

**User Story:** As an Operator, I want to run a single agent and watch its reasoning stream live,
so that I can follow the reason→act→observe loop and its final grounded answer.

#### Acceptance Criteria

1. WHEN an Operator starts a streaming single-agent run, THE Web_Client SHALL open the
   `POST /agent/stream` SSE_Stream and render each received event in the order received.
2. WHEN the SSE_Stream emits a `completion` Terminal_Event, THE Web_Client SHALL render the final
   answer and any citations and close the stream.
3. WHEN the SSE_Stream emits an `error` Terminal_Event, THE Web_Client SHALL present the error
   detail and close the stream.
4. WHEN an Operator starts a non-streaming single-agent run, THE Web_Client SHALL call
   `POST /agent/run` and display the answer, the single `termination_reason`, and any citations.
5. WHEN an Operator opens a completed run's trace, THE Web_Client SHALL call
   `GET /agent/runs/{run_id}/trace` and display the ordered trace entries.
6. IF `GET /agent/runs/{run_id}/trace` returns `404 not_found`, THEN THE Web_Client SHALL present
   the run trace as not found.
7. WHILE an SSE_Stream is open, THE Web_Client SHALL provide a control to cancel the client-side
   stream subscription.

### Requirement 10: Multi-Agent Run with Streaming and Human Approval

**User Story:** As an Operator, I want to launch a multi-agent collaboration, watch each role's
contribution stream, and act on approval checkpoints, so that I can supervise Planner→Researcher→
Writer→Critic runs to completion.

#### Acceptance Criteria

1. WHEN an Operator starts a multi-agent run, THE Web_Client SHALL call `POST /multi-agent/runs`
   and display the returned `run_id`, `conversation_id`, and `status`.
2. WHEN an Operator opens the stream for a run, THE Web_Client SHALL open the
   `POST /multi-agent/runs/{run_id}/stream` SSE_Stream and render each event, attributing every
   agent event to its `role_id` and ordering events by their `sequence`.
3. WHEN the SSE_Stream emits an `approval_required` Approval_Checkpoint, THE Web_Client SHALL
   present the checkpoint content and offer `approve`, `reject`, and `edit` actions.
4. WHEN an Operator submits an Approval_Decision, THE Web_Client SHALL call
   `POST /multi-agent/runs/{run_id}/approval` with the decision type and any feedback or edited
   content, and display the returned `status` and `termination_reason`.
5. WHEN the SSE_Stream emits a `completion` Terminal_Event, THE Web_Client SHALL render the
   final output and its citations and close the stream.
6. WHEN an Operator opens a run's result, THE Web_Client SHALL call
   `GET /multi-agent/runs/{run_id}` and display the `status`, `termination_reason`, final output,
   and the role-attributed ordered trace.
7. IF a multi-agent endpoint returns `404 not_found`, THEN THE Web_Client SHALL present the run as
   not found.
8. IF `POST /multi-agent/runs/{run_id}/approval` returns `409 run-not-awaiting-approval`, THEN THE
   Web_Client SHALL present that the run is not awaiting approval and refresh the run status.

### Requirement 11: Analytics and Usage Dashboard

**User Story:** As an Operator with read access, I want to view my organization's token usage and
cost, so that I can monitor consumption and spend.

#### Acceptance Criteria

1. WHEN an Operator opens the analytics dashboard, THE Web_Client SHALL call
   `GET /analytics/usage` for the Org_Context and display `total_tokens` and `total_cost`.
2. WHEN an Operator selects a start and end time range, THE Web_Client SHALL call
   `GET /analytics/usage` with the `start` and `end` query parameters and display the resulting
   Usage_Report.
3. THE Web_Client SHALL display the `by_provider`, `by_model`, and `by_user` breakdown entries,
   each showing its key, total tokens, and total cost.
4. THE Web_Client SHALL render each `total_cost` value as the exact string returned by the
   Backend_API without numeric reformatting.
5. WHEN the Usage_Report contains no records for the selected range, THE Web_Client SHALL render
   an empty usage state.
6. IF rendering a breakdown grouping fails, THEN THE Web_Client SHALL hide that breakdown
   independently while continuing to display the usage totals and any remaining breakdowns.

### Requirement 12: Prompt Registry

**User Story:** As an Operator, I want to browse the immutable versioned prompt registry, create
new versions, and render prompts, so that I can manage prompt evolution safely.

#### Acceptance Criteria

1. WHEN an Operator opens the prompt registry, THE Web_Client SHALL call `GET /prompts` and list
   the Org_Context template names.
2. WHEN an Operator selects a template, THE Web_Client SHALL call `GET /prompts/{name}/versions`
   and display the ascending version numbers.
3. WHEN an Operator selects a version, THE Web_Client SHALL call `GET /prompts/{name}` with the
   `version` query parameter and display that Prompt_Version's body, variables, and created-at.
4. WHERE the Session Role holds the `ingest_documents` Permission, THE Web_Client SHALL present a
   control that calls `POST /prompts` to append a new immutable Prompt_Version and display the
   returned version number.
5. WHEN an Operator renders a prompt with supplied variable values, THE Web_Client SHALL call
   `POST /prompts/{name}/render` and display the rendered string.
6. IF the Operator omits a value for any variable declared by the selected Prompt_Version, THEN
   THE Web_Client SHALL block the render submission and prompt for the missing variables before
   calling `POST /prompts/{name}/render`.
7. IF `POST /prompts/{name}/render` returns `400 missing_variable`, THEN THE Web_Client SHALL
   present the missing variable names from the AppError_Envelope details.

### Requirement 13: Guardrails

**User Story:** As an Operator, I want to view the active guardrail configuration and evaluate
content against it, so that I can understand and test the safety pipeline.

#### Acceptance Criteria

1. WHEN an Operator opens the guardrails view, THE Web_Client SHALL call `GET /guardrails/config`
   and display each active guardrail's `name` and `kind` in the returned order.
2. WHEN an Operator submits content to evaluate, THE Web_Client SHALL call
   `POST /guardrails/evaluate` and display the returned Guardrail_Decision.
3. WHEN a Guardrail_Decision is `flag`, THE Web_Client SHALL display the returned flags and any
   returned reason.
4. WHEN a Guardrail_Decision is `block`, THE Web_Client SHALL display the returned reason.
5. WHERE the guardrail configuration list is empty, THE Web_Client SHALL render an explicit
   no-active-guardrails state.

### Requirement 14: Evaluations

**User Story:** As an Operator, I want to create evaluation datasets, run evaluators over them,
and view results, so that I can measure output quality reproducibly.

#### Acceptance Criteria

1. WHERE the Session Role holds the `run_agents` Permission, THE Web_Client SHALL present a
   control that calls `POST /evaluations/datasets` to create a named dataset with its items and
   display the returned `dataset_id`.
2. WHEN an Operator opens the evaluations view, THE Web_Client SHALL call
   `GET /evaluations/datasets` and list the Org_Context datasets with their name and created-at.
3. WHERE the Session Role holds the `run_agents` Permission, THE Web_Client SHALL present a
   control that calls `POST /evaluations/runs` with a `dataset_id` and named evaluators and
   display the returned aggregate score and per-item scores.
4. WHEN an Operator opens a run, THE Web_Client SHALL call `GET /evaluations/runs/{run_id}` and
   display the `aggregate_score` and per-item `EvaluationItemScore` entries.
5. IF an evaluations endpoint returns `404 not_found`, THEN THE Web_Client SHALL present the
   dataset or run as not found.

### Requirement 15: Conversation Context for Runs

**User Story:** As an Operator, I want agent and multi-agent runs to be attached to a conversation,
so that multi-turn context is preserved across runs.

#### Acceptance Criteria

1. WHEN an Operator starts a new conversation, THE Web_Client SHALL call `POST /conversations` and
   retain the returned `conversation_id` for subsequent runs.
2. WHEN an Operator submits a run within an active conversation, THE Web_Client SHALL include the
   retained `conversation_id` in the run request.
3. WHEN an Operator opens a conversation, THE Web_Client SHALL call
   `GET /conversations/{conversation_id}` and display the messages ordered by position.
4. IF `GET /conversations/{conversation_id}` returns `404 not_found`, THEN THE Web_Client SHALL
   present the conversation as not found.
