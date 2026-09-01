BEGIN;

ALTER TABLE IF EXISTS website_crawls
    ADD COLUMN IF NOT EXISTS pages_eligible INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pages_skipped INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS duplicate_urls_removed INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_depth_reached INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS coverage_percent DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE IF EXISTS documents
    ADD COLUMN IF NOT EXISTS ingestion_job_id VARCHAR;

ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS ingestion_job_id VARCHAR;

ALTER TABLE IF EXISTS ingestion_jobs
    ADD COLUMN IF NOT EXISTS arq_job_id VARCHAR,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS audit_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS ix_documents_ingestion_job_id ON documents (ingestion_job_id);
CREATE INDEX IF NOT EXISTS ix_chunks_ingestion_job_id ON chunks (ingestion_job_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_arq_job_id ON ingestion_jobs (arq_job_id);

COMMIT;
