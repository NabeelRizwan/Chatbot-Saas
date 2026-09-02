# Chatbot SaaS

A multi-tenant chatbot platform built with Next.js, FastAPI, PostgreSQL/pgvector, Redis/ARQ, Firecrawl, and Gemini/OpenAI provider routing.

Implemented product paths include organization-scoped bot management, persistent bot/widget configuration, encrypted platform/BYOK provider credentials, file and website knowledge ingestion, grounded RAG chat, public-origin-controlled widgets, conversation transcripts, usage quotas, and measured analytics.

## Local stack

The production-shaped topology is defined in `docker-compose.yml`:

- frontend: Next.js on port 3000
- backend: FastAPI on port 8000
- worker: independent ARQ process
- postgres: PostgreSQL with pgvector
- redis: Redis with AOF
- minio: private S3-compatible source-object storage

Create `backend/.env` from `backend/.env.example` and provide real development keys. The compose file deliberately runs the backend in production mode, so secure JWT/cookie/encryption/origin values are required.

```sh
docker compose up --build
```

Open `http://localhost:3000`. API documentation is available at `http://localhost:8000/docs`.

## Manual development

Backend:

```sh
cd backend
python -m pip install -r requirements.txt
python scripts/start_api.py
```

Worker (separate terminal, with Redis running):

```sh
cd backend
python scripts/start_worker.py
```

Frontend:

```sh
cd frontend
npm ci
npm run dev
```

The API entrypoint applies Alembic migrations before serving. Production ingestion requires Redis/ARQ; the development-only background queue is not a production substitute.

## Validation

Frontend checks:

```sh
cd frontend
npm run typecheck
npm run lint
npm run build
npm run test:e2e:install
npm run test:e2e
```

Phase I Playwright tests require `E2E_EMAIL`, `E2E_PASSWORD`, and `E2E_BOT_ID`. Set `PHASE_I_LIVE_EXTERNAL=1` only when the external fixture origins and live providers are deliberately configured.

Backend tests are Python `unittest` modules in `backend/`; phase-specific suites can be run directly with the same interpreter used by the API.

## Operations

- Deployment topology, environment, startup, health, and rollback: `DEPLOYMENT.md`
- Portable production architecture: `PRODUCTION_ARCHITECTURE.md`
- First Railway deployment procedure: `RAILWAY_PRODUCTION_SETUP.md`
- Operations and first-customer checks: `PRODUCTION_OPERATIONS.md`, `FIRST_CUSTOMER_PILOT_CHECKLIST.md`
- Database and knowledge-file backup/restore drill: `backend/BACKUP_RESTORE.md`
- Phase I acceptance evidence and launch verdict: `FINAL_PRODUCT_ACCEPTANCE_REPORT.md`

Do not claim production readiness from mocked tests alone. Live Firecrawl, real provider, independent worker, restart, browser, and restore evidence should be collected in the intended deployment environment before public launch.

## License

See `LICENSE`.
