-- 0005_create_multi_agent_runs.sql
-- Multi-agent runs, human approval decisions, and resumable run checkpoints (Req 10).
-- Reuses the existing conversations, messages, agent_runs, and trace_entries tables:
-- agent messages continue to live in `messages` (role = role_id) and per-agent trace
-- entries in `trace_entries`, with only the multi-agent-specific tables added below.

CREATE TABLE IF NOT EXISTS multi_agent_runs (
    id                 UUID PRIMARY KEY,
    conversation_id    UUID REFERENCES conversations(id) ON DELETE CASCADE,
    task               TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'running',   -- running | awaiting_approval | terminated
    termination_reason TEXT,                              -- completed | max-rounds-reached | ...
    final_output       TEXT,                              -- Final_Output content on completion (Req 10.5)
    final_citations    JSONB NOT NULL DEFAULT '[]'::jsonb,-- preserved citations (Req 8.3, 10.5)
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approval_decisions (
    id             UUID PRIMARY KEY,
    run_id         UUID NOT NULL REFERENCES multi_agent_runs(id) ON DELETE CASCADE,
    checkpoint     TEXT NOT NULL,                         -- after_plan | before_finalize
    decision_type  TEXT NOT NULL,                         -- approve | reject | edit (Req 10.3)
    feedback       TEXT,                                   -- reject feedback (Req 5.3)
    edited_content TEXT,                                   -- edit content (Req 5.4)
    position       INTEGER NOT NULL,                       -- ordinal of the decision within the run
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, position)
);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    id          UUID PRIMARY KEY,
    run_id      UUID NOT NULL REFERENCES multi_agent_runs(id) ON DELETE CASCADE,
    checkpoint  TEXT NOT NULL,                             -- after_plan | before_finalize
    blackboard  JSONB NOT NULL,                            -- snapshot to resume from (Req 10.4)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS multi_agent_runs_conversation_idx
    ON multi_agent_runs (conversation_id);
CREATE INDEX IF NOT EXISTS run_checkpoints_run_idx
    ON run_checkpoints (run_id, created_at);
