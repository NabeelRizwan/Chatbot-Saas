ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS allowed_origins JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE conversation_sessions
    ADD COLUMN IF NOT EXISTS public_token_hash VARCHAR;

CREATE INDEX IF NOT EXISTS ix_conversation_sessions_public_token_hash
    ON conversation_sessions (public_token_hash);

ALTER TABLE conversation_messages
    ADD COLUMN IF NOT EXISTS client_turn_id VARCHAR;

CREATE INDEX IF NOT EXISTS ix_conversation_messages_client_turn_id
    ON conversation_messages (client_turn_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_messages_public_turn
    ON conversation_messages (bot_id, session_id, client_turn_id)
    WHERE client_turn_id IS NOT NULL;
