# RAGFlow native runtime validation

2026-09-21. Native validation **PENDING**, not accepted.

Transport: explicitly authorized `ragflow-derived-dev` GitHub branch; no Windows CLI/WSL. Baseline `06f2d5d4c78805f54e818cc3886cf2438e5990cf`, upstream v0.27.2 `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.

## Offline gates completed

- 143/143 focused tests PASS, including 33 new synthetic-authority/API security tests.
- Syntax/secret-pattern preflight PASS (no secret values emitted; pre-existing test/example matches reviewed).
- Provenance PASS: 30 mapped files, 32 mappings and official source blobs verified.
- No production engine/service/dependency changes. Prior unrelated untracked files preserved.

## Native gates (all NOT RUN until a Railway result is recorded)

1. Native Infinity SDK tokenizer and assets.
2. Real private Elasticsearch 8.11.3 and new volume.
3. Pinned real CPU embedding inference and vector indexing/search.
4. Native lexical query path and RAGFlow-derived hybrid retrieval.
5. Real CPU reranking; pre/post order and scores.
6. Bounded exact context/citations/version provenance.
7. Ingest v1, update v2, stale exclusion, delete and reingest.
8. Tenant A/B isolation plus wrong org/bot/generation/version rejection.
9. Authenticated external HTTP operations and component health.
10. Structured storage/model/input/authorization failures with no old-engine fallback.
11. Identical persisted sentinel/citations after restarting ONLY the new Elasticsearch service.

## Model pins

- Embedding: `sentence-transformers/all-MiniLM-L6-v2`, `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache-2.0, CPU, 384 dimensions.
- Reranker: `cross-encoder/ms-marco-MiniLM-L6-v2`, `233902d25c440f23af6f7d6e94d2946bac0bee0a`, Apache-2.0, CPU.

Model weights are not Git files. Build-time pinned downloads and real CPU smoke precede offline-only model loading at runtime. Offline tests are explicitly test doubles; successful native acceptance must use real implementations.

## Reproducible external validation (after deployment)

Set the NEW URL and A/B/admin credentials in process-only environment variables; obtain the credentials from the NEW service's Railway Variables UI. Never paste values into commands/reports/source. Run `dev/ragflow/native_acceptance.py --url <NEW_URL> --phase initial --output <safe-report.json>` outside the container. Restart only the NEW Elasticsearch service, wait for health, then run the same command with `--phase persistence`. The script clears its credential environment entries afterward. It never calls an AI provider or the old app.

No queries have run yet. No native PASS, measured RAM/CPU/latency or persistence claim is made. No 90-case/GOLD/customer evaluation, production access, main push or main merge.
