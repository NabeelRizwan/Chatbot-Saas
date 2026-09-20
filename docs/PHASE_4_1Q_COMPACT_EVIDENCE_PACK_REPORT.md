# Phase 4.1Q1 — Compact Exact Evidence Pack

## Status

**PHASE 4.1Q1 — ACCEPT (incremental compact-packing validation only).** The separately authorized case-73 structural recovery completed: **90/90 pairs, 180/180 successful lanes**. Exact upstream/replay parity, fresh **3,983/3,983** canonical tests and final preservation/security gates PASS. No previously delivered support was lost. **Not production-ready; broader retrieval deficiencies remain.**

## CASE 73 TARGETED RECOVERY — 2026-09-20

Authorization: **CASE73_STRUCTURAL_POST_OUTAGE_RECOVERY_20260920**. Same frozen Q1 family; no full-loop rerun, new family, implementation change or tuning.

- Starting branch/main checkpoint: 9bda2d5790449d271f56ba989ac2aabe3c3496a7. File-only checks verified exactly 89 pairs/179 lanes, missing only case 73 structural, valid saved case 73 legacy, all case/packing/pair checksums, upstream parity, 740 protected hashes, immutable Phase P and unchanged .env.
- Full read-only preflight revalidated approval/target/ownership, both sealed manifests, generation, source snapshots, corpus/vector inventories, all 90 saved query vectors, exact question/history and HardKnowledgeScope. Lease remained **2026-09-21 09:04:18 UTC**; no renewal or database write.
- Separate one-use admission retained the same query vector, Phase-P reference, first-48 routes, requested atom order, replay checksum, **131,072-byte budget and 48-unit cap**. Only the current in-memory deferred view was resolved; historical attempt/deferred files were not rewritten.
- New session: 23f06b5f96774f0b916a63618bc21492. Immutable attempt: overnight-attempt-73-STRUCTURAL_CANARY-23f06b5f96774f0b916a63618bc21492-2.json. The unchanged CompactCanary.evaluate_lane body ran **exactly once**. No other lane ran.
- Result: **COMPLETE**, no primary failure or cleanup errors. Case, packing, checksum, read summary, resolution receipt and pair 73 were saved normally.
- Pack: **41 units / 130,681 bytes**, 126 byte-cap exclusions, zero unit-cap exclusions, INCOMPLETE_BUDGET. Exact compact identities/order/bytes match replay. Pack SHA-256: 0f02ca3a9b50dbbe40aeb709d5dafdb6b0f977ef7a98f5ae47946fae703a1053.
- Case 73 mapped support and required-document scores are **0/0**, exactly as replay: no eligible mapped obligation exists for this case. Execution recovery is not evidence of answer quality for this question.
- New read-summary window: **1,683 SQL attempts; zero failed reads, retries, recoveries or backoff**; successful-read wall time 542,796 ms. Trace retrieval total 582,155.925 ms. Targeted window including closing checks 637.584 s; whole process including full preflight/preservation 1,440.201 s.
- Exact dense/FTS/RRF, scope/manifest/query and compact-replay parity: **PASS**. The unchanged saved case 73 legacy lane supplied the other half of pair 73: **90/90 pairs and 180/180 lanes**.
- Proofs in the existing family: case73-targeted-preflight.json, case73-targeted-authorization-consumed.json, case73-targeted-read-summary.json, case73-targeted-resolution.json and case73-targeted-attempt-result.json. The old outage remains historical/unscored; the new successful resolution is a separate immutable event.

## FINAL LIVE 90-CASE Q1 RESULT

Calculated from all 180 successful live artifacts, not assumed from replay. Evidence: q1-final-live-aggregation.json. All 90 pair checksums and 180 case/packing checksums validate.

### Phase P vs offline Q1 vs live Q1

Structural lane; recall denominators are eligible mapped obligations, not every possible fact.

| Metric | Phase P | Offline Q1 | Complete live Q1 |
|---|---:|---:|---:|
| Dense @5 | 75/109 | 75/109 | 75/109 |
| Dense @10 | 81/109 | 81/109 | 81/109 |
| Dense @48 | 96/109 | 96/109 | 96/109 |
| FTS @5 | 6/109 | 6/109 | 6/109 |
| FTS @10 | 6/109 | 6/109 | 6/109 |
| FTS @48 | 12/109 | 12/109 | 12/109 |
| RRF @10 | 84/109 | 84/109 | 84/109 |
| RRF @48 | 101/109 | 101/109 | 101/109 |
| Materialized support | 77/109 (70.6422%) | 89/109 | **89/109 (81.6514%)** |
| Required-document recall | 82/109 (75.2294%) | 91/109 | **91/109 (83.4862%)** |
| Duplicate evidence | 0/1,364 | 0/3,592 | 0/3,592 |
| Source-noise proxy | 164/1,182 (13.8748%) | 505/3,111 | 505/3,111 (16.2327%) |
| Candidate diversity, full-union distinct-document sum | 432 | Same upstream; full union not separately rescored | 432 |
| Lexical-collapse cases | 8/90 | Same upstream | 8/90 |
| ATOM_ONLY routes | 0 | Same upstream | 0 |
| INCOMPLETE_BUDGET | 90/90 | 90/90 | 90/90 |
| Model-facing bytes, min–max | 127,529–131,067 | 122,650–131,070 | 122,650–131,070 |
| Units, min–max | 5–20 | 20–48 | 20–48 |
| Byte-cap exclusions | 13,229 | 9,770 | 9,770 |
| Unit-cap exclusions | 0 | 1,231 | 1,231 |
| Cases reaching 48 units | 0 | 9 | 9 |

**Critical parity PASS:** all 180 lanes have exact Phase-P raw dense/FTS/first-48 RRF identities and scores, scopes, manifests and query identities. Channel/fusion code remains unchanged. All 90 structural packs match replay exactly in ordered atoms, byte count and pack checksum; every live per-case metric equals replay. **Discrepancies: NONE.** Full-union diversity/ATOM_ONLY diagnostics also equal the original values; bounded first-48 traces cannot independently reconstruct unseen tail diagnostics.

All 90 legacy outcomes/packs remain identical to Phase P: materialized support 79/109; required documents 104/109; dense @5/@10/@48 17/29/77 of 109; FTS 9/11/22; RRF @10/@48 35/79. No legacy lane was rerun in this task.

### Support inventory and explicit quality answers

All **12/12** replay-predicted byte-cap losses recovered live (case:obligation, document):
4:1 (27), 35:1 (23), 58:2 (31), 61:1 (25), 62:1 (23), 63:2 (25), 64:2 (29), 66:2 (24), 79:3 (25), 85:1 (29), 89:2 (24), 89:3 (25).

Remaining 12 original byte-cap losses:
30:2 (3), 51:2 (24), 52:2 (3), 52:3 (11), 52:4 (23), 52:5 (24), 52:6 (25), 55:2 (24), 60:2 (29), 63:1 (24), 65:1 (3), 86:2 (30).

1. Previously delivered Phase-P support lost: **0**.
2. Predicted recoveries realized live: **12/12**.
3. Additional live support beyond replay: **0**.
4. Predicted recoveries missing live: **0**.
5. Required-document recall: **82→91/109**, no per-case regression.
6. Source noise: **+2.3579 percentage points** (13.8748%→16.2327%). More supported evidence also brings more non-required-document evidence under this GOLD-relative proxy.
7. The 48-unit cap binds in **9 cases: 8, 48, 62, 70, 74, 76, 79, 80, 82**, producing 1,231 unit-cap exclusions. It is a new limiting factor in those cases.
8. Byte-cap exclusions remaining: **9,770**, a **26.1471% reduction**.
9. All **90/90** structural cases remain INCOMPLETE_BUDGET.
10. Compact provenance/security failures found: **0**.

There are still 20/109 unreturned mapped spans, two historical scope/query-understanding failures, 43 unchanged mapping gaps and 90 unreviewed field assignments. Structural support remains below legacy in cases **30, 52, 60** (previously seven cases). No generated-answer, field-completeness or false-absence claim is made.

The unchanged broad retrieval scorer still returns **B** for those remaining wider retrieval deficiencies. That value is preserved in the aggregation. The **A decision below concerns only incremental Q1 packing**, not overall retrieval acceptance or production readiness.

### Performance observations

Complete remote live structural measurements, milliseconds:

| Component | p50 | p95 |
|---|---:|---:|
| Dense | 2,182.537 | 2,352.145 |
| FTS | 1,704.514 | 2,421.938 |
| RRF | 0.243 | 0.388 |
| Evidence-reader wall | 456,352.022 | 616,874.784 |
| Materialization SQL wall | 502,668.000 | 639,932.000 |
| Serialization CPU | 640.625 | 968.750 |
| Materialization wall | 576,717.527 | 736,856.986 |
| Total retrieval | 583,184.629 | 744,729.007 |

These overlapping categories must not be added. Historical Phase-P structural materialization p50/p95 was 331,534.415/666,600.604 ms; live Q1 is slower in these observed cohorts. Different transport/execution periods prevent a controlled causal latency comparison. These are **not production latency**, and Q1 is not claimed to improve speed.

### Security, tests and preservation

All 180 Q1 artifacts passed the existing runtime validator against actual sealed manifests, query receipts, source/atom membership, HardKnowledgeScope, generation and budgets. Unauthorized organization/bot/stale-generation/stale-source results: **0**.

Five retained Phase-P attack families—foreign org, foreign bot, stale generation, stale source and identical text in another scope—were revalidated through immutable receipt checksums, unchanged seals/source identity and exact upstream parity. Each retains zero unauthorized dense/FTS/routing/materialization results. **No attack query was rerun.**

All 90 live compact hashes equal the replay that verified complete original sidecar recovery. Unauthorized provenance lookup and cross-tenant compact-reference resolution: **0 observed**. No live answer consumer exists here, so a separate live sidecar-consumer lookup was not invoked. Fresh additive tests exercise repository gates and reject foreign scope, stale source/generation/lifecycle, corrupted/missing references, payload changes and source races.


- Fresh canonical suite: **3,983/3,983 PASS**, standard runner summary **OK**, 538.554 s (540.225 s including wrapper overhead). The unchanged canonical suite was augmented in process with the two Q1 modules and overnight-controller module: 3,923 historical + 60 additive tests. No test/source registration file was edited.
- Validation-recording interruption disclosed: an initial observer wrongly assumed only one TestRunner result, but canonical tests invoke nested runners. Its post-suite recorder raised SUITE_RESULT_REQUIRED; that run is **UNCERTIFIED**, not counted as a pass or a test failure. The same suite was repeated with the original standard runner, producing the fresh certified result above. No implementation fix or live query was involved.
- **740/740 protected hashes unchanged**, including a post-canonical recheck; all **58,831 Phase-P namespace artifacts unchanged**, all 180 Phase-P lanes and 90 pair checksums intact.
- All **637 pre-existing Q1 result/history artifacts** pinned at task start remain byte-identical, including the original failed/deferred case-73 attempt. All 180 current case/packing proofs and 90 pair checksums pass.
- Bounded/secret audit: **401,463 Q1 artifacts** and 58,831 Phase-P artifacts validated at the full-audit snapshot; later generated summaries validated on creation/read. **0 secret hits; 0 pending artifacts; .env unchanged; process-only secret absent after completion.**
- AST/compile: **7/7 source/test files PASS**; changed-component imports **4/4 PASS**; git diff/whitespace checks PASS.
- Additional trace/admission audit: **180 lanes / 25,679 route records**, zero unauthorized/stale results; **181 historical admissions over 180 distinct lanes**, with the sole second admission being authorized case 73 structural. Every other lane remains single-attempt.
- Durable receipts: q1-final-canonical-suite.json, q1-final-suite-observer-interruption.json, q1-final-preservation-review.json and q1-final-security-execution-review.json.


### Final decision and checkpoint

**A — PHASE 4.1Q1 — ACCEPT**

COMPACT EXACT EVIDENCE PACK IMPROVES FINAL EVIDENCE DELIVERY

UPSTREAM RETRIEVAL IDENTICAL

PROVENANCE / SECURITY PRESERVED

READY FOR NEXT MEASURED RETRIEVAL ISSUE

**Not production-ready.** No serving activation or next phase is authorized by this decision.

The local-only completion checkpoint contains the already-existing overnight controller/tests and this report, on top of implementation checkpoint 9bda2d5790449d271f56ba989ac2aabe3c3496a7. Its SHA is recorded in the delivery and ignored completion receipt; a commit cannot contain its own SHA. No implementation source was edited during this targeted task.

No providers, embeddings, answer generation, customer/production database access, data/schema writes, extra renewal, other live benchmark-lane execution, push, deployment, FTS/scope/query repair, new materialization optimization or Q2. Connections closed; process-only disposable credential cleared and never printed/persisted.


## Historical overnight summary

The following historical sections preserve the pre-recovery outage and partial state. Their then-current authorization and incomplete counts are superseded only by the targeted recovery/final result above; they must not be used to restart the completed evaluator.

| Item | Observed result |
|---|---|
| Cases attempted / last attempted | 90/90 / case 90 |
| Successful pairs | 89/90: cases 1–72 and 74–90 |
| Successful lanes | 179/180: 89 structural, 90 legacy |
| Incomplete pair / deferred lane | Case 73 / `STRUCTURAL_CANARY` only |
| Deferred classification | `DEFERRED_EXECUTION_FAILURE`, `UNSCORED`; not zero recall/support |
| Provider calls | 0 |
| Successful transient read recoveries | 0 recorded recovery-success events |
| Permanent execution-deferred failures | 1; no deferred lane retried |
| Read-retry detail for missing lane | One retry, 1,000 ms backoff; replacement connection failed before diagnostic probes or bounded recovery exhaustion |
| Lease extended | YES, once: 2026-09-20 09:04:18 → 2026-09-21 09:04:18 UTC |
| Upstream parity failures | 0 across all 179 successful lanes |
| Security/provenance/pack failures | 0 observed; all saved scope checks, compact replay identities and packing checksums passed |
| Phase-P artifacts | UNCHANGED; final runner hash-inventory gate passed; 90 historical pair checksums intact |
| Protected files / environment | 740/740 unchanged; environment hash unchanged |
| Duplicate successful lane executions | 0; every lane has exactly one admission attempt |
| Final process / cleanup | Evaluator exited; final terminal `PARTIAL_DEFERRED`, no primary failure and no cleanup errors |
| Pending artifact writes | 0 |
| Final canonical suite / acceptance commit | NOT RUN / NOT CREATED, as required while deferred work remains |
| Existing implementation checkpoint | `9bda2d5790449d271f56ba989ac2aabe3c3496a7` (local only) |

**First and only lane to review later:** case 73 structural. Preserve its original attempt, failed-read trace, failure terminal and deferred review record. Diagnose the lost connection and conservative classification of the reconnect `OperationalError`; after separate authorization, validate retained identity/lease and rerun only the missing lane. Case 73 legacy is already successful and must not be rerun. Do not reuse the overnight skip-deferred run as a claim that this lane passed.

The user subsequently confirmed a temporary connection outage. No code, retrieval, packing, query, GOLD or vector tuning was performed in response. The interrupted restart also lost an ownership connection; read-only inspection later found the lock clear. The next unchanged restart passed full preflight and completed all later lanes. All 179 case/packing checksum pairs and 89 pair checksums were verified file-only at shutdown. No full-90 live quality scores are published: the 90-case replay figures below remain **offline replay**, not completed live acceptance. The terminal's inherited `decision: C`, `pairs_at_start: 90` and `reused_lanes: 180` describe historical Phase-P initialization, not Q1 acceptance; authoritative Q1 counts are 89/179.

Final safe review receipt: `overnight-final-partial-review.json` in the existing Q1 family. No further retrieval, deferred retry, provider activity, final commit, push, deployment or Q2 work is authorized by this completed overnight run.

## OVERNIGHT Q1 EXECUTION LOG

### Restart preflight interruption — 2026-09-20 11:22:45 UTC; reviewed 11:53 UTC

Session `03d9e96e594049b68052a6f05d329b5e` validated structural documents through 23, then lost its ownership connection while admitting document 24. The existing one-retry preflight path encountered `RETAINED_RUN_ALREADY_ACTIVE`; cleanup recorded `UNLOCK_SKIPPED_INVALID_CONNECTION`. No new evaluation lane was admitted, so this creates no additional deferred lane and does not change the saved 72 pairs / 144 lanes. The terminal's zero successful counts describe its unfinished preflight, not loss of existing artifacts.

A read-only lock-catalog check at the next heartbeat confirmed the expected retained identity and authorized extended expiry, with **zero current holders of the exact namespace advisory lock**. No lock bypass, backend termination, database mutation, or source change was performed. The previous owner could not be observed after the fact; the log establishes connection loss followed by lock refusal, not another active evaluator. A further restart of the unchanged controller is authorized to repeat necessary identity preflight and then continue case 73 legacy; case 73 structural remains deferred/unscored.

### Execution interruption — 2026-09-20 10:44:44 UTC; reviewed 11:15 UTC

At 72 complete pairs / 144 saved lanes, case 73 structural stopped during `split_atom_row`. Its scoped SELECT recorded a 19,281 ms transport failure and invalidated connection; the first recovery retry then failed inside `fresh_raw` / `psycopg2.connect` before replacement SQL. The classifier conservatively emitted `HARD_STOP` for that unclassified connection-establishment `OperationalError`. The specific network cause is **UNKNOWN** because driver text was safely suppressed; no identity, scope, upstream-parity or provenance guard fired. Cleanup also recorded a transport error.

Case 73 structural is now explicitly **DEFERRED_EXECUTION_FAILURE / UNSCORED**, not a quality zero: one retry, zero recoveries, 1,000 ms backoff, no independent probe reached, no lane or packing artifact saved. Partial materialization had started and the first-48 RRF parity gate had passed; final all-channel/pack validation had not completed. The original terminal/read diagnostics remain immutable. Review record: `overnight-deferred-73-STRUCTURAL_CANARY-interruption-review.json` in the existing Q1 family.

No source or retry-policy repair was made. The approved recovery action is to preserve all 144 successful lanes, run the existing full restart identity/artifact preflight, and resume **case 73 legacy**, followed by cases 74–90. The deferred structural lane must not be retried tonight. Restart admission and actual progress will be recorded below; this entry does not claim restart success yet. Since a lane is now deferred, no final acceptance verdict, full canonical suite or final Q1 acceptance commit is authorized tonight.

The operator's latest overnight instruction supersedes the interim case-20/six-hour stop. The same Q1 family is retained. No completed lane will be rerun. Execution-only failures are to be durably deferred/unscored; integrity, authorization, provenance, upstream-parity or provider-access failures remain hard stops. One bounded 24-hour retention extension is authorized only after the required full identity validation, with its audit kept in Q1 rather than Phase P.

- Initial bounded-session audit: 8 pairs / 17 lanes; case 9 legacy was active. The evaluator was not restarted.
- Local-only implementation checkpoint: `9bda2d5790449d271f56ba989ac2aabe3c3496a7`, containing only the five already-tested Q1 implementation/test files. Their working-byte hashes matched the tested versions; no implementation edit occurred. Nothing pushed.
- At the overnight instruction: 14 pairs / 28 successful lanes; case 15 structural was active. The superseded interim guard was verified by process ancestry and stopped before it had acquired or queued any database lock. The evaluator remained running. No lease change occurred.
- The frozen original evaluator remains active while a narrowly scoped same-family resume/defer/lease execution controller is prepared and validated. Packing, retrieval and read-recovery implementations are not being changed.
- Raw read/recovery records remain durable after each operation. Additional per-lane read-summary snapshots are derived locally without new database queries. The completed-subset/final metrics have not yet been calculated for this overnight instruction.

No overnight final acceptance decision has been made. Later entries will record any handoff, deferred lane, lease event and exact completion state.

### Overnight controller handoff — 2026-09-19 21:48:59 UTC

- Handoff completed at **16 pairs / 32 successful lanes**. The active case 16 legacy lane finished and saved normally. A queued existing namespace advisory lock then refused the original evaluator's next admission before any case 17 attempt/query. The original terminal's `RETAINED_RUN_ALREADY_ACTIVE` is this deliberate control handoff, not a retrieval-quality failure or deferred lane. Lock release was confirmed; no process was killed and no saved lane will be rerun.
- Execution-only same-family controller added in `backend/scripts/run_compact_evidence_overnight.py`, with `backend/test_compact_evidence_overnight.py`: **20/20 focused tests PASS** (0.422 s), AST/compile/import/secret/whitespace checks PASS. Original Q1 lane function and repository binding are inherited unchanged. All five original implementation/test files remain at their verified checkpoint; no packing, ranking, retrieval or recovery-policy edits.
- Startup preservation audit: 740/740 protected hashes unchanged; 58,974 Phase-P bounded artifacts validated; 90 Phase-P pair checksums intact; environment hash unchanged; secret scan zero hits. Full canonical suite intentionally not run before successful 90/90 live completion.
- New execution begins with full saved-artifact/source/vector preflight in the **same** Q1 folder. The explicitly authorized retention-only extension will be applied once after that validation because remaining execution is expected to exceed the old expiry. Extension is not claimed until its committed receipt exists.
- Controller uses immutable per-lane attempt/failure/checksum records, defers recognized exhausted execution failures without assigning quality zeros, and continues independent lanes. Permission/integrity/unclassified guard failures remain fail-closed. Partial orphan artifacts require review rather than being represented as success. Original Phase-P files remain read-only.
- A same-task 30-minute heartbeat (`finish-q1-overnight-validation`) is active for interruption recovery and final reporting. It does not execute retrieval while the existing evaluator is healthy. It must stop after the case-90 report or any integrity hard stop. No second lease renewal, deferred-lane retry, provider call, push, deployment or Q2 work is authorized.

Date: 2026-09-19 UTC.
Phase-P baseline/local HEAD: `2d9f04cb02c343fbb921ca63c31851d483f37d9c`, branch `main`.
Starting working tree clean. Phase P is closed and its report/results are not rewritten.

## Checkpoint and consumer audit

- Historical final receipt records 90 pairs, 180 lanes, 3,923 passing canonical tests, 740 protected hashes, and report working-byte SHA-256 `78508f8e2419b4c2bce5fbe506f816946f0016fa23ca59e775ab4bc9af71252f`.
- Initial audit verified all 90 pair checksums, 180 lane identities, 740 protected hashes and unchanged environment file.
- Replay hashed all 58831 files in the retained namespace before/after; all unchanged. The wider Phase-P audit inventory contains 58,974 bounded artifacts.
- Actual old materializer consumer is the canary evaluation runner. `score_case` uses scoped route/atom identities; `safe_trace` emits IDs/counts/timings, not source text. Existing mechanics tests inspect the exact evidence object.
- No serving/chat/generation consumer currently consumes this canary pack. Q1 defines and tests the exact future model-facing serialization; nothing was sent to an answer model. Serving context formatting was not changed.
- Old accounting summed canonical JSON bytes of each `evidence_view`, not the containing scorer-unit route/reason or a final model envelope. Q1 counts its whole actual designated context envelope.

## Implementation scope

Additive files:

- `backend/services/compact_evidence_pack.py`: compact contract, immutable request-local full-payload sidecar, fresh scoped provenance lookup, whole-atom materializer.
- `backend/scripts/replay_compact_evidence_pack.py`: file-only frozen request replay and post-selection scoring.
- `backend/scripts/run_compact_evidence_canary.py`: new Q1 result-family runner reusing Phase-P preflight, full-row attestation, read-only transport and original query function bytecode.
- `backend/test_compact_evidence_pack.py`: exactness, budgets, authorization and race tests.
- `backend/test_compact_evidence_canary.py`: binding/algorithm equivalence, result-family isolation and read-only gates.
- This report.

No existing application/retrieval/Phase-P source file was edited. The structural query function gets a private globals dictionary binding only `materialize`; its bytecode, defaults, SQL/channel/ranking functions and process-global bindings remain unchanged. Legacy still calls the original materializer. This is an internal experimental canary hook, not a serving activation.

## Pre-edit byte composition

The aggregate study completed before the first source edit. These are canonical UTF-8 JSON sizes, not token estimates. Text categories include JSON string encoding; syntax includes keys, separators and containers. Array-valued heading/table reference leaves fall under structural-other in this version of the partition; semantic headings themselves remain in source-part text. No raw corpus text is printed.

| Category (encoded leaf bytes; syntax assigned separately) | All 3,242 atoms | 797 previously included atoms | 49 byte-cap-lost candidate atoms |
|---|---:|---:|---:|
| atom_source_identity_values | 7024299 | 1640624 | 88377 |
| json_keys_separators_container_syntax | 13889051 | 3228974 | 172058 |
| node_text | 1325418 | 350348 | 14091 |
| provenance_values | 1832050 | 419632 | 21799 |
| semantic_attribute_values | 800897 | 171784 | 7498 |
| source_part_text | 1126745 | 312858 | 13058 |
| span_mapping_values | 1659613 | 391691 | 20768 |
| structural_other_values | 1284671 | 296409 | 13602 |
| structural_reference_values | 3044448 | 711282 | 38346 |
| Total | 31987192 | 7523602 | 389597 |

Both exact source-part and node text are retained. Their combined encoded values are 2,452,163 / 31,987,192 bytes across the corpus (7.666%). The remainder is not all removable: semantic attributes, local parent/header references, roles, completeness and quality remain model-facing. Routing manifest/generation is already outside the old payload; it is not falsely credited as an old-payload saving.

## Contracts, exactness and citations

Contract: `compact-evidence-pack-v1`.

The model-facing object is canonical JSON `{contract, units}`. Each unit contains the original atom ID, immutable provenance reference, document citation ID, atom kind, ordered source parts and ordered nodes.

Retained verbatim: every source-part text and node text; all local heading/table references; node ID/parent; node type and semantic role; all semantic attributes (commercial/quantity/timeline/link/list/table/cell); quality; part order/count; completeness flags; list indices. No string deduplication, text truncation, summarization or contextual-entry substitution occurs. Both node text and source-part text stay visible because one cannot be assumed to cover the other.

Out-of-band sidecar: complete original atomic payload (including source parts, nodes, full spans/mappings, canonical projection, provenance, source/version/crawl identity), payload digest, exact route, manifest, generation/profile and hard-scope identity. Records are frozen canonical bytes; the SHA-256 of the entire scoped record is the model-visible reference. Same text in another source/bot cannot reuse this identity.

Lookup accepts trusted manifest/hard scope separately from the reference. It freshly checks the existing repository read gate; checks reference integrity, manifest, hard scope and expected atom; reads the exact scoped original atom; checks byte equality/payload hash; and rechecks the read epoch before returning. References do not confer authorization. Returned dictionaries cannot mutate stored bytes.

All 3,242 frozen atoms passed exact source/node string and semantic-field projection checks. Every selected replay unit recovered its full original payload byte-for-byte and retained source/spans/order/citation/scorer identities. This proves the defined source-object contract, not final generated-answer behavior.

## Budget and selection

Unchanged: first 48 fused routes, lexical witness algorithm, repository child ordering, requested atom sequence, scoped deduplication, maximum 48 whole units, maximum 131,072 bytes.

Q1 counts exactly `len(serialize_pack(model_units))`: the contract envelope, atom/reference/citation labels, all exact strings/semantic fields, JSON escaping, commas and formatting. UTF-8 tests include non-ASCII scripts and emoji. No out-of-band sidecar bytes or backend-only scorer wrapper are sent in this serialization. No hidden second model context is claimed.

An overlarge whole unit is excluded, never truncated. The empty envelope itself must fit. Exclusions distinguish byte cap from unit cap without changing selection order.

## Offline replay (no dense, FTS or RRF execution)

Artifact family: `.codex_phase4q/compact-replay-48327d46b68048a0be6bd81eb19cc696`.

- 90/90 original packs reproduced exactly: ordered units and byte totals equal saved Phase P; original scorer metrics equal saved outcomes.
- Same saved scoped routes, frozen memberships and request order.
- Same unchanged evaluator runs only after selection; GOLD never enters packing.
- Previously included mapped support lost: **0**.
- Required-document per-case regressions: **0**.
- All 90 packs changed in representation/bytes; detailed table below.
- Rerun gate: **PASS**.

| Metric | Phase-P structural | Q1 offline replay |
|---|---:|---:|
| Dense @5 / @10 / @48 | 75 / 81 / 96 of 109 | Same saved inputs |
| FTS @5 / @10 / @48 | 6 / 6 / 12 of 109 | Same saved inputs |
| RRF @10 / @48 | 84 / 101 of 109 | Same saved inputs |
| Materialized support | 77/109 | 89/109 |
| Required-document recall | 82/109 | 91/109 |
| Duplicate evidence | 0/1364 | 0/3592 |
| Source-noise proxy | 164/1182 (13.8748%) | 505/3111 (16.2327%) |
| INCOMPLETE_BUDGET cases | 90/90 | 90/90 |
| Byte-cap excluded unique requests | 13,229 | 9,770 |
| Unit-cap excluded unique requests | 0 | 1,231 |
| Cases reaching 48-unit cap | 0 | 9 |
| Pack bytes range | 127,529–131,067 | 122,650–131,070 |
| Units range | 5–20 | 20–48 |

Byte-cap exclusions decrease 26.1471%. More support is delivered but the noise proxy rises; this is not presented as an improvement on every metric. It is span-hit scoring, not proof of field completeness. The 43 historical mapping gaps and unreviewed field assignments are unchanged.

## Original 24 byte-cap losses

Recovered 12 (case: mapped-obligation ordinal): 4:1 (doc 27), 35:1 (doc 23), 58:2 (doc 31), 61:1 (doc 25), 62:1 (doc 23), 63:2 (doc 25), 64:2 (doc 29), 66:2 (doc 24), 79:3 (doc 25), 85:1 (doc 29), 89:2 (doc 24), 89:3 (doc 25).

Still absent 12: 30:2 (doc 3), 51:2 (doc 24), 52:2 (doc 3), 52:3 (doc 11), 52:4 (doc 23), 52:5 (doc 24), 52:6 (doc 25), 55:2 (doc 24), 60:2 (doc 29), 63:1 (doc 24), 65:1 (doc 3), 86:2 (doc 30).

No scope/channel/FTS fix or selection-policy tuning was made to address these. Cases 53/54 and the no-channel misses remain separate issues.

## Every changed case — offline only

Support and document numbers below are numerators; the unchanged per-case denominators remain in JSON artifacts.

| Case | Support P → Q1 | Required docs P → Q1 | Bytes P → Q1 | Units P → Q1 | Q1 exclusions: bytes / units |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 → 1 | 1 → 1 | 130267 → 130954 | 16 → 42 | 131 / 0 |
| 2 | 1 → 1 | 1 → 1 | 130924 → 130949 | 18 → 38 | 140 / 0 |
| 3 | 1 → 1 | 1 → 1 | 130621 → 131004 | 8 → 32 | 137 / 0 |
| 4 | 0 → 1 | 1 → 1 | 130824 → 131043 | 8 → 30 | 148 / 0 |
| 5 | 1 → 1 | 1 → 1 | 130572 → 130480 | 14 → 39 | 122 / 0 |
| 6 | 1 → 1 | 1 → 1 | 129929 → 130711 | 14 → 42 | 119 / 0 |
| 7 | 1 → 1 | 1 → 1 | 130724 → 131034 | 15 → 38 | 132 / 0 |
| 8 | 1 → 1 | 1 → 1 | 130338 → 122650 | 16 → 48 | 0 / 113 |
| 9 | 1 → 1 | 1 → 1 | 130526 → 130759 | 16 → 44 | 142 / 0 |
| 10 | 1 → 1 | 1 → 1 | 130804 → 130539 | 11 → 37 | 140 / 0 |
| 11 | 1 → 1 | 1 → 1 | 128579 → 129726 | 14 → 42 | 110 / 0 |
| 12 | 1 → 1 | 1 → 1 | 130695 → 130810 | 20 → 41 | 124 / 0 |
| 13 | 1 → 1 | 1 → 1 | 129838 → 130419 | 16 → 46 | 124 / 0 |
| 14 | 1 → 1 | 1 → 1 | 129213 → 130628 | 17 → 42 | 124 / 0 |
| 15 | 0 → 0 | 0 → 0 | 129973 → 130491 | 12 → 36 | 117 / 0 |
| 16 | 1 → 1 | 1 → 1 | 127529 → 130214 | 15 → 38 | 113 / 0 |
| 17 | 1 → 1 | 1 → 1 | 130818 → 130589 | 17 → 40 | 122 / 0 |
| 18 | 1 → 1 | 1 → 1 | 130032 → 130994 | 13 → 32 | 134 / 0 |
| 19 | 1 → 1 | 1 → 1 | 130912 → 130547 | 19 → 36 | 117 / 0 |
| 20 | 1 → 1 | 1 → 1 | 130555 → 130940 | 17 → 43 | 117 / 0 |
| 21 | 1 → 1 | 1 → 1 | 130416 → 131020 | 16 → 36 | 135 / 0 |
| 22 | 0 → 0 | 0 → 0 | 129974 → 130794 | 16 → 36 | 125 / 0 |
| 23 | 1 → 1 | 1 → 1 | 128537 → 130192 | 15 → 36 | 115 / 0 |
| 24 | 1 → 1 | 1 → 1 | 130107 → 130974 | 15 → 38 | 122 / 0 |
| 25 | 1 → 1 | 1 → 1 | 129858 → 130641 | 16 → 45 | 131 / 0 |
| 26 | 1 → 1 | 1 → 1 | 128537 → 131031 | 15 → 39 | 135 / 0 |
| 27 | 1 → 1 | 1 → 1 | 129662 → 130864 | 19 → 40 | 135 / 0 |
| 28 | 1 → 1 | 1 → 1 | 130976 → 130830 | 16 → 44 | 153 / 0 |
| 29 | 0 → 0 | 0 → 0 | 129954 → 130693 | 14 → 33 | 134 / 0 |
| 30 | 1 → 1 | 1 → 1 | 130768 → 130322 | 17 → 42 | 123 / 0 |
| 31 | 1 → 1 | 1 → 1 | 129484 → 131060 | 18 → 35 | 126 / 0 |
| 32 | 1 → 1 | 1 → 1 | 130140 → 130992 | 16 → 38 | 133 / 0 |
| 33 | 1 → 1 | 1 → 1 | 129587 → 130043 | 12 → 37 | 126 / 0 |
| 34 | 1 → 1 | 1 → 1 | 131009 → 131070 | 17 → 39 | 107 / 0 |
| 35 | 0 → 1 | 1 → 1 | 130796 → 131011 | 5 → 20 | 151 / 0 |
| 36 | 1 → 1 | 1 → 1 | 129479 → 131022 | 18 → 42 | 115 / 0 |
| 37 | 1 → 1 | 1 → 1 | 130925 → 130130 | 16 → 38 | 131 / 0 |
| 38 | 0 → 0 | 0 → 0 | 128648 → 130592 | 10 → 35 | 131 / 0 |
| 39 | 1 → 1 | 1 → 1 | 129858 → 130488 | 16 → 42 | 127 / 0 |
| 40 | 1 → 1 | 1 → 1 | 128528 → 130723 | 6 → 43 | 109 / 0 |
| 41 | 1 → 1 | 1 → 1 | 129728 → 130606 | 18 → 45 | 120 / 0 |
| 42 | 1 → 1 | 1 → 1 | 129438 → 130853 | 19 → 45 | 79 / 0 |
| 43 | 1 → 1 | 1 → 1 | 130989 → 130360 | 18 → 39 | 94 / 0 |
| 44 | 1 → 1 | 1 → 1 | 130765 → 130993 | 15 → 40 | 112 / 0 |
| 45 | 1 → 1 | 1 → 1 | 129952 → 130713 | 10 → 37 | 65 / 0 |
| 46 | 1 → 1 | 1 → 1 | 129151 → 131003 | 13 → 41 | 73 / 0 |
| 47 | 1 → 1 | 1 → 1 | 130241 → 130651 | 16 → 45 | 57 / 0 |
| 48 | 1 → 1 | 1 → 1 | 129599 → 129166 | 17 → 48 | 0 / 79 |
| 49 | 1 → 1 | 1 → 1 | 129481 → 130665 | 16 → 37 | 83 / 0 |
| 50 | 1 → 1 | 1 → 1 | 129937 → 130538 | 14 → 41 | 95 / 0 |
| 51 | 1 → 1 | 1 → 1 | 129743 → 130818 | 14 → 42 | 134 / 0 |
| 52 | 2 → 2 | 3 → 4 | 130400 → 130466 | 8 → 32 | 186 / 0 |
| 53 | 1 → 1 | 1 → 1 | 129927 → 131045 | 15 → 38 | 31 / 0 |
| 54 | 0 → 0 | 0 → 0 | 130622 → 130820 | 19 → 42 | 27 / 0 |
| 55 | 1 → 1 | 1 → 1 | 128860 → 130356 | 17 → 39 | 192 / 0 |
| 56 | 2 → 2 | 2 → 2 | 128967 → 130876 | 18 → 41 | 110 / 0 |
| 57 | 2 → 2 | 2 → 2 | 128576 → 130879 | 19 → 37 | 134 / 0 |
| 58 | 1 → 2 | 1 → 2 | 130088 → 131037 | 18 → 41 | 122 / 0 |
| 59 | 1 → 1 | 1 → 1 | 129971 → 130824 | 15 → 37 | 94 / 0 |
| 60 | 1 → 1 | 1 → 1 | 131067 → 130830 | 7 → 32 | 144 / 0 |
| 61 | 1 → 2 | 1 → 2 | 129527 → 130804 | 18 → 47 | 122 / 0 |
| 62 | 1 → 2 | 1 → 2 | 129407 → 128276 | 19 → 48 | 1 / 102 |
| 63 | 0 → 1 | 0 → 1 | 130919 → 130291 | 16 → 46 | 60 / 0 |
| 64 | 1 → 2 | 1 → 2 | 129435 → 130369 | 18 → 47 | 98 / 0 |
| 65 | 1 → 1 | 1 → 1 | 129779 → 131069 | 16 → 39 | 90 / 0 |
| 66 | 1 → 2 | 1 → 2 | 130923 → 130542 | 15 → 40 | 121 / 0 |
| 67 | 1 → 1 | 1 → 1 | 130401 → 130768 | 15 → 32 | 129 / 0 |
| 68 | 1 → 1 | 1 → 1 | 128662 → 130498 | 14 → 40 | 124 / 0 |
| 69 | 1 → 1 | 1 → 1 | 130983 → 131038 | 14 → 36 | 113 / 0 |
| 70 | 1 → 1 | 1 → 1 | 129017 → 123967 | 20 → 48 | 0 / 68 |
| 71 | 0 → 0 | 0 → 0 | 129557 → 130602 | 16 → 42 | 153 / 0 |
| 72 | 0 → 0 | 0 → 0 | 130181 → 130806 | 17 → 40 | 138 / 0 |
| 73 | 0 → 0 | 0 → 0 | 130183 → 130681 | 17 → 41 | 126 / 0 |
| 74 | 1 → 1 | 1 → 1 | 130944 → 127529 | 15 → 48 | 0 / 236 |
| 75 | 1 → 1 | 1 → 1 | 130555 → 129951 | 17 → 46 | 114 / 0 |
| 76 | 1 → 1 | 1 → 1 | 129252 → 130790 | 16 → 48 | 0 / 122 |
| 77 | 1 → 1 | 1 → 1 | 130176 → 130697 | 15 → 37 | 136 / 0 |
| 78 | 1 → 1 | 1 → 1 | 129736 → 130911 | 15 → 34 | 147 / 0 |
| 79 | 2 → 3 | 3 → 3 | 130783 → 126509 | 13 → 48 | 0 / 164 |
| 80 | 0 → 0 | 0 → 0 | 130360 → 128957 | 16 → 48 | 0 / 180 |
| 81 | 0 → 0 | 0 → 0 | 130764 → 130617 | 16 → 40 | 129 / 0 |
| 82 | 0 → 0 | 0 → 0 | 130837 → 130836 | 16 → 48 | 2 / 167 |
| 83 | 0 → 0 | 0 → 0 | 129089 → 131037 | 17 → 44 | 184 / 0 |
| 84 | 1 → 1 | 1 → 1 | 130265 → 130743 | 12 → 31 | 145 / 0 |
| 85 | 0 → 1 | 0 → 1 | 129121 → 130472 | 11 → 44 | 125 / 0 |
| 86 | 1 → 1 | 1 → 1 | 128872 → 130895 | 18 → 43 | 125 / 0 |
| 87 | 0 → 0 | 0 → 0 | 129341 → 129802 | 15 → 38 | 111 / 0 |
| 88 | 1 → 1 | 1 → 1 | 131059 → 130265 | 19 → 44 | 113 / 0 |
| 89 | 1 → 3 | 2 → 3 | 130354 → 130634 | 7 → 21 | 112 / 0 |
| 90 | 1 → 1 | 1 → 1 | 131045 → 130520 | 16 → 41 | 123 / 0 |

## Security and anti-overfitting

Historical five attack families are retained: foreign org, foreign bot, stale generation, stale source and identical text in another scope. The immutable Phase-P security receipt reports zero unauthorized dense/FTS/routing/materialization results for each.

New tests exercise the actual in-memory SQL repository/gates, not just mocked permission booleans: foreign hard org/bot/docs/versions, foreign same-text bot, stale source/lifecycle/manifest/generation, wrong atom/route, changed/corrupt payload, missing/corrupt reference and concurrent source-fingerprint/epoch changes all fail closed. Normal complete original payload lookup succeeds.

New materializer source scan forbids benchmark/product identifiers, GOLD fields and query/ranker hooks. It uses no case IDs, site/product names, required-document heuristics, support IDs or benchmark questions. Benchmark IDs appear only in post-selection evaluation artifacts/report.

## Performance

Offline local CPU/file replay, NOT remote or production latency:

- Serialization CPU p50 125.000 ms; p95 203.125 ms; total 10796.875 ms.
- Local evidence-reader wall p50 17.924 ms; p95 30.788 ms.
- Materialization wall p50 150.688 ms; p95 227.331 ms.
- Database time: 0 ms (no DB accessed by replay).
- Whole replay: 138.773 seconds, including reconstruction, hashing and audits.

Real rerun records SQL read wall, evidence-reader wall, serialization CPU, materialization wall, pack bytes and units separately. These are overlapping categories, not values to sum. No causal latency claim versus historical Phase-P transport cohorts is authorized.

## Real paired rerun

STOPPED — partial completion, 89 pairs / 179 lanes. Existing family: `.codex_phase4q/REAL_CORPUS_V1_EVAL_V1_PHASE4Q1-90aed10d99f2463b9cd94c1bbd2e1541`.

Original owned disposable schema/manifests remain unchanged. The original runner allowed no DB writes; the later explicitly authorized overnight controller changed only the two owned expiry columns once, with Q1-only prepared/committed audit records. Per-lane gates require exact saved upstream identities/scores and original legacy packs; structural pack hashes/order/bytes must equal replay. An upstream mismatch stops the run.

Historical initial progress snapshot (2026-09-19, approximately 19:40 UTC): 6/90 pairs complete, case 7 structural lane running. Superseded by the final summary above. All successful lanes passed upstream parity; structural packs matched offline replay and legacy packs matched Phase P.

The operator subsequently authorized one 24-hour extension. Its committed receipt confirms expiry 2026-09-21 09:04:18 UTC. No second renewal occurred. Final acceptance and full canonical validation are withheld because one lane remains deferred.

## Validation and final checkpoint

Focused offline: **40/40 PASS** (19.412 seconds).
AST/import: **5/5 PASS**. Diff whitespace check PASS at preflight.

Execution-controller focused tests: **20/20 PASS** (0.422 seconds); AST/import/compile/whitespace checks PASS. These are separate from the earlier 40/40 Q1 tests.
Fresh complete canonical suite: **NOT RUN**, per the deferred-lane stop rule.
Final protected hashes/environment/secret scan: **PASS**; 740 unchanged, no secret hits.
Final local HEAD remains the implementation checkpoint `9bda2d5790449d271f56ba989ac2aabe3c3496a7`. No final acceptance commit, push or deployment.

## Boundaries

No provider calls, new embeddings, answer generation, chat/widget, production/customer database access, corpus changes, schema writes, source discovery, ranking/FTS/scope/query/prompt changes, deployment or push. Phase P remains immutable. Q2 is not started.

- OVERNIGHT Q1 EXECUTION LOG: `{"deferred_lanes": 0, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "OVERNIGHT_RESUMED", "next_lane": {"case": 17, "lane": "STRUCTURAL_CANARY"}, "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 32, "successful_pairs": 16, "timestamp": 1789855388}`

- OVERNIGHT Q1 EXECUTION LOG: `{"identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LEASE_EXTENDED", "new_retained_until": 1789981458, "old_retained_until": 1789895058, "provider_calls": 0, "reason": "ACTIVE_PHASE_4_1Q1_90_CASE_EVALUATION", "session": "59ecd01b6f934be5be76fae5ba385530", "timestamp": 1789855423}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 17, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 33, "successful_pairs": 16, "timestamp": 1789856029}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 17, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 34, "successful_pairs": 17, "timestamp": 1789856267}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 18, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 35, "successful_pairs": 17, "timestamp": 1789856881}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 18, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 36, "successful_pairs": 18, "timestamp": 1789857122}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 19, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 37, "successful_pairs": 18, "timestamp": 1789857712}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 19, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 38, "successful_pairs": 19, "timestamp": 1789857949}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 20, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 39, "successful_pairs": 19, "timestamp": 1789858559}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 20, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 40, "successful_pairs": 20, "timestamp": 1789858796}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 21, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 41, "successful_pairs": 20, "timestamp": 1789859431}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 21, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 42, "successful_pairs": 21, "timestamp": 1789859670}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 22, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 43, "successful_pairs": 21, "timestamp": 1789860294}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 22, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 44, "successful_pairs": 22, "timestamp": 1789860531}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 23, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 45, "successful_pairs": 22, "timestamp": 1789861111}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 23, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 46, "successful_pairs": 23, "timestamp": 1789861347}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 24, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 47, "successful_pairs": 23, "timestamp": 1789861956}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 24, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 48, "successful_pairs": 24, "timestamp": 1789862185}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 25, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 49, "successful_pairs": 24, "timestamp": 1789862832}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 25, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 50, "successful_pairs": 25, "timestamp": 1789863068}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 26, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 51, "successful_pairs": 25, "timestamp": 1789863719}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 26, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 52, "successful_pairs": 26, "timestamp": 1789863961}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 27, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 53, "successful_pairs": 26, "timestamp": 1789864610}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 27, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 54, "successful_pairs": 27, "timestamp": 1789864844}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 28, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 55, "successful_pairs": 27, "timestamp": 1789865566}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 28, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 56, "successful_pairs": 28, "timestamp": 1789865806}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 29, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 57, "successful_pairs": 28, "timestamp": 1789866423}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 29, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 58, "successful_pairs": 29, "timestamp": 1789866665}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 30, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 59, "successful_pairs": 29, "timestamp": 1789867292}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 30, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 60, "successful_pairs": 30, "timestamp": 1789867532}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 31, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 61, "successful_pairs": 30, "timestamp": 1789868146}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 31, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 62, "successful_pairs": 31, "timestamp": 1789868383}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 32, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 63, "successful_pairs": 31, "timestamp": 1789869015}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 32, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 64, "successful_pairs": 32, "timestamp": 1789869250}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 33, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 65, "successful_pairs": 32, "timestamp": 1789869867}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 33, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 66, "successful_pairs": 33, "timestamp": 1789870108}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 34, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 67, "successful_pairs": 33, "timestamp": 1789870672}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 34, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 68, "successful_pairs": 34, "timestamp": 1789870909}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 35, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 69, "successful_pairs": 34, "timestamp": 1789871550}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 35, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 70, "successful_pairs": 35, "timestamp": 1789871785}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 36, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 71, "successful_pairs": 35, "timestamp": 1789872372}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 36, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 72, "successful_pairs": 36, "timestamp": 1789872609}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 37, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 73, "successful_pairs": 36, "timestamp": 1789873243}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 37, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 74, "successful_pairs": 37, "timestamp": 1789873480}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 38, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 75, "successful_pairs": 37, "timestamp": 1789874103}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 38, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 76, "successful_pairs": 38, "timestamp": 1789874342}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 39, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 77, "successful_pairs": 38, "timestamp": 1789874966}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 39, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 78, "successful_pairs": 39, "timestamp": 1789875201}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 40, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 79, "successful_pairs": 39, "timestamp": 1789875794}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 40, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 80, "successful_pairs": 40, "timestamp": 1789876030}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 41, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 81, "successful_pairs": 40, "timestamp": 1789876639}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 41, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 82, "successful_pairs": 41, "timestamp": 1789876880}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 42, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 83, "successful_pairs": 41, "timestamp": 1789877373}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 42, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 84, "successful_pairs": 42, "timestamp": 1789877609}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 43, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 85, "successful_pairs": 42, "timestamp": 1789878191}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 43, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 86, "successful_pairs": 43, "timestamp": 1789878428}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 44, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 87, "successful_pairs": 43, "timestamp": 1789879007}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 44, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 88, "successful_pairs": 44, "timestamp": 1789879244}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 45, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 89, "successful_pairs": 44, "timestamp": 1789879679}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 45, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 90, "successful_pairs": 45, "timestamp": 1789879917}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 46, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 91, "successful_pairs": 45, "timestamp": 1789880376}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 46, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 92, "successful_pairs": 46, "timestamp": 1789880617}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 47, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 93, "successful_pairs": 46, "timestamp": 1789881056}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 47, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 94, "successful_pairs": 47, "timestamp": 1789881305}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 48, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 95, "successful_pairs": 47, "timestamp": 1789881599}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 48, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 96, "successful_pairs": 48, "timestamp": 1789881837}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 49, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 97, "successful_pairs": 48, "timestamp": 1789882325}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 49, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 98, "successful_pairs": 49, "timestamp": 1789882565}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 50, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 99, "successful_pairs": 49, "timestamp": 1789883106}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 50, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 100, "successful_pairs": 50, "timestamp": 1789883348}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 51, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 101, "successful_pairs": 50, "timestamp": 1789883999}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 51, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 102, "successful_pairs": 51, "timestamp": 1789884235}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 52, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 103, "successful_pairs": 51, "timestamp": 1789885005}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 52, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 104, "successful_pairs": 52, "timestamp": 1789885241}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 53, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 105, "successful_pairs": 52, "timestamp": 1789885545}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 53, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 106, "successful_pairs": 53, "timestamp": 1789885706}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 54, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 107, "successful_pairs": 53, "timestamp": 1789886007}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 54, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 108, "successful_pairs": 54, "timestamp": 1789886167}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 55, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 109, "successful_pairs": 54, "timestamp": 1789886963}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 55, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 110, "successful_pairs": 55, "timestamp": 1789887200}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 56, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 111, "successful_pairs": 55, "timestamp": 1789887781}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 56, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 112, "successful_pairs": 56, "timestamp": 1789888018}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 57, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 113, "successful_pairs": 56, "timestamp": 1789888662}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 57, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 114, "successful_pairs": 57, "timestamp": 1789888939}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 58, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 115, "successful_pairs": 57, "timestamp": 1789889558}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 58, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 116, "successful_pairs": 58, "timestamp": 1789889789}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 59, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 117, "successful_pairs": 58, "timestamp": 1789890304}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 59, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 118, "successful_pairs": 59, "timestamp": 1789890548}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 60, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 119, "successful_pairs": 59, "timestamp": 1789891201}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 60, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 120, "successful_pairs": 60, "timestamp": 1789891444}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 61, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 121, "successful_pairs": 60, "timestamp": 1789892075}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 61, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 122, "successful_pairs": 61, "timestamp": 1789892310}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 62, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 123, "successful_pairs": 61, "timestamp": 1789892599}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 62, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 124, "successful_pairs": 62, "timestamp": 1789892839}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 63, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 125, "successful_pairs": 62, "timestamp": 1789893300}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 63, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 126, "successful_pairs": 63, "timestamp": 1789893539}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 64, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 127, "successful_pairs": 63, "timestamp": 1789894097}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 64, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 128, "successful_pairs": 64, "timestamp": 1789894331}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 65, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 129, "successful_pairs": 64, "timestamp": 1789894838}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 65, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 130, "successful_pairs": 65, "timestamp": 1789895076}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 66, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 131, "successful_pairs": 65, "timestamp": 1789895675}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 66, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 132, "successful_pairs": 66, "timestamp": 1789895905}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 67, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 133, "successful_pairs": 66, "timestamp": 1789896518}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 67, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 134, "successful_pairs": 67, "timestamp": 1789896758}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 68, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 135, "successful_pairs": 67, "timestamp": 1789897372}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 68, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 136, "successful_pairs": 68, "timestamp": 1789897612}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 69, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 137, "successful_pairs": 68, "timestamp": 1789898195}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 69, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 138, "successful_pairs": 69, "timestamp": 1789898434}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 70, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 139, "successful_pairs": 69, "timestamp": 1789898715}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 70, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 140, "successful_pairs": 70, "timestamp": 1789898951}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 71, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 141, "successful_pairs": 70, "timestamp": 1789899639}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 71, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 142, "successful_pairs": 71, "timestamp": 1789899871}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 72, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 143, "successful_pairs": 71, "timestamp": 1789900512}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 72, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "successful_lanes": 144, "successful_pairs": 72, "timestamp": 1789900744}`

- OVERNIGHT Q1 EXECUTION LOG: `{"failure": {"category": "NON_TRANSPORT_FAILURE", "exception_class": "OperationalError", "frames": [{"file": "scripts/run_compact_evidence_overnight.py", "function": "run", "line": 366}, {"file": "scripts/run_compact_evidence_canary.py", "function": "evaluate_lane", "line": 176}, {"file": "services/canary_retrieval.py", "function": "run_query", "line": 153}, {"file": "scripts/run_compact_evidence_canary.py", "function": "selected", "line": 164}, {"file": "services/compact_evidence_pack.py", "function": "materialize_compact", "line": 167}, {"file": "scripts/run_compact_evidence_canary.py", "function": "split_original", "line": 56}, {"file": "scripts/canary_split_evidence.py", "function": "split_atom_row", "line": 33}, {"file": "scripts/canary_read_recovery.py", "function": "execute", "line": 222}, {"file": "scripts/canary_read_recovery.py", "function": "_connect", "line": 195}, {"file": "scripts/canary_full_completion.py", "function": "fresh_raw", "line": 109}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/base.py", "function": "connect", "line": 3295}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/base.py", "function": "__init__", "line": 146}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/base.py", "function": "_handle_dbapi_exception_noconnection", "line": 2450}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/base.py", "function": "__init__", "line": 144}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/base.py", "function": "raw_connection", "line": 3319}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "connect", "line": 448}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "_checkout", "line": 1272}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "checkout", "line": 712}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/impl.py", "function": "_do_get", "line": 307}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "_create_connection", "line": 389}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "__init__", "line": 674}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "__connect", "line": 900}, {"file": ".venv/Lib/site-packages/sqlalchemy/util/langhelpers.py", "function": "__exit__", "line": 122}, {"file": ".venv/Lib/site-packages/sqlalchemy/pool/base.py", "function": "__connect", "line": 896}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/create.py", "function": "connect", "line": 667}, {"file": ".venv/Lib/site-packages/sqlalchemy/engine/default.py", "function": "connect", "line": 630}, {"file": ".venv/Lib/site-packages/psycopg2/__init__.py", "function": "connect", "line": 135}]}, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "OVERNIGHT_HARD_STOP", "provider_calls": 0, "session": "59ecd01b6f934be5be76fae5ba385530", "timestamp": 1789901084}`

- OVERNIGHT Q1 EXECUTION LOG: `{"failure": {"category": "NON_TRANSPORT_FAILURE", "exception_class": "CanaryError", "frames": [{"file": "scripts/run_compact_evidence_overnight.py", "function": "run", "line": 352}, {"file": "scripts/run_compact_evidence_overnight.py", "function": "setup", "line": 174}, {"file": "scripts/canary_evaluation_resume.py", "function": "setup", "line": 399}, {"file": "scripts/canary_evaluation_resume.py", "function": "validate_sealed", "line": 487}, {"file": "scripts/canary_post_atom_completion.py", "function": "validated_document", "line": 63}, {"file": "scripts/canary_evaluation_resume.py", "function": "validated_document", "line": 454}, {"file": "scripts/canary_full_completion.py", "function": "exclusive", "line": 96}, {"file": "scripts/canary_evaluation_transport.py", "function": "acquire", "line": 95}, {"file": "scripts/canary_recovery_state.py", "function": "acquire", "line": 180}], "guard": "RETAINED_RUN_ALREADY_ACTIVE"}, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "OVERNIGHT_HARD_STOP", "provider_calls": 0, "session": "03d9e96e594049b68052a6f05d329b5e", "timestamp": 1789903365}`

- OVERNIGHT Q1 EXECUTION LOG: `{"deferred_lanes": 1, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "OVERNIGHT_RESUMED", "next_lane": {"case": 73, "lane": "LEGACY_CONTROL"}, "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 144, "successful_pairs": 72, "timestamp": 1789906104}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 73, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 145, "successful_pairs": 72, "timestamp": 1789906344}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 74, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 146, "successful_pairs": 72, "timestamp": 1789906632}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 74, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 147, "successful_pairs": 73, "timestamp": 1789906875}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 75, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 148, "successful_pairs": 73, "timestamp": 1789907483}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 75, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 149, "successful_pairs": 74, "timestamp": 1789907726}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 76, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 150, "successful_pairs": 74, "timestamp": 1789908012}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 76, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 151, "successful_pairs": 75, "timestamp": 1789908257}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 77, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 152, "successful_pairs": 75, "timestamp": 1789908935}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 77, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 153, "successful_pairs": 76, "timestamp": 1789909174}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 78, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 154, "successful_pairs": 76, "timestamp": 1789909872}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 78, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 155, "successful_pairs": 77, "timestamp": 1789910122}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 79, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 156, "successful_pairs": 77, "timestamp": 1789910420}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 79, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 157, "successful_pairs": 78, "timestamp": 1789910659}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 80, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 158, "successful_pairs": 78, "timestamp": 1789910965}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 80, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 159, "successful_pairs": 79, "timestamp": 1789911283}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 81, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 160, "successful_pairs": 79, "timestamp": 1789912012}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 81, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 161, "successful_pairs": 80, "timestamp": 1789912277}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 82, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 162, "successful_pairs": 80, "timestamp": 1789912575}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 82, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 163, "successful_pairs": 81, "timestamp": 1789912835}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 83, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 164, "successful_pairs": 81, "timestamp": 1789913705}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 83, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 165, "successful_pairs": 82, "timestamp": 1789913971}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 84, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 166, "successful_pairs": 82, "timestamp": 1789914859}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 84, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 167, "successful_pairs": 83, "timestamp": 1789915164}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 85, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 168, "successful_pairs": 83, "timestamp": 1789916017}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 85, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 169, "successful_pairs": 84, "timestamp": 1789916326}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 86, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 170, "successful_pairs": 84, "timestamp": 1789917038}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 86, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 171, "successful_pairs": 85, "timestamp": 1789917280}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 87, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 172, "successful_pairs": 85, "timestamp": 1789917861}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 87, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 173, "successful_pairs": 86, "timestamp": 1789918097}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 88, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 174, "successful_pairs": 86, "timestamp": 1789918683}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 88, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 175, "successful_pairs": 87, "timestamp": 1789918921}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 89, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 176, "successful_pairs": 87, "timestamp": 1789919440}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 89, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 177, "successful_pairs": 88, "timestamp": 1789919674}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 90, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "STRUCTURAL_CANARY", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 178, "successful_pairs": 88, "timestamp": 1789920274}`

- OVERNIGHT Q1 EXECUTION LOG: `{"case": 90, "identity_hash": "267cc90ae317a760db2d9f92beaa91d36cea6ab87b27fb19753001f8aca5e7d2", "kind": "LANE_COMPLETE", "lane": "LEGACY_CONTROL", "provider_calls": 0, "session": "f353922463e3463a87054acf84326bcc", "successful_lanes": 179, "successful_pairs": 89, "timestamp": 1789920505}`
