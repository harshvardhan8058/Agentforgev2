-- 0003_create_conversations.sql
-- Persistent multi-turn conversation history (Req 8.1-8.4).

CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id               UUID PRIMARY KEY,
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,           -- user | assistant | tool | system
    content          TEXT NOT NULL,
    position         INTEGER NOT NULL,        -- ordinal within the conversation (Req 8.2, 8.3)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, position)
);

CREATE INDEX IF NOT EXISTS messages_conversation_pos_idx
    ON messages (conversation_id, position);
