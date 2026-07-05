# Implementation Plan: AgentForge Production Observability (Phase 6)

## Overview

This plan converts the Phase 6 design into an ordered, incremental, test-driven coding
sequence. Every task builds on the previous one — settings + observability domain models
+ base interfaces first, then the pure/leaf seams (`Cost_Model`, `Tracing_Exporter`),
then the usage-instrumentation core (`Usage_Sink`/`Usage_Store`, `Instrumented_Provider`,
`Usage_Recorder`), then the org-scoped `Analytics_Service` + `Pg_Usage_Store` + migration
`0008`, then the `Prompt_Registry` + migration `0009`, then the `Guardrail_Pipeline`,
then the `Evaluation_Framework` + migration `0010`, then the composition-root wiring that
re-wraps the LLM provider with the `Instrumented_Provider` and composes every seam, then
the API schemas + four new routers + the guardrail wrapping of the existing entry points,
then the app wiring in `main.py`, and finally the design-decisions doc — with everything
wired together so no code is orphaned.

The whole layer **reuses, never reimplements** the existing Phase 1–5 seams: the async
FastAPI `API_Service` + uniform `AppError` error envelope (`api/errors.py`), the typed
request/response schemas (`api/schemas.py`), `Settings` + `load_settings`
(`config/settings.py`), the composition root (`config/container.py`) + `main.py`, Postgres
+ pgvector + the versioned migration runner (`db/migrations.py`), Redis, the pluggable
`LLM_Provider` seam (`llm/base.py`) with the deterministic keyless `Fallback_Provider`
(`llm/fallback_provider.py`), the `Trace_Recorder` + `Trace` (`tracing/base.py`) consumed
(not reimplemented) by the exporter, and the Phase 5 enterprise layer — the `Principal`,
`get_current_principal` + `require_permission` dependencies (`api/deps.py`), the static
`RBAC_Policy` (`enterprise/rbac.py`), and the request-scoped tenancy context
(`enterprise/tenancy.py`). New code lives under `src/agentforge/observability/`, four new
routers under `src/agentforge/api/routers/`, and three additive SQL migrations (`0008`,
`0009`, `0010`).

**Keyless-first, deterministic testing.** All 10 correctness properties from the design
are implemented as **Hypothesis** property tests (minimum 100 iterations each, one test
per property, each tagged `Feature: agentforge-observability, Property {n}: {text}`),
placed next to their implementation area under `tests/property/`. Unit tests cover error
branches and shape guarantees; integration tests marked `@pytest.mark.integration` cover
the real Postgres migration/round-trip paths. The default lane runs KEYLESS and
DETERMINISTIC with **no** `Tracing_Credential` and **no** external LLM credential:
`settings.active_tracing_exporter() == "noop"`, the wired provider is the
`Fallback_Provider` wrapped by the `Instrumented_Provider`, the `Default_Cost_Model` uses
its deterministic default rate, the default guardrails are pure functions of the content,
the evaluators are pure functions of `(input, expected, actual)`, and usage/prompt/
evaluation state uses the in-memory stores.

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Top-level tasks are never optional.
- Each task references the specific requirements and design components it implements.

## Tasks

- [x] 1. Extend `Settings`, scaffold the `observability/` package with domain models, base interfaces, and stubs
  - Extend `config/settings.py` `Settings` with the Phase 6 fields (all optional /
    defaulted / bounded so keyless boot is preserved): `langsmith_api_key: SecretStr |
    None = None` (the `Tracing_Credential`), `langsmith_project: str = "agentforge"`,
    `tracing_export_enabled: bool = True`, `cost_default_prompt_per_1k: str = "0.0"`,
    `cost_default_completion_per_1k: str = "0.0"`, `cost_rate_table_json: str | None =
    None`, `guardrail_max_input_chars: int = 8000`, `guardrail_blocklist_json: str | None
    = None`.
  - Add `Settings.active_tracing_exporter() -> str` returning `"langsmith"` iff
    `tracing_export_enabled and langsmith_api_key is not None`, else `"noop"`, so no
    external tracer is constructed on the keyless path.
  - Add the new env-var names to `.env.example` with commented-out sample values so
    keyless boot remains the default.
  - Create the `src/agentforge/observability/` package with `__init__.py` and the stubbed
    modules matching the design's Repository/Module Layout: `models.py`,
    `tracing_exporter.py`, `cost.py`, `analytics.py`, `usage/` (`base.py`,
    `instrumented_provider.py`, `recorder.py`, `sink.py`, `store.py`), `prompt_registry/`
    (`base.py`, `registry.py`, `store.py`), `guardrails/` (`base.py`, `defaults.py`), and
    `evaluation/` (`base.py`, `framework.py`, `evaluators.py`, `store.py`).
  - Implement `observability/models.py` domain dataclasses: `Token_Count` (frozen, with
    `total` property `== prompt + completion`), `Usage_Record`, `Breakdown_Entry`,
    `Usage_Report`, `Prompt_Template`, `Prompt_Version` (frozen), `Evaluation_Dataset`,
    `Evaluation_Item`, `Evaluation_Result`, `Evaluation_Run` — plain, framework-agnostic,
    `Cost` as `Decimal`, `org_id` on every persisted record.
  - Declare the abstract seams in the various `base.py` modules: `Tracing_Exporter`,
    `Usage_Sink`, `Usage_Store`, `Cost_Model`, `Prompt_Store`, `Guardrail` +
    `Guardrail_Decision` enum + `Guardrail_Result`, `Evaluator`, `Evaluation_Store`.
  - _Requirements: 8.2, 9.5, 9.6, 9.7, 10.1, 10.2, 2.7_
  - _Design: `Settings` additions, Repository/Module Layout, Observability domain models
    (`observability/models.py`), Components and Interfaces (ABCs)_

  - [x]* 1.1 Write a smoke test for the package layout, ABC abstractness, and settings defaults
    - Assert every `observability/*` submodule imports cleanly; that `Tracing_Exporter`,
      `Usage_Sink`, `Usage_Store`, `Cost_Model`, `Prompt_Store`, `Guardrail`,
      `Evaluator`, and `Evaluation_Store` are abstract (cannot be instantiated); that
      `Token_Count(p, c).total == p + c`; and that `Settings()` in the local profile with
      no env vars returns `langsmith_api_key is None` and
      `active_tracing_exporter() == "noop"`; assert `langsmith_api_key` is redacted from
      `repr`/`model_dump`.
    - _Requirements: 9.5, 10.1, 10.2, 2.7_

- [x] 2. Implement the `Cost_Model` (`observability/cost.py`)
  - Implement `Default_Cost_Model(rates, default_rate)`: a config-driven per-1K-token
    rate table with `cost_for(provider, model, tokens) -> Decimal` that applies the
    default rate for any unlisted `(provider, model)` pair and computes
    `prompt/1000 * prompt_per_1k + completion/1000 * completion_per_1k` using `Decimal`.
  - Provide a builder-side helper to parse `cost_rate_table_json` and the default
    per-1K rates from `Settings` into the rate table (parsing lives with the model but is
    invoked from the container in task 10).
  - _Requirements: 2.2, 2.5, 2.6_
  - _Design: `Cost_Model` (`observability/cost.py`)_

  - [x]* 2.1 Write property test for `Cost_Model` totality with a default rate
    - **Property 5: Cost_Model is total with a default rate**
    - **Validates: Requirements 2.5**
    - Hypothesis over arbitrary provider/model strings (both in and absent from the rate
      table) and `Token_Count`s at `0` and large values: assert `cost_for(...)` returns a
      defined, non-negative `Decimal` without raising, and that the configured default
      rate is applied when the pair is unlisted.

  - [x]* 2.2 Write unit tests for cost arithmetic
    - Cover a listed pair using its specific rate, an unlisted pair falling back to the
      default rate, the keyless `0.0` default producing `Decimal("0")`, and exact
      `Decimal` (no float drift) arithmetic.
    - _Requirements: 2.2, 2.5_

- [x] 3. Implement the `Tracing_Exporter` (`observability/tracing_exporter.py`)
  - Implement `NoOp_Tracing_Exporter` (`name == "noop"`, `export(...)` makes no external
    call and no external side effect) and `LangSmith_Tracing_Exporter(api_key, *,
    project, client=None)` (`name == "langsmith"`) that maps the consumed `Trace` to the
    external run tree, tags it with `org_id`/`user_id` metadata, and wraps the forward in
    a `try/except` that suppresses any exception so export never changes a run's outcome.
  - Consume the existing `Trace` produced by the reused `Trace_Recorder`; do NOT record
    steps or reimplement the recorder.
  - Add `build_tracing_exporter(settings)` selection logic (referenced by the container in
    task 10): `NoOp` when `active_tracing_exporter() == "noop"`, LangSmith-backed
    otherwise.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 9.1_
  - _Design: `Tracing_Exporter` (`observability/tracing_exporter.py`)_

  - [x]* 3.1 Write property test for org/user tagging on export
    - **Property 1: Tracing export tags the trace with org and user**
    - **Validates: Requirements 1.5**
    - Hypothesis over arbitrary `Trace`s, `org_id`, and `user_id` (present or absent),
      using a capturing fake LangSmith client: assert the payload delivered to the
      external destination is tagged with exactly that `org_id` and `user_id`.

  - [x]* 3.2 Write property test for export-never-changes-outcome
    - **Property 2: Trace export never changes a run's outcome**
    - **Validates: Requirements 1.7**
    - Hypothesis over a fake tracer client that raises an arbitrary exception on forward:
      assert `LangSmith_Tracing_Exporter.export(...)` returns normally (failure
      suppressed) and that a captured run result is identical to the result under a
      successful or NoOp export.

  - [x]* 3.3 Write unit tests for selection and the keyless no-call guarantee
    - Assert `build_tracing_exporter` returns `NoOp_Tracing_Exporter` with no credential
      and `LangSmith_Tracing_Exporter` with one; assert `NoOp.export` makes no external
      call via a network-guard spy.
    - _Requirements: 1.2, 1.3, 1.4, 11.2_

- [x] 4. Implement the usage-instrumentation core (`observability/usage/`)
  - [x] 4.1 Implement `InMemory_Usage_Store` and the deterministic token counter
    - Implement `InMemory_Usage_Store` backing the `Usage_Store` ABC with `add(record)`
      and `list_for_org(org_id, *, start, end)`, keying/filtering by `org_id` so
      cross-org reads are structurally empty.
    - Implement `deterministic_token_count(prompt, result) -> Token_Count` as a pure
      function of the request/response text (e.g. whitespace-delimited counts), with
      `total == prompt + completion` by construction.
    - _Requirements: 2.4, 2.7, 10.3_
    - _Design: `Usage_Sink, Usage_Recorder, Usage_Store`, Instrumented_Provider token
      count_

  - [x] 4.2 Implement the `Usage_Recorder` and `Recording_Usage_Sink` / `NoOp_Usage_Sink`
    - `Usage_Recorder(store, cost_model)` builds a `Usage_Record` (computing `cost` via
      `Cost_Model.cost_for`) and persists it scoped to `org_id`.
    - `Recording_Usage_Sink` adapts the `Usage_Recorder` to the `Usage_Sink` seam;
      `NoOp_Usage_Sink` is the inert double for tests that don't assert on usage.
    - _Requirements: 2.1, 2.2, 2.3_
    - _Design: `Usage_Recorder`, `Recording_Usage_Sink`_

  - [x] 4.3 Implement the `Instrumented_Provider` decorator
    - Implement `Instrumented_Provider(wrapped, sink, *, token_counter=None)` that
      implements `LLM_Provider`, exposes the wrapped provider's `name`, delegates
      `generate(prompt)` to the wrapped provider **first**, then emits exactly one usage
      record to the `Usage_Sink` inside a guard that swallows any exception so the wrapped
      result is always returned unchanged; read `org_id`/`user_id` from the request-scoped
      tenancy context without widening the `LLM_Provider` contract.
    - _Requirements: 2.1, 7.1, 7.2, 7.7, 9.2_
    - _Design: `Instrumented_Provider` (`observability/usage/instrumented_provider.py`)_

  - [x]* 4.4 Write property test for the transparent, safe decorator
    - **Property 3: Instrumented_Provider is a transparent, safe decorator**
    - **Validates: Requirements 2.1, 7.1, 7.2, 7.7**
    - Hypothesis over arbitrary wrapped providers (fakes) and prompts: assert
      `generate(prompt)` returns a `GenerationResult` equal to the wrapped provider's and
      exposes its `name`; that the wrapped provider is called exactly once and the sink
      receives exactly one emission; and that for any sink that raises, `generate` still
      returns the wrapped result unchanged.

  - [x]* 4.5 Write property test for `Usage_Record` correctness, determinism, and token invariant
    - **Property 4: Usage_Record correctness, determinism, and token invariant**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.7**
    - Hypothesis over prompts (unicode, whitespace, empty) with the `Fallback_Provider`
      and a given acting `org_id`/`user_id`: assert the emitted `Usage_Record` captures
      that `org_id`, `user_id`, provider, and model; that `total_tokens == prompt_tokens
      + completion_tokens`; that `cost == Cost_Model.cost_for(provider, model, tokens)`;
      and that repeating the identical call yields an identical record in its token fields
      and cost.

  - [x]* 4.6 Write unit tests for the emission-failure path and context attribution
    - Cover a sink that raises (result still returned), a missing tenancy context, and
      the exactly-once delegation/emission counts.
    - _Requirements: 2.3, 7.7_

- [x] 5. Implement the `Analytics_Service`, `Pg_Usage_Store`, and migration `0008`
  - [x] 5.1 Implement `Analytics_Service` (`observability/analytics.py`)
    - `usage_report(org_id, *, start, end)` reads only `store.list_for_org(org_id, ...)`
      and returns a `Usage_Report` whose `total_tokens`/`total_cost` are the sums over
      those records and whose `by_provider`/`by_model`/`by_user` breakdowns partition the
      same record set (each breakdown's tokens sum to the report total).
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.7_
    - _Design: `Analytics_Service` (`observability/analytics.py`)_

  - [x] 5.2 Implement `Pg_Usage_Store` (`observability/usage/store.py`)
    - Use sync SQLAlchemy mirroring the Phase 5 `Pg_*` stores; `add` and `list_for_org`
      both constrain SQL by `WHERE org_id = :org_id` (and the time range) so cross-org
      rows are never returned.
    - _Requirements: 2.3, 3.3, 9.3, 9.6, 10.3_
    - _Design: `Pg_Usage_Store`_

  - [x] 5.3 Add migration `migrations/0008_create_usage_records.sql`
    - Create `usage_records` with `id`, `org_id UUID NOT NULL REFERENCES organizations(id)
      ON DELETE CASCADE`, `user_id UUID REFERENCES users(id) ON DELETE SET NULL`,
      `provider`, `model`, `prompt_tokens`/`completion_tokens` (`CHECK >= 0`),
      `total_tokens` (`CHECK total_tokens = prompt_tokens + completion_tokens`),
      `cost NUMERIC(20,8) NOT NULL`, `created_at`; add
      `usage_records_org_time_idx (org_id, created_at)`. Use `CREATE ... IF NOT EXISTS`.
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 2.7_
    - _Design: `0008_create_usage_records.sql`_

  - [x]* 5.4 Write property test for analytics aggregation and tenant isolation
    - **Property 6: Analytics aggregation partitions the org's records and isolates tenants**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.7, 10.5, 11.3, 11.4**
    - Hypothesis over multi-org `Usage_Record` sets with overlapping providers/models/
      users and empty ranges: assert org `A`'s report `total_tokens`/`total_cost` equal
      the sums of exactly `A`'s in-range records; the provider-breakdown token sum and the
      model-breakdown token sum each equal the report total; and no `org_id != A` record
      contributes to `A`'s report.

  - [x]* 5.5 Write an integration test applying migration `0008` and round-tripping usage (`@pytest.mark.integration`)
    - Apply `0008` through the existing runner; assert it reaches `schema_migrations`; the
      `total = prompt + completion` CHECK rejects an inconsistent row; and `Pg_Usage_Store`
      round-trips under `org_id` scoping with cross-org isolation.
    - _Requirements: 8.1, 8.4, 8.5, 2.7_

- [x] 6. Implement the `Prompt_Registry`, its stores, and migration `0009`
  - [x] 6.1 Implement `InMemory_Prompt_Store` and `Pg_Prompt_Store` (`observability/prompt_registry/store.py`)
    - Back the `Prompt_Store` ABC: `next_version_number(org_id, name)` (`max+1` or `1`),
      `add_version` (append-only), `get_version`, `get_latest`, `list_versions`
      (ascending). Both implementations constrain every query by `org_id`; the Postgres
      version relies on the `UNIQUE (template_id, version)` constraint from `0009`.
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 9.3, 9.6, 10.3_
    - _Design: `Prompt_Store` (ABC + stores)_

  - [x] 6.2 Implement `Prompt_Registry` (`observability/prompt_registry/registry.py`)
    - `create_version(org_id, name, body, variables)` appends `max+1`/`1`;
      `get(org_id, name, version=None)` returns the latest or a specific version and
      raises `AppError("not_found", 404)` when absent (cross-tenant included);
      `render(version, values)` substitutes every declared variable, raising
      `AppError("missing_variable", 400, {"missing": [...]})` when any is omitted.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_
    - _Design: `Prompt_Registry` (`observability/prompt_registry/registry.py`)_

  - [x] 6.3 Add migration `migrations/0009_create_prompt_registry.sql`
    - Create `prompt_templates` (`org_id` FK, `UNIQUE (org_id, name)`) and
      `prompt_versions` (`org_id` FK, `template_id` FK to `prompt_templates` `ON DELETE
      CASCADE`, `version CHECK >= 1`, `body`, `variables JSONB`, `UNIQUE (template_id,
      version)`) with a `(template_id, version)` index. Use `CREATE ... IF NOT EXISTS`.
    - _Requirements: 8.1, 8.2, 8.3, 8.6, 4.2_
    - _Design: `0009_create_prompt_registry.sql`_

  - [x]* 6.4 Write property test for prompt versioning and rendering
    - **Property 7: Prompt versioning is monotonic, contiguous, immutable; rendering is total-or-errors**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 11.5**
    - Hypothesis over create sequences of length `0..N` with interleaved template names:
      assert version numbers form exactly `{1..N}` in creation order with no gaps/dupes;
      `get_latest` returns the highest; `get(name, k)` returns the k-th; `list_versions`
      is ascending; no prior version's `body`/`variables` changes; and rendering
      substitutes all declared variables when supplied but raises
      `AppError("missing_variable", 400)` (listing the missing names) when any is omitted.

  - [x]* 6.5 Write unit tests for render error branches and cross-tenant 404
    - Cover missing-one, missing-several, extra-values-ignored rendering, and a
      cross-org `get` returning 404.
    - _Requirements: 4.7, 4.8_

  - [x]* 6.6 Write an integration test applying migration `0009` (`@pytest.mark.integration`)
    - Apply `0009`; assert `schema_migrations` advances; the `UNIQUE (template_id,
      version)` constraint rejects a duplicate-version insert; `Pg_Prompt_Store`
      round-trips under `org_id` scoping.
    - _Requirements: 8.1, 8.4, 8.6_

- [x] 7. Implement the `Guardrail_Pipeline` and default guardrails (`observability/guardrails/`)
  - [x] 7.1 Implement `Guardrail`, `Guardrail_Decision`, `Guardrail_Result`, `Guardrail_Pipeline`, and an input-guard helper
    - `Guardrail_Pipeline(guardrails)` evaluates in stable configured order, accumulates
      flags, and short-circuits on the first `BLOCK`, returning `ALLOW` (all allow),
      `ALLOW` with flags (some flag, none block), or `BLOCK` with reason.
    - Add a reusable `apply_input_guardrail(pipeline, content, downstream)` helper that
      raises `AppError("guardrail_blocked", 400, {"reason": ...})` and does NOT invoke
      `downstream` when the input pipeline blocks; entry points reuse this helper (task 14).
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.8_
    - _Design: `Guardrail + Guardrail_Pipeline` (`observability/guardrails/`)_

  - [x] 7.2 Implement the deterministic default guardrails (`observability/guardrails/defaults.py`)
    - Implement non-empty, max-input-length (from `guardrail_max_input_chars`), and static
      blocklist (from `guardrail_blocklist_json`) guardrails whose `check(content)` is a
      pure function of the content; provide the default pipeline factory used by the
      container in task 10.
    - _Requirements: 5.7, 10.2_
    - _Design: default guardrails (`observability/guardrails/defaults.py`)_

  - [x]* 7.3 Write property test for guardrail ordering, short-circuit, and downstream prevention
    - **Property 8: Guardrail pipeline order, short-circuit, and downstream prevention**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 11.6**
    - Hypothesis over guardrail orderings (allow-only, flag-only, block-at-position-`i`,
      mixed) and arbitrary content: assert evaluation order; `ALLOW` when all allow;
      `ALLOW` with all accumulated flags when some flag and none block; `BLOCK` with reason
      and no guardrail evaluated after the first block; determinism of the default
      pipeline; and — via `apply_input_guardrail` with a call-counting fake downstream —
      that a blocking input invokes the downstream zero times.

  - [x]* 7.4 Write unit tests for the default guardrails and flag accumulation
    - Cover empty-input block, over-length block, blocklist term block, clean-content
      allow, and multi-guardrail flag accumulation.
    - _Requirements: 5.5, 5.7_

- [x] 8. Implement the `Evaluation_Framework`, evaluators, stores, and migration `0010`
  - [x] 8.1 Implement `InMemory_Evaluation_Store` and `Pg_Evaluation_Store` (`observability/evaluation/store.py`)
    - Back the `Evaluation_Store` ABC: `add_dataset`, `get_dataset(org_id, id)`,
      `add_item`, `list_items(org_id, dataset_id)`, `add_run`, `get_run(org_id, id)`,
      `list_datasets(org_id)`. Every method constrains by `org_id`; child rows carry FKs
      to their parents.
    - _Requirements: 6.1, 6.5, 6.8, 9.3, 9.6, 10.3_
    - _Design: `Evaluation_Store` (ABC + stores)_

  - [x] 8.2 Implement the deterministic evaluators (`observability/evaluation/evaluators.py`)
    - Implement `Exact_Match`, `Contains`, and a `Heuristic` scorer, each with
      `score(*, input, expected, actual) -> float` as a pure function of its inputs.
    - _Requirements: 6.3, 6.7_
    - _Design: evaluators (`observability/evaluation/evaluators.py`)_

  - [x] 8.3 Implement `Evaluation_Framework` (`observability/evaluation/framework.py`)
    - `run(org_id, dataset_id, evaluator_names)` loads the org-scoped dataset (404 if
      absent), produces each item's actual output via the injected keyless
      `pipeline_runner` (RAG/agent on the `Fallback_Provider`), scores each item with each
      named evaluator, computes the `Aggregate_Score` as the mean of per-item scores, and
      persists the `Evaluation_Run` with its results scoped to `org_id`.
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 6.9_
    - _Design: `Evaluation_Framework` (`observability/evaluation/framework.py`)_

  - [x] 8.4 Add migration `migrations/0010_create_evaluations.sql`
    - Create `evaluation_datasets` (`org_id` FK, `UNIQUE (org_id, name)`),
      `evaluation_items` (`org_id` FK, `dataset_id` FK `ON DELETE CASCADE`),
      `evaluation_runs` (`org_id` FK, `dataset_id` FK, `aggregate_score`), and
      `evaluation_results` (`org_id` FK, `run_id` FK `ON DELETE CASCADE`, `item_id` FK,
      `evaluator`, `score`) with the design's indexes. Use `CREATE ... IF NOT EXISTS`.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
    - _Design: `0010_create_evaluations.sql`_

  - [x]* 8.5 Write property test for evaluation scoring and aggregation determinism
    - **Property 9: Evaluation scoring and aggregation are deterministic and consistent**
    - **Validates: Requirements 6.3, 6.4, 6.6, 6.9, 11.7**
    - Hypothesis over datasets (with `expected` present and absent) and evaluator sets on
      the keyless path with repeated identical runs: assert each `Item_Score` is a pure
      function of `(input, expected, actual)` (repeated runs identical), and the persisted
      `Aggregate_Score` equals the mean of the run's persisted per-item scores.

  - [x]* 8.6 Write property test for observability tenant isolation across every resource type
    - **Property 10: Observability tenant isolation across every resource type**
    - **Validates: Requirements 2.3, 3.3, 4.8, 6.1, 6.5, 6.8, 7.6, 10.3, 10.4, 10.5**
    - Hypothesis over two distinct orgs `A`, `B` and a resource kind drawn from
      `{Usage_Record, Prompt_Template/Version, Evaluation_Dataset, Evaluation_Run}` across
      the in-memory `Usage_Store`/`Prompt_Store`/`Evaluation_Store`: create the resource
      under `A`, then assert every read/mutate from a `Principal` in `B` returns
      `AppError("not_found", 404)` (or empty for lists) and no response to `B` includes an
      `A`-owned resource — enforced at the store layer independently of any handler check.

  - [x]* 8.7 Write an integration test applying migration `0010` (`@pytest.mark.integration`)
    - Apply `0010`; assert `schema_migrations` advances; child FKs and `ON DELETE CASCADE`
      from `evaluation_runs`/`evaluation_datasets` behave; `Pg_Evaluation_Store`
      round-trips under `org_id` scoping.
    - _Requirements: 8.1, 8.3, 8.4_

- [x] 9. Checkpoint — observability core logic
  - Ensure the observability-core property + unit suite (Properties 3–10 plus their unit
    tests) is green on the keyless path with the in-memory stores, and that the three
    migrations parse. Ensure all tests pass, ask the user if questions arise.

- [x] 10. Wire the observability layer through the composition root (`config/container.py` + `api/deps.py`)
  - Add per-seam builders `build_tracing_exporter(settings)`, `build_cost_model(settings)`
    (parsing the rate table + defaults), `build_usage_recorder(settings, store,
    cost_model)`, `build_prompt_registry(settings, store)`, `build_guardrail_pipeline(
    settings)`, and `build_evaluation_framework(settings, store, pipeline_runner,
    evaluators)`; each selects the Postgres store in production and the in-memory store in
    local/keyless.
  - Add `build_observability_context(settings, **overrides)` returning an
    `ObservabilityContext` (exporter, usage recorder/sink, cost model, analytics, prompt
    registry, guardrail pipeline, evaluation framework) and **re-wrap** the LLM provider in
    `build_app_context` with the `Instrumented_Provider` so every downstream RAG/agent/
    multi-agent flow emits usage transparently; keep `config/container.py` the ONLY place
    concrete observability implementations are named.
  - Extend `api/deps.py` with `get_observability_context` + per-seam accessors reading
    `app.state.observability_context`.
  - _Requirements: 1.2, 1.4, 2.6, 5.8, 6.7, 7.3, 9.7, 10.2_
  - _Design: Composition root wiring, Layering and Dependency Rule_

  - [x]* 10.1 Write unit tests for the composition-root selection and provider re-wrap
    - Assert no credential → `NoOp_Tracing_Exporter` and in-memory stores; a
      `Tracing_Credential` → `LangSmith_Tracing_Exporter`; the app context's provider is
      an `Instrumented_Provider` wrapping the `Fallback_Provider`; and that only
      `config/container.py` names concrete observability implementations.
    - _Requirements: 1.2, 1.4, 7.3, 9.7, 10.2_

- [x] 11. Extend `api/schemas.py` with the Phase 6 request/response models
  - Add `UsageReportResponse` (totals + `by_provider`/`by_model`/`by_user` breakdown
    lists), `CreatePromptVersionRequest`, `PromptVersionResponse`, `RenderPromptRequest`/
    `RenderPromptResponse`, `GuardrailConfigResponse`, `GuardrailEvaluateRequest`/
    `GuardrailEvaluateResponse`, `CreateDatasetRequest`, `EvaluationRunRequest`, and
    `EvaluationRunResponse` (aggregate + per-item scores); all errors render through the
    existing envelope.
  - _Requirements: 7.4, 9.4_
  - _Design: API request/response schemas (`api/schemas.py`, extended)_

- [x] 12. Implement the `analytics` router (`api/routers/analytics.py`)
  - Add `GET /analytics/usage` with `Depends(require_permission(read))`, query params
    `start`/`end`, returning the `Usage_Report` for `principal.org_id` via the
    `Analytics_Service`; unauthenticated → 401, missing `read` → 403; render errors
    through the existing envelope.
  - _Requirements: 3.1, 3.5, 3.6, 7.4, 7.5, 7.6, 9.3, 9.4_
  - _Design: API endpoints (analytics row), Applying auth + tenancy_

  - [x]* 12.1 Write unit tests for the analytics endpoint auth surface
    - Cover no-credential → 401, authenticated-without-`read` → 403, and a `read`
      principal receiving a report scoped to its own org only.
    - _Requirements: 3.5, 3.6_

- [x] 13. Implement the `prompts` router (`api/routers/prompts.py`)
  - Add `POST /prompts` (`ingest_documents`, create a `Prompt_Version`),
    `GET /prompts` (`read`, list template names), `GET /prompts/{name}/versions`
    (`read`, ascending version numbers), `GET /prompts/{name}` (`read`, latest or
    `?version=N`), and `POST /prompts/{name}/render` (`read`, missing variable → 400);
    thread `principal.org_id` into the registry so cross-tenant lookups return 404.
  - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 7.4, 7.5, 7.6, 9.3, 9.4_
  - _Design: API endpoints (prompts rows)_

  - [x]* 13.1 Write unit tests for the prompts router
    - Cover create-then-get-latest, get-specific-version, ascending version list,
      render success, render missing-variable → 400, and cross-org get → 404.
    - _Requirements: 4.5, 4.7, 4.8_

- [x] 14. Implement the `guardrails` router and wrap the existing entry points
  - [x] 14.1 Implement `api/routers/guardrails.py`
    - Add `GET /guardrails/config` (`read`, ordered active guardrail names + kinds) and
      `POST /guardrails/evaluate` (`run_agents`, returns allow/flag/block) rendered
      through the existing envelope.
    - _Requirements: 5.1, 7.4, 7.5, 9.4_
    - _Design: API endpoints (guardrails rows)_

  - [x] 14.2 Wrap the existing query / agent / multi-agent entry points with the guardrail pipeline
    - In the existing `query`, `agent`, and `multi_agent` handlers, run the input pipeline
      via `apply_input_guardrail(...)` **before** invoking the downstream LLM/agent/
      multi-agent orchestrator (a `BLOCK` raises `AppError("guardrail_blocked", 400)` and
      the downstream is never called), and run the output pipeline on the produced result,
      attaching flags to the response; add no bespoke logic to the orchestrators
      themselves.
    - _Requirements: 5.4, 5.6, 5.8_
    - _Design: Application at entry points, High-Level Architecture (guardrail-wrapped
      routers)_

  - [x]* 14.3 Write unit tests for entry-point guardrail application
    - Cover a blocked input at each of the three entry points (downstream not invoked,
      400 `guardrail_blocked`), a flagged input proceeding with annotations, and the
      `/guardrails/evaluate` allow/flag/block responses.
    - _Requirements: 5.4, 5.6_

- [x] 15. Implement the `evaluations` router (`api/routers/evaluations.py`)
  - Add `POST /evaluations/datasets` (`run_agents`, create a dataset + items scoped to the
    org), `GET /evaluations/datasets` (`read`, list the org's datasets),
    `POST /evaluations/runs` (`run_agents`, execute a run over a dataset with named
    evaluators), and `GET /evaluations/runs/{id}` (`read`, aggregate + per-item scores);
    thread `principal.org_id` so cross-tenant access returns 404.
  - _Requirements: 6.1, 6.2, 6.5, 6.8, 6.9, 7.4, 7.5, 7.6, 9.3, 9.4_
  - _Design: API endpoints (evaluations rows)_

  - [x]* 15.1 Write unit tests for the evaluations router
    - Cover create-dataset, list-datasets, run-then-get (aggregate == mean of per-item
      scores), and cross-org dataset/run access → 404.
    - _Requirements: 6.5, 6.8, 6.9_

- [x] 16. Register the new routers and wire the observability context in `main.py`
  - Register `analytics_router`, `prompts_router`, `guardrails_router`, and
    `evaluations_router` on the FastAPI app factory alongside the existing routers.
  - At startup, build `observability_context = build_observability_context(settings)` and
    assign it to `app.state.observability_context`, honoring any pre-injected override, and
    ensure the LLM provider seen by downstream contexts is the `Instrumented_Provider`.
  - Ensure `from agentforge.main import app` still imports cleanly under the keyless
    default (`active_tracing_exporter() == "noop"`).
  - _Requirements: 7.3, 7.4, 9.4, 9.7, 10.2_
  - _Design: `main.py` wiring, High-Level Architecture_

  - [x]* 16.1 Write a wiring unit test
    - Assert all four new routers are registered, `app.state.observability_context` is
      populated, every Phase 6 route declares `get_current_principal` +
      `require_permission`, and the keyless boot uses the `NoOp_Tracing_Exporter`.
    - _Requirements: 7.5, 9.3, 10.2_

- [x] 17. Extend `docs/decisions.md` with the Phase 6 design decisions
  - Append a "Phase 6 — Production Observability" section covering: the decorator over the
    `LLM_Provider` seam for usage capture; the `Tracing_Exporter` as a consumer of the
    existing `Trace` with suppressed failures; immutable, monotonically-versioned prompts
    with the DB uniqueness constraint; the ordered guardrail pipeline with allow/flag/
    block + short-circuit; deterministic evaluation on the keyless `Fallback_Provider`;
    `Decimal` cost + a total `Cost_Model` with a default rate; and tenant isolation at the
    data-access layer (404, never 403).
  - Include the four required extension how-to guides: adding a new `Tracing_Exporter`,
    `Cost_Model`, `Guardrail`, and `Evaluator` behind its interface through the
    composition root without modifying core flows; how the `Instrumented_Provider`
    captures usage without breaking the `LLM_Provider` contract or the keyless promise; and
    how tenant isolation is enforced for observability resources at the data-access layer.
  - _Requirements: 12.1, 12.2, 12.3, 12.4_
  - _Design: Design Decisions & Why_

- [x] 18. Checkpoint — docs + wiring
  - Ensure `docs/decisions.md` renders correctly, `from agentforge.main import app` still
    imports under the keyless default, and the fast (property + unit) suite is green.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Final full-suite keyless checkpoint (leave unchecked for the user)
  - Run the full keyless suite `pytest -m 'not integration' -q`: all 10 Hypothesis
    property tests (>=100 iterations each), all unit tests, and all router tests.
    Environment: no `Tracing_Credential` and no external LLM credential
    (`active_tracing_exporter() == "noop"`, `Fallback_Provider` wrapped by
    `Instrumented_Provider`, `Default_Cost_Model` default rate, default guardrails,
    deterministic evaluators, in-memory usage/prompt/evaluation stores). Only tests marked
    `@pytest.mark.integration` (real Postgres) remain deselected in this lane.
  - Verify every correctness property (1–10) has a passing property test and confirm no
    external credential was required. Report the pass/fail result.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Each task references specific acceptance criteria for traceability
  (`_Requirements: X.Y_`) and the design section it implements (`_Design: <section>_`);
  property sub-tasks additionally reference the design property they validate
  (`**Property N: <text>** ; **Validates: Requirements X.Y**`).
- The 10 Hypothesis property tests are the primary correctness surface for the
  observability core; unit tests cover error branches and shape guarantees; integration
  tests (`@pytest.mark.integration`) exercise the real Postgres migrations/round-trips and
  are excluded from the default keyless lane.
- Structural, configuration, migration-runner, wiring, and documentation criteria
  (exporter selection, `Settings` shape, schema FKs, seam reuse, `docs/decisions.md`) are
  covered by unit / integration / smoke tests rather than property tests, per the design's
  Testing Strategy.
- Everything is KEYLESS + DETERMINISTIC by default: no `Tracing_Credential` and no external
  LLM credential are ever required to run the full Phase 6 property + unit suite.
- Scope is strictly Phase 6: no React frontend, third-party integrations, or cloud
  deployment — this phase ships the APIs and seams that enable them later.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "Settings extension + observability/ package scaffolding with domain models and base ABCs."
    },
    {
      "wave": 2,
      "tasks": ["2", "3"],
      "description": "Cost_Model (Property 5) and Tracing_Exporter (Properties 1, 2) — independent leaf seams, may run in parallel."
    },
    {
      "wave": 3,
      "tasks": ["4"],
      "description": "Usage-instrumentation core: Usage_Store/Sink, Instrumented_Provider, Usage_Recorder (Properties 3, 4)."
    },
    {
      "wave": 4,
      "tasks": ["5", "6"],
      "description": "Analytics + Pg_Usage_Store + migration 0008 (Property 6) and Prompt_Registry + migration 0009 (Property 7) — independent, may run in parallel."
    },
    {
      "wave": 5,
      "tasks": ["7", "8"],
      "description": "Guardrail_Pipeline (Property 8) and Evaluation_Framework + migration 0010 (Properties 9, 10) — independent, may run in parallel."
    },
    {
      "wave": 6,
      "tasks": ["9"],
      "description": "Checkpoint — observability core logic green on the keyless path."
    },
    {
      "wave": 7,
      "tasks": ["10"],
      "description": "Composition-root wiring: per-seam builders + build_observability_context + Instrumented_Provider re-wrap."
    },
    {
      "wave": 8,
      "tasks": ["11"],
      "description": "API request/response schema extensions for the four new routers."
    },
    {
      "wave": 9,
      "tasks": ["12", "13"],
      "description": "analytics router and prompts router — independent, may run in parallel."
    },
    {
      "wave": 10,
      "tasks": ["14", "15"],
      "description": "guardrails router + entry-point wrapping and evaluations router — independent, may run in parallel."
    },
    {
      "wave": 11,
      "tasks": ["16"],
      "description": "Register the four new routers + wire the observability context in main.py."
    },
    {
      "wave": 12,
      "tasks": ["17", "18"],
      "description": "docs/decisions.md extension and docs/wiring checkpoint."
    },
    {
      "wave": 13,
      "tasks": ["19"],
      "description": "Final full-suite keyless checkpoint (left unchecked for the user)."
    }
  ],
  "notes": [
    "Each wave depends on all prior waves; interfaces and domain models precede implementations.",
    "Wave 2 tasks 2 and 3 are independent (both depend only on task 1) and may run in parallel.",
    "Wave 4 tasks 5 and 6 write to different modules/migrations (0008 vs 0009) and may run in parallel.",
    "Wave 5 tasks 7 and 8 write to different modules/migrations (guardrails vs 0010) and may run in parallel.",
    "Wave 9 tasks 12 and 13 and Wave 10 tasks 14 and 15 touch distinct router files and may run in parallel.",
    "Optional (*) test sub-tasks may be deferred without blocking dependent waves.",
    "Property 10 (tenant isolation) attaches to task 8 because by then the usage, prompt, and evaluation stores all exist and it parametrizes across all three.",
    "Property 8's downstream-prevention clause is tested at task 7 via the apply_input_guardrail helper with a call-counting fake, then reused by the real entry points in task 14."
  ]
}
```
