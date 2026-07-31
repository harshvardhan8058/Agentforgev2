-- 0014_create_spend_budgets.sql
-- Per-organization spend budget: a monthly cost ceiling that can warn or block.
-- Strictly additive and idempotent (CREATE ... IF NOT EXISTS), so re-running is a no-op and
-- no prior-phase column is altered or dropped.
--
-- One row per organization (org_id is the primary key), because a budget is a property OF the
-- tenant rather than a collection it owns: "which of my three budgets applies" is a question
-- nobody asked, and a single row makes the enforcement read a primary-key lookup.
CREATE TABLE IF NOT EXISTS spend_budgets (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    -- The ceiling, in the same unit as usage_records.cost, with the same exactness. NUMERIC
    -- rather than a float for the same reason money is Decimal end to end.
    limit_amount NUMERIC(20, 8) NOT NULL CHECK (limit_amount >= 0),
    -- 'warn'  = report the overage; runs continue.
    -- 'block' = refuse new runs for the rest of the period.
    -- A CHECK rather than an enum type so adding an action stays an application change.
    action      TEXT NOT NULL DEFAULT 'warn' CHECK (action IN ('warn', 'block')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
