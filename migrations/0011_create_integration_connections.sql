-- 0011_create_integration_connections.sql
-- Optional per-org, NON-SECRET integration configuration (Req 11.1, 11.3, 11.4).
-- Strictly additive; idempotent (CREATE ... IF NOT EXISTS) so re-running is a no-op and
-- no prior-phase column is altered or dropped. There is NO column for a token or secret;
-- the schema structurally cannot hold credential material (Req 4.3, 11.4).
CREATE TABLE IF NOT EXISTS integration_connections (
    id           UUID PRIMARY KEY,
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,  -- tenant key (Req 11.1)
    integration  TEXT NOT NULL,                          -- slack | gmail | google_drive | github
    config       JSONB NOT NULL DEFAULT '{}'::jsonb,     -- NON-SECRET only (Req 11.4)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS integration_connections_org_idx
    ON integration_connections (org_id, integration);
