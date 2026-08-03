-- 0016_create_budget_notifications.sql
-- Which spend-budget thresholds an organization has already been told about, per period.
-- Strictly additive and idempotent (CREATE ... IF NOT EXISTS), so re-running is a no-op.
--
-- The problem this table solves is that a budget threshold is NOT a single-shot event. Every
-- other webhook event in the platform corresponds to one occurrence (a run finished, a
-- document was ingested); "spend passed 80%" is a *condition* that is true for every request
-- after it first becomes true. Emitting on the condition would send one webhook per request
-- for the rest of the month. So the first request to observe a crossing CLAIMS it here, and
-- only the winner notifies.
CREATE TABLE IF NOT EXISTS budget_notifications (
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- The period the crossing belongs to, computed (never stored) by `current_period()` —
    -- the same UTC calendar month the enforcement and the dashboard use. Part of the key, so
    -- a new month starts with a clean slate without any scheduled job to roll it over.
    period_start      TIMESTAMPTZ NOT NULL,
    -- The threshold crossed, as a whole percentage (80, 100). An INTEGER rather than the
    -- observed percentage: what is claimed is "the 80% notification", not "80.4% of budget".
    threshold_percent INTEGER NOT NULL CHECK (threshold_percent > 0),
    notified_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The primary key IS the claim. `INSERT ... ON CONFLICT DO NOTHING` makes claiming one
    -- atomic statement, so two concurrent requests that both observe the crossing cannot both
    -- notify — the loser sees zero rows affected and stays quiet. Doing this with a
    -- SELECT-then-INSERT would be a race with a month-long consequence.
    PRIMARY KEY (org_id, period_start, threshold_percent)
);

-- Reading is always "which thresholds has this org been told about this period", which the
-- primary key's leading columns already serve; no extra index is created, because an index
-- that no query uses is write cost with no read benefit.
