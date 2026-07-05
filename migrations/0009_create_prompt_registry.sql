-- 0009_create_prompt_registry.sql
-- Named templates + immutable, monotonically versioned revisions (Req 8.1, 8.6).
-- Strictly additive; every statement is idempotent (CREATE ... IF NOT EXISTS) so
-- re-running the migration is a no-op and no prior-phase column is altered (Req 8.4).
CREATE TABLE IF NOT EXISTS prompt_templates (
    id         UUID PRIMARY KEY,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)                       -- one template per name per org
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id            UUID PRIMARY KEY,
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    template_id   UUID NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,  -- (Req 8.3)
    version       INTEGER NOT NULL CHECK (version >= 1),
    body          TEXT NOT NULL,                -- immutable: no UPDATE path (Req 4.2)
    variables     JSONB NOT NULL DEFAULT '[]',  -- declared variable names
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (template_id, version)               -- no two versions share a number (Req 8.6)
);
CREATE INDEX IF NOT EXISTS prompt_versions_tpl_idx ON prompt_versions (template_id, version);
