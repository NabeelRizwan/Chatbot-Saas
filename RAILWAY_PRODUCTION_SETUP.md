# Railway Production Setup

Do not deploy yet. Complete the plan, secret, domain, backup, and pilot decisions below first. Railway is only the first infrastructure adapter; application configuration stays provider-neutral.

## 1. Provision infrastructure

Create one Railway project and add:

1. PostgreSQL with pgvector support.
2. Redis.
3. A private S3-compatible Storage Bucket.
4. Backend service from this repository with root directory `/backend` and `backend/Dockerfile`.
5. Worker service from the same commit and root directory `/backend`.
6. Frontend service with root directory `/frontend` and `frontend/Dockerfile`.

Do not attach a persistent upload volume to the API or worker. Uploaded originals belong in the bucket.

## 2. Map infrastructure variables

Use Railway reference variables in service configuration. The service names below are examples; substitute the actual names instead of hardcoding them in application code.

```dotenv
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}

OBJECT_STORAGE_PROVIDER=s3
OBJECT_STORAGE_BUCKET=${{Bucket.BUCKET}}
OBJECT_STORAGE_ACCESS_KEY_ID=${{Bucket.ACCESS_KEY_ID}}
OBJECT_STORAGE_SECRET_ACCESS_KEY=${{Bucket.SECRET_ACCESS_KEY}}
OBJECT_STORAGE_REGION=${{Bucket.REGION}}
OBJECT_STORAGE_ENDPOINT=${{Bucket.ENDPOINT}}
```

Give Backend and Worker the same database, Redis, bucket, crawler, embedding, generation-provider, encryption, and queue variables. Never place bucket or provider secrets in Frontend variables.

## 3. Backend variables and command

Set at minimum:

```dotenv
APP_ENV=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
OBJECT_STORAGE_PROVIDER=s3
OBJECT_STORAGE_BUCKET=${{Bucket.BUCKET}}
OBJECT_STORAGE_ACCESS_KEY_ID=${{Bucket.ACCESS_KEY_ID}}
OBJECT_STORAGE_SECRET_ACCESS_KEY=${{Bucket.SECRET_ACCESS_KEY}}
OBJECT_STORAGE_REGION=${{Bucket.REGION}}
OBJECT_STORAGE_ENDPOINT=${{Bucket.ENDPOINT}}
CRAWLER_PROVIDER=firecrawl
FIRECRAWL_API_KEY=<secret>
EMBEDDING_PROVIDER=gemini
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_API_KEY=<secret-if-used-as-default>
INGESTION_QUEUE_MODE=arq
ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK=false
ALLOW_LEGACY_PLAINTEXT_BYOK=false
JWT_SECRET=<at-least-32-random-bytes>
PLATFORM_KEY_ENCRYPTION_KEY=<stable-fernet-key>
REFRESH_COOKIE_SECURE=true
REFRESH_COOKIE_SAMESITE=lax
CORS_ALLOWED_ORIGINS=https://APP_DOMAIN
AUTH_ALLOWED_ORIGINS=https://APP_DOMAIN
FRONTEND_URL=https://APP_DOMAIN
PUBLIC_DIRECT_API_ENABLED=false
```

Add routine generation credentials through `/admin/api-credentials`, not Railway variables. Managed bots require an assigned enabled profile with bot capacity; environment generation keys are not a fallback. Explicit customer BYOK is unchanged. Keep infrastructure/embedding environment credentials as required and preserve the encryption key across deploys.

Configure the Backend service under **Settings → Deploy** with:

- Pre-deploy command: `python scripts/run_migrations.py`
- Pre-deploy timeout: `300` seconds initially
- Start command: `python scripts/start_api.py`

Railway runs the pre-deploy command in a separate container before the new deployment starts. A non-zero migration exit prevents that deployment from proceeding. It has the Backend service variables, including `DATABASE_URL`, but it does not use a persistent filesystem. Do not configure this migration command on Worker or Frontend.

Reference: [Railway Pre-Deploy Command documentation](https://docs.railway.com/deployments/pre-deploy-command).

Production `start_api.py` never executes Alembic. Every Backend replica performs only a read-only revision check and refuses to start unless the database is already at head. Development startup still applies migrations automatically for local convenience.

Configure liveness as `/health/live`. Treat `/health/ready` as the operational dependency check; it becomes ready after the worker heartbeat exists.

## 4. Worker variables and command

Use the same commit and relevant Backend variables. Set the start command to:

```text
python scripts/start_worker.py
```

The worker needs no public domain. It must have `DATABASE_URL`, `REDIS_URL`, all object-storage variables, `CRAWLER_PROVIDER`, `FIRECRAWL_API_KEY`, embedding credentials/model, infrastructure provider credentials used by background work, `PLATFORM_KEY_ENCRYPTION_KEY`, `APP_ENV=production`, and `INGESTION_QUEUE_MODE=arq`.

Start with one worker replica and the current bounded `WORKER_MAX_JOBS`. Scale only after DB pool, provider quotas, Firecrawl quota, Redis, and per-organization concurrency are observed under real load.

## 5. Frontend variables

Set these before the Docker build because `NEXT_PUBLIC_*` values are compiled into the browser bundle:

```dotenv
NEXT_PUBLIC_API_URL=https://API_DOMAIN
NEXT_PUBLIC_APP_URL=https://APP_DOMAIN
```

The image uses `npm ci`, `npm run build`, and `npm run start`; Next.js reads Railway's `PORT`. Generate the frontend domain first, update Backend CORS/auth origins, and rebuild Frontend after its final API/app URLs are known.

## 6. Deployment order

1. Confirm a database backup/restore procedure and bucket retention policy.
2. Start PostgreSQL, Redis, and Bucket.
3. Configure Backend's pre-deploy command exactly as `python scripts/run_migrations.py` and its start command as `python scripts/start_api.py`.
4. Prevent Worker from rolling to the new commit before Backend's pre-deploy step succeeds. For each release, deploy Backend first; confirm the pre-deploy migration exited `0` and the new Backend reports `/health/live`.
5. Deploy Worker from the same commit, then confirm its DB/Redis/bucket connections and heartbeat. Worker must not run migrations.
6. Confirm Backend `/health/ready` reports DB, migration head, Redis, Worker, and storage ready.
7. Assign Backend and Frontend public domains and HTTPS.
8. Set exact Backend CORS/auth origins and final Frontend public variables, then rebuild/deploy Frontend.
9. Keep one replica of each application service during the pilot; scale horizontally only after the smoke tests. Later Backend replicas use the same read-only schema gate and do not race Alembic.

If repository-linked services would auto-deploy simultaneously, stage or pause the Worker deployment so this ordering is preserved. Never work around a failed pre-deploy migration by starting new application replicas against an older schema.

## 7. Production smoke tests

### Post-deployment platform administrator bootstrap

After infrastructure → Backend's one-off migrations → Backend/Worker → Frontend are healthy, register the intended owner through the normal `/signup` flow. In an authorized one-off Backend service command (with its production database variables and private-network access), run from the Backend application directory:

```text
python scripts/set_platform_admin.py --email "EXISTING_ACCOUNT_EMAIL" --yes
```

Alternatively select the exact existing account with `--user-id EXISTING_USER_ID --yes`. Omit `--yes` in an interactive shell to require typing `PROMOTE`. The command never creates an account or prints a password; it reports the promoted user ID and is idempotent. Do not put it in startup/pre-deploy commands. No permanent admin secret or email-based registration promotion is required; remove any legacy `BOOTSTRAP_ADMIN_EMAIL` variable.

Log in again through `https://APP_DOMAIN/login`, then open `/admin`. In `/admin/api-credentials`, add platform-owned encrypted profiles with **Maximum bot assignments** (default 2). New platform bots automatically use the oldest same-provider enabled profile with a free slot, across customers. In `/admin/bots`, assign existing unassigned bots and inspect disabled profiles; no capacity means generation unavailable, not an environment-key fallback. Routine credential management no longer requires changing Railway variables. Keep `PLATFORM_KEY_ENCRYPTION_KEY` stable. See [PLATFORM_ADMIN_GUIDE.md](PLATFORM_ADMIN_GUIDE.md) for supported providers, allocation limits, rotation, and security precautions.

### Credential-pool upgrade for an existing installation

For revision `20260903_01`, back up and drain/stop the old Backend and Worker replicas before the one-off `python scripts/run_migrations.py` release step. Do not overlap old one-to-one allocation writers with new shared-profile writers. Start Backend and Worker at the new commit, then Frontend, following the normal readiness gates. Before customer traffic, provision enough capacity in `/admin/api-credentials` and assign existing environment-only/unassigned bots via `/admin/bots`. Disabled profiles retain all references; move/unassign every bot before deleting one. Do not roll back to the old allocator after enabling shared assignments. The migration was tested in isolated schemas, not applied to a customer database by this development task.

### Customer smoke tests

Use a dedicated pilot organization/bot, never an administrator shortcut.

- Sign in, refresh, change password, and verify the current device remains signed in while another refresh session is rejected.
- Upload one small valid PDF, TXT, and DOCX. Confirm each job proceeds through ARQ to ready, the source survives an API/worker restart, and the extracted content is useful.
- Submit one exact page and confirm no child pages appear.
- Submit a small controlled recursive site and review requested/crawled/indexed/skipped/duplicate coverage.
- Ask direct, follow-up, unknown, price, list, and comparison questions in the dashboard; verify sources and latency.
- Activate the bot, configure its exact customer origin, embed the dashboard snippet on an external HTTPS test page, and verify session continuity, streaming, sources, links, and Markdown safety.
- Stop Redis or Worker only during an approved maintenance test and confirm readiness fails closed, then restore them.

Do not onboard the first customer until [FIRST_CUSTOMER_PILOT_CHECKLIST.md](FIRST_CUSTOMER_PILOT_CHECKLIST.md) is complete.
