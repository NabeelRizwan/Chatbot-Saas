# Native RAGFlow knowledge service

This image extends the exact official RAGFlow image used in the saved WOWMD and
IKEA experiments. It adds authenticated retrieval and source-manifest routes;
it does not replace the SaaS account, bot, session, Redis, quota or provider systems.
The official Apache-2.0 license is included. The upstream revision and six native
search file hashes are pinned in `source-manifest.json`.

`POST /v1/saas_native/retrieve` accepts only `question`, `dataset_id` and
`document_ids`. RAGFlow validates native tenant ownership and ready documents,
then uses its unchanged Dealer: W128, threshold 0.1, vector weight 0.3, KNN
top_k 1024 / candidates 2048. Parent expansion happens before BGE ranking.
The addon is necessary because the ordinary retrieval REST endpoint caps a page
at 100; splitting a native 128 window would change grouping/order semantics.

`POST /v1/saas_native/manifest` accepts a dataset and document ID and returns
complete source passages and content hashes, without embedding vectors.
Both routes and `/ready` use the native API bearer/tenant decorators.
SaaS source bindings further restrict each request to that bot's current versions.

Build from this directory. Use the official image's `service_conf.yaml.template`
and environment configuration. Required services are MySQL 8.0.40, Elasticsearch
8.11.3, S3-compatible object storage, native Redis/Valkey, and TEI serving
`BAAI/bge-small-en-v1.5`. These are additional RAGFlow dependencies; the existing
SaaS PostgreSQL and Redis remain in place. Do not share Redis logical state or
object buckets by accident. Keep service ports private.

For a new local stack, `compose.yml` is an optional overlay on the repository's
root compose file. It uses the same dependency images as stock-dev, retains
native volumes, and bounds MySQL binary-log retention to one day / 64 MiB files.
Supply its required environment variables with your local environment file.
Start the native dependencies first, provision a native service tenant through
the official UI, register the HuggingFace embedding provider at
`http://native-tei:80` with model `BAAI/bge-small-en-v1.5`, and create its native
API token. Set the token, tenant ID and registered embedding reference in the
SaaS environment. A tenant-model UUID is supported as well as the named reference.
No Gemini key or Codex bridge is needed in this retrieval service.

For Railway, use this directory as the service root with its Dockerfile and set:

```text
API_PROXY_SCHEME=python
PORT=9380
RAGFLOW_HOST=0.0.0.0
```

Set the Railway start command to
`/ragflow/entrypoint.sh --disable-datasync --workers=1`.
Railway's Docker start command replaces the image entrypoint, so supplying only
the flags is insufficient. Compose instead passes its flags to the inherited
entrypoint. The pinned entrypoint requires `API_PROXY_SCHEME=python` to start the
Python API and task executor that own these routes. Its configuration fixes the
API port at 9380; `PORT` aligns Railway's healthcheck with that listener.
Use `/api/v1/system/ping` for the deployment healthcheck and verify the
authenticated `/v1/saas_native/ready` separately before application cutover.

Use private service DNS names, without schemes or port suffixes, for
`MYSQL_HOST`, `ES_HOST`, `MINIO_HOST`, `REDIS_HOST` and `TEI_HOST`. The upstream
template uses ports 3306, 9200, 9000, 6379 and 80 respectively. MinIO's console
port 9001 is not its object API. A restored tenant's registered HuggingFace model
must also point to the target TEI URL; changing `TEI_HOST` does not rewrite stored
model records. Preserve bucket/key layout when restoring objects. Supply a stable
`RAGFLOW_SECRET_KEY` of at least 32 characters through Railway variables.

Verify internal DNS has an IPv4 address before using the current IPv4 listeners.
Railway environments created after October 16, 2025 support IPv4 and IPv6; older
IPv6-only environments need compatible listeners before cutover. Keep these
services private. See Railway's [start-command rules](https://docs.railway.com/deployments/start-command)
and [private-network requirements](https://docs.railway.com/networking/private-networking/how-it-works).

SaaS API and ingestion worker both need:

- `RAGFLOW_URL`, `RAGFLOW_API_TOKEN`, `RAGFLOW_TENANT_ID`, `RAGFLOW_EMBEDDING_ID`.
- `RAG_COMBINED_RERANKER_URL` and `RAG_COMBINED_RERANKER_TOKEN` for the separate
  pinned BGE image in `../bge-reranker`.
- Their existing database, Redis, object storage and Gemini configuration.

Run the normal one-off SaaS migration before starting the new application.
Existing knowledge must be migrated before cutover: reindex through the existing
Knowledge jobs, or use `backend/scripts/bind_native_knowledge.py` to adopt an
already parsed native corpus without changing its chunks. That command requires
an explicit database target and document/source/manifest hashes, defaults to a
rolled-back dry run, and never changes the remote corpus. New uploads and crawls
automatically use official native upload/parse APIs, stage their manifests, and
activate only after the complete source version is ready. Bot copies queue their
own index; web page copies are source snapshots, not shared source permissions.

Retired documents are removed by a durable outbox in the existing maintenance
worker. A failed deletion is retried; active source bindings are protected.
Original source files remain governed by the platform's existing storage rules.

Before each release, verify the built Linux image, authenticated readiness,
source manifests, and a complete widget request through the destination SaaS
backend. Frozen ranking tests alone do not establish live database, queue or
network behavior. Measure capacity on the deployed hardware: CPU ranking can
take substantially longer than the same model running on a GPU.
