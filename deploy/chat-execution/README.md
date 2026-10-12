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
separate keys do not necessarily mean separate provider quotas.

Set request and token allowances with `PROVIDER_CAPACITY_BUDGETS_JSON`. The
following numbers are illustrative configuration, not provider quotas:

```json
{"openai:customer-project":{"rpm":100,"tpm":200000},"openai:customer-project:gpt-6.1-sol":{"rpm":50,"tpm":100000}}
```

Both project and model budgets apply atomically across workers. Supported
dimensions are `rpm`, `input_tpm`, `output_tpm`, `tpm`, `rpd` and `tpd`.
`provider:*` supplies a default policy separately to each credential/model;
explicit group policies constrain keys mapped to the same provider project.
`PROVIDER_CAPACITY_MODEL_GROUPS_JSON` maps exact `provider:model` names to a
shared quota family when the provider documents shared model allowances.
Gemini's optional `models/` prefix is normalized automatically.

Unconfigured limits are unknown, not unlimited. API feedback learns explicit
limits with known windows from OpenAI, Claude and structured Gemini errors.
Header ceilings never increase during their one-hour observation lifetime;
late responses cannot refill local counters. Confirmed exhausted project
windows block every model in that project. Providers may also have external
traffic, short burst limits or unpublished capacity constraints, so retries
and provider `Retry-After` remain necessary. Gemini's active free/paid project
limits must be checked in AI Studio; no historical free-tier table is assumed.

Tokens are estimated locally before dispatch with 20% input headroom plus
message overhead. `PROVIDER_CAPACITY_TOKEN_ESTIMATE_MARGIN` controls that
margin; `PROVIDER_CAPACITY_OUTPUT_RESERVE` defaults to 2048 when the adapter
has no explicit output cap. A reservation does not truncate answers or change
generation parameters. Actual usage reconciles upward only. Failed/partial
sent attempts stay counted; cancellation before dispatch refunds reservations.
Estimates cannot guarantee exact accounting for every tokenizer/reasoning model.
Daily budgets use a conservative rolling 24 hours, which differs from a
provider's calendar reset (for example Gemini midnight Pacific).

Generation diagnostics preserve bounded per-attempt status, safe provider
request IDs, admission time, retry/cooldown waits and usage. They contain no
API keys, prompt text or raw provider errors. Existing last-call latency remains
available; `execution_ms` measures the full generation path including waits.

The LlamaIndex answer call also selects source IDs in a private trailer. The
widget sees only validated selected sources; the trailer is stripped from both
buffered and streamed answers. Missing/malformed attribution never triggers an
extra AI call and does not fabricate sources. ID validation does not prove
semantic support, so test actual model attribution before rollout.

Three optional answer-layer switches are disabled by default. Set the same
values on Backend and chat-worker for a controlled rollout:

- `LLAMA_ANSWER_NATIVE_MESSAGES=1` sends history as native user/assistant messages
  for Gemini and OpenAI. The current question and evidence remain together in
  the last user message; trusted instructions stay separate. The existing planner
  also receives explicit history message indexes, with its validation unchanged.
- `LLAMA_ANSWER_STRUCTURED_OUTPUT=1` uses native JSON schema for supported text
  models. The answer remains ordinary prose; source IDs are separate metadata.
  Unknown model IDs retain the existing trailer protocol.
- `LLAMA_ANSWER_NORMALIZE_CITATIONS=1` accepts explicit inline evidence markers
  against the existing source whitelist and removes their display syntax.
  This includes grouped markers and empty citation spans with validated IDs.
  Quoted examples, code, ordinary links and unknown references remain intact.
  In progressive mode, an ambiguous Markdown reference can hold the remaining
  text until the answer finishes so a later link definition is preserved.
  Buffered mode still returns the complete answer after normal finalization.

These switches do not alter the planning algorithm, retrieval or ranking, and add no model
call. Streaming decodes only the answer field. Invalid native JSON uses the
existing error path; it does not trigger an answer-repair call. Schema validation
does not establish factual correctness or completeness. Set all three to `0`
to restore the existing answer protocol. Attribution and upstream licenses are
recorded in `backend/third_party/answer-layer/manifest.json`.

The optional planner safeguard is also disabled by default. Configure Backend
and chat-worker consistently and restart them when changing it:

- `LLAMA_QUESTION_PLAN_GUARD=1` labels history indexes and prevents bounded
  reference edits from replacing explicit current names, quantities or
  preferences. Quantified references retain their quantifiers. Rejected plans
  preserve the original question and any separately validated exclusions.
  A wrong reference index can be corrected when the same case-sensitive literal
  subject appears elsewhere in the scoped history. Repeated exact occurrences
  resolve to identical query text; no historical facts or preferences are copied.
  The correction is recorded in planning diagnostics. Exclusions, ellipsis and
  the model's choice of subject are not repaired by this step.
  This does not prove that the planner identified every exclusion or the correct
  referent; it adds no model call and leaves the existing grounding checks intact.
Set the switch to `0` to restore the planner's prior behavior. The
retrieval service's separate `LLAMA_EVIDENCE_ROLE_WEIGHT` remains `0` unless
an evaluation demonstrates a benefit. The planner safeguard does not enable it.

`LLAMA_QUESTION_ALTERNATIVES_CONTRACT=1` adds an explicit alternatives decision
to the existing follow-up planning call. Previously suggested option names must
be exact quotes from assistant history before they can become exclusions.
Supported providers receive the schema natively; other models receive the same
schema in the prompt. The switch is disabled by default and must be configured
consistently on Backend and chat-worker. It adds no separate model call, but
models may still miss an option, return an invalid plan, or mistake choosing
among previous options for requesting additional ones. Exact-history validation
checks where an option name came from, not whether it should be excluded.
Keep `LLAMA_QUESTION_ALTERNATIVES_CONTRACT=0` in the normal profile. Treat this
contract as experimental until tests with the intended model establish that
choices, changed criteria, reconsideration and ordinary follow-ups all work.
It is independent of the planner safeguard and citation-normalization switches.

Links in selected LlamaIndex evidence enter the existing reference-link ledger.
This allows supported manual and document URLs to survive answer validation.
Only source passages actually supplied to the answer can authorize such links;
the existing URL, origin and credential checks still apply.

Saved-answer acceptance checks are available in
[`backend/evaluation`](../../backend/evaluation/README.md). Keep reference
datasets, outputs and reviewer annotations outside the repository. This offline
tool reports omissions, contradictions and uncertainty without adding work to
the live answer path; semantic judgements require explicit trusted reviews.

Before enabling the queue for traffic, require API readiness with a registered,
live chat worker, retrieval readiness, and successful widget/cancellation/replay
checks. Keep the existing image and configuration available for rollback.

Implementation references: [Hatchet concurrency](https://docs.hatchet.run/v1/concurrency),
[Hatchet workers](https://docs.hatchet.run/v1/workers), and
[official Hatchet Lite deployment](https://docs.hatchet.run/self-hosting/hatchet-lite).
