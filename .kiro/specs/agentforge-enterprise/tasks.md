# Implementation Plan: AgentForge Enterprise Controls (Phase 5)

## Overview

This plan converts the Phase 5 design into an ordered, incremental, test-driven coding
sequence. Every task builds on the previous one — settings + interfaces first, then the
domain models and RBAC map, then the `Auth_Service` (hashing + JWT), then the
`Identity_Store` (in-memory + Postgres + migration `0006`), then the `API_Key_Service`,
then the `Rate_Limiter`, then the reusable `Principal` + FastAPI dependencies, then the
composition root wiring, then the tenancy migration `0007` and the extension of every
existing store to require `org_id`, then the new `auth` + `orgs` routers, then the
application of auth + tenancy to the existing routers, and finally the app wiring and
the design-decisions doc — with everything wired together so no code is orphaned.

The whole layer **reuses, never reimplements** the existing Phase 1-4 seams: the
`API_Service` (FastAPI) + uniform `AppError` error envelope, `Settings` +
`load_settings` + `config/container.py` + `main.py`, Postgres + pgvector + the migration
runner (`db/migrations.py`), Redis, and every existing router and store
(`ingest`, `query`, `documents`, `conversations`, `agent`, `multi_agent`, along with
`DBDocumentStore`, `PgConversation_Store`, `Pg_Trace_Recorder`,
`Pg_Multi_Agent_Run_Store` and their in-memory counterparts). New code lives under
`src/agentforge/enterprise/`, two new routers under `src/agentforge/api/routers/`, and
two new SQL migrations (`0006`, `0007`).

**Keyless-first testing.** All 10 correctness properties from the design are implemented
as **Hypothesis** property tests (minimum 100 iterations each, one test per property,
tagged `Feature: agentforge-enterprise, Property {n}: {text}`), placed next to their
implementation area under `tests/property/`. Unit tests cover error branches and shape
guarantees; integration tests marked `@pytest.mark.integration` cover real Postgres +
Redis paths. The default lane runs KEYLESS via an in-memory `Identity_Store`, an
in-memory `API_Key_Store`, a `NoOp_Rate_Limiter` (with `Fake_Clock_Rate_Limiter`
injected in tests), and a dev-generated `jwt_secret`; the production profile requires a
real `jwt_secret` and wires the Postgres stores + Redis limiter through the same seams.

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Top-level tasks are never optional.
- Each task references the specific requirements and design components it implements.

## Tasks

- [x] 1. Extend `Settings`, scaffold the `enterprise/` package with base interfaces and stubs
  - Extend `config/settings.py` `Settings` with the Phase 5 fields (all optional /
    defaulted so keyless boot is preserved): `auth_enabled: bool = True`,
    `jwt_secret: SecretStr | None = None`, `jwt_algorithm: Literal["HS256"] = "HS256"`,
    `jwt_expiry_seconds: int = 3600` (range `[60, 86_400]`),
    `argon2_time_cost: int = 2`, `argon2_memory_cost: int = 64 * 1024`,
    `argon2_parallelism: int = 2`, `rate_limit_enabled: bool = True`,
    `rate_limit_max: int = 60`, `rate_limit_window_seconds: int = 60`.
  - Extend `load_settings()` with the production guard: if
    `profile == "production" and auth_enabled and jwt_secret is None`, raise
    `ConfigError(["jwt_secret"], detail="required in production profile")` before
    startup completes.
  - Add the new env-var names to `.env.example` with commented-out sample values, so
    keyless boot remains the default.
  - Create the `src/agentforge/enterprise/` package with `__init__.py` and the stubbed
    modules matching the design's Repository/Module Layout: `base.py` (ABCs for
    `Identity_Store`, `API_Key_Store`, `Rate_Limiter`), `models.py`, `rbac.py`,
    `auth.py`, `identity.py`, `api_keys.py`, `rate_limit.py`, `principal.py`, `store.py`
    (thin re-exports).
  - Add `tests/property/` and `tests/unit/` placeholder `__init__.py` files (if they do
    not already exist) so property/unit lanes are collectible.
  - _Requirements: 9.1, 9.2, 9.5, 9.6, 10.1, 1.7, 1.8_
  - _Design: Settings additions (`config/settings.py`), Repository/Module Layout,
    "Keyless dev boot preserved"_

  - [x]* 1.1 Write a smoke test for the package layout, ABC abstractness, and settings defaults
    - Assert every `enterprise/*` submodule imports cleanly, that `Identity_Store`,
      `API_Key_Store`, and `Rate_Limiter` are abstract (cannot be instantiated), and
      that `Settings()` in the local profile with no env vars returns
      `auth_enabled=True`, `jwt_secret is None`, `rate_limit_enabled=True`, and the
      other Phase 5 defaults.
    - _Requirements: 9.1, 10.1_

- [x] 2. Implement enterprise domain models and `RBAC_Policy`, with property tests
  - [x] 2.1 Implement `enterprise/models.py` domain dataclasses
    - Define `Organization`, `User` (with `password_hash: str`, never plaintext),
      `Membership` (with `role: Role`), `Team`, `Team_Membership`, `API_Key` (with
      `key_prefix`, `key_hash`, `revoked_at`), `Access_Token_Claims` (frozen), and
      `Principal` (frozen dataclass carrying `kind`, `user_id | None`, `key_id | None`,
      `org_id`, `role`, `permissions: frozenset[Permission]`).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7, 5.1, 8.5_
    - _Design: Enterprise domain models (`enterprise/models.py`)_

  - [x] 2.2 Implement `enterprise/rbac.py` — Role/Permission enums, `ROLE_PERMISSIONS`, `RBAC_Policy`
    - Define `Role` (`OWNER`, `ADMIN`, `MEMBER`, `VIEWER`) and `Permission`
      (`MANAGE_MEMBERS`, `MANAGE_API_KEYS`, `INGEST_DOCUMENTS`, `RUN_AGENTS`, `READ`).
    - Define `ROLE_PERMISSIONS: dict[Role, frozenset[Permission]]` matching the design
      matrix (viewer ⊆ member ⊆ admin ⊆ owner; every role includes `READ`).
    - Implement `RBAC_Policy` with `is_authorized(role, permission)` and
      `permissions_for(role)` as pure functions over the static map.
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6_
    - _Design: `RBAC_Policy` (`enterprise/rbac.py`)_

  - [x]* 2.3 Write property test for the RBAC iff-invariant
    - **Property 2: RBAC iff-invariant**
    - **Validates: Requirements 3.3**
    - Hypothesis over the cartesian product of `Role` × `Permission`: assert
      `RBAC_Policy.is_authorized(r, p) is (p in ROLE_PERMISSIONS[r])`.

  - [x]* 2.4 Write property test for role-permission subset nesting with universal read
    - **Property 3: Role-permission subset nesting with universal read**
    - **Validates: Requirements 3.2, 3.5**
    - Hypothesis over role pairs `(r1, r2)` with `r1 ≺ r2` in `viewer ≺ member ≺ admin ≺ owner`:
      assert `ROLE_PERMISSIONS[r1] ⊆ ROLE_PERMISSIONS[r2]` and
      `Permission.READ in ROLE_PERMISSIONS[r]` for every `r`.

- [x] 3. Implement `Auth_Service` — password hashing + JWT round-trip
  - [x] 3.1 Add dependencies and implement `enterprise/auth.py`
    - Add `pyjwt` and `argon2-cffi` to `pyproject.toml` pinned to compatible versions.
    - Implement `Auth_Service(identity, *, jwt_secret, jwt_algorithm="HS256",
      jwt_expiry_seconds=3600, password_hasher=None)` using `argon2.PasswordHasher`
      built from `settings.argon2_time_cost / argon2_memory_cost / argon2_parallelism`.
    - Implement `hash_password(pw) -> str` and `verify_password(hash, pw) -> bool`
      routing through the argon2 verifier (constant-time; never a plaintext compare).
    - Implement `issue(user_id, org_id, role, *, now=None) -> str` producing an HS256
      JWT with claims `{sub, org_id, role, exp}` where `exp = int((now or utcnow()) +
      jwt_expiry_seconds)`.
    - Implement `verify(token, *, now=None) -> Access_Token_Claims | None` that returns
      `None` on any invalid condition (bad signature, wrong secret, expired, malformed,
      wrong algorithm) — never raises for bad tokens.
    - Implement `register(email, password, org_id, role) -> User` and
      `login(email, password) -> str`; `login` raises `AppError("auth_failed",
      "Invalid credentials.", 401)` on unknown email or password mismatch.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
    - _Design: `Auth_Service` (`enterprise/auth.py`)_

  - [x]* 3.2 Write property test for JWT issue/verify round-trip and rejection of tampered tokens
    - **Property 4: JWT issue/verify round-trip and rejection of tampered tokens**
    - **Validates: Requirements 1.2, 1.5**
    - Hypothesis over `(user_id, org_id, role, exp_offset)`: (a) a token issued with a
      positive `exp_offset` round-trips through `verify` returning the same claims;
      (b) a token whose payload has one bit flipped, whose HS256 signature has been
      stripped, whose secret differs, or whose `exp` is `<= now` returns `None`
      without raising.

  - [x]* 3.3 Write property test for password hash correctness and plaintext non-disclosure
    - **Property 5: Password hash correctness and plaintext non-disclosure**
    - **Validates: Requirements 1.1, 1.6, 8.5**
    - Hypothesis over distinct password pairs `(pw, pw')`: assert
      `verify_password(hash_password(pw), pw) is True`,
      `verify_password(hash_password(pw), pw') is False`, and that the hash string does
      not contain `pw` as a substring.

  - [x]* 3.4 Write unit tests for hash + verify basics
    - Cover the argon2 `VerifyMismatchError` path, unicode passwords, empty strings, and
      long inputs.
    - _Requirements: 1.1, 1.6_

- [x] 4. Implement `Identity_Store` (in-memory + Postgres) and migration `0006`
  - [x] 4.1 Finalize the `Identity_Store` ABC in `enterprise/base.py`
    - Declare the abstract methods from the design: `create_user`, `get_user_by_email`,
      `get_user`, `create_organization`, `get_organization`, `add_membership` (UNIQUE
      `(user_id, org_id)`), `get_membership`, `list_org_members`, `create_team`,
      `add_team_member` (raises `AppError("org_mismatch", 400)` when the user has no
      membership in the team's org).
    - Never accept or return plaintext passwords; only `password_hash` crosses the
      boundary.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 9.5, 9.6_
    - _Design: `Identity_Store` (`enterprise/base.py` + `enterprise/identity.py`)_

  - [x] 4.2 Implement `InMemory_Identity_Store` in `enterprise/identity.py`
    - Back with `dict`s keyed by id/email; enforce `UNIQUE(user_id, org_id)` on
      memberships and `UNIQUE(org_id, name)` on teams; `add_team_member` verifies the
      user holds a membership in the team's org, raising the `org_mismatch` `AppError`
      when not.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 10.1_
    - _Design: `Identity_Store` (in-memory double for keyless/test path)_

  - [x] 4.3 Implement `Pg_Identity_Store` in `enterprise/identity.py`
    - Use sync SQLAlchemy mirroring `PgConversation_Store`; mirror every ABC method
      onto the tables created by `0006`; `UNIQUE(user_id, org_id)` and the
      `add_team_member` cross-org guard are re-enforced at the SQL layer.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 8.1, 9.3_
    - _Design: `Pg_Identity_Store` (mirrors `PgConversation_Store`)_

  - [x] 4.4 Add migration `migrations/0006_create_enterprise_identity.sql`
    - Create tables `organizations`, `users` (`email UNIQUE`, `password_hash NOT NULL`),
      `memberships` (composite PK `(user_id, org_id)`), `teams` (`UNIQUE(org_id,
      name)`), `team_memberships` (composite PK `(team_id, user_id)`), `api_keys` (with
      `key_prefix`, `key_hash`, `revoked_at`).
    - Add `CREATE INDEX ... ON api_keys (key_prefix) WHERE revoked_at IS NULL` and
      `CREATE INDEX ... ON api_keys (org_id)`; add `CREATE INDEX ... ON memberships
      (org_id)`.
    - Use `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` so re-runs are no-ops.
    - _Requirements: 8.1, 8.3, 8.4, 8.5_
    - _Design: `0006_create_enterprise_identity.sql`_

  - [x]* 4.5 Write unit tests for `InMemory_Identity_Store` invariants
    - Cover `UNIQUE(user_id, org_id)` rejection on duplicate `add_membership`,
      `UNIQUE(org_id, name)` rejection on duplicate `create_team`, and the
      `add_team_member` cross-org rejection raising `AppError("org_mismatch", 400)`.
    - _Requirements: 2.5, 2.7_

  - [x]* 4.6 Write an integration test applying migration `0006` and round-tripping identity (`@pytest.mark.integration`)
    - Run the existing migration runner against a real Postgres, assert `0006` reaches
      `schema_migrations`, and round-trip `create_organization` → `create_user` →
      `add_membership` → `create_team` → `add_team_member` through `Pg_Identity_Store`.
    - _Requirements: 8.1, 8.3, 8.4, 9.3_

- [x] 5. Implement `API_Key_Service` (`enterprise/api_keys.py`) with in-memory + Postgres stores
  - [x] 5.1 Finalize the `API_Key_Store` ABC in `enterprise/base.py`
    - Declare `create(api_key)`, `list_active_by_prefix(prefix)`, `list_for_org(org_id)`,
      `get_for_org(org_id, key_id)`, `revoke_for_org(org_id, key_id)`; all
      `*_for_org` methods filter by `org_id` in the store's query, so cross-org access
      is structurally `None` (Property 6.e).
    - _Requirements: 5.1, 5.4, 5.5, 5.7, 9.5_

  - [x] 5.2 Implement `API_Key_Service.create`
    - Generate `secret = f"af_{secrets.token_urlsafe(32)}"`; compute `key_prefix =
      secret[:8]`; compute `key_hash = hasher.hash(secret)` via the same argon2
      `PasswordHasher` reused from `Auth_Service`; persist the `API_Key` row (never the
      secret); return `(API_Key, secret)` so the router surfaces `secret` **exactly
      once** in the response.
    - _Requirements: 5.1, 5.2, 8.5_
    - _Design: `API_Key_Service` (`enterprise/api_keys.py`)_

  - [x] 5.3 Implement `resolve_key`, `list`, and `revoke`
    - `resolve_key(secret)`: reject if the prefix is wrong; call
      `list_active_by_prefix(prefix)` and constant-time-verify each candidate via
      `hasher.verify` — return the match or `None` (revoked keys are excluded by the
      indexed `WHERE revoked_at IS NULL`).
    - `list(caller_org_id)`: return metadata only (no `key_hash`, no secret).
    - `revoke(caller_org_id, key_id)`: `revoke_for_org` returns `None` if the key is not
      in the caller's org — the router surfaces that as `AppError("not_found", 404)`.
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 5.7_
    - _Design: `API_Key_Service` (resolve, list, revoke)_

  - [x] 5.4 Provide `InMemory_API_Key_Store` and `Pg_API_Key_Store`
    - Both implementations back the same ABC; the in-memory version keys on `(org_id,
      id)` and enforces the `list_active_by_prefix` filter in-process; the Postgres
      version uses the indexed prefix + `revoked_at IS NULL` filter from migration
      `0006`.
    - _Requirements: 5.1, 5.4, 5.5, 5.7, 9.3, 10.1_

  - [x]* 5.5 Write property test for the API-key lifecycle
    - **Property 6: API key lifecycle — create, resolve, revoke, cross-org**
    - **Validates: Requirements 5.1, 5.2, 5.4, 5.5, 5.6, 5.7, 8.5, 10.6**
    - Hypothesis over `(org_id, role)` and secondary org `B != A`: (a) `create` returns
      a plaintext secret and `resolve_key(secret)` returns metadata with
      `permissions = RBAC_Policy.permissions_for(role)`; (b) after `revoke`,
      `resolve_key(secret)` returns `None`; (c) no two created keys share an id; (d)
      the stored `key_hash` does not contain the plaintext secret as a substring;
      (e) `list_for_org(B)` never contains a key created in `A`; (f) `revoke_for_org(B,
      key_a.id)` returns `None` (cross-org 404 at the router).

  - [x]* 5.6 Write unit tests for the one-time-return and list shape
    - Assert the create response includes `secret` exactly once and is absent from
      `list`; assert `list` items expose `id`, `org_id`, `role`, `key_prefix`,
      `revoked_at`, and `created_at` and **never** `key_hash` or `secret`.
    - _Requirements: 5.1, 5.2, 5.4_

- [x] 6. Implement `Rate_Limiter` (`enterprise/rate_limit.py`)
  - [x] 6.1 Implement the `Rate_Limiter` ABC and three concrete implementations
    - `Rate_Limiter.check(principal_key: str) -> None` raises `AppError("rate_limited",
      "Rate limit exceeded.", 429, {"limit", "window_seconds"})` on overflow.
    - `Redis_Rate_Limiter`: pipelined atomic `INCR` + `EXPIRE(window_seconds)` on
      `f"rl:{principal_key}:{window_start}"`, where `window_start = int(clock()) //
      window * window`.
    - `NoOp_Rate_Limiter`: `check` is a pass-through (the keyless default; Req 6.5).
    - `Fake_Clock_Rate_Limiter`: deterministic in-memory counter backed by an injected
      `clock()` callable, so property tests are reproducible.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.4_
    - _Design: `Rate_Limiter` (`enterprise/rate_limit.py`)_

  - [x]* 6.2 Write property test for the rate limiter's bound + per-principal isolation + rollover
    - **Property 7: Rate limiter bound and per-principal isolation**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.6, 10.7**
    - Hypothesis over `(Max, Window, k1, k2 != k1)` with a `Fake_Clock_Rate_Limiter`:
      assert the first `Max` calls to `check(k1)` in a single window succeed and the
      `(Max + 1)`-th raises `AppError("rate_limited", 429)`; assert independence of
      `check(k2)`; advance the fake clock by `Window` seconds and assert each key's
      count resets and admits `Max` more successful calls.

  - [x]* 6.3 Write a unit test for window rollover under `Fake_Clock_Rate_Limiter`
    - A single principal fills the window, the fake clock advances one full window, and
      the next `Max` calls succeed.
    - _Requirements: 6.1, 6.3, 10.7_

- [x] 7. Implement `Principal` + FastAPI dependencies (`enterprise/principal.py` + `api/deps.py`)
  - [x] 7.1 Wire `Principal` and `get_current_principal`
    - Add `get_current_principal(request, settings, auth, keys, rbac, rl)` in
      `api/deps.py`: try `Authorization: Bearer <jwt>` first via `auth.verify` (build a
      `Principal(kind="user", user_id, org_id, role, permissions =
      rbac.permissions_for(role))`); otherwise try `X-API-Key` via `keys.resolve_key`;
      otherwise raise `AppError("unauthorized", 401)`. After successful resolution,
      call `rl.check(principal_key)` where `principal_key = f"user:{user_id}"` or
      `f"key:{key_id}"`.
    - _Requirements: 1.4, 1.5, 5.3, 6.1, 7.1_
    - _Design: Principal + FastAPI dependencies_

  - [x] 7.2 Implement `require_permission(permission)` dependency factory + `get_org_id`
    - `require_permission(perm)` returns a callable that depends on
      `get_current_principal` and raises `AppError("forbidden", 403, {"required": perm})`
      if `perm not in principal.permissions`.
    - `get_org_id(principal=Depends(get_current_principal))` returns `principal.org_id`
      for stores that only need the tenant key.
    - _Requirements: 3.3, 3.4, 7.2, 7.6, 7.7_

  - [x]* 7.3 Write property test for principal resolution
    - **Property 8: Principal resolution from any valid credential; 401 for any invalid one**
    - **Validates: Requirements 1.4, 1.5, 5.3, 7.1**
    - Hypothesis alternates between "valid JWT" and "valid API-key" credentials and
      between "no credential", "malformed JWT", "expired JWT", "wrong-secret JWT",
      "unknown API key", and "revoked API key" invalid credentials; asserts a
      well-formed `Principal` in the valid branches (with `permissions` derived from
      `RBAC_Policy.permissions_for(role)`) and `AppError("unauthorized", 401)` in the
      invalid branches.

  - [x]* 7.4 Write unit tests for the dependency chain
    - Cover: (a) Bearer-only path; (b) X-API-Key-only path; (c) precedence when both
      headers are present with only one valid; (d) missing/malformed `Authorization`;
      (e) expired JWT; (f) revoked API key; (g) `require_permission` 403 with the
      `{"required": <perm>}` details.
    - _Requirements: 1.4, 1.5, 3.4, 5.3, 5.6, 7.1, 7.2_

- [x] 8. Wire the enterprise components through the composition root (`config/container.py`)
  - Add `build_auth_service(settings, identity)`: resolves `jwt_secret` from
    `settings.jwt_secret` if present; otherwise generates a per-boot
    `secrets.token_urlsafe(64)` **only when `profile == "local"`**; passes the
    argon2 parameters through as a `PasswordHasher`.
  - Add `build_identity_store(settings)`: returns `Pg_Identity_Store` when
    `profile == "production"`, else `InMemory_Identity_Store`.
  - Add `build_api_key_service(identity, settings, hasher)` using the same argon2 hasher
    reused from `build_auth_service`.
  - Add `build_rbac_policy()` as a singleton.
  - Add `build_rate_limiter(settings, redis, *, clock=None)`: returns
    `Redis_Rate_Limiter` when `rate_limit_enabled and redis is not None`, else
    `NoOp_Rate_Limiter`; tests can inject a `Fake_Clock_Rate_Limiter` via an override.
  - Define `EnterpriseContext` dataclass (`auth`, `identity`, `api_keys`, `rbac`,
    `rate_limiter`) and `build_enterprise_context(settings, **overrides)`; `main.py`
    wires `app.state.enterprise_context` at startup, respecting pre-injected overrides.
  - _Requirements: 1.7, 1.8, 6.4, 6.5, 9.2, 9.5, 10.1_
  - _Design: Composition root wiring (`config/container.py`)_

  - [x]* 8.1 Write unit tests for the composition root selection
    - `build_auth_service` generates a dev secret in local when
      `settings.jwt_secret is None`; `load_settings()` raises `ConfigError` in
      production when `jwt_secret` is missing; `build_rate_limiter` returns
      `NoOp_Rate_Limiter` when `rate_limit_enabled=False` regardless of Redis;
      `build_identity_store` returns the Postgres implementation in production and the
      in-memory implementation in local.
    - _Requirements: 1.7, 1.8, 6.5, 10.1_

- [x] 9. Add tenancy migration `0007_add_org_id_to_tenant_resources.sql`
  - Add `org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE` to
    `documents`, `conversations`, `agent_runs`, `multi_agent_runs`; add composite
    `(org_id, id)` indexes on all four (`documents_org_id_idx`, `conversations_org_id_idx`,
    `agent_runs_org_id_idx`, `multi_agent_runs_org_id_idx`).
  - Use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` so
    re-runs are no-ops; no production data exists yet, so no backfill is required.
  - Descendant tables (`chunks`, `messages`, `trace_entries`, `approval_decisions`,
    `run_checkpoints`) intentionally inherit tenancy through their parent FK — the
    store SQL joins/filters through the parent's `org_id`, so no descendant column
    change is needed.
  - _Requirements: 8.2, 8.3, 8.4, 8.6_
  - _Design: `0007_add_org_id_to_tenant_resources.sql` + "parent-join enforcement"_

  - [x]* 9.1 Write an integration test for migration `0007` (`@pytest.mark.integration`)
    - Apply `0007` through the existing runner and assert `ALTER` succeeded on all four
      tables, the composite indexes exist, and `ON DELETE CASCADE` from
      `organizations(id)` sweeps a seeded document/conversation/agent_run/multi_agent_run
      in a single delete.
    - _Requirements: 8.2, 8.3, 8.4_

- [x] 10. Extend every existing tenant-owned store to require and constrain by `org_id`
  - [x] 10.1 Extend the store interfaces + Postgres implementations
    - Add a required `org_id: UUID` parameter to every method on `DBDocumentStore`,
      `PgConversation_Store`, `Pg_Trace_Recorder`, and `Pg_Multi_Agent_Run_Store` (and
      their `Document_Store` / `Conversation_Store` / `Multi_Agent_Run_Store` ABCs);
      extend the SQL with `WHERE org_id = :org_id` on top-level tables and with
      `AND parent.org_id = :org_id` joins on descendant tables (`chunks`, `messages`,
      `trace_entries`, `approval_decisions`, `run_checkpoints`).
    - Cross-tenant reads return `None` / empty list — the caller router raises
      `AppError("not_found", 404)`; cross-tenant mutations affect zero rows and the
      router raises the same 404. Never 403.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.3, 7.4, 7.5_
    - _Design: Multi-tenancy design + `Tenant_Scoped store pattern`_

  - [x] 10.2 Extend the in-memory counterparts
    - The in-memory `Document_Store`, `Conversation_Store`, `Trace_Recorder`, and
      `Multi_Agent_Run_Store` doubles used by keyless/test lanes gain the same
      `org_id` parameter and internally key by `(org_id, id)`; cross-tenant `get`
      returns `None` and cross-tenant `list_for_org` returns `[]`.
    - _Requirements: 4.2, 4.3, 4.4, 4.6, 10.1_

  - [x] 10.3 Extend the vector-store / long-term memory writes and queries with `org_id`
    - Both the Chroma (dev) and pgvector (prod) memory writers accept `org_id` and set
      it as a `metadata['org_id']` field on writes; every query filters by
      `metadata['org_id'] = principal.org_id` so long-term memory records are strictly
      tenant-scoped alongside the relational tables.
    - _Requirements: 4.1, 4.2, 4.6_

  - [x] 10.4 Thread `org_id` through the services that persist tenant-owned rows
    - Update the `Ingestion_Service`, `Agent_Orchestrator`, and
      `Multi_Agent_Orchestrator` to accept `org_id` as a required parameter on the
      call paths that persist rows and pass it into the extended stores.
    - No handler-level tenancy checks are added — the stores are the enforcement
      point.
    - _Requirements: 4.4, 4.5, 7.3, 9.5_

  - [x]* 10.5 Write property test for tenant isolation across every resource type
    - **Property 1: Tenant isolation invariant across every resource type**
    - **Validates: Requirements 4.3, 4.5, 4.6, 7.5, 10.4**
    - Hypothesis over two distinct orgs `A`, `B` and a resource kind drawn from
      `{Document, Conversation, Agent_Run, Multi_Agent_Run}`: create the resource in
      `A`, then assert every `get` / `list` / `mutate` / `delete` from a Principal in
      `B` returns 404 and leaves the row unchanged; extend to descendants (chunks,
      messages, trace_entries, approval_decisions, run_checkpoints) accessed by parent
      id to confirm the parent-join guard.

  - [x]* 10.6 Write property test for the tenant-scoped store round-trip
    - **Property 9: Tenant-scoped store round-trip**
    - **Validates: Requirements 4.1, 4.2, 4.4, 7.3, 7.4**
    - Hypothesis over one org `A` and one resource kind: created rows carry
      `org_id = A`, `list/get` scoped to `A` returns them, and every `list/get` scoped
      to any `B != A` does not — parametric across the four in-memory stores.

  - [x]* 10.7 Write unit tests for cross-tenant `None` on each in-memory store
    - Create a resource under `org_a`, read it under `org_b`, assert `None`; try to
      delete/mutate it under `org_b`, assert zero rows changed; assert the resource is
      unchanged when re-read under `org_a`.
    - _Requirements: 4.3, 4.6_

  - [x]* 10.8 Write an integration test round-tripping org-scoped documents/conversations/agent_runs/multi_agent_runs (`@pytest.mark.integration`)
    - After applying `0007`, create rows in two orgs, assert every store's SQL filters
      by `org_id`, and confirm cascade-delete on `organizations(id)` removes all four
      resource kinds plus their descendants.
    - _Requirements: 4.1, 4.6, 8.2, 8.3_

- [x] 11. Implement the new `auth` router (`api/routers/auth.py`)
  - Add `POST /auth/register-self`, `POST /auth/login`, and `POST /auth/refresh`; all
    three are **anonymous** (no `Depends(get_current_principal)`) — `refresh` accepts
    a still-valid, non-expired token and re-issues one.
  - Extend `api/schemas.py` with `RegisterRequest`, `LoginRequest`, `TokenResponse`, and
    the refresh payload.
  - Registration validates password strength and email uniqueness — a weak password or
    duplicate email raises `AppError("validation_error", 400)` naming the failing
    field, and the argon2 hash is not computed on the duplicate-email branch.
  - Login raises `AppError("auth_failed", 401)` on unknown email or password mismatch.
  - _Requirements: 1.1, 1.2, 1.3, 7.6, 9.1_
  - _Design: Router: auth (register / login / refresh)_

  - [x]* 11.1 Write unit tests for the auth router error branches
    - Cover weak-password 400, duplicate-email 400, unknown-email 401, wrong-password
      401, successful register-then-login round trip, and successful refresh.
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 12. Implement the new `orgs` router (`api/routers/orgs.py`)
  - Add `POST /orgs` (an authenticated user can create an org they own),
    `POST /orgs/{id}/members` (`manage_members`),
    `POST /orgs/{id}/teams` (`manage_members`),
    `POST /orgs/{id}/teams/{tid}/members` (`manage_members`),
    `POST /orgs/{id}/api-keys` (`manage_api_keys`, returns secret **once**),
    `GET /orgs/{id}/api-keys` (`manage_api_keys`, metadata only — no hash, no secret),
    `DELETE /orgs/{id}/api-keys/{key_id}` (`manage_api_keys`).
  - Cross-org access (caller's `principal.org_id != {id}` in the path) surfaces as
    `AppError("not_found", 404)` — the router does not perform its own tenant check;
    the store's `_for_org` methods return `None`.
  - `POST /orgs/{id}/teams/{tid}/members` for a user without a membership in `{id}`
    raises `AppError("org_mismatch", 400)` propagated from `Identity_Store.add_team_member`.
  - Extend `api/schemas.py` with `CreateOrgRequest`, `CreateMembershipRequest`,
    `CreateTeamRequest`, `CreateApiKeyResponse` (includes plaintext secret **once**),
    and `ApiKeyMetadata`.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.4, 5.5, 5.7, 7.6, 7.7, 9.1_
  - _Design: Router: orgs (members / teams / api-keys)_

  - [x]* 12.1 Write unit tests for the orgs router
    - Cover: create org, add member, create team, cross-org add-member 404, add
      team-member for a non-member of the org 400, api-key create returns secret once
      + list returns metadata only, revoke marks revoked, revoke cross-org 404,
      subsequent `X-API-Key` presentation of a revoked key hits 401.
    - _Requirements: 2.5, 5.1, 5.4, 5.5, 5.6, 5.7_

- [x] 13. Apply auth + tenancy to the existing routers (`ingest`, `query`, `documents`, `conversations`, `agent`, `multi_agent`)
  - Add `Depends(require_permission(P))` on every existing endpoint per the design's
    endpoint→permission table (§ "Applying auth + tenancy to existing endpoints"):
    - `POST /documents` → `ingest_documents`; `GET /documents`, `GET /documents/{id}`
      → `read`; `DELETE /documents/{id}` → `ingest_documents`.
    - `POST /query` → `run_agents`.
    - `POST /conversations`, `POST /conversations/{id}/messages`,
      `GET /conversations/{id}` → `read`.
    - `POST /agent/run`, `POST /agent/stream` → `run_agents`;
      `GET /agent/runs/{id}/trace` → `read`.
    - `POST /multi-agent/runs`, `POST /multi-agent/runs/{id}/stream`,
      `POST /multi-agent/runs/{id}/approval` → `run_agents`;
      `GET /multi-agent/runs/{id}` → `read`.
  - Thread `principal.org_id` (or the `get_org_id` shortcut) into every store /
    service call — the stores are already `org_id`-scoped after task 10, so
    cross-tenant returns 404 without any bespoke handler check.
  - Unauthenticated requests → 401 (from `get_current_principal`); authenticated
    principal missing the permission → 403 (from `require_permission`); cross-tenant
    or unknown-in-tenant → 404 (from the org-scoped store).
  - Update the existing keyless integration tests to authenticate via a
    fixture-created org + user + JWT so the pre-existing behavior continues to pass
    under the enforced auth layer.
  - _Requirements: 3.4, 4.2, 4.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 9.1_
  - _Design: Applying auth + tenancy to existing endpoints (endpoint→permission table)_

  - [x]* 13.1 Write property test for the endpoint permission mapping
    - **Property 10: Endpoint permission mapping — accepts iff role grants required permission**
    - **Validates: Requirements 3.4, 7.1, 7.2, 10.5**
    - Hypothesis over the cartesian product of protected endpoints × roles: an
      authenticated principal with role `r` in the resource's org is accepted by
      endpoint `E` (does not raise 403) if and only if `E`'s required permission is
      in `ROLE_PERMISSIONS[r]`; an unauthenticated request yields 401; a permitted
      role produces a successful (2xx) response through the same handler flow.

  - [x]* 13.2 Write unit tests for 401 / 403 / cross-tenant 404 on the extended routers
    - Cover: no credentials → 401 on every protected endpoint; viewer role on
      `run_agents` endpoints → 403; a document/conversation/agent_run/multi_agent_run
      created in `org_a` and fetched by a principal in `org_b` → 404; a revoked API
      key presented via `X-API-Key` → 401.
    - _Requirements: 3.4, 4.3, 5.6, 7.1, 7.2, 7.5_

- [x] 14. Register the new routers and wire the enterprise context in `main.py`
  - Register `auth_router` and `orgs_router` on the FastAPI app factory alongside the
    existing routers, before the app is served.
  - At startup, build `enterprise_context = build_enterprise_context(settings)` and
    assign it to `app.state.enterprise_context`, honoring any pre-injected override
    (so tests can supply `Fake_Clock_Rate_Limiter` + `InMemory_Identity_Store`).
  - Ensure `from agentforge.main import app` still imports cleanly under the keyless
    default (auth_enabled + rate_limit_enabled=False in tests).
  - _Requirements: 9.1, 9.2, 9.5, 10.1_
  - _Design: `main.py` wiring_

  - [x]* 14.1 Write a wiring unit test
    - Assert both new routers are registered, `app.state.enterprise_context` is
      populated, and every existing router carries `Depends(require_permission(...))`
      on its protected handlers (Req 7.6, 3.6).
    - _Requirements: 3.6, 7.6, 9.5_

- [x] 15. Extend `docs/decisions.md` with the Phase 5 design decisions
  - Append a "Phase 5 — Enterprise Controls" section covering: argon2id choice + params;
    the `Auth_Service` seam (JWT today, OAuth/SSO later without endpoint edits); RBAC
    as a static map + how to extend `ROLE_PERMISSIONS` without touching handlers;
    tenancy at the DAL + how new endpoints adopt `Principal` + `Authorization`
    dependencies + why cross-tenant is 404 (never 403); API-key + password hashing
    approach; how `Settings` supplies secrets while preserving keyless dev boot.
  - Include two short how-to guides at the end: "Adding a new role or permission" (edit
    `ROLE_PERMISSIONS`, add tests, no handler edits) and "Adopting auth on a new
    endpoint" (declare `Depends(require_permission(...))`, thread `principal.org_id`
    into an org-scoped store call; nothing else).
  - _Requirements: 11.1, 11.2, 11.3, 11.4_
  - _Design: Design Decisions & Why_

- [x] 16. Checkpoint — docs + wiring
  - Ensure `docs/decisions.md` renders correctly, `from agentforge.main import app`
    still imports under the keyless default, and the fast (property + unit) suite is
    green.
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Final full-suite keyless checkpoint (leave unchecked for the user)
  - Run the full keyless suite: all 10 Hypothesis property tests (>=100 iterations
    each), all unit tests, and all extended-router tests. Environment:
    `auth_enabled=True`, `rate_limit_enabled=False`, `profile=local`, `jwt_secret`
    unset (dev-generated), `InMemory_Identity_Store`, `InMemory_API_Key_Store`,
    `NoOp_Rate_Limiter` (Property 7's tests inject `Fake_Clock_Rate_Limiter`
    directly). Only tests marked `@pytest.mark.integration` — real Postgres + real
    Redis — remain deselected in this lane.
  - Report the pass/fail result and confirm no external credential was required.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Each task references specific acceptance criteria for traceability
  (`_Requirements: X.Y_`) and the design section it implements
  (`_Design: <section>_`); property sub-tasks additionally reference the design
  property they validate (`**Property N: <text>** ; **Validates: Requirements X.Y**`).
- The 10 Hypothesis property tests are the primary correctness surface for the
  enterprise core; unit tests cover error branches and shape guarantees; integration
  tests (`@pytest.mark.integration`) exercise real Postgres + Redis and are excluded
  from the default keyless lane.
- Structural, schema, seam-reuse, migration-runner, and documentation criteria are
  covered by unit / integration / smoke tests rather than property tests, per the
  design's Testing Strategy.
- Scope is strictly Phase 5: no production observability, evaluation frameworks,
  React frontend, third-party integrations, or cloud deployment.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "Settings extension + enterprise/ package scaffolding with base interfaces/stubs."
    },
    {
      "wave": 2,
      "tasks": ["2"],
      "description": "Domain models and RBAC_Policy (Properties 2, 3)."
    },
    {
      "wave": 3,
      "tasks": ["3"],
      "description": "Auth_Service — argon2id password hashing + JWT round-trip (Properties 4, 5)."
    },
    {
      "wave": 4,
      "tasks": ["4"],
      "description": "Identity_Store (in-memory + Postgres) + migration 0006."
    },
    {
      "wave": 5,
      "tasks": ["5", "6"],
      "description": "API_Key_Service (Property 6) and Rate_Limiter (Property 7) — independent, may run in parallel."
    },
    {
      "wave": 6,
      "tasks": ["7"],
      "description": "Principal + FastAPI dependencies (get_current_principal, require_permission) (Property 8)."
    },
    {
      "wave": 7,
      "tasks": ["8"],
      "description": "Composition root wiring for Auth / Identity / API-key / RBAC / Rate limiter."
    },
    {
      "wave": 8,
      "tasks": ["9"],
      "description": "Tenancy migration 0007 (org_id on top-level tenant-owned tables)."
    },
    {
      "wave": 9,
      "tasks": ["10"],
      "description": "Extend every existing tenant-owned store to require and constrain by org_id (Properties 1, 9)."
    },
    {
      "wave": 10,
      "tasks": ["11", "12"],
      "description": "New auth and orgs routers — independent, may run in parallel."
    },
    {
      "wave": 11,
      "tasks": ["13"],
      "description": "Apply auth + tenancy Depends to every existing router (Property 10)."
    },
    {
      "wave": 12,
      "tasks": ["14"],
      "description": "Register new routers + wire enterprise context in main.py."
    },
    {
      "wave": 13,
      "tasks": ["15", "16"],
      "description": "docs/decisions.md extension and docs/wiring checkpoint."
    },
    {
      "wave": 14,
      "tasks": ["17"],
      "description": "Final full-suite keyless checkpoint (left unchecked for the user)."
    }
  ],
  "notes": [
    "Each wave depends on all prior waves; interfaces precede implementations.",
    "Wave 5 tasks 5 and 6 are independent of each other and may run in parallel.",
    "Wave 10 tasks 11 and 12 are independent of each other and may run in parallel.",
    "Optional (*) test sub-tasks may be deferred without blocking dependent waves.",
    "Property 1 (tenant isolation) and Property 9 (tenant round-trip) both attach to task 10 because the store extensions are the enforcement point.",
    "Property 10 (endpoint permission mapping) attaches to task 13 because it is only meaningful once every existing router carries require_permission(...)."
  ]
}
```
