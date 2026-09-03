# Production Architecture

## Runtime map

### Chat

Dashboard or embedded widget → authenticated or public chat route → tenant/session and origin checks → atomic quota and rate limit → query contract and conversation resolution → semantic cache → tenant-scoped hybrid retrieval → bot-selected generation provider → existing critique/verify/polish policy → conversation and usage persistence → SSE response with sources.

Normal chat does not read object storage or invoke a crawler. Provider/model selection is read from the bot for every request; request-local metadata prevents one bot's selection or usage data from leaking into another request.

### Website ingestion

Frontend crawl request → tenant authorization and quota check → staging `Document` and `IngestionJob` → Redis/ARQ → worker → `CrawlerProvider` → active Firecrawl adapter → current extraction and structured metadata preservation → current structure-aware chunking → configured embedding adapter → validation/quota check → atomic promotion. Exact-page and controlled recursive crawl remain separate modes. The old active version remains queryable if a replacement fails.

### File ingestion

Frontend PDF/TXT/DOCX upload → tenant authorization, extension/MIME/size/signature validation → private `ObjectStorage` → durable object key and staging DB record → Redis/ARQ → worker → secure temporary download → content-hash verification → current extraction/chunking → configured embedding adapter → validation/quota check → atomic promotion → temporary-file removal. The original private object is retained for retry or reprocessing.

Pre-object-storage rows with a legacy `file_path` remain readable during rollout. They must be copied to object storage before retiring any filesystem that contains those original uploads.

## Ports and adapters

The application core uses small explicit boundaries:

| Port | Active adapters | Durable/configured identity |
| --- | --- | --- |
| Generation | Gemini, OpenAI, Claude/Anthropic, Grok/xAI | Bot `provider`, `model_name`, BYOK or platform credential profile |
| Embeddings | Gemini, OpenAI; deterministic only for development/tests | Chunk/document provider, model, version, dimensions |
| Crawler | Firecrawl | Crawl provider plus requested/canonical URL and audit metadata |
| Object storage | Local development adapter; S3-compatible production adapter | Private bucket key on `Document` |
| Cache/queue | Redis | `REDIS_URL` |
| Database/vector index | PostgreSQL/pgvector | `DATABASE_URL` |

There is no hosting-vendor credential or service name in these ports. An S3-compatible service can be Railway Bucket, AWS S3, Cloudflare R2, MinIO, or another compatible endpoint.

## Generation and credentials

Generation and embeddings are deliberately independent. Changing a bot from Gemini generation to OpenAI generation does not change or re-embed its knowledge. Query embeddings are generated with the exact active provider/model profile stored on ready knowledge, and vector search filters to that profile. Mixed models, versions, or dimensions fail before vector search; a future embedding change requires staging, re-embedding, validation, and atomic promotion of a new knowledge version.

Credential resolution never changes the selected provider or model:

1. encrypted bot BYOK credential;
2. an assigned, enabled, encrypted platform credential profile for the same provider.

Unassigned or disabled managed-bot generation fails closed; environment defaults do not bypass bot-capacity enforcement. Existing infrastructure/embedding environment credentials remain separate.

One bot → at most one platform credential; one platform credential → many bots up to `max_bot_assignments` (default 2, minimum 1). `Bot.platform_credential_id` is authoritative; the legacy reverse column is historical only. Creation/clone/provider changes and BYOK clear allocate the oldest compatible enabled profile with a slot (created timestamp, then ID), independent of customer or organization. No free slot means unassigned, not overload or provider fallback.

All assignment/lifecycle and capacity mutations share a PostgreSQL transaction-scoped advisory lock, with counts checked after locking at READ COMMITTED isolation. Manual moves affect only the selected bot. Capacity reductions below the count fail; disabling preserves references but blocks new use; deleting any referenced profile fails. BYOK does not consume a slot. Admin-only metadata includes IDs/labels, provider/status, count/maximum/free slots and bounded assignment lists. Customer responses contain no pool metadata; tenant/request usage records remain separate from an additional atomic profile aggregate.

The additive `20260903_01` release migration preserves valid assignments and ciphertext, and fails transactionally on incompatible canonical references. Drain old one-to-one writers before the one-off migration and start only the new version; do not run mixed old/new writers. Existing environment-only generation bots must be provisioned through the admin console before customer traffic. Secrets are decrypted only at the provider boundary and are never serialized to bot/admin responses. Provider adapters return a canonical result containing provider, model, response text, available input/output usage, and normalized error information. Missing usage remains unknown; it is not estimated.

## Crawl safety and fidelity

Firecrawl is the only active crawler adapter. Crawl4AI files remain legacy/test artifacts and are not reactivated by production ingestion. The application normalizes Firecrawl output into generic pages while retaining canonical URL, requested URL, title, markdown/text, links, OpenGraph/JSON-LD metadata, and crawl diagnostics.

Recursive crawls enforce public-address validation, redirect/canonical domain boundaries, maximum pages, maximum depth, canonical deduplication, cancellation checks, retries, and coverage accounting. Exact-page mode indexes only the submitted page. Firecrawl provider semantics, including robots handling, remain authoritative.

## Storage and tenant isolation

New object keys are generated by the application:

`organizations/{organization_id}/bots/{bot_id}/documents/{random_id}/source.{ext}`

Raw filenames never become keys. Keys reject absolute paths and traversal, and workers verify the organization/bot prefix before downloading. Database reads, jobs, chunks, conversations, quotas, credential lookups, cache keys, and distributed concurrency guards retain organization and bot scope. Objects are private and are never exposed by a public download route.

## Production topology

- Stateless backend replicas serve dashboard/public APIs and health endpoints.
- Stateless ARQ worker replicas consume Redis jobs and use the same DB, bucket, crawler, and provider configuration.
- PostgreSQL/pgvector owns durable application and vector state.
- Redis owns queue, cache, rate-limit, semaphore, and worker-heartbeat state.
- Private S3-compatible storage owns uploaded source files.
- The Next.js frontend serves the dashboard and generic widget script.

`/health/live` proves the API process is alive. In production, `/health/ready` requires current migrations, PostgreSQL, Redis, an ARQ worker heartbeat, and object storage. Optional unused generation providers are not readiness dependencies.

## Widget embedding

No WordPress-specific backend or plugin is required. After production domains and the bot's origin allowlist are configured, use the dashboard-generated snippet or the equivalent:

```html
<script
  src="https://APP_DOMAIN/widget.js"
  data-api-base-url="https://API_DOMAIN"
  data-bot-id="BOT_ID"
></script>
```

The same script works in WordPress custom HTML, Shopify theme HTML, plain HTML, or another framework. Keep the bot ID public, keep credentials out of the snippet, and allow only the real customer origins.
