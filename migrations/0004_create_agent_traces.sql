-- 0004_create_agent_traces.sql
-- Lightweight observability: agent runs and their ordered trace entries (Req 10.1-10.3).

CREATE TABLE IF NOT EXISTS agent_runs (
    id                 UUID PRIMARY KEY,
    conversation_id    UUID REFERENCES conversations(id) ON DELETE CASCADE,
    termination_reason TEXT,                  -- final-answer | iteration-limit-reached (Req 1.7)
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trace_entries (
    id         UUID PRIMARY KEY,
    run_id     UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,              -- ascending within the run (Req 10.1, 10.3)
    step_type  TEXT NOT NULL,                 -- reason | tool_call | observe
    tool_name  TEXT,                          -- set for tool_call entries (Req 10.2)
    outcome    TEXT,                          -- invocation outcome (Req 10.2)
    detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, ordinal)
);

CREATE INDEX IF NOT EXISTS trace_entries_run_ordinal_idx
    ON trace_entries (run_id, ordinal);
