-- 0007_add_org_id_to_tenant_resources.sql
-- Tenant column on the top-level tenant-owned tables (Req 8.2).
--
-- Descendant tables inherit tenancy through their parent FK (chunks -> documents,
-- messages -> conversations, trace_entries -> agent_runs, approval_decisions and
-- run_checkpoints -> multi_agent_runs), so the stores' tenant guards join through the
-- parent's org_id; the top-level org_id column is defense-in-depth and gives the
-- audit-friendly "which org owns this row" answer (design: parent-join enforcement).
--
-- The migration is strictly additive (ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT
-- EXISTS), so re-running it is a no-op and no prior-phase column is dropped or altered
-- (Req 8.3). No production data exists yet, so no backfill step is required (Req 8.6).

ALTER TABLE documents        ADD COLUMN IF NOT EXISTS org_id UUID NOT NULL
    REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE conversations    ADD COLUMN IF NOT EXISTS org_id UUID NOT NULL
    REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE agent_runs       ADD COLUMN IF NOT EXISTS org_id UUID NOT NULL
    REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE multi_agent_runs ADD COLUMN IF NOT EXISTS org_id UUID NOT NULL
    REFERENCES organizations(id) ON DELETE CASCADE;

-- Composite (org_id, id) indexes accelerate tenant-filtered lookups on each table.
CREATE INDEX IF NOT EXISTS documents_org_id_idx        ON documents        (org_id, id);
CREATE INDEX IF NOT EXISTS conversations_org_id_idx    ON conversations    (org_id, id);
CREATE INDEX IF NOT EXISTS agent_runs_org_id_idx       ON agent_runs       (org_id, id);
CREATE INDEX IF NOT EXISTS multi_agent_runs_org_id_idx ON multi_agent_runs (org_id, id);
