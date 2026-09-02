# Railway Deployment Readiness Report

Date: 2026-09-02
Base commit: `44c670e` (Add multi-entity conversational RAG and widget delivery latency fixes)
Result commit: `874c19d` (Prepare Railway multi-service deployment)

Scope: smallest possible deployment-specific changes. Phase L/L.2/L.3/L.4 RAG
behavior, retrieval, query contract, Gemini models, Firecrawl, embeddings, and
auth were not touched. `git diff --stat` for this task: 2 files modified
(`backend/Dockerfile`, `backend/scripts/start_api.py`), 1 test file added.

## 1. PORT fix

`backend/scripts/start_api.py` exec'd Uvicorn with a hardcoded `--port 8000`.
Railway assigns the listen port dynamically via `PORT`. Changed to:

```python
port = str(int(os.getenv("PORT", "8000")))
```

Bind stays `0.0.0.0`. Local/Docker-compose usage without `PORT` set is
unaffected (still defaults to 8000). Migration-before-serve ordering
(`upgrade_to_head()` before `os.execv`) is unchanged.

Frontend needs no change: `next start` (invoked by `npm run start`) already
reads `PORT` from the real process environment natively (confirmed against
Next.js CLI docs) — only `.env*` files are excluded from this because the
HTTP server starts before they load. Railway sets `PORT` as a real process
env var, so this works out of the box.

## 2. Playwright production dependency finding

`backend/Dockerfile` ran `playwright install --with-deps chromium`, downloading
a full Chromium browser plus system libraries on every build. Traced actual
usage:

- **Active production crawler is Firecrawl** (`services/firecrawl_service.py`,
  external HTTP API, no browser needed) — confirmed via
  `document_processing_service.py` importing `firecrawl_service`, not
  `crawl4ai_service`.
- `services/crawl4ai_service.py` imports `playwright` but is only used by
  legacy tests, never imported by the active knowledge/ingestion pipeline.
- **Found one live exception**: `services/scraper_service.py` imports
  `playwright.sync_api` and is wired into the mounted `/ingest/website` route
  (`routes/ingest_routes.py`, included in `main.py`). This route is **not**
  called by the frontend/dashboard (confirmed: no references in
  `frontend/**`) and its `use_playwright` flag defaults to `False`
  (`schemas/schemas.py: WebsiteIngestRequest.use_playwright: bool = False`).
  The default static-scraping path (`httpx` + `BeautifulSoup`) needs no
  browser.

Removed the Chromium install from the Dockerfile. This is not fully
consequence-free: if `/ingest/website` is ever called with
`"use_playwright": true` in the deployed Railway image, that one legacy
endpoint will fail (no Chromium binary). This is documented, not hidden, and
guarded by a new test (`test_ingest_website_playwright_flag_defaults_to_false`)
that will fail loudly if that default ever flips without revisiting this
Dockerfile change.

## 3. Upload / API-worker storage finding — ACTION REQUIRED

Traced the full path:

`knowledge_routes.py: upload_document` → `document_processing_service.py:
create_file_document` → `save_upload()` writes the file to
`UPLOAD_DIR / bot_id / <uuid>-<filename>` where
`UPLOAD_DIR = Path(os.getenv("KNOWLEDGE_UPLOAD_DIR", BACKEND_DIR / "storage" / "knowledge"))`
→ `Document.file_path` stores that **absolute local path** in Postgres →
`enqueue_ingestion_job` → ARQ `document_task`
(`workers/worker.py`) → `execute_document_job`
(`workers/embedding_worker.py`) → `process_document_ingestion` reads
`document.file_path` from disk (`extract_text_from_file(document.file_path, ...)`).

**Confirmed: the worker expects to read a local file path written by the API
process.** On Railway, the API and ARQ worker are separate services with
independent, non-shared container filesystems (a Railway Volume attaches to
exactly one service). A file uploaded through the dashboard would be written
by the API container and be invisible to the worker container, causing every
document (PDF/TXT/DOCX) **upload** job to fail on Railway once API and worker
run as separate services.

**Firecrawl/website ingestion is unaffected** — the worker fetches URLs over
HTTP directly, no shared filesystem is involved.

**No existing object-storage abstraction was found** in the repository
(`boto3`, `s3`, `blob`, `azure.storage`, `google.cloud.storage`, `minio` — no
matches anywhere in `backend/`). Per instructions, I am **not** selecting a
vendor. Options to choose from, in increasing effort:

1. **Railway Volume on a single combined service.** Run API + worker as one
   Railway service (one container, one filesystem) instead of two. Smallest
   change, but loses independent worker scaling/restarts and no longer
   matches the "separate services" topology this task assumes.
2. **Railway Volume shared via a network filesystem trick is not supported.**
   Railway Volumes are single-service only; this option does not exist as
   stated and is listed only to rule it out explicitly.
3. **Object storage (S3-compatible).** Upload to S3, Cloudflare R2, Backblaze
   B2, or Railway's own bucket add-on; store an object key instead of a local
   path in `Document.file_path`/`file_path`; worker downloads by key before
   extraction. This is the architecturally correct fix and matches the
   pattern already used for Firecrawl (fetch over network, not shared disk),
   but requires a new dependency, new credentials, and changes to
   `save_upload()`/`extract_text_from_file()` call sites — explicitly outside
   "smallest possible" scope for this task.
4. **Route uploads through the API only (no worker handoff for file
   uploads).** Process PDF/TXT/DOCX synchronously in the API request instead
   of enqueuing to ARQ. Avoids cross-service storage entirely but changes the
   upload UX (blocking request) and duplicates logic that currently lives in
   the worker path.

**No implementation choice was made.** This is the one blocker in an
otherwise-ready deployment.

## 4. Backend Railway config

| Setting | Value |
| --- | --- |
| Root directory | `backend` |
| Build | `backend/Dockerfile` |
| Start command | `python scripts/start_api.py` (already the Dockerfile `CMD`; now honors `PORT`) |
| Health check | `/health/live` (do **not** use `/health/ready` as the deploy gate — it requires a live worker heartbeat in production ARQ mode and will legitimately 503 before the worker service exists) |
| Depends on | Postgres (pgvector), Redis |

## 5. Worker Railway config

| Setting | Value |
| --- | --- |
| Root directory | `backend` (same image as backend) |
| Build | `backend/Dockerfile` |
| Start command override | `python scripts/start_worker.py` |
| Health check | none (ARQ worker is not an HTTP service; readiness is observed via the Redis heartbeat key the backend's `/health/ready` checks) |
| Depends on | Postgres, Redis (same instances as backend) |
| Blocker | See Section 3 — uploaded-file jobs will fail until upload storage is resolved. Website/Firecrawl jobs are unaffected. |

## 6. Frontend Railway config

| Setting | Value |
| --- | --- |
| Root directory | `frontend` |
| Build | `frontend/Dockerfile` (multi-stage: `npm ci` → `npm run build` with `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_APP_URL` build args → `npm run start`) |
| Start command | `npm run start` (`next start`; honors Railway's `PORT` natively, no change needed) |
| Rebuild trigger | Any change to `NEXT_PUBLIC_*` values requires a rebuild — they are inlined at build time, not read at runtime |

## 7. Redis wiring

`utils/redis_client.py: get_redis_url()` reads `os.getenv("REDIS_URL", "redis://localhost:6379/0")`.
`workers/worker.py: WorkerSettings.redis_settings` reads the same `REDIS_URL`
via `RedisSettings.from_dsn(...)`. Both are plain `redis://` URL consumers —
no Memurai, no hardcoded localhost assumption in any active runtime path
(verified: no `memurai`/`127.0.0.1:6379` literals outside `.env.example`
defaults and tests). Point both the backend and worker service's `REDIS_URL`
at the **same** Railway Redis instance, ideally via a Railway variable
reference so the value is never copied as plaintext between services. No
Redis code changes made or required.

## 8. Database

`database/connection.py` reads `DATABASE_URL` directly into
`sqlalchemy.create_engine(...)` — a standard `postgresql://` DSN, compatible
with Railway's provisioned Postgres connection string as-is. Migration head is
unchanged at `20260821_01` (single migration file,
`backend/migrations/versions/20260821_01_current_schema.py`), which itself
runs `CREATE EXTENSION IF NOT EXISTS vector`, so pgvector enablement is
already handled by the existing migration — no new database setup step was
added or required. No schema or migration changes were made in this task.

## 9. Environment variable names

Names only, no values. Backend and worker share the same set (except the
worker never terminates HTTP requests):

**Runtime / infra:** `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `PORT` (backend
only — Railway sets this automatically, do not set manually)

**Auth/security:** `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`REFRESH_TOKEN_EXPIRE_DAYS`, `REFRESH_COOKIE_NAME`, `REFRESH_COOKIE_SECURE`,
`REFRESH_COOKIE_SAMESITE`, `AUTH_ALLOWED_ORIGINS`, `FRONTEND_URL`,
`ALLOW_LEGACY_PLAINTEXT_BYOK`, `PLATFORM_KEY_ENCRYPTION_KEY`,
`CORS_ALLOWED_ORIGINS`, `BOOTSTRAP_ADMIN_EMAIL`

**Providers:** `GEMINI_API_KEY`, `OPENAI_API_KEY`, `EMBEDDING_PROVIDER`,
`GEMINI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_MODEL`, `FIRECRAWL_API_KEY`,
`FIRECRAWL_API_BASE`, `MAX_CRAWL_PAGES`, `MAX_DEPTH`, `CRAWL_TIMEOUT`

**Queue/worker:** `INGESTION_QUEUE_MODE`, `ARQ_QUEUE_NAME`,
`QUEUE_CONNECT_TIMEOUT_SECONDS`, `WORKER_MAX_TRIES`, `WORKER_JOB_TIMEOUT`,
`WORKER_MAX_JOBS`, `WORKER_HEARTBEAT_INTERVAL`, `WORKER_HEARTBEAT_TTL`,
`MESSAGE_RESERVATION_STALE_SECONDS`

**Embedding/resilience:** `ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK`,
`REDIS_SOCKET_TIMEOUT`, `REDIS_CONNECT_TIMEOUT`, `REDIS_MAX_CONNECTIONS`,
`LLM_TIMEOUT`, `LLM_CONNECT_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_BACKOFF_BASE`,
`LLM_BACKOFF_MAX`, `LLM_CIRCUIT_FAILURE_THRESHOLD`,
`LLM_CIRCUIT_RECOVERY_TIMEOUT`, `EMBEDDING_MAX_RETRIES`,
`EMBEDDING_RATE_LIMIT_MAX_RETRIES`, `EMBEDDING_MAX_RETRY_DELAY_SECONDS`,
`EMBEDDING_BATCH_SIZE`

**Rate limits/semaphores:** `RATE_LIMIT_PUBLIC_CHAT_MAX/WINDOW`,
`RATE_LIMIT_AUTH_CHAT_MAX/WINDOW`, `RATE_LIMIT_CRAWL_MAX/WINDOW`,
`RATE_LIMIT_UPLOAD_MAX/WINDOW`, `RATE_LIMIT_ADMIN_MAX/WINDOW`,
`GLOBAL_MAX_CRAWLS`, `PER_ORG_MAX_CRAWLS`, `GLOBAL_MAX_LLM_REQUESTS`,
`PER_ORG_MAX_LLM_REQUESTS`, `GLOBAL_MAX_EMBEDDING_REQUESTS`,
`PER_ORG_MAX_EMBEDDING_REQUESTS`, `SEMAPHORE_DEFAULT_TTL`

**DB pool:** `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`,
`DB_POOL_RECYCLE`, `DB_POOL_PRE_PING`

**Upload:** `KNOWLEDGE_UPLOAD_DIR`, `KNOWLEDGE_MAX_UPLOAD_MB`,
`PUBLIC_DIRECT_API_ENABLED`

**Frontend (build-time, inlined):** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_URL`

**Railway service-reference candidates** (never copy plaintext):
`DATABASE_URL` (from the Postgres service), `REDIS_URL` (from the Redis
service, shared identically by backend and worker).

Confirmed appropriate and unchanged for Railway production:
`APP_ENV=production`, `ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK=false`,
`INGESTION_QUEUE_MODE=arq`.

## 10. Tests

| Suite | Result |
| --- | --- |
| `test_railway_deployment_readiness.py` (new) | 10/10 pass |
| Phase L | 15/15 pass |
| Phase L.2 | 20/20 pass |
| Phase L.3 | 26/26 pass |
| Phase L.4 | 8/8 pass |
| `test_redis_rate_limit_suite.py` | pass |
| `test_db_pool_cache_suite.py` | 11/11 pass |
| `test_arq_queue_suite.py` | 5/6 pass — 1 pre-existing failure (`test_6_chat_unaffected_during_active_crawl_job`), reproduced identically on unmodified `44c670e` before any Railway change; not caused by this task and not fixed (out of scope: no RAG/query-contract edits permitted) |
| `test_job_state_machine_suite.py` | pass |
| `test_phase_c_public_upload_contract.py` | 4/4 pass |
| `test_phase_d_ingestion_lifecycle.py` | 6/6 pass |
| `test_phase_e_widget_streaming_parity.py` | 16/16 pass |
| Backend `compileall` | clean |
| Frontend `npm run typecheck` | pass |
| Frontend `npm run lint` | 0 errors, 2 pre-existing `<img>` warnings (unchanged) |
| Frontend `npm run build` | pass, 17 routes generated |

No RAG/retrieval/query-contract code was touched; `git diff` for this task
touches only `backend/Dockerfile`, `backend/scripts/start_api.py`, and the new
test file.

## 11. Final commit

`874c19d` — "Prepare Railway multi-service deployment", pushed to
`origin/main`. Verified `git rev-parse main` == `git rev-parse origin/main`
== `874c19d` after fetch. No force push.

## 12. Blockers

**One blocker: shared upload storage.** Document (PDF/TXT/DOCX) uploads will
fail once the API and ARQ worker run as separate Railway services, because
the worker reads a local file path written by the API container. Website/
Firecrawl ingestion is unaffected. Four options are listed in Section 3; none
was implemented, per instructions not to pick a vendor unilaterally.

## Final verdict

**RAILWAY DEPLOYMENT READY EXCEPT SHARED UPLOAD STORAGE**
