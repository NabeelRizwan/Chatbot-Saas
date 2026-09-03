# Database portability and fresh bootstrap audit

Date: 2026-09-03. Audited baseline: `87a8b6ac26fdd8fdc5758bd39fa5eadc9ce1e7a3`.

**DATABASE PORTABILITY PARTIALLY READY**

The runtime is PostgreSQL/pgvector-portable; no Supabase-specific implementation change is needed. Local configuration, schema-contract, startup-gate, Redis, and storage checks pass. **Fresh live PostgreSQL acceptance is blocked, not passed:** this machine has no PostgreSQL binaries, Docker/Podman, or installed WSL, and no separate disposable database URL was supplied. The configured database is the protected old Supabase database; it was not connected to or modified.

## 1. Supabase dependency and database configuration

Supabase is **A: the old PostgreSQL host through `DATABASE_URL`**, not an auth/storage/SDK runtime dependency.

- Tracked Backend/Frontend runtime and dependency-manifest searches found no Supabase SDK package, imports, client calls, project-ID requirement, API-secret requirement, storage adapter, or Supabase authentication flow.
- Residual mentions: unused `SUPABASE_URL`/`SUPABASE_KEY` reads in `backend/database/connection.py`; an old host-specific error message in `backend/main.py`; and a comment in legacy `backend/database.py`. None selects a connection, validates a Supabase credential, or changes behavior. Left unchanged to avoid unnecessary runtime edits.
- The active SQLAlchemy engine/session uses `DATABASE_URL`. Alembic, the API schema gate, and workers use the same PostgreSQL contract. A subprocess successfully loaded the engine and Alembic configuration using a synthetic generic PostgreSQL hostname with no Supabase variables or local dotenv loading; it did not connect.
- No production hostname, Supabase project ID, or pooler naming convention is required. Development localhost defaults and examples are not production dependencies.

Fresh Railway PostgreSQL is supported by the configuration/schema design **provided pgvector is available and the migration role can enable it**. Actual Railway connectivity and fresh-schema execution remain unverified.

## 2. Migrations, pgvector, and fresh acceptance

Current sole Alembic head: **`20260903_01`**.

Revision chain: `20260821_01` → `20260902_01` → `20260902_02` → `20260903_01`.

Exact production command, from the Backend directory with the new database's `DATABASE_URL`:

```text
python scripts/run_migrations.py
```

Backend owns this one-off pre-deploy step. Production replicas only check the revision; Worker/Frontend do not run migrations. Development API startup retains automatic migration convenience.

| Check | Result in this audit |
|---|---|
| Revision chain and single current head | Passed, offline Alembic inspection |
| Production accepts head / rejects empty or outdated revision | Passed, mocked revision state |
| Production does not run migrations per replica; local startup does | Passed, existing startup tests |
| PostgreSQL table/FK DDL, `vector(768)` | Passed, compiled SQLAlchemy metadata; no server execution |
| Baseline enables vector and cosine IVFFlat index (`lists = 100`) | Confirmed in committed migration source |
| Credential capacity: non-null default `2`, check `>= 1`, canonical bot FK | Passed, compiled schema contract; capacity revision inspected |
| Exact migration entrypoint on an empty PostgreSQL database | **Skipped: isolated database unavailable** |
| Live extension/index/constraint creation, idempotent rerun, row counts | **Not measured** |
| Application import and real production head gate on fresh schema | **Not executed** |

The baseline enables `vector` before creating the current tables and IVFFlat index. The SQL does not install a missing server-side extension package. No dimensions, embedding model, vectors, or retrieval semantics were changed. The capacity migration is additive, validates/backfills existing assignments, and creates no profiles or bots when tables are empty.

The new opt-in `FreshPostgresAcceptance` test is ready to run against a separate empty database named `fresh_bootstrap_<unique_suffix>` via `FRESH_BOOTSTRAP_DATABASE_URL`. It refuses Supabase/non-test endpoints and connection overrides, checks that no user relations exist before migration, runs the **unmodified** production script twice, verifies tables/indexes/FKs/capacity/vector and zero rows, then imports the application and checks the production gate. It uses synthetic isolated application configuration and never defaults to the old `DATABASE_URL`. It does not create/drop databases or delete existing data. This harness has **not** passed live acceptance yet.

The older migration suites were intentionally not run: their default fixtures create schemas on the configured database, which would violate the instruction to leave old Supabase untouched. Their historical results are not claimed as fresh Railway evidence.

## 3. Expected fresh row state

These are **source-derived expectations, not live counts from this audit**.

| State | After migrations alone | After first Backend import, before signup |
|---|---:|---:|
| Customers/users/organizations/memberships/subscriptions | 0 each | 0 each |
| Bots | 0 | 0 |
| Conversations and messages | 0 each | 0 each |
| Websites/crawls/documents/chunks | 0 each | 0 each |
| Ingestion jobs | 0 | 0 |
| Platform credential profiles | 0 | 0 |
| Other application usage/session/audit tables | 0 each | 0 each |
| Internal billing plans | 0 | 3: `free`, `pro`, `team` |
| Alembic revision bookkeeping | 1 | 1 |

`main.py` calls `ensure_default_plans()` on import; these three genuine internal rows are expected. Migrations do not create an administrator or test/customer seeds. Later normal owner signup deliberately creates its new customer/user/workspace/membership/subscription/login session; the separate admin command promotes that existing account. Zero customer rows is the pre-signup condition, not the state after owner registration.

## 4. Fresh Redis and Storage Bucket

**Redis:** `REDIS_URL` configures the sync cache/rate-limit client, asynchronous client, ARQ pool, and worker connection. Optional timeouts/queue names tune behavior, not legacy dependencies. No old keys are required. With an initially empty in-memory fake Redis, readiness correctly failed for a missing worker heartbeat; the real worker startup hook created its TTL heartbeat and readiness passed with DB/storage dependencies mocked. Queue URL parsing and sync ping-only connection passed. Full ARQ worker execution and a real Railway Redis instance were not tested; normal ARQ housekeeping creates new keys as needed. No cache/queue import or flush occurred.

**Storage:** production uses the S3-compatible adapter and its endpoint/bucket/access-key/secret/region configuration. Readiness calls `head_bucket`, not a list/download of old objects. A mocked empty accessible bucket passed; an inaccessible bucket failed; production local-storage rejection passed. Fresh documents will create their own object references. No old local/Supabase files need copying. Actual Railway bucket credentials/network/permissions were not tested, and no object was uploaded/copied/deleted.

## 5. Changes and deployment order

Only these repository files changed:

- `RAILWAY_PRODUCTION_SETUP.md`: explicit new DB/no-import strategy; exact release command/head and pgvector prerequisite; fresh Redis/empty bucket behavior; zero-row versus internal-plan/owner-signup distinction; protected old Supabase; isolated acceptance instructions.
- `backend/test_database_portability.py`: 13 deterministic offline tests plus one explicitly opt-in live acceptance test.
- `DATABASE_PORTABILITY_AND_FRESH_BOOTSTRAP_REPORT.md`: this report.

**No runtime code or existing migrations changed.** No deployment command was issued. No real credentials were added. Old Supabase, the local controlled corpus, providers, RAG, Firecrawl, ingestion, embedding, storage, and Redis architecture were untouched. No customer data, cache, jobs, uploads, or vectors were exported/imported.

Documented future sequence: new PostgreSQL/Redis/empty bucket → one-off migrations → Backend/Worker/Frontend health → owner signup and explicit admin promotion → real provider credentials → first pilot customer/bot → real knowledge ingestion. Keep old Supabase untouched until Railway is validated; any later manual decommission requires a separate authorized operation.

## 6. Tests and blockers

Python: bundled local CPython 3.12.13. Tests ran with dotenv disabled, a synthetic non-serving database URL, fake/mocked infrastructure, and a network guard allowing only Windows asyncio's internal socket pair.

| Selected tests | Passed | Skipped |
|---|---:|---:|
| `test_database_portability` | 13 | 1 live PostgreSQL test |
| `test_railway_deployment_readiness.TestStartApiHonorsPort` | 8 | 0 |
| `test_railway_deployment_readiness.TestUploadStorageIsPortable` | 2 | 0 |
| `ProductionObjectStorageTests.test_local_adapter_is_development_only_and_s3_config_fails_closed` | 1 | 0 |
| Phase F production JWT and encryption-secret validation tests | 2 | 0 |
| **Total** | **26** | **1** |

Final unittest result: **27 tests run, 26 passed, 1 skipped, 0 failures/errors; 0.706 seconds**. The initial network guard also blocked Windows asyncio's private socket-pair initialization, causing two test-harness failures; narrowing that guard resolved them without any product-code change. No provider APIs or customer RAG benchmarks ran.

`python -m py_compile backend/test_database_portability.py` and `git diff --check` also passed. The repository started on clean `main`, and `git fetch origin --prune` confirmed local HEAD matched `origin/main` at the audited baseline, including the final pre-commit check.

Blocking acceptance item: supply a separate disposable PostgreSQL database with pgvector available, then run the opt-in acceptance test. No local PostgreSQL/container runtime is installed and no `FRESH_BOOTSTRAP_DATABASE_URL` was configured. **Do not substitute the protected old Supabase database.** Railway infrastructure provisioning and live Redis/bucket validation remain manual future steps, not completed deployment evidence.

Final verdict: **DATABASE PORTABILITY PARTIALLY READY**.
