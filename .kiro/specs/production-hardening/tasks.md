# Implementation Plan: Production Hardening

## Overview

This plan implements the six audited production-readiness fixes (B1–B6) exactly as described in
`design.md`, with no new scope. Work proceeds through the documented seams only —
`config/settings.py`, the nine gated builders in `config/container.py`, `nginx/snippets/proxy_backend.conf`,
the root `Dockerfile`, `constraints.txt`, `docker-compose.yml`, `docker-compose.production.yml`,
removal of `Dockerfile.verify`, regeneration of `frontend/openapi.json` + `frontend/src/api/schema.d.ts`,
a new `scripts/check_openapi.py`, and `.github/workflows/ci-cd.yml`. No service/router/store-interface
rewrites and no new or edited migrations.

The keyless-by-default boot and the deterministic Keyless_Unit_Lane (currently 472 tests) MUST remain
green. Most tasks are checkpointed with `pytest -m "not integration" -q`. Runtime/compose/nginx/image
properties belong to the opt-in integration lane (`-m integration`) and run on a Docker host.

**Property-based testing.** This project uses `hypothesis` (backend) and `fast-check` (frontend).
Each of the seven Correctness Properties from `design.md` is implemented by a single property test,
run with **≥100 iterations** where applicable, and tagged with a comment:
`Feature: production-hardening, Property {n}: {text}`. Property tests are optional sub-tasks (marked `*`)
placed next to the implementation they validate.

## Tasks

- [x] 1. B1 settings seam — persistence selector
  - Add `use_database: bool = False` to `Settings` in `src/agentforge/config/settings.py` (default `False`
    preserves the keyless unit lane's in-memory behavior).
  - Add the derived selector `persist_domain_stores(self) -> bool` returning
    `self.use_database or self.profile == "production"`, mirroring the existing `active_*` helpers.
  - Leave the `load_settings` production guard unchanged.
  - Verify: `pytest -m "not integration" -q` stays green (472 tests, no credentials).
  - _Requirements: 1.1, 1.3, 2.4, 8.1, 10.1_

  - [x]* 1.1 Write unit test for the persistence selector
    - Assert `persist_domain_stores()` is `False` for default keyless settings, `True` when
      `use_database=True`, and `True` when `profile=="production"`.
    - _Requirements: 1.1, 1.3, 10.1_

- [x] 2. B1 composition-root predicate swap (nine gated builders)
  - In `src/agentforge/config/container.py`, change the predicate `settings.profile == "production"` to
    `settings.persist_domain_stores()` in exactly these nine builders: `build_conversation_store`,
    `build_trace_recorder`, `build_identity_store`, `build_api_key_store`, `build_usage_store`,
    `build_prompt_store`, `build_evaluation_store`, `build_multi_agent_run_store`,
    `build_integration_connection_store`.
  - Make no other change: each builder still constructs the same `Pg_*` class from `settings.database_url`;
    interfaces, wiring order, and `build_document_store`/`build_vector_store` are untouched.
  - Verify: `pytest -m "not integration" -q` stays green; no new credential requirement introduced.
  - _Requirements: 1.1, 1.3, 1.6, 8.1, 8.2, 8.3, 9.3, 10.2_

  - [x]* 2.1 Write property test — Property 1 (store-selection predicate)
    - **Property 1: Store-selection predicate is correct and profile-independent**
    - For generated `Settings`, each of the nine gated `build_*` returns a `Pg_*` instance when
      `persist_domain_stores()` is true and the in-memory implementation when false, independent of
      any credential. `hypothesis`, ≥100 iterations, keyless (no DB).
    - Tag: `Feature: production-hardening, Property 1: store-selection predicate is correct and profile-independent`
    - **Validates: Requirements 1.1, 1.3, 8.1, 8.2, 10.1**

  - [x]* 2.2 Write property test — Property 4 (keyless boot invariant)
    - **Property 4: Keyless boot invariant (no credential required, none read)**
    - For keyless generated `Settings` with `persist_domain_stores()` true, every gated builder
      constructs successfully without reading any credential and constructs no network-capable provider.
      `hypothesis`, ≥100 iterations, keyless.
    - Tag: `Feature: production-hardening, Property 4: keyless boot invariant (no credential required, none read)`
    - **Validates: Requirements 1.3, 1.5, 9.2, 9.3, 10.2**

- [x] 3. Checkpoint — keyless lane green after B1 seam changes
  - Ensure all tests pass (`pytest -m "not integration" -q`), ask the user if questions arise.

- [x] 4. B1 store-logic correctness properties (keyless lane)
  - [x]* 4.1 Write property test — Property 2 (persistence round-trip / model equivalence)
    - **Property 2: Persistence round-trip / model equivalence per Domain_Store**
    - For a record written through a store under an `org_id`, reading it back within the same `org_id`
      returns equal field values; and for any sequence of operations the store's observable results equal
      the in-memory reference store's results (model-based). Run against in-memory stores in the keyless
      lane. `hypothesis`, ≥100 iterations.
    - Tag: `Feature: production-hardening, Property 2: persistence round-trip / model equivalence per Domain_Store`
    - **Validates: Requirements 1.2**

  - [x]* 4.2 Write property test — Property 3 (cross-tenant reads never leak)
    - **Property 3: Cross-tenant reads never leak (404, never 403 or contents)**
    - For two distinct `org_id` values and a record created under org A, a read of that id under org B
      returns `None` (surfaced as HTTP 404), never the contents and never 403 — for every newly-persistent
      Domain_Store. Run against in-memory stores in the keyless lane. `hypothesis`, ≥100 iterations.
    - Tag: `Feature: production-hardening, Property 3: cross-tenant reads never leak (404, never 403 or contents)`
    - **Validates: Requirements 1.4, 8.4**

  - [x]* 4.3 Add integration-lane checks for Pg_* durability and equivalence
    - Mark with `-m integration`: model-based equivalence of each `Pg_*` store vs its in-memory reference
      against real Postgres, plus write→read durability across a restart. Do NOT run in the keyless lane.
    - _Requirements: 1.2, 1.4_

- [x] 5. B1 compose wiring for persistence
  - In `docker-compose.yml`, add `USE_DATABASE: ${USE_DATABASE:-true}` to the `api` service environment
    (already `PROFILE=local`) so the default local stack persists.
  - In `docker-compose.production.yml`, add explicit `USE_DATABASE: "true"` to both the `api` and `migrate`
    service environments (belt-and-suspenders; `profile==production` already satisfies the selector).
  - Do not add any credential to the default `docker compose up` boot.
  - _Requirements: 1.2, 1.5, 2.1, 9.1, 9.3_

  - [x]* 5.1 Add integration-lane local persistence smoke
    - Mark with `-m integration`: `docker compose up`, write application data through a Domain_Store,
      `docker compose restart`, then read back identical field values within the same `org_id`; assert the
      stack reaches healthy serving state (Frontend, Backend, PostgreSQL, Redis) within 180s using no
      credentials. Run on a Docker host only.
    - _Requirements: 1.2, 1.5, 9.1_

- [ ] 6. B2 configuration boundary documentation (no behavior change)
  - Document, per setting and by name, which settings are required vs optional in the `production` and
    `local` profiles (config model table from the design), placed in a docs file and/or
    `.env.production.example`. Include `DATABASE_URL`, `REDIS_URL`, `PROFILE`, `USE_DATABASE`, `JWT_SECRET`,
    and the optional feature-gated `SecretStr` keys.
  - Confirm (and note in the docs) that `load_settings` aborts naming the missing key when a required
    non-secret or (in production) `JWT_SECRET` is absent, that `JWT_SECRET` is sourced as `SecretStr` from
    the overlay and never from a version-controlled file, and that `build_auth_service` never falls back to
    the per-boot dev secret under `production`. No code behavior change.
  - _Requirements: 2.2, 2.3, 2.5, 2.6, 2.7_

- [ ] 7. B3 nginx SSE proxy directives
  - In `nginx/snippets/proxy_backend.conf`, add `proxy_http_version 1.1;` and an explicit
    `proxy_set_header X-Accel-Buffering no;` (alongside the existing `proxy_buffering off`, `proxy_cache off`,
    and 3600s read/send timeouts). This shared snippet is included by all backend routes, including the
    SSE routes `/agent` and `/multi-agent`.
  - Note in the change that non-streaming JSON routes remain byte-identical (buffering off does not alter
    bodies).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 7.1 Add integration-lane property test — Property 5 (SSE ordering/byte-identity)
    - **Property 5: SSE ordering and byte-identity through the proxy**
    - For a finite sequence of SSE events emitted on an SSE_Route, the bytes and ordering received through
      the running nginx are identical to those emitted, with no coalescing. Integration harness against
      running nginx; mark `-m integration`. `hypothesis` for event-sequence generation where practical.
    - Tag: `Feature: production-hardening, Property 5: SSE ordering and byte-identity through the proxy`
    - **Validates: Requirements 3.1, 3.4**

- [ ] 8. B4 CPU-only backend image
  - In the `Dockerfile` builder stage, add a pinned CPU-only torch install BEFORE the
    `pip install -r requirements.txt -c constraints.txt` step:
    `pip install --retries 5 --timeout 120 --index-url https://download.pytorch.org/whl/cpu "torch==2.5.1"`
    so the `sentence-transformers` resolve reuses it instead of the CUDA wheel.
  - Update the torch note in `constraints.txt` to reflect the CPU-index install (keep existing bounds such
    as `transformers>=4.41,<4.48`). Preserve the two-stage build, non-root `appuser`, and `EXPOSE`/`API_PORT`
    CMD unchanged.
  - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 8.1 Add CI build-job image-size gate and CUDA-absence assertion
    - In `.github/workflows/ci-cd.yml` `build` job, after building `agentforge-backend`, assert
      `docker image inspect` size ≤ 4 GB and assert no `nvidia-*`/CUDA libraries exist in the venv.
    - _Requirements: 4.1, 4.2_

- [ ] 9. B5 remove stray build artifact
  - Delete `Dockerfile.verify` from the repository root (untracked and unreferenced by any tracked build/CI
    file).
  - Verify `git status` reports zero untracked build-artifact entries at the repository root.
  - _Requirements: 5.1, 5.3, 5.4_

- [ ] 10. B6 regenerate API contract and add keyless drift check
  - [ ] 10.1 Regenerate the committed contract and client types
    - Dump `create_app().openapi()` to `frontend/openapi.json` (now including `GET /integrations/status`),
      then run `npm run codegen` to regenerate `frontend/src/api/schema.d.ts` so the existing client-side
      `codegen:check` passes.
    - _Requirements: 6.1, 6.2, 7.2, 7.3_

  - [ ] 10.2 Add keyless server-side drift check `scripts/check_openapi.py`
    - New backend script builds the app keyless (`create_app()`, no credentials), serializes `app.openapi()`,
      and compares it to committed `frontend/openapi.json`; on mismatch exit non-zero and print each
      differing path/method; on match report success. Deterministic, reads no credential. Mirror the existing
      `check-codegen.mjs` pattern.
    - _Requirements: 6.3, 6.4, 6.5_

  - [ ]* 10.3 Write property test — Property 6 (committed contract matches mounted routes)
    - **Property 6: Committed contract matches the mounted routes exactly**
    - The committed `frontend/openapi.json` equals `app.openapi()` — every mounted route present, nothing
      extra. Deterministic keyless test.
    - Tag: `Feature: production-hardening, Property 6: committed contract matches the mounted routes exactly`
    - **Validates: Requirements 6.1, 6.2, 7.2, 7.3**

  - [ ]* 10.4 Write property test — Property 7 (drift check is sound, keyless, deterministic)
    - **Property 7: Drift check is sound, keyless, and deterministic**
    - Inject synthetic divergences (add/remove/modify a route) and assert the check fails and names them;
      assert identity passes; assert determinism and no credential read. `hypothesis` for divergence
      generation, ≥100 iterations; keyless.
    - Tag: `Feature: production-hardening, Property 7: drift check is sound, keyless, and deterministic`
    - **Validates: Requirements 6.3, 6.4, 6.5**

  - [ ] 10.5 Wire the drift check into CI
    - Add `python scripts/check_openapi.py` to the keyless `test` job in `.github/workflows/ci-cd.yml`,
      beside the existing backend lane and the frontend `npm run ci` (which already runs `codegen:check`).
    - _Requirements: 6.3, 6.5_

- [ ] 11. Checkpoint — keyless lane + frontend CI green after B3–B6
  - Ensure all keyless tests pass (`pytest -m "not integration" -q`) and the frontend `npm run ci` passes;
    ask the user if questions arise.

- [ ] 12. Final verification checkpoint (leave UNCHECKED for human sign-off)
  - Confirm the full Keyless_Unit_Lane is green (`pytest -m "not integration" -q`, still 472 tests,
    credential-free) and frontend `npm run ci` passes.
  - Run the integration-lane/compose/nginx/image properties on a Docker host (`-m integration`): local
    persistence across `docker compose restart`, production overlay healthy boot with secrets, SSE
    incremental delivery/timeouts (Property 5), keyless suite inside the built image, and image builds/starts
    keyless as non-root on the configured port with size ≤ 4 GB.
  - Confirm migrations `0001`–`0011` are unchanged (none added/edited) and that the B1 diff is confined to
    `settings.py` + `container.py` (+ compose files).
  - _Requirements: 1.2, 1.5, 2.1, 3.1, 3.2, 3.3, 4.2, 4.3, 4.5, 4.6, 10.1, 11.1, 11.2_

## Task Dependency Graph

```
1 (settings seam)
└─> 2 (nine-builder predicate swap)  ──> 3 (checkpoint)
        ├─> 4 (Property 2/3 + integration durability)      ┐
        └─> 5 (compose wiring + persistence smoke)          │
                                                            ├─> 11 (checkpoint) ─> 12 (final sign-off)
6 (B2 docs)            ── independent ──                     │
7 (B3 nginx SSE)       ── independent ──                     │
8 (B4 CPU image)       ── independent ──                     │
9 (B5 remove file)     ── independent ──                     │
10 (B6 contract + drift check + Properties 6/7 + CI) ───────┘
```

**Sequential (hard dependencies):**
- 1 → 2 → 3 (selector must exist before the predicate swap; checkpoint after).
- 2 → 4 and 2 → 5 (store selection must be in place).
- 10.1 → 10.2/10.3/10.4/10.5 (regenerated contract before drift check and its tests).
- Everything → 11 → 12 (final checkpoints last).

**Parallelizable (independent seams, no shared files):**
- Tasks 6 (B2 docs), 7 (B3 nginx), 8 (B4 Dockerfile/constraints/CI-build), 9 (B5 delete), and 10 (B6
  frontend contract + `scripts/check_openapi.py` + CI-test) touch disjoint files and may proceed in
  parallel with the B1 track (1→5) and with each other. Note 8 and 10.5 both edit
  `.github/workflows/ci-cd.yml` (build job vs test job) — coordinate to avoid a merge conflict.

## Notes

- Tasks marked with `*` are optional test sub-tasks and may be skipped for a faster MVP; core
  implementation tasks are never optional.
- Each of the seven Correctness Properties is implemented by exactly one property test, ≥100 iterations
  where applicable, tagged `Feature: production-hardening, Property {n}: {text}`.
- Properties 1, 4, 6, 7 run in the keyless lane; Properties 2, 3 run keyless against in-memory stores and
  additionally in the integration lane against Postgres; Property 5 is integration-lane only.
- The default `use_database=False` keeps the 472-test keyless lane in-memory, credential-free, and
  reproducible; no existing test is modified for B1.
- Task 12 stays UNCHECKED for manual human sign-off after the Docker-host integration lane runs.
