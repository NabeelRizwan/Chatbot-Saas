# Phase 4.1O-PG disposable PostgreSQL validation

2026-09-17. **Decision B — PHASE 4.1O STAGE A — COMPLETE:
POSTGRESQL MECHANICS NEED REVISION.**

Offline Stage A is checkpointed; **real PostgreSQL acceptance is withheld**.
The authorized pgvector installation succeeded. Real migrations, staging and
database rejection tests passed, but the first normal seal failed with
`ENTRY_VECTOR_CORRUPTION`. The owned schema was removed and unrelated catalog
objects were verified unchanged. No runtime repair or seal bypass was performed.

## 1. Checkpoint and working-tree audit

Branch: `main`. Starting and final HEAD:
`4703119071b0380bd7399d9377234b47cffda5c0` —
`Phase 4.1O: add isolated canary retrieval mechanics`.

The prior turn created that local O checkpoint from N
`88b427afb4083d4eb53a935368e26bb425230d12`. This continuation created **no commit**.

Exactly the expected five PG closure paths were uncommitted at entry:

- `backend/scripts/canary_postgres_validation.py`
- `backend/test_canary_postgres_guard.py`
- `backend/test_canary_stage_a_postgres.py`
- `backend/scripts/test_scoped_rag_regressions.py`
- This report.

No unexpected paths. The tracked registration diff adds only the offline guard
suite; the live PG driver is not part of ordinary offline discovery.
740/740 protected hashes matched. All existing implementation/test files were
preserved. **Only this report was edited during this continuation.**

## 2. Disposable authorization and extension availability

The operator explicitly reauthorized the previously supplied target as disposable,
development/test only, without customer data, and additionally permitted installing
`vector` **only if the server listed it as available**.

Approval reference: `user-phase-4-1o-vector-install-20260917`.
Only process-local `CANARY_DATABASE_URL` was used, with the same independent
allowlisted fingerprint and `disposable_test` approval. No application settings,
dotenv, default DSN, remembered alternative, customer or production database.

Actual read-only availability query:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name = 'vector';
```

Result: **available YES; default 0.8.6; installed version initially NULL**.
Elapsed: **5,542.681999999331 ms**. No mutation in that inspection.

The previous report's `PGVECTOR_EXTENSION_REQUIRED` blocker was genuine; the
new authorization allowed enabling the available extension, not bypassing a guard.

## 3. Target fingerprint and extension installation

Sanitized target identity:

- Host/port/database fingerprint:
  `f0ea52198bce34330bbc29a51544883b6d039a53d71d684773b8d0037c86cf90`.
- Host fingerprint:
  `31c0d26e9e9b3e7c285e928a6a64c8965ff72f9c77343e7ca656af97a7bf5c4c`.
- Database-name fingerprint:
  `43607caeef59149899666821db393db2085a0467c87f0dc92c97b684c8b14e1b`.

Before the installation transaction: explicit target/current-database identity,
application-table and stale-test-schema guards **PASS**; extension availability
was rechecked in the transaction. Executed:

```sql
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
```

**Installed by this task: YES.** Transaction committed. Installed version **0.8.6**;
extension-owned vector type verified through catalogs. Elapsed:
**7,123.813100013649 ms**. No unrelated extension or application table changed.

**The vector extension remains installed.** A final read-only diagnostic confirmed
version 0.8.6 after schema cleanup. No DROP EXTENSION was issued; its later removal
is an operator decision.

## 4. Fresh full preflight / server facts

Validation restarted from the beginning after installation, not halfway:

| Fact | Actual result |
| --- | --- |
| PostgreSQL | 18.6, Debian 18.6-1.pgdg12+2, x86_64, 64-bit |
| server_version_num | 180006 |
| Encoding | UTF8 |
| Timezone | Etc/UTC |
| Initial search_path | `"$user", public` (literal setting, no username disclosed) |
| Initial current_schema | public |
| pgvector installed / available | 0.8.6 / 0.8.6 |
| Extension namespace | public |
| Application-schema / stale-schema guard | PASS / PASS |
| Canary namespace | `canary_stagea_9c63a68cfdc443d094698e99dc4af9fb` |

The new namespace and ownership marker were created before mutable canary tables.
All canary objects were created inside that namespace. Connections used an explicit
local search path, bounded statement/lock timeouts and hidden SQL parameters.

## 5. Real migration validation

**PASS**: upgrade → inventory validation → downgrade → removal validation →
re-upgrade → inventory validation, all actual PostgreSQL DDL.

14 tables created. Downgrade removed the ten run-owned tables and retained only
`canary_ownership`, `canary_source_history`, `canary_source_lifecycle` and
`canary_source_nodes`, as designed. Re-upgrade succeeded. This cycle ran before
fixture staging; it does **not** prove populated fixture preservation across
downgrade. No application Alembic or serving schema was touched.

## 6. Real schema objects and constraints

Catalog validation **PASS**:

- 14 primary keys.
- 3 unique constraints.
- 15 foreign keys, scoped by organization/bot except the explicit run-to-database
  ownership-marker key.
- 18 CHECK constraints.
- 228 NOT NULL columns/constraints.
- Both entry-vector and legacy-vector columns are real `vector(768)`.
- 19 indexes observed, including the valid/ready atomic FTS GIN index.

All 14 proposed ownership/source/lifecycle/run/manifest/entry/vector/atom/
membership/span/work/legacy tables existed in the isolated namespace.

## 7. Actual database rejection tests

**23/23 negative insert cases rejected; savepoint rollback PASS.** These are
subcases within the `database_rejections` integration gate, not 23 additional
top-level test methods.

| Boundary attacked | Actual enforcement |
| --- | --- |
| Foreign organization, bot, run | Database run-state trigger, SQLSTATE P0001, before FK evaluation |
| Foreign manifest, generation, profile, policy | Composite FK, 23503 |
| Foreign document, document version, source version/hash, revision | Composite FK, 23503 |
| Foreign website, crawl ID/version | Composite FK, 23503 |
| Foreign entry | Composite FK, 23503 |
| Foreign atom/entry in membership | Composite FK, 23503 |
| Foreign source node in span | Composite FK, 23503 |
| Duplicate vector / altered input hash on an existing vector PK | Unique/PK, 23505 |
| Invalid span range | CHECK, 23514 |
| NULL embedding | NOT NULL, 23502 |

The wrong-input-hash insert was rejected by the duplicate primary key; this is
**not** credited as independently proving the input-hash FK. Likewise foreign
org/bot/run rejection is credited to a **database trigger**, not Python or an
FK that did not execute first. No invalid row survived its savepoint.

These insert attacks do not substitute for the not-run stronger foreign-candidate
retrieval tests or concurrency/authorization acceptance.

## 8. Real vector storage and invalid-vector layer

**PASS for staging and finite/nonzero 768-dimensional round-trip validation.**
Only deterministic `SYNTHETIC_TEST` / `canary-local-fixture` / `sha256-v1`
vectors were used.

Actual SQLAlchemy result type: **list of Python float**, not a native NumPy
float32 array. That distinction causes the seal failure documented in section 14.

767 dimensions, 769 dimensions, NaN, Inf and all-zero supplied vectors:
**5/5 refused by repository validation before INSERT; stored row counts unchanged.**
Do not interpret those checks as proving PostgreSQL rejects all five payloads.

Wrong profile/generation keys were rejected by database FKs; altered existing
input-hash binding was rejected by PK as recorded above. Full profile/provenance
attack coverage and cosine ordering remain incomplete.

## 9. Dense scoped retrieval

**NOT RUN**, because no valid sealed/readable generation could be published.
No exact-cosine candidate ranking, stronger foreign org/bot/generation/source
fixture or scope-before-LIMIT execution was credited. No ANN change was made.

## 10. Real FTS characterization

**NOT RUN** after seal failure: word, phrase, OR, negative, stemming, number,
currency-like text, punctuation-rich identifier, empty and non-indexable input.
No ILIKE, trigram, analyzer substitution or query rewriting was introduced.
Atomic projection rows were stored, but storage alone is not FTS query acceptance.

## 11. GIN and EXPLAIN

**GIN existence/validity/expression PASS.**
`ix_canary_atoms_content_fts_en_v1` is valid and ready, using:

```sql
to_tsvector('english'::regconfig, COALESCE(canonical_text, ''::text))
```

Index size after staging: **24,576 bytes**.
Natural lexical/dense EXPLAIN ANALYZE: **NOT RUN**; no plan, buffer, scope-ordering
or natural index-use claim. Seqscan was not disabled or otherwise forced.

## 12. Typed RRF from real DB candidates

**NOT RUN**. No actual eligible dense/FTS candidate set existed after the failed
seal. One-based ranks, 1/1 weights, k=60, route collapse, missing-channel zero,
ATOM_ONLY routing and raw lexical witness preservation remain offline-tested
only. Serving weighted RRF and all canary policies are unchanged.

## 13. Staging and materialization

Both run A and run B were staged with the same synthetic fixture.
Measured **run A** inventory:

| Relation | Rows |
| --- | ---: |
| Runs / manifests / document pins | 1 / 1 / 1 |
| Entries / vectors / completed work | 11 / 11 / 11 |
| Atoms / atomic FTS rows | 21 / 21 |
| Entry-atom memberships | 31 |
| Span rows | 35 |
| Legacy members | 0 |

Do not treat the harness's `run_b_same_counts` label as an independent count
assertion; its staging completed, but only run A's counts were emitted.

Actual candidate → membership → atom → exact payload materialization:
**NOT RUN**. Typed roles, UTF-8, qualifiers, review/list/timeline/quantity ownership,
continuation completeness, 48-unit/128-KiB budget, 32-child and 256-map boundaries
remain PG acceptance obligations. No entry embedding text became an answer fact.

## 14. Measured seal failure and exact root cause

**FAIL**: `CanaryRepository.transition(..., INDEX_READY)` called
`_validate_run`, which raised `ENTRY_VECTOR_CORRUPTION` at
`backend/services/canary_repository.py:238`.

The actual normal build could not seal. The guarded transaction rolled back;
CANARY_READ was never reached and no partial INDEX_READY was committed. Missing/
extra vector/atom/map, manifest/epoch, cancelled/expired and wrong-generation
seal cases were not subsequently run or counted as passes.

A separate **SELECT-only** diagnostic used the same SQLAlchemy column type
(`s.vectors.c.embedding.type`) and real `public.vector(768)` cast, with no
table creation or fixture mutation. It proved:

- Decoded result is a list of Python floats matching JSON parsing of PostgreSQL's
  vector text output.
- 768/768 coordinates differ from the original Python float representation.
- Example: synthetic **0.6854400634765625** returns as **0.68544006**.
- Maximum absolute difference: **2.9492187469948306e-08**.
- `validate_vector` passes, but both exact synthetic-vector equality and the
  vector digest comparison fail.
- Casting the returned values to float32 and then Python float recovers the
  original synthetic vector **exactly**.

The mapping `JSON().with_variant(Vector(768), 'postgresql')` gives PostgreSQL
vector DDL but this runtime result path decodes the textual coordinates through
the JSON/Python-float representation. The seal compares those values/hash against
the original synthetic coordinates without canonical float32 round-trip handling.
Thus valid staged vectors are falsely marked corrupt. This is a **measured
representation/attestation compatibility defect**, not provider quota, missing
extension, bad vector dimension, a demonstrated tenant leak or a bad source fact.

**No runtime fix, tolerance relaxation, forced state update or seal bypass was
implemented.** Readable retrieval cannot honestly be accepted until this is repaired.

## 15. Concurrency and races

**NOT RUN**: independent-session duplicate work, cancellation versus seal,
source epoch during query, OFF in flight, duplicate manifest/generation,
cleanup versus read and late commit after cancellation. The failed ordinary seal
is a prerequisite blocker. No race result or uniqueness claim is invented.

## 16. State / cancellation

No run reached a read lease. CANARY_READ/COMPARATIVE_EVAL/return-to-INDEX_READY,
expiry, cancellation and stale-result final release are **NOT VERIFIED ON PG**.
The failing seal transaction did not partially publish. No ACTIVE state,
production activation, endpoint or serving cache behavior was introduced.

## 17. Owned cleanup and extension ownership

**Final owned-schema cleanup PASS**, even though the selective `cleanup_runs`
test was not reached. The harness checked schema OID/owner, marker contents and
OID, exact owned object inventory and unrelated catalog snapshot, then removed
only:

`canary_stagea_9c63a68cfdc443d094698e99dc4af9fb`.

Schema, marker, fixture tables, indexes and function were removed. A later
SELECT-only diagnostic independently confirmed the namespace is absent.

Unrelated catalog before/after cleanup: **126 records**, identical digest:
`5379861bc2836ae3c64914139f6787c923d3cdde61e55393038a173a14a0d645`.
This baseline was taken **after** the explicitly authorized vector installation,
so it correctly includes the retained extension.

Run-A deletion preserving Run-B/shared/legacy history: **NOT RUN**, not PASS.
Whole-owned-schema cleanup is not substituted for that selective cascade test.
No DROP DATABASE, DROP public or DROP EXTENSION occurred.

All connections closed, engines disposed, process-local canary secret/approval
variables removed in finally blocks. No DSN/credential was printed or persisted.

## 18. Isolation and scope limits

Preflight and pre-install catalog safety guards passed; no customer contents or
application DB connection was used. All mutable canary rows were in the owned
schema, under synthetic tenant identities.

Relational foreign-key/run-trigger attacks were rejected, but stronger foreign
dense/lexical candidates, lifecycle/profile retrieval filters and race release
boundaries were not exercised. Consequently **no full PG tenant-isolation
acceptance is claimed**. No serving security or query policy was changed.

## 19. Real integration totals, timing and storage

Executed `test_canary_stage_a_postgres.py` once from its beginning after extension
installation, via a stdin-only `runpy` wrapper with process-local authorization
and Python provider/source network denial; explicit PostgreSQL uses libpq.
Exit code **1**. There was no retry of the failed acceptance or weaker substitute.

Top-level stages: **6 PASS, 1 FAIL, 2 NOT RUN**. Final cleanup independently
**PASS**. The additional vector diagnostic was SELECT-only, not a second
acceptance run. The driver is still a prerequisite suite, not full PG approval.

| Stage | Result | Elapsed ms |
| --- | --- | ---: |
| preflight | PASS | 7074.2657000082545 |
| migration_cycle | PASS | 38216.434700007085 |
| schema_constraints | PASS | 3575.290100008715 |
| stage_real_rows | PASS | 93218.33420000621 |
| invalid_vectors | PASS | 12479.884100001073 |
| database_rejections | PASS | 29035.075899999356 |
| seal | FAIL | 7131.0260000173 |
| query_database | NOT RUN PREREQUISITE FAILED | N/A |
| cleanup_runs | NOT RUN PREREQUISITE FAILED | N/A |
| Final owned-schema cleanup | PASS | 8386.680499999784 |

FTS, cosine query, RRF and materialization timings: **N/A**, not executed.
These are synthetic remote test timings, never production latency.

Physical storage after staging, before cleanup. Table total includes its
indexes/TOAST; do not add it again to the index totals. There were **14 tables
and 19 indexes**; standalone index sizes sum to **581,632 bytes**.

| Relation | Kind | Main bytes | Total bytes |
| --- | --- | ---: | ---: |
| `canary_atoms` | table | 32,768 | 303,104 |
| `canary_atoms_pkey` | index | 49,152 | 49,152 |
| `canary_embedding_work` | table | 16,384 | 81,920 |
| `canary_embedding_work_pkey` | index | 32,768 | 32,768 |
| `canary_entries` | table | 16,384 | 204,800 |
| `canary_entries_organization_id_bot_id_run_id_lane_generatio_key` | index | 32,768 | 32,768 |
| `canary_entries_pkey` | index | 32,768 | 32,768 |
| `canary_entry_atom_memberships` | table | 73,728 | 237,568 |
| `canary_entry_atom_memberships_pkey` | index | 73,728 | 73,728 |
| `canary_entry_atom_spans` | table | 49,152 | 155,648 |
| `canary_entry_atom_spans_pkey` | index | 73,728 | 73,728 |
| `canary_entry_vectors` | table | 16,384 | 204,800 |
| `canary_entry_vectors_pkey` | index | 32,768 | 32,768 |
| `canary_legacy_members` | table | 0 | 16,384 |
| `canary_legacy_members_pkey` | index | 8,192 | 8,192 |
| `canary_ownership` | table | 8,192 | 24,576 |
| `canary_ownership_pkey` | index | 16,384 | 16,384 |
| `canary_runs` | table | 8,192 | 32,768 |
| `canary_runs_pkey` | index | 16,384 | 16,384 |
| `canary_source_history` | table | 8,192 | 139,264 |
| `canary_source_history_pkey` | index | 16,384 | 16,384 |
| `canary_source_lifecycle` | table | 8,192 | 24,576 |
| `canary_source_lifecycle_pkey` | index | 16,384 | 16,384 |
| `canary_source_nodes` | table | 90,112 | 155,648 |
| `canary_source_nodes_pkey` | index | 32,768 | 32,768 |
| `ix_canary_atoms_content_fts_en_v1` | index | 24,576 | 24,576 |
| `ix_canary_memberships_reverse` | index | 57,344 | 57,344 |
| `retrieval_manifest_documents` | table | 8,192 | 65,536 |
| `retrieval_manifest_documents_organization_id_bot_id_run_id__key` | index | 16,384 | 16,384 |
| `retrieval_manifest_documents_pkey` | index | 16,384 | 16,384 |
| `retrieval_manifests` | table | 8,192 | 98,304 |
| `retrieval_manifests_organization_id_bot_id_run_id_lane_gene_key` | index | 16,384 | 16,384 |
| `retrieval_manifests_pkey` | index | 16,384 | 16,384 |

## 20. Offline regressions / preservation

Accepted entry baseline: 137 focused and 3,543 canonical tests PASS.
Fresh continuation focused run: **137/137 PASS (24.790 s)**.
Fresh canonical run: **FAIL, exit 1 — 3,515 tests ran in 559.291 s; one
class-setup error**. `test_structural_docling_adapter.RealExtractionTests.setUpClass`
raised `DoclingAdapterError('WORKER_FAILED')` at
`services/structural_docling_adapter.py:159`, because the local worker output could
not be parsed as JSON. That prevented its 28 tests from starting; the run did not
complete the 3,543-test baseline. No ordinary assertion failures were reported.

One isolated rerun of that class: **28/28 PASS (52.418 s), exit 0**. Its three
setup workers returned valid JSON with exit 0; the setup failure did not reproduce.
The observer recorded only worker exit code, output length/JSON validity and
format, without changing implementation, test parameters or extraction behavior.
The original non-JSON worker failure's underlying cause is not established
(stderr was discarded by the unchanged adapter). The full canonical failure is
not erased or reclassified as a pass by this focused retry. No second complete
canonical run or implementation/environment repair was performed.

The canonical suite includes all O, M/L and structural regressions, with provider/
source transports and application DB access denied. No test was removed or
weakened. No new source/test changes were made during this continuation.

740/740 protected hashes match; AST/import, credential scan and diff check **PASS**.
The existing four PG Python/registration files are byte-identical to the entry
snapshot; only this report records the new evidence. All PG closure
work remains uncommitted. HEAD remains the O checkpoint. No push or deployment.

## 21. Semantic GOLD limitation

Unchanged: 90 cases; 152 supporting spans; 109 unique source occurrences;
43 coverage gaps; all 90 field associations **AMBIGUOUS / review-required**.
No GOLD edits, semantic recall claim, 23-document semantic run or 90-answer
generation occurred.

## 22. Provider / production boundary

Provider/model calls **0**; real embeddings **0**. No Gemini/OpenAI/Claude/Grok,
customer corpus, live fetch, crawl, ingestion, re-embedding, production DB,
production Railway action, public endpoint or deployment. The only shared
database-level change is the expressly authorized `vector` extension in the
disposable testing database, which was intentionally retained.

## 23. Exact next step and decision

Authorize a narrow canary vector round-trip/attestation repair: preserve the
768-dimensional synthetic provenance contract while making PostgreSQL decoded
coordinates and hashes use the same canonical representation. Do not weaken the
seal, remove hashes, relax tenant checks or apply broad approximate matching.

Then restart PG validation and complete all currently unrun dense/FTS/EXPLAIN,
routing/materialization, seal-negative, race/cancellation and selective cleanup
gates. Also resolve or independently clear the offline Docling worker failure
and obtain a clean full canonical run; it is an additional acceptance blocker.
The current result does not authorize real Gemini embeddings.

**B — PHASE 4.1O STAGE A — COMPLETE**

**POSTGRESQL MECHANICS NEED REVISION**

**Exact defect: PostgreSQL vector text → JSON/Python-float decoding breaks exact
synthetic-vector equality/hash attestation, causing a false
ENTRY_VECTOR_CORRUPTION during seal.**
