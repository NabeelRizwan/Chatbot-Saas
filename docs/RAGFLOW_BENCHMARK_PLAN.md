# RAGFlow comparison plan — NOT EXECUTED

The existing 90 cases and GOLD were not inspected to design this port and were not executed by the new engine. They are a regression set, not a true holdout. No HOLDOUT_B questions/labels were created or fabricated.

backend/ragflow_derived/evaluation.py provides compare_saved_queries with caller-supplied queries, authorized scope, current-engine callback and derived engine. It captures separate lane identities, exact hashes, context and timings without loading a corpus, credentials or GOLD itself. One synthetic contract test invokes both callbacks; it is not a benchmark result. This is ready as a harness interface, not a completed benchmark runner with quality instrumentation.

## Prerequisites to authorize separately

1. Install/validate the declared optional dependencies and native tokenizer resources; start only the loopback ES service.
2. Native generic synthetic ingest/update/delete/retrieval smoke, including mapping/scripted similarity, lexical+KNN prefilters, ready activation and real-model dimension compatibility.
3. Select licensed embedding/reranking models and approve any provider usage explicitly. Do not silently reuse incompatible current vectors: this port weights title/content embeddings.
4. Give both engines equivalent immutable authorized source/version inventories. Keep current accepted Q1+Q3 code unchanged and isolated from rejected experiments.
5. Capture pre-retrieval lexical/vector candidate identities and rerank traces for the native port; current neutral output alone does not expose full independent-channel recall.
6. Freeze engine parameters and manifests before comparative scoring. No iterative known-case tuning.

## Later metrics

| Stage | Measurement |
| --- | --- |
| Vector and lexical | Independent recall@K, exact-term/semantic recoveries, in-scope document recall |
| Hybrid / reranked | Candidate recall, rank metrics, threshold exclusions and weighted-score breakdown |
| Evidence/context | Final supported obligations, complete exact evidence, document coverage, byte/unit exclusions |
| Noise / duplicates | Irrelevant-source and redundant-text rates, with common denominators and explicit annotations |
| Latency | Parse/embed/index/search/rerank/context wall times, p50/p95; service cold/warm state and hardware |
| Security | Stronger foreign matches, scope narrowing/revocation, stale/delete/version/profile scenarios; zero leaks |
| Failure paths | No provider fallback; native errors recorded unscored, never disguised as quality misses |

Use a genuinely unseen HOLDOUT_B corpus and questions authored independently of this implementation, with separately established source-grounded GOLD. Do not derive HOLDOUT_B from the old case list or use its labels in runtime. Include multiple domains/formats, paraphrases, follow-ups, ambiguous requests, exclusions, comparisons, numeric facts, long documents and adversarial instructions. Document label uncertainty instead of manufacturing target answers.

Native runtime and model readiness come before any 90-case or holdout run. Benchmark results, quality gains and production readiness are all unclaimed.
