# Frozen observation-only instrumentation

Authorized before any new SAME8 or HOLDOUT_B result on 2026-09-21.

Quality baseline: `8136c0926da39e87adecda1bfe620f07a05b8c4c` (working Gemini 3.5 adapter); retrieval algorithm freeze `ef97a2dca4874e1a53b409738b3037b418b3f9a8`, expanded executable freeze `ed6dde00dc3742bf899cac3dbcd38fc7e0d4e2f3`. Upstream RAGFlow v0.27.2: `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.

## Observation boundary

- Request-local, bounded, copied trace events capture original/prepared queries, actual upstream helper outputs, callback latency, and already-approved row/relationship identities. No prompts, credentials, headers, or raw errors are recorded.
- Instance-local Dealer observers call the original methods with the identical arguments and return the original result objects. They snapshot model-rerank scores before cutoff and parent/TOC routes; no score, candidate, query, context, or authorization decision is changed.
- Actual CPU reranker input text/query is recorded alongside its existing hashes/scores. Existing query diagnostics remain explicitly labeled as original-query diagnostics, not prepared-query independent channels.
- The acceptance harness now validates SAME8, HOLDOUT_B and auxiliary candidates, including final citation identities, using the existing scope/READY/provenance validator and read-only index checks. Assessments never become retrieval inputs.
- Failure health observation reads counters only; no provider or quality-request retry.
- Traces are bounded to 4096 events/request; any dropped event fails the validation evidence-completeness gate, without changing retrieval decisions.

## Offline validation

168 focused tests passed with network access denied by the test fixture. This includes 12 exact tracing-off/on comparisons covering keyword/refinement/default, low/high reranker scores and child/parent evidence; an actual upstream TOC parity test; copied/bounded/request-local observations; unchanged fail-closed errors; SAME8 foreign/missing trace detection; and lossless compressed trace transport with plaintext secret scanning before compression.

AST comparisons against the baseline prove engine, scope storage, and query preparation are identical after removing observation-only hooks. Upstream search, tokenizer, synonyms, structure/TOC/parent algorithms and prompts are not edited.

Provenance: 79 destination files / 83 mappings verified against pinned upstream blobs. Syntax, secret preflight and diff whitespace checks pass. Provider/model calls during implementation/tests: **0**.

## Unchanged experiment

SAME8 and the holdout are frozen artifacts; keyword=True uniformly for the 16 quality queries. Gemini `gemini-3.5-flash-lite`; MiniLM embedding/reranker and pinned revisions unchanged. Threshold 0.2; term/neural blend 0.7/0.3; top-k 12; candidates 64; KNN 1024 / 2048; context 8192 tokens / 131072 bytes / 48 units. No post-result changes or retries; maximum 20 generateContent calls.

The exact instrumentation commit, deployment and pre-result file hashes are recorded separately in `RAGFLOW_EXPANDED_VALIDATION_FREEZE.json` before live execution. Only the new development Railway project may be deployed; no main/production access or old90 benchmark.
