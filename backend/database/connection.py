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

DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT = float(os.getenv("DB_POOL_TIMEOUT", "30.0"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))
DB_POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() in ("true", "1", "yes")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=DB_POOL_PRE_PING,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    pool_recycle=DB_POOL_RECYCLE,
)


def get_pool_status() -> dict:
    """Returns runtime metrics for database connection pool."""
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checkedin": pool.checkedin(),
        "checkedout": pool.checkedout(),
        "overflow": pool.overflow(),
    }


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
                text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS logical_size_bytes INTEGER DEFAULT 0 NOT NULL")
            )
            conn.execute(
                text(
                    "UPDATE documents SET logical_size_bytes = COALESCE(file_size, octet_length(COALESCE(raw_text, '')), 0) "
                    "WHERE logical_size_bytes = 0"
                )
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
            conn.execute(
                text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS retrieval_attempted BOOLEAN DEFAULT FALSE")
            )
            conn.execute(
                text(
                    """
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
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_org ON message_usage_reservations (organization_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_period ON message_usage_reservations (period)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_status ON message_usage_reservations (status)"))
            conn.execute(text("ALTER TABLE IF EXISTS message_usage_reservations ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMP DEFAULT NOW() NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS message_usage_reservations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '1 hour') NOT NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_heartbeat ON message_usage_reservations (last_heartbeat_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_message_usage_reservations_expires ON message_usage_reservations (expires_at)"))
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
                text("ALTER TABLE IF EXISTS bots ADD COLUMN IF NOT EXISTS allowed_origins JSONB DEFAULT '[]'::jsonb NOT NULL")
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
                text("ALTER TABLE IF EXISTS conversation_sessions ADD COLUMN IF NOT EXISTS public_token_hash VARCHAR")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_conversation_sessions_public_token_hash ON conversation_sessions (public_token_hash)")
            )
            conn.execute(
                text("ALTER TABLE IF EXISTS conversation_messages ADD COLUMN IF NOT EXISTS client_turn_id VARCHAR")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_conversation_messages_client_turn_id ON conversation_messages (client_turn_id)")
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_messages_public_turn "
                    "ON conversation_messages (bot_id, session_id, client_turn_id) "
                    "WHERE client_turn_id IS NOT NULL"
                )
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
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
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

                            UPDATE platform_api_keys
                            SET encrypted_key = convert_to('MIGRATED_PLACEHOLDER', 'UTF8'),
                                status = 'disabled';

                            ALTER TABLE platform_api_keys
                                ALTER COLUMN encrypted_key SET NOT NULL;

                            ALTER TABLE platform_api_keys
                                DROP COLUMN IF EXISTS api_key,
                                DROP COLUMN IF EXISTS description,
                                DROP COLUMN IF EXISTS is_active,
                                DROP COLUMN IF EXISTS allotted_to_bot_id;
                        END IF;

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

            # ── Phase 11-15 Knowledge Persistence & Lifecycle Tables ──
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS websites (
                        id SERIAL PRIMARY KEY,
                        bot_id INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
                        organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
                        root_url TEXT NOT NULL,
                        domain VARCHAR NOT NULL,
                        status VARCHAR NOT NULL DEFAULT 'ready',
                        crawl_status VARCHAR NOT NULL DEFAULT 'ready',
                        last_crawled_at TIMESTAMP,
                        next_scheduled_crawl_at TIMESTAMP,
                        active_crawl_id INTEGER,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_websites_bot_root_url UNIQUE (bot_id, root_url)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_websites_bot_id ON websites (bot_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_websites_domain ON websites (domain)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_websites_status ON websites (status)"))

            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS website_crawls (
                        id SERIAL PRIMARY KEY,
                        website_id INTEGER NOT NULL REFERENCES websites(id) ON DELETE CASCADE,
                        bot_id INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
                        organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        completed_at TIMESTAMP,
                        pages_discovered INTEGER NOT NULL DEFAULT 0,
                        pages_crawled INTEGER NOT NULL DEFAULT 0,
                        pages_failed INTEGER NOT NULL DEFAULT 0,
                        chunks_created INTEGER NOT NULL DEFAULT 0,
                        chunks_updated INTEGER NOT NULL DEFAULT 0,
                        chunks_deleted INTEGER NOT NULL DEFAULT 0,
                        embeddings_created INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR NOT NULL DEFAULT 'processing',
                        error_summary TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_website_crawls_website_id ON website_crawls (website_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_website_crawls_bot_id ON website_crawls (bot_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_website_crawls_status ON website_crawls (status)"))
            conn.execute(text("ALTER TABLE IF EXISTS website_crawls ADD COLUMN IF NOT EXISTS pages_eligible INTEGER DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS website_crawls ADD COLUMN IF NOT EXISTS pages_skipped INTEGER DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS website_crawls ADD COLUMN IF NOT EXISTS duplicate_urls_removed INTEGER DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS website_crawls ADD COLUMN IF NOT EXISTS max_depth_reached INTEGER DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS website_crawls ADD COLUMN IF NOT EXISTS coverage_percent DOUBLE PRECISION DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS website_crawls ADD COLUMN IF NOT EXISTS audit_metadata JSONB DEFAULT '{}'::jsonb NOT NULL"))

            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS website_id INTEGER"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS crawl_id INTEGER"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS canonical_url TEXT"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS crawl_depth INTEGER DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'ready' NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP DEFAULT NOW() NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP DEFAULT NOW() NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS last_crawled_at TIMESTAMP"))

            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS website_id INTEGER"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS crawl_id INTEGER"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS content_hash VARCHAR"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'ready' NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR DEFAULT 'gemini' NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS embedding_model VARCHAR DEFAULT 'gemini-embedding-001' NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS embedding_version INTEGER DEFAULT 1 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW() NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS chunks ADD COLUMN IF NOT EXISTS ingestion_job_id VARCHAR"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_ingestion_job_id ON chunks (ingestion_job_id)"))
            conn.execute(text("ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS ingestion_job_id VARCHAR"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_ingestion_job_id ON documents (ingestion_job_id)"))
            conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS arq_job_id VARCHAR"))
            conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0 NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS audit_metadata JSONB DEFAULT '{}'::jsonb NOT NULL"))
            conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS cancellation_requested_at TIMESTAMP"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_arq_job_id ON ingestion_jobs (arq_job_id)"))
    except Exception as exc:
        raise RuntimeError(f"Database compatibility upgrade failed: {exc}") from exc





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
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_chunks_bot_status
                ON chunks (bot_id, status)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_chunks_content_hash
                ON chunks (content_hash)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_documents_content_hash
                ON documents (content_hash)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id SERIAL PRIMARY KEY,
                    job_id VARCHAR UNIQUE NOT NULL,
                    organization_id INTEGER REFERENCES organizations(id),
                    bot_id INTEGER NOT NULL REFERENCES bots(id),
                    website_id INTEGER REFERENCES websites(id),
                    crawl_id INTEGER REFERENCES website_crawls(id),
                    document_id INTEGER REFERENCES documents(id),
                    job_type VARCHAR DEFAULT 'crawl' NOT NULL,
                    status VARCHAR DEFAULT 'queued' NOT NULL,
                    progress_percent INTEGER DEFAULT 0 NOT NULL,
                    current_stage VARCHAR DEFAULT 'queued' NOT NULL,
                    pages_discovered INTEGER DEFAULT 0 NOT NULL,
                    pages_crawled INTEGER DEFAULT 0 NOT NULL,
                    pages_failed INTEGER DEFAULT 0 NOT NULL,
                    documents_created INTEGER DEFAULT 0 NOT NULL,
                    chunks_created INTEGER DEFAULT 0 NOT NULL,
                    embeddings_created INTEGER DEFAULT 0 NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    last_heartbeat TIMESTAMP DEFAULT NOW() NOT NULL,
                    error_code VARCHAR,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
                )
                """
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_bot_id ON ingestion_jobs (bot_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_status ON ingestion_jobs (status)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_created_at ON ingestion_jobs (created_at)")
        )
        conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS arq_job_id VARCHAR"))
        conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0 NOT NULL"))
        conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS audit_metadata JSONB DEFAULT '{}'::jsonb NOT NULL"))
        conn.execute(text("ALTER TABLE IF EXISTS ingestion_jobs ADD COLUMN IF NOT EXISTS cancellation_requested_at TIMESTAMP"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_arq_job_id ON ingestion_jobs (arq_job_id)"))



def get_db():
    """FastAPI dependency that gives each request its own DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
