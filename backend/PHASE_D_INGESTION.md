# Phase D ingestion operations

Production ingestion uses three distinct processes: the FastAPI API, Redis, and an ARQ worker. The API commits an `IngestionJob` before enqueueing `crawl_task` or `document_task` on the `ingestion` queue. The worker reads the same database and application configuration as the API. Uploaded files must be mounted at the same `KNOWLEDGE_UPLOAD_DIR` in both containers.

Required production settings:

```text
APP_ENV=production
INGESTION_QUEUE_MODE=arq
REDIS_URL=redis://redis:6379/0
ARQ_QUEUE_NAME=ingestion
ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK=false
```

Start the repository topology:

```shell
docker compose up --build postgres redis backend worker frontend
```

Run the worker outside Compose:

```shell
cd backend
arq workers.worker.WorkerSettings
```

`INGESTION_QUEUE_MODE=background` is limited to non-production development and tests. Production startup/configuration must use ARQ; an unavailable queue produces a truthful `503` response and a failed dispatch job instead of running ingestion inside the API process.

Existing databases require `migrations/phase_d_atomic_ingestion.sql`. Startup compatibility migrations apply the same additive columns and indexes, but managed production databases should run the SQL migration explicitly before deployment.
