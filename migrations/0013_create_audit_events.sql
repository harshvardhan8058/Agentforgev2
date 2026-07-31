-- 0013_create_audit_events.sql
-- Enterprise audit trail: an append-only record of administrative actions, org-scoped.
-- Strictly additive; every statement is idempotent (CREATE ... IF NOT EXISTS) so re-running
-- the migration is a no-op and no prior-phase column is altered or dropped.
--
-- Design notes that the schema itself enforces:
--
--  * There is NO column that could hold a credential. An audit row records that an API key
--    was created, never the secret, and `metadata` is a JSONB object of non-secret scalars
--    admitted by `enterprise/audit.py` before the write.
--  * `actor_user_id` uses ON DELETE SET NULL rather than CASCADE: deleting a user must not
--    erase the record of what they did. The row survives with a null actor, which the API
--    renders as an unresolvable actor rather than silently attributing it to nobody.
--  * `org_id` CASCADEs, because an audit trail belongs to the tenant it describes and must
--    not outlive it (the tenant's right to deletion beats retention here).
--  * Append-only is a property of the application (no UPDATE/DELETE statement exists for
--    this table outside the org cascade), not of a database grant; a deployment that wants
--    it enforced in the database should REVOKE UPDATE, DELETE on this table from the app
--    role. Documented in docs/KNOWN_LIMITATIONS.md.
CREATE TABLE IF NOT EXISTS audit_events (
    id             UUID PRIMARY KEY,
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- Who acted. Exactly one of actor_user_id / actor_key_id is set, matching the two
    -- Principal kinds; both are nullable so the row outlives the actor it names.
    actor_kind     TEXT NOT NULL CHECK (actor_kind IN ('user', 'api_key')),
    actor_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_key_id   UUID,
    -- What happened, from the fixed vocabulary in `enterprise/audit.py` (dotted,
    -- past-tense: "member.removed"). TEXT rather than an enum type so adding an action is
    -- an application change, not a migration.
    action         TEXT NOT NULL,
    -- What it happened to. `target_type` is a coarse noun ("member", "api_key");
    -- `target_id` is free-form so it can hold a UUID, an email, or an integration name.
    target_type    TEXT NOT NULL,
    target_id      TEXT,
    -- Non-secret scalars only (e.g. {"role": "admin"}), admitted before the write.
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The only read pattern: one org's events, newest first, optionally filtered by action or
-- actor and bounded by time. `(org_id, created_at DESC, id DESC)` serves the listing and
-- its keyset pagination; `id DESC` breaks ties so a page boundary cannot repeat or skip a
-- row when several events share a timestamp.
CREATE INDEX IF NOT EXISTS audit_events_org_time_idx
    ON audit_events (org_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS audit_events_org_action_time_idx
    ON audit_events (org_id, action, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_org_actor_time_idx
    ON audit_events (org_id, actor_user_id, created_at DESC);
