# RAGFlow-derived isolated Railway deployment plan

Date: 2026-09-21. Status: IMPLEMENTED LOCALLY; native deployment and acceptance pending.

## Authorized transport change

The operator now authorizes normal pushes ONLY to `ragflow-derived-dev` in the existing `NabeelRizwan/Chatbot-Saas` repository. That branch was created from the port HEAD below. Local main is unchanged; remote main was separately observed at `7c8236001ccc552c89c860b2db6a4d4c369ee211`. No main merge/push. A dry-run branch push succeeded.

This supersedes all local-source-only/no-GitHub-push instructions in this historical plan. Use the dedicated Dockerfile from the development branch, with an empty NEW service configured before source connection/deployment. The Windows CLI is not used or repaired; no WSL or policy bypass. Strong independent A/B tenant tokens plus a separate admin failure-check token will live only in NEW Railway Variables and process memory.

## Preserved baseline and destination

- Branch: `main`; HEAD: `06f2d5d4c78805f54e818cc3886cf2438e5990cf`.
- RAGFlow upstream: v0.27.2, `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.
- Existing local port commits: `cd7ac160772612b7db2f5d9317dc290079da175b` and the HEAD above.
- Proposed NEW project: `ragflow-derived-dev`; no visible name collision at inspection.
- `FORBIDDEN_EXISTING_PROJECT_ID`: `4ca162fa-755c-4c70-b3aa-7f4166a1fb36` (`Chatbot-SaaS-Production`).
- Before EVERY future mutation, verify the target is the newly created project, differs from the forbidden ID, and owns the selected environment/service/volume. Do not rely on CLI ambient linking.
- No new project/environment/service/volume ID exists yet. Do not reuse any existing project.
- The original engine remains `current`; accepted Q1/Q3 and existing databases/configuration are untouched.

## Minimum topology, to be implemented after source-upload access works

| Service | Implementation | Initial bounded development sizing | Exposure / persistence |
| --- | --- | --- | --- |
| `ragflow-dev-backend` | Linux Python 3.12; isolated FastAPI app; existing RAGFlow-derived port; native Infinity SDK tokenizer; real CPU embedding and reranker | One process/replica, roughly 2 vCPU ceiling and 2 GiB RAM planning budget; measure before claiming sufficient | Only public service; strong development authentication; model assets preloaded into image |
| `ragflow-dev-elasticsearch` | Elasticsearch 8.11.3, matching the port's existing runtime plan and DSL | One node/replica; 1 GiB JVM heap, approximately 2 GiB container budget | Railway private network only; dedicated persistent volume at `/usr/share/elasticsearch/data` |

These are estimates, not provisioned reservations or observed consumption. No GPU, autoscaling, HA, worker, Redis, PostgreSQL, separate model service, paid addon or plan upgrade is planned. Stop before any unusually large resources or explicit upgrade.

The standalone port accepts explicit scope/model/storage objects; it does not require the application's SQL database. A new development authority layer must persist only synthetic tenant/source/version/active-generation metadata in the NEW Elasticsearch service and construct trusted `AuthorizedScope` objects internally. Caller JSON must never establish authority. Version activation, deletion and concurrent reads must fail closed. Do not mount the existing platform router if doing so would connect to the original application DB.

## Proposed real model pair

Verified from publisher model cards and Hugging Face model metadata on 2026-09-21; not downloaded, installed or executed in this task.

| Role | Model / exact revision | License | Weight file | Runtime plan |
| --- | --- | --- | --- | --- |
| Embedding | `sentence-transformers/all-MiniLM-L6-v2`, `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | Apache-2.0 | `model.safetensors`: 90,868,376 bytes | 384-dimensional CPU Transformers encoder with model-card mean pooling/normalization; preserve the port's title/content blending |
| Reranking | `cross-encoder/ms-marco-MiniLM-L6-v2`, `233902d25c440f23af6f7d6e94d2946bac0bee0a` | Apache-2.0 | `model.safetensors`: 90,870,598 bytes | CPU sequence-classification model; sigmoid score conversion for the port's bounded reranker contract |

Combined weight payload is 181,738,974 bytes, not total runtime memory. The proposed 2 GiB backend budget includes Python/native libraries, model weights, activations and API overhead; actual peak RAM and CPU latency must be measured. Small batches and CPU thread limits are appropriate. Both models are small real learned models, not deterministic fixtures; licenses are permissive. The embedding model's published default truncation is 256 wordpieces; encoding truncation must not truncate stored evidence or citations. Do not present the reranker model card's GPU throughput as Railway CPU performance.

Sources: [embedding model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/blob/main/README.md), [reranker model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/blob/main/README.md).

## Native image and API boundary

Use additive deployment files, not the current production Dockerfile/dependency environment. Linux must install the existing separate RAGFlow dependency set and required build tools for `datrie`, Infinity SDK 0.7.3, parser dependencies, CPU model runtime, NLTK WordNet/tokenizer assets and tiktoken encoding data. Preload pinned model assets; no inference-time provider calls or automatic downloads. OCR/DeepDoc remains deferred.

Only allowlisted engine/deployment files and license notices may enter the source archive. Exclude `.env`, credentials, `.git`, customer corpora, saved benchmarks, local caches, rejected experiments and unrelated source. Do not push GitHub.

Proposed routes: `/ragflow-dev/health`, authenticated ingest/retrieve/context, and scoped source delete. Detailed health reports Elasticsearch, tokenizer, embeddings, reranker and engine separately; green requires all required components. Strict payload limits and sanitized structured errors are required. No unrestricted destructive route or publicly accessible Elasticsearch.

Generate a strong development credential only when deploying; store it as a secret variable in the new backend and use process memory for acceptance. Never save/print it in code, commands, reports or logs. Operator retrieves it from the NEW service's Railway Variables UI. Use separate server-side tenant authorization in addition to the outer credential.

## Validation order

1. Resolve the local source-upload/authentication blocker below; verify the approved deployment path.
2. Implement the isolated native image, authority/API, health and reproducible synthetic smoke scripts; run focused offline security/contract tests.
3. Create only the NEW project, record all IDs, configure modest resource ceilings, private Elasticsearch and its new volume, then deploy backend from allowlisted local source.
4. Verify real Linux tokenizer, model initialization, Elasticsearch health/index creation, and component health from outside the container.
5. Ingest 10-30 synthetic text/Markdown/HTML documents with headings, paragraphs, lists, tables, overlapping terms and exact facts. No old corpus, GOLD or benchmark.
6. Capture lexical/vector/hybrid candidates, real reranker input/output order and scores, exact context, full citations, scope/version identities, bytes/units and stage timings. Explicitly report unsupported negative/follow-up semantics rather than adding quality heuristics.
7. Verify v1 -> v2 activation, stale exclusion, deletion, reingestion; verify two deliberately overlapping test tenants and wrong bot/version/generation fail closed on REAL Elasticsearch.
8. Exercise structured storage/model/embedding/reranker/input/authorization failures; no old-engine fallback. Distinguish controlled failure injection from the real successful native path.
9. Ingest/retrieve a persistence sentinel, restart only the NEW Elasticsearch service, and retrieve the same sentinel/identities after restart. Leave the test index intact.
10. Inspect service logs for crashes/OOM/reconnect loops/dependency failures/secret leakage; record memory/CPU/index size and ingest/retrieve/rerank latency as development observations.
11. Only after every mandatory native gate passes, create scoped LOCAL commits. No push, production switch or 90-case run.

## Historical transport blocker (superseded by authorized GitHub branch)

Connected Railway tool authentication passes. However, installed local `railway.exe` execution was denied by Windows Application Control. Its Node shim does not reliably report that native failure. Do not disable or bypass the policy.

The local Railway config exists and contains OAuth credential fields, but a minimal direct API `me { id }` read using its saved access token is authorization-refused. No token value was printed; no credential file was modified. This probe does not establish whether the token is expired or has another authorization issue. No refresh or scope modification was attempted.

The connected tool catalog can deploy GitHub sources or container images but exposes no local-source archive upload operation. The official CLI supports local upload; its published source also identifies the upload HTTP route, but a working authorized local credential is not established. No alternate source upload was attempted, and no GitHub push is permitted.

No CLI repair or login is now requested. The newly authorized GitHub branch transport replaces this blocked local-source-upload path. Provision after committing and pushing only that development branch. Native gates remain mandatory.

References: [Railway local upload](https://docs.railway.com/cli/up), [Railway integration choices](https://docs.railway.com/agents), [API authentication](https://docs.railway.com/integrations/api), [official CLI upload implementation](https://github.com/railwayapp/cli/blob/master/src/controllers/upload.rs).
