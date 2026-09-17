# Phase 4.1O-PG — Vector attestation repair and PostgreSQL acceptance

Date: 2026-09-17 (UTC). Synthetic, isolated disposable-database validation only.

## Decision

**B — PHASE 4.1O STAGE A — COMPLETE**

**POSTGRESQL MECHANICS STILL NEED REVISION**

The float32 repair is verified on real PostgreSQL. However, three required
seal-negative cases were unexpectedly accepted as `INDEX_READY`: a different
manifest evaluation identity, an unstaged generation, and an epoch-only source
change after staging. This is not full PostgreSQL acceptance and does not
authorize real embeddings. No second runtime repair was attempted.

## Checkpoint and preservation

- Starting branch: `main`; starting HEAD: `4703119071b0380bd7399d9377234b47cffda5c0`.
- The entry working tree contained exactly the five expected PG closure files.
  Their implementation/report audit passed; no unrelated file was staged.
- Requested checkpoint created: **`5334f6a318a5cdc457b9135b4ed3d50c0a6bc0a1`**.
- Message: `Phase 4.1O-PG: add disposable PostgreSQL validation harness`.
- Its five files: `backend/scripts/canary_postgres_validation.py`,
  `backend/test_canary_postgres_guard.py`, `backend/test_canary_stage_a_postgres.py`,
  `backend/scripts/test_scoped_rag_regressions.py`, and
  `docs/PHASE_4_1O_POSTGRESQL_VALIDATION_REPORT.md`.
- No push. New repair, tests, extended harness and this report remain uncommitted.
- Final branch: `main`; final HEAD: `5334f6a318a5cdc457b9135b4ed3d50c0a6bc0a1`.
  Working tree intentionally dirty with only the ten repair/closure files listed
  below; index empty. No second commit. The nine code/test/GOLD files are byte-
  identical to the versions validated before PostgreSQL; only this report was
  added afterward.
- All **740/740** protected pre-O file hashes match. No inventory was rewritten.
  Phase M/L representation, HardKnowledgeScope, routing, RRF, FTS policy, mapping,
  budgets, heading policy, serving RAG and application migrations are unchanged.

## Original defect and narrow repair

The canary vector column's actual SQLAlchemy read path returns a list of Python
floats decoded from pgvector's decimal output. Thus `0.6854400634765625` can return
as `0.68544006`: different Python values representing the same stored binary32
coordinate. The old seal compared arbitrary decoded floats and JSON-derived
hashes directly, producing a false `ENTRY_VECTOR_CORRUPTION`.

`services/canary_contracts.py` now supplies one canonicalization implementation:

1. Exactly 768 real numeric, non-boolean coordinates; reject non-finite input.
2. Explicit IEEE-754 binary32 conversion using `struct.pack/unpack('!768f', ...)`.
3. Reject binary32 overflow/non-finite output and vectors that become all-zero
   after quantization. Nonzero subnormal coordinates remain valid.
4. Normalize both signs of zero to positive zero; this is an explicit identity rule.
5. Hash exactly **3,072 big-endian binary32 bytes** with SHA-256, not decimal JSON,
   repr, locale-dependent formatting, or PostgreSQL text.

`validate_vector`, synthetic staging, structural/legacy persistence, and seal
readback share this helper. Equality remains exact after canonicalization. There
is no epsilon, `isclose`, decimal rounding, omitted hash or vector-comparison bypass.
The unchanged self-cosine query test uses its pre-existing distance-score bound;
that is separate from the new exact identity assertions.

### Explicit version/reuse identity

Version: **`vector-attestation-f32-v1`**. It is a required profile field, not a
default silently attached to old manifests. It is also included in the synthetic
configuration hash and persisted as a NOT NULL/CHECK-constrained provenance field
on both vector-bearing canary tables. Profile hashes already bind the manifest,
full row keys, work/reuse identity and typed route identity. Both seal lanes verify
the stored version and binary digest. An old profile without a version, an unknown
version, or an old JSON vector digest is refused rather than reinterpreted.

Text input hashes retain their existing exact UTF-8 meaning. Synthetic provenance
remains `SYNTHETIC_TEST / canary-local-fixture / sha256-v1`; its authoritative output
is now explicitly canonical binary32. Mock provider-shaped arrays use the same
numeric contract, but REAL_PROVIDER remains unauthorized in Stage A.

## Additive frozen GOLD

`backend/fixtures/canary_vector_f32_v1/gold.json` was created and hashed **before**
the runtime repair/evaluation. LF-normalized SHA-256:

`59072664a720322ab1ffefc0a2891de458a2625bfadc3f83936d2dbad105e877`

It freezes all 25 requested categories: exact/quantized coordinates; tiny positive
and negative values; normal positive/negative values; near-one; repeated and 768-D
vectors; JSON/shortened-PG/Python representations; repeated binary32 conversion;
digest stability and a one-coordinate change; signed zeros; NaN and both infinities;
zero vectors; 767/769 dimensions; locale/serialization independence; and synthetic
repeatability. Additional cases cover booleans, strings, overflow and all-underflow.
Fixed coordinate hex and a fixed full-vector digest are independent expected values.
No pre-existing GOLD was edited.

## Offline validation

| Run | Result |
| --- | --- |
| Before checkpoint: existing O + PG guard | 137/137 PASS, 22.481 s |
| First new vector/O/M/L run | 499 PASS / 1 FAIL, 112.662 s; see fixture correction below |
| Corrected focused vector/O/M/L/PG guards | **502/502 PASS**, 112.499 s |
| Fresh full canonical suite before any PG connection | **3,585/3,585 PASS**, 561.398 s |
| Final full canonical suite after the PG run | **3,585/3,585 PASS**, 493.934 s |
| Changed Python AST/import checks | PASS |
| Protected hashes / secret scan / diff check | 740/740 unchanged / PASS / PASS |

The initial new test incorrectly shortened every float32 coordinate to eight
significant decimal digits; that cannot round-trip every binary32 value. Only the
new readback emulator was corrected to NumPy's shortest round-trippable binary32
decimal output. Frozen GOLD, production expectations, and runtime comparisons were
not weakened. Two additional legacy-lane attestation tests brought the focused
count to 502. The new canonical-vector module contributes 42 tests to the canonical
baseline of 3,543.

Commands used the existing backend `.venv`, `-B`, and the established
`scripts/test_scoped_rag_regressions.py` runner. A process-only wrapper denied
external socket/HTTP/provider/source access; the canonical runner also denied
application DB connections. The Windows asyncio loopback socketpair exception
does not permit external connections.

### Prior Docling failure

The earlier full-suite non-JSON worker setup failure remains historical evidence,
not reclassified by an isolated retry. The new pre-PG **full** run completed all
3,585 tests. Its real Docling workers returned valid JSON; the expected negative
worker returned exit 1 with valid error JSON. A process-only diagnostic observer
captured exit code, JSON validity, output lengths and sanitized stderr categories/
hashes without changing parsing semantics or source. No Docling/environment fix,
skip or test weakening was made.
The final post-PG full run also completed **3,585/3,585** tests with valid JSON
worker output; the prior setup failure did not recur in either clean full run.

## Disposable PostgreSQL execution

One fresh coherent acceptance run, from preflight, after the clean offline gate.
Only the reauthorized CANARY target was used; no normal application DATABASE_URL.
No pgvector reinstall. Provider/source transports were blocked during the run.

- PostgreSQL **18.6**, server version number **180006**, UTF8, Etc/UTC.
- pgvector **0.8.6**, existing extension namespace `public`.
- Target fingerprint: `f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
- New owned namespace: `canary_stagea_17307a023fc844c8a451e4c96cad43bb`.
- Driver: explicit `python -B test_canary_stage_a_postgres.py`; **exit 1**.
- Gate summary: **8 PASS, 1 FAIL, 4 NOT RUN**. Final schema cleanup separately PASS.

| Gate | Result | Elapsed ms |
| --- | --- | ---: |
| Preflight | PASS | 6284.481100010453 |
| Upgrade / downgrade / re-upgrade | PASS | 39933.31649998436 |
| Schema / constraints / GIN | PASS | 3655.0146999943536 |
| Staging / exact round trip | PASS | 123697.80089997221 |
| Invalid vector application checks | PASS | 12411.563400004525 |
| Database rejection cases | PASS | 32546.364799985895 |
| Normal seal / read lease | PASS | 10240.86520000128 |
| Real query / FTS / RRF / materialization / plans | PASS | 66956.4177999855 |
| Seal-negative cases | **FAIL** | 105442.32770000235 |
| Stronger foreign/stale candidate fixtures | NOT RUN: prerequisite failed | N/A |
| Rich typed/continuation/ATOM_ONLY fixtures | NOT RUN: prerequisite failed | N/A |
| Multi-session races | NOT RUN: prerequisite failed | N/A |
| Selective Run A/B cleanup | NOT RUN: prerequisite failed | N/A |
| Final owned-schema cleanup | PASS | 9039.973000006285 |

Sum of timed gates plus final cleanup: **410208.1250999472 ms**. This excludes
minor wrapper/setup overhead and is not a production latency measurement.

## Migration, constraints, storage and vector invariants

Fresh upgrade created all **14** canary tables. Downgrade removed the run-owned
schema objects and retained ownership/source-history/lifecycle/node tables;
re-upgrade passed. These operations stayed inside the owned namespace. Final
selective cleanup/downgrade after populated fixtures was not reached.

Real catalog: **14 PK, 3 UNIQUE, 15 FK, 20 CHECK, 230 NOT NULL** constraints/columns;
both vector-bearing columns are actual `vector(768)`.

Per run (A and B independently asserted equal): 1 run; 2 manifests/document pins
(structural + legacy); 11 entries, vectors and succeeded work rows; 21 atoms;
31 memberships; 35 spans; 21 legacy members. Two runs share immutable source history.

Before seal, all **11 structural vectors** read through the actual driver path
had exactly equal canonical tuples, bytes and SHA-256, plus equal input hash,
profile/config identity and attestation version. Decoded values were Python
`list` / `float`. The normal seal also attested every legacy vector with the same
canonical contract and reached `INDEX_READY`, then `CANARY_READ`, without bypass.

| Invariant | Enforcement actually exercised |
| --- | --- |
| 768 dimensions | Application validation; real DB column type separately confirmed |
| NaN / Inf / zero rejection | Application validation before INSERT; do not credit these five cases to PG |
| Boolean/non-numeric, overflow, quantized all-zero | Focused application tests |
| Exact coordinate/input/digest identity | Application staging + actual PG round trip + seal |
| Version and synthetic provenance | Required profile contract; DB NOT NULL/CHECK; seal |
| Full tenant/bot/run/manifest/source/profile relationships | FK/UNIQUE plus run-state trigger negative INSERT tests |
| Duplicate vector | Actual PG PK rejection, SQLSTATE 23505 |
| Missing embedding | Actual NOT NULL rejection, SQLSTATE 23502 |
| Invalid span bounds | Actual CHECK rejection, SQLSTATE 23514 |

All **23/23** pre-existing relational attacks were rejected and savepoint changes
rolled back. Organization/bot/absent-run attempts hit `P0001` (run-state trigger);
foreign source/manifest/generation/profile/entry/member/node references hit
`23503`; duplicate vector and input-hash mutation of an existing PK hit `23505`.
The latter is **not** independent proof of an input-hash FK rejection. No cross-
tenant INSERT succeeded; the stronger-candidate retrieval leakage gate remains
unrun, so no full retrieval-isolation acceptance is claimed.

After staging: **14 tables, 19 indexes**; table main bytes **409600**; summed table
total bytes **2121728** (includes indexes/TOAST); standalone index bytes **614400**.
Do not add index bytes to table-total bytes again. Entry vectors occupied 16384
main / 204800 total bytes; legacy members 65536 main / 352256 total bytes; GIN
24576 bytes. All measurements are disposable synthetic-fixture storage only.

## Measured remaining seal defects

| Negative fixture | Actual result |
| --- | --- |
| Missing vector | REFUSED: INCOMPLETE_BUILD |
| Extra undeclared vector/entry/work | REFUSED: INCOMPLETE_BUILD |
| Missing atom | REFUSED: INCOMPLETE_BUILD |
| Missing mapping span | REFUSED: SPAN_CORRUPTION |
| Different manifest evaluation hash | **ACCEPTED: INDEX_READY** |
| Source lifecycle epoch increment, unchanged fingerprint/readiness | **ACCEPTED: INDEX_READY** |
| Cancelled run | REFUSED: INVALID_TRANSITION |
| Expired approval | REFUSED: RUN_EXPIRED |
| Generation not staged in the run | **ACCEPTED: INDEX_READY** |

Each fixture was constructed with normal create/INSERT operations under active
constraints and triggers. No trigger was disabled, no state was force-updated,
and no accepted bad state was committed: each negative case's savepoint was rolled
back. The runner collected the nine outcomes, raised `SEAL_NEGATIVE_ACCEPTED`,
and stopped dependent gates without a retry or another runtime repair.

Exact read-only code explanation: `CanaryRepository.transition` (line 131) calls
`_run` (line 60), which identifies the scoped run/approval but not the supplied
manifest hash or generation. `_validate_run` (line 208) then validates stored
manifests belonging to that run, rather than requiring the transition argument to
match a stored manifest. Hence a changed evaluation identity or unstaged generation
can advance the valid stored run. Separately `_fresh` returns lifecycle epochs,
but sealing does not compare them to an epoch captured before the build. An
epoch-only increment is accepted when the fingerprint/readiness remain unchanged.
This does **not** demonstrate that a different source fingerprint or foreign
tenant was accepted; do not generalize the measured failure beyond these cases.

The first negative case unexpectedly accepted was **manifest_mismatch**.
The vector-only repair did not change these transition/freshness decisions.

## Actual retrieval, FTS, RRF and exact evidence

Dense exact cosine returned **11** authorized entry candidates; no ANN was added.
FTS ran the real English `websearch_to_tsquery` / `ts_rank_cd` path:

| Category | Input | Actual hits / status |
| --- | --- | --- |
| Word | console | 2 / indexable |
| Phrase | "before renewal" | 2 / indexable |
| OR | console OR renewal | 4 / indexable |
| Negative | console -straightforward | 1 / indexable |
| Stemming | provide | 1 / indexable |
| Number | 42 | 1 / indexable |
| Currency-like | $42 | 1 / indexable |
| Identifier | ERR-42/ALPHA | 1 / indexable |
| Empty | empty string | 0 / empty |
| Non-indexable | -console | 0 / non_indexable |

Actual dense/FTS results entered the unchanged typed RRF: one-based ranks, weights
1/1, k=60, exact channel contributions, missing-channel zero and stable repeated
output checked. There were **11 fused routes**, **4 raw FTS hits / 4 FTS routes**,
and **4 raw witness-ledger records**. This fixture did not demonstrate an actual
multi-hit collapse or ATOM_ONLY route; those broader DB fixtures were not reached.
Offline O coverage is not substituted for those outstanding PG checks.

Actual materialization returned **21 exact source payloads / 96523 bytes**,
within 48 units / 131072 bytes / 32 children. Every returned payload was compared
against its complete expected source projection, not entry search text. The later
rich typed review/timeline/qualifier/continuation/commercial/quantity/UTF-8 fixtures
and ATOM_ONLY DB test were not reached; no complete claim for those gates is made.

Observed synthetic remote timings: dense channel **1492.605100007495 ms**; FTS
channel **1356.665700004669 ms**; fusion **0.10340000153519213 ms**;
materialization **40615.09300000034 ms**; full internal query
**45363.96820002119 ms**. The client path performs many remote repository calls;
the much smaller server EXPLAIN timings below must not be confused with end-to-end
latency. No performance optimization was attempted.

## GIN and natural EXPLAIN ANALYZE / BUFFERS

`ix_canary_atoms_content_fts_en_v1`: **exists, valid, ready**. Actual expression:

```sql
USING gin (to_tsvector('english'::regconfig, COALESCE(canonical_text, ''::text)))
```

Both plans were collected with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` using
bound parameters. **No forced-index/enable_seqscan setting was used.**

| Natural plan | Dense exact cosine | FTS |
| --- | ---: | ---: |
| Planning ms | 0.566 | 0.651 |
| Execution ms | 0.214 | 0.348 |
| Authorized sources | 1 | 1 |
| Candidate vector/atom rows read | 11 | 21 |
| Output rows | 11 | 4 |
| Top-level shared hits / reads | 32 / 0 | 21 / 0 |
| Rows removed by join filter | 0 | 17 |
| Rows removed by index recheck | 0 | 0 |
| Sort | quicksort | quicksort |
| GIN naturally selected | N/A | **NO** |

Dense shape: scoped document/lifecycle/run primary-key scans → materialized
eligible sources/vectors → vector PK scan → CTE cosine sort → LIMIT.
FTS shape: one-row query CTE + scoped sources → atoms PK scan (21 rows) → FTS
join/filter (17 removed) → rank sort → LIMIT (4 rows) → outer result sort.
The valid GIN index was not naturally chosen for this tiny, tightly scoped
fixture. That is not by itself a failure. No forced plan is presented as natural.
SQLAlchemy emitted a Cartesian-product warning for the intentional one-row query
CTE; the actual natural plan and query results above were captured, not optimized.

## Concurrency and cleanup

New opt-in multi-session cases cover duplicate work, cancellation before a blocked
seal, late work after cancellation, duplicate manifest/generation, source epoch
during read, OFF during read and cleanup during read. They use the existing bounded
statement/lock timeouts and owned connection factory. **They were not executed**
because seal-negative acceptance failed. No race-safety claim is made.

Selective Run A deletion preserving Run B/shared history/legacy controls also
remains **NOT RUN**. The required independent final **owned-schema cleanup passed**:
namespace, marker, tables, vectors and indexes removed; unrelated catalog remained
126 objects with unchanged hash:

`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`

pgvector 0.8.6 was retained. No DROP DATABASE, DROP EXTENSION or DROP public. Engines
were disposed, connections closed, and all CANARY secret/approval environment
variables removed in finally blocks. No credential URL or values were written to
source, .env, logs or this report. No unresolved owned-schema cleanup remains.

## New uncommitted files/changes

- `backend/services/canary_contracts.py` — canonical binary32 helpers and explicit profile version.
- `backend/services/canary_repository.py` — structural/legacy binary attestation at staging/seal.
- `backend/database/canary_schema.py` — isolated vector provenance version columns/checks.
- `backend/test_canary_stage_a.py` — explicit version in two profile test constructors.
- `backend/test_canary_vector_f32.py` — 42 focused GOLD/runtime attestation tests.
- `backend/fixtures/canary_vector_f32_v1/gold.json` — additive frozen numeric cases.
- `backend/scripts/test_scoped_rag_regressions.py` — register the new focused module.
- `backend/test_canary_stage_a_postgres.py` — exact readback, legacy fixture,
  extended gate orchestration, truthful complete-acceptance result.
- `backend/scripts/canary_postgres_extended.py` — opt-in PG assertions/plans/negative
  builds/scoped and rich fixtures/multi-session tests; no application entry point.
- This report. The checkpointed historical PG report is preserved unchanged.

## Limits, boundaries and exact next step

Semantic GOLD is unchanged: 90 cases, 152 supporting spans, 109 unique source
occurrences, 43 coverage gaps, and 90 field associations still review-required.
No semantic recall acceptance, 23-document semantic run or answer benchmark.

Provider/model/embedding calls: **0**. No production/customer DB, customer corpus,
source fetch, crawl, ingestion, re-embedding, public endpoint, application API,
Railway configuration/deployment or push. Only the requested initial checkpoint
was committed; the repair/closure is left for review.

Next: review this vector repair and separately authorize a narrow seal
manifest/generation identity and source-epoch contract correction, then rerun the
full disposable acceptance including the four unreached gate groups. Do not begin
real Gemini embeddings or semantic evaluation yet.
