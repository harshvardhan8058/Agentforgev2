-- 0012_add_document_content_hash.sql
-- Content hash on documents, so re-uploading the same file is recognised (Req 7.3).
--
-- Ingestion had no notion of document identity beyond the generated id, so uploading the
-- same file twice produced two complete copies: two document rows, two full sets of
-- chunks, and two sets of embeddings. Besides the duplicated storage and the wasted
-- embedding work, the corpus listing showed the same filename repeatedly, which reads as
-- a defect. The hash is of the uploaded bytes, so it identifies content rather than
-- filename — the same file uploaded under two names is still one document.
--
-- The column is NULLABLE and there is no backfill: the raw bytes are not retained after
-- extraction, so a hash cannot be computed for documents ingested before this migration.
-- Those rows keep NULL and are simply never matched as duplicates.
--
-- The index is deliberately NOT unique. A unique constraint is the only true guard
-- against two concurrent uploads of the same file, but it would turn that race into a
-- failed request, and a rare duplicate row is exactly today's behaviour — strictly less
-- harmful than a 500. Duplicate detection is therefore an application-level lookup
-- (Ingestion_Service) and this index exists to make that lookup cheap.
--
-- Strictly additive (ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS), so
-- re-running it is a no-op (Req 8.3).

ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE INDEX IF NOT EXISTS documents_org_content_hash_idx
    ON documents (org_id, content_hash);
