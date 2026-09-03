# Production deployment

## Runtime topology

Run these as separate long-lived services:

1. PostgreSQL with pgvector: authoritative application, tenancy, job, conversation, quota, and vector data.
2. Redis: durable ARQ queue coordination, worker heartbeat, rate limits, semaphores, and short-lived caches. Enable AOF or use a managed Redis persistence tier.
3. One-off release migration: `python scripts/run_migrations.py` from `backend/`. It must complete before new production API/worker processes start.
4. API: `python scripts/start_api.py` from `backend/`. Production replicas perform a read-only Alembic-head check before starting Uvicorn; they never run DDL.
5. ARQ worker: `python scripts/start_worker.py` from `backend/`. Run at least one independently supervised worker.
6. Next.js frontend: build with the public API/app URLs, then run `npm run start`.
7. Private S3-compatible object storage shared logically by API and workers. API-local upload storage is development/test only.

`docker-compose.yml` expresses this topology with MinIO for a single-host deployment. For managed production, use equivalent independent services and managed Postgres/Redis/private object storage rather than exposing their ports publicly. See `PRODUCTION_ARCHITECTURE.md`; the first Railway procedure is `RAILWAY_PRODUCTION_SETUP.md`.

## Required production environment

Copy `backend/.env.example` and provide real secret values. At minimum:

- `APP_ENV=production`
- `DATABASE_URL`
- `REDIS_URL`
- `INGESTION_QUEUE_MODE=arq`
- `ARQ_QUEUE_NAME=ingestion`
- `JWT_SECRET` with at least 32 unpredictable bytes
- `PLATFORM_KEY_ENCRYPTION_KEY` as a retained Fernet key
- `REFRESH_COOKIE_SECURE=true`
- explicit `AUTH_ALLOWED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, and `FRONTEND_URL`
- `ALLOW_LEGACY_PLAINTEXT_BYOK=false` after the documented key migration
- `ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK=false`
- `OBJECT_STORAGE_PROVIDER=s3`
- `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY_ID`, `OBJECT_STORAGE_SECRET_ACCESS_KEY`, `OBJECT_STORAGE_REGION`, and optional S3-compatible `OBJECT_STORAGE_ENDPOINT`
- `CRAWLER_PROVIDER=firecrawl`
- `FIRECRAWL_API_KEY`
- at least one configured LLM/embedding provider key (`GEMINI_API_KEY` or `OPENAI_API_KEY`)

Frontend build variables:

- `NEXT_PUBLIC_API_URL=https://api.example.com`
- `NEXT_PUBLIC_APP_URL=https://app.example.com`

Never place provider, JWT, database, Firecrawl, or encryption secrets in `NEXT_PUBLIC_*` variables.

## Startup and health

1. Start PostgreSQL and Redis and wait for their native health checks.
2. Run `python scripts/run_migrations.py` once and require exit code `0`.
3. Start the API. An outdated schema is fatal; `scripts/start_api.py` verifies but does not migrate in production.
4. Start the worker and wait for its Redis heartbeat.
5. Require `GET /health/ready` to return HTTP 200 before routing customer traffic.
6. Start the frontend.

`/health/live` only proves that the API process responds. `/health/ready` also verifies PostgreSQL, Alembic head, Redis, ARQ mode, worker heartbeat, and private object storage in production.

## Pre-deploy checks

From `frontend/`: `npm ci`, `npm run typecheck`, `npm run lint`, `npm run build`.

From `backend/`: install `requirements.txt`, run the relevant `unittest` modules, then `python -m compileall -q .`.

For live browser acceptance, configure `E2E_EMAIL`, `E2E_PASSWORD`, and `E2E_BOT_ID`, then run `npm run test:e2e`. External provider and crawl tests incur real provider calls and must use a controlled acceptance environment.

## Rollout and rollback

- Take and verify a database backup before migration.
- Deploy API and worker from the same revision.
- Alembic migrations through `20260903_01` are forward-only; application rollback may require restoring the pre-deploy database backup as described in `backend/BACKUP_RESTORE.md`.
- Preserve `PLATFORM_KEY_ENCRYPTION_KEY`. Losing it makes encrypted provider credentials unrecoverable.
- Preserve/restore the private source-object bucket together with the database so document rows do not point to missing uploads. Migrate any legacy `file_path` originals before retiring their old filesystem.
