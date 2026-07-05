-- 0010_create_evaluations.sql
-- Datasets, items, runs, and per-item results -- all org-scoped (Req 8.1, 8.2, 8.3).
-- Strictly additive; every statement is idempotent (CREATE ... IF NOT EXISTS) so
-- re-running the migration is a no-op and no prior-phase column is altered (Req 8.4).
CREATE TABLE IF NOT EXISTS evaluation_datasets (
    id         UUID PRIMARY KEY,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS evaluation_items (
    id         UUID PRIMARY KEY,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL REFERENCES evaluation_datasets(id) ON DELETE CASCADE,  -- (Req 8.3)
    input      TEXT NOT NULL,
    expected   TEXT
);
CREATE INDEX IF NOT EXISTS evaluation_items_dataset_idx ON evaluation_items (dataset_id);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id              UUID PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    dataset_id      UUID NOT NULL REFERENCES evaluation_datasets(id) ON DELETE CASCADE,
    aggregate_score DOUBLE PRECISION NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS evaluation_runs_org_idx ON evaluation_runs (org_id, created_at);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id         UUID PRIMARY KEY,
    org_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    run_id     UUID NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,        -- (Req 8.3)
    item_id    UUID NOT NULL REFERENCES evaluation_items(id) ON DELETE CASCADE,
    evaluator  TEXT NOT NULL,
    score      DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS evaluation_results_run_idx ON evaluation_results (run_id);
