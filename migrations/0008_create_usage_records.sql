-- 0008_create_usage_records.sql
-- Per-call token usage + computed cost, org-scoped (Req 8.1, 8.2).
-- Strictly additive; every statement is idempotent (CREATE ... IF NOT EXISTS) so
-- re-running the migration is a no-op and no prior-phase column is altered (Req 8.4).
CREATE TABLE IF NOT EXISTS usage_records (
    id                UUID PRIMARY KEY,
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id           UUID REFERENCES users(id) ON DELETE SET NULL,   -- attribution (Req 2.1)
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_tokens     INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL CHECK (completion_tokens >= 0),
    total_tokens      INTEGER NOT NULL CHECK (total_tokens = prompt_tokens + completion_tokens),
    cost              NUMERIC(20, 8) NOT NULL,                         -- exact monetary (Req 2.2)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_records_org_time_idx ON usage_records (org_id, created_at);
