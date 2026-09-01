# Production deployment

## Runtime topology

Run these as separate long-lived services:

1. PostgreSQL with pgvector: authoritative application, tenancy, job, conversation, quota, and vector data.
2. Redis: durable ARQ queue coordination, worker heartbeat, rate limits, semaphores, and short-lived caches. Enable AOF or use a managed Redis persistence tier.
3. API: `python scripts/start_api.py` from `backend/`. It runs Alembic to head and exits on migration failure before starting Uvicorn.
4. ARQ worker: `python scripts/start_worker.py` from `backend/`. Run at least one independently supervised worker.
5. Next.js frontend: build with the public API/app URLs, then run `npm run start`.
6. Persistent knowledge upload storage mounted at `KNOWLEDGE_UPLOAD_DIR` and shared by API and workers when local uploads are used.

`docker-compose.yml` expresses this topology for a single-host deployment. For managed production, use equivalent independent services and managed Postgres/Redis rather than exposing their ports publicly.

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
- `FIRECRAWL_API_KEY`
- at least one configured LLM/embedding provider key (`GEMINI_API_KEY` or `OPENAI_API_KEY`)
- persistent `KNOWLEDGE_UPLOAD_DIR`

Frontend build variables:

- `NEXT_PUBLIC_API_URL=https://api.example.com`
- `NEXT_PUBLIC_APP_URL=https://app.example.com`

Never place provider, JWT, database, Firecrawl, or encryption secrets in `NEXT_PUBLIC_*` variables.

## Startup and health

1. Start PostgreSQL and Redis and wait for their native health checks.
2. Start the API. A failed or outdated schema is fatal; do not bypass `scripts/start_api.py`.
3. Start the worker and wait for its Redis heartbeat.
4. Require `GET /health/ready` to return HTTP 200 before routing customer traffic.
5. Start the frontend.

`/health/live` only proves that the API process responds. `/health/ready` also verifies PostgreSQL, Alembic head, Redis, ARQ mode, and the worker heartbeat in production.

## Pre-deploy checks

From `frontend/`: `npm ci`, `npm run typecheck`, `npm run lint`, `npm run build`.

From `backend/`: install `requirements.txt`, run Phase A–I/security regression suites, then `python -m compileall -q .`.

For live acceptance, configure the Phase I fixture variables and run `npm run test:e2e`. External provider/crawl tests incur real provider calls and must use a controlled acceptance environment.

## Rollout and rollback

- Take and verify a database backup before migration.
- Deploy API and worker from the same revision.
- Alembic migration `20260821_01` is forward-only; application rollback requires restoring the pre-deploy database backup as described in `backend/BACKUP_RESTORE.md`.
- Preserve `PLATFORM_KEY_ENCRYPTION_KEY`. Losing it makes encrypted provider credentials unrecoverable.
- Preserve/restore `KNOWLEDGE_UPLOAD_DIR` together with the database so document rows do not point to missing uploads.
