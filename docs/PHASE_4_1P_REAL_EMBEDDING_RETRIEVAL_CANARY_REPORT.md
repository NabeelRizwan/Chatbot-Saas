# Phase 4.1P — Real Embedding Retrieval Canary Report

Date: 2026-09-18, Asia/Calcutta. Provider start: 2026-09-17T18:56:36.020395+00:00.

## Decision

**C — PHASE 4.1P — BLOCKED**

**P1_RESULT_CAPTURE_TRUNCATED — test orchestration failure, not a Gemini failure.**

The eight-document-input batch and one query embedding succeeded and passed local
768-dimensional finite/nonzero canonical-f32 validation. My orchestration then
serialized their complete vector receipts to the command output for handoff to
the PostgreSQL stage. That output was approximately **41,477 tokens** and was
truncated by the capture boundary (18,000-token requested output limit).
The complete vector payloads were therefore not recoverable for PostgreSQL
attestation. P1 did **not** pass its PostgreSQL/seal/retrieval gates.

Provider work stopped immediately upon detecting the capture failure. No repeat
batch, query retry, P2 build, database connection, schema creation or retrieval
was performed. This is **not** semantic acceptance and is not evidence of a
retrieval-quality regression.

### 1. Phase O checkpoint

Starting HEAD: `eeef44641810e28c1cf68eadcd207314ac8ecd39`, branch `main`.
Audited the actual 13-file closure against its report: all 12 implementation/test/
GOLD hashes matched the previously validated bytes; 740/740 protected hashes
matched; diff checks passed. The three broad secret-pattern matches were existing
dummy URL test fixtures, not credentials. No unrelated or serving diff existed.

Requested local checkpoint:
`3f4fec77f78b04e49d7be1c5c1e5378417213e1a`
— **Phase 4.1O-PG: close canary seal and source epoch safety**.

No push. Phase P remains uncommitted.

### 2. Authorization boundary

Only Gemini embedding calls were made. No chat/generation, planner/reviewer LLM,
other provider, live customer question, widget, source fetch or production action.
Credential source was the existing development `GEMINI_API_KEY` in
`backend/.env`, identified as that development embedding path in the prior
baseline report. Read only; never emitted, replaced or newly persisted.
No remembered alternative key was substituted.

### 3. Exact embedding profile

- Provider: `gemini`; model: `gemini-embedding-001`; profile version: 1.
- Output: 768 dimensions; cosine intended, not executed against PG in this run.
- SDK: `google-genai 2.22.0`.
- Embedding request configuration: `{"output_dimensionality":768}`.
- No task type, title, prefix, generated context or new normalization.
- Serialization: `exact-utf8-no-prefix-no-title-no-task-type-no-normalization-v1`.
- Attestation: `vector-attestation-f32-v1`.
- Gemini Developer API, Vertex disabled; fixed Google endpoint; 45-second timeout;
  SDK attempts=1. Wrapper owns retries; P1 used retries=0.
- Wrapper normalized-source SHA-256:
  `d85c24c7851d128b0a21e93d76644020b31edcdff08a0d2e22ed0b8741b6399d`.

### 4. Database target safety

No database was opened. No application DATABASE_URL or alternate target was used.
No CANARY_DATABASE_URL was injected because execution never reached that stage.
PostgreSQL 18.6 / pgvector 0.8.6 remain **previous Phase O observations**, not newly
verified Phase P facts. No Stage B schema exists from this task.

### 5. P1 result

Provider sub-gates passed locally: 8 responses for 8 ordered inputs, followed by
one embedding of frozen evaluation question 1. Each returned vector passed the
768-value, finite, nonzero-after-f32 and 3,072-byte checks.

Selection used structural kinds/heading context, not expected semantic results.
Eight exact Phase M entries totalled **3,044 local tokens**, below 4,000.
Query input totalled **11 local tokens**.

**P1 overall: BLOCKED** at result capture before PostgreSQL handoff.
Roundtrip, seal eligibility and scoped cosine sanity retrieval: **NOT RUN**.
Response ordering follows the existing SDK/API batch positional contract; no
extra provider calls were made to independently re-embed ordering probes.

### 6. Provider/vector attestation

Input digests and canonical f32 digests survived in the bounded accounting suffix.
Complete vector receipts did not. These hashes are not a substitute for pgvector
roundtrip proof, which remains unverified.

| Input | Exact UTF-8 SHA-256 | Canonical f32 SHA-256 |
| --- | --- | --- |
| 1 | 9e9a6679e3f12ca520582f10d675fde5ae1d2f3fcbf828d2e02a92314941e516 | fcbea283c74c2e447c53f7c605cacdd01f5ca9b914fff0b8dfa13c57134d3384 |
| 2 | 0301eee17c6d1aa060dfd0b50ba15e62416da0dfa4b653a84b7c11b30caa2e9f | 4e03191c463af62ac2e38a71abe4b6fa0c8750d498838cdc0adae4cb881af24f |
| 3 | 7d2c572decf376c2b693f2a4572359b1d3a683ff72225b19b06fb504af5e719f | f4b187fec162930bc80991fa96d71c6d277402d60604026ebf7cef4ffb554cd3 |
| 4 | 61ab17725d1bd7a7b8630ee8bb7c86ef6f7d004e504bfc8d1fcef61bd1da9e38 | cbf5530184defaec348fd3a7749d19399322822616c8eaba27bb5451a7c884f6 |
| 5 | 12786554f80089338b9144d51a31edc09bfdf941c03c9b84979d4107e0a2d35b | 1fc8085a06eed62e5f81685824d2a0b6ac043af021ae2a80e57ac82f3cab9c45 |
| 6 | b52cecf3c30eaefae27ea5e93fd1ea905123d29e171522f1fcd5be891d559fd3 | 469102dc603f6c426970c0d79fc8c0d570280d266926bd56d895440d55b68c48 |
| 7 | 611d9d651e519ce0f2fe168ed39f1ddc4d6bbdc194670d96e532dba9db74dc60 | 812f24dcfa7d211bdba4de5ce6419f8f201f96fb9d29c0beb4e3aa3000657913 |
| 8 | e4b5e7feea464cf553be63346bb8aac9e1c5da335a8c043eec254685c677110b | 39a29219328a9a1f5ba5546df4880ff04aa5e4a854ef5038ab5708daa90e1327 |
| Query | 387288b7d1dd2fe4db9357048c80e55afde0a1dad599cfc86b8668044fefa62d | 39bf9b108cb583f790625b508bdc6146cc7a73cee718c8f48969550ff1cbecb4 |

No epsilon, decimal rounding, approximate equality or synthetic substitution was used.

### 7. Structural full-build manifest

Read-only reconstruction with unchanged Phase M code verified every saved batch
against the frozen sidecar, plus the original M aggregate digest:
`5101cadbe166c65d12c5bf203099dc035bb2357d317274a045e52ebdf40209ee`.

Inventory: **23 documents / 1,030 entries / 3,242 searchable atoms /
217,263 local representation tokens**.
M implementation: `197ea1bb19ecec482352fde40c8b37300d5a85b82065030653b622c0b03a8243`.
Source version/hash, crawl identity and structural revision were retained in
each validated scope. No new source capture or parser change.

This is a **local inventory freeze**, not a staged/sealed full PG manifest.

### 8. Legacy control provenance/rebuild decision

NOT REACHED. Existing legacy vectors were not reused or represented as equivalent.
No PAIRED_LEGACY_REBUILD was performed. Serving legacy embeddings were untouched.

### 9. Provider usage/accounting

| Item | Measured |
| --- | ---: |
| P1 planned evidence inputs | 8 |
| Full structural plan | 1,030 inputs / 217,263 local tokens |
| Provider attempts | 2 |
| Successful requests | 2 |
| Failed provider requests | 0 |
| Retried requests | 0 |
| Evidence embeddings returned | 8 |
| Query embeddings returned | 1 |
| Reused vectors | 0 |
| Local evidence input tokens | 3,044 |
| Local query input tokens | 11 |
| Requests with unknown provider token accounting | 2 |

The SDK returned no per-embedding token count for these responses.
Actual billed tokens and dollar cost are **unknown**, not zero.

### 10. Phase M full vector build

NOT RUN. Eight P1 vectors were computed; no full structural lane was persisted.

### 11. Atomic FTS build

NOT RUN. Frozen inventory verified 3,242 atoms; no FTS rows/index were created.

### 12. Query embedding handling

One frozen query was embedded once:
“Is Collagen Complex a powder or a capsule supplement?”
No answer was generated. No alternate query, expansion, or extra test was used.
The complete 90-query embedding/evaluation stage was not reached.

### 13. Common planner/scope snapshot

NOT RUN. No planner, discovery, conversation-state, scope or rewriting logic changed.
The shared paired execution snapshots remain pending.

### 14. Retrieval query set

Existing REAL_CORPUS_V1_EVAL_V1: 90 unchanged cases.
File SHA-256: `e7d0314bd79bd6279f5b404ee28a9c2211e2d0ddf0313d938e10370b3f19f5b1`.
Only its first query supplied P1's permitted embedding input; no retrieval or answer
evaluation was run.

### 15. Supporting-span evaluator

NOT RUN. No new field labels, alternative supports or semantic guesses were added.
No GOLD facts were supplied to a retriever.

### 16. GOLD_MAPPING_GAP handling

Existing sidecar remains unchanged: 152 historical supporting spans,
109 exact unique source occurrences, 43 mapping gaps, and 90 paraphrased
field assignments still requiring review. No gaps were reclassified as failures.

### 17. Legacy raw dense results

NOT RUN; recall@5/@10/@48 unavailable.

### 18. Structural raw dense results

NOT RUN; recall@5/@10/@48 unavailable. No semantic claim from P1 embeddings.

### 19. Legacy FTS results

NOT RUN; recall@5/@10/@48 unavailable.

### 20. Structural atomic FTS results

NOT RUN; recall@5/@10/@48 unavailable.

### 21. RRF results

NOT RUN; recall@10/@48 unavailable. Weights, k, typing, collapse and tie rules unchanged.

### 22. Materialization results

NOT RUN. Evidence units/bytes, required-document recall, duplicate rate, source noise
and candidate diversity unavailable. Budgets and exact atom representation unchanged.

### 23. Per-case regressions

No paired case was executed, so no regression/improvement verdict is justified.
The earliest failure is the P1 **orchestration output boundary**, before PG.

### 24. False absence

Not measured; no retrieval or generated answer was produced.

### 25. Wrong resource/source

Not measured; no candidates or materialized evidence were returned.

### 26. Protected evidence categories

Not evaluated: ingredients/lists, directions/quantities, commercial roles,
review attribution, FAQ, timeline stages, warnings, comparisons and follow-ups.
No ambiguous category was promoted to a proven assignment.

### 27. Security isolation with real vectors

NOT RUN. No PG vectors existed, so stronger foreign-org/bot/stale attacks with
real vectors could not be evaluated. No database exposure occurred; **do not**
interpret absence of a run as a newly measured zero-leak acceptance.

### 28. INCOMPLETE_BUDGET cases

Not measured. No candidate/materialization budget was changed.

### 29. Vector / FTS / storage counts

Provider returned 9 vectors in process: 8 evidence + 1 query.
Persisted canary vectors: **0**. FTS rows: **0**.
Owned schemas/runs/manifests/atoms/maps/work rows created: **0**.

### 30. Provider usage/cost

See section 9. Two successful requests; actual provider tokens and cost unavailable.

### 31. Latency

- Eight-entry batch: **1,828 ms**.
- One query embedding: **500 ms**.
- Total measured provider-call duration: **2,328 ms**.

No PostgreSQL/vector/FTS/fusion/materialization latency was measured. These are
development provider measurements, not production chatbot latency.

### 32. Canonical pre/post results

- Focused P tests: **35/35 PASS**, 0.822 s with external network denied
  (initial direct mocked run also 35/35 PASS, 0.864 s).
- Full canonical pre-provider suite: **3,659/3,659 PASS**, 486.006 s.
  Docling workers returned valid JSON; no skip. Redis access was blocked by the
  offline network guard, as intended.
- Both local corpus freeze runs passed every batch digest; final aggregate matched M.
- Final AST, secret-pattern and whitespace checks: **4/4 PASS**.
- Protected hashes: **740/740 unchanged** before and after the provider attempt.
- git diff --check: PASS.
- Post-retrieval canonical suite: **NOT RUN**, because no real retrieval occurred;
  the explicit P1 failure stop was honored. No tested provider code changed after
  its pre-provider suite.

### 33. Cleanup

Provider client closed; in-memory key reference cleared; its process exited.
No new credential file, environment entry, provider profile or bot setting was
created. Dedicated canary secret variables absent at final check.
No database connection/schema existed, so no DROP/cleanup action was needed.
Incomplete vector-output capture was discarded; only metrics/digests are retained.
No production/customer DB, serving corpus, extension or unrelated object was touched.

### 34. Limitations and current diff

This task does not deliver a completed real-vector PG adapter or full P2 runner.
The capture failure occurred in the transient execution orchestration, not in
Gemini, Phase M, pgvector or measured semantic retrieval.

Uncommitted Phase P files:
- `backend/scripts/canary_gemini_embeddings.py` — explicit bounded embedding client.
- `backend/scripts/canary_semantic_inventory.py` — exact frozen inventory checks.
- `backend/test_canary_gemini_embeddings.py` — 35 offline safety tests.
- `backend/scripts/test_scoped_rag_regressions.py` — register those tests.
- This report.

No serving/runtime RAG files, schemas, migration logic, prompts, bot settings,
retrieval arithmetic, source epoch/seal contract or protected representation changed.
Final HEAD remains `3f4fec77f78b04e49d7be1c5c1e5378417213e1a`.
Working tree intentionally contains the five Phase P files above.

### 35. Exact next step

Repair the **test orchestration handoff** so vectors remain in one bounded process
through PostgreSQL persistence, exact readback and seal validation; emit only
bounded metrics/digests to the tool channel. Add a large-result handoff regression.
A fresh P1 would require repeating already-used provider inputs, so it was not
attempted in this failure-stopped run. After an explicitly authorized continuation
passes all P1 gates, proceed automatically to the full paired canary.

No P commit, push, deployment, production operation, chat generation, widget run,
90-answer benchmark, crawl, ingestion or serving re-embedding occurred.
