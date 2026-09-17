# Phase 4.1O Stage A — canary mechanics implementation

2026-09-17. **Decision C: PHASE 4.1O STAGE A — BLOCKED: SAFE POSTGRESQL TARGET REQUIRED.**

**STAGE A POSTGRESQL VALIDATION HOLD.** Offline mechanics are implemented and
tested. This is not real PostgreSQL, semantic-recall, real-provider, production,
or final-answer acceptance. No real embeddings are authorized or performed.

## 1. N checkpoint SHA

`88b427afb4083d4eb53a935368e26bb425230d12`, branch `main`:
`Phase 4.1N: design isolated development hybrid retrieval canary`.
Parent M: `7dc87fccbb16cb8e33f85cf28f5e2dba8076cc25`.

Before this sole local commit: exactly the two N documentation files differed;
740/740 protected hashes matched, secret-pattern scan and diff checks passed.
No runtime change, database access, provider call, embedding or deployment was
part of the N checkpoint. Nothing pushed. O is left uncommitted.

## 2. Files changed

New O files:

- `backend/database/canary_schema.py`
- `backend/services/canary_contracts.py`
- `backend/services/canary_database_guard.py`
- `backend/services/canary_representation.py`
- `backend/services/canary_repository.py`
- `backend/services/canary_retrieval.py`
- `backend/scripts/canary_stage_a.py`
- `backend/scripts/canary_schema_migration.py`
- `backend/scripts/canary_retrieval_gold.py`
- `backend/test_canary_stage_a.py`
- `backend/fixtures/canary_mechanics_v1/gold.json`
- `backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json`
- this report.

One existing file changed: `backend/scripts/test_scoped_rag_regressions.py`,
one O-suite registration. All other checkpointed files remain byte-identical.

## 3. Stage A authorization boundary

Internal, non-serving, deterministic synthetic fixtures only. No API/widget/admin
route selects these lanes. No application connection/model imports in canary
services; no environment DSN lookup, live source fetch, serving cache or provider
helper. Saved corpus files were read only to prepare evaluator mappings.
No production/customer DB, Railway, credentials, bot settings, acquisition,
ingestion, planner, reviewer, context builder, generator, serving FTS/RRF, or M
policy changed. No final 90-answer benchmark, push or deployment.

## 4. Canary contracts

Frozen Pydantic values define approval, profile, source pins, manifest, policy,
lane and typed routes. Tuple inventories and canonical JSON hashes bind nested
values; ingress round-trips validate unsafe copied objects before staging.
`LEGACY_CONTROL` and `STRUCTURAL_CANARY` never share candidate identities.

## 5. Manifest identity

Digest binds run, lane, generation, tenant, operator/environment/database marker,
expiry, exact source/revision/crawl/version/hash set, M implementation/policy,
batch/entry/atom/mapping/projection/quality hashes, profile and provenance,
dimensions, english FTS policy, RRF/tie rules, budgets and query/evaluation hashes.
DB uniqueness prevents replacing a generation's manifest. Counts alone cannot
seal a build: exact payloads, identity sets, vectors, memberships and spans are
compared with the imported M batch.

## 6. State machine

OFF -> EMBEDDING_STAGING -> INDEX_READY -> CANARY_READ/COMPARATIVE_EVAL.
Read leases can return to INDEX_READY; cancellation/failure/expiry/staleness and
OFF deny reads. Terminal states cannot resume. No ACTIVE state exists.
Seal validates every staged manifest in the run. Run-row locks, epoch CAS and
PostgreSQL payload guard SQL are implemented; actual PG concurrency remains HOLD.
Current time and source epochs are rechecked before releasing a query result.

## 7. Schema

Separate SQLAlchemy metadata, not registered in application Alembic. Ten N
run-owned relations plus owned database marker, immutable source snapshot,
source-node inventory and mutable fixture lifecycle relations. Composite keys
carry tenant/run/lane/manifest/generation/profile/policy and complete source pins.
Entry-vector/input, membership/entry/atom and span/source-node foreign keys reject
foreign identities at the relational boundary. No dummy Chunk rows or active
structural pointer. SQLite enforces foreign keys in tests; PG DDL compiles with
`vector(768)` and the atomic GIN expression.

## 8. Repository

Connection/transaction are explicitly caller-owned. Repository verifies the
pre-existing ownership marker; never selects a database itself. `validate_target`
requires an explicit allowlisted host/database fingerprint, approval reference
and marker, returning only a fingerprint or a fixed refusal code. The migration
API additionally requires a `canary_stagea_<32 hex>` owned namespace. Neither API
was run against PostgreSQL. Current lifecycle authority is an owned fixture
snapshot, not a new production tenant authorization model or live data connector.

## 9. Phase M staging

Imports and verifies exact v2 batches. Does not alter M text, atoms, packing,
heading allocations, coverage or mapping identities. Source hash, batch hash,
ordered entry/atom inventories and mapping/projection digests must match the
manifest. Wrong/missing/extra/swapped vectors or incomplete rows cannot seal.

## 10. atomic-fts-v1

One stored projection per admitted atom, including lexical-only atoms. Original
parts, companions, typed nodes and exact provenance remain authoritative. Only
repeated intervals on the identical scoped source node are removed from the
lexical projection; equal strings at distinct occurrences are retained. LF
separators are non-evidence. Ancestor headings owned by another atom remain
independent records. No summary, alias generation or resource-name injection.

## 11. Synthetic vector system

Dedicated local SHA-256 fixture, 768 finite nonzero coordinates, marked
`SYNTHETIC_TEST` with provider `canary-local-fixture`, model `sha256-v1` and its
own configuration hash. Input-specific vectors are verified before publication;
float32 pgvector decoding is covered offline. Real-provider manifests refuse
with `REAL_PROVIDER_NOT_AUTHORIZED`. This does not measure semantic recall.

## 12. Dense scoped retrieval

PG SQL creates materialized eligible-source and eligible-vector relations before
cosine ordering/LIMIT. Manifest, tenant, lane, generation, profile, source/version,
crawl/lifecycle, run lease and expiry predicates precede ranking. Uses exact
cosine, no ANN modification. SQLite's explicitly labeled exact-cosine emulator
exercises the relational scope and ordering, including a stronger unauthorized
document match. It is not evidence of real pgvector execution.

## 13. Atomic scoped FTS

Parameterized english `websearch_to_tsquery`, `to_tsvector` and `ts_rank_cd`;
scope before rank/LIMIT; a sentinel distinguishes empty/non-indexable input from
an indexable query with no hits. No ILIKE, trigram or alternate analyzer.
Phrase, OR, negatives, stemming, numbers, currency and punctuation are present in
the frozen characterization plan but **real behavior is NOT YET MEASURED**.
SQLite raises a PG-validation HOLD rather than pretending to implement FTS.

## 14. Typed routing keys

ENTRY, ATOM_ONLY and LEGACY_CHUNK bind full immutable ownership. No naked integer
is sent to serving fusion as an entry/atom. Legacy numeric tie ordering is kept
numeric, so key 10 does not incorrectly precede key 2.

## 15. Primary route

Body membership wins by part index, ordinal, key. Context-only headings use M's
exact witness. Other context requires all original mapped intervals; otherwise
ATOM_ONLY. Routing is query-independent, never string similarity. All reverse
memberships remain available; a continuation route is not a completeness claim.

## 16. Typed RRF

Explicit frozen weights 1/1 and k=60 in the measured fixture. One-based ranks,
zero missing channel, score/best-rank/document/typed-key ties. Tests compare
formula, ordering and missing-channel behavior with unchanged serving
`weighted_rrf`. No raw dense/FTS score blending.

## 17. Lexical collapse

Unique routes are reranked contiguously after preserving their best raw hit.
The 40-hit same-route test contributes exactly one lexical vote. No refill or
candidate-budget widening. Measured structural rank fixture: 21 atomic hits ->
11 routes, collapse ratio 0.47619047619047616; legacy fixture has no collapse.

## 18. Witness reservation

Best eight distinct witnesses, maximum two per route on first pass, remaining
slots filled in raw-rank order. Reservations consume the same 48-unit cap and
do not add RRF votes. Applied to both experimental lanes. Unchanged serving
legacy fusion is recorded separately, without attributing wrapper effects to
representation quality.

## 19. Materialization

Exact children only, never entry embedding text as answer evidence. Limits:
48 routes/units, 32 children per entry, 256 maps per entry, 128 KiB serialized
evidence and 20 supplemental seed identities; no recursive expansion. Repeated
identity/policy metadata is factored out in the evidence view, while original
payload digest, source text, roles, node attributes, provenance and parts remain.
Both measured synthetic lanes returned all 21 units within the byte cap.

## 20. Continuation handling

All original continuation parts are carried as one atom payload. UTF-8 maps and
part numbering are checked. A unit exceeding remaining byte/count budget is
`INCOMPLETE_BUDGET`; no partial fragment is labeled complete and no absence claim
is generated. A long continuation fixture and a one-byte budget test pass.

## 21. Traces

Structured results include effective/hard scope, raw channel hits, typed routes,
deduplicated channel ranks, RRF contributions, lexical ledger/reservations,
materialized payloads, budget exclusions, epoch/source revalidation, timings and
final completeness. Fixed error categories suppress raw exceptions. The measured
lexical backend is explicitly `INJECTED_RANK_FIXTURE_NOT_POSTGRESQL_FTS`; its
callback duration is not FTS latency. No DSNs or provider errors are recorded.

## 22. Mechanical GOLD

Frozen before implementation evaluation: 28 domain-neutral obligations and ten
FTS characterization categories. SHA-256:
`e37ea082044798ffdbda8345183ec7b101023cfc8201c58bd72c85f11a5043e7`.
Tests exercise ownership, invalid state/vector builds, exact maps, continuation,
heading/atom-only routes, collapse, reservation, degradation and cleanup.
The ordinary text fixture emits prose/list/price/directions/headings; preservation
of richer typed roles relies on exact imported M payloads, not newly inferred
review/FAQ/timeline classification. Real FTS categories remain pending.

## 23. Real-corpus retrieval GOLD sidecar

Original 90-question GOLD is unchanged. New evaluator-only sidecar retains all
90 cases/90 obligations and 152 supporting spans; all 152 historical chunk/span
references verify exactly. 109 map to unique raw-source occurrences; 43 are
coverage gaps. 1,435 candidate atom/span associations are recorded with M routes.

**All 90 paraphrased field assignments remain AMBIGUOUS/review-required.** Primary
span overlap is not proof of a fact's complete qualifier/companion coverage.
No unsupported alternative set or negative-resource label was invented. History
question lineage is hashed; no generated answer history was fabricated. This
sidecar is not yet reviewed semantic-recall GOLD and never enters retrieval.

Final canonical digest:
`11932248a247a41bdc7a227503468274ba0498b6367932e440d60a91265cfeb5`.
During construction, the hash check caught a noncanonical export; node iteration
was sorted and ASCII transport used to avoid Windows code-page conversion. The
final artifact self-digest passes. Source/GOLD facts were not changed.

## 24. Multi-tenant isolation

Uses existing HardKnowledgeScope intersection; None means the authorized manifest
set, empty remains empty. Wrong org/bot/profile refuse. Relational foreign-key
tests reject changed org, bot, manifest, generation, profile, document, version,
hash, revision, crawl and policy. Full source-node FKs reject a foreign mapping.
No isolation violations were observed offline. This is not a real PG tenant-leak
benchmark; stronger foreign FTS matches must still be tested on PostgreSQL.

## 25. Source/version isolation

Exact source fingerprint plus READY/completed/validated and active crawl/upload
state are required. Changed, processing, failed, deleted, superseded, inactive
or wrong-revision fixtures refuse reads/seal. Source-epoch changes invalidate an
in-flight result even if its source fingerprint subsequently returns to the old
value. No source history or corpus is rewritten.

## 26. Lifecycle/cancellation

Cancellation before seal prevents publication; terminal builds cannot restart.
OFF/expiry reject reads and final release. Partial generations are unreadable.
Owned fixture state transitions are exercised in SQLite. PostgreSQL trigger and
locking semantics have been compiled/inspected, not concurrency-tested live.

## 27. Cache isolation

No serving retrieval or answer cache is accessed. No result cache is implemented.
Every read/materialization checks the current run and source state. No warm-cache
exception exists for OFF or expiry.

## 28. Cleanup

Measured deletion removed one run, two manifests/pins, 11 entries/vectors/work
rows, 21 atoms, 31 memberships, 35 spans and 21 legacy fixture members. Zero
run-owned rows remained; source history was retained. A separate-run test proves
another run survives. Injected cleanup failure is not reported as success.
SQLite engine disposal removes the volatile test database. No DROP DATABASE,
extension removal, external table deletion or real DB cleanup occurred.

## 29. PostgreSQL validation

**HOLD.** No explicitly authorized target supplied for this turn; no Docker,
psql or pg_ctl executable on PATH. Previously supplied remote credentials were
not reused or inspected. No connection to application/default/production DB.

PG DDL, composite constraints, vector(768), GIN expression, candidate SQL and
guard/migration APIs are present. Server version, pgvector, actual FTS semantics,
GIN validity/use, EXPLAIN ANALYZE, PG concurrency/rollback, upgrade/downgrade,
index sizes, real dense/FTS timings and PG cleanup are **NOT MEASURED**.

## 30. Security checks

740/740 protected hashes unchanged. All checkpointed files except the single
test-runner registration unchanged. AST/import check: ten new Python modules
PASS. Secret-pattern and trailing-whitespace scans PASS; diff check PASS.
Tests run with external sockets/DNS denied; canonical runner additionally blocks
configured application DB connections and HTTP provider transports. No live
source fetch, real embedding/provider call or production access was required.

## 31. Canonical suite

Focused O: **110/110 PASS, 18.667 s**, network denied.
Complete canonical suite: **3,516/3,516 PASS, 455.375 s**, exit 0, network denied
(3,406 existing + 110 O). Expected Redis-network-denial messages came from the
existing offline fallback tests; no external Redis connection succeeded.
It includes O, all M/L, all structural and established RAG/security regressions;
accepted pre-O baseline is 3,406 tests. No tests were removed or weakened.

## 32. Mechanical metrics

One measured paired query, synthetic vectors and injected lexical ranks, SQLite
in-memory. Not production latency, PG latency or semantic recall. Legacy control
uses synthetic fixture chunks from original structural source parts, not live
customer Chunk rows or a production-retrieval benchmark.

| Measure | Structural | Legacy experimental control |
| --- | ---: | ---: |
| Manifests | 1 | 1 |
| Dense units/vectors | 11 | 21 |
| Stored lexical units | 21 atoms | 21 fixture chunks |
| Entry-atom memberships / spans | 31 / 35 | N/A |
| Materialized units | 21 | 21 |
| Serialized evidence bytes | 96,523 | 118,854 |
| Maximum route fanout | 3 | 1 |
| Dense scoped emulator ms | 9.68670001020655 | 14.279299997724593 |
| RRF ms | 0.06819999543949962 | 0.11110000195913017 |
| Materialization ms | 39.3200000107754 | 35.40890000294894 |
| Query total ms | 52.33429998042993 | 52.85940002067946 |
| Final status | COMPLETE | COMPLETE |

Paired staging/sealing: 233.27910000807606 ms. Entire measurement including
fixture construction and cleanup: 600.1287999970373 ms. One sample; no p50/p95
claim. Real FTS timings, storage/index sizes and GIN/vector plans: N/A (HOLD).

## 33. Limitations

- No real PostgreSQL execution: cannot approve migrations, locking, GIN or vector
  mechanics from compilation and SQLite tests alone.
- Real retrieval sidecar requires field/qualifier association review; no semantic
  recall score or reviewed 90-case coverage claim is made.
- Current source/lifecycle loader and CLI are fixture-only; no application-data
  activation path is implemented. A real development smoke needs fresh source,
  profile and allowlist attestation, not just a database URL.
- Richer typed review/FAQ/timeline inputs and concurrent PG races need dedicated
  integration witnesses before declaring all N acceptance gates satisfied.
- No provider budget/reuse attestation, real embedding, production performance or
  downstream answer-quality claim. Neither lane is exposed to serving traffic.

## 34. Exact next step

Obtain explicit authorization for a named disposable PostgreSQL+pgvector target,
its host/database fingerprint, operator approval, canary ownership marker and
isolated namespace. Do not use an application DSN or an old remembered target.
Then run a separately reviewed target-bootstrap/integration harness through
`validate_target`, the marker/namespace guard, `canary_schema_migration.upgrade`,
repository stage/seal/dense/FTS/materialization, constraint/race/EXPLAIN checks and
owned cleanup/downgrade. The current CLI does **not** silently connect remotely.

Offline reproduction from `backend`:

```powershell
.\.venv\Scripts\python.exe -B -m unittest test_canary_stage_a
.\.venv\Scripts\python.exe -B scripts/canary_stage_a.py prepare-fixtures
.\.venv\Scripts\python.exe -B scripts/canary_stage_a.py compare-mechanical-lanes
.\.venv\Scripts\python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
```

Other internal volatile-fixture commands: `stage-synthetic`, `validate-index`,
`run-mechanical-query`, `expire-run`, `delete-run`. They use only in-memory SQLite;
they are not PostgreSQL validation commands. Rerun with external-network denial
for the same isolation envelope used here.

**C — PHASE 4.1O STAGE A — BLOCKED: SAFE POSTGRESQL TARGET REQUIRED.**
Do not authorize real Gemini smoke based on this offline result. O remains
uncommitted for review. No push, deployment, production activation, real provider
call or 90-question final-answer benchmark.
