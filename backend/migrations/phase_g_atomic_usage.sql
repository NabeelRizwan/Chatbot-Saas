-- Phase G: durable message reservations and truthful knowledge/analytics fields.
BEGIN;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS logical_size_bytes INTEGER NOT NULL DEFAULT 0;

UPDATE documents
SET logical_size_bytes = COALESCE(file_size, octet_length(COALESCE(raw_text, '')), 0)
WHERE logical_size_bytes = 0;

ALTER TABLE conversation_messages
    ADD COLUMN IF NOT EXISTS retrieval_attempted BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS message_usage_reservations (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    period VARCHAR NOT NULL,
    idempotency_key VARCHAR NOT NULL,
    channel VARCHAR NOT NULL DEFAULT 'unknown',
    status VARCHAR NOT NULL DEFAULT 'reserved',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_message_usage_reservation_org_period_key
        UNIQUE (organization_id, period, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_org
    ON message_usage_reservations (organization_id);
CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_period
    ON message_usage_reservations (period);
CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_status
    ON message_usage_reservations (status);

COMMIT;
