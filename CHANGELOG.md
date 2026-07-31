# Changelog

All notable changes to AgentForge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely: one section per release,
newest first, grouped by the kind of change. Dates are the date the work landed on `main`.

This file starts at v1.1. Everything before it is v1.0 — Phases 1–9 plus the
production-hardening pass — and is documented per phase in `docs/FEATURE_INVENTORY.md`
with the merged-PR index in `docs/SESSION_HANDOFF.md`.

## [Unreleased] — v1.1 work in progress

Branch `feat/v1.1-admin-crud-and-cost-defaults` ([PR #2](https://github.com/harshvardhan8058/Agentforgev2/pull/2)).
Closes three v1.1 roadmap items. **No migration is required** — every change reuses the
existing tables.

### Added

- **Member and team administration.** The org surface was create-and-add only; there was no
  way to see who was in an organization, change a role, or remove anybody. Added
  `GET /orgs/{id}/members`, `PATCH|DELETE /orgs/{id}/members/{user_id}`,
  `GET /orgs/{id}/teams`, `DELETE /orgs/{id}/teams/{team_id}`,
  `GET /orgs/{id}/teams/{tid}/members` and
  `DELETE /orgs/{id}/teams/{tid}/members/{user_id}`, all under `manage_members`, with the
  matching `Identity_Store` methods on both the in-memory and Postgres implementations, and
  a fully server-backed `MembersView`.
- **Last-owner invariant.** A demotion or removal that would leave an organization with
  nobody holding `owner` is refused with `last_owner` (400), evaluated over a
  `SELECT … FOR UPDATE` roster inside the writing transaction so concurrent requests cannot
  both slip through.
- **Named cost-rate presets.** `COST_RATE_PRESET` selects a shipped table of published
  per-model prices (`groq-public-2026-07`), so a deployment holding a provider key reports
  real costs without hand-authoring JSON. `COST_RATE_TABLE_JSON` still overrides it pair by
  pair, and `GROQ_MODEL` makes every priced model selectable.
- **`GET /analytics/cost-rates`** (`read`) reporting the effective preset, the per-model
  rates with each entry's source, the default rates, and whether the deployment prices
  anything — resolved through the same function that builds the `Cost_Model`, so reported
  and charged rates cannot drift. Surfaced as a Cost rates panel on the Analytics page.
- **Integration connection configuration.** `Integration_Connection`, its Postgres store and
  migration `0011` shipped in Phase 8 with no HTTP surface at all. Added
  `GET|POST /integrations/connections` and
  `GET|PATCH|DELETE /integrations/connections/{connection_id}` (`read` to list, the new
  `manage_integrations` permission to mutate), `update_config`/`delete` on both store
  implementations, and a Connection settings panel on the Integrations page.
- **Non-secret admission policy** for connection config
  (`integrations/config_policy.py`): credential-shaped keys, recognisable credential values
  (`xoxb-`, `ghp_`, `sk-`, `ya29.`, …), nested structures and oversized payloads are refused
  with `invalid_config` (400), and a refusal never echoes the submitted value.
- **`manage_integrations` permission**, granted from `admin` upwards, plus a property test
  that parses `frontend/src/auth/rbac.ts` and asserts the client RBAC mirror matches
  `enterprise/rbac.py` exactly. Drift there is silent in the worst direction: a permission
  the server grants but the client omits hides a control the caller is authorized to use.
- **Accessibility coverage** for the administration surfaces: axe in jsdom for the populated
  member/team and API-key views, plus a full-page Playwright axe scan of `/members`.

### Fixed

- **Cross-tenant write through team membership (security).**
  `POST /orgs/{id}/teams/{tid}/members` resolved the team only through the store's
  "is the user a member of the team's org?" guard, which a user holding memberships in
  **both** organizations satisfied — so a caller could add a member to a foreign tenant's
  team. The team is now resolved within the caller's org first; a foreign team is a 404.
- **Heading order (WCAG 1.3.1)** in `MembersView` and `ApiKeysView`: card titles are `h3`,
  so with no `h2` above them the document jumped `h1 → h3`.
- **Unordered rosters.** `list_org_members` had no `ORDER BY`, so the roster a client
  rendered could change order between calls; both store implementations now return
  oldest-first, identically.
- **`add_team_member` was not idempotent** across implementations: the in-memory store
  replaced `created_at` while Postgres kept the original row. Both now return the original.
- **Blank optional settings were treated as invalid.** `COST_RATE_PRESET=` (as shipped in
  `.env.production.example`) made `load_settings` abort, because pydantic-settings yields
  `""` rather than `None` — an unbootable production template. Empty and whitespace-only
  values for `COST_RATE_PRESET`, `COST_RATE_TABLE_JSON` and `GROQ_MODEL` now mean "unset".
  A genuinely misspelled preset still aborts startup, naming the setting.
- **Ownerless organizations were frozen.** The last-owner predicate decided on the
  post-state, so an organization that already held no owner refused every removal and
  demotion — including of an unrelated member — under an error that misstated the cause. The
  rule is now about the transition: an organization with no owner cannot lose one.
- **Wrong-team writes after creating a team.** `MembersView` fell back to the first team
  whenever the selected id was absent from the cached list — exactly the state a fresh
  create produces — so the detail card and its "Add to team" write could target a different
  team, and a failed refetch left it that way behind a success toast.
- **Stale team rosters after removing a member.** Removal drops the user from every team in
  the organization, but only the visible team's cache was invalidated.
- **Concurrency hardening in `Pg_Identity_Store`** (reasoned, not yet exercised against a
  live database): `add_team_member`'s membership guard takes `FOR SHARE` so it cannot commit
  alongside a concurrent `remove_membership` and orphan a team membership, and the roster
  lock read is `ORDER BY user_id` so two mutations in one organization cannot deadlock by
  locking the same rows in opposite orders.

### Changed

- `POST /orgs/{id}/teams` now returns `created_at`, so a client can place the created team
  into its list without inventing a timestamp.
- Connection config values are declared as JSON **scalars** in the contract rather than an
  opaque object: it states what the server accepts, rejects nesting at the transport layer,
  and gives generated clients a usable type.
- The client error normalizer classifies the domain 400 refusals (`last_owner`,
  `org_mismatch`, the uniqueness conflicts) as validation-class.
- Documentation corrected where it had drifted from the code: the backend image ships
  CPU-only torch under a CI-enforced 4 GB budget (not ~11–12 GB of CUDA), the committed
  OpenAPI contract is drift-checked in CI rather than "slightly stale", and the integrations
  management UI exists.

### Verification

Every gate below was run on the branch: backend `pytest -m 'not integration' -q` → **711
passed**; `cd frontend && npm run ci` → **439 passed**; `cd frontend && npm run e2e` →
**20 passed**; `python scripts/check_openapi.py` and `python scripts/scan_secrets.py` clean.

The live-PostgreSQL lane (`pytest -m integration`) was **not** run: no database could be
started in the authoring environment. New Postgres store behaviour is covered by
`test_pg_admin_crud_parity` and `test_pg_connection_update_and_delete_are_org_scoped`, which
have not yet executed against real SQL.

## v1.0 — 2026-07-09

Phases 1–9 (foundation, core RAG, agentic layer, multi-agent collaboration with human
approval, enterprise controls, production observability, React frontend, third-party
integrations, cloud deployment) plus the production-hardening pass: persistent keyless
domain stores, the documented keyless↔production configuration boundary, SSE through nginx,
a CPU-only backend image under a CI-enforced size budget, and an OpenAPI drift check.

See `docs/FEATURE_INVENTORY.md` for the per-feature inventory and
`docs/SESSION_HANDOFF.md` for the merged-PR index.
