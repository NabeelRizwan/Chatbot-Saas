# Phase 4.1P — Real Embedding Retrieval Canary Report

## Current continuation decision — 2026-09-18 IST

**C — PHASE 4.1P — BLOCKED**

**GEMINI_EMBEDDING_PROVIDER_FAILURE during the paired legacy-control rebuild.**

The provider-to-PostgreSQL handoff repair is **live verified by P1**. P2 started
automatically, staged all 23 documents, persisted all 1,030 structural vectors,
and persisted the first 32 legacy chunks. The next legacy provider batch failed
after the existing bounded policy's initial attempt plus two retries. The runner
stopped, closed the provider/DB resources and removed its owned schema. There was
no additional provider attempt or implementation repair after this failure.

**This is not full retrieval acceptance:** neither full P2 generation was sealed,
and **0/90 paired retrieval cases** ran. No semantic improvement/regression or
production readiness is established. The retained failure record identifies the
provider boundary but does **not** retain its final HTTP status; quota exhaustion
versus provider-server failure cannot be determined from the saved artifact.

### Checkpoint and scope

Starting branch/HEAD: `main`, `3f4fec77f78b04e49d7be1c5c1e5378417213e1a`.
The five prior Phase P scaffold/report files were audited against the recorded
3,659-test baseline; their 35 focused tests were rerun successfully, the protected
740 hashes matched, and whitespace/secret checks passed.

The explicitly authorized local-only scaffold checkpoint was created:
`d3b7097eac21ac52b89cc92d5ecc994bc30cda5a`
— `Phase 4.1P: add bounded real embedding canary scaffold`.

HEAD remains that checkpoint. **The continuation is uncommitted. No push or
deployment occurred.** No serving RAG, ingestion, parser, representation,
embedding-provider wrapper, prompt, model, ranking, FTS analyzer or candidate/
materialization budget was changed during the live run.

### Handoff repair and offline proof

The prior attempt's complete vector receipts were serialized through a bounded
console/tool channel and truncated. The new internal runner retains complete
coordinates in one Python process from the Gemini response through validation,
canonical f32 conversion, SQL INSERT, actual pgvector readback, attestation,
sealing and cosine retrieval. Coordinates are never written to output/artifacts.

The real-provider adapter requires explicit authorization, operator reference,
organization/bot, exact profile/configuration and SDK-response provenance. The
default repository still rejects real-provider use. Phase O's seal, source epoch,
read gates, scope-before-LIMIT SQL, dense/FTS execution and materialization methods
were AST-compared with the checkpoint and remain unchanged. The adapter changes
only real-versus-synthetic validation and canary staging/work bookkeeping.

P1 declares an explicit eight-vector inventory while retaining the **complete
unchanged source batch** and its mappings/atoms; it does not mutate or truncate a
Phase M batch. Full P2 has no vector-subset selection.

Output is restricted to metadata and checked to be **<=65,536 UTF-8 bytes per
record**, with bounded depth/collections and forbidden secret/vector fields.
Observed P1 summary: **4,958 bytes**; first evidence receipt summary: **2,482 bytes**;
largest retained artifact/final result: **7,626 bytes**. All **142 JSON artifacts**
passed the bounded-output validator after the process exited.

New regressions exercise the actual handoff function with eight 768-dimensional
vectors plus one query and multiple further batches, including complete SQLite
persistence/readback before summary creation. They also cover authorization,
partial seals, explicit inventory, receipt/input/profile corruption, unknown work,
completed-work reopen, legacy ledger binding, source epoch changes, P1 stop/P2
continuation gates, and forbidden/oversized output. SQLite tests are not presented
as PostgreSQL acceptance; the live P1 below supplies that evidence.

### Live execution and fixed configuration

- Runner window (UTC): approximately **2026-09-17 19:41:41.266 to 21:23:43.207**;
  elapsed **6,121,940.327 ms / 102.032 minutes**. Start is derived from the retained
  result timestamp and measured elapsed time, not a separate wall-clock trace.
- Command: `backend/.venv/Scripts/python.exe -B` invoking
  `scripts.canary_real_embedding_retrieval.main()` in the same controlled process.
  Exit **1**. Secrets/authorization were process-only; no DSN was stored in code,
  environment files, reports or console output.
- Only the previously authorized disposable target was opened. Fresh observations:
  **PostgreSQL 18.6, pgvector 0.8.6, extension namespace public**.
- Owned namespace: `canary_stagep_dc2e2658291846338833ecc4b50f6c52` — **removed**.
- Provider: **Gemini / gemini-embedding-001 / profile v1 / 768 dimensions**;
  `output_dimensionality=768`; task type/title/prefix absent; no new normalization.
- Exact UTF-8 input; `vector-attestation-f32-v1`; configuration/profile hash:
  `bd524bb94626d8d5f5282b286beffeb5fc806011685d18af16fa24619cc7e407`.
- Existing authorized development Gemini key only. No key display, replacement,
  newly persisted secret or unrelated credential inspection.
- Serial batches: maximum 8 inputs / 4,000 local tokens. SDK attempts=1; wrapper
  alone owns retries. P1 retries=0; full-build maximum two retries after initial.

### Repeated P1 — PASS

Same eight frozen entry IDs/input hashes as the historical attempt, **3,044 local
tokens**, and exactly the same mechanical query:

> Is Collagen Complex a powder or a capsule supplement?

| Gate | Measured result |
| --- | --- |
| Evidence response | 8/8 ordered inputs, one successful request |
| Query response | 1/1, one successful request, 11 local tokens |
| Profile/vector checks | 768 finite, nonzero f32 values; exactly 3,072 bytes each |
| PostgreSQL roundtrip | Exact tuple, canonical bytes, digest, input hash and provenance; no epsilon |
| Seal/read lease | INDEX_READY then CANARY_READ, normal Phase O gates |
| Seal time | 18,210.592 ms |
| Actual scoped cosine | Exactly the eight admitted entries; mapped atoms returned |
| Source epoch | Unchanged before/after retrieval and rollback-only attacks |
| Isolation | Zero unauthorized dense, FTS, routed or materialization results |
| Output | Bounded digest-only records; no vector handoff through stdout |

P1 manifest hash:
`79bca4678f271aa71b9251f6d693a815cb40cd13a20dd5c9e2eb4f22f17cfec5`.
Query input hash:
`387288b7d1dd2fe4db9357048c80e55afde0a1dad599cfc86b8668044fefa62d`.
Query canonical-vector hash:
`39bf9b108cb583f790625b508bdc6146cc7a73cee718c8f48969550ff1cbecb4`.

Authorized P1 scope: organization **538**, bot **674**, source/document **3**,
exact manifest generation/profile/source-version/crawl scope, with hard scope
applied before LIMIT. This tiny pool is **mechanical**, not semantic acceptance.

| Ranked entry ID prefix | Cosine distance | Mapped atoms |
| --- | ---: | ---: |
| 8a596500f29e | 0.41352461331207424 | 13 |
| c6a7dc565483 | 0.43209274298753886 | 2 |
| 3105a62b314c | 0.4376475021707976 | 3 |
| 69f3cb55a088 | 0.4404384986032095 | 6 |
| 3b69c885ddc3 | 0.44241217526368415 | 4 |
| 63aebd14542c | 0.4435448783176812 | 3 |
| 22167e6afc16 | 0.45016071309050154 | 2 |
| 0fadc67d2b90 | 0.46435499734609176 | 2 |

Full IDs, atom mappings, input/config/vector digests are retained in the bounded
local `p1.json` and batch summaries beneath
`.codex_phase4p/canary_stagep_dc2e2658291846338833ecc4b50f6c52/`.

### P1 real-vector security

Five rollback-only adversarial identities were exercised: foreign organization,
foreign bot, stale generation, stale source, and identical text in another scope.
Each copied the authorized real query vector, had measured raw distance **0.0**,
and was strictly stronger than the authorized candidates. Unauthorized result
counts were **0 at dense / FTS / routing / materialization for all five cases**.

These were deliberately forged database test rows, explicitly labelled
`SECURITY_TEST_COPY_NOT_PROVIDER_ATTESTATION`, not separately embedded or trusted
sealed builds. They test isolation against hostile rows and cannot satisfy the
real-provider receipt validator. No trigger was disabled. Wrong-org/bot hard
scopes were independently refused; a nonmatching active-version scope returned
zero candidates. Full-generation P2 attacks were **not reached**.

### P2 frozen build and stopping point

Frozen Phase M verification passed **23/23 batch hashes**:
**23 documents / 1,030 entries / 3,242 atoms / 217,263 local tokens**.
Aggregate digest:
`5101cadbe166c65d12c5bf203099dc035bb2357d317274a045e52ebdf40209ee`.

The legacy snapshot did not prove exact request configuration, serialized input
and real-provider receipts. The authorized **paired control rebuild** was used:
**1,092 frozen chunk inputs / 212,061 local tokens**. Planned combined evidence
inventory: **2,122 inputs / 429,324 local tokens**, below both authorized caps.
Existing serving embeddings were neither reused as proven nor modified.

| P2 item | Result before cleanup |
| --- | --- |
| Full structural + control manifests | Created in owned schema |
| Source/version/crawl pins | Frozen; all 23 documents acknowledged staged |
| Structural entries and atomic-fts-v1 | All 1,030 entry records and 3,242 atom projections staged |
| Memberships/spans/work | Staged for every document; final SQL-count snapshot not captured |
| Structural real vectors | **1,030/1,030 persisted and individually readback-validated** |
| Legacy real vectors | **32/1,092 persisted**; last four successful batches match exact first 32 control inputs |
| Next legacy batch | Provider exception; bounded retries exhausted |
| Full P2 seal/read lease | **NOT RUN** for either lane |
| Full P2 security/query evaluation | **NOT RUN** |

Earliest stopping function: `GeminiCanary._embed`,
`backend/scripts/canary_gemini_embeddings.py:153`, called by
`handoff → store_batch → build → p2` during the legacy build. The wrapper emitted
`GEMINI_EMBEDDING_PROVIDER_FAILURE`. The two preceding retry decisions imply
retry-eligible statuses in the wrapper's fixed 429/500/502/503/504 set; they do not
prove the final status or a daily-quota cause.

The final JSON's `p2: NOT_RUN` is an overly coarse completion marker: P2 **did run
partially**, as the staged-document/progress/batch records prove. It did not reach
completion. Full P2 manifest digests were stored in the database but were not
included in the retained pre-failure summary; no exact digest is invented here.

### Work reuse and restart limitation

Work is committed UNKNOWN before HTTP, then SUCCEEDED only after exact DB
readback. Completed receipts are reused only after input/profile/config/provenance
validation. **87 persisted-vector reuses** occurred, including P1 reuse and exact
duplicate inputs. Unknown-consumption work is never silently re-embedded.

Repository-level reopening is tested. Automatic crashed-process CLI recovery is
**not implemented**: a fresh invocation refuses stale owned schemas. This run's
terminal cleanup removed all vectors, including successful batches, so a future
continuation cannot resume from this cleaned database. It requires separately
authorized provider work and an explicit recovery/retention decision; do not
represent the scaffold as a fully crash-resumable operator workflow.

### Provider usage — this continuation only

| Measurement | Result |
| --- | ---: |
| Total requests/attempts | 144 |
| Successful requests | 141 (140 evidence + 1 query) |
| Failed attempts | 3 |
| Retries | 2 |
| Successful unique evidence inputs | 983 |
| Successful query inputs | 1 |
| Persisted-vector reuses | 87 |
| Persisted vector rows across P1 + P2 before cleanup | 1,070 = 8 + 1,030 + 32 |
| Successful local evidence input tokens | 217,159 |
| Successful local query input tokens | 11 |
| Attempts with unavailable provider-token accounting | 144 |
| Measured provider-call elapsed time | 227,859.000 ms |
| Actual billed tokens / monetary cost | **UNKNOWN** |

Local successful-input counters do not account for uncertain consumption on failed
attempts. The emitted numeric provider-token accumulator is zero because the SDK
supplied no counts, **not** evidence of zero usage. Failed batch HTTP status,
per-attempt timings and failed-input token totals were not retained individually.
The 140 successful evidence batch artifacts contain only bounded digest receipts.

### Paired snapshots, retrieval GOLD and metrics

All **90 historical question/history/query-contract/scope snapshots** were loaded
and frozen once without planner calls or GOLD-based scope rescue. Both lanes were
configured to receive the identical replayed snapshot/query vector and frozen
budgets. Snapshot-set digest:
`3337207fc25b1ab0788e30daca69bef8b12144a7d2e6980fd3cf7ae20cd42be7`.
The 90 evaluation query embeddings were **not requested**; only P1's query exists.

The unchanged GOLD sidecar still has **152 spans, 109 exact unique source
occurrences, 43 mapping gaps, and 90 field assignments requiring review**. The
implemented evaluator labels source-proven constituent **span-hit recall**, not
complete fact/qualification recall. No GOLD values enter retrieval inputs.

| Requested measure | Legacy | Structural |
| --- | --- | --- |
| Dense supporting-span hit recall @5/@10/@48 | NOT MEASURED | NOT MEASURED |
| FTS supporting-span hit recall @5/@10/@48 | NOT MEASURED | NOT MEASURED |
| RRF recall @10/@48 | NOT MEASURED | NOT MEASURED |
| Materialized span-hit / required-document recall | NOT MEASURED | NOT MEASURED |
| False absence / wrong-source claims | NOT MEASURED; no answers | NOT MEASURED; no answers |
| Duplicate evidence / noise / diversity / lexical collapse | NOT MEASURED | NOT MEASURED |
| ATOM_ONLY / INCOMPLETE_BUDGET / query-understanding failures | NOT MEASURED | NOT MEASURED |
| Full-generation foreign/stale result count | NOT MEASURED | NOT MEASURED |
| Dense / FTS / RRF / materialization / total p50/p95 | NOT MEASURED | NOT MEASURED |

Per-case result: **cases 1–90 NOT RUN (0 completed pairs, no case trace files)**.
No denominator of 90, recall percentage, improvement or regression is fabricated.

### Storage, timing and cleanup

Acknowledged pre-cleanup vector rows totalled 1,070, equivalent to **3,287,040 raw
coordinate bytes** at 3,072 bytes each, excluding database/index overhead. Full P2
relation/index sizes and completed build/seal timings were not captured because
the recording stage follows the paired build. Staging counts above are from
completed transactions, not a separately captured final SQL COUNT inventory.

Total runner time was **6,121,940.327 ms**; timed provider calls consumed
**227,859.000 ms**, about **3.72%**. The remaining **5,894,081.327 ms** includes
frozen reconstruction, SQL transport/persistence, validation, security and cleanup;
it is not accurately separable into DB/CPU/network stages from this run. Do not
attribute all of it to Gemini or claim production latency. P1 seal and cleanup
times were 18,210.592 ms and **8,068.568 ms**, respectively. The three-hour lease
did **not** expire; the observed stop was the provider exception.

Cleanup **PASS**: owned namespace, marker, fixture tables, vectors and indexes
removed. Unrelated catalog (126 recorded objects) remained identical, hash:
`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
The public pgvector extension was retained. Connections/engine/client closed,
process-only secret variables unset, provider ledger cleared, process exited.
Only bounded metadata/digests remain locally; **no new vector-coordinate file**.

### Validation and changed files

- Previous scaffold focused audit: **35/35 PASS**, 0.880 s.
- Expanded continuation + related O/P focused tests: **283/283 PASS**, 28.188 s.
- New handoff tests independently: **30/30 PASS**, 3.849 s.
- Pre-provider full canonical suite: **3,689/3,689 PASS**, 492.082 s, external
  network denied, no skipped Docling validation.
- Post-stop full canonical suite: **3,689/3,689 PASS**, 514.578 s, external network
  denied. This is offline regression validation, not a replacement for unrun P2 retrieval.
- Final protected hashes: **740/740 unchanged**.
- AST/import check: PASS; secret-pattern scan of all changed files: zero matches.
- Bounded-artifact scan: **142/142 PASS**. `git diff --check`: PASS.

Continuation files (all left uncommitted):

1. `backend/database/canary_schema.py` — real receipt columns and scoped work ledger.
2. `backend/services/canary_contracts.py` — exact real config and explicit P1 inventory.
3. `backend/services/canary_repository.py` — provenance validation hooks; synthetic default preserved.
4. `backend/scripts/canary_postgres_validation.py` — explicit owned Stage-P namespace/settings.
5. `backend/scripts/canary_schema_migration.py` — permit only generated owned Stage-P namespace.
6. `backend/scripts/canary_real_repository.py` — gated real staging, work, persistence/readback.
7. `backend/scripts/canary_real_embedding_retrieval.py` — one-process P1/P2 orchestration.
8. `backend/scripts/canary_bounded_output.py` — size/type/secret/vector output boundary.
9. `backend/scripts/canary_real_evaluation.py` — identical frozen replay and source-backed scoring.
10. `backend/scripts/canary_real_security.py` — rollback-only copied-vector isolation fixtures.
11. `backend/scripts/canary_real_summary.py` — conservative paired metric aggregation.
12. `backend/fixtures/canary_real_embedding_v1/plan.json` — unchanged P1/M/query digests.
13. `backend/test_canary_real_handoff.py` — 30 focused regressions.
14. `backend/scripts/test_scoped_rag_regressions.py` — test registration.
15. This report.

### Exact next step and restrictions

Do not proceed to chat/widget validation or claim full Phase P acceptance. First,
in a separately authorized continuation, retain safe per-attempt provider status
and resolve the embedding-provider block. Before repeating already consumed work,
settle durable operator recovery/retention and the measured canary transport
overhead without changing the frozen retrieval baseline. This task made no such
second repair and issued no post-failure provider request.

No production/customer DB connection; no source fetch/crawl; no ingestion; no
serving re-embedding; no chat/generation; no planner/reviewer LLM; no widget; no
90-answer benchmark; no push or deployment. Only the explicitly requested initial
scaffold checkpoint was committed; continuation changes remain uncommitted.

---

## Historical first attempt — superseded by the continuation above

The following retained record describes the earlier output-truncation failure,
not the current run. Its historical NOT RUN statements do not supersede P1's new
live PASS or P2's partial build described above.

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
