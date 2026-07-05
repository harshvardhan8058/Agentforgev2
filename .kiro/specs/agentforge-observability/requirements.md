# Requirements Document

## Introduction

This spec covers **Phase 6 (Production Observability)** of the AgentForge platform. Phases 1
(Foundation), 2 (Core RAG), 3 (Agentic Layer), 4 (Multi-Agent Collaboration), and 5
(Enterprise Controls) are already built and provide the reusable, pluggable seams this phase
builds on and MUST NOT reimplement: an async FastAPI `API_Service` with a uniform error
envelope (`{ "error": { code, message, details } }`) and typed request/response schemas; a
`Configuration_Manager` (`Settings`) that loads settings exclusively from environment
variables, treats every credential as optional (`SecretStr`), and keeps the platform bootable
with no external credentials; a composition root (`config/container.py`) that wires the object
graph behind abstract interfaces and is the only place concrete implementations are named;
Postgres with pgvector plus a versioned SQL migration runner (`db/migrations.py`) that applies
additive migrations from the `migrations/` directory; Redis; a pluggable `LLM_Provider` seam
exposing `generate(prompt) -> GenerationResult` with a Groq primary provider and a
deterministic, network-free keyless `Fallback_Provider`; a `Trace_Recorder` seam recording an
ordered per-run `Trace` of steps (`InMemory_Trace_Recorder` plus `Pg_Trace_Recorder`) consumed
by the agent and multi-agent orchestrators; and the Phase 5 enterprise layer providing a
`Principal` (org_id, user_id/key_id, role), `get_current_principal` and `require_permission`
FastAPI dependencies, strict multi-tenancy (an `org_id` on every tenant-owned resource enforced
at the data-access layer), an RBAC policy (roles owner/admin/member/viewer over permissions
manage_members/manage_api_keys/ingest_documents/run_agents/read), organization-scoped API keys,
and Redis-backed per-principal rate limiting. Every prior phase runs and tests fully **keyless**
by default, and Phase 6 MUST preserve that promise.

Phase 6 adds **production observability** that makes the platform measurable, controllable, and
verifiable in production while remaining keyless and deterministic by default. It introduces a
pluggable **Tracing_Exporter** seam that forwards the existing `Trace` to an external tracer
(LangSmith) only when configured, defaulting to a keyless NoOp/local exporter that makes no
external call; **token analytics and cost tracking** that capture prompt/completion/total token
usage and a computed cost for each `LLM_Provider` call, attributed to an organization, user,
provider, and model and persisted for later analysis; an org-scoped **cost/analytics API** that
returns aggregated usage and cost with strict tenant isolation; a **Prompt_Registry** storing
named prompt templates with immutable, monotonically versioned revisions that the RAG, agent,
and multi-agent flows can resolve and render; a pluggable **Guardrail** seam applying ordered
input and output validation where a blocking guardrail short-circuits with a standard error and
a flagging guardrail annotates without blocking; and an **Evaluation_Framework** that runs
Evaluators over an Evaluation_Dataset against the RAG/agent pipeline using the keyless
`Fallback_Provider`, producing a persisted Evaluation_Run with per-item scores and an aggregate.
All new capabilities are wired through the existing composition root and exposed through the
existing `API_Service` with authentication, tenancy, and RBAC applied, and every new
observability record is org-scoped and enforced at the data-access layer consistent with
Phase 5.

Explicitly OUT OF SCOPE for this spec (reserved for later phases): the React frontend — this
phase provides the analytics, prompt-registry, guardrail-config, and evaluation APIs that a
frontend will later consume, but not the UI itself; third-party integrations such as Slack,
Gmail, Drive, and GitHub; and cloud deployment. The observability seams MUST remain modular so
these can be added later without rewriting core flows.

## Glossary

- **Observability_Layer**: The Phase 6 subsystem delivered by this spec, composed of the
  Tracing_Exporter, the Usage_Recorder, the Cost_Model, the Analytics_Service, the
  Prompt_Registry, the Guardrail_Pipeline, and the Evaluation_Framework, together with the
  Phase 6 extensions to the API_Service, Configuration_Manager, and Database.
- **Trace**: The existing ordered, per-run record of agent and multi-agent steps produced by
  the Trace_Recorder; consumed by Phase 6 but not reimplemented.
- **Trace_Recorder**: The existing Phase 3/4 seam that records and exposes a Trace; Phase 6
  wraps or consumes it and MUST NOT reimplement it.
- **Tracing_Exporter**: The Phase 6 pluggable seam that forwards a completed or in-progress
  Trace to an external tracing destination when configured, and does nothing observable
  otherwise.
- **NoOp_Tracing_Exporter**: The default keyless Tracing_Exporter that performs no external
  call and produces no external side effect, active when no external tracing credential is
  configured.
- **External_Tracer**: An external tracing destination (LangSmith) to which the Tracing_Exporter
  forwards Traces when a Tracing_Credential is configured.
- **Tracing_Credential**: The optional secret (e.g. the LangSmith API key) supplied through the
  Configuration_Manager as a `SecretStr` that enables the External_Tracer; absent by default.
- **LLM_Provider**: The existing pluggable seam exposing `generate(prompt) -> GenerationResult`;
  Phase 6 instruments its call path without changing its contract.
- **Fallback_Provider**: The existing deterministic, network-free keyless LLM_Provider used on
  the keyless path and in tests.
- **Instrumented_Provider**: A Phase 6 wrapper around an LLM_Provider that emits a Usage_Record
  to the Usage_Sink for each generate call while delegating generation to the wrapped provider
  and preserving the LLM_Provider contract.
- **Usage_Record**: A persisted record of a single LLM_Provider call capturing Org_Id, User_Id,
  provider name, model name, prompt tokens, completion tokens, total tokens, computed Cost, and
  a timestamp.
- **Token_Count**: The prompt, completion, and total token quantities associated with a single
  LLM_Provider call.
- **Cost_Model**: The pluggable component that maps a (provider, model, Token_Count) to a Cost.
- **Cost**: The monetary amount computed by the Cost_Model for a single LLM_Provider call,
  expressed in a fixed currency unit.
- **Usage_Recorder**: The component that constructs and persists Usage_Records.
- **Usage_Sink**: The seam through which the Instrumented_Provider forwards usage data to the
  Usage_Recorder, passed through the composition root; its keyless default is deterministic.
- **Analytics_Service**: The component that queries and aggregates Usage_Records for an
  Organization over a time range, producing totals and breakdowns.
- **Usage_Report**: The aggregated result returned by the Analytics_Service, containing total
  tokens, total Cost, and breakdowns by provider, model, and user for the caller's Organization.
- **Prompt_Registry**: The component that stores named Prompt_Templates as immutable
  Prompt_Versions and resolves them by name and version.
- **Prompt_Template**: A named, org-scoped prompt identified by its name within an Organization,
  owning an ordered sequence of Prompt_Versions.
- **Prompt_Version**: An immutable revision of a Prompt_Template, identified by a monotonically
  increasing version number and carrying the template body and declared variable names.
- **Prompt_Rendering**: The substitution of supplied variable values into a Prompt_Version's
  body to produce a concrete prompt string.
- **Guardrail**: A pluggable rule applied to an input or an output that returns a
  Guardrail_Result of allow, flag, or block.
- **Guardrail_Pipeline**: The ordered collection of Guardrails applied to an input or an output;
  it runs the Guardrails in a defined order and short-circuits on the first blocking result.
- **Guardrail_Result**: The outcome of evaluating a Guardrail or the Guardrail_Pipeline, one of
  allow, flag (with annotations), or block (with a reason).
- **Input_Guardrail**: A Guardrail applied to user input or a rendered prompt before it reaches
  the LLM_Provider or agent.
- **Output_Guardrail**: A Guardrail applied to a model or agent output before it is returned to
  the caller.
- **Evaluation_Framework**: The Phase 6 subsystem that runs Evaluators over an
  Evaluation_Dataset against the RAG/agent pipeline and produces an Evaluation_Run.
- **Evaluation_Dataset**: An org-scoped named collection of Evaluation_Items, each with an input
  and an optional expected output.
- **Evaluation_Item**: One entry in an Evaluation_Dataset consisting of an input and an optional
  expected output.
- **Evaluator**: A deterministic scoring function that maps an (input, expected output, actual
  output) to a numeric Item_Score (e.g. exact-match, contains, a heuristic scorer).
- **Item_Score**: The numeric score an Evaluator assigns to a single Evaluation_Item.
- **Evaluation_Run**: The persisted, org-scoped result of running one or more Evaluators over an
  Evaluation_Dataset, containing per-item Item_Scores and an Aggregate_Score.
- **Aggregate_Score**: The summary score of an Evaluation_Run computed by aggregating its
  per-item Item_Scores.
- **Principal**: The existing Phase 5 authenticated identity making a request, carrying an
  Org_Id, a User_Id or Key_Id, a Role, and effective Permissions.
- **Org_Id**: The identifier of the Organization that owns a tenant-owned resource; the tenant
  scoping key defined in Phase 5.
- **User_Id**: The identifier of the User associated with a Principal, used for usage
  attribution and trace tagging.
- **RBAC_Policy**: The existing Phase 5 component mapping Roles to Permissions; Phase 6 reuses it
  and its `read` Permission for analytics reads.
- **API_Service**: The existing FastAPI application that exposes HTTP endpoints using the uniform
  Error_Envelope and the Phase 5 authentication and authorization dependencies.
- **Configuration_Manager**: The existing component that loads and validates settings and secrets
  from environment variables.
- **Composition_Root**: The existing `config/container.py` that wires concrete implementations
  behind abstract interfaces.
- **Database**: The existing PostgreSQL instance with pgvector, extended by additive Phase 6
  migrations applied through the existing migration runner.
- **Migration_Runner**: The existing versioned SQL migration runner (`db/migrations.py`) that
  applies additive migrations and halts on the first failure naming the failing migration.
- **Error_Envelope**: The existing uniform error response body of the form
  `{ "error": { code, message, details } }`.
- **Keyless_Mode**: The default operating mode in which no external credential is configured and
  the platform, including the full Phase 6 test suite, runs deterministically.

## Requirements

### Requirement 1: Pluggable Tracing Export

**User Story:** As an operator, I want the platform's existing agent and multi-agent traces
forwarded to an external tracer only when I configure one, so that I gain production
observability without any external calls occurring by default.

#### Acceptance Criteria

1. THE Observability_Layer SHALL define a Tracing_Exporter seam that consumes the existing Trace produced by the Trace_Recorder and SHALL NOT reimplement the Trace_Recorder.
2. WHERE no Tracing_Credential is configured, THE Composition_Root SHALL select the NoOp_Tracing_Exporter as the active Tracing_Exporter.
3. WHEN the NoOp_Tracing_Exporter exports a Trace, THE NoOp_Tracing_Exporter SHALL make no external call and SHALL produce no external side effect.
4. WHERE a Tracing_Credential is configured, THE Composition_Root SHALL select the External_Tracer-backed Tracing_Exporter as the active Tracing_Exporter.
5. WHEN the active Tracing_Exporter exports a Trace for a run owned by an Organization, THE Tracing_Exporter SHALL tag the exported Trace with the Org_Id and the User_Id of the Principal that initiated the run.
6. THE Observability_Layer SHALL allow a new Tracing_Exporter implementation to be added by registering it in the Composition_Root without modifying the agent orchestrator, the multi-agent orchestrator, or the Trace_Recorder.
7. IF the External_Tracer-backed Tracing_Exporter fails to forward a Trace, THEN THE Tracing_Exporter SHALL suppress the failure from the caller's request path so that trace export never changes the outcome of an agent or multi-agent run.

### Requirement 2: Token Usage and Cost Tracking

**User Story:** As an organization owner, I want token usage and cost captured for every model
call and attributed to my organization, so that I can understand and account for consumption.

#### Acceptance Criteria

1. WHEN an LLM_Provider call completes through the Instrumented_Provider, THE Usage_Recorder SHALL construct a Usage_Record capturing the Org_Id, the User_Id, the provider name, the model name, the prompt tokens, the completion tokens, and the total tokens for that call.
2. WHEN the Usage_Recorder constructs a Usage_Record, THE Cost_Model SHALL compute the Cost from the provider name, the model name, and the Token_Count, and THE Usage_Recorder SHALL store the computed Cost on the Usage_Record.
3. THE Usage_Recorder SHALL persist each Usage_Record scoped to the Org_Id of the Principal on whose behalf the LLM_Provider call was made.
4. WHEN the Fallback_Provider is the active provider for a call, THE Instrumented_Provider SHALL report a deterministic Token_Count that is a pure function of the request, so that keyless tests produce deterministic Usage_Records.
5. THE Cost_Model SHALL map every (provider name, model name, Token_Count) to a defined Cost, applying a default rate WHERE no rate is configured for a given provider and model.
6. THE Observability_Layer SHALL allow a new Cost_Model to be added by registering it in the Composition_Root without modifying the Instrumented_Provider or the LLM_Provider contract.
7. THE total tokens of every Usage_Record SHALL equal the sum of that Usage_Record's prompt tokens and completion tokens.

### Requirement 3: Organization-Scoped Cost and Usage Analytics API

**User Story:** As an organization owner, I want to query aggregated usage and cost for my
organization over a time range, so that I can monitor spend without ever seeing another
tenant's data.

#### Acceptance Criteria

1. WHEN a Principal holding the read Permission requests a Usage_Report for a time range, THE Analytics_Service SHALL return the total tokens and total Cost of the Usage_Records whose Org_Id equals the Principal's Org_Id within that time range.
2. WHEN a Principal holding the read Permission requests a Usage_Report, THE Analytics_Service SHALL include breakdowns of tokens and Cost by provider, by model, and by User_Id for the Principal's Organization.
3. THE Analytics_Service SHALL compute a Usage_Report only from Usage_Records whose Org_Id equals the requesting Principal's Org_Id and SHALL exclude every Usage_Record owned by any other Organization.
4. THE total tokens reported in a Usage_Report SHALL equal the sum of the total tokens of the Usage_Records included in that report, and the total Cost SHALL equal the sum of their Costs.
5. WHEN a request to the analytics endpoint presents no valid Access_Token or API_Key, THE API_Service SHALL reject the request with HTTP status 401 using the Error_Envelope.
6. IF an authenticated Principal that lacks the read Permission requests a Usage_Report, THEN THE API_Service SHALL reject the request with HTTP status 403 using the Error_Envelope and SHALL NOT return usage data.
7. THE sum of the tokens across the provider breakdown of a Usage_Report SHALL equal the report's total tokens, and the sum of the tokens across the model breakdown SHALL equal the report's total tokens.

### Requirement 4: Prompt Registry with Immutable Versioning

**User Story:** As a prompt engineer, I want named prompt templates stored as immutable versions
scoped to my organization, so that I can evolve prompts safely and resolve a known version at
run time.

#### Acceptance Criteria

1. WHEN a Principal creates a Prompt_Version for a Prompt_Template name within the Principal's Organization, THE Prompt_Registry SHALL persist the Prompt_Version scoped to the Org_Id with a version number equal to one greater than the highest existing version number for that Prompt_Template name, or one when no prior version exists.
2. THE Prompt_Registry SHALL treat every persisted Prompt_Version as immutable and SHALL NOT modify the body or declared variables of a Prompt_Version after it is created.
3. WHEN a Principal requests the latest Prompt_Version for a Prompt_Template name within the Principal's Organization, THE Prompt_Registry SHALL return the Prompt_Version with the highest version number for that name and Org_Id.
4. WHEN a Principal requests a specific version number of a Prompt_Template name within the Principal's Organization, THE Prompt_Registry SHALL return the Prompt_Version with that version number for that name and Org_Id.
5. WHEN a Principal lists the versions of a Prompt_Template name within the Principal's Organization, THE Prompt_Registry SHALL return the version numbers for that name and Org_Id in ascending order.
6. WHEN a Prompt_Version is rendered with a set of variable values that supplies every declared variable, THE Prompt_Registry SHALL produce a prompt string with each declared variable replaced by its supplied value.
7. IF a Prompt_Version is rendered with variable values that omit a declared variable, THEN THE Prompt_Registry SHALL reject the rendering and return a missing-variable error using the Error_Envelope.
8. IF a Principal requests a Prompt_Template or Prompt_Version whose Org_Id differs from the Principal's Org_Id, THEN THE Prompt_Registry SHALL respond with HTTP status 404 using the Error_Envelope, consistent with Phase 5 tenant isolation.
9. THE version numbers of the Prompt_Versions of a Prompt_Template SHALL form a contiguous sequence beginning at one with no duplicates.

### Requirement 5: Input and Output Guardrails

**User Story:** As a platform operator, I want ordered guardrails validating inputs and outputs,
so that unsafe or non-compliant content is blocked or flagged before or after model calls.

#### Acceptance Criteria

1. THE Guardrail_Pipeline SHALL apply its configured Guardrails to an input or an output in a defined, stable order.
2. WHEN the Guardrail_Pipeline evaluates an input or an output and every Guardrail returns allow, THE Guardrail_Pipeline SHALL return a Guardrail_Result of allow and permit the downstream operation to proceed.
3. WHEN a Guardrail in the Guardrail_Pipeline returns block, THE Guardrail_Pipeline SHALL stop evaluating subsequent Guardrails and return a blocking Guardrail_Result carrying the blocking reason.
4. IF an Input_Guardrail returns block for a request at the query, agent, or multi-agent entry point, THEN THE API_Service SHALL reject the request using the Error_Envelope and SHALL NOT invoke the downstream LLM_Provider, agent, or multi-agent orchestrator for that request.
5. WHEN a Guardrail in the Guardrail_Pipeline returns flag and no Guardrail returns block, THE Guardrail_Pipeline SHALL return an allowing Guardrail_Result annotated with each flag and permit the downstream operation to proceed.
6. THE Guardrail_Pipeline SHALL apply Input_Guardrails to the input of the query, agent, and multi-agent entry points and SHALL apply Output_Guardrails to the output of those entry points.
7. WHERE no Guardrail configuration is supplied, THE Composition_Root SHALL apply a deterministic default set of Guardrails whose results are a pure function of the evaluated content.
8. THE Observability_Layer SHALL allow a new Guardrail to be added to the Guardrail_Pipeline by registering it in the Composition_Root without modifying the query, agent, or multi-agent entry points.

### Requirement 6: Deterministic Evaluation Framework

**User Story:** As a developer, I want to run scoring evaluators over a dataset against the
pipeline using the keyless provider, so that I can measure quality deterministically and track
results per organization.

#### Acceptance Criteria

1. WHEN a Principal creates an Evaluation_Dataset within the Principal's Organization, THE Evaluation_Framework SHALL persist the Evaluation_Dataset and its Evaluation_Items scoped to the Org_Id.
2. WHEN an Evaluation_Run is executed over an Evaluation_Dataset using one or more Evaluators, THE Evaluation_Framework SHALL produce the actual output for each Evaluation_Item by running the RAG or agent pipeline with the Fallback_Provider on the keyless path.
3. WHEN an Evaluation_Run scores an Evaluation_Item with an Evaluator, THE Evaluation_Framework SHALL compute a deterministic Item_Score that is a pure function of the item's input, its expected output, and the actual output.
4. WHEN an Evaluation_Run completes, THE Evaluation_Framework SHALL compute the Aggregate_Score by aggregating the per-item Item_Scores of the Evaluation_Run.
5. WHEN an Evaluation_Run completes, THE Evaluation_Framework SHALL persist the Evaluation_Run with its per-item Item_Scores and its Aggregate_Score scoped to the Org_Id of the Principal that initiated the run.
6. WHERE the keyless path is active, THE Evaluation_Framework SHALL produce identical Item_Scores and an identical Aggregate_Score for repeated Evaluation_Runs over the same Evaluation_Dataset and the same Evaluators.
7. THE Observability_Layer SHALL allow a new Evaluator to be added by registering it in the Composition_Root without modifying the Evaluation_Run execution logic.
8. IF a Principal requests an Evaluation_Dataset or an Evaluation_Run whose Org_Id differs from the Principal's Org_Id, THEN THE Evaluation_Framework SHALL respond with HTTP status 404 using the Error_Envelope, consistent with Phase 5 tenant isolation.
9. THE Aggregate_Score of an Evaluation_Run SHALL equal the aggregation of the per-item Item_Scores recorded for that Evaluation_Run.

### Requirement 7: Instrumentation of the LLM Path and API Wiring

**User Story:** As a developer, I want usage capture and the new endpoints wired through the
existing seams, so that observability is added without breaking the LLM_Provider contract or the
keyless promise.

#### Acceptance Criteria

1. THE Instrumented_Provider SHALL implement the existing LLM_Provider interface, exposing the same `generate(prompt) -> GenerationResult` contract as the provider it wraps.
2. WHEN the Instrumented_Provider handles a generate call, THE Instrumented_Provider SHALL delegate generation to the wrapped LLM_Provider and SHALL forward the resulting usage data to the Usage_Sink.
3. THE Composition_Root SHALL wire the Instrumented_Provider, the Usage_Sink, the Tracing_Exporter, the Cost_Model, the Prompt_Registry, the Guardrail_Pipeline, and the Evaluation_Framework, and SHALL be the only place their concrete implementations are named.
4. THE API_Service SHALL expose the analytics, prompt-registry, guardrail-configuration, and evaluation endpoints through the existing FastAPI application using the existing Error_Envelope.
5. THE API_Service SHALL apply the existing Phase 5 current-principal dependency and the existing require_permission authorization dependency to every Phase 6 endpoint.
6. WHEN a Phase 6 endpoint creates or reads an observability resource, THE API_Service SHALL scope the operation to the requesting Principal's Org_Id, consistent with Phase 5 tenant isolation.
7. IF the Usage_Sink fails to record usage for a call, THEN THE Instrumented_Provider SHALL still return the wrapped provider's GenerationResult so that usage capture never changes the result of a generation.

### Requirement 8: Observability Persistence and Additive Migrations

**User Story:** As a developer, I want usage, prompt, and evaluation data persisted with tenant
scoping, so that observability state is durable without disrupting prior phases.

#### Acceptance Criteria

1. THE Observability_Layer SHALL add new database migrations, applied through the existing Migration_Runner, that create tables for Usage_Records, Prompt_Templates and Prompt_Versions, and Evaluation_Datasets, Evaluation_Items, Evaluation_Runs, and per-item Evaluation results.
2. THE Observability_Layer SHALL include an Org_Id column with a foreign key to the Organizations table on every table it adds.
3. THE Observability_Layer SHALL define a foreign key from each Prompt_Version to its parent Prompt_Template, from each Evaluation_Item to its parent Evaluation_Dataset, and from each per-item evaluation result to its parent Evaluation_Run.
4. WHEN the Phase 6 migrations run through the existing Migration_Runner, THE Database SHALL apply them additively without dropping or altering the meaning of any column created by a prior phase.
5. IF a Phase 6 migration fails, THEN THE Migration_Runner SHALL halt on the failing migration and report the failing migration identifier, consistent with the existing runner behavior.
6. THE Observability_Layer SHALL enforce a uniqueness constraint on (Prompt_Template, version number) so that no two Prompt_Versions of the same Prompt_Template share a version number.

### Requirement 9: Reuse of Existing Platform Seams

**User Story:** As a developer, I want the observability layer to reuse the existing platform
seams, so that behavior stays consistent and no prior-phase component is reimplemented.

#### Acceptance Criteria

1. THE Observability_Layer SHALL consume the existing Trace_Recorder and Trace for tracing export and SHALL NOT reimplement trace recording.
2. THE Observability_Layer SHALL instrument the existing LLM_Provider seam through the Instrumented_Provider and SHALL NOT modify or replace the LLM_Provider interface contract.
3. THE Observability_Layer SHALL reuse the existing Phase 5 Principal, tenancy enforcement, and RBAC_Policy for authentication, tenant scoping, and authorization and SHALL NOT introduce a separate access-control mechanism.
4. THE Observability_Layer SHALL expose all Phase 6 endpoints through the existing API_Service and SHALL reuse the existing Error_Envelope for every response.
5. THE Observability_Layer SHALL source all settings and secrets, including the Tracing_Credential and any Cost_Model rates, through the existing Configuration_Manager as environment variables and secrets, and SHALL NOT introduce a separate configuration mechanism.
6. THE Observability_Layer SHALL persist all observability state in the existing Postgres Database using the existing Migration_Runner and SHALL NOT introduce a separate persistence mechanism.
7. THE Observability_Layer SHALL wire the Tracing_Exporter, Usage_Recorder, Cost_Model, Analytics_Service, Prompt_Registry, Guardrail_Pipeline, and Evaluation_Framework through the existing Composition_Root and SHALL NOT reimplement the existing RAG, agentic, multi-agent, or enterprise components.

### Requirement 10: Secure-by-Default Configuration and Tenant Isolation

**User Story:** As a security-conscious operator, I want every external observability credential
optional and every observability record isolated by tenant, so that the platform is safe by
default.

#### Acceptance Criteria

1. THE Configuration_Manager SHALL treat the Tracing_Credential and every other external observability credential as optional and SHALL supply each as a `SecretStr` so that no secret value appears in logs, `repr`, or serialized output.
2. WHERE no external observability credential is configured, THE Observability_Layer SHALL boot and operate using the NoOp_Tracing_Exporter, the Fallback_Provider, deterministic default Guardrails, and deterministic Evaluators, preserving Keyless_Mode.
3. THE Observability_Layer SHALL enforce tenant scoping on every Usage_Record, Prompt_Template, Prompt_Version, Evaluation_Dataset, and Evaluation_Run at the data-access layer by constraining every query and mutation by Org_Id, independently of any check performed in a request handler.
4. IF a Principal requests or attempts to mutate an observability resource whose Org_Id differs from the Principal's Org_Id, THEN THE Observability_Layer SHALL deny access by returning HTTP status 404 using the Error_Envelope, consistent with Phase 5.
5. THE Observability_Layer SHALL ensure that no Usage_Report, Prompt_Registry response, or Evaluation_Framework response returned to a Principal includes any resource whose Org_Id differs from the Principal's Org_Id.

### Requirement 11: Keyless Runnability and Deterministic Testing

**User Story:** As a developer, I want the observability layer runnable and testable with no
external credentials, so that I can verify tracing, usage, prompts, guardrails, and evaluation
locally and deterministically.

#### Acceptance Criteria

1. WHERE no external credential is configured, THE Observability_Layer SHALL run the full Phase 6 test suite deterministically using the NoOp_Tracing_Exporter, the Fallback_Provider, deterministic default Guardrails, and deterministic Evaluators.
2. THE Observability_Layer SHALL provide an automated test verifying that the active Tracing_Exporter makes no external call when no Tracing_Credential is configured.
3. THE Observability_Layer SHALL provide an automated test verifying that, for an Organization, the total tokens and total Cost reported by the Analytics_Service equal the sum of that Organization's persisted Usage_Records.
4. THE Observability_Layer SHALL provide an automated test verifying that a Usage_Report for one Organization never includes any Usage_Record of another Organization.
5. THE Observability_Layer SHALL provide an automated test verifying that Prompt_Versions are immutable and that their version numbers increase monotonically and contiguously per Prompt_Template.
6. THE Observability_Layer SHALL provide an automated test verifying that a blocking Guardrail prevents the downstream LLM_Provider, agent, or multi-agent invocation.
7. THE Observability_Layer SHALL provide an automated test verifying that an Evaluation_Run's Aggregate_Score equals the aggregation of its per-item Item_Scores.

### Requirement 12: Documented Design Decisions

**User Story:** As a developer learning the stack, I want the observability layer's design
decisions documented, so that I understand why it is built this way and how to extend it.

#### Acceptance Criteria

1. THE Observability_Layer SHALL document the rationale for each major architectural decision of the observability layer in a written record within the repository.
2. THE Observability_Layer SHALL document how a new Tracing_Exporter, Cost_Model, Guardrail, and Evaluator is added behind its interface through the Composition_Root without modifying core flows.
3. THE Observability_Layer SHALL document how the Instrumented_Provider captures usage without breaking the LLM_Provider contract or the keyless promise.
4. THE Observability_Layer SHALL document how tenant isolation is enforced for observability resources at the data-access layer, consistent with Phase 5.
