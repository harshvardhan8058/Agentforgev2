# Configuration Boundary — Keyless `local` ↔ Credentialed `production`

This document is the authoritative, per-setting reference for which settings are
**required** vs **optional** in each Environment_Profile (`local` and `production`), and it
records the keyless↔production configuration boundary that the platform enforces. It is
**documentation only** — it describes existing behavior and introduces **no code change**
(production-hardening B2 / Requirement 2).

AgentForge boots **keyless by default**: `docker compose up` brings the full stack up under
`PROFILE=local` with zero credentials. The `production` profile is the credentialed path: it
is supplied secrets from a Secret_Source (an operator-managed `.env` or an orchestrator
secret store) through the production Compose overlay, and never from any version-controlled
file.

## Config model — required vs optional by profile

Settings are named by their environment-variable name. `SecretStr` values are typed as
secrets (`pydantic.SecretStr`) and are sourced only at runtime.

| Setting | Type | `local` | `production` |
|---------|------|---------|--------------|
| `DATABASE_URL` | str (DSN, non-secret) | **required** — supplied by the compose default | **required** |
| `REDIS_URL` | str (DSN, non-secret) | **required** — supplied by the compose default | **required** |
| `PROFILE` | `local` / `production` | `local` | `production` |
| `USE_DATABASE` | bool | `true` (set by compose) — persists Domain_Stores to Postgres | `true` (implied by `profile == "production"`) |
| `JWT_SECRET` | `SecretStr` | **optional** — a per-boot dev secret is generated when absent | **required** (when `auth_enabled`) — boot aborts if absent |
| `GROQ_API_KEY` | `SecretStr` | optional (LLM provider disabled → deterministic fallback) | optional (feature-gated) |
| `HOSTED_EMBEDDING_API_KEY` | `SecretStr` | optional (hosted embeddings disabled) | optional (feature-gated) |
| `SEARCH_API_KEY` | `SecretStr` | optional (web search disabled) | optional (feature-gated) |
| `LANGSMITH_API_KEY` | `SecretStr` | optional (keyless NoOp trace exporter) | optional (feature-gated) |
| `SLACK_BOT_TOKEN`, `GMAIL_TOKEN`, `GOOGLE_DRIVE_TOKEN`, `GITHUB_TOKEN` | `SecretStr` | optional (integration disabled) | optional (feature-gated) |

**Required non-secret settings** (both profiles) are `DATABASE_URL` and `REDIS_URL`; they are
declared with `Field(...)` on `Settings` and always carry a non-secret compose default in the
`local` stack. **`JWT_SECRET`** is the only required *secret*, and only in `production`.

All other credentials are **optional and feature-gated**: leaving them blank keeps the
corresponding capability disabled so that no external network call is ever made without a
credential — preserving the keyless promise in both profiles.

## Boundary behavior (existing guards — confirmed, unchanged)

1. **Missing required non-secret setting → abort naming the key.** If a documented required
   non-secret setting (`DATABASE_URL`, `REDIS_URL`) is absent, `load_settings` aborts startup
   before any route is served and reports the missing setting **by name** through the existing
   configuration error path (`ConfigError`). This holds in both profiles (Requirement 2.6).

2. **Missing `JWT_SECRET` in `production` → abort naming the key.** When `PROFILE=production`
   (with auth enabled) and `JWT_SECRET` is absent, `load_settings` aborts before serving any
   request and reports `JWT_SECRET` by name via the same `ConfigError` path (Requirement 2.3).

3. **`JWT_SECRET` is a `SecretStr` sourced at runtime — never committed.** In `production`,
   the signing secret is consumed as a `SecretStr` supplied from the Secret_Source through the
   overlay (`JWT_SECRET: ${JWT_SECRET}` in `docker-compose.production.yml`). It is **never**
   read from a version-controlled file (Requirement 2.2).

4. **No dev-secret fallback under `production`.** `build_auth_service` generates a per-boot
   development secret (`secrets.token_urlsafe(...)`) **only** when `PROFILE=local`. Under
   `production` it raises `ConfigError` instead of falling back to a generated secret, so the
   production path never silently boots with an ephemeral secret (Requirement 2.7).

5. **Keyless `local` boot needs no secret.** With `PROFILE=local` and no credentials, the
   backend boots using the existing per-boot development secret path and requires no secret to
   be supplied (Requirement 2.4).

## Persistence across the boundary (`USE_DATABASE`)

`USE_DATABASE` selects whether the ten Domain_Stores persist to the running Postgres. The
derived selector `Settings.persist_domain_stores()` returns `use_database or profile ==
"production"`, so:

- **`local`:** the compose file sets `USE_DATABASE=true`, so the default stack persists over a
  **DSN only (no credential)** and survives `docker compose restart`.
- **`production`:** persistence is implied by `profile == "production"` (and set explicitly in
  the overlay for clarity).

The deterministic keyless unit lane never sets `USE_DATABASE`, so `use_database` defaults
`False` and the stores stay in-memory and reproducible.

## Cost pricing (`COST_RATE_PRESET`, `COST_RATE_TABLE_JSON`, `COST_DEFAULT_*_PER_1K`)

All three are **optional in both profiles**, and none is a credential. Together they decide
what the usage/cost analytics report, and they resolve lowest precedence first:

1. **`COST_DEFAULT_PROMPT_PER_1K` / `COST_DEFAULT_COMPLETION_PER_1K`** (default `0.0`) — the
   rate for any `(provider, model)` pair the stages below do not list.
2. **`COST_RATE_PRESET`** (default unset) — a **named preset** of published per-model list
   prices shipped in `src/agentforge/observability/cost_presets.py`. Known presets:
   `groq-public-2026-07`. Setting this one variable is enough for a deployment that holds a
   `GROQ_API_KEY` to report real costs.
3. **`COST_RATE_TABLE_JSON`** (default unset) — explicit per-1K rates keyed
   `"provider:model"`, e.g.
   `{"groq:llama-3.1-8b-instant": {"prompt": "0.00005", "completion": "0.00008"}}`. Entries
   here **override the preset** for the same pair, so a preset can be adopted wholesale and
   corrected model by model.

Notes and guarantees:

- **Keyless stays free and deterministic.** With none of the three set, every call costs
  exactly `Decimal("0")` — correct, because the keyless Fallback provider runs locally.
- **Rates are indicative.** Preset values are the vendor's public list prices as of the date
  in the preset name; a deployment with negotiated, batch, or cached-input pricing should
  override the affected pairs. All arithmetic is `Decimal`, and rates cross the API as exact
  strings, so no float drift is possible.
- **A typo aborts startup.** An unknown `COST_RATE_PRESET` fails in `load_settings`, naming
  the setting, rather than leaving the deployment silently unpriced.
- **Verify at runtime.** `GET /analytics/cost-rates` (requires `read`) reports the effective
  preset, the per-model rates with their source (`preset` / `override`), the default rates,
  and whether the deployment prices anything at all. `GET /analytics/usage` carries the same
  fact as `cost_rates_configured`, which is how the console distinguishes "nothing spent"
  from "nothing priced". Both are shown on the Analytics page.

## See also

- `.env.example` — every `local` setting with placeholder values.
- `.env.production.example` — every `production` setting with placeholder values.
- `docs/INFRASTRUCTURE.md` — infrastructure and image notes.
