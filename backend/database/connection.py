import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Add it to backend/.env or your environment.")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def init_db() -> None:
    """Enable pgvector and make older local databases compatible with current models."""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text("ALTER TABLE IF EXISTS customers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")
            )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS system_prompt TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS provider VARCHAR DEFAULT 'gemini' NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS model_name VARCHAR DEFAULT 'gemini-2.5-flash' NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS provider_api_key TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS welcome_message TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS organization_id INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS customer_id INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS organization_id INTEGER")
        )
        conn.execute(
            text(
                """
                UPDATE documents
                SET organization_id = bots.organization_id
                FROM bots
                WHERE documents.bot_id = bots.id AND documents.organization_id IS NULL
                """
            )
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS filename VARCHAR")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS title VARCHAR")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS raw_text TEXT")
        )
        conn.execute(
            text("UPDATE documents SET raw_text = '' WHERE raw_text IS NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ALTER COLUMN raw_text DROP NOT NULL")
        )
        conn.execute(
            text("UPDATE documents SET filename = COALESCE(filename, title, source_url, CONCAT('document-', id)) WHERE filename IS NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ALTER COLUMN filename SET NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS file_path TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS file_size INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_status VARCHAR DEFAULT 'completed' NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_error TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER DEFAULT 0 NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS token_count INTEGER DEFAULT 0 NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW() NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS bot_id INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS organization_id INTEGER")
        )
        conn.execute(
            text(
                """
                UPDATE chunks
                SET bot_id = documents.bot_id
                FROM documents
                WHERE chunks.document_id = documents.id AND chunks.bot_id IS NULL
                """
            )
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER DEFAULT 0 NOT NULL")
        )
        conn.execute(
            text(
                """
                WITH ordered AS (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY document_id ORDER BY id) - 1 AS rn
                    FROM chunks
                )
                UPDATE chunks
                SET chunk_index = ordered.rn
                FROM ordered
                WHERE chunks.id = ordered.id
                """
            )
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS token_count INTEGER DEFAULT 0 NOT NULL")
        )
        conn.execute(
            text(
                """
                UPDATE chunks
                SET organization_id = documents.organization_id
                FROM documents
                WHERE chunks.document_id = documents.id AND chunks.organization_id IS NULL
                """
            )
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS organization_id INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS channel VARCHAR DEFAULT 'widget' NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW() NOT NULL")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS token_usage JSONB")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS organization_id INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS error_message TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bot_analytics_daily ADD COLUMN IF NOT EXISTS organization_id INTEGER")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS widget_config JSONB DEFAULT '{}'::jsonb")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'open'")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS is_fallback BOOLEAN DEFAULT FALSE")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS had_knowledge_hit BOOLEAN DEFAULT FALSE")
        )
        # V2 Upgrades
        conn.execute(
            text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS bio TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS avatar_url TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT jsonb_build_object('theme', 'system', 'language', 'en', 'notifications', jsonb_build_object('email', true, 'in_app', true))")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS description TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS category VARCHAR DEFAULT 'general'")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS avatar_url TEXT")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active'")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS tone VARCHAR DEFAULT 'neutral'")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT jsonb_build_object('web_search', false, 'file_analysis', true)")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS title VARCHAR")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE")
        )
        conn.execute(
            text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS shared_token VARCHAR UNIQUE")
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS platform_api_keys (
                    id SERIAL PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    encrypted_key BYTEA NOT NULL,
                    label VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'available',
                    allocated_to_bot_id INTEGER UNIQUE,
                    requests_count BIGINT NOT NULL DEFAULT 0,
                    tokens_used BIGINT NOT NULL DEFAULT 0,
                    last_used_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (allocated_to_bot_id) REFERENCES bots(id) ON DELETE SET NULL
                )
                """
            )
        )
        # ── Migrate existing platform_api_keys rows if the old schema is present ──
        # If the old `api_key` (plaintext TEXT) column exists and the new
        # `encrypted_key` (BYTEA) column does not yet exist, perform a migration.
        # We cannot decrypt old plaintext keys retroactively, so we mark them
        # disabled so admins can re-add them with the new encrypted form.
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    -- Add encrypted_key column if missing (schema upgrade)
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='platform_api_keys' AND column_name='api_key'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='platform_api_keys' AND column_name='encrypted_key'
                    ) THEN
                        ALTER TABLE platform_api_keys
                            ADD COLUMN encrypted_key BYTEA,
                            ADD COLUMN label VARCHAR,
                            ADD COLUMN status VARCHAR NOT NULL DEFAULT 'disabled',
                            ADD COLUMN allocated_to_bot_id_new INTEGER UNIQUE,
                            ADD COLUMN requests_count BIGINT NOT NULL DEFAULT 0,
                            ADD COLUMN tokens_used BIGINT NOT NULL DEFAULT 0,
                            ADD COLUMN last_used_at TIMESTAMP,
                            ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT NOW();

                        -- Fill encrypted_key with a placeholder so NOT NULL can be enforced
                        -- Admins must re-enter their keys through the new UI
                        UPDATE platform_api_keys
                        SET encrypted_key = convert_to('MIGRATED_PLACEHOLDER', 'UTF8'),
                            status = 'disabled';

                        ALTER TABLE platform_api_keys
                            ALTER COLUMN encrypted_key SET NOT NULL;

                        -- Drop old columns
                        ALTER TABLE platform_api_keys
                            DROP COLUMN IF EXISTS api_key,
                            DROP COLUMN IF EXISTS description,
                            DROP COLUMN IF EXISTS is_active,
                            DROP COLUMN IF EXISTS allotted_to_bot_id;
                    END IF;

                    -- Add missing columns to existing new-style table
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='platform_api_keys' AND column_name='encrypted_key'
                    ) THEN
                        ALTER TABLE platform_api_keys
                            ADD COLUMN IF NOT EXISTS label VARCHAR,
                            ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'available',
                            ADD COLUMN IF NOT EXISTS requests_count BIGINT NOT NULL DEFAULT 0,
                            ADD COLUMN IF NOT EXISTS tokens_used BIGINT NOT NULL DEFAULT 0,
                            ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP,
                            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();
                    END IF;
                END$$;
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_platform_api_keys_provider ON platform_api_keys (provider)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_platform_api_keys_status ON platform_api_keys (status)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_platform_api_keys_allocated_to_bot_id ON platform_api_keys (allocated_to_bot_id)")
        )
    except Exception as exc:
        print(f"Database startup migration warning: {exc}")





def create_vector_indexes() -> None:
    """Create indexes used by knowledge listing and semantic search."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_chunks_embedding_cosine
                ON chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_chunks_bot_id
                ON chunks (bot_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_bots_organization_id
                ON bots (organization_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_org_status
                ON documents (organization_id, processing_status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_bot_status
                ON documents (bot_id, processing_status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_conversation_sessions_bot_created
                ON conversation_sessions (bot_id, created_at)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_conversation_messages_bot_created
                ON conversation_messages (bot_id, created_at)
                """
            )
        )


def get_db():
    """FastAPI dependency that gives each request its own DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
