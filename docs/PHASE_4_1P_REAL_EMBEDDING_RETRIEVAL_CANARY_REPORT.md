# Phase 4.1P — Real Embedding Retrieval Canary Report

## PHASE 4.1P — FINAL 90-CASE RETRIEVAL RESULT

**C — PHASE 4.1P — BLOCKED. Still 81/90 pairs and 163/180 saved lanes.**

Updated **2026-09-19**. All 163 starting results remain byte-identical. The
case-82 payload diagnosis and five-row equivalence gate completed, but the one
newly authorized measurement failed **earlier, in the entry-membership SELECT
inside `CanaryRepository.children()`**, before any evidence payload call.
The exact failing entry was not captured by the existing evidence-only
telemetry. The required fresh exact-scope retry could therefore not be
authorized; the guard stopped execution. No additional measurement or repair
was attempted. This is not a wall-clock/deadline stop.

### Starting state and local checkpoint

- Started on `main` at `de6728e30291eca3de2cedb9ffda464168508bd9`, with the eight
  expected uncommitted case-75 diagnostic/transport/test/report files only.
- Fresh initial audit: **210/210 tests PASS in 52.636 seconds**; 740 protected
  hashes unchanged; 163 saved lanes and 81 pair checksums valid; all 149 earlier
  lane hashes unchanged; 11,662 bounded JSON artifacts; AST/import, secret scan,
  unchanged .env and `git diff --check` PASS. No provider process credential.
- Created exactly the requested local-only checkpoint:
  **`a841a002de9367fce29b130c3ec6bfd78b752472`** —
  **`Phase 4.1P: add exact-equivalent structural evidence transport`**.
  Working tree was clean immediately afterward. Nothing was pushed.
- Final HEAD remains that checkpoint on `main`. New case-82 work below remains
  uncommitted. Final 90-case completion checkpoint: **NONE**.

### Exact diagnosed case-82 scope

- Namespace `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`;
  run `paired-real`; generation `real-baseline-v1`.
- Resume identity
  `267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.
- Structural manifest
  `3266a4a52aff8e7b803185d4fdf6371b799a83538719e3daa8ffeb3eefb2c8bc`;
  legacy manifest
  `003ecf3a2e30dbb73a8b48ccd0b6a72861a448486b5da5ae5020de2144ea99e3`.
- Organization **538**, bot **674**, document **25**, source version **1**,
  website **21**, crawl **24**, crawl version **1**.
- Atom `9ee4f5efd85afc9e6163c3d1d2710dbf75735a312a52c764fa97ed062ca1954c`.
- Source hash
  `7aac33d3e4a7027653d4b2bc5ccf631486ce9cf1fe1a4931cc4c5cd9f3e0527d`.
- Document version
  `phase-j-native-v1-7aac33d3e4a7027653d4b2bc5ccf631486ce9cf1fe1a4931cc4c5cd9f3e0527d`.
- Revision
  `phase-j-native-ab4982c63d12f90eaa82ac0cbc90ac516a7d2170557cdf51a89f24de3e799ab1`.
- Payload SELECT shape
  `cb70814ac45fe283652c232bdd3f1b6e05cd66d3f13fdb09e2ce1c2b34ad57ee`.
- Recorded scope digest
  `bc7777bb8e1ba970737022e488f49e80575fcdacbadc33009c3cfc51981ebd0a`.

The two historical 31,578 ms payload failures and intervening 1,969 ms
successful probe remain immutable. They were not reset or reclassified.

### Bounded read-only diagnostic matrix

Session **`aed363e7d0dc47afbe3ff4c199c06ff1`**. Existing complete preflight first
revalidated 23 documents, 1,030 structural vectors, 1,092 legacy vectors,
3,242 atoms, both manifests, all 90 query receipts and all 163 saved lanes.
Only the retained disposable database was used. No provider request occurred.

| Test | Success / attempts | Timeouts | Payload p50 (ms) | Payload backend PIDs |
| --- | --- | --- | --- | --- |
| B1 observed metadata then payload, same connection | 1/1 | 0 | 281 | 14161; observer 14162 |
| B2 payload-only fresh connection | 1/1 | 0 | 281 | 14164 |
| B3 A: metadata + payload, same connection | 3/3 | 0 | 281 | 14167, 14169, 14171 |
| B3 B: metadata connection closed, new payload connection | 3/3 | 0 | 281 | 14174, 14178, 14181 |
| B3 C: payload-only fresh connection | 2/3 | **1** | 281 | 14183, **14186**, 14188 |

P50 is across each row's attempts, including the timeout duration; these tiny
samples are diagnostics, not a reliability or performance benchmark. Pattern C
durations were **281 / 30,000 / 265 ms**. Pattern A metadata reads were
266 / 250 / 266 ms; pattern B metadata reads 281 / 266 / 250 ms. Pattern B
metadata PIDs 14173 / 14177 / 14180 differed from their payload PIDs, proving
physical connection replacement. Same-connection pairs retained the same PID
and connection token.

At payload entry, measured connection-age ranges were:
A **4,913.805–5,184.411 ms**, B **4,634.697–5,044.008 ms**,
C **4,660.078–4,999.098 ms**. Transaction-age ranges were:
A **3,915.619–4,136.077 ms**, B **3,595.996–3,876.446 ms**,
C **3,582.783–3,958.337 ms**. These fresh, short transactions do not reproduce
the full connection history of the earlier 130th-evidence-call failures.

Every successful payload was reconstructed with validated metadata and matched
both stored payload hash and the preflight full-row hash. Failed pattern C2
retains the inner **DatabaseTransportTimeout** separately from the subsequent
**PendingRollbackError** during transaction exit; the cleanup error does not
explain or replace the read timeout. No failed read was treated as a match.

### Observer, plan, size evidence and classification

The independent observer sampled the successful B1 sequence. It saw PID 14161
`idle in transaction`, **Client/ClientRead**, no blockers, all recorded locks
granted, and no xid/xmin. The payload read had already succeeded by the recorded
sample. **No server-state observation captured the failing C2 operation.**
Therefore the observer does not establish why that timeout occurred, and it
does not prove a case-75-style client/server divergence here. No raw server
query, payload, parameter, DSN or credential was recorded; no backend was killed.

`EXPLAIN (FORMAT JSON)` of the exact guarded payload SELECT: **Index Scan** on
**`canary_atoms_pkey`**, estimated **1 row**, width **18**, cost **0.53..8.60**.
All 17 document/atom hard-scope columns were in the index condition; additional
metadata equality checks remained in the filter. This is not evidence of a
broad scan. No ANALYZE, index/statistics change or planner-setting change ran.

| Atom | Database JSON bytes | Stored payload bytes | Text UTF-8 bytes | Full-row read ms |
| --- | --- | --- | --- | --- |
| Target `9ee4f5ef…` | 27,705 | 5,415 | 648 | 297 |
| Preceding `9e309362…` | 26,645 | 4,302 | 371 | 265 |
| Preceding `9cb7d7eb…` | 7,613 | 1,979 | 26 | 265 |
| Following `a1059ee7…` | 23,854 | 3,542 | 155 | 266 |
| Following `a1772451…` | 34,720 | 5,389 | 313 | 266 |

Peers are nearest neighbors in immutable atom-ID primary-key order, not document
text order; all use the same source scope. Complete IDs and row hashes are in
the bounded diagnostic artifacts. Target canonical JSON payload is **26,437
bytes**; PostgreSQL JSON text uses a different serialization. Larger peer data
also succeeded, so size/TOAST causation is not established.

**Case-82 payload root cause: ROOT_CAUSE_UNKNOWN.** A new connection was not a
reliable cure in this matrix: a fresh payload-only read also timed out.
Same-connection dependence, server execution/locking, TOAST, and a particular
network/proxy/driver mechanism are unproven. **No new transport repair was
introduced.** The verified `EXACT_SPLIT_ROW_V1` implementation remains unchanged.

The 18 diagnostic artifacts are `payload-diagnostic-aed363e7d0dc47afbe3ff4c199c06ff1-*.json`.
Their hashes, exact scope and five proof scopes are pinned in
`case82-payload-diagnosis-20260919.json`. Diagnosis completed at **13:40:37 UTC**;
elapsed **843,598.1448 ms** includes full preflight and ownership checks, not just
the row reads. No measured benchmark lane ran in that diagnostic session.

### Equivalence gates and separate execution authorization

The fresh **225/225 focused test PASS (58.759 seconds)** includes the existing
whole-row and full-materialization equivalence fixtures: exact atom requests,
accepted IDs/order, unit/byte exclusions, bytes, status, support scoring and
route relationships; wrong/stale scope, corruption and concurrent metadata
changes fail closed. Additions are five diagnostic SQL/equality/read-only tests
and ten authorization/replay/retry/proof-gate tests. Baseline was 210 tests.

Before the measured attempt, another complete unchanged preflight validated
all **3,242** logical atom rows. The target plus four peers passed real split-row
equality **5/5** against those preflight hashes. Target canonical row hash:
`83c71dc2cf1aacb0389f51af79782554936cfcf9c20da7920e07658e21e112b8`;
payload hash:
`994206fd23c094fc602e0e2f172af1914f6715db322568437add7a6ac0671f2a`.
Proof file: `case82-row-proof-75f2cd2054d04ddab43aafc8a41f1f0e.json`.
No fields, evidence, authorization predicates, order, budgets, vectors, query,
history, ranking or GOLD were changed.

The new immutable execution record is
**`CASE82_STRUCTURAL_POST_DIAGNOSIS_20260919-82-STRUCTURAL_CANARY-attempt-1.json`**.
It pins the original snapshot, query vector, hard scope, generation and
manifest. All earlier attempt ledgers remain untouched. The previous immutable
diagnostic-checkpoint reference `a185741...` is retained for admission identity;
the new audited transport checkpoint is `a841a00...`, not a moved old admission.

### New measured outcome: different earlier failure, no qualified retry

Session **`75f2cd2054d04ddab43aafc8a41f1f0e`** reached the original `run_query()`
materialization path. While collecting children for fused routes,
**`CanaryRepository.children()` line 458** failed on its scoped membership
SELECT (`canary_memberships.atom_id`, document scope + exact `entry_id`, ordered
by atom ID, limit 33). The safe underlying failure is **OperationalError /
DATABASE_TRANSPORT_FAILURE**, raised during driver polling.

- Evidence payload calls: **0**. SQL executions observed in the lane: **108**.
- The diagnosed document-25 payload was **not reached** in this measurement.
  This is not a new repeat of its old evidence-130 timeout.
- Failed entry ID/document, query-shape digest, SQLSTATE and exact statement
  elapsed: **not captured**. Do not infer them from the SQL execution count.
- Evidence telemetry only emits exact per-operation scope for evidence reads;
  it had no failed-operation record for this membership SELECT.
- The retry guard returned **`EXACT_FAILED_SCOPE_TELEMETRY_REQUIRED`**. Without
  that exact read identity, the mandated independent successful probe could
  not be performed. **No retry, guessed-scope probe, or guard bypass ran.**
- The original transport exception is retained in
  `measured-summary-75f2cd2054d04ddab43aafc8a41f1f0e-82-STRUCTURAL_CANARY-failed.json`;
  the terminal separately records the retry-refusal guard. Neither is presented
  as a retrieval-quality or content-integrity failure.

Terminal **SAFE_STOP / C**, exit **1**, **2026-09-19 13:57:01 UTC**
(19:27:01 IST), **704,770.5575 ms** including preflight, five-row proof and cleanup.
No overall deadline; transport retries **0**; new saved lanes **0**.
All **163** old lanes were reused. Cases **83–90 were not run**.
The terminal's `next_resumable_lane` is a missing-work pointer, **not fresh
authorization to replay the consumed attempt**.

### Final counts, quality/performance limitations and safety

- **81/90 complete pairs; 163/180 saved lanes; 81/81 pair checksums PASS**.
  All 163 starting lane hashes, including the original 149, are unchanged.
- Full 90-case metrics, complete difference inventories, materialization
  root-cause analysis, final quality A/B verdict and full canonical suite are
  **WITHHELD / NOT RUN**, as required until 90/90. Existing partial quality
  findings and `INCOMPLETE_BUDGET` results are preserved, not repaired.
- Latency boundaries remain **PRE_SPLIT_TRANSPORT: L1–75, S1–74** and
  **CURRENT_SPLIT_TRANSPORT: L76–82, S75–81**. No third transport variant or new
  successful latency observation was added. Diagnostic/failed-attempt costs
  are not merged into successful-lane p50/p95. Final performance tables await
  completion; none of these times are production chatbot latency.
- Retained five real-vector isolation scenarios revalidated: foreign org,
  foreign bot, stale generation, stale source and identical foreign text all
  retain **0 unauthorized dense / FTS / routing / materialization** results.
  All 163 saved lanes passed reuse validation; no new result exists. No claim
  of inspecting 180 final lanes is made.
- **740/740 protected hashes unchanged**, all five changed/new Python ASTs and
  harness imports PASS, implementation hashes unchanged during execution,
  **11,692 bounded JSON artifacts PASS**, secret scan PASS, .env unchanged,
  `git diff --check` PASS, no pending artifact writes.
- Unrelated catalog: 126 objects, hash
  `5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`,
  unchanged at every completed identity gate. Last gate was before measurement;
  no extra DB inspection or final 90-case sealed validation followed the stop.
- Both processes exited; local connections/engines were closed/disposed and
  process-only CANARY variables cleared. Diagnostic terminal cleanup errors
  were empty (C2's transaction-exit error remains in its diagnostic record).
  Measured terminal records one `UNLOCK_SKIPPED_INVALID_CONNECTION`; no unlock
  SQL was issued on that invalid connection. Server lock release was not
  independently re-observed. Retained schema/corpus/results were not deleted.
- Lease unchanged: **2026-09-20 09:04:18 UTC / 14:34:18 IST**; no new renewal.
- Provider calls **0**. No customer/application DB use, serving-RAG change,
  ranking/configuration/budget change, ingestion, re-embedding, generation,
  chatbot/API/widget launch, production action, push or deployment.

### Uncommitted files and next boundary

- `backend/scripts/canary_payload_diagnostic.py`
- `backend/scripts/canary_case82_completion.py`
- `backend/test_canary_payload_diagnostic.py`
- `backend/test_canary_case82_completion.py`
- `backend/scripts/test_scoped_rag_regressions.py` — test registration only
- `docs/PHASE_4_1P_REAL_EMBEDDING_RETRIEVAL_CANARY_REPORT.md`

**Next task remains Phase P**, not chat/widget validation: separately authorize
evaluation-only exact membership/children-read telemetry and diagnosis, then
establish the required fresh exact-scope proof before any further measurement.
The current attempt must not be silently reset. No final completion commit was
created; HEAD is `a841a002de9367fce29b130c3ec6bfd78b752472`. Stop here.

---

Earlier sections below are preserved historical records, superseded by the
current result above where checkpoint or execution status differs.

## PHASE 4.1P FINAL RETRIEVAL COMPLETION

**C — PHASE 4.1P — BLOCKED: 81/90 pairs and 163/180 lanes saved.**

Updated **2026-09-19**. The original case-75 atom now succeeds with an
exact-equivalent evaluation-only transport. Continuation completed cases 75–81
and case 82 LEGACY_CONTROL. Case 82 STRUCTURAL_CANARY then exhausted its initial
attempt and single permitted retry on the **same document-25 atom**. This is the
explicit repeated-scope stop condition, not a wall-clock deadline. No third
attempt, second repair, case 83–90 execution, or new provider call followed it.

### Checkpoint and preservation

- Starting HEAD: `a185741b847fbc151b16e37a068285762019e428`, branch `main`.
- Required initial audit: **184/184 focused tests PASS** (63.701 seconds),
  740/740 protected hashes unchanged, all 149 saved lanes preserved, 74/74 pair
  checksums valid, bounded artifacts, AST/import, secret scan, unchanged .env,
  and `git diff --check` PASS.
- Created the authorized **local-only** checkpoint:
  **`de6728e30291eca3de2cedb9ffda464168508bd9`** —
  `Phase 4.1P: harden measured retrieval telemetry and resume safety`.
  It contains only the eight previously audited harness/test/report files.
- Final HEAD remains `de6728e30291eca3de2cedb9ffda464168508bd9` on `main`.
  The new exact-atom diagnostic, split transport, authorization wrapper, tests
  and this report remain **uncommitted**. Final completion checkpoint: **NONE**;
  the 90/90 prerequisite was not met. Nothing pushed or deployed.

### Retained identity and exact original case-75 scope

- Namespace: `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`;
  run `paired-real`; generation `real-baseline-v1`.
- Resume identity:
  `267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.
- Target fingerprint:
  `f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
- Structural manifest:
  `3266a4a52aff8e7b803185d4fdf6371b799a83538719e3daa8ffeb3eefb2c8bc`.
- Legacy manifest:
  `003ecf3a2e30dbb73a8b48ccd0b6a72861a448486b5da5ae5020de2144ea99e3`.
- Organization **538**, bot **674**, document **29**, source version **1**,
  website **25**, crawl **28**, crawl version **1**.
- Atom:
  `03fb47f3e9a640babf37996c1333aa84201ca24a0c4930239df080bbdcb58a0b`.
- Source hash:
  `d28a1ebdc3afba79254bb96438692f4697d10d6491d6bc63a89c6285e2684140`.
- Document version:
  `phase-j-native-v1-d28a1ebdc3afba79254bb96438692f4697d10d6491d6bc63a89c6285e2684140`.
- Revision:
  `phase-j-native-1478bbdcf123c73b4d17857b463d057c3d842556eccc2cedf90191227c6f250a`.
- Original SELECT shape:
  `3ac325d8db12f712da9c489485fb58c1657590b773738e945d75390993e54535`.
- Original scope digest:
  `90c7f202f988a2d3543bb09c32b0197c4ac3620ff3a553e7ec869ea294572162`.

Full unchanged preflight validated 23 documents, 1,030 structural vectors,
1,092 legacy vectors, 3,242 atoms, all 90 query receipts, both sealed manifests,
source/version/crawl/hash identities, frozen configuration and historical lanes.
PostgreSQL **18.6**, pgvector **0.8.6**, vector namespace `public`.

### Exact atom diagnosis: measured facts

Diagnostic session: `b73b6bac10354c889ca0dfea8bd309a2`. Only scoped reads,
safe telemetry and EXPLAIN without ANALYZE; no raw content, SQL parameters,
connection secret, or vector coordinates were written to diagnostics.

| Diagnostic | Result |
| --- | --- |
| A: original full-row SELECT, fresh connection | Client timeout at **30,015 ms**; backend PID 13779, independent observer PID 13780 |
| B: metadata-only SELECT | PASS; exact scope and stored payload hash present |
| C: database-side sizes | Payload JSON text 13,385 bytes; `pg_column_size(payload)` 2,750 bytes; canonical text 186 UTF-8 bytes / 190 stored bytes |
| D: canonical text alone, fresh connection | PASS, **250 ms**, 186 bytes |
| D: payload alone, fresh connection | PASS, **297 ms**, 12,761 canonical JSON bytes; stored hash matches |
| E: two preceding / two following peers | All four full rows PASS, **281 ms** each; canonical payloads 56,306 / 22,710 / 12,395 / 18,142 bytes |
| Exact and peer EXPLAIN FORMAT JSON | `Index Scan`, `canary_atoms_pkey`, estimated 1 row; no broad scan |

Peers are immediate neighbors in immutable **atom-ID primary-key order**, not
document text order. Each retained the same document/source scope. Their IDs
are `02aa7f9a5e1a195e32674f9310ddd0b8f16e8383ea94220867a32ac989040f66`,
`027ad2add91b56f75699edaaa87024440d2e21aa1a7c9a8f144b55d2115aff60`,
`0418ba2daad073a9b5c9a2225f1b17dfb39f12b18f2e2ae23b0b10a5a32233d7`,
and `0492b1d8c46a01f163c7d08e2d8ebb057fa62382967f549dd790f59fe94c2061`.
Canonical versus PostgreSQL JSON text byte counts use different serialization;
they are not competing measurements of the same encoding.

Client operation: **10:18:20.300665–10:18:50.320619 UTC**.
Observed server query start: **10:18:20.851131 UTC**;
state change: **10:18:20.851991 UTC**. The server was already
`idle in transaction`, waiting on **Client/ClientRead**, approximately
**0.860 ms** after query start. This is an activity-timestamp interval, **not an
EXPLAIN ANALYZE execution measurement**. Seven samples through about 14.4 seconds
showed no blockers, all locks granted, and no backend xid/xmin. The backend was
no longer visible at approximately 16 seconds; why it disappeared is UNKNOWN.
The client remained blocked until its watchdog expired. No backend was killed.

**Earliest proven case-75 classification: CLIENT_TRANSPORT_RESPONSE_STALL.**
The underlying network/proxy/libpq/driver mechanism remains **UNKNOWN**. There
is no evidence of server execution or lock waiting during the observed stall,
nor of a general large-payload/TOAST threshold: larger peers returned promptly.
The exact plan estimated cost **0.53..8.59**, width **1123**, one row, with all
17 document/atom hard-scope columns in the index condition. No index, statistics,
planner settings, schema, or source data changed.

The diagnostic outer stage took 43,734 ms including setup/observer handling.
A secondary `PendingRollbackError` during failed-connection cleanup was recorded
separately and did not replace the exact-read timeout. Diagnostic artifacts are
the eleven `atom75-diagnostic-b73b6bac10354c889ca0dfea8bd309a2-*.json` files;
their checksums are pinned in `case75-atom-diagnosis-20260919.json`.

### Evaluation-only transport and equivalence

`canary_split_evidence.split_atom_row()` reads the complete original atom row
in two bounded SELECTs: all non-payload columns first, then the exact payload.
Both apply **every original document/source/manifest/generation/atom predicate**.
The second also compares every metadata field returned by the first, so a
concurrent metadata change fails closed rather than mixing row versions. The
payload hash and reconstructed complete-row canonical hash must match.
Original authorization/read gates and atom membership checks remain in force.
Legacy evidence uses the original method unchanged.

No atom is skipped, substituted, truncated, cached, or replaced by entry text.
Requested order, evidence objects, units, bytes, exclusions, support scoring,
dense/FTS/RRF semantics, query/vector/history, GOLD and budgets are unchanged.
The wrapper adds an ownership check; its overhead is evaluation-only and must
not be mistaken for a retrieval-quality change.

Proof before measured execution:

- Offline complete-row tests cover every fixture atom; wrong/missing/stale scope,
  duplicate primary keys, payload corruption, concurrent changes and full-row
  hash mismatch fail closed.
- Full materialization fixtures prove identical requested atom order, accepted
  units/IDs/order, byte and unit exclusions, bytes, status and support scoring.
- Existing unchanged full-row preflight reads validated and hashed **all 3,242
  old logical atom rows**. The target and four peers then passed real split-read
  equality against those complete rows (**5/5**). The failed target single-row
  diagnostic is not falsely claimed to have returned a comparable row.
- Every later measured split read must equal its corresponding old preflight
  full-row hash. There were no approximate comparisons or missing fields.
- Durable `BEFORE_SQL_PART1` / `BEFORE_SQL_PART2` records precede actual SQL;
  success follows payload/full-row validation only.

Real proof: `post-atom-split-proof-8164d58de27f47518d9950b0c1c6ab25.json` and
its five per-row proof files. Individual proof-stage totals include connection,
ownership and identity checks, not just SELECT latency.

### New authorization and measured continuation

New immutable authorization:
**`CASE75_STRUCTURAL_POST_ATOM_DIAGNOSIS_20260919`**.
Historical exhausted attempt/retry ledgers and all saved lanes were retained.
The new admission and attempt files are separate and cannot reset old attempts.

A pre-measured launch (`0759ad98d6234e1fbf325c450bd7474d`) stopped at
`EVALUATION_ARTIFACT_CONFLICT`: it supplied the new checkpoint as the diagnostic
checkpoint, while the existing immutable admission required its original
`a185741...` reference. No measured attempt was consumed and no lane was run.
Git comparison confirmed the referenced diagnostic wrapper bytes were identical;
the launch reference was corrected to the original checkpoint, without editing
code, deleting admission, or weakening a guard. That setup took 543,174.119 ms.

Measured session: **`8164d58de27f47518d9950b0c1c6ab25`**.

| Cases | Saved outcome |
| --- | --- |
| 1–74, both lanes; 75 legacy | All **149** original lane bytes unchanged; never rerun |
| 75 structural | PASS/save; original failing atom at evidence call 22 passed in **1,875 ms**, hash PASS |
| 76–79 | Both lanes PASS/save |
| 80 legacy | PASS/save |
| 80 structural | First attempt timed out on a different document-27 atom at payload part 2 (**31,610 ms**); exact fresh probe PASS (**1,875 ms**); one authorized retry PASS/save, same atom **3,000 ms** |
| 81 | Both lanes PASS/save |
| 82 legacy | PASS/save |
| 82 structural | Initial attempt and sole authorized retry failed at the identical document-25 payload read; **not saved/scored** |
| 83–90 | Not run, pursuant to repeated-failure stop rule |

**14 new lanes**, **81/90 complete pairs**, **163/180 total saved lanes**.
Pair files 1–81 validate; no incomplete lane was represented as a successful
result. `evaluation-incremental.json` remains **PARTIAL / PENDING_FULL_BASELINE**.

### Exact current blocker: case 82 STRUCTURAL_CANARY

- Organization **538**, bot **674**, document **25**, source version **1**,
  website **21**, crawl **24**, crawl version **1**; same run/generation/manifests.
- Atom:
  **`9ee4f5efd85afc9e6163c3d1d2710dbf75735a312a52c764fa97ed062ca1954c`**.
- Source hash:
  `7aac33d3e4a7027653d4b2bc5ccf631486ce9cf1fe1a4931cc4c5cd9f3e0527d`.
- Document version:
  `phase-j-native-v1-7aac33d3e4a7027653d4b2bc5ccf631486ce9cf1fe1a4931cc4c5cd9f3e0527d`.
- Revision:
  `phase-j-native-ab4982c63d12f90eaa82ac0cbc90ac516a7d2170557cdf51a89f24de3e799ab1`.
- Payload SELECT shape:
  `cb70814ac45fe283652c232bdd3f1b6e05cd66d3f13fdb09e2ce1c2b34ad57ee`.
- Scope digest:
  `bc7777bb8e1ba970737022e488f49e80575fcdacbadc33009c3cfc51981ebd0a`.
- Failure function: `canary_split_evidence.split_atom_row`, second SELECT
  (`conn.execute(payload_stmt).scalar_one()`, line 33).

| Execution | Evidence ordinal | Global telemetry operation | Result |
| --- | --- | --- | --- |
| Initial measured attempt | 130 | 1922 | **31,578 ms**, DATABASE_TIMEOUT, hash NOT_COMPLETED, connection INVALID_OR_CLOSED |
| Independent exact fresh-scope probe | Not scored | 1923 | **1,969 ms**, SUCCESS, one row, hash PASS; identity revalidated |
| Sole permitted fresh-connection retry | 130 | 2053 | **31,578 ms**, DATABASE_TIMEOUT, hash NOT_COMPLETED, connection INVALID_OR_CLOSED |

Both measured attempts have durable BEFORE_SQL_PART2 and AFTER_CALL records,
the same shape and scope digest, and different connection tokens. No SQLSTATE or
server execution error was returned. The independent probe success authorized
exactly one retry; it did not prove the lane would succeed. No observer was run
for this new atom, so its underlying server/transport cause is **UNKNOWN**;
the case-75 observer conclusion is not silently transferred to case 82.

Terminal: **SAFE_STOP / decision C**, **2026-09-19 12:19:05 UTC**
(17:49:05 IST), exit **1**. Session elapsed **6,030,686.2321 ms** includes
preflight, real equivalence checks, successful lanes, failed attempts, probes
and cleanup. **No overall deadline** was configured. Two permitted transport
retries were used in total (case 80 recovered; case 82 did not).

The terminal artifact is
`evaluation-session-8164d58de27f47518d9950b0c1c6ab25.json`.
Its `next_resumable_lane` identifies the missing lane, **not new retry authority**:
case 82's current attempt authorization is exhausted. Another measured attempt
requires a separate diagnosis and explicit authorization; it was not run here.

### Metrics, performance and quality analysis status

The full 90-case metrics, complete improvement/regression inventories,
materialization root-cause analysis and final A/B quality decision are
**WITHHELD**, because the user expressly gates them on 90/90. Existing partial
74-case observations below are preserved unchanged. Incremental 81-pair scores
are durable but are not presented as final benchmark results. No known quality
finding was repaired or hidden. False-absence/wrong-source answer claims remain
UNSCORED: no answers were generated.

Do not combine changed transport latency into a single homogeneous comparison.
Current saved timing cohorts are **pre-repair L1–75 (75), S1–74 (74)** and
**post-repair L76–82 (7), S75–81 (7)**. Legacy SQL itself did not change, but its
wrapper cohort is disclosed. Successful-lane timings exclude failed-attempt
and fresh-probe costs; session elapsed includes those costs. Final cohort
p50/p95 tables await completion. These are disposable remote-canary observations,
not production latency. Quality comparability is supported by exact row and
materialization equivalence, not assumed from timing.

### Security, tests, cleanup and final audit

- **210/210 focused tests PASS**, 63.683 seconds: prior 184 plus 5 diagnostic,
  8 new-authorization/retry, and 13 split-transport tests. Command:
  `python -B -m unittest test_canary_exact_atom_diagnostic test_canary_post_atom_completion test_canary_split_evidence test_canary_final_evaluation test_canary_session_diagnostics test_canary_evaluation_resilience test_canary_evaluation_resume test_canary_alternate_credential test_canary_durable_recovery test_canary_provider_recovery test_canary_real_handoff`.
- Full canonical suite: **NOT RUN**; only authorized after 90/90. Historical
  full-suite totals are not represented as a fresh pass.
- AST: all seven changed/new Python files PASS; changed harness imports PASS.
  Python source hashes unchanged throughout the measured run.
- Final preservation: **740/740 protected hashes unchanged**, **149/149 original
  lane hashes unchanged**, **81/81 pair checksums PASS**, 163 valid saved lanes;
  no pending artifact writes. .env unchanged.
- Revalidated retained real-vector isolation evidence: foreign organization,
  foreign bot, stale generation, stale source and identical foreign text all
  retain **0 unauthorized dense / FTS / routing / materialization** results,
  despite stronger foreign distance 0.0. These were existing attack results
  revalidated, not newly executed provider-backed attacks.
- Saved lanes received full manifest/query/scope/member/score validation during
  reuse or save. Final local scan of all 163 traces also found zero scope or
  generation violations across **7,752 dense**, **567 FTS**, **7,752 RRF** and
  **5,135 materialized** trace items; manifest/full-hybrid/source validation PASS.
- Unrelated catalog: 126 objects, hash
  `5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`,
  unchanged at every successful identity gate, including before case-82 retry.
  No new DB inspection followed the mandatory final stop. Final 90-case full
  sealed revalidation was not reached; do not imply otherwise.
- **11,662 bounded JSON artifacts PASS**, secret scan PASS, `git diff --check`
  PASS. No URL, API key or connection secret persisted in new files/artifacts.
- Cleanup closed/disposed the local DB/lock/telemetry resources and cleared
  process-only CANARY variables. The process exited. Three
  `UNLOCK_SKIPPED_INVALID_CONNECTION` records (one per measured timeout) are
  retained separately; the harness did not issue SQL on invalid connections.
  Server-side lock release was not independently re-observed after final stop.
  No schema, marker, fixture, vector, saved result or retained corpus was deleted.
- Lease remains **2026-09-20 09:04:18 UTC / 14:34:18 IST**. The one earlier
  renewal remains the only renewal; none occurred during this task.
- Provider calls **0**. No application/customer DB access, production action,
  serving-RAG change, tuning, query/vector/GOLD change, ingestion, re-embedding,
  chatbot/API/widget launch, generation, push or deployment.

### Files changed after the local checkpoint

- `backend/scripts/canary_exact_atom_diagnostic.py`
- `backend/scripts/canary_post_atom_completion.py`
- `backend/scripts/canary_split_evidence.py`
- `backend/test_canary_exact_atom_diagnostic.py`
- `backend/test_canary_post_atom_completion.py`
- `backend/test_canary_split_evidence.py`
- `backend/scripts/test_scoped_rag_regressions.py` — registration only
- `docs/PHASE_4_1P_REAL_EMBEDDING_RETRIEVAL_CANARY_REPORT.md`

**Exact next task:** separately authorized read-only diagnosis of the repeated
case-82 document-25 payload read, preserving 163 lane artifacts and the exhausted
retry ledger. No Phase P quality tuning, end-to-end chat/widget validation or
later phase is authorized by this incomplete run. Stop here.

---

The following sections are historical records. Their earlier HEAD/progress/
uncommitted-state statements are superseded by the current section above.

## FINAL 90-CASE RETRIEVAL COMPLETION

**C — PHASE 4.1P — BLOCKED at 74/90 pairs, not complete.**

Report updated **2026-09-19**. This replaces the timed-pause status below.
The stop was a **repeated, scoped database-response timeout**, not elapsed
benchmark time. No overall deadline was imposed. Case 75 STRUCTURAL_CANARY
exhausted its initial attempt plus the one permitted fresh-connection transport
retry; no third attempt or additional database probe was made.

### Checkpoints, preservation and authorized scope

- Starting committed checkpoint: `e1e533461ca72f5d44fd63e576da74301bc48c42`.
- Audited diagnostic checkpoint: **`a185741b847fbc151b16e37a068285762019e428`**,
  `Phase 4.1P: add case72 structural transport diagnostics`. Local only.
  Before this checkpoint: 158/158 focused tests, 740 protected hashes,
  143 historical lane files, 71 pair checksums, bounded artifacts, AST/import,
  secret scan, unchanged .env and diff checks passed.
- HEAD remains the diagnostic checkpoint on `main`. New completion wrappers,
  tests and this report remain **uncommitted**. Final Phase P checkpoint: **NONE**.
- Retained namespace: `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`;
  run: `paired-real`; generation: `real-baseline-v1`.
- Resume identity:
  `267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.
- Target fingerprint:
  `f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
- Structural manifest:
  `3266a4a52aff8e7b803185d4fdf6371b799a83538719e3daa8ffeb3eefb2c8bc`.
- Legacy manifest:
  `003ecf3a2e30dbb73a8b48ccd0b6a72861a448486b5da5ae5020de2144ea99e3`.
- Full retained-data preflight passed before each session: 23 documents,
  1,030 structural vectors, 1,092 legacy vectors, 3,242 atoms, all 90 saved
  query receipts; exact source/version/hash/crawl/epoch, seals, manifest,
  scope, configuration, query-set and artifact identities.

### Lease and restart history

Exactly one authorized 24-hour renewal was applied after full validation:
**2026-09-19 09:04:18 UTC → 2026-09-20 09:04:18 UTC**
(**20 September, 14:34:18 IST** new expiry).
Reason: `ACTIVE_90_CASE_EVALUATION`.
Authorization: `CASE72_STRUCTURAL_FINAL_MEASURED_RETRY_20260919`.
The immutable write-ahead audit records old/new expiry, namespace/run,
resume identity, both manifests, source-validation digest, authorization and
timestamp. Source-validation digest:
`80fb56d787bfbd577804a8dfcc54388a807a083f968f67f4407ed86209cbd6bb`.
No second renewal, new generation or TTL bypass occurred.

Session `bdf8bf2260f848149812fa1a00096860` completed case 72 structural
and case 73 legacy. The user then requested a PC-restart pause. Only the exact
evaluation Python process was terminated; its incomplete case-73 structural
attempt was not scored. The session is durably `PAUSED_BY_USER`, not RUNNING.

The subsequent user request to continue was recorded by a bounded resume
wrapper. It validates the paused session, unchanged original attempt, exact
query/vector/manifest/scope, unsaved lane and absence of an old transport-retry
ledger. It writes a separate immutable user-resume record without deleting or
resetting any attempt. Saved lanes cannot be replayed. Only the interrupted
case-73 structural lane received this user-resume authorization.

Resumed session: `0dc03fa37dc44252ac7754206796d7bd`.
It reused all 145 pre-resume lanes and completed four additional lanes.
Terminal: **SAFE_STOP**, **2026-09-19 09:50:17 UTC**.
Elapsed resumed execution: **2,030,841.245700 ms** (includes full preflight,
successful lanes, failed attempts and cleanup). No session deadline.

### Observation-only telemetry and wrapper repairs

Every valid evaluation evidence call durably writes a bounded BEFORE_CALL
record before its authorization/SQL path, and a BEFORE_SQL record at the exact
SQLAlchemy cursor boundary before DBAPI execution. Records contain case/lane,
manifest/generation, complete declared source/atom scope, scope digest,
query-shape hash, operation and attempt ordinals, evaluation session, opaque
connection token and monotonic start. AFTER_CALL records distinguish SUCCESS,
DATABASE_TIMEOUT, TRANSPORT_FAILURE and VALIDATION_FAILURE, with elapsed time,
row count, payload-hash status and connection state. Raw evidence, vectors,
credentials, DSNs and authorization material are not recorded.

Structural success is recorded only after the original payload-hash validation.
The original legacy method has no per-call hash check, so legacy telemetry
truthfully says NOT_PERFORMED_BY_LEGACY_METHOD; its retained corpus was validated
by the complete preflight. Telemetry does not add or change retrieval SQL.

Evaluation-only channel boundaries preserve genuine dense/FTS transport
failures through the frozen run_query exception handler. Per-unit cleanup-only
stops remain separate from primary failures. Invalidated connections receive
no blind advisory-unlock SQL. No application retrieval implementation,
configuration, budgets, ranking, materialization policy, source content,
query text/history, vectors or GOLD changed.

### Case 72 and completion progress

The new case-72 authorization was consumed once. **Case 72 structural succeeded
on its first new attempt**: 178 evidence reads, 17 accepted units, 130,181 bytes,
161 budget exclusions, INCOMPLETE_BUDGET, 1,151 measured SQL executions.
No case-72 transport retry or fresh failure probe was needed. The unknown
historical failed atom remains UNKNOWN; it was not invented.

- Cases 1–74: both lanes saved, **74/74 valid pair checksums**.
- Case 75: LEGACY_CONTROL saved; STRUCTURAL_CANARY failed twice and is unsaved.
- Cases 76–90: not run.
- Total: **149/180 immutable lane artifacts; 74/90 complete pairs**.
- Initial 143 historical lanes preserved; all 145 lanes present at user-resume
  are byte-identical after this run.
- Six new lanes across the two final-continuation sessions: 72 structural,
  73 legacy/structural, 74 legacy/structural, 75 legacy.
- Cases 72/73 have a mapping gap and no scoreable supporting span (0/0),
  not a retrieval-recall failure. Case 74's mapped support was found by both lanes.

### Exact repeated failure — case 75 structural

Both failures are the **22nd evidence call in the lane attempt**, under the same
manifest, generation and complete scope, on different fresh connections:

| Attempt | Operation ordinal | Evidence-call elapsed | Connection token |
| --- | ---: | ---: | --- |
| Initial | 569 | 31,250.000000 ms | `f2d02b9db17a4f1f97ede9c5febbd08f` |
| One permitted retry | 591 | 31,594.000000 ms | `5c35204c1fab4cea88ea82e3407eedd0` |

The measured call time includes the unchanged authorization work; the client
SQL-response watchdog remains 30 s (connect 8 s, statement 15 s, lock 3 s).

Safe exact scope: organization **538**, bot **674**, document **29**,
source version **1**, website **25**, crawl **28**, crawl version **1**.

- Atom: `03fb47f3e9a640babf37996c1333aa84201ca24a0c4930239df080bbdcb58a0b`.
- Source hash:
  `d28a1ebdc3afba79254bb96438692f4697d10d6491d6bc63a89c6285e2684140`.
- Document version:
  `phase-j-native-v1-d28a1ebdc3afba79254bb96438692f4697d10d6491d6bc63a89c6285e2684140`.
- Revision:
  `phase-j-native-1478bbdcf123c73b4d17857b463d057c3d842556eccc2cedf90191227c6f250a`.
- Query-shape SHA-256:
  `3ac325d8db12f712da9c489485fb58c1657590b773738e945d75390993e54535`.
- Scope digest:
  `90c7f202f988a2d3543bb09c32b0197c4ac3620ff3a553e7ec869ea294572162`.

Both BEFORE_SQL records are durable; statement_started=true. Both AFTER_CALL
records report DATABASE_TIMEOUT, row_count=null, payload_hash_validation=
NOT_COMPLETED and INVALID_OR_CLOSED. Exact artifacts are
`measured-0dc03fa37dc44252ac7754206796d7bd-00569-{BEFORE_SQL,AFTER_CALL}.json`
and the equivalent `00591` records in the retained namespace folder.

First proven failure path:
`EvaluationRunner.evaluate_lane → run_query → materialize →
EvaluationRepository.evidence → CanaryRepository.evidence:469 →
scoped single-atom SELECT → wait_bounded → DatabaseTransportTimeout`.

This proves repeated failure at the same scoped response boundary, **not** the
underlying PostgreSQL/network cause. That cause remains **UNKNOWN**. No third
lane execution, exact-atom probe or repair was attempted after the exhausted
retry. The case-75 retry ledger and both attempt records remain immutable.

### Partial paired metrics — cases 1–74 only

These are not final 90-case results. Case-75 legacy is excluded from paired
aggregates. There are 91 scoreable mapped spans and 38 mapping gaps across
129 span labels; mapping gaps are excluded from recall denominators.
Field assignments for the 90-case set remain unreviewed, and no answers were
generated or judged.

| Metric | Legacy | Structural |
| --- | ---: | ---: |
| Dense span recall @5 | 17/91 (18.681319%) | 65/91 (71.428571%) |
| Dense span recall @10 | 27/91 (29.670330%) | 69/91 (75.824176%) |
| Dense span recall @48 | 66/91 (72.527473%) | 80/91 (87.912088%) |
| FTS span recall @5 | 8/91 (8.791209%) | 6/91 (6.593407%) |
| FTS span recall @10 | 10/91 (10.989011%) | 6/91 (6.593407%) |
| FTS span recall @48 | 18/91 (19.780220%) | 12/91 (13.186813%) |
| RRF span recall @10 | 33/91 (36.263736%) | 70/91 (76.923077%) |
| RRF span recall @48 | 68/91 (74.725275%) | 85/91 (93.406593%) |
| Materialized span recall | 68/91 (74.725275%) | 66/91 (72.527473%) |
| Required-document recall | 87/91 (95.604396%) | 69/91 (75.824176%) |
| Duplicate evidence | 0/3518 (0.000000%) | 0/1125 (0.000000%) |
| Source-noise proxy | 756/3182 (23.758642%) | 136/1023 (13.294233%) |

Candidate diversity totals: **402/74 cases** legacy versus **325/74** structural
(a descriptive count/mean, not accuracy). ATOM_ONLY: **0 / 0**.
Lexical-collapse cases: **0 / 7** (structural 1, 3, 4, 35, 38, 52, 60).
INCOMPLETE_BUDGET: **0/74 legacy; 74/74 structural**.
Query-understanding failures: **2 each**, cases 53/54.
GOLD_MAPPING_GAP: **38 labels each**; no gap was scored as failed recall.

The six measured materialization regressions remain **4, 30, 35, 52, 60, 61**.
Known RRF→materialization losses remain **4, 30, 35, 51, 52, 55, 58, 60, 61,
62, 63, 64, 65, 66**. Known required-document regressions remain **30, 51, 52,
55, 58, 60, 61, 62, 63, 64, 65, 66**.
Known materialization improvements remain **51, 55, 66, 69, 70**.
Cases 72/73 add no scoreable span comparison; case 74 is equal on all scored
recall fields. Strong dense/RRF results do not erase the final-evidence losses.

The requested **full 90-case** improvement/regression inventory and per-regression
materialization root-cause analysis are **deferred**, as instructed, until the
frozen baseline completes. No quality tuning was performed.

### Partial performance and SQL counts

Milliseconds, paired cases 1–74, **p50 / p95**:

| Stage | Legacy | Structural |
| --- | ---: | ---: |
| Dense | 2446.307400 / 2935.182000 | 2314.372700 / 2873.086700 |
| FTS | 1571.205200 / 1799.339700 | 1649.737900 / 2346.708000 |
| RRF | 0.244800 / 0.451500 | 0.247600 / 0.390300 |
| Materialization | 130926.306200 / 172054.317100 | 319642.962300 / 499906.843800 |
| Total retrieval | 138630.482300 / 180774.946700 | 327459.547300 / 506948.408700 |

Materialization remains the measured dominant stage. These are **remote
disposable-canary measurements**, not production chat latency.

Successful newly measured cursor-SQL/evidence counts (from attempt admission through
retrieval completion; excluding preflight, preceding ownership and final cleanup):

| Lane | SQL executions | Evidence calls | Accepted units / bytes |
| --- | ---: | ---: | ---: |
| 72 structural | 1,151 | 178 | 17 / 130,181 |
| 73 legacy | 453 | 48 | 48 / 41,842 |
| 73 structural | 1,096 | 167 | 17 / 130,183 |
| 74 legacy | 453 | 48 | 48 / 61,161 |
| 74 structural | 1,681 | 284 | 15 / 130,944 |
| 75 legacy, unpaired | 453 | 48 | 48 / 39,098 |

The initial failed case-75 structural attempt recorded **367 SQL executions /
22 evidence calls**. Its retry has 22 durable evidence-call records but no
completed per-lane SQL-count summary; no total is fabricated. The interrupted
pre-restart case-73 attempt is not included in successful-lane timings or recall.

### Security, validation and cleanup

- Existing real-vector security evidence revalidated: foreign organization,
  foreign bot, stale generation, stale source and identical text in another
  scope each retain **zero unauthorized dense, FTS, routing and materialized
  results**. Saved lanes pass scope/identity validation; foreign/stale count=0.
- Unrelated catalog: **126 objects**, hash
  `5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`,
  matched by the retained ownership gates, including before the final retry.
- Before first new case-72 attempt: **180/180 focused tests PASS**, 47.335 s.
- Before user-resume: **184/184 focused tests PASS**, 55.111 s (four added
  pause/resume safety tests). Includes actual run_query transport boundaries,
  telemetry ON/OFF equality of SQL/binds/order/rankings/materialization/budgets,
  durable before-read identity, cleanup-only versus primary+cleanup, provider
  denial, terminal persistence, saved-lane refusal and immutable retry guards.
- **Full canonical suite: NOT RUN**, because the explicit 90/90 prerequisite
  has not been met. No stale full-suite result is claimed as a fresh pass.
- Final local preservation: **740/740 protected hashes**, **149 lane files**,
  **74/74 pair checksums**, **145/145 pre-resume lane hashes unchanged**.
- **3,708 bounded JSON artifacts PASS**, **7 Python AST checks PASS**,
  **5 harness imports PASS**, no pending artifact, no secret hits in 3,716
  changed/artifact files; .env unchanged; no provider credential in the checking
  process. Code hashes stayed unchanged throughout the live resumed run.
- `git diff --check` PASS. The seven wrapper/test files and this report are the
  only changes after the diagnostic checkpoint; no serving-RAG file changed.
- Provider calls during both final-continuation sessions: **0**.
- The primary error is DATABASE_TRANSPORT_FAILURE. Two separate cleanup
  diagnostics report UNLOCK_SKIPPED_INVALID_CONNECTION. No blind unlock SQL
  was attempted on either invalid connection; the primary was not replaced.
- Connections were closed and engine disposed through the terminal path.
  Process-only CANARY variables were cleared. No evaluation Python process
  remains. Server-side lock release was not independently probed after stop.
- Owned data/markers/manifests/vectors/query receipts remain intentionally
  retained under the renewed lease; nothing was dropped or rebuilt.
- No production access, provider call, embedding, generation, API/widget test,
  crawl, ingestion, deployment, push or new final commit.

### Decision and exact next step

**C. PHASE 4.1P — BLOCKED.**

The exhausted case-75 structural transport retry is the concrete blocker.
This is not a timeout imposed on overall evaluation, a quality-based early
exit, or a claim that the database failure is permanently unrecoverable.

Next separately authorized engineering task: diagnose the exact document-29
atom read and its transport/server response under the recorded safe scope.
Do not reset the exhausted case-75 ledger or rerun any of the 149 saved lanes.
Only after resolving that blocker and explicitly authorizing any new unsaved
attempt can the frozen baseline continue to 90/90. Materialization-quality
revision and performance optimization remain later, separate work.

---


## 25-MINUTE CONTINUATION SESSION — 2026-09-19

**SESSION_USAGE_WINDOW_ENDED — safe timed pause, not a new Phase 4.1P failure.**

Session started **2026-09-19 07:47:27.149 UTC** / **13:17:27.149 IST**.
The clock was captured immediately after reading the task and carried into the
Python process using a monotonic-clock offset measurement. No timer reset was
made at process launch. The execution guard stops starting work at 23 minutes;
24 minutes remains the hard no-new-database-work boundary. The existing connect
8 s, statement 15 s, lock 3 s and client-operation 30 s limits were unchanged.

### Starting state and authorized scope

- Branch/HEAD: `main / e1e533461ca72f5d44fd63e576da74301bc48c42`.
- **71/90 complete pairs; 143/180 saved lanes**.
- Cases 1–71 and case 72 LEGACY_CONTROL immutable/reused, not rerun.
- First unsaved lane: **72 STRUCTURAL_CANARY**.
- Historical retry ledger unchanged; the separate authorization
  `CASE72_TRANSPORT_DIAGNOSTIC_RETRY_AUTH_20260919` is required before any new
  measured case-72 attempt and can be consumed only once.

### Narrow telemetry and diagnosis

Inspection confirmed that the two historical failures did not persist the
atom/document bind or loop ordinal. The legacy trace cannot identify a
structural atom; no historical identity was invented.

Added evaluation-only SQLAlchemy hooks that record the exact single-atom SELECT
scope before cursor execution: case/lane, declared source/manifest/generation,
atom hash, query-shape hash, operation ordinal, connection age, elapsed time and
safe outcome category. Hooks do not change SQL, binds, rows or retrieval results.
Raw evidence, vector coordinates, credentials and DSNs are excluded.
A failed ownership/read gate cannot be mislabeled as a failed atom SELECT;
matching fresh operation telemetry is required.

The diagnostic reconstructs the existing dense/FTS/RRF, witness and child-request
order using the frozen query vector and scope, then probes requested evidence
through the unchanged `repository.evidence()` checks on fresh read-only
connections. It is not saved/scored as a baseline lane. The original ordering,
deduplication, byte limit and evidence-unit limit remain unchanged. A diagnostic
transport failure, if captured at an exact atom, is eligible for one fresh
read-only check of that exact scope. Only a successful check can authorize the
new measured execution; success without identifying a failure does not recover
the unknown historical bind.

The complete retained-data preflight passed again: all 23 documents in both
lanes, exact vectors/receipts/snapshots/seals and frozen corpus/query identity.
All **143 saved lanes** were validated/reused. Only the retained disposable canary was accessed; no application or production
database was used. The existing one-row FTS query alias emitted
its prior SQLAlchemy cartesian-product warning; it was not changed or treated
as a new correctness result.

### Session result and exact resume point

Session ID: `cc9ce0314fde477f9389cfbe5e34f399`.
Database work stopped at **08:10:28 UTC**, **23m 01.094s** from the original
session clock. The process closed normally through its terminal path; local
verification/reporting followed within the 25-minute limit.

- Frozen candidate reconstruction produced **234 pre-deduplication requests**.
- **31 fresh atom reads succeeded**, with existing evidence/payload validation.
  Seventeen units / 130,181 bytes passed the unchanged materialization budgets
  in this diagnostic; these are **not newly scored retrieval measurements**.
- No database/transport error was reproduced. The next probe was stopped in
  its read gate **before** executing its atom SELECT by the session clock.
- Historical failing atom: still **UNKNOWN**. Successful reads do not identify
  the unknown bind from the two earlier failures.
- New case-72 execution authorization: **NOT USED / not consumed**.
- New measured lanes: **0**. New completed pairs: **0**.
- Ending totals: **71/90 pairs; 143/180 lanes**. Earlier metrics unchanged.
- Provider calls: **0**. Transport failures/retries this session: **0 / 0**.
- Primary stop reason: `SESSION_USAGE_WINDOW_ENDED`, not a DB failure.
  Cleanup errors: **none**; connection state: **RELEASED**.
- Exact next unsaved measurement: **CASE 72 / STRUCTURAL_CANARY**.
  Cases 1–71 and 72 legacy must continue to be reused.
- Next diagnostic starts from the saved frozen request progress; the first
  31 successful read probes and their scope telemetry are diagnostic evidence,
  not lane artifacts. No claim is made that the historical failed atom is among
  those probes.

The durable authoritative bounded-session record is
`case72-bounded-session-cc9ce0314fde477f9389cfbe5e34f399.json`, with
status `SESSION_USAGE_WINDOW_ENDED` and phase_decision `DEFERRED`.
The reused parent runner also wrote its generic SAFE_STOP/decision-C record
and returned exit 1 for the clock guard; this is a legacy stop encoding,
**not a new Phase 4.1P failure or retrieval regression**. Both records are
preserved, and no session remains RUNNING.

Retained DB identity remains resumable as of the successful full preflight
and subsequent fresh ownership/source gates. Existing lease expiry remains
**2026-09-19 09:04:18 UTC / 14:34:18 IST**; no renewal was performed. The
unrelated catalog matched its prior 126-object identity. No new diagnostic or
retrieval operation began after shutdown preparation; healthy lock release was
cleanup only. A future session must recheck
identity and the unconsumed authorization prerequisites; it must not reset the
historical retry ledger.

An initial local constructor invocation refused missing explicit evaluation
opt-in before opening any database connection. Supplying the task-authorized
process-only opt-in allowed the single diagnostic session above; no safety
guard was bypassed.

### Files, tests and preservation

New evaluation-only files this session:

- `backend/scripts/canary_session_diagnostics.py`
- `backend/scripts/canary_case72_diagnostic.py`
- `backend/test_canary_session_diagnostics.py`

All earlier implementation changes were preserved. No application retrieval,
provider, representation, source data or configuration file changed.

Focused offline tests: **18/18 PASS (0.187 seconds)**, covering exact scope
recognition/redaction, unchanged row results, durable pre-execution telemetry,
failure-write isolation, hook cleanup, monotonic shutdown gates, original
session start, refusal for unknown historical scope, matching-atom error proof,
and rejection of missing/mismatched fresh-read proof before DB access or
authorization consumption. An intermediate test-class placement error was fixed
before database diagnosis started; the final focused module passed.
The full canonical suite was **not run**.

Final local checks: **740/740 protected hashes unchanged**, **143/143 starting
lane files byte-identical**, **71/71 pair checksums PASS**, **1052/1052 bounded JSON
artifacts PASS**, **9 Python AST checks PASS**, **1062 files secret-scan PASS**,
no pending artifacts, and `.env` unchanged. All pre-existing implementation
files retain their starting bytes; only the three listed new files and this
report belong to this session. `git diff --check` passed with existing
line-ending warnings only. No full canonical suite or broad benchmark ran.

No provider/model or embedding calls, no new vectors, no corpus rebuild,
ingestion, recrawl, query rewrite, retrieval tuning, generated answers, chat,
widget, production action, deployment, commit or push. Process-only database
variables were cleared on exit. No local checkpoint was created.

---


## DATABASE-TRANSPORT RESILIENCE + 90-CASE COMPLETION — 2026-09-19

**C — PHASE 4.1P — BLOCKED: case 72 STRUCTURAL_CANARY hit the
30-second database-operation response watchdog twice, including its one
authorized fresh-connection retry. 71/90 pairs are complete; 143/180 lanes
are saved. 90-case completion was NOT achieved.**

This is an actual repeated operation failure, not an overall time limit. No
third attempt, retrieval tuning, new vectors, provider calls or corpus rebuild
was made. The previous sections below are historical records, not the current
progress.

### SQL-224 diagnosis: fresh read succeeds

The old control flow reconstructs operation 224 as the eleventh legacy
document read: **LEGACY_CONTROL / document 20 / 27 expected rows**, generation
`real-baseline-v1`, in the exact retained run. The earlier watchdog recorded
the ordinal and stack, not document bind values; this document identity is
therefore a reconstruction from the unchanged ordered call sequence, not a
captured bind. The first legacy-document read was ordinal 214.

- Query-shape hash:
  `6f5c2eba9ce3ab3f581a2b592bc2aaf0b435c2c870479efa74dda5fb62aab9cd`.
- Exact source/scope digest:
  `c40dce593d3af10437ffde4b21068ccb043232198f377c5b255206b3b779f86b`.
- Original connection/transaction ages at operation 224: not captured.
- Each reproduction used a new connection with unchanged connect **8 s**,
  statement **15 s**, lock **3 s**, plus a client operation watchdog **30 s**.
  No DDL, data mutation, forced index, VACUUM, REINDEX or ANALYZE was used.

| Read-only reproduction | Rows | Measured operation time |
| --- | ---: | ---: |
| A: original scoped full SELECT | 27 | 1,518.672600 ms |
| B: same rows in ordered pages of 25 | 27 | 1,754.994200 ms |
| C: count | 27 | 272.988600 ms |
| D: identifiers | 27 | 258.236600 ms |
| E: first bounded payload/vector page | 25 | 1,394.485400 ms |

A and B produced **identical full canonical row hashes**. A's surrounding
connection/probe elapsed time was 3,905.534700 ms; B's was 4,171.055400 ms.
These are not the old connection's age.

Diagnosis: **PRIOR_CONNECTION_RESPONSE_FAILURE_NOT_REPRODUCED_ON_FRESH_SCOPE**.
There is no evidence establishing corruption, proxy failure, SSL failure,
authentication failure, server restart, SQL statement timeout or network
outage. The later case-72 failure is a different read path, described below.

### Narrow repair and exact-validation proof

Only evaluation transport, validation transport and terminal handling changed.
Serving retrieval, FTS, dense search, RRF, source selection, query/history,
HardKnowledgeScope, GOLD, vector values, representations, evidence budgets and
materialization logic remain unchanged.

- Validation opens a fresh ownership/connection unit per document/lane.
  Structural source DTOs are fetched separately; six related table categories
  use bounded aggregate pages. Legacy rows/work use two bounded categories.
- Each category is primary-key ordered, at most **100 rows per page**; a short
  final page proves exhaustion. Each source/page transfer has a **16 MiB
  accepted serialized-size limit**, checked after the bounded response is
  decoded, not a streaming wire-byte cap. Total accumulated row counts are
  bounded by the declared document inventory plus the permitted page margin.
- Every row remains validated. Scope and duplicate primary keys are explicit
  checks. No sampling, counts-only acceptance or approximate digest replaces
  payload, source-pin, profile/config, input-hash, canonical-f32 vector,
  membership/span, work-receipt, query-receipt or seal validation.
- Full old/new logical-validator fixtures have equal canonical hashes for both
  structural and legacy lanes. One-row pagination yields the same proof.
  Missing/extra/corrupt vectors, wrong input/profile/config/scope/generation,
  missing work, duplicate rows and stale source epochs are rejected.
- Successful remote preflight revalidated **1,030 structural vectors, 1,092
  legacy vectors, 3,242 atoms, 23 documents and all 90 saved query receipts**.
  Both manifests stayed CANARY_READ; source versions/hashes/crawl/revision/
  epochs, sealed-generation identities and frozen inputs passed.
- The complete 46-document/lane proof was saved at **06:45:10 UTC** as
  `evaluation-validation-80fb56d787bfbd577804a8dfcc54388a807a083f968f67f4407ed86209cbd6bb.json`.
  Query-inventory digest:
  `c0fcf71bc700e8c3bff4115e2f96d74d19553015d2993a7abd69db39ed7fece0`.

One intermediate wrapper preflight, session
`e56fb8fde78647d1a1a0c64974f37c6d`, stopped safely after 54,318.020 ms
with VALIDATION_RESPONSE_BYTE_BOUND on structural document 12. Its source DTO
alone was 10,851,073 bytes. Combining it with the other page categories exceeded
the new transfer bound. The correction split the single source DTO into its
own transfer; the 16 MiB limit, complete data and exact checks were retained.
The focused suite then passed again. That intermediate session ran **zero
retrieval lanes**, had no cleanup errors, and durably recorded SAFE_STOP and
RELEASED. No saved case was repeated.

### Ownership, connections, retry and terminal behavior

The same namespace advisory lock is retained. Its connection also performs the
bounded document/lane work, rather than remaining an idle companion for hours.
Each lane rechecks exact ownership/catalog/run/manifests/seals/source snapshots
before retrieval. Saved lane and pair artifacts are persisted before release.

Clear transport timeouts, invalidated DBAPI connections and connection-class
SQLSTATEs qualify for one unsaved-lane retry. A durable per-lane retry ledger
prevents resetting that allowance by restarting the process. Correctness or
identity failures are not transient retries. Existing lane files are validated
and reused, never rerun.

Cleanup records safe errors separately, avoids sending unlock SQL through a
known-invalid connection, and closes local resources. The terminal artifact
records primary error, cleanup errors, current/last/next lane, saved pairs,
retry count, timestamp and provider_calls=0. A secondary terminal-file fallback
exists if the normal session write fails.

The observed repeated case-72 failure exercised the genuine materialization
path: the primary timeout remained authoritative and invalid-connection
cleanup did not mask it. Local close/dispose was attempted, the process exited,
and a durable SAFE_STOP replaced RUNNING. A successful server-side unlock or
post-stop reacquisition was **not** independently demonstrated.

Two remaining wrapper edge cases were identified by code inspection, not by
new live calls, and were not changed after the required stop:

- A transport exception inside the existing dense/FTS channel callbacks can be
  converted by frozen `run_query()` into a generic channel failure before the
  evaluation retry classifier sees it. The mocked retry tests do not prove
  that channel-specific path. This was **not** the observed materialization
  timeout.
- The per-unit `exclusive()` cleanup-only failure is raised as
  DATABASE_CLEANUP_FAILURE and can consequently populate the outer primary
  field; tests cover top-level cleanup-only handling but not that exact
  per-unit classification. The observed primary-plus-cleanup path is preserved.

Thus the measured repair progress is not a claim that every transport/terminal
edge case is fully closed.

### Actual continuation and required stop

Current run session: `ceaa15c904cc4453bd40b73b4de68c4c`.
PostgreSQL **18.6**, pgvector **0.8.6**, namespace public for the extension.
Exact retained namespace:
`canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`; run `paired-real`.
Resume identity:
`267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.

| Work | Result | Retrieval elapsed |
| --- | --- | ---: |
| Cases 1–70, both lanes | 140 immutable results reused | Not rerun |
| Case 71 legacy | Saved, COMPLETE | 135,038.530000 ms |
| Case 71 structural | Saved, INCOMPLETE_BUDGET | 400,096.805500 ms |
| Case 72 legacy | Saved, COMPLETE | 128,606.755600 ms |
| Case 72 structural, first attempt | Transport watchdog; not saved | Failed-attempt total not captured |
| Case 72 structural, one retry | Same failure category/path; not saved | Failed-attempt total not captured |
| Cases 73–90 | Not run | — |

The first timeout was recorded at **07:03:18 UTC**. The retry acquired fresh
ownership, passed its identity gate and reused the same saved query vector,
scope and frozen configuration. Its second timeout produced terminal SAFE_STOP
at **07:09:53 UTC** (12:39:53 IST), exit **1**, session elapsed
**1,983,486.607600 ms**. There was no overall deadline.

Exact captured failure path on both attempts:

`EvaluationRunner.evaluate_lane()` → `run_query()` →
`materialize()` → `CanaryRepository.evidence()`, line 469 →
the exactly scoped structural-atom SELECT → psycopg2 wait callback →
`DatabaseTransportTimeout` at `wait_bounded()`, line 33.

That SELECT reads a single declared atom row under the manifest/document/source
scope before checking its payload hash. The trace does **not** retain the
specific atom/document bind for the failed operation; it cannot establish that
both attempts stalled on the same atom. No server SQLSTATE or server error
was returned. The failure is the **client-observed absence of a database
response within 30 seconds**, not evidence that the SQL statement timeout fired.

Terminal record:

- completed_pairs = **71**; new_lanes = **3**; reused_lanes = **140**.
- last complete pair = **71**; last saved lane = **72 LEGACY_CONTROL**.
- current and next resumable lane = **72 STRUCTURAL_CANARY**.
- transport_retry_count = **1**; its allowance is exhausted.
- primary_error = **DATABASE_TRANSPORT_FAILURE / DatabaseTransportTimeout**.
- cleanup_errors = **two UNLOCK_SKIPPED_INVALID_CONNECTION records**, one per
  failed attempt; connection_state = INVALID_OR_CLOSED.
- provider_calls = **0**.
- No further retry was run. Resumption now requires a separately authorized
  response to the actual blocker, not simply restarting around the ledger.

### Retention and catalog

No lease renewal occurred: the run stopped while its existing expiry was still
**2026-09-19 09:04:18 UTC / 14:34:18 IST**. The authorized 24-hour conditional
renewal implementation remains available, but no old/new renewal event or
renewal success is claimed. There is no background renewal.

Preflight and subsequent ownership gates matched the unrelated catalog:
**126 objects**, hash
`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
The latest successful gate preceded the second case-72 attempt. There was no
fresh post-stop catalog inspection or complete post-run database revalidation.
No DDL, unrelated-object mutation, corpus mutation or serving activation was
performed.

### Partial metrics only: 71 paired cases, not a 90-case acceptance

Case 71 has one GOLD_MAPPING_GAP and zero scoreable spans; it cannot establish
answer/evidence success. Thus adding it leaves the original 90 scoreable-span
and required-document denominators unchanged. Case 72's unpaired legacy lane
is excluded from this paired summary. Saved outcomes were aggregated; previous
retrieval was not recomputed.

| Metric | Legacy | Structural |
| --- | ---: | ---: |
| Dense @5 | 16/90 (17.7778%) | 64/90 (71.1111%) |
| Dense @10 | 26/90 (28.8889%) | 68/90 (75.5556%) |
| Dense @48 | 65/90 (72.2222%) | 79/90 (87.7778%) |
| FTS @5 | 7/90 (7.7778%) | 5/90 (5.5556%) |
| FTS @10 | 9/90 (10.0000%) | 5/90 (5.5556%) |
| FTS @48 | 17/90 (18.8889%) | 11/90 (12.2222%) |
| RRF @10 | 32/90 (35.5556%) | 69/90 (76.6667%) |
| RRF @48 | 67/90 (74.4444%) | 84/90 (93.3333%) |
| Materialized supporting spans | 67/90 (74.4444%) | 65/90 (72.2222%) |
| Required documents | 86/90 (95.5556%) | 68/90 (75.5556%) |
| Duplicate evidence | 0/3374 (0%) | 0/1076 (0%) |
| Source-noise proxy | 745/3134 (23.7715%) | 129/1008 (12.7976%) |
| Lexical collapse cases | 0/71 (0%) | 7/71 (9.8592%) |
| ATOM_ONLY cases/routes | 0/71 cases; 0 routes | 0/71 cases; 0 routes |
| INCOMPLETE_BUDGET | 0/71 (0%) | 71/71 (100%) |
| QUERY_UNDERSTANDING_FAILURE | 2/71 (2.8169%) | 2/71 (2.8169%) |
| GOLD_MAPPING_GAP assignments | 36/126 (28.5714%) | 36/126 (28.5714%) |

Candidate diversity is a **count, not an accuracy percentage**: 377 document
appearances / 71 cases = 5.309859 documents/case legacy; 304/71 = 4.281690
structural. The source-noise proxy is relative to mapped required sources;
it does not prove every other source irrelevant. Ninety field assignments
remain unreviewed. No generated answers, false-absence or unsupported-answer
quality claims are scored.

All six already-measured structural-versus-legacy materialization regressions
remain: **4, 30, 35, 52, 60, 61**. All their supported spans had reached
structural RRF@48 before materialization dropped some/all; strong dense scores
do not negate these final-evidence losses.

The wider structural RRF→materialization loss inventory remains:
**4, 30, 35, 51, 52, 55, 58, 60, 61, 62, 63, 64, 65, 66**.
Required-document regressions remain:
**30, 51, 52, 55, 58, 60, 61, 62, 63, 64, 65, 66**.
Structural materialization improvements remain **51, 55, 66, 69, 70**.
FTS regressions remain @48: **4, 34, 36, 52**; @10:
**34, 35, 36, 52**; @5: **34, 36**. No prior dense regression or FTS
improvement was introduced by case 71's unscoreable addition.
Lexical collapse remains **1, 3, 4, 35, 38, 52, 60**; query-understanding failures
remain **53, 54**. Every saved structural case **1–71** is INCOMPLETE_BUDGET;
every paired legacy case is COMPLETE. Case 72 structural has no budget/result
artifact and must not be counted as a measured budget or recall failure.

The complete 90-case improvement/regression inventory is **unavailable**, not
inferred from 71 cases. Full A/B acceptance is withheld.

| Partial retrieval latency, ms | Legacy p50 | Legacy p95 | Structural p50 | Structural p95 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 2445.532 | 2689.866 | 2312.791 | 2788.159 |
| FTS | 1571.205 | 1799.340 | 1649.738 | 2346.708 |
| RRF | 0.245300 | 0.442000 | 0.248900 | 0.390300 |
| Materialization | 130926.306 | 162138.471 | 319360.012 | 464415.343 |
| Total retrieval | 138630.482 | 170503.994 | 327184.090 | 479425.906 |

These are retained disposable-canary retrieval measurements, not production/chat
latencies. Failed attempts and preflight are outside these successful paired
latency distributions.

### Tests, preservation and scope

Latest combined focused command, run after the final validation-transport edit:

```text
.\.venv\Scripts\python.exe -B -m unittest test_canary_evaluation_resilience test_canary_evaluation_resume test_canary_alternate_credential test_canary_durable_recovery test_canary_provider_recovery test_canary_real_handoff
```

**140/140 PASS, 50.540 seconds**, including **34 new resilience tests** and
18 evaluation-resume tests. Tests cover logical validation equivalence and
corruption rejection, bounded SQL construction, preflight disconnect/reconnect,
one retry/second failure, immutable saved lanes, durable retry ledger,
provider denial, callback restoration, invalid-connection unlock avoidance,
primary-versus-cleanup cases and terminal fallback. The specific coverage gaps
above are disclosed rather than hidden behind the count.

Post-stop local checks:

- **740/740 protected hashes unchanged**.
- **140/140 original lane artifacts byte-identical**; original 56 case-1–28
  artifacts also unchanged. All saved retrieval remains immutable.
- **143 lane artifacts**, **71/71 pair checksums PASS**.
- **1,048/1,048 bounded JSON artifacts PASS**, no pending artifact.
- **6/6 changed/new Python AST checks PASS**; changed harness imports PASS.
- Secret-pattern scan **1,055 files PASS**; no API key in the checking process.
- `.env` byte-identical. No generated credential or secret URL was persisted.
- `git diff --check`: PASS, existing line-ending warnings only.
- **Canonical suite NOT RUN**: user explicitly gates it on 90/90.
  Historical 3,739 is not presented as a fresh result.

Fresh preflight preserved the existing zero-unauthorized-result security
baseline for foreign org, foreign bot, stale generation, stale source and
identical-text foreign scope across dense/FTS/routing/materialization.
Successful new artifacts passed authorized route/source/manifest checks.
Those are not 90-case coverage or newly rerun adversarial fixtures.

Starting/final branch and HEAD remain **main /
e1e533461ca72f5d44fd63e576da74301bc48c42**. Changes remain uncommitted:

1. `backend/scripts/canary_evaluation_resume.py`
2. `backend/scripts/canary_evaluation_transport.py` (new)
3. `backend/scripts/canary_evaluation_validation.py` (new)
4. `backend/test_canary_evaluation_resilience.py` (new)
5. `backend/test_canary_evaluation_resume.py`
6. `backend/scripts/test_scoped_rag_regressions.py`
7. This report.

The pre-existing six sealed recovery implementation files and application
retrieval files were not edited. The test-runner change only registers the
focused resilience tests; the prior resume test change adapts its ownership
fixture. The original evaluation admission remains immutable, with a separate
execution-only admission tied to the reviewed checkpoint.

**Next action:** separately diagnose the repeated case-72 structural atom-read
response failure using safe operation/scope telemetry, and close the disclosed
evaluation-wrapper edge cases before authorizing another unsaved-lane attempt.
Do not tune retrieval or discard saved results. The exhausted retry is not
automatically reset.

No Gemini/other provider, new embeddings/vectors, recrawl, ingestion, corpus
rebuild, query rewrite, retrieval tuning, chat/widget requests, generated
answers, production access, deployment, commit or push occurred. Process-only
CANARY variables were removed in the evaluator's terminal finally path and the
process exited. The run is stopped, not left in the background.

**Final decision: C — PHASE 4.1P — BLOCKED.**

---



## DATABASE-RECOVERY + FINAL EVALUATION CONTINUATION — 2026-09-19

**C — PHASE 4.1P — BLOCKED: exact sealed-data preflight could not finish a
bounded database read. Still 70/90 pairs; no case-71 retrieval was run.**

This is a **per-operation database response failure**, not an overall evaluation
deadline or a decision to stop because the remaining evaluation is slow. The
database is reachable through a fresh connection, but a complete, trustworthy
retained-data proof was not obtained. No retrieval result or identity mismatch
was manufactured from the missing response.

### Verified local checkpoint, before any repair

Starting branch/HEAD: `main` /
`7ec2b891080051d6eddbc5f1746f0ea9c6641102`.
The expected 19 changed/untracked recovery/evaluation/report files were audited.
No unexpected implementation file was found. Fresh checks:

- Combined focused tests: **106/106 PASS**, 45.433 seconds. This includes all
  **18/18** evaluation-resume tests; they were not reported as a separate rerun.
- Protected hashes: **740/740 unchanged**.
- Existing pair checksums: **70/70 PASS**; **140** lane artifacts present.
- Original cases 1–28: **56/56 byte-identical** to the prior snapshot.
- Bounded JSON artifacts: **1,039/1,039 PASS**; no pending artifact.
- AST: **18/18 changed/untracked Python files PASS**; evaluator import PASS.
- Secret-pattern scan: **1,058 changed/artifact files PASS**; `.env` unchanged;
  no API key in the checking process.
- `git diff --check` and staged diff check: PASS, with existing newline warnings
  only.

Created the explicitly authorized **local-only checkpoint**:

`e1e533461ca72f5d44fd63e576da74301bc48c42`

Message: `Phase 4.1P: add resumable retrieval-only evaluation`.

The commit contains exactly the 19 audited files, no ignored run artifacts,
environment files or credentials. The working tree was clean immediately after
the commit. **Nothing was pushed.** This report update is the only subsequent
uncommitted change; no runtime or test repair was applied.

### Read-only database diagnosis

Only the previously authorized disposable target/run was used, with its explicit
target fingerprint and process-only URL. No application database configuration
or provider key was used. Python HTTP/socket/provider entry points were denied
by the existing `provider_free()` guard; libpq remained the database transport.

The diagnostic called the existing evaluator's `setup()` with artifact writes
replaced by read-only equality checks. It did **not** call `evaluate()`,
`run_query()`, lease renewal, staging, migration or cleanup DDL. Database work was
read-only SELECT/catalog inspection plus session/read-only settings and advisory
lock operations. No retrieval data was mutated.

1. The first diagnostic started at approximately **05:38:39 UTC**. It stalled
   before returning the complete sealed-data proof. A separate fresh SELECT-only
   connection succeeded and reported one other session as `idle / ClientRead`.
   That observation does not establish a proxy, SSL, server-restart or network
   root cause. Only the owned stalled Python diagnostic was terminated; no
   application/service process was stopped.
2. A fresh diagnostic started at approximately **05:46:10 UTC**, still read-only
   and with no retrieval. It added an ephemeral client-side **30-second bound
   per SQL execution**, alongside the unchanged connect 8-second, server
   statement 15-second and lock 3-second limits. This diagnostic-only watchdog
   was passed through stdin, not saved as application or harness code.
3. It reacquired the exact namespace advisory lock, demonstrating that the first
   process no longer held conflicting ownership. It passed the initial
   target/approval, marker/catalog, run/resume identity, manifest and lease-chain
   checks and progressed into generation validation.
4. At **SQL execution 224**, a scoped legacy-row SELECT failed to return within
   the per-operation bound. The safe watchdog emitted
   **`DATABASE_OPERATION_RESPONSE_TIMEOUT`** and closed the process. Failure was
   observed by **05:49:11 UTC**. No raw database error text, SQL parameters,
   credentials or connection address was emitted.

Exact captured call path at the blocked operation:

`EvaluationRunner.setup()` → `validate_sealed(full=True)` →
`RealCanaryRepository._validate_generation()` →
`CanaryRepository._validate_generation()` (legacy lane, line 299) →
`CanaryRepository._rows()` (line 291) → SQLAlchemy `do_execute()`.

The statement reads the retained legacy rows for one exact manifest/document
scope, before checking their payload and vector integrity. This was **not case
71 retrieval**. The database did not provide a PostgreSQL SQLSTATE or exception
message for that timed-out operation; the category is a client-observed missing
database response. It is not proof that a server-side query exceeded its SQL
timeout, that authentication failed, or that the stored data is corrupt.

**Fresh full inventory/source validation: NOT COMPLETE.** Historical PostgreSQL
18.6 / pgvector 0.8.6 and the 1,030 / 1,092 / 3,242 / 23 / 90 inventory remain the
last fully reported facts; this partial preflight must not be presented as a
complete re-verification of them. Initial ownership/catalog checks passed, but
no post-timeout final catalog proof or healthy advisory-unlock result was
obtained. Process exit closed local sockets; final server-side release was not
independently checked after the stop.

### Required stop and preserved results

The read-only preflight did not pass, so terminal/cleanup repair, bounded
per-lane execution changes and new failure-shape tests were **not attempted**.
The previously identified cleanup-masking defect remains open. No retrieval
transport retry was made: **new retrieval lanes = 0; provider calls = 0**.
No retention renewal occurred. The last recorded expiry remains
**2026-09-19 09:04:18 UTC / 14:34:18 IST**; there is no background renewal.

All cases **1–70 remain persisted, not rerun**. Case **71 LEGACY_CONTROL** is
still the first incomplete lane; neither case-71 lane artifact exists.
Cases 72–90 remain unstarted. The prior partial metrics, six materialization
regressions (4, 30, 35, 52, 60, 61), wider RRF-to-materialization losses and
70/70 structural INCOMPLETE_BUDGET findings below remain unchanged. There are
no final 90-case metrics or fresh final security/latency conclusions.

Post-diagnosis local checks again passed: 740 protected hashes; 1,039 bounded
artifacts; 70 pair checksums; all 140 lane-file hashes unchanged; `.env`
unchanged; no pending artifact or secret-pattern hit. No owned diagnostic Python
process remains. Process-only secrets expired with terminated processes; the
normally completed probe explicitly removed its CANARY variables. No secret was
printed or persisted. The complete canonical suite was **not run**, as instructed:
it is gated on 90/90 retrieval completion. Historical suite counts are not a
fresh pass.

**Exact next step:** establish why this exact retained legacy-row read stops
returning a response, using bounded read-only database/transport diagnostics,
and obtain the complete identity/source/catalog proof. Then apply the authorized
exception-safe execution repair and resume only the unsaved case-71 legacy lane.
Do not tune retrieval, alter evidence or rebuild embeddings to work around this
database response failure.

No provider/model calls, new embeddings, corpus rebuild, retrieval changes,
chat/widget requests, production access, deployment or push occurred. The only
commit was the requested preservation checkpoint above. Decision A/B and
end-to-end chat/widget acceptance remain withheld.

---

## Current evaluation-only continuation decision — 2026-09-19

**C — PHASE 4.1P — BLOCKED: database OperationalError; not elapsed time.**

**FULL EVALUATION-ONLY COMPLETION: NOT ACHIEVED — 70/90 pairs saved.**
The new deadline-free evaluator reused all 28 original pairs, completed cases
29–70 (42 additional pairs / 84 additional lane results), and began case 71's
legacy lane. There is no saved result for either lane of case 71, and cases
72–90 were not started. The 20 missing pairs are missing coverage, not 20
measured retrieval failures. **No provider calls, new embeddings, build, corpus
mutation, tuning, chat or widget requests occurred.**

### Real stop, exact evidence and uncertainty

One evaluation session/process ran:
`bec866374da44520839d1d2b6abc13d3`; no host-kill/process restart occurred.
A separate identity-only preflight
(`c9cfd75bdd514a7791249b5ff92a56b9`, status PREFLIGHT_ONLY) performed no retrieval.
The process started at 2026-09-18 19:14:31 UTC; the last completed pair was
durably written at **2026-09-19 00:48:27.213 UTC**. It therefore ran for over
5 hours 33 minutes before the last completed pair, beyond the removed five-hour
limit. Exit code **1** was observed before the final clock check at
2026-09-19 00:55:34 UTC. Exact final elapsed time was not finalized.

The safely emitted exception was SQLAlchemy **OperationalError** at:

- `backend/scripts/canary_recovery_state.py:184`,
  `ExclusiveRun.close()`, executing the parameterized
  `SELECT pg_advisory_unlock(:key)`.
- Called from `backend/scripts/canary_evaluation_resume.py:528`,
  `EvaluationRunner.run()`'s cleanup/finally block.

No SQLSTATE or raw connection message was emitted. **It is not possible to
determine the original case-71 exception from the retained output.** The cleanup
exception propagated before the evaluator could save any preceding exception,
elapsed time and final session status. The session JSON therefore
still says RUNNING at its last successful case-70 checkpoint, although local
process inspection confirms that the Python process has exited. That stale
status is not evidence that evaluation is continuing.

This exposes a terminal-recording gap in the new resume wrapper: an unlock
failure must not mask an earlier exception or prevent a durable terminal record.
The trigger might involve a connection failure, but authentication, proxy idle
timeout, SSL, statement timeout and server restart are **not established** by
the available safe evidence. No unsupported root-cause claim is made. The actual
database OperationalError is sufficient to stop under the task's failure rule;
this was not a host termination, and no automatic retrieval retry was attempted.

A separate bounded observer artifact preserves the visible exit without rewriting
the earlier session evidence:
`evaluation-observed-stop-bec866374da44520839d1d2b6abc13d3.json`.
The lock helper's connection-close finally and the runner's enclosing database
dispose/secret-clear finally were executed; the CLI also clears CANARY process
variables. Successful server-side unlock and a post-failure catalog check were
not independently verified. No database reconnection or acceptance retry was
made after the error, and no follow-on repair was implemented.

### Exact identity, scope and narrow implementation

Branch/HEAD remained `main` /
`7ec2b891080051d6eddbc5f1746f0ea9c6641102`.

- Namespace: `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`.
- Run: `paired-real`.
- Target: `f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
- Resume identity: `267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.
- Structural manifest:
  `3266a4a52aff8e7b803185d4fdf6371b799a83538719e3daa8ffeb3eefb2c8bc`.
- Legacy manifest:
  `003ecf3a2e30dbb73a8b48ccd0b6a72861a448486b5da5ae5020de2144ea99e3`.
- Same sealed generation `real-baseline-v1`; both lanes already CANARY_READ
  after their INDEX_READY seals. No generation/state publication was repeated.

Changes made in this task, relative to its starting dirty-tree snapshot:

1. Added `backend/scripts/canary_evaluation_resume.py`.
2. Added `backend/test_canary_evaluation_resume.py`.
3. Registered the focused test module in
   `backend/scripts/test_scoped_rag_regressions.py`.
4. Updated this report.

Ignored bounded evaluation artifacts were added under the existing run directory.
All other pre-existing implementation files, including the six original
identity-bound recovery files, remain byte-identical. The intentionally dirty
tree grew from 17 to 19 tracked/untracked paths; no existing work was discarded.

The standalone evaluation path does not inherit the embedding/staging runner or
its overall deadline. It calls the unchanged `run_query`, scorer and trace
formatter, using saved vectors and original manifests. Python HTTP/socket and
Gemini client entry points are denied with `UNEXPECTED_PROVIDER_ACCESS`; no
API key is needed or supplied. Database transport uses the existing libpq path.
All retrieval transactions are read-only. **Connect 8 seconds, statement
15 seconds, lock 3 seconds, transaction rollback and the existing no-automatic-
retry DB policy remain in place.** No candidate, FTS, RRF, heading, continuation,
scope, history, question, profile or materialization setting changed.

Preflight verified exact ownership/catalog, approval, run/manifest/build identities,
source snapshots and epochs, generation receipts, 1,030 structural vectors,
1,092 legacy vectors, 3,242 atoms across 23 documents, and all 90 saved query
receipts. Both preflight and the actual evaluator validated the frozen query
inventory and all 56 prior lane artifacts. Cases 1–28 are **EVALUATION_REUSE**,
not reruns. Their file hashes remain unchanged.

Each new lane was atomically written before advancing. Each complete pair has
an identity-bound checksum record; incremental aggregation was persisted.
**140 lane files and 70 pair checksum records survive.** All 70 pair checksums
pass. No partial/pending artifact remains. The observer preserves the terminal
failure despite the finalizer gap described above.

### Retention and security

**Lease renewals: 0.** Original expiry remains
**2026-09-19 09:04:18 UTC / 14:34:18 IST**. No lease write-ahead or applied-renewal
artifact exists. This task did not need to extend retention before stopping and
does not renew an inactive run in the background.

The added path supports explicitly authorized 24-hour increments only after full
sealed/source/query/configuration validation and ownership checks, with source/run
locks, compare-and-swap expiry updates and a durable old/new/reason audit
(`ACTIVE_90_CASE_EVALUATION`). Original approvals/manifests and source epochs are
immutable. This renewal path has focused deterministic coverage but **was not
exercised against the remote database in this run**.

The existing five copied-real-vector attacks were revalidated as retained
evidence, not rerun: foreign org, foreign bot, stale generation, stale source and
identical foreign text all recorded zero unauthorized dense/FTS/routing/
materialization results, with stronger raw attack matches. Every saved lane
result was checked for authorized scope, declared generation/routes, query/vector
digest, snapshot, manifest/configuration identity and bounded output.
**No unauthorized result was observed in the 140 completed lane artifacts.**

Preflight verified PostgreSQL **18.6**, pgvector **0.8.6**, and all **126 unrelated
catalog objects unchanged**, hash
`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
Post-failure remote inventory/catalog/lease state was **not rechecked**, so final
remote preservation is not claimed as newly proven. No schema, marker, fixture,
vector, extension, source or unrelated database object was deleted or rebuilt.

### Partial metrics — completed cases 1–70 ONLY

These are incremental **mapped-span hit** measurements, not final 90-case metrics
or generated-answer correctness. The 70 cases contain **90 scoreable spans** and
35 excluded mapping-gap occurrences (35/125 support assignments). Cases 15, 22,
29 and 38 have 0/0 scoreable support and are unscored, not retrieval failures.
The complete frozen fixture still has 109 scoreable spans, 43 mapping gaps and
90 unreviewed field associations. No missing labels were invented.

| Metric | Legacy | Structural |
| --- | ---: | ---: |
| Dense span-hit recall @5 | 16/90 (17.777778%) | 64/90 (71.111111%) |
| Dense span-hit recall @10 | 26/90 (28.888889%) | 68/90 (75.555556%) |
| Dense span-hit recall @48 | 65/90 (72.222222%) | 79/90 (87.777778%) |
| FTS span-hit recall @5 | 7/90 (7.777778%) | 5/90 (5.555556%) |
| FTS span-hit recall @10 | 9/90 (10.000000%) | 5/90 (5.555556%) |
| FTS span-hit recall @48 | 17/90 (18.888889%) | 11/90 (12.222222%) |
| RRF span-hit recall @10 | 32/90 (35.555556%) | 69/90 (76.666667%) |
| RRF span-hit recall @48 | 67/90 (74.444444%) | 84/90 (93.333333%) |
| Materialized supporting-span recall | 67/90 (74.444444%) | 65/90 (72.222222%) |
| Required-document recall | 86/90 (95.555556%) | 68/90 (75.555556%) |
| Exact-identity duplicate evidence | 0/3326 (0.000000%) | 0/1060 (0.000000%) |
| Source-noise proxy relative to mapped support | 745/3134 (23.771538%) | 129/1008 (12.797619%) |
| Candidate-diversity sum / evaluated cases | 365/70 | 295/70 |
| Cases containing ATOM_ONLY routes | 0/70 (0 total) | 0/70 (0 total) |
| Cases with lexical route collapse | 0/70 | 7/70 |
| INCOMPLETE_BUDGET | 0/70 | 70/70 |
| QUERY_UNDERSTANDING_FAILURE | 2/70 | 2/70 |
| GOLD_MAPPING_GAP occurrences / support assignments | 35/125 | 35/125 |

Source noise is relative to mapped required documents, not proof that every other
selected source is irrelevant. Candidate diversity is a diagnostic mean/sum, not
an accuracy score. The bounded historical traces retain only the first 48 fused
routes; original full-union candidate-diversity/ATOM_ONLY diagnostics are retained,
not falsely reconstructed from missing tail routes. False-absence and wrong-source
claims remain unscored because no answers were generated.

All completed structural cases **1–70 inclusive** are INCOMPLETE_BUDGET; all
completed legacy cases are COMPLETE. Lexical collapse appears in structural
cases **1, 3, 4, 35, 38, 52, 60**. Historical frozen-scope/gold disagreement
(`QUERY_UNDERSTANDING_FAILURE`) appears in **53 and 54 in both lanes**; it was
not repaired or silently attributed to the new structural representation.

### Measured losses and improvements — partial, unfixed

Six cases have lower structural materialized support than legacy:

| Case | Legacy materialized | Structural dense @48 | Structural RRF @48 | Structural materialized | Structural required documents |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| 30 | 2/2 | 2/2 | 2/2 | 1/2 | 1/2 |
| 35 | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 |
| 52 | 4/7 | 2/7 | 7/7 | 2/7 | 3/7 |
| 60 | 2/2 | 2/2 | 2/2 | 1/2 | 1/2 |
| 61 | 2/2 | 2/2 | 2/2 | 1/2 | 1/2 |

In each, structural RRF @48 contains all mapped support before exact materialization
loses it: **STRUCTURAL_MATERIALIZATION_LOSS**. Case 52's FTS channel helps rescue
support missing from its dense top 48, but materialization then falls from 7/7 to
2/7. These stage observations do not by themselves prove which individual budget
or hydration rule caused each loss; every structural trace is INCOMPLETE_BUDGET.
No repair, larger budget, extra hydration or alternative answer evidence was used.

Structural RRF-to-materialization losses occur in **4, 30, 35, 51, 52, 55, 58, 60,
61, 62, 63, 64, 65, 66**; not all are worse than legacy, which sometimes missed the
same spans earlier. Required-document recall also regresses in several otherwise
equal or improved span-hit cases, so better dense/RRF recall is not accepted as a
substitute for final evidence breadth.

For every measured recall metric, these are all changed cases in the completed
subset (unlisted cases tie):

| Metric | Structural improvement cases | Structural regression cases |
| --- | --- | --- |
| Dense span-hit recall @5 | 1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 21, 31, 32, 33, 34, 35, 36, 37, 39, 40, 41, 43, 44, 45, 52, 53, 56, 57, 58, 60, 61, 62, 64, 65, 66, 67, 68, 69, 70 | None |
| Dense span-hit recall @10 | 2, 3, 4, 6, 9, 12, 13, 16, 17, 18, 19, 20, 21, 31, 32, 33, 34, 35, 36, 37, 39, 40, 43, 44, 52, 57, 58, 60, 61, 62, 64, 65, 66, 67, 68, 69, 70 | None |
| Dense span-hit recall @48 | 51, 55, 58, 62, 63, 64, 65, 66, 69, 70 | None |
| FTS span-hit recall @5 | None | 34, 36 |
| FTS span-hit recall @10 | None | 34, 35, 36, 52 |
| FTS span-hit recall @48 | None | 4, 34, 36, 52 |
| RRF span-hit recall @10 | 2, 3, 4, 6, 9, 10, 12, 13, 16, 17, 18, 19, 20, 21, 31, 32, 33, 37, 43, 44, 51, 55, 57, 58, 60, 61, 62, 64, 65, 66, 67, 68, 69, 70 | None |
| RRF span-hit recall @48 | 51, 52, 55, 58, 62, 63, 64, 65, 66, 69, 70 | None |
| Materialized supporting-span recall | 51, 55, 66, 69, 70 | 4, 30, 35, 52, 60, 61 |
| Required-document recall | None | 30, 51, 52, 55, 58, 60, 61, 62, 63, 64, 65, 66 |

### Partial timing — remote disposable canary, not production/chat latency

Nearest-rank p50/p95 over 70 results per lane, milliseconds:

| Stage | Legacy p50 | Legacy p95 | Structural p50 | Structural p95 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 2440.954 | 2675.634 | 2304.790 | 2737.636 |
| FTS | 1571.205 | 1799.340 | 1644.386 | 2346.708 |
| RRF | 0.245 | 0.442 | 0.249 | 0.390 |
| Exact materialization | 130926.306 | 162138.471 | 319116.831 | 464415.343 |
| Total retrieval | 138630.482 | 170503.994 | 326972.167 | 479425.906 |

Materialization accounts for **94.416303%** of summed legacy retrieval time and
**97.604175%** of structural retrieval time. The slowest structural completed
case was **32: 836,658.512 ms**; case 60 took **834,466.892 ms**. Both were allowed
to finish; time alone did not stop the run. New completed cases 29–70 total
**5,742,388.095 ms legacy + 13,852,693.683 ms structural**. These trace times exclude
preflight, file/checksum work and the incomplete case 71; no exact final wall-time
reconciliation is claimed because terminal timing was not saved. Original 1–28
timings were reused unchanged and span a different measurement session.

### Completed per-case comparison

Each cell is **Legacy : Structural**, found/scoreable. Latency is legacy /
structural seconds. This is not a 90-case completion table.

| Case | Dense @5 | FTS @48 | RRF @10 | Materialized support | Required documents | Seconds L / S |
| --- | --- | --- | --- | --- | --- | ---: |
| 1 | 0/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 151.149 / 343.530 |
| 2 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 180.775 / 372.991 |
| 3 | 0/1 : 1/1 | 1/1 : 1/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 146.473 / 341.088 |
| 4 | 0/1 : 1/1 | 1/1 : 0/1 | 0/1 : 1/1 | 1/1 : 0/1 | 1/1 : 1/1 | 141.055 / 347.725 |
| 5 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 143.576 / 320.940 |
| 6 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 148.158 / 330.306 |
| 7 | 0/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 141.185 / 359.482 |
| 8 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 136.540 / 479.426 |
| 9 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 141.432 / 385.642 |
| 10 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 148.506 / 534.976 |
| 11 | 0/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 141.587 / 305.766 |
| 12 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 142.990 / 327.460 |
| 13 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 135.900 / 353.836 |
| 14 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 145.590 / 379.142 |
| 15 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 144.464 / 311.028 |
| 16 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 138.257 / 308.745 |
| 17 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 187.479 / 342.666 |
| 18 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 141.004 / 325.539 |
| 19 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 188.492 / 313.259 |
| 20 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 144.219 / 330.065 |
| 21 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 142.153 / 445.777 |
| 22 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 143.423 / 337.513 |
| 23 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 149.550 / 418.829 |
| 24 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 140.626 / 324.060 |
| 25 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 138.422 / 332.206 |
| 26 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 133.406 / 396.538 |
| 27 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 139.514 / 385.442 |
| 28 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 139.333 / 384.384 |
| 29 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 167.962 / 326.972 |
| 30 | 1/2 : 1/2 | 0/2 : 0/2 | 1/2 : 1/2 | 2/2 : 1/2 | 2/2 : 1/2 | 134.259 / 319.245 |
| 31 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 131.410 / 339.646 |
| 32 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 133.229 / 836.659 |
| 33 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 133.622 / 316.517 |
| 34 | 0/1 : 1/1 | 1/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 135.577 / 292.283 |
| 35 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 0/1 | 1/1 : 1/1 | 139.868 / 313.058 |
| 36 | 0/1 : 1/1 | 1/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 135.485 / 309.013 |
| 37 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 129.208 / 318.768 |
| 38 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 0/0 : 0/0 | 137.945 / 324.934 |
| 39 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 132.366 / 339.568 |
| 40 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 136.410 / 391.099 |
| 41 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 135.892 / 327.504 |
| 42 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 138.630 / 268.989 |
| 43 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 138.622 / 286.223 |
| 44 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 134.777 / 308.369 |
| 45 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 133.492 / 231.028 |
| 46 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 133.969 / 249.428 |
| 47 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 142.097 / 225.946 |
| 48 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 133.733 / 273.786 |
| 49 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 139.141 / 270.349 |
| 50 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 136.007 / 294.895 |
| 51 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 1/2 | 0/2 : 1/2 | 2/2 : 1/2 | 135.656 / 346.863 |
| 52 | 0/7 : 1/7 | 6/7 : 3/7 | 2/7 : 2/7 | 4/7 : 2/7 | 7/7 : 3/7 | 138.970 / 387.270 |
| 53 | 0/3 : 1/3 | 0/3 : 0/3 | 1/3 : 1/3 | 1/3 : 1/3 | 1/3 : 1/3 | 97.338 / 174.656 |
| 54 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 0/2 | 103.050 / 170.579 |
| 55 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 1/2 | 0/2 : 1/2 | 2/2 : 1/2 | 142.940 / 430.459 |
| 56 | 0/2 : 2/2 | 0/2 : 0/2 | 2/2 : 2/2 | 2/2 : 2/2 | 2/2 : 2/2 | 137.989 / 310.910 |
| 57 | 0/2 : 1/2 | 0/2 : 0/2 | 0/2 : 2/2 | 2/2 : 2/2 | 2/2 : 2/2 | 170.504 / 367.865 |
| 58 | 0/2 : 1/2 | 0/2 : 0/2 | 0/2 : 1/2 | 1/2 : 1/2 | 2/2 : 1/2 | 141.866 / 339.466 |
| 59 | 1/1 : 1/1 | 0/1 : 0/1 | 1/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 137.828 / 277.584 |
| 60 | 0/2 : 2/2 | 1/2 : 1/2 | 0/2 : 1/2 | 2/2 : 1/2 | 2/2 : 1/2 | 136.535 / 834.467 |
| 61 | 0/2 : 1/2 | 0/2 : 0/2 | 0/2 : 2/2 | 2/2 : 1/2 | 2/2 : 1/2 | 140.299 / 350.514 |
| 62 | 0/2 : 1/2 | 0/2 : 0/2 | 0/2 : 1/2 | 1/2 : 1/2 | 2/2 : 1/2 | 136.626 / 319.667 |
| 63 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 0/2 | 0/2 : 0/2 | 2/2 : 0/2 | 137.189 / 247.705 |
| 64 | 0/3 : 1/3 | 0/3 : 0/3 | 0/3 : 1/3 | 1/3 : 1/3 | 3/3 : 1/3 | 137.457 / 309.035 |
| 65 | 0/3 : 1/3 | 0/3 : 0/3 | 0/3 : 1/3 | 1/3 : 1/3 | 3/3 : 1/3 | 137.258 / 272.791 |
| 66 | 0/2 : 1/2 | 0/2 : 0/2 | 0/2 : 2/2 | 0/2 : 1/2 | 2/2 : 1/2 | 140.297 / 346.214 |
| 67 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 141.819 / 317.818 |
| 68 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 1/1 : 1/1 | 1/1 : 1/1 | 136.942 / 327.184 |
| 69 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 0/1 : 1/1 | 1/1 : 1/1 | 136.378 / 300.825 |
| 70 | 0/1 : 1/1 | 0/1 : 0/1 | 0/1 : 1/1 | 0/1 : 1/1 | 1/1 : 1/1 | 141.746 / 256.544 |
| 71 | STARTED legacy, no saved result | — | — | UNAVAILABLE | UNAVAILABLE | — |
| 72–90 (all 19 cases) | NOT STARTED | — | — | NOT EVALUATED | NOT EVALUATED | — |

### Validation and remaining boundary

Before remote continuation:

- New evaluation-resume tests: **18/18 PASS**, 5.873 seconds.
- Combined focused evaluation/alternate/recovery/handoff tests:
  **106/106 PASS**, 55.107 seconds.
- Syntax/import checks for the new path and registry: PASS.
- Protected hashes: **740/740 unchanged**.

New tests cover saved-artifact identity/configuration/receipt validation,
foreign/stale routes, score tampering, preservation of INCOMPLETE_BUDGET,
no-deadline/first-incomplete-lane dispatch, atomic/immutable persistence, bounded
output, provider denial, expiry/read-gate behavior, authorized progress-bound
24-hour renewal, compare-and-swap limits and lease audit recovery. They did **not**
cover unlock failure masking terminal recording; the live run exposed that gap.

After the stop, local-only checks passed: **740/740 protected hashes**;
**56/56 original lane files byte-identical**; **70/70 pair checksum records**;
**1,039/1,039 bounded JSON artifacts**; AST for **18 changed/untracked Python
files**; secret-pattern scan of **1,058 changed/artifact files**; `.env` unchanged;
no API key in the validation process; no pending artifact. `git diff --check`
passes with existing LF/CRLF warnings only. Post-write checks and the resume-module
import also passed; only the registry and report changed among the 17 starting paths.

**The complete canonical suite was NOT run:** the instruction explicitly places
it after 90/90 completion. Historical 3,739/3,739 remains historical; it is not
reported as a fresh full-suite pass. No current full acceptance is claimed.

**Exact next step:** separately diagnose the disposable database connection
failure read-only, and repair only exception-safe terminal recording if
authorized so an advisory-unlock failure cannot conceal the primary exception.
Then revalidate this same retained sealed identity, original lease/source state,
all 140 saved lane files and 90 query receipts before resuming from **case 71,
LEGACY_CONTROL**. Do not repeat 1–70, re-embed, rebuild, tune retrieval or start
chat/widget validation. If the lease has expired, renewal needs the authorized
identity/source checks; no unattended renewal is running now.

The current task stops on the observed database failure. No customer/application
database, provider API/key, production service, serving activation, deployment,
crawl, ingestion, re-embedding, commit or push was used. No later phase was started.
The database secret was process-only, never printed or written into files.

---

## Historical exact retained-run continuation decision — 2026-09-18

**C — PHASE 4.1P — BLOCKED**

**Blocker: `CANARY_EXECUTION_DEADLINE`, not Gemini quota.** The authorized
continuation ran without changes to its original 300-minute limit, including
after the operator explicitly chose to continue the bounded run. It exited 1
after **18,010,740.992 ms (5 hours, 10.741 seconds)**. The cooperative deadline
check stopped entry to case 29's retrieval repository; it did not erase progress.
The result artifact was finalized at **2026-09-18 17:49:19.895 UTC**.

**Embedding build COMPLETE: 1,030 structural + 1,092 legacy = 2,122 corpus
vectors; all 90 unique query vectors durably saved before evaluation.** Both
lanes passed the existing atomic INDEX_READY seal and CANARY_READ publication.
All five copied-real-vector isolation attacks passed. **Only 28/90 paired
retrieval cases completed (56 lane evaluations); cases 29–90 have no scored
paired result.** No automatic restart, deadline extension, tuning or re-embedding
followed. Full paired retrieval acceptance and chat/widget readiness are withheld.

There is also a measured retrieval regression in the completed subset: **case 4
retained 1/1 supporting spans in legacy but 0/1 in structural materialization**.
Its structural dense/RRF candidates did contain mapped support. All 28 structural
cases reported INCOMPLETE_BUDGET. These findings remain unfixed and must not be
hidden by the successful embedding build or better structural dense recall.

### Scope, preservation and narrow continuation changes

Starting/final branch is `main`; HEAD remains
`7ec2b891080051d6eddbc5f1746f0ea9c6641102`. The same 17 tracked/untracked paths
remain in the intentionally dirty working tree. Relative to this continuation's
starting snapshot, only these three files changed:

- `backend/scripts/canary_alternate_credential.py`
- `backend/test_canary_alternate_credential.py`
- This report.

The wrapper preserves the prior alternate runner's defaults and adds an exact
2,106-vector continuation inventory, single-attempt provider calls, delayed
one-time eight-item UNKNOWN grant, mandatory durable completion of all 90 query
receipts before paired evaluation, and a per-instance no-delete wrapper honoring
the operator's retained-run instruction. Connection closing still delegates to
the existing database object. The original identity-bound recovery files,
retrieval implementation, Gemini SDK/configuration module, schema, profile,
frozen queries/history, FTS/RRF settings, candidate/materialization budgets,
heading policy and corpus inputs did not change in this continuation. No files
were edited while the live measurements were running.

### Exact retained-run gates and credential usage

Namespace: `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`; run: `paired-real`.
Target fingerprint:
`f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
Resume identity:
`267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.
Current session: `4fc3262c806c4828a69abeeb13b64d5c`.

Preflight revalidated all **2,106 existing successful vectors** and exact
source/version/epoch, manifest, receipt, profile, configuration, ownership,
implementation and TTL identities before new spend. The starting ledger was
1,030 structural successes, 1,076 legacy successes, eight UNKNOWN, eight PENDING
and 90 pending queries. No new schema or generation was created.

The supplied new key was used only with explicit process-only authorization as
`CANARY_GEMINI_API_KEY`, operational label **new-development-credential**.
No API key was recovered from chat history, printed, hashed, saved in files,
written to `.env`, or placed in reports/artifacts. No alternate-provider or
existing-key fallback was used. The client closed and process exited; relevant
CANARY secret environment variables were absent in the final validation process.

**Exact compatibility: 3/3 PASS**, with the same deterministic distinct retained
structural inputs selected independently of retrieval results. All 768 f32
coordinates, 3,072 canonical bytes, input/vector hashes and profile/configuration
matched exactly. These comparison-only outputs did not replace retained vectors.
The input/vector pairs are the same three listed in the historical compatibility
table below. No epsilon or cosine-only substitution was used.

Provider remains Gemini Developer API / `gemini-embedding-001` / profile v1 /
768 dimensions, without task/title/prefix/extra normalization. Profile hash:
`bd524bb94626d8d5f5282b286beffeb5fc806011685d18af16fa24619cc7e407`.
Configuration hash:
`27286dd5851c8bab987365fb2619200d621390eac31c295d86eed9ad2e206628`.

**Useful quota probe: PASS.** One pending legacy input, 79 local tokens, one
successful request, no retry; PostgreSQL persistence/readback/digest/provenance
verified, and never re-embedded later:

- Input: `d37a6ffa57bd81d940bfb1c196f98b53fbb9ba74ca9fe47e2faf47c10c3e921d`
- Vector: `a9cc59fa95ec8d3aa260f6658a022c4c5f48af99839d17ac0bc7c1875f60afa5`

Only after both gates passed was the exact eight-item UNKNOWN grant spent once:
`c5a064ee6485e4559cd49768d28ef8ab0311c6f0b3aca793fa3bdbaf6e648066`, reference
`phase41p-new-key-final-resume-20260918`. All eight completed in one successful
eight-input request (911 local tokens). Remaining pending legacy work finished;
15 newly generated build vectors plus one validated identical-input receipt
reuse filled the 16 outstanding rows. Existing successful work was not regenerated
apart from the three explicitly authorized comparison probes.

| Current continuation usage | Measured result |
| --- | ---: |
| Provider requests / successes / failures | 95 / 95 / 0 |
| Automatic retries | 0 |
| Evidence outputs (including 3 comparison-only probes) | 18 |
| Query outputs, all durably readback-verified | 90 |
| Submitted inputs | 108 |
| Local evidence tokens / query tokens | 3,243 / 1,254 |
| Total local input tokens | 4,497 |
| Total measured HTTP call time | 63,345.000 ms |
| Previously completed rows revalidated/reused | 2,106 |
| Additional exact-input persisted reuse | 1 |
| Billed provider tokens / monetary cost | UNKNOWN / UNKNOWN |

All 95 attempts lack billed-usage metadata; the raw metric's zero accumulator is
**not evidence of zero billed tokens**. Last request started at
2026-09-18 13:43:13.129 UTC. No provider requests occurred during paired retrieval.
Across this retained run's three credential labels: 384 attempts, 378 successes,
six historical failures and four historical retries; 2,152 submitted inputs and
430,182 local input tokens, below unchanged 2,500/500,000 caps. Historical quota
failures below are not failures of this new credential.

### Sealing, durable state and isolation — PASS

Both exact manifests sealed atomically through the existing rules; no partial
pair was published. Measured paired seal time: **169,873.932 ms**. All 90 frozen
unique query vectors then completed and were persisted/readback-verified before
security testing or case 1. Both lanes used identical query receipts and snapshot
hashes in every completed pair. No query rewriting or additional security
embedding was performed.

Final SELECT-only verification on the same approved disposable database found:

- 23 frozen documents; 3,242 atoms; 1,030 structural vectors; 1,092 legacy vectors.
- 90 query work rows SUCCEEDED; zero remaining/UNKNOWN legacy work; no failed or
  missing build work in the final work ledgers.
- Both manifests and the run remain CANARY_READ; recovery condition is PAUSED,
  not COMPLETE. This is disposable canary state, not serving activation.
- One ownership marker, two total spend grants (historical seven-item grant plus
  current eight-item grant), 384 retained provider-attempt records.
- Resume identity and identity-bound implementation match; owned catalog unchanged.
- All 126 unrelated catalog objects unchanged; catalog hash remains
  `5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
- Owned schema size: 148,414,464 bytes; retained as explicitly instructed.
- PostgreSQL 18.6 / pgvector 0.8.6. No production/application database was used.

All five isolation scenarios (foreign organization, foreign bot, stale generation,
stale source, identical text in another scope) used copied real vectors with raw
attack distance **0.0**, recorded strictly stronger than authorized candidates.
Each produced **0 unauthorized dense, FTS, routing and materialization results**.
Security evidence is in the final result artifact; no extra Gemini call was used.

### Partial paired retrieval metrics — cases 1–28 ONLY

All 56 completed lane traces were `full_hybrid`, with identical query/snapshot
identity across lanes. These are micro-aggregated **mapped-span hit** measures,
not semantic field completeness or final-answer correctness. Only 26 support
spans are scoreable in this subset. Five GOLD_MAPPING_GAP occurrences were excluded
here; the full fixture still contains 43 excluded mapping gaps and 90 unreviewed
field associations. Cases 15 and 22 have zero scoreable spans and are not scored
as retrieval failures. No semantic labels were invented.

| Metric | Legacy | Structural |
| --- | ---: | ---: |
| Dense recall @5 | 8/26 (30.769231%) | 26/26 (100%) |
| Dense recall @10 | 13/26 (50%) | 26/26 (100%) |
| Dense recall @48 | 26/26 (100%) | 26/26 (100%) |
| FTS recall @5 | 1/26 (3.846154%) | 1/26 (3.846154%) |
| FTS recall @10 | 1/26 (3.846154%) | 1/26 (3.846154%) |
| FTS recall @48 | 3/26 (11.538462%) | 2/26 (7.692308%) |
| RRF recall @10 | 12/26 (46.153846%) | 26/26 (100%) |
| RRF recall @48 | 26/26 (100%) | 26/26 (100%) |
| Materialized supporting-span recall | 26/26 (100%) | 25/26 (96.153846%) |
| Required-document recall | 26/26 (100%) | 26/26 (100%) |
| Exact-identity duplicate evidence | 0/1,344 | 0/424 |
| Source-noise proxy relative to mapped support | 135/1,248 (10.817308%) | 24/396 (6.060606%) |
| Candidate-diversity total across cases | 92 | 78 |
| ATOM_ONLY count | 0 | 0 |
| Cases with lexical collapse | 0 | 3 (1, 3, 4) |
| INCOMPLETE_BUDGET cases | 0 | 28 |
| QUERY_UNDERSTANDING_FAILURE | 0 | 0 |
| Excluded GOLD_MAPPING_GAP occurrences | 5 | 5 |
| Wrong-resource/source claims; false-absence claims | UNSCORED | UNSCORED |

Source noise is a GOLD-relative proxy, not proof that every other selected source
is irrelevant. Candidate diversity is a summed diagnostic, not a standalone
quality score. No answers were generated, so unsupported/wrong-source/absence
claims cannot be scored. Security violations were zero in the explicit attacks
above; no all-90-case quality or safety outcome is inferred from partial coverage.

**Measured regression:** in case 4 structural dense @5 and RRF @10 both hit the
mapped support, and required-document recall remained 1/1. Exact atomic
materialization returned 0/1 supporting spans versus legacy's 1/1, alongside
INCOMPLETE_BUDGET and 8 materialized records. Thus finding the right document or
contextual search entry was insufficient to preserve its answer evidence. No
contextual entry text was substituted for atoms, and no repair/tuning was made.
Structural FTS @48 was also lower on this subset (2/26 versus 3/26). Better dense
and top-10 fusion recall does not erase either measured loss.

### Timing — disposable remote canary, NOT production/chat latency

Nearest-rank p50/p95 over the 28 completed cases per lane, in milliseconds:

| Stage | Legacy p50 | Legacy p95 | Structural p50 | Structural p95 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 2,494.459 | 2,853.918 | 2,326.322 | 2,788.159 |
| FTS | 1,620.394 | 1,839.042 | 1,658.083 | 2,319.256 |
| RRF | 0.250 | 0.442 | 0.255 | 0.428 |
| Exact evidence materialization | 134,284.116 | 177,738.033 | 334,437.378 | 464,415.343 |
| Total retrieval | 142,152.526 | 187,479.064 | 342,665.776 | 479,425.906 |

Materialization accounts for **94.465160% of summed legacy retrieval time** and
**97.673778% of summed structural retrieval time**. The evaluation timing recorded
43,480 DBAPI SQL executions. This identifies the measured slow stage; it does
not separate server execution, network round-trips and local validation into
unmeasured subcomponents. No performance fix was attempted.

Full-run exclusive timing: query evaluation 14,539,733.645 ms (80.7281%), work
ledger 2,571,375.589 ms (14.2769%), vector persistence/readback 486,619.773 ms
(2.7018%), seal 169,873.911 ms (0.9432%), source reconstruction 64,695.474 ms
(0.3592%), provider wait 64,363.153 ms (0.3574%), other 114,079.464 ms (0.6334%).
These reconcile approximately to the 18,010,740.992 ms wall time. Provider HTTP
time is included in provider wait, not an additional additive stage. The build
summary's `build_ms` is cumulative to that checkpoint, not incremental embedding
HTTP time. Two nonfatal SQLAlchemy single-row query-CTE cartesian-product warnings
were observed; all completed channels succeeded. No warning was suppressed by a fix.

### Case-by-case observed materialized recall and latency

Every completed legacy case was COMPLETE; every completed structural case was
INCOMPLETE_BUDGET. Table recall is found/scoreable mapped spans; latency is seconds.

| Case | Legacy span recall | Structural span recall | Legacy seconds | Structural seconds |
| --- | --- | --- | ---: | ---: |
| 1 | 1/1 | 1/1 | 151.149 | 343.530 |
| 2 | 1/1 | 1/1 | 180.775 | 372.991 |
| 3 | 1/1 | 1/1 | 146.473 | 341.088 |
| 4 | 1/1 | 0/1 | 141.055 | 347.725 |
| 5 | 1/1 | 1/1 | 143.576 | 320.940 |
| 6 | 1/1 | 1/1 | 148.158 | 330.306 |
| 7 | 1/1 | 1/1 | 141.185 | 359.482 |
| 8 | 1/1 | 1/1 | 136.540 | 479.426 |
| 9 | 1/1 | 1/1 | 141.432 | 385.642 |
| 10 | 1/1 | 1/1 | 148.506 | 534.976 |
| 11 | 1/1 | 1/1 | 141.587 | 305.766 |
| 12 | 1/1 | 1/1 | 142.990 | 327.460 |
| 13 | 1/1 | 1/1 | 135.900 | 353.836 |
| 14 | 1/1 | 1/1 | 145.590 | 379.142 |
| 15 | 0/0 | 0/0 | 144.464 | 311.028 |
| 16 | 1/1 | 1/1 | 138.257 | 308.745 |
| 17 | 1/1 | 1/1 | 187.479 | 342.666 |
| 18 | 1/1 | 1/1 | 141.004 | 325.539 |
| 19 | 1/1 | 1/1 | 188.492 | 313.259 |
| 20 | 1/1 | 1/1 | 144.219 | 330.065 |
| 21 | 1/1 | 1/1 | 142.153 | 445.777 |
| 22 | 0/0 | 0/0 | 143.423 | 337.513 |
| 23 | 1/1 | 1/1 | 149.550 | 418.829 |
| 24 | 1/1 | 1/1 | 140.626 | 324.060 |
| 25 | 1/1 | 1/1 | 138.422 | 332.206 |
| 26 | 1/1 | 1/1 | 133.406 | 396.538 |
| 27 | 1/1 | 1/1 | 139.514 | 385.442 |
| 28 | 1/1 | 1/1 | 139.333 | 384.384 |
| 29 | NOT EVALUATED: deadline before retrieval repository entry | NOT EVALUATED | — | — |
| 30–90 (each of these 61 cases) | NOT RUN | NOT RUN | — | — |

The remaining 62 cases are missing evaluation coverage, not 62 retrieval failures.
Their query embeddings remain saved. No complete 90-case comparison is claimed.

### Validation, retention and next boundary

Current focused command (backend working directory):

```text
.\.venv\Scripts\python.exe -B -m unittest test_canary_alternate_credential test_canary_durable_recovery test_canary_provider_recovery test_canary_real_handoff
```

**88/88 PASS, 45.922 seconds**, including 23 alternate-credential tests (eight
new exact-continuation cases). New tests cover exact inventory/default preservation,
probe-before-grant ordering, quota-stop behavior, forced no-retry client behavior,
seal/all-90-durable-before-evaluation ordering, query-failure stop, invalid query
inventory refusal, and retained database cleanup/connection-close delegation.

The complete canonical suite was **not rerun** because the instruction conditions
that rerun on completion of all 90 paired cases. The prior **3,739/3,739** baseline
is historical, not a fresh result for this continuation. No full-suite pass or
Phase P completion is claimed.

Final checks: **740/740 protected hashes unchanged; 880/880 bounded JSON artifacts
PASS; AST checks for all 16 changed/untracked Python files PASS; changed wrapper
and test imports PASS; secret-pattern scan across 897 changed/artifact files PASS;
git diff --check PASS; `.env` unchanged; all pre-existing implementation files
outside the two authorized wrapper/test changes preserved.** Git emits only
existing LF-to-CRLF conversion warnings, not whitespace errors. The runner process
is stopped; provider and database clients closed, and secret environment variables
were not persisted.

Retained expiry remains **2026-09-19 09:04:18 UTC / 14:34:18 IST** (approximately
15 hours 13 minutes remained at the final read-only verification). No TTL bypass,
schema deletion, marker deletion, cleanup/rebuild or automatic resume occurred.
The recorded recovery condition is PAUSED. All build/query receipts exist, so
remaining retrieval needs no new embeddings if identities/TTL continue to pass.
However, the current exact embedding-continuation entry point intentionally
expects the old staging inventory and is **not** a blind resume command for this
now-sealed state. A separately authorized evaluation-only continuation must honor
the existing seals, receipts, completed-case artifacts and TTL; none was implemented
or started here. Expired state must fail closed.

Evidence: ignored bounded artifacts under
`.codex_phase4p/canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6/`, especially
`result-4fc3262c806c4828a69abeeb13b64d5c.json`, its attempt/probe artifacts, and the
56 `case-01` through `case-28` lane artifacts. No raw vectors or credentials were
printed in these summaries.

No generation model, chatbot API, widget, production database/service, deployment,
crawl, customer ingestion, serving activation, commit or push was used. No new
phase was started. **Final decision remains C: bounded execution prevented full
measurement, with a concrete partial-set materialization regression also recorded.**

## Historical alternate-credential continuation decision — earlier 2026-09-18

**C — PHASE 4.1P — BLOCKED**

**Alternate credential: HTTP 429 / RESOURCE_EXHAUSTED / QUOTA_EXHAUSTED.**
The exact compatibility and quota probes passed, and the authorized continuation
persisted 1,028 additional legacy vectors. The next eight-input legacy batch
then exhausted its permitted initial attempt plus two retries. The runner exited
1 and retained all progress; no additional provider call or automatic restart
followed. Structured QuotaFailure metadata proves quota exhaustion, but the
quota window/tier/reset time was not retained and is not inferred.

**Current durable inventory: 1,030/1,030 structural + 1,076/1,092 legacy vectors.**
Only **16 legacy work items remain: eight UNKNOWN and eight pending**. All
**90 query embeddings remain pending; 0/90 paired retrieval cases ran**. Both
lanes remain EMBEDDING_STAGING, not INDEX_READY/CANARY_READ/COMPARATIVE_EVAL.
Full retrieval acceptance and readiness for chat/widget validation remain pending.

### Audit, scope and implementation

Starting/final HEAD remains `7ec2b891080051d6eddbc5f1746f0ea9c6641102`, branch
`main`. No commit, push or deployment. The previous recovery implementation and
its identity-bound files were preserved. Its recorded 315+ focused checks,
3,724/3,724 canonical result, real disposable PostgreSQL recovery proof and
433/433 bounded artifacts were audited. Recovery/provider/handoff rerun:
**65/65 PASS**, 44.383 seconds. Protected hashes: **740/740 unchanged**.

This continuation adds only:

- `backend/scripts/canary_alternate_credential.py`: an explicit retained-run
  wrapper with process-only alternate credential, exact compatibility gate,
  persisted quota probe and delayed seven-item spend grant.
- `backend/test_canary_alternate_credential.py`: 15 offline tests.
- Registration in `backend/scripts/test_scoped_rag_regressions.py`.
- This report.

The original recovery implementation hash, Gemini SDK/configuration module,
receipt format, schema, exact-generation seals and retrieval functions remain
unchanged. No serving Chunk.embedding, RAG, ingestion, model, query, source
corpus, FTS/RRF settings, candidate budgets, heading or materialization changes.

The supplied key was confirmed different from the existing development key.
Only **CANARY_GEMINI_API_KEY**, process-only, was supplied to the explicit SDK
client. No fallback to the existing key or alternate provider was permitted.
Operational label: **alternate-development-credential**. No key value, key hash,
reversible representation, authorization header or raw exception was recorded.

### Retained-run preflight — PASS

Before the alternate provider client was constructed, the normal resume gates
verified the exact target, namespace marker/OIDs/catalog, run, manifests,
generation/source/epoch identities, frozen M/chunk/query inventories, profile,
configuration, attestation, work ledger, recovery implementation and TTL.
Every one of the **1,078 existing completed vectors** passed full PostgreSQL
receipt/input/profile/provenance/f32/readback checks and was counted RESUMED_REUSE.
The initial state exactly matched 1,030 structural successes, 48 legacy successes,
seven legacy unknowns, 1,037 legacy pending and 90 query pending.

Namespace: `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`; run: `paired-real`.
Original approval remains `phase41p-recovery-real-20260918`.
Target fingerprint:
`f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
Independent resume identity remains:
`267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`.

### Exact credential compatibility — 3/3 PASS

Selection was the first three distinct completed structural inputs ordered by
document ID, entry ordinal and entry key, independent of retrieval/GOLD results.
One provider request, three inputs, **1,463 local tokens**, HTTP 200,
**922.000 ms**. No retry. Inputs were exact frozen UTF-8 text.

Provider: Gemini Developer API; `gemini-embedding-001`; profile v1;
`output_dimensionality=768`; no task type/title/prefix/extra normalization;
`vector-attestation-f32-v1`. For every sample, the retained and alternate results
had identical input hashes, canonical coordinates, all 3,072 f32 bytes and SHA-256.
No epsilon, rounding or cosine-similarity substitution was used. Probe vectors
were comparison-only and did not replace any retained vector.

| Input SHA-256 | Old and new canonical vector SHA-256 (identical) |
| --- | --- |
| `9e9a6679e3f12ca520582f10d675fde5ae1d2f3fcbf828d2e02a92314941e516` | `fcbea283c74c2e447c53f7c605cacdd01f5ca9b914fff0b8dfa13c57134d3384` |
| `0301eee17c6d1aa060dfd0b50ba15e62416da0dfa4b653a84b7c11b30caa2e9f` | `4e03191c463af62ac2e38a71abe4b6fa0c8750d498838cdc0adae4cb881af24f` |
| `7d2c572decf376c2b693f2a4572359b1d3a683ff72225b19b06fb504af5e719f` | `f4b187fec162930bc80991fa96d71c6d277402d60604026ebf7cef4ffb554cd3` |

Profile hash: `bd524bb94626d8d5f5282b286beffeb5fc806011685d18af16fa24619cc7e407`.
Configuration hash: `27286dd5851c8bab987365fb2619200d621390eac31c295d86eed9ad2e206628`.
This satisfies the prescribed three-sample continuation gate, not a universal
guarantee about all future provider outputs.

### Quota probe and original seven-item grant — PASS

The first pending legacy input not already covered by a validated receipt was
embedded once: **75 local tokens**, HTTP 200, **656.000 ms**, no retries.
Its actual legacy row was committed, readback-attested and marked complete; it
was not wasted or repeated by the later build.

Input hash: `316f9fd4a8a3936a4637f4fb14bf3155233d7f3b6dcc9cec1465d4896cef9a42`.
Vector hash: `f5a94b21fbb3c7d8c8da6bbafd7c47e5680fb99ac8b6d65f0af356fe325476ed`.

Only after both probes passed was the exact original seven-item grant enabled:
`8ce1188efdd29e7d8c3da577f38d5425d7a1ce1a75486da600d5eda59c290d76`,
reference `phase41p-alternate-key-20260918`. That batch completed. One identical
input reused the newly persisted quota-probe receipt; the other six required
new embeddings. The grant was not broadened to other UNKNOWN work.

### Provider usage by operational credential label

These figures cover the retained run's original build and this continuation,
not older historical runs whose schemas were cleaned.

| Measure | previous-development-credential | alternate-development-credential |
| --- | ---: | ---: |
| Attempts / successful / failed | 145 / 142 / 3 | 144 / 141 / 3 |
| Retries | 2 | 2 |
| Successful evidence outputs | 999 | 1,000 |
| Compatibility-only outputs included above | 0 | 3 |
| New persisted legacy rows this invocation | 48 | 1,028 |
| Reused pre-existing completed rows | 0 | 1,078 |
| Additional committed exact-input reuses | 79 | 31 |
| Successful local evidence tokens | 221,253 | 199,125 |
| Actual input submissions including failed retries | 1,020 | 1,024 |
| Actual local tokens including failed retries | 223,827 | 201,858 |
| Query embeddings | 0 | 0 |
| HTTP call time ms | 221,645.000 | 232,254.000 |
| Provider billed tokens / cost | UNKNOWN | UNKNOWN |

The alternate key's 1,000 successful outputs comprise three compatibility samples
and 997 new build receipts (including the quota probe); 997 + 31 validated reuses
accounts for the 1,028 additional legacy rows. The original 1,078 rows were not
regenerated, except for the three expressly authorized comparison probes.
Combined actual submissions are **2,044 inputs / 425,685 local tokens**, below
the unchanged 2,500-input / 500,000-local-token caps. Missing billed-token metadata
is unknown, never zero. These observed counts do not establish a quota reset time.

The last eight-input batch (911 local tokens per attempt) returned structured
QUOTA_EXHAUSTED on attempts **142/143/144**, durations **953/516/532 ms**,
HTTP 429 / RESOURCE_EXHAUSTED, no Retry-After header. Wrapper delays were two
and four seconds; SDK attempts=1. Final request started
**2026-09-18 12:27:29.183 UTC**. No request followed retry exhaustion.

### Current persistence, retention and safety

Post-exit read-only verification confirms:

- PROVIDER_HOLD; run and both manifests EMBEDDING_STAGING; no partial publication.
- **2,106 vectors**: 1,030 structural and 1,076 legacy; 3,242 atoms unchanged.
- Eight UNKNOWN + eight pending legacy rows; all 90 query rows pending.
- One original ownership marker, 289 total safe attempt records, one spend grant.
- Original identity and recovery-implementation hashes still match.
- Owned catalog unchanged; all 126 unrelated objects unchanged, catalog hash
  `5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
- Owned table/index/TOAST storage: **146,186,240 bytes**; canonical coordinate
  bytes across persisted vectors: **6,469,632**.
- Provider/DB resources and advisory lock closed; process-only alternate key
  and authorization/DSN variables cleared. The existing `.env` is unchanged.

Retained TTL is unchanged: **2026-09-19 09:04:18 UTC / 14:34:18 IST**.
No owned data was deleted. Expiry refuses resume/read; explicit owned cleanup
is still required for deletion. No automatic cleanup service was introduced.

The **new** eight-item work grant identity is:
`c5a064ee6485e4559cd49768d28ef8ab0311c6f0b3aca793fa3bdbaf6e648066`.
Its provider diagnostic batch hash is:
`f39af1f6292a53113f406e83bf62d62d6cd02585b6ef05ca0e6c515ac2441fb5`.
The earlier seven-item authorization does **not** authorize spending this batch.
Attempt-level client rejection is KNOWN_FAILURE; unfinished work conservatively
remains UNKNOWN until separately reviewed/authorized, not automatically reset.

### Retrieval, paired differences and real-vector security

**NOT RUN: both-lane seal, 90 query embeddings, all 90 paired retrieval cases,
and full-generation foreign/stale real-vector attacks.** No unauthorized-hit
count or semantic pass is fabricated from the unexecuted stages.

For **both** legacy and structural, the following remain NOT MEASURED: dense
span-hit recall @5/@10/@48; FTS @5/@10/@48; RRF @10/@48; materialized span recall;
required-document recall; duplicate evidence; source noise; candidate diversity;
lexical collapse; ATOM_ONLY; INCOMPLETE_BUDGET; QUERY_UNDERSTANDING_FAILURE;
foreign/stale hits. **Cases 1–90: no paired differences available.**
Unchanged GOLD remains 152 supporting spans, 109 unique exact occurrences,
43 mapping gaps and 90 review-required field associations. Gaps are not failures.
No answers, generation, /chat, widget, query rewrites or GOLD-driven rescue ran.

### Timing and final validation

Runner wall time: **4,414,107.434 ms / 73.568 minutes**, within the 300-minute
cap. No restaging was needed. Exclusive wall-time buckets:

| Bucket | Milliseconds | Wall share | SQL executions |
| --- | ---: | ---: | ---: |
| Source reconstruction | 60,397.936 | 1.368% | 0 |
| Vector persistence/readback, including reuse verification | 1,792,895.982 | 40.617% | 2,709 |
| Work ledger | 2,208,363.748 | 50.030% | 2,865 |
| Provider wait, including bounded delays | 242,007.274 | 5.483% | 0 |
| Other | 110,442.515 | 2.502% | 57 |
| Staging / seal / evaluation / cleanup | 0 | 0% | 0 |
| **Total** | **4,414,107.434** | **100%** | **5,631** |

HTTP time alone was 5.262% of wall time. SQL counts are DBAPI executions,
not packet-level round trips. No new transport/ranking tuning was made.

- New alternate-key tests: **15/15 PASS**, 0.431 seconds. They cover exact f32
  mismatch, bad profile/input/scope/digest, invalid vectors, bounded samples,
  no fresh-run mode, preflight-before-provider, compatibility/quota-before-grant,
  process-only credential/no existing-key fallback, secret clearing, actual
  persistence/readback/reuse of the quota input, and 429 immediate stop.
- Complete pre-provider canonical suite: **3,739/3,739 PASS**, 493.887 seconds,
  external network blocked. No implementation changed after that passing run.
- Post-retrieval canonical run: not reached because retrieval did not run;
  provider-hold STOP was honored rather than invoking another live attempt.
- Final protected hashes **740/740 unchanged**; all **721/721** Phase P JSON
  artifacts pass the bounded-output guard; **16/16** changed Python files pass
  AST/import checks; exact-secret scan has **zero matches**; `git diff --check`
  passes. The existing `.env` fingerprint is unchanged. Of the 15 pre-existing
  uncommitted files, only test-runner registration and this report changed;
  the other 13 are byte-identical. The new wrapper and tests bring the current
  intentionally uncommitted file count to 17.

**Exact next step:** obtain available Gemini embedding quota and separately
authorize continuation of this same retained identity, its current inventory,
the new eight-item spend grant, the remaining eight pending chunks and 90
queries, before TTL expiry. Reuse all 2,106 verified vectors. The initial
alternate-credential bootstrap command intentionally expects the old 48-legacy /
seven-unknown starting inventory and must not be blindly rerun on this new state.
A future authorized continuation must admit the exact new inventory and retain
all identity/source/receipt gates; no guards were weakened here. If the run
expires, stop for an explicit cleanup/rebuild decision. No commit/push/deploy.

---

## Historical provider recovery / durable resume continuation — 2026-09-18

**C — PHASE 4.1P — BLOCKED**

**Current blocker: Gemini HTTP 429 / RESOURCE_EXHAUSTED, with structured
QuotaFailure violations proving QUOTA_EXHAUSTED.** The seven-input legacy batch
failed on its initial attempt and both permitted retries. The runner stopped;
no additional provider attempt, automatic resume or deletion was performed.
The quota window/tier/reset time was not retained and is not inferred.

**Recovery succeeded at the live failure boundary:** 1,030/1,030 structural
vectors and 48/1,092 legacy vectors remain persisted and readback-verified.
Both lanes remain EMBEDDING_STAGING, not INDEX_READY/CANARY_READ. There are
seven unknown legacy work items, 1,037 pending legacy items and 90 pending query
embeddings. **0/90 paired retrieval cases completed.** No retrieval-quality
verdict or readiness for chat/widget validation is established.

The previously verified 15-file continuation was audited and committed **locally
only** as `7ec2b891080051d6eddbc5f1746f0ea9c6641102` —
`Phase 4.1P: add durable real embedding canary runner`. Audit rerun: 283/283 PASS,
740 protected hashes unchanged, 142 bounded artifacts valid, AST/secret/diff
checks PASS; 12 core canary read/seal methods unchanged. The two historical
3,689-test canonical results remain the recorded pre/post evidence for that
checkpoint. No push. All recovery changes described below remain uncommitted.

### Recovery validation completed before provider spend

- Installed SDK audit: google-genai 2.22.0 `APIError` / `ClientError` /
  `ServerError` provide structured `code`, `status`, `response.headers`, and
  `details`. No arbitrary exception text or response body is persisted.
- The frozen Gemini request module is unchanged. Profile hash remains
  `bd524bb94626d8d5f5282b286beffeb5fc806011685d18af16fa24619cc7e407`;
  configuration hash is separately
  `27286dd5851c8bab987365fb2619200d621390eac31c295d86eed9ad2e206628`.
- Safe attempt records include a started marker, exact input/batch hashes,
  local tokens, SDK class category, HTTP status, allowlisted provider enum,
  Retry-After, retryability, duration and consumption classification. Generic
  429 means RATE_LIMIT; QUOTA_EXHAUSTED requires structured QuotaFailure proof.
  Missing status remains unknown. The prior run's missing final status cannot
  be retrospectively recovered.
- SDK attempts=1; the recovery transport alone owns at most two retries.
  Invalid/auth/permission/response-validation errors do not retry. Retry-After
  is honored only within the execution deadline. Actual billed usage remains
  unknown when the provider supplies no usage counts.
- Retention is immutable and bounded to **24 hours**. Each explicitly approved
  invocation has a **maximum 300-minute execution window**. A partial build
  stays EMBEDDING_STAGING, with separate provider-hold bookkeeping; no partial
  read or publication. Both paired seals/publications commit atomically.
- Resume requires an explicit namespace, run, independent identity hash,
  target fingerprint, original approval reference, real-provider authorization,
  and resume authorization. It verifies marker/OIDs/catalog, exact manifests,
  source snapshots/epochs, inventories, M/query digests, profile/configuration,
  recovery implementation and work ledger. No latest-schema discovery.
- Every completed receipt is revalidated against PostgreSQL f32 bytes/digest,
  input, profile, provenance and scope before reuse. Unknown work is not reset
  to pending: a one-use, batch-specific spend grant must precede any reattempt.
  Source changes mark the run STALE. Expired runs cannot resume/read; explicit
  owned cleanup remains possible without corpus reconstruction or an API key.
- Fresh-process SQLite recovery tests cover 60/100, 99/100, first-batch failure,
  multiple cycles, commit-before-artifact process death, started-call process
  death, unknown-spend refusal, source epoch changes, wrong identity, expiry,
  corrupt readback, partial read refusal and atomic paired publication.
- Focused run: **315/315 PASS** before the final three additional assertions.
  Complete canonical suite: **3,723/3,723 PASS**, 495.544 seconds; one additional
  structural-transport equivalence regression subsequently passed. Post-stop
  canonical verification: **3,724/3,724 PASS**, 487.837 seconds, including all
  35 new recovery regressions (15 provider diagnostics + 20 durability tests).
- An initial orchestration-only network guard incorrectly blocked Windows'
  `_fallback_socketpair`: 11 failures out of 3,721, 503.318 seconds. The guard
  was corrected to permit that internal pipe only; no application code was
  changed for these failures. The clean canonical rerun above kept external
  network blocked and did not skip Docling.

### Real disposable PostgreSQL recovery proof — PASS

PostgreSQL **18.6**, pgvector **0.8.6**, namespace `public` for the extension.
**Zero provider calls.** Sixty mocked work units persisted, the connection/engine
closed, the exact named run reopened, all 60 receipts revalidated and reused,
and the remaining 40 completed. Inventory exactly 100 unique work/vector rows;
exact readback and seal PASS. Partial reads, missing unknown-work grants and
expired resumes REFUSED. Fresh-process crash boundaries were separately proven
by the SQLite tests, not falsely attributed to this PostgreSQL process.

Transport measurements with identical pre/post row/hash inventories:

| Fixture | Before | Batched | Equality |
| --- | ---: | ---: | --- |
| PostgreSQL eight-vector work/persist/readback | 53 executions | 18 executions | Exact row hash identical |
| SQLite 32-unit handoff, seal and inventory reads | 303 executions | 163 executions | Exact row hash identical |
| Structural source/node/entry/atom/member/span staging | 74 DBAPI parameter sets | 22 parameter sets | Exact row hash identical |

These are DBAPI execution/parameter-set counts, not packet-level measurements.
Only bounded multi-VALUES inserts, batched work updates and bulk readback changed;
constraints, transaction/savepoint boundaries, every receipt proof and the source
and publication gates remain enforced. No retrieval budget/ranking change.

Test schema `canary_stagep_eba1e5a020d64dd7b01e73f76da1ed5a` removed; all owned
tables/indexes/marker removed. All 126 unrelated catalog objects unchanged:
`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
Cleanup took 7,807.692 ms. Public vector extension retained.

### Fresh real run — stopped safely, progress retained

Explicitly authorized fresh namespace:
`canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`.
The one-input probe **PASS**: 768 dimensions / 3,072 canonical bytes;
input `9e9a6679e3f12ca520582f10d675fde5ae1d2f3fcbf828d2e02a92314941e516`,
vector `fcbea283c74c2e447c53f7c605cacdd01f5ca9b914fff0b8dfa13c57134d3384`.
The probe took **860.000 ms**, returned HTTP 200, and was persisted alone before
additional batches without a repeated provider call. P1's eight accepted inputs
and mechanical query were not repeated. Operational order remained structural
then legacy; neither lane received a different input/configuration treatment.

All 23 frozen documents, 1,030 structural entries and 3,242 atom projections
were staged. The legacy manifest/work inventory remains the same 1,092 frozen
chunks. The complete planned evidence inventory is 2,122 inputs / 429,324 local
tokens; no entries, queries, snapshots, GOLD, ranking or budgets were changed.
The 90 frozen unique query snapshots still hash to
`3337207fc25b1ab0788e30daca69bef8b12144a7d2e6980fd3cf7ae20cd42be7`.

| Live result | Measured value |
| --- | ---: |
| Structural persisted and verified | 1,030 / 1,030 |
| Legacy persisted and verified | 48 / 1,092 |
| Legacy unknown / pending | 7 / 1,037 |
| Query embeddings / paired retrieval cases | 0 / 0 |
| Provider attempts | 145 |
| Successful / failed attempts | 142 / 3 |
| Retries | 2 |
| New successful provider vectors | 999 |
| Reused committed exact-input vectors | 79 |
| Reused probe receipt | 1 (included in the build, not a second HTTP call) |
| Successful local evidence input tokens | 221,253 |
| All attempt input submissions, including retries | 1,020 |
| All attempt local tokens, including retries | 223,827 |
| Provider billed tokens / cost | UNKNOWN / UNKNOWN |
| Resume events during this run | 0 |

Both unique/logical work and actual attempt submissions remain below the
authorized 2,500-input / 500,000-local-token evidence caps. Provider token
counts were unavailable on all 145 attempts: the accumulator's numeric zero
is **not** evidence of zero billing. No query/generation/chat calls occurred.

The final three safe diagnostics are:

| Attempt | Retry | HTTP | Category | Provider enum | Inputs / local tokens | Duration ms |
| --- | ---: | ---: | --- | --- | --- | ---: |
| 143 | 0 | 429 | QUOTA_EXHAUSTED | RESOURCE_EXHAUSTED | 7 / 858 | 906.000 |
| 144 | 1 | 429 | QUOTA_EXHAUSTED | RESOURCE_EXHAUSTED | 7 / 858 | 531.000 |
| 145 | 2 | 429 | QUOTA_EXHAUSTED | RESOURCE_EXHAUSTED | 7 / 858 | 547.000 |

No Retry-After header was available; bounded policy delays were two and four
seconds. These explicit client rejections are classified KNOWN_FAILURE at the
attempt level; no vector exists for the seven work items, which conservatively
remain UNKNOWN in the durable work ledger and require an explicit spend grant.
This does not claim knowledge of billed consumption. The earlier historical
failure's lost HTTP status still cannot be retrospectively classified.

First request: **2026-09-18 09:04:24.758 UTC**. Final request started:
**2026-09-18 10:24:54.308 UTC**. Total runner wall time:
**4,909,845.101 ms (81.831 minutes)**, below the 300-minute deadline.

### Transport timing and storage

Exclusive wall buckets reconcile to total wall time within rounding. SQL counts
are DBAPI executions, not network packets; parameter-set total is 6,870.

| Bucket | Elapsed ms | Wall share | SQL executions |
| --- | ---: | ---: | ---: |
| Source reconstruction | 60,724.928 | 1.237% | 0 |
| Manifest preparation | 388,166.586 | 7.906% | 186 |
| Entry/atom staging | 533,427.682 | 10.864% | 393 |
| Membership/span staging | 72,289.550 | 1.472% | 199 |
| Provider wait, including bounded retry waits | 231,616.674 | 4.717% | 0 |
| Vector persistence/readback | 1,852,490.917 | 37.730% | 3,008 |
| Work-ledger operations | 1,727,297.273 | 35.180% | 2,462 |
| Seal | 0 | 0% | 0 |
| Query evaluation | 0 | 0% | 0 |
| Cleanup (intentionally retained) | 0 | 0% | 0 |
| Other | 43,831.514 | 0.893% | 83 |
| **Total** | **4,909,845.101** | **100%** | **6,331** |

Measured HTTP call time alone was **221,645.000 ms / 4.514%**. Database-side
transport/verification bookkeeping, not Gemini HTTP time, dominates elapsed
time. Fixture-based round-trip reductions above are proven equivalent; this
interrupted run is not a controlled end-to-end before/after speed benchmark.
No further optimization was made after the interruption.

Read-only post-stop storage inspection: **138,330,112 bytes** for owned table
storage including associated indexes/TOAST. The 1,078 verified 768-dimensional
vectors contain **3,311,616 canonical f32 bytes** before database overhead.

### Retention, safety and exact resume conditions

Read-only verification after process exit confirmed:

- Recovery condition PROVIDER_HOLD; run and both manifests EMBEDDING_STAGING.
- 1,030 structural vector rows, 48 legacy vector/member rows, 3,242 atoms,
  one ownership marker, 145 safe attempt records and zero spend grants.
- All 90 query-work rows pending; no lane seal/publication or paired evaluation.
- Saved identity and recovery-implementation hashes match current code.
- Owned catalog identity matches with the harness search path. All 126 unrelated
  objects remain unchanged, with catalog hash
  `5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
- Provider client, database connections and advisory lock were closed/released;
  process-only credentials/authorization variables were cleared.

The owned live schema is **intentionally retained, not cleaned**. Expiry:
**2026-09-19 09:04:18 UTC / 14:34:18 IST**. Expiry denies resume/read and makes
the exact owned run eligible for explicitly authorized cleanup; this does not
install an automatic cleanup service. The earlier mocked PostgreSQL recovery
fixture was cleaned successfully and is separate from this retained live run.

The live full-generation foreign/stale attack suite did **not** run, because
neither paired lane sealed. Its stronger real-vector security result is
**NOT MEASURED**, not a claimed zero. Prior P1 security acceptance and the
offline/owned-database partial-read refusal tests remain the available proof.

Exact future resume identity (not executed here):

- Namespace: `canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6`
- Run: `paired-real`
- Original approval: `phase41p-recovery-real-20260918`
- Target fingerprint: `f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`
- Independent resume identity: `267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2`
- Seven-item work retry grant: `8ce1188efdd29e7d8c3da577f38d5425d7a1ce1a75486da600d5eda59c290d76`
- Provider batch diagnostic hash (not the work grant): `26f73734210fe9947ae94bc07e892356934738885970c646e8acb174b05ae121`

With quota restored **and separate operator authorization before expiry**, use
the same explicitly approved disposable target/profile and process-only
CANARY_DATABASE_URL, CANARY_TARGET_FINGERPRINT, CANARY_ENVIRONMENT,
CANARY_APPROVAL_REFERENCE, CANARY_REAL_EMBEDDING_AUTHORIZED=true and
CANARY_RESUME_AUTHORIZED=true. From backend, the internal command is:

```powershell
.\.venv\Scripts\python.exe -B scripts/canary_recovery_runner.py resume --namespace canary_stagep_d29359d8b536465b8ef3d7af5ca5f1c6 --run-id paired-real --identity-hash 267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2 --retry-batch 8ce1188efdd29e7d8c3da577f38d5425d7a1ce1a75486da600d5eda59c290d76 --spend-reference <new-explicit-operator-approval> --deadline-minutes 300
```

This is conditional resume eligibility, not permission to bypass admission:
exact ownership, immutable identities, all source snapshots and every completed
f32 receipt must revalidate before any new spend. Reuse the 1,078 completed
vectors without provider regeneration. No automatic latest-run attachment,
unapproved unknown-work retry, provider switch or new probe was performed.

### Retrieval measurements and limitations

**NOT MEASURED in this run:** dense supporting-span hit recall @5/@10/@48;
FTS supporting-span hit recall @5/@10/@48; RRF hit recall @10/@48; materialized
span recall; required-document recall; duplicate evidence; source noise;
candidate diversity; lexical collapse; ATOM_ONLY; INCOMPLETE_BUDGET;
QUERY_UNDERSTANDING_FAILURE; foreign/stale hits; per-case paired differences.
No result is inferred from the successful embedding build. The historical
**43 GOLD mapping gaps remain gaps**, and **90 field associations remain
unreviewed**. There are no generated answers or false-absence/claim scores.

### Recovery files and final checks

Only isolated canary schema/transport/runner/test/report changes are included:

- `backend/database/canary_schema.py`
- `backend/scripts/canary_schema_migration.py`
- `backend/scripts/canary_real_repository.py`
- `backend/scripts/canary_real_embedding_retrieval.py`
- `backend/scripts/canary_provider_recovery.py` (new)
- `backend/scripts/canary_recovery_state.py` (new)
- `backend/scripts/canary_recovery_repository.py` (new)
- `backend/scripts/canary_recovery_runner.py` (new)
- `backend/scripts/canary_recovery_fixture.py` (new)
- `backend/scripts/canary_recovery_postgres.py` (new)
- `backend/scripts/canary_timing.py` (new)
- `backend/test_canary_provider_recovery.py` (new)
- `backend/test_canary_durable_recovery.py` (new)
- `backend/scripts/test_scoped_rag_regressions.py`
- This report.

Post-run canonical suite: **3,724/3,724 PASS**, 487.837 seconds, exit 0,
with external networking blocked. Protected hashes **740/740 unchanged**.
All **433/433** saved Phase P JSON artifacts pass the bounded-output guard;
largest live attempt diagnostic is 1,630 bytes. All **14/14 changed Python files**
pass AST and import checks; the changed-file secret scan has zero matches and
`git diff --check` passes. HEAD remains the local-only foundation
checkpoint `7ec2b891080051d6eddbc5f1746f0ea9c6641102`; recovery changes remain
uncommitted. No production access, serving RAG changes, corpus changes, crawl,
ingestion, re-embedding of an application corpus, generation, widget, push or
deployment. Frozen copied evidence was embedded only in the authorized canary.

**Exact next step:** restore provider quota and separately authorize the exact
retained-run resume and seven-item spend grant before its TTL expires. Otherwise
authorize owned cleanup. Full paired retrieval acceptance remains pending;
do not start end-to-end chat/widget validation or a later phase yet.

---

## Historical pre-recovery continuation decision — 2026-09-18 IST

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
