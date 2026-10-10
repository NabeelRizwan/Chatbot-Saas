# Distributed chat execution

This optional deployment moves complete widget turns onto Hatchet workers. The
API still authenticates the widget, checks its origin and reserves usage. Workers
run the existing planning, retrieval, ranking, generation and persistence path.
Accounts, bot settings and the application database remain authoritative.

## Images and commands

The supported scheduler pair is **Hatchet engine v0.110.5** and **Python SDK
1.41.1**. Chat workers require Linux. Build from the repository root:

```sh
docker build -f backend/Dockerfile --build-arg INSTALL_CHAT_EXECUTION=true \
  -t chatbot-saas-backend:chat-execution backend
```

Use this same image for both processes:

| Process | Command |
| --- | --- |
| API | `python scripts/start_api.py` (the image default) |
| Chat worker | `python -m workers.chat_worker` |

Without the build argument, the Dockerfile retains the standard API build and
does not install the optional SDK. Runtime execution defaults to `inline`.
Installing the SDK does not enable queuing by itself. Existing ingestion workers
keep their existing command and queue.

## Scheduler and storage

`compose.local.yml` runs an isolated Hatchet database and engine for local use:

```sh
docker compose -f deploy/chat-execution/compose.local.yml up -d
```

The dashboard/API binds to `127.0.0.1:8890`; gRPC binds to `127.0.0.1:7077`.
The database is not exposed on a host port. Create a local API token through
Hatchet and keep it outside the repository. These local defaults are not public
production credentials.

Production can use the existing PostgreSQL cluster with a **separate Hatchet
database and database role**. Run Hatchet's own migrations against that database,
never against the SaaS database. Keep engine/API/gRPC endpoints private and use
authenticated SDK connections. Hatchet owns scheduling; Redis holds bounded
chat payloads, event streams and temporary capacity leases. The SaaS database
holds completed conversations and billing records.

## Shared API and worker configuration

Both processes need the same application database, Redis, encryption settings,
retrieval configuration and Hatchet tenant/namespace. Configure secrets through
the deployment environment; no provider key or widget session token is placed
inside a Hatchet task input.

| Variable | Purpose/default |
| --- | --- |
| `CHAT_EXECUTION_MODE=hatchet` | Enable distributed widget turns; default `inline`. |
| `HATCHET_CLIENT_TOKEN` | Private Hatchet API token. |
| `HATCHET_CLIENT_SERVER_URL` | Reachable private Hatchet HTTP API address. |
| `HATCHET_CLIENT_HOST_PORT` | Reachable private gRPC host and port. |
| `HATCHET_CLIENT_TLS_STRATEGY` | Match the engine; `none` is used for local plaintext testing. |
| `HATCHET_CLIENT_NAMESPACE` | Shared workflow namespace; use a distinct namespace for tests. |
| `CHAT_EXECUTION_REDIS_PREFIX` | Shared relay namespace; default `chat-execution:v1`. |
| `CHAT_EXECUTION_WORKER_NAME` | Default `saas-chat-worker`; keep this prefix for readiness checks. |
| `CHAT_EXECUTION_WORKER_SLOTS` | Active task slots per worker; default `20`. |
| `CHAT_EXECUTION_QUEUE_TIMEOUT_SECONDS` | Maximum queue wait; default `120`. |
| `CHAT_EXECUTION_TIMEOUT_SECONDS` | Application execution deadline; default `180`. |
| `CHAT_EXECUTION_MAX_PENDING_PER_BOT` | Running plus queued turns per bot; default `100`. |
| `CHAT_EXECUTION_MAX_PENDING_GLOBAL` | Running plus queued turns overall; default `2000`. |
| `CHAT_EXECUTION_RETENTION_SECONDS` | Relay retention; default `3600`, at least queue + execution + `120`. |
| `CHAT_STREAM_MODE` | Default `buffered`; opt-in `progressive` emits checked complete paragraphs. |

Hatchet admits **10 active turns per organization/bot pair**, with round-robin
scheduling for excess work. Turns within a conversation execute one at a time.
The active slot covers generation and saving the answer. Worker slots, retrieval
capacity and provider quotas remain separate limits; a 10-turn limit alone does
not establish a latency guarantee.

Allow database connection headroom beyond active chat worker slots. A turn can
retain its read connection while credential lookup, usage accounting or lease
maintenance briefly needs another. For a 20-slot worker, `DB_POOL_SIZE=10` and
`DB_MAX_OVERFLOW=20` permit 30 connections; this configuration passed the
20-concurrent-turn accounting check. It is a sizing example, not a universal
capacity guarantee. Sum `DB_POOL_SIZE + DB_MAX_OVERFLOW` across every process
and service replica, including API and ingestion workers, and leave capacity
for administration and other clients below PostgreSQL's usable connection limit.
Recheck this budget when increasing worker slots or replicas.

Progressive delivery can expose an approved prefix before a later source check,
provider error or persistence failure. Buffered delivery retains the completed
answer check before exposure. Cancellation is cooperative during bounded socket
operations; it does not instantly terminate an already-running provider call.

## Retrieval capacity and reuse

For two CPU inference lanes, run two separately addressed retrieval service
processes, each with its own cache volume and one Uvicorn worker. Keep their
model/configuration versions identical. Do not point concurrent processes at
the same writable index directory. Each process keeps models loaded and a
bounded set of isolated bot indexes in memory.

Configure the API and chat workers with:

```text
LLAMA_RETRIEVAL_URL=<primary private retrieval URL>
LLAMA_RETRIEVAL_URLS=<first private URL>,<second private URL>
LLAMA_RETRIEVAL_WORKER_SLOTS=1
LLAMA_RETRIEVAL_QUEUE_TIMEOUT_SECONDS=60
LLAMA_RETRIEVAL_POOL_ENABLED=true
LLAMA_RETRIEVAL_CACHE_ENABLED=true
LLAMA_RETRIEVAL_PIPELINE_REVISION=<version covering code, models and retrieval configuration>
```

`LLAMA_RETRIEVAL_TOKEN` must match both services. Routing waits up to 60 seconds
by default, bounded by the remaining full chat deadline and cancellation.
Tune `LLAMA_RETRIEVAL_QUEUE_TIMEOUT_SECONDS` for measured serving capacity.
Size CPU and memory for both processes; model copies consume separate
memory. Each service's authenticated `/health/ready` requires loaded models.

Explicit corpus preparation warms every configured endpoint before source
promotion. For a new replica with existing datasets, run a one-off backend job
using its intended private URLs and normal database/token configuration:

```sh
python scripts/warm_retrieval.py --all-active
# Or select only particular active bots:
python scripts/warm_retrieval.py --bot-id 1 --bot-id 2
```

Require a successful warm-up before adding the new URLs to serving API/worker
configuration. Startup model readiness does not mean all bot indexes are warm.

Change `LLAMA_RETRIEVAL_PIPELINE_REVISION` whenever retrieval code, models or
configuration change. Missing revisions disable evidence caching. Dataset
fingerprints invalidate changed content automatically. Cache hits still undergo
tenant, source and evidence validation. Do not change shared Redis eviction
policy to evict queue/session/limit keys merely to make room for caches.

Provider admission supports configured global, organization, credential and
provider quota-group limits. Set actual quota groups and RPM budgets through
`PROVIDER_CAPACITY_QUOTA_GROUPS_JSON` and `PROVIDER_CAPACITY_RPM_LIMITS_JSON`;
separate keys do not necessarily mean separate provider quotas. Token/day limits
still belong to the provider and existing usage controls.

Before enabling the queue for traffic, require API readiness with a registered,
live chat worker, retrieval readiness, and successful widget/cancellation/replay
checks. Keep the existing image and configuration available for rollback.

Implementation references: [Hatchet concurrency](https://docs.hatchet.run/v1/concurrency),
[Hatchet workers](https://docs.hatchet.run/v1/workers), and
[official Hatchet Lite deployment](https://docs.hatchet.run/self-hosting/hatchet-lite).
