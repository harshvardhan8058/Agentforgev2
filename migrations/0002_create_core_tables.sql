-- 0002_create_core_tables.sql
-- Core relational tables plus the vector-embeddings table (Req 4.2, 4.3).

CREATE TABLE IF NOT EXISTS documents (
    id            UUID PRIMARY KEY,
    filename      TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    size_bytes    BIGINT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id            UUID PRIMARY KEY,
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    content       TEXT NOT NULL,
    overlap_prev  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (document_id, idx)
);

-- The vector column is sized to the CONFIGURED embedding dimension (Req 4.3).
-- ${EMBEDDING_DIMENSION} is templated by the migration runner from the
-- Configuration_Manager (default 384 for all-MiniLM-L6-v2).
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id      UUID PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    embedding     vector(${EMBEDDING_DIMENSION}) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunk_embeddings_vec_idx
    ON chunk_embeddings USING hnsw (embedding vector_cosine_ops);
