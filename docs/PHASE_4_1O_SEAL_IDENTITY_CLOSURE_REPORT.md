# Phase 4.1O-PG Seal Identity + Source-Epoch Closure

Date: 2026-09-17 (Asia/Calcutta). Disposable synthetic mechanics only.

## Decision

A.

PHASE 4.1O STAGE A — COMPLETE

REAL POSTGRESQL / PGVECTOR / FTS CANARY MECHANICS VERIFIED

SEAL IDENTITY + SOURCE-EPOCH CONTRACT VERIFIED

MULTI-TENANT / VERSION / RACE / CLEANUP GATES PASS

FULL CANONICAL SUITE PASS

READY TO REQUEST EXPLICIT AUTHORIZATION FOR SMALL REAL GEMINI EMBEDDING SMOKE

13/13 PostgreSQL gates PASS, zero failures, zero unrun gates, verified cleanup.
Full canonical suite: 3624/3624 PASS both before and after PG. No automatic
real-embedding authorization is implied. Oversized continuation atoms remain
explicitly budget-incomplete as detailed below; this is not semantic acceptance.

## Checkpoint and preservation

Starting branch: main; starting HEAD: `5334f6a318a5cdc457b9135b4ed3d50c0a6bc0a1`.

The previously verified vector repair was audited against its report: the nine
code/test/GOLD file hashes matched the validated bytes, the report matched the
recorded 502/502 focused and 3585/3585 pre/post-PG results, all 740 protected hashes
matched, secret scan and diff checks passed. Only its ten reported files were
checkpointed locally:

`eeef44641810e28c1cf68eadcd207314ac8ecd39`
— `Phase 4.1O-PG: canonicalize vector attestation`.

The new seal/freshness changes are **uncommitted**. Final HEAD remains that
checkpoint. No push or deployment. The working tree is intentionally not clean.

## Measured defects and root cause

The old generic INDEX_READY transition authorized the run, then validated every
stored manifest under it. It did not require the supplied manifest/evaluation or
generation to identify the representation being sealed. Its freshness check used
the current source epoch but had no persisted staged epoch to compare against.

This allowed wrong evaluation identity, unstaged generation, and epoch-only
source changes to advance a valid stored run. All three now refuse in real PG.

## Exact seal, generation and source contracts

- `seal_generation(manifest, expected_build_identity=..., now=...)` is explicit.
  Generic INDEX_READY transition refuses `EXPLICIT_SEAL_IDENTITY_REQUIRED`.
- Lookup requires exact org, bot, run, lane, generation, full canonical manifest
  hash, profile hash and policy hash, plus equality of the complete stored
  manifest payload. Its full digest includes document/source pins, implementation,
  representation policy, profile/config, query contract and evaluation identity.
  No newest/same-run/other-lane substitution.
- `retrieval_manifests` now has immutable `build_snapshot` and `build_identity`,
  plus generation-local `state` and `state_epoch`. Build identity is the digest
  of `canary-generation-build-v1`, exact manifest identity and source snapshot.
- Creation freezes source org/bot/doc/version/hash, website/crawl/version,
  structural revision, fingerprint, readiness/processing/crawl/revision state,
  active crawl and the **existing lifecycle epoch**. No timestamp identity and
  no new parallel tenant-version system.
- Staging, sealing and read acquisition/release compare the persisted snapshot
  with current state. Epoch-only and ABA changes refuse `STALE_SOURCE_EPOCH`,
  even when all other values return to their original values.
- The lifecycle DB guard requires strictly increasing epoch on every update,
  disallows identity changes and disallows delete/reinsert reset. The SQLite
  constraint double has equivalent epoch/reset checks.
- Inventory validation is restricted to that exact stored generation. Existing
  structural/legacy vector, entry, atom, membership, span, work and pin validation
  is retained. A complete older generation never supplies a newer incomplete one.
- Seal holds the run row FOR UPDATE and source rows FOR SHARE in document order
  through final validation/publication. A savepoint makes failed publication
  atomic. Source writers cannot commit in the validation/publication gap.
- Run state is a coarse cancellation/readability aggregate, not seal authority.
  Payload staging requires the exact generation still be STAGING; payload and
  snapshot updates remain forbidden. OFF/terminal state prevents late work.
  Duplicate exact seal intentionally refuses INVALID_TRANSITION.

## Read lease identity

CANARY_READ/COMPARATIVE_EVAL require that exact generation already be INDEX_READY.
Mixed-generation read activation refuses MIXED_READ_GENERATIONS. The lease token
binds run epoch, generation state epoch, exact build identity and current source
snapshot. Existing final run_query revalidation is retained. Unknown identity,
OFF, removed run and source epoch changes prevent release; no global-ready
shortcut is accepted.

## Files changed after the checkpoint

1. `backend/database/canary_schema.py` — isolated generation fields/state guard and monotonic lifecycle guard.
2. `backend/services/canary_repository.py` — exact seal API, persisted snapshot validation, generation-local state/read lease.
3. `backend/scripts/canary_schema_migration.py` — owned epoch-trigger/function downgrade handling.
4. `backend/scripts/canary_stage_a.py` — explicit per-lane seals/read activation.
5. `backend/test_canary_stage_a.py` — adapt seal calls; lifecycle mutations increment epoch.
6. `backend/test_canary_vector_f32.py` — call explicit seal, including the exact legacy lane; numeric assertions unchanged.
7. `backend/test_canary_seal_identity.py` — 39 focused cases.
8. `backend/fixtures/canary_seal_identity_v1/gold.json` — additive frozen 30-case obligations.
9. `backend/scripts/canary_seal_gold.py` — same GOLD executor for SQLite and PG.
10. `backend/scripts/canary_postgres_extended.py` — exact negative seals/GOLD, stronger same-run alternate generation, rich cases, collapse, actual final-release races and seal-gap writer.
11. `backend/test_canary_stage_a_postgres.py` — seal both lanes explicitly; negative gate before queries.
12. `backend/scripts/test_scoped_rag_regressions.py` — register new tests.
13. This report.

No application/Alembic/serving path was modified. Dense/FTS SQL, eligibility SQL,
dense/FTS execution, children and evidence functions were compared by AST:
**7/7 unchanged**. The f32 contracts/profile/GOLD, M/L representations, HardKnowledgeScope,
atomic-fts-v1, RRF, reservations, budgets, parser/chunking and heading policy remain unchanged.

## Frozen GOLD and offline tests

New GOLD was written before implementation/evaluation. Normalized-LF SHA-256:

`f4d40d45ca59b487b27feb40a61ca10681f2256d3abba0a4a4591ce2f3a0a2d5`

All **30/30 GOLD cases** passed offline and in real PG: three exact positive
controls and 27 required refusals. Existing GOLD was not edited.

| Case | PG result | Guard |
| --- | --- | --- |
| cancelled | REFUSED | INVALID_TRANSITION |
| comparative_mixed_generation | REFUSED | MIXED_READ_GENERATIONS |
| content_aba | REFUSED | STALE_SOURCE_EPOCH |
| crawl_version | REFUSED | STALE_OR_INELIGIBLE_SOURCE |
| duplicate_seal | REFUSED | INVALID_TRANSITION |
| epoch_only | REFUSED | STALE_SOURCE_EPOCH |
| exact | SEAL | exact persisted build |
| expired | REFUSED | RUN_EXPIRED |
| foreign_bot | REFUSED | INVALID_MANIFEST_SCOPE |
| foreign_org | REFUSED | INVALID_MANIFEST_SCOPE |
| incomplete_generation | REFUSED | INCOMPLETE_BUILD |
| off | REFUSED | INVALID_TRANSITION |
| older_complete_newer_incomplete | REFUSED | INCOMPLETE_BUILD |
| other_lane | REFUSED | BUILD_IDENTITY_MISMATCH |
| other_run | REFUSED | BUILD_IDENTITY_MISMATCH |
| policy_mismatch | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| processing | REFUSED | STALE_OR_INELIGIBLE_SOURCE |
| profile_mismatch | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| read_exact | READ | exact persisted build |
| read_wrong_generation | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| source_hash | REFUSED | STALE_OR_INELIGIBLE_SOURCE |
| source_version | REFUSED | STALE_OR_INELIGIBLE_SOURCE |
| stale_manifest | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| state_aba | REFUSED | STALE_SOURCE_EPOCH |
| structural_revision | REFUSED | STALE_OR_INELIGIBLE_SOURCE |
| unchanged_snapshot | SEAL | exact persisted build |
| unknown_manifest | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| unstaged_generation | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| wrong_generation | REFUSED | MANIFEST_IDENTITY_MISMATCH |
| wrong_manifest_hash | REFUSED | MANIFEST_IDENTITY_MISMATCH |

Additional tests cover mandatory explicit identity, persisted snapshot across a
repository reopen, reset/delete refusal, snapshot mutation, wrong build token,
read ABA release, FOR SHARE SQL and rollback after a publication failure.

Offline execution used the existing local venv, -B and the external-network denial
wrapper (only the internal Windows socketpair is allowed).

| Validation | Result |
| --- | --- |
| Existing O/vector/PG-independent guards | 179/179 PASS, 33.316 s |
| Initial new seal tests | 38/38 PASS, 2.222 s |
| O/vector/guards/new seal + M/L focused set | 540/540 PASS, 136.007 s |
| Final seal module, including added publication rollback | 39/39 PASS, 2.285 s |
| Full canonical before PG | **3624/3624 PASS**, 658.270 s |
| Full canonical after PG | **3624/3624 PASS**, 644.740 s |
| AST/import, secret scan, git diff --check | PASS |
| Protected hashes | **740/740 unchanged** |

No isolated retry substituted for the complete suite. No Docling skip; the pre-PG
suite's Docling workers emitted valid JSON, including the expected negative-input
worker. The post-PG run also completed every Docling check with valid JSON; no
tests were skipped. The offline Redis warning was an intentionally blocked external network
attempt, not a connection to Redis or a runtime change.

## Fresh disposable PostgreSQL run

Explicit CANARY_DATABASE_URL only; no application/default/customer DB fallback.
PostgreSQL **18.6**, pgvector **0.8.6**, UTF8, vector namespace public.
Fresh owned namespace:

`canary_stagea_3ec8ead36bbe42dda01ed690545815b1` — **removed**.

Command from backend: `.venv/Scripts/python.exe -B test_canary_stage_a_postgres.py`.
One complete fresh run, exit **0**. No extension install or configuration change.

| Gate | Result | Elapsed ms |
| --- | --- | ---: |
| preflight | PASS | 6354.659 |
| migration_cycle | PASS | 38411.159 |
| schema_constraints | PASS | 4148.021 |
| stage_real_rows | PASS | 120089.983 |
| invalid_vectors | PASS | 13918.044 |
| database_rejections | PASS | 32483.085 |
| seal | PASS | 17271.834 |
| seal_negatives | PASS | 253847.993 |
| query_database | PASS | 72059.903 |
| scoped_candidates | PASS | 82089.010 |
| rich_materialization | PASS | 439283.006 |
| concurrent_sessions | PASS | 222955.162 |
| cleanup_runs | PASS | 34082.217 |
| Final owned-schema cleanup | PASS | 7748.202 |

Sum of gate and cleanup measurements: **1344.742279 s**. These are remote
synthetic-test measurements, not production latency.

Migration upgrade/downgrade/re-upgrade passed. Four source-history/marker tables
were retained by downgrade, then reused by re-upgrade. Schema: 14 tables,
14 primary keys, 3 unique constraints, 15 full-scope FKs, 21 CHECKs, 234 NOT NULLs.
Both vector columns remain vector(768). GIN `ix_canary_atoms_content_fts_en_v1`
exists, is valid and ready.

Run A and B each staged 2 manifests/documents (structural + legacy), 11 entries,
11 vectors, 11 work rows, 21 atoms, 31 memberships, 35 spans and 21 legacy members.
All 11 structural pgvector round trips had exact coordinate/byte/digest/profile/
input/version equality; legacy canonical attestation passed its separate seal.
Five invalid vector shapes were rejected without mutation.

All **23/23 DB rejection attacks** refused and savepoints rolled back. Missing
run/generation/manifest/profile/policy guards may reject before FK evaluation;
input-hash attack hit 23505, so this is not misreported as independent FK proof.

Normal structural and legacy generation seals passed; structural read lease passed.
Before any retrieval, all **9/9 previous negative seals** refused: missing/extra
vector, missing atom, missing span, wrong manifest, wrong generation, changed
source epoch, cancelled and expired. All 30 GOLD cases then passed, plus actual
PG epoch reset and immutable snapshot mutation refusals (P0001).
All case mutations/positive controls rolled back; no bad state was committed.

## Retrieval, scope and rich evidence

Real exact-cosine dense query: 11 hits. FTS categories:
word 2, quoted phrase 2, OR 4, exclusion 1, stemming 1, numeric 1, currency 1,
identifier 1, empty 0/empty, negative-only 0/non_indexable. All **10/10 PASS**.

Actual dense/FTS ranks, typed weighted RRF, deduplication, zero missing-channel
contribution, stable ties, reservation/budget bounds and exact payload equality
passed. Main query: 21 units, 96,523 bytes, 4 raw FTS hits/4 routes/4 witnesses.

Stronger foreign-org, foreign-bot, same-run alternate-generation and stale-source
fixtures had better dense and lexical matches, but **0 unauthorized/stale result
rows** entered the authorized result. Stale lifecycle also yielded zero raw
eligible dense candidates and no FTS candidate. Scope predicates precede rank/LIMIT.

| Rich fixture | Status | Returned units | Bytes | Source continuation parts |
| --- | --- | ---: | ---: | ---: |
| review | COMPLETE | 2 | 6417 | 0 |
| timeline | COMPLETE | 2 | 6602 | 0 |
| long_stage | INCOMPLETE_BUDGET | 2 | 8971 | 22 |
| huge_list | INCOMPLETE_BUDGET | 1 | 2501 | 3 |
| price | COMPLETE | 2 | 6416 | 0 |
| directions | COMPLETE | 2 | 6409 | 0 |
| UTF-8 | COMPLETE | 2 | 7968 | 0 |
| faq | COMPLETE | 2 | 7783 | 0 |
| warning | COMPLETE | 2 | 6421 | 0 |

Returned atom payloads were compared exactly with source-backed projections;
source UTF-8 span slices matched entry slices; role, qualification, source-part
and provenance fields remained intact. No entry text was substituted as evidence.

**Important limit:** long_stage and huge_list correctly reported INCOMPLETE_BUDGET.
Their complete oversized atoms were not truncated or claimed fully retrieved.
Storage/seal/span checks covered the continuation records, but this run does
**not** claim complete hydration of these oversized continuation atoms. Budgets
were not changed. This is bounded-mechanics acceptance, not semantic recall or
answer-completeness acceptance.

Real ATOM_ONLY: 1 lexical-only route, zero dense contribution, no invented parent,
retained raw witness and exact source materialization.
Real collapse: **2 raw atom hits -> 1 route/RRF vote**; both raw hits retained in
the ledger; one weighted rank contribution, no parent score multiplication.

## Multi-session races and release

All eight measured race categories passed using independent PG sessions and
existing 3-second lock / 15-second statement timeouts:

| Race | Observed outcome |
| --- | --- |
| Duplicate work | One committed owner; other session refused with 55P03; one vector inventory |
| Cancel vs seal | Cancellation committed; blocked seal refused INVALID_TRANSITION |
| Late work after cancellation | INVALID_TRANSITION |
| Duplicate manifest/generation | One committed identity; other refused 23505 |
| Source epoch during actual query | Status changes and returns to ready with incremented epoch; final release refused STALE_SOURCE_EPOCH |
| OFF during actual query | Final release refused NO_READ_LEASE |
| Cleanup during actual query | Final release refused UNKNOWN_RUN |
| Source writer in final-validation/publication gap | FOR SHARE prevented commit; writer refused 55P03; no partial publication |

For read races, the hook ran at the real run_query final gate **after actual dense,
FTS and materialization**, not in a standalone simulated token check. No stale
result returned. After the locked seal committed, a later source epoch update was
allowed; subsequent read activation then refused STALE_SOURCE_EPOCH.
If a source change commits first, the negative tests prove seal refuses; if seal
holds the source lock first, the writer cannot commit in the validation gap.
This is the measured serialization behavior, not a claim that every writer wins.

## Natural plans and timing

No forced-index setting or ANN/index tuning was used.

| Component | Client elapsed ms |
| --- | ---: |
| Dense channel | 1618.561600 |
| FTS channel | 1538.530700 |
| Typed fusion | 0.099400 |
| Materialization | 43979.670100 |
| Complete main query, including gates | 49280.224600 |

Natural dense plan: materialized eligible sources/vectors, scoped PK/index scans,
11 vector rows, exact-distance quicksort then LIMIT; planning **0.555 ms**,
execution **0.244 ms**, root shared buffers 32 hits / 0 reads.

Natural FTS plan: one-row query CTE, materialized eligible source scope, atom PK
index scan (21 rows), four matching rows, rank sort before LIMIT and outer sort;
planning **0.730 ms**, execution **0.403 ms**, 22 shared hits / 0 reads.
GIN was valid but **not naturally selected** for this tiny scope. This is not
presented as a forced GIN plan. SQLAlchemy emitted the existing warning about the
single-row q CTE cross product; SQL/results were unchanged.

Materialization remains round-trip-heavy. No batching/performance rewrite was
combined with this repair, and no production-latency or semantic-quality claim
is inferred from these synthetic vectors.

## Cleanup, boundaries and next step

Selective cleanup passed: A rows became zero while B counts, shared source hashes
and B legacy controls remained unchanged. B was then removed; final downgrade
passed. Finally, only the owned schema was dropped after marker/OID/catalog
checks; schema, marker, fixture tables/vectors/indexes/functions were removed.

Unrelated catalog remained **126 objects** with unchanged hash:

`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.

pgvector was retained. No DROP DATABASE, DROP EXTENSION or unrelated schema change.
Connections closed and engines disposed; child and launching process CANARY
secret/approval variables were cleared. The secret URL was not emitted in test
output or persisted in source, .env, reports or captured result files.

Semantic GOLD remains unchanged: 90 cases, 152 supporting spans, 109 unique
occurrences, 43 coverage gaps and 90 field associations review-required.
No 23-document semantic run, 90-answer benchmark, customer corpus, provider/model
call, real embedding, crawl, ingestion, re-embedding, production action,
deployment or push occurred. Only the explicitly requested initial vector
checkpoint was committed.

Final read-only diff review, AST/import checks, secret scan and diff check passed;
all 740 protected hashes remain intact. No source changed during/after the PG run;
only this report was added/finalized while the post-PG suite ran.

Next step is review of this **uncommitted** closure and a separate explicit request
for authorization of a small real Gemini embedding smoke. No such call is
authorized or executed by this task.
