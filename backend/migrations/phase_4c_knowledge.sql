CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS filename VARCHAR;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS title VARCHAR;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS raw_text TEXT;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS file_path TEXT;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS file_size INTEGER;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_status VARCHAR DEFAULT 'completed' NOT NULL;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_error TEXT;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS token_count INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL;
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW() NOT NULL;

UPDATE documents
SET filename = COALESCE(filename, title, source_url, CONCAT('document-', id))
WHERE filename IS NULL;

UPDATE documents
SET raw_text = ''
WHERE raw_text IS NULL;

ALTER TABLE IF EXISTS documents ALTER COLUMN filename SET NOT NULL;
ALTER TABLE IF EXISTS documents ALTER COLUMN raw_text DROP NOT NULL;

ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS bot_id INTEGER;
ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL;
ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS token_count INTEGER DEFAULT 0 NOT NULL;

UPDATE chunks
SET bot_id = documents.bot_id
FROM documents
WHERE chunks.document_id = documents.id AND chunks.bot_id IS NULL;

WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY id) - 1 AS rn
  FROM chunks
)
UPDATE chunks
SET chunk_index = ordered.rn
FROM ordered
WHERE chunks.id = ordered.id;

CREATE INDEX IF NOT EXISTS ix_chunks_embedding_cosine
ON chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS ix_chunks_bot_id
ON chunks (bot_id);

CREATE INDEX IF NOT EXISTS ix_documents_bot_status
ON documents (bot_id, processing_status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_bot_source_url_not_null
ON documents (bot_id, source_url)
WHERE source_url IS NOT NULL;
