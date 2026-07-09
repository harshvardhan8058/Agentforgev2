# Design Document — Production Hardening

## Overview

This design closes the six production-readiness gaps (B1–B6) found in the AgentForge audit
without adding any product feature, breaking any API, or re-architecting the platform. Every
fix is **root-cause driven**, **minimal**, and **confined to the seams that already exist**:
the composition root (`config/container.py`), the typed `Settings`, the nginx proxy snippet,
the backend `Dockerfile`, the CI workflow, and the committed frontend contract. No service,
router, or store interface changes.

The single most important change (B1) is the **store-selection predicate** in the composition
root. Today ten Domain_Stores are DB-backed *only* when `settings.profile == "production"`, so
the keyless local stack keeps them in process memory and loses data on restart. We introduce an
explicit, keyless-safe persistence selector so the local stack persists to the already-running
Postgres over a **DSN only (no credential)**, while the deterministic keyless unit lane stays
in-memory by default. Every referenced `Pg_*` store already exists, is synchronous-psycopg, takes
only a `database_url`, and maps onto tables created by the existing migrations `0001`–`0011` — so
**no new migration and no new store implementation are required**.

The remaining fixes are localized: correct the nginx SSE proxy directives (B3), install a CPU-only
torch build to shrink the image (B4), remove the stray untracked `Dockerfile.verify` (B5),
regenerate the committed OpenAPI contract and add a keyless drift check (B6), and document the
keyless↔production configuration boundary while confirming the existing production guard (B2).

### Issue → Requirement map

| ID | Issue | Requirements |
|----|-------|--------------|
| B1 | Domain_Stores memory-only under `local` | R1 (primary), R8, R9, R10, R11 |
| B2 | Keyless↔production config boundary | R2 |
| B3 | SSE buffered/stalled through proxy | R3 |
| B4 | Backend image ~17.8 GB (CUDA torch) | R4 |
| B5 | Stray untracked `Dockerfile.verify` | R5 |
| B6 | Committed `openapi.json` stale (missing `GET /integrations/status`) | R6 |
| — | Guardrails (no new feature, arch/keyless/tests/migrations preserved, minimal) | R7–R12 |

## Architecture

The platform layering is unchanged. All fixes land at the edges of the existing architecture:

```mermaid
flowchart TB
    subgraph Proxy["Reverse_Proxy (nginx)"]
        P[proxy_backend.conf<br/>B3: http/1.1 + no-buffer]
    end
    subgraph Backend["Backend_Service (FastAPI / uvicorn)"]
        M[main.lifespan<br/>unchanged wiring order]
        CR[config/container.py<br/>B1: store-selection predicate]
        ST[config/settings.py<br/>B1: use_database flag / B2: prod guard]
        RS[(routers + services + store INTERFACES<br/>UNCHANGED)]
        PG[Pg_* stores  ->  sync psycopg  ->  to_sync_dsn]
    end
    subgraph Data["Running infra (already in compose)"]
        DB[(PostgreSQL + pgvector<br/>migrations 0001-0011)]
        RD[(Redis)]
    end
    Build["Dockerfile / constraints.txt<br/>B4: CPU-only torch"]
    CI[".github/workflows/ci-cd.yml<br/>B4 size gate / B6 contract drift"]
    FE["frontend/openapi.json + schema.d.ts<br/>B6: regenerated"]

    P --> M --> CR --> PG --> DB
    CR --> ST
    RS -. abstract seams only .-> CR
    CI --> Build
    CI --> FE
```

**Key architectural invariant preserved:** `config/container.py` remains the *only* module that
names concrete implementations, and every selection continues to flow through the existing
dependency-injection `build_*` seams (R8.1, R8.2). Routers and services keep seeing abstract
interfaces only.

## Root-Cause Analysis and Chosen Fix (B1–B6)

### B1 — Domain_Stores are memory-only on the local stack (R1, primary)

**Root cause.** Nine builders in `config/container.py` select the `Pg_*` implementation with the
predicate `if settings.profile == "production": ... else: <in-memory>`:

`build_conversation_store`, `build_trace_recorder`, `build_identity_store`,
`build_api_key_store`, `build_usage_store`, `build_prompt_store`, `build_evaluation_store`,
`build_multi_agent_run_store`, `build_integration_connection_store`.

(`build_document_store` is already always DB-backed via `DBDocumentStore`.) Because the
one-command stack runs `PROFILE=local`, all nine fall to the in-memory branch and lose data on
restart, even though a fully-migrated Postgres is running in the same compose network.

The predicate conflates two independent axes:
- **Persistence** — should state live in Postgres or process memory?
- **Keyless posture / credentialed provider selection** — which is what `profile` legitimately
  drives elsewhere (`active_llm`, `active_vector_store`, `active_search`, `active_tracing_exporter`,
  and the JWT production guard).

**Chosen fix (root-cause, seam-confined).** Split persistence from profile by introducing an
explicit, keyless-safe setting and a single derived selector, then change *only* the nine
builders' predicate to consult it.

1. **New setting** in `Settings` (default preserves the keyless unit lane):
   ```python
   # Persist the ten Domain_Stores to the running Postgres over a DSN (no credential).
   # Default False so the keyless unit lane stays in-memory and deterministic (R10).
   use_database: bool = False
   ```
2. **New derived selector** on `Settings` (mirrors the existing `active_*` helpers), so production
   behavior is unchanged with zero compose edits and local opts in explicitly:
   ```python
   def persist_domain_stores(self) -> bool:
       """DB-backed Domain_Stores when explicitly enabled OR in production."""
       return self.use_database or self.profile == "production"
   ```
3. **Predicate change** in the nine builders — the *only* code edit in `container.py`:
   `if settings.profile == "production":` → `if settings.persist_domain_stores():`.
   Nothing else in each builder changes; each still constructs the same `Pg_*` class from
   `settings.database_url`.
4. **Compose wiring.** In `docker-compose.yml` the `api` service (already `PROFILE=local`) adds:
   ```yaml
   USE_DATABASE: ${USE_DATABASE:-true}
   ```
   so the local stack persists. `docker-compose.production.yml` keeps `PROFILE=production`, which
   already satisfies `persist_domain_stores()`; we additionally set `USE_DATABASE: "true"` there
   for explicitness (belt-and-suspenders; behavior identical either way).

**Why this is keyless-safe and additive.** Every `Pg_*` constructor takes only `database_url`
(a DSN, never a `SecretStr`) and converts it with the shared `to_sync_dsn` / `_to_sqlalchemy_sync_dsn`
path. The compose DSN (`postgresql+asyncpg://agentforge:agentforge@postgres:5432/agentforge`) is a
non-secret bundled default. All target tables already exist:

| Builder | `Pg_*` class | Sync/async | Tables (migration) |
|---------|--------------|-----------|--------------------|
| `build_conversation_store` | `PgConversation_Store` | sync psycopg | `conversations`,`messages` (0003) |
| `build_trace_recorder` | `Pg_Trace_Recorder` | sync psycopg | `agent_runs`,`trace_entries` (0004) |
| `build_multi_agent_run_store` | `Pg_Multi_Agent_Run_Store` | sync psycopg | `multi_agent_runs`,`approval_decisions`,`run_checkpoints` (0005), reuses `messages` |
| `build_identity_store` | `Pg_Identity_Store` | sync psycopg | `users`,`organizations`,`memberships`,`teams`,`team_memberships` (0006) |
| `build_api_key_store` | `Pg_API_Key_Store` | sync psycopg | `api_keys` (0006) |
| `build_usage_store` | `Pg_Usage_Store` | sync psycopg | `usage_records` (0008) |
| `build_prompt_store` | `Pg_Prompt_Store` | sync psycopg | `prompt_templates`,`prompt_versions` (0009) |
| `build_evaluation_store` | `Pg_Evaluation_Store` | sync psycopg | `evaluation_*` (0010) |
| `build_integration_connection_store` | `Pg_Integration_Connection_Store` | sync psycopg | `integration_connections` (0011) |

**No missing `Pg_*` implementation** — all nine exist and were verified against the code. This is a
design confirmation, not an assumption: if any had been missing it would have been flagged here as a
scope risk; none are.

**Sync vs async (reused, not reinvented).** Every `Pg_*` store is synchronous and driven off the
event loop through the existing worker-thread pattern (`run_in_threadpool` in the deps/services
layer, unchanged). Each store builds its engine from the shared
`to_sync_dsn(...)`/`_to_sqlalchemy_sync_dsn(...)` helper in `vectorstore/pgvector_store.py` /
`conversation/store.py`. We reuse this DSN-conversion path verbatim; no new engine or conversion
logic is added. The app's async engine (`db/engine.py`) remains reserved for health checks and
migrations.

**Determinism (R10).** The keyless unit lane never sets `USE_DATABASE`, so `use_database` defaults
`False`, `profile` defaults `local`, and `persist_domain_stores()` returns `False` → every gated
builder returns its in-memory double exactly as today. Tests that already inject in-memory doubles
via `build_*` / context overrides are unaffected. No test contacts Postgres, so the 472-test suite
stays green and reproducible with zero test changes.

**Vector store scope note.** `build_vector_store` remains profile-driven (`Chroma_Store` locally,
`Pgvector_Store` in production) — it is **not** one of the ten Domain_Stores enumerated in R1 and is
intentionally left unchanged to keep the change minimal (see Risks).

### B2 — Keyless↔production configuration boundary (R2)

**Root cause.** The boundary is functionally correct today (`load_settings` aborts in production
when `JWT_SECRET` is absent; `build_auth_service` only generates a per-boot dev secret under
`local`) but is undocumented, and the persistence flag from B1 must be defined per profile.

**Chosen fix.** No behavior change to the guard — confirm and document it, and slot the new
`use_database` flag into the boundary:

- **Required vs optional settings** are documented per profile (see Data Model section). Production
  required: `DATABASE_URL`, `REDIS_URL` (non-secret, already `Field(...)`), and `JWT_SECRET`
  (`SecretStr`, required when `auth_enabled`). The existing `load_settings` guard already enforces
  all three and reports the missing key by name via `ConfigError` (R2.3, R2.6).
- **`SecretStr` at runtime (R2.2).** `jwt_secret: SecretStr | None` is env-sourced; the production
  overlay supplies it as `JWT_SECRET: ${JWT_SECRET}` from the operator Secret_Source — never
  committed. Confirmed against `docker-compose.production.yml`.
- **No dev-secret fallback in production (R2.7).** `build_auth_service` generates
  `secrets.token_urlsafe(64)` *only* when `settings.profile == "local"`; the production branch
  raises `ConfigError`. Unchanged.
- **Persistence per profile.** `persist_domain_stores()` is ON in both local (via `USE_DATABASE=true`)
  and production (via `profile == "production"`).

### B3 — SSE stalls/buffers through the proxy (R3)

**Root cause.** `nginx/snippets/proxy_backend.conf` already sets `proxy_buffering off`,
`proxy_cache off`, `proxy_read_timeout 3600s`, `proxy_send_timeout 3600s`, and clears the
`Connection` header — but it **omits `proxy_http_version 1.1`**. nginx defaults upstream to
HTTP/1.0, which cannot sustain chunked streaming or upstream keepalive, so SSE events are held/
coalesced and long-lived streams behave incorrectly. Clearing `Connection ""` for keepalive is only
effective under HTTP/1.1.

**Chosen fix.** Add the missing directive (and make the unbuffered intent explicit) to the shared
backend snippet, which is included by every backend route in `locations.conf` (including the SSE
routes `/agent` and `/multi-agent`):

```nginx
# Stream SSE incrementally; HTTP/1.1 is required for chunked streaming + upstream keepalive.
proxy_http_version 1.1;
proxy_set_header   X-Accel-Buffering no;   # explicit; honored by proxy_buffering off
```

`proxy_buffering off` + `proxy_cache off` + `proxy_http_version 1.1` yields byte-identical,
in-order, incremental forwarding for SSE (R3.1, R3.4). The `3600s` timeouts already satisfy the
≥300 s inactivity (R3.2) and ≥3600 s duration (R3.3) bounds. Non-streaming JSON is unaffected: with
buffering off nginx still forwards the complete body byte-for-byte (R3.5). Upstream close propagates
to the client with events already forwarded retained (R3.6) — nginx default behavior, now correct
under HTTP/1.1.

### B4 — Backend image ~17.8 GB (R4)

**Root cause.** `torch` is resolved as an ordinary transitive dependency of
`sentence-transformers==3.3.1` from PyPI, whose Linux wheel bundles the full CUDA/NVIDIA payload
(multi-GB `nvidia-cu*` wheels). A prior session found the PyTorch CPU wheel CDN
(`download-r2.pytorch.org`) TLS-unreachable *inside this sandbox*, which is why the current
Dockerfile/constraints deliberately avoid the CPU index and instead free runner disk to cope with
the CUDA payload.

**Chosen fix (robust CPU-only install).** Install a **pinned CPU-only torch first**, so the later
`pip install -r requirements.txt -c constraints.txt` sees `torch` already satisfied and never pulls
the CUDA build. In the builder stage, before the requirements install:

```dockerfile
# CPU-only torch: no CUDA/NVIDIA payload. Installed BEFORE requirements so the
# sentence-transformers resolve reuses it instead of the CUDA PyPI wheel (R4.1).
RUN pip install --retries 5 --timeout 120 \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1"
```

- **Version** pinned to a build present on the CPU index (compatible with
  `sentence-transformers==3.3.1`, which requires `torch>=1.11`). Keeps the resolve deterministic.
- **Robustness / CDN availability.** The earlier TLS failure was **sandbox-specific**; GitHub-hosted
  runners reach `download.pytorch.org` normally. `--retries`/`--timeout` add resilience. If a runner
  cannot reach the CPU index, the documented fallback is to pin the equivalent `+cpu` build with an
  explicit `--extra-index-url` for the CPU wheels while keeping PyPI for the rest — behavior identical,
  still CPU-only. This is a build-input change only; **application behavior is byte-identical** because
  no source and no pinned app dependency changes (R4.3, R4.4).
- **Constraints.** Update the `constraints.txt` note to reflect the CPU-index install (the
  `transformers>=4.41,<4.48` bound stays). The CUDA-driven disk-freeing steps in CI may remain but
  become unnecessary; keep them (harmless) to minimize churn.
- **Non-root & port preserved.** The two-stage build, `appuser`, and `EXPOSE 8000` /
  `API_PORT` CMD are untouched (R4.5, R4.6).
- **Target ≤4 GB (R4.2).** Removing the CUDA/NVIDIA wheels drops the image from ~17.8 GB to well
  under 4 GB. Verified in CI (see Testing Strategy: image-size gate).

### B5 — Stray untracked `Dockerfile.verify` (R5)

**Root cause + finding.** `git status` reports `?? Dockerfile.verify` (untracked) and `git ls-files`
returns nothing; a repo-wide search finds **no tracked build or CI file referencing it** (only this
spec's requirements mention it). Its own header says "NOT committed."

**Chosen fix.** **Remove** `Dockerfile.verify` (R5.3). It serves no ongoing tracked purpose, so the
track-it branch (R5.2) does not apply. After removal, version-control status reports zero untracked
build artifacts at the repo root (R5.1, R5.4).

### B6 — Committed OpenAPI contract is stale (R6)

**Root cause.** `frontend/openapi.json` was dumped before `GET /integrations/status` was mounted, so
the committed contract is missing that operation. There is a client-side drift check
(`frontend/scripts/check-codegen.mjs`: `schema.d.ts` vs `openapi.json`) but **no server-side check**
that `openapi.json` matches the routes the backend actually mounts.

**Chosen fix.**
1. **Regenerate the contract** from the mounted app: dump `create_app().openapi()` to
   `frontend/openapi.json` (now including `GET /integrations/status`), then run
   `npm run codegen` to regenerate `frontend/src/api/schema.d.ts` so the existing client-side check
   still passes.
2. **Add a keyless server-side drift check.** A small backend script
   `scripts/check_openapi.py` builds the app keyless (no credentials — `create_app()` mounts all
   routers without touching infra), serializes `app.openapi()`, and compares it to the committed
   `frontend/openapi.json`. On mismatch it exits non-zero and prints the differing paths/methods
   (R6.3, R6.4). It reads no credential and is deterministic (R6.5). Wire it into the CI **test
   (keyless)** job alongside the existing backend lane, and keep the frontend `codegen:check` as the
   complementary client-side guard. This mirrors the existing `check-codegen.mjs` pattern rather than
   inventing new tooling.

## Components and Seams Touched

Exact files and functions (nothing outside these):

| File | Change |
|------|--------|
| `src/agentforge/config/settings.py` | Add `use_database: bool = False`; add `persist_domain_stores()` helper; (B2) document required/optional in docstrings. `load_settings` guard unchanged. |
| `src/agentforge/config/container.py` | In the **nine** gated builders, change predicate `profile == "production"` → `settings.persist_domain_stores()`. No other change; interfaces/wiring order untouched. |
| `nginx/snippets/proxy_backend.conf` | Add `proxy_http_version 1.1;` and explicit `proxy_set_header X-Accel-Buffering no;`. |
| `Dockerfile` | Add CPU-only torch install step in the builder stage (before requirements). |
| `constraints.txt` | Update the torch note to reflect the CPU-index install (bounds unchanged). |
| `docker-compose.yml` | `api.environment`: add `USE_DATABASE: ${USE_DATABASE:-true}`. |
| `docker-compose.production.yml` | `api.environment` (+ `migrate`): add explicit `USE_DATABASE: "true"`. |
| `Dockerfile.verify` | **Delete** (untracked, unreferenced). |
| `frontend/openapi.json` | Regenerate from `app.openapi()` (adds `GET /integrations/status`). |
| `frontend/src/api/schema.d.ts` | Regenerate via `npm run codegen`. |
| `scripts/check_openapi.py` (new) | Keyless server-side contract drift check. |
| `.github/workflows/ci-cd.yml` | Add contract-drift step to the `test` job; add image-size gate to the `build` job. |

**Emphasis — `container.py` store selection:** the entire B1 code change is a one-line predicate
swap in each of nine builders plus one new settings field and one helper. No `Pg_*` class, store
interface, service, or router is modified (R1.6, R8).

## Data Model / Migrations

**No new migration and no schema change (R11).** All ten Domain_Stores map onto tables already
created by the existing additive migrations `0001`–`0011` (see the B1 table). The B1 change only
flips *which existing store class* is constructed; the persisted shapes are exactly those the
production profile already writes. Migrations remain additive-only and idempotent via the existing
runner; none is added, rewritten, or deleted.

**Configuration model (B2) — required vs optional by profile:**

| Setting | Type | `local` | `production` |
|---------|------|---------|--------------|
| `DATABASE_URL` | str | required (compose default) | **required** |
| `REDIS_URL` | str | required (compose default) | **required** |
| `PROFILE` | `local`/`production` | `local` | `production` |
| `USE_DATABASE` | bool | `true` (compose) — persists | `true` (implied by profile) |
| `JWT_SECRET` | SecretStr | optional (per-boot dev secret) | **required** (`auth_enabled`) |
| `GROQ_API_KEY`,`SEARCH_API_KEY`,`HOSTED_EMBEDDING_API_KEY`,`LANGSMITH_API_KEY`, integration tokens | SecretStr | optional (disabled) | optional (feature-gated) |

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a
system — a formal statement about what the system should do. Properties bridge human-readable
specifications and machine-verifiable correctness guarantees.* This project already uses
property-based testing (`hypothesis` for the backend, `fast-check` for the frontend); the properties
below are framed so tasks can implement them as PBT and targeted integration properties.

### Property 1: Store-selection predicate is correct and profile-independent

*For all* `Settings` values, every one of the nine gated `build_*` functions returns a DB-backed
`Pg_*` instance when `settings.persist_domain_stores()` is true, and returns the in-memory
implementation when it is false — independent of any credential being present.

**Validates: Requirements 1.1, 1.3, 8.1, 8.2, 10.1**

### Property 2: Persistence round-trip / model equivalence per Domain_Store

*For any* domain record written through a `Pg_*` store under an `org_id`, reading it back within the
same `org_id` returns field values equal to those written; and *for any* sequence of store
operations, the `Pg_*` store's observable results equal the in-memory reference store's results
(model-based). This is the write→read equivalence that a restart preserves (durability verified in
the integration lane).

**Validates: Requirements 1.2**

### Property 3: Cross-tenant reads never leak (404, never 403 or contents)

*For any* two distinct `org_id` values and *any* record created under org A, a `get`/read of that
record's id under org B returns `None` (surfaced by the router as HTTP 404) and never returns the
record's contents and never a 403 — for every newly-persistent Domain_Store.

**Validates: Requirements 1.4, 8.4**

### Property 4: Keyless boot invariant (no credential required, none read)

*For all* keyless `Settings` (no secrets supplied) with `persist_domain_stores()` true, every gated
builder constructs successfully without reading any credential, and no network-capable provider is
constructed; adding persistence introduces no credential requirement to the default boot.

**Validates: Requirements 1.3, 1.5, 9.2, 9.3, 10.2**

### Property 5: SSE ordering and byte-identity through the proxy

*For any* finite sequence of SSE events emitted by the Backend_Service on an SSE_Route, the bytes and
ordering received by the client through the Reverse_Proxy are identical to those emitted, with no
coalescing. (Executed in an integration harness against the running nginx.)

**Validates: Requirements 3.1, 3.4**

### Property 6: Committed contract matches the mounted routes exactly

*For all* routes mounted by the Backend_Service, the committed `frontend/openapi.json` contains a
matching path, method, and operation definition, and contains no path/method/operation that is not
mounted — i.e. the committed contract equals `app.openapi()`. This also guarantees no existing
route/field is removed relative to the mounted surface.

**Validates: Requirements 6.1, 6.2, 7.2, 7.3**

### Property 7: Drift check is sound, keyless, and deterministic

*For any* committed contract, the drift check reports success when it equals the generated schema and
failure naming each differing route when it does not; and *for all* runs on unchanged inputs it reads
no credential and returns the same result.

**Validates: Requirements 6.3, 6.4, 6.5**

## Error Handling

- **Configuration (B2).** `load_settings` continues to raise `ConfigError` naming the missing key(s)
  when a required non-secret setting or (in production) `JWT_SECRET` is absent; startup aborts before
  any route is reachable (R2.3, R2.6). `build_auth_service` raises `ConfigError` in production without
  a secret rather than generating one (R2.7).
- **Persistence (B1).** `Pg_*` stores preserve the existing uniform `AppError` envelope and tenancy
  semantics (cross-tenant → `AppError("not_found", 404)`), and their transactional writes already
  leave nothing behind on failure. No new error paths are introduced.
- **SSE (B3).** Upstream close/failure propagates to the client; events already forwarded are retained
  unaltered (R3.6).
- **Drift check (B6).** Exits non-zero and prints the differing paths/methods on mismatch (R6.4);
  never throws on a matching contract.
- **Image (B4).** A failed CPU-index install fails the build fast (with retries); the size gate fails
  the `build` job if the image exceeds the 4 GB budget.

## Testing Strategy

**Keyless unit lane stays green (R10).** The default `use_database=False` keeps all gated builders on
their in-memory doubles, so the existing 472-test suite runs unchanged, credential-free, and
reproducible. No test is modified to accommodate B1.

**Property-based tests (backend, `hypothesis`; frontend, `fast-check`).** Implement each correctness
property as a single property test, min 100 iterations, tagged
`Feature: production-hardening, Property {n}: {text}`:
- Property 1 & 4 — pure tests over generated `Settings` in the keyless lane (no DB).
- Property 2 & 3 — run against the in-memory stores in the keyless lane (tenancy/round-trip logic is
  identical across implementations); additionally executed against real Postgres in the
  **integration lane** for the `Pg_*` stores (model-based equivalence + restart durability).
- Property 6 — deterministic keyless test comparing `app.openapi()` to the committed contract.
- Property 7 — inject synthetic divergences (add/remove/modify a route) and assert the check fails and
  names them; assert identity passes; assert determinism.

**Integration lane (opt-in, `-m integration`).** Compose-up smokes for: local persistence survives
`docker compose restart` (R1.2, R1.5); production overlay boots healthy and reproducibly with secrets
from the Secret_Source (R2.1); SSE incremental delivery and long-lived timeouts through nginx
(R3.1–R3.3, R3.5, R3.6, Property 5); the keyless suite runs identically inside the built image
(R4.3, R4.4); image builds and starts keyless as non-root on the configured port (R4.5, R4.6).

**CI gates (`.github/workflows/ci-cd.yml`).**
- `test` job (keyless): add `python scripts/check_openapi.py` (contract drift, R6) beside the existing
  backend lane and frontend `npm run ci` (which already runs `codegen:check`).
- `build` job: after building `agentforge-backend`, add an **image-size gate** asserting
  `docker image inspect` size ≤ 4 GB (R4.2), and assert no `nvidia-*`/CUDA libraries are present in
  the venv (R4.1).

**Guardrail checks.** Confirm `migrations/` is unchanged (0001–0011 intact, none added) for R11;
confirm the B1 diff touches only `settings.py` + `container.py` (+ compose) for R1.6/R8; `git status`
reports no untracked root build artifacts for R5.

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| A `Pg_*` implementation missing for some store | **None (verified)** | All nine `Pg_*` classes confirmed present, sync-psycopg, DSN-only. No new store needed. If a future audited store lacks a `Pg_*`, add it additively mirroring the existing pattern — do not expand scope now. |
| PyTorch CPU CDN unreachable on the runner | Low–Medium | Prior failure was sandbox-specific; GitHub runners reach `download.pytorch.org`. Use `--retries/--timeout`; documented fallback to `+cpu` pin via `--extra-index-url`. Behavior identical (CPU-only). |
| Image-size regression undetected | Low | CI size gate (≤4 GB) + CUDA-absence assertion fail the build on regression. |
| Local vector embeddings still ephemeral (Chroma) while chunks persist | Low | Out of R1's enumerated ten Domain_Stores; document as known local behavior. Not changed to keep the fix minimal; re-ingestion regenerates embeddings. |
| Applying the SSE snippet to all backend routes (incl. JSON) | Low | `proxy_buffering off` does not alter bytes; JSON bodies remain byte-identical (R3.5). Scope is the shared backend snippet by design. |
| Persistence enabled but DB unavailable at first request | Low | `pool_pre_ping=True` on every `Pg_*` engine; compose `depends_on: postgres service_healthy` gates the api. Mirrors production behavior already in use. |

## Requirements Coverage Mapping

| Requirement | Design element |
|-------------|----------------|
| R1.1–R1.6 | B1: `use_database` + `persist_domain_stores()`; nine-builder predicate swap; DSN-only `Pg_*`; seam-confined; Properties 1–4 |
| R2.1–R2.7 | B2: documented boundary; confirmed `load_settings` guard + `build_auth_service` no-fallback; `SecretStr` from overlay; config model table |
| R3.1–R3.6 | B3: `proxy_http_version 1.1` + `X-Accel-Buffering no` in `proxy_backend.conf`; existing 3600s timeouts; Property 5 |
| R4.1–R4.6 | B4: CPU-only torch install; ≤4 GB size gate; non-root/port preserved; unchanged app behavior |
| R5.1–R5.4 | B5: remove untracked, unreferenced `Dockerfile.verify` |
| R6.1–R6.5 | B6: regenerate `openapi.json`+`schema.d.ts`; keyless `scripts/check_openapi.py` in CI; Properties 6–7 |
| R7.1–R7.3 | Remediation-only; no route/field removed (Property 6); no new feature |
| R8.1–R8.4 | Composition-root-only selection via existing DI seams; `AppError`/404-tenancy/`SecretStr` preserved (Property 3) |
| R9.1–R9.3 | Keyless boot preserved; no credential added to `docker compose up`; providers disabled by default (Property 4) |
| R10.1–R10.3 | Default `use_database=False` keeps the 472-test keyless lane in-memory, credential-free, reproducible (Properties 1, 4) |
| R11.1–R11.3 | No new/modified migration; tables 0001–0011 already present |
| R12.1–R12.2 | Each fix root-cause, minimal, production-ready; no stub/placeholder |
