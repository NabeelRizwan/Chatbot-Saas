# Chatbot SaaS

A multi-tenant chatbot platform for website and document knowledge. Organizations manage bots, ingest PDF/TXT/DOCX files and website pages, and embed a public widget that answers from that knowledge with source attribution.

The runtime is Next.js, FastAPI, PostgreSQL with pgvector, Redis with ARQ workers, Firecrawl for website crawls, private S3-compatible object storage for uploaded originals, and bot-selected generation (Gemini, OpenAI, Anthropic, or xAI) with independent embedding configuration.

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

The API entrypoint applies Alembic migrations automatically in development. Production releases run `python scripts/run_migrations.py` once before starting or scaling API/worker processes; production API replicas only verify that the schema is already at head. Production ingestion requires Redis/ARQ; the development-only background queue is not a production substitute.

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

Playwright end-to-end tests require `E2E_EMAIL`, `E2E_PASSWORD`, and `E2E_BOT_ID`. Enable live external fixtures only when those origins and providers are deliberately configured.

Backend tests are Python `unittest` modules in `backend/`.

## Operations

- Architecture and adapter boundaries: [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md)
- Hosting-neutral topology, environment, health, and rollback: [DEPLOYMENT.md](DEPLOYMENT.md)
- First Railway deployment procedure: [RAILWAY_PRODUCTION_SETUP.md](RAILWAY_PRODUCTION_SETUP.md)
- Ongoing operations and troubleshooting: [PRODUCTION_OPERATIONS.md](PRODUCTION_OPERATIONS.md)
- Platform administrator console: [PLATFORM_ADMIN_GUIDE.md](PLATFORM_ADMIN_GUIDE.md)
- First-customer pilot checks: [FIRST_CUSTOMER_PILOT_CHECKLIST.md](FIRST_CUSTOMER_PILOT_CHECKLIST.md)
- Database and object-storage backup/restore: [backend/BACKUP_RESTORE.md](backend/BACKUP_RESTORE.md)

Do not treat local mocked tests as production evidence. Confirm live Firecrawl, provider credentials, independent workers, health gates, browser chat, and restore drills in the intended deployment environment before public launch.
