# RAGFlow Railway deployment report

2026-09-21. **STATUS: PARTIAL — local native runtime implemented; Railway deployment not yet performed.**

## Baseline and transport

Created `ragflow-derived-dev` from `06f2d5d4c78805f54e818cc3886cf2438e5990cf`. Local main is unchanged. Remote main was observed at `7c8236001ccc552c89c860b2db6a4d4c369ee211`; no merge/main push is authorized or performed. Existing 19 untracked Q2/Q4/Q4B experiment files remain untouched and excluded from staging.

The operator explicitly replaced local-upload-only deployment with a dedicated GitHub development branch. The Windows Railway CLI remains unused/blocked; no WSL or policy changes. A dry-run branch push succeeded. Native acceptance is not claimed from offline tests.

## Isolation and topology

FORBIDDEN production project: `4ca162fa-755c-4c70-b3aa-7f4166a1fb36`, `Chatbot-SaaS-Production`.

NEW project: `ragflow-derived-dev`, ID `068a5695-2cf6-4c7f-89fc-3d24a225e4a5`. Environment ID `31650c5f-fc5f-4954-9094-6d06383b3d17` (Railway's default name `production`, belonging ONLY to this isolated development project). Backend/ES/volume IDs and public URL: pending. Every mutation verifies target ownership in this new project and rejects the forbidden ID.

Development branch first runtime commit pushed and remote-verified: `a3aceb53ab0c0d6571bd80c2744f54946ef2dd75`. Main remains unchanged locally and remotely.

Two services planned: dedicated CPU backend with both real models, and private Elasticsearch 8.11.3 with persistent volume. No PostgreSQL, old DB, separate model service, GPU, extra replicas or worker. No production variables copied.

## Implemented locally

- Additive Dockerfile/config and strict build-context allowlist, isolated requirements and build-time native tokenizer/model asset preparation.
- Real pinned CPU MiniLM embedding (384 dimensions) and cross-encoder inference callbacks; safetensors, local-only runtime loading, no provider fallback.
- Standalone API with distinct synthetic tenant credentials, separate admin-only failure injection, bounded bodies/corpus, sanitized errors and per-component health.
- Elasticsearch-persisted tenant authority with CAS, pending/ready/deleted states, monotonic source versions and fresh pre/post authorization checks. Source text cannot establish authority.
- Real-channel diagnostic hooks wrapping the unchanged port; lexical/vector/hybrid candidates, real reranker scores and exact evidence/citations.
- Outside-container synthetic acceptance script: 24 generic documents plus one lifecycle/persistence sentinel, eight functional questions, tenant security, failure cases, lifecycle and separate post-restart validation.

## Offline verification

143 focused tests PASS (110 prior port tests + 33 new API/authority tests). Tests deliberately use offline doubles and do not count as native acceptance. Syntax/secret-pattern preflight PASS; reviewed pre-existing synthetic connection/encryption fixture false positives without emitting their values. Upstream provenance PASS: 30 mapped files, 32 mappings, official blobs verified. Production source/dependencies and vendored upstream files unchanged.

## Pending measured results

Native tokenizer, Elasticsearch, models, ingest/retrieval/rerank/context/citations, lifecycle, tenant isolation, service health and restart persistence: NOT RUN. Resource measurements and public URL: unavailable until deployment. Generic questions attempted: 0. Provider calls: 0. 90-case benchmark: NOT RUN. Original database/customer data/production project: NOT USED. Main push/merge: NO.

This report will be updated only with actual deployment and acceptance evidence. See the deployment plan and native validation ledger.
