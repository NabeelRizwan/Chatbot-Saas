# Two retrieval lanes, two explicit pipeline profiles

Both existing retrieval services run this image. No additional service count is
required. Each process loads one shared BGE-small/MiniLM runtime and keeps two
independently admitted corpus stores. The existing `retrieval_engine/` package is
the unchanged Clean OG implementation. `rag2_engine/` is the separately named
prepared variant; `rag2/` contains its planned Voyage and supplemental algorithms.

## Authenticated API

The existing bearer token remains required for every operation except liveness.
Organization and bot authority must be resolved by the SaaS backend. The public
widget may not select or forward a pipeline profile itself.

`/v1/snapshots`, `/v1/retrieve`, and `/v1/prepare` accept optional fields:

```json
{"pipeline":"rag2_improved","pipeline_build_revision":"rag2-voyage-v1"}
```

Omitted profile fields select OG. Explicit `og` accepts a missing revision or
`og-v1`. Unknown pipelines/revisions fail validation with 422. The RAG2 revision
is mandatory. Organization policy revisions do not belong in index identity;
switching OG → RAG2 → OG reuses the valid original OG index.

Snapshot records and their canonical fingerprint are unchanged. RAG2 snapshot
and retrieval responses echo both profile fields. OG response shapes remain
unchanged. RAG2 retrieval also accepts `queries` (up to six unique, nonempty
queries, each at most 420 characters/65 words) and `timeout_seconds` (>0, at most
1440). The backend must pin the profile when accepting a queued turn and send
the remaining request budget. A later organization toggle must not rewrite an
already accepted turn's profile.

OG cache paths stay `LLAMA_DATA_DIR/<org>-<bot>/<fingerprint>`. RAG2 uses
`LLAMA_DATA_DIR/pipelines/rag2-voyage-v1/<org>-<bot>/<fingerprint>`. Pruning is
restricted to each store's canonical corpus paths, so neither store prunes the
other. Each store retains the configured bounded memory/disk/index budgets;
combined corpus-cache capacity is therefore up to twice those per-store limits.
Both share model weights. Account for this when sizing the existing volumes/RAM.

`/health/ready` retains the exact OG response. `/health/rag2` additionally checks
RAG2 startup/cache readiness, offline models, readable Voyage tokenizer,
credential presence, quota configuration and Redis connectivity. A successful
response includes `pipeline`, `pipeline_build_revision`, `quota_store: "ready"`
and `provider_validation: "not_probed"`. It makes no Voyage request and does not
claim the credential/account is accepted by Voyage. A failed RAG2 startup cache
does not disable healthy OG readiness.

## Voyage quota and cancellation

Set `VOYAGE_API_KEY` and `VOYAGE_REDIS_URL` (or existing `REDIS_URL`) identically
on both lanes. `VOYAGE_QUOTA_ACCOUNT_ID` is an optional stable, non-secret account
identifier; it must be identical for all keys belonging to the same account.
Without it, identical API keys still derive identical opaque Redis namespaces.
Do not use organization IDs for this shared-account limiter.

Default limits remain three requests and 10,000 tokens per conservative
62-second rolling window. Redis Lua uses Redis server time, atomically reserves
both limits, shares Retry-After/cooldown, retains uncertain/failed reservations,
and only increases usage on reconciliation. Redis errors fail closed; there is
no SQLite or per-container quota fallback. Differing live worker quota limits
fail closed until the prior rolling policy window expires. `VOYAGE_RPM` and
`VOYAGE_TPM` may change only with `VOYAGE_QUOTA_LIMITS_VERIFIED=true` after the
operator confirms the provider account's allowance. This release does not raise
the free limits.

At most 3,500 estimated Voyage tokens are sent per whole-text batch, with no
provider truncation, at most four attempts, a 60-second whole HTTP attempt cap,
and a request-local deadline. Errors, cancellation and deadline exhaustion do
not skip focused queries, fall back to local primary scores, or replay the
request on another worker. The ASGI disconnect watcher signals the synchronous
engine; quota waits and the async HTTP transport observe cancellation. Active
CPU inference and bounded Redis operations finish their current call before
the next cancellation checkpoint.

Recommended upper budgets are 1800 seconds for a RAG2 queued turn, 1500 seconds
for its backend retrieval HTTP request and at most 1440 seconds passed to this
service. The backend must reduce inner budgets to the remaining outer lifetime.
These are ceilings, not promises: free-tier quota may still prevent a large
request from completing. Existing OG budgets and admission remain unchanged.

## CPU sharing and retained semantics

The prepared variant held its shared runtime lock during external Voyage work.
This integration uses a private postprocessor copy, never swapping the shared
MiniLM model. It releases the shared CPU lock while remote passage scoring waits
for quota/network and reacquires it before any local inference. The RAG2 corpus
and pipeline admission remain pinned. OG has separate service admission and can
use the local CPU models during those remote waits. Local model inference itself
remains serialized, so this is not a promise of zero CPU contention.

The original-query plus focused-query merge, source/span checks, MiniLM
discovery and 32-block second pass remain the prepared algorithms. Per-query
context stays at most 5200 tokens; planned context stays at most 48000 tokens and
448 evidence records. No saved corpus, questions, plans, answers or provider
caches are runtime inputs. The backend owns the improved source-map answer
method and its separate model eligibility and request-local settings.

## Validation scope

Focused tests exercise independent clients sharing Redis Lua via fakeredis,
pipeline/cache isolation, legacy API responses, actual variant orchestration
with a blocked mock HTTP request plus concurrent OG scoring, real Pydantic
ranker-copy behavior, cancellation and the prepared source/assembly invariants.
Mocks and synthetic sources are not evidence of provider health or live quality.
No external provider calls are required by this suite.
