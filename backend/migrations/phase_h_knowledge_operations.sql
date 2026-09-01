-- Phase H: operational knowledge lifecycle, cancellation acknowledgement,
-- and conservative durable message-reservation reconciliation.
BEGIN;

ALTER TABLE ingestion_jobs
    ADD COLUMN IF NOT EXISTS cancellation_requested_at TIMESTAMP;

ALTER TABLE message_usage_reservations
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '1 hour');

UPDATE message_usage_reservations
SET last_heartbeat_at = COALESCE(last_heartbeat_at, updated_at, created_at, NOW()),
    expires_at = COALESCE(expires_at, updated_at, created_at, NOW()) + INTERVAL '1 hour';

CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_heartbeat
    ON message_usage_reservations (last_heartbeat_at);
CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_expires
    ON message_usage_reservations (expires_at);

COMMIT;
