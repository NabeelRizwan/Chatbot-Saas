# Phase 4.1F — shadow structural ingestion

Date: 2026-09-16. Branch: `main`. Verdict: **PHASE 4.1F — COMPLETE**.

## 1. Phase 4.1E checkpoint

Committed locally: `b388b7f8fb142d67991c4e19b4b8c288bd3cefbb` —
`Phase 4.1E: add deterministic structure-aware chunk serializer`.
Starting parent: `12d38f0196b29704c3f7b85aaed46a8cccf2ca78`.
The ten intended E files were audited, with no ingestion/retrieval changes,
generated payloads, models, environment files or credentials staged. Frozen
hashes and whitespace checks passed. Nothing was pushed. F remains uncommitted.

## 2. OSS lifecycle/indexing study

Actual current source and licenses were inspected before ingestion edits for
Docling, RAGFlow, LlamaIndex, Haystack and Onyx. Pinned commits, source functions,
adapted patterns and rejected behavior are recorded in the
[OSS ledger](PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md#phase-41f--ingestionlifecycle-source-study-2026-09-16).
No literal upstream implementation was copied, dependency added, or framework
queue, datastore, authorization, embedding or retrieval architecture adopted.

## 3. Files changed in F

- `backend/services/structural_shadow_config.py` — new server-only mode/scope control.
- `backend/services/structural_shadow.py` — new observer, identity, telemetry and scoped writer orchestration.
- `backend/services/document_processing_service.py` — configuration check, promotion audit manifest, post-success observer hook.
- `backend/services/structural_docling_adapter.py` — optional cancellation of the existing owned child; conversion recipe unchanged.
- `backend/workers/embedding_worker.py` and `backend/workers/crawl_worker.py` — READY-job observer redelivery.
- `backend/test_structural_shadow.py` — focused offline and legacy-parity tests.
- `backend/scripts/test_phase41f_shadow_postgres.py` — guarded synthetic PostgreSQL tests.
- `backend/scripts/evaluate_structural_shadow.py` — offline saved-source parity/metrics replay.
- `backend/scripts/test_scoped_rag_regressions.py` — focused suite registration.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` and this report.

No migration, structural repository/schema, text parser, frozen serializer,
requirements, GOLD fixture, application configuration, RAG or frontend file changed.

## 4. Integration architecture

Legacy acquisition, page validation, chunking, embedding, quota checks and atomic
promotion remain authoritative. Successful promotion adds only a bounded pending
manifest to existing `IngestionJob.audit_metadata.structural_shadow_v1`.
An independent session captures an immutable source, parses and serializes outside
promotion locks, then commits the validated sidecar graph and summary together.
There is no parallel acquisition service or new queue/table/state machine.

## 5. Exact hook point

`_process_file_document` and `_process_website_document` call `mark_pending` after
`_mark_job_ready`, before the existing promotion commit. This only constructs
bounded JSON; it performs no parsing or sidecar SQL. `process_document` invokes
`resume_shadow_job` after successful promotion **and after the original retrieval
cache invalidation**, outside both legacy failure-cleanup blocks. This ordering
does not delay serving-cache invalidation behind optional parsing.

## 6. Feature flag

`STRUCTURAL_INGESTION_MODE` defaults to `off`. Vocabulary is `off`, `shadow`,
`active`; invalid values and `active` raise configuration errors. Import of the
existing ingestion service validates configuration for API/worker startup.
Active behavior is not implemented. No environment file was changed.

## 7. Allowlist behavior

`STRUCTURAL_SHADOW_ALLOWLIST` defaults to empty. It accepts at most 1,000 exact
`organization_id:bot_id` pairs, comma-separated, without wildcards. Pair matching
is not a Cartesian product of independent organization/bot lists. Request fields,
source text and customer metadata cannot opt in. A durable ingestion job is
required; legacy development-only inline calls without one remain legacy-only.

## 8. Format routing

Website captured Markdown uses the 4.1C Markdown adapter; inline text and verified
TXT bytes use the plain-text adapter. PDF/DOCX bytes use the 4.1D adapter's isolated
child. Existing accepted upload extensions are unchanged. Unsupported formats,
unverified legacy file paths, invalid UTF-8, malformed/encrypted/rotated PDFs and
OCR requirements produce separate shadow failures, not permissive parser fallback.
`STRUCTURAL_DOCLING_MODEL_CACHE` is an optional server-owned path to the existing
checksum-verified local assets. No models are downloaded or imported into workers.

## 9. Source-version capture

Inputs come from READY, completed, scoped documents at the manifest's exact
version. Website sources reuse the captured `raw_text`; no recrawl or chunk
concatenation occurs. Uploads reuse the existing tenant-owned immutable object,
ownership validation and source-content hash. The source is captured using
`StructuralRepository.create_document_version` with immutable text or artifact
reference. Source IDs bind version plus SHA-256. Shadow revision IDs bind that
immutable identity plus format, parser implementation, serializer and tokenizer
recipes. Source/version ownership is rechecked before graph writes.

## 10. Structural revision lifecycle

Only existing `staging` then `validated` states are used, with shadow mode recorded
in the job audit. Validation does **not** mean serving activation or source-quality
approval. Parser quality remains unknown/manual-review where appropriate.
`activate_revision` is never called; active pointers remain untouched.

## 11. Graph staging

The existing repository stages nodes and edges in batches of at most 500 and
validates expected counts and the complete graph. No structural serving Chunk or
`chunk_structural_nodes` mapping rows are created. Graph plus successful audit
commit atomically. Failure rolls back the graph transaction; earlier immutable
source capture may remain as non-serving history. No existing constraint is weakened.

## 12. Serializer integration

The unchanged `structure-chunk-v1` serializer ends at prospective specs. Budgets
remain 450 target, 250–650 ordinary range, 800 hard maximum, 80 prefix and 60
overlap. Summaries retain graph/batch hashes, recipe and storage build fingerprint,
counts, token totals, coverage and kind statistics. Prospective mappings remain
in the transient validated batch, not fake chunk foreign keys. Stored repository
graph-seal hashes are not overwritten with prospective serialization hashes.

## 13. Shadow failure semantics

Per-document audit outcomes are running/validated/failed/cancelled, separate from
legacy status. Typed parser/serializer/cancellation categories are stored; unknown
exceptions become `SHADOW_OPERATION_FAILED`, without raw text or exception details.
Storage/audit outages leave the pending manifest and emit a safe identifier-only
error. An overall audit `complete` means attempts terminated; consumers must inspect
individual statuses, not treat completion as success. Cost flags do not fail ingestion.

## 14. Legacy-path independence

Legacy success plus shadow failure remains READY. Legacy failure does not trigger
shadow work or gain publication through it. No structural embedding call, vector
row, embedding quota reservation, provider call, resource projection, catalog
revision update or serving-cache identity change is introduced.

## 15. Idempotency

Same source/version and recipes select the same source/revision identities and
reuse validated graph counts. Changed parser/chunk recipe yields another build;
changed source/version yields another source and revision. The extra PostgreSQL
closure test initially exposed reuse of a recipe-only revision ID across source
versions. The ID derivation was corrected to include immutable source identity,
with two explicit offline regressions added. No repository/schema change was needed.

## 16. Restart behavior

The pending manifest commits with legacy promotion. A worker crash after source
capture leaves a repeatable running record. READY-job redelivery invokes only the
observer, not acquisition/embedding/promotion. A committed validated build is reused;
an interrupted graph transaction rolls back. No new retry queue is introduced.
Terminal shadow failures remain auditable and are not automatically retried forever.

## 17. Cancellation

Existing job cancellation status/request timestamp is checked before/after parse
and serialization and before graph persistence. The final successful audit checks
cancellation under the job row lock, serializing cancellation against graph commit.
Docling polls while waiting and kills/reaps only its owned child; it retains the
120-second ceiling. Markdown parsing is bounded and cancellation checked at phase
boundaries, not preempted at every parser node. No partial graph becomes active.

## 18. Concurrency

Two independently connected observers may parse concurrently, but the existing
scoped document lock, immutable source/build checks and constraints prevent duplicate
revisions/graphs. The job audit lock merges results and does not downgrade a prior
validated result due to a later duplicate failure. No distributed lock was added.

## 19. PostgreSQL behavior

Only the previously authorized disposable target was used through the existing
URL/application-target, empty-database, ownership and RESTRICT-cleanup guards.
PostgreSQL 18.6; pgvector package/runtime fixture version 0.8.6. No pre-existing
extensions were present in this test database; the existing harness created its
vector fixture extension inside its owned schema and removed only owned objects.
No application/Supabase/customer/production database was used.

## 20. Telemetry

Durable job audit includes scoped document/version/revision identity, mode, parser
and chunk policies, fidelity, start/completion timestamps, status/error category,
node/edge/spec/token counts, parse/serialization times, source bytes, structural
evidence coverage, unknown-role rate, quality and OCR/model policy. Unavailable
measurements are null rather than fabricated. It stores no raw text, private URLs,
API keys or database credentials. No new UI or customer-facing API was added.

## 21. Cost-review telemetry

Per-document and aggregate legacy/spec counts, token counts and ratios are retained.
Review thresholds are >1.5× chunks and >1.3× tokens. Saved-source totals:

| Measurement | Legacy | Structural shadow | Ratio |
|---|---:|---:|---:|
| Chunks/specs | 1,092 | 3,242 | 2.968864468864469 |
| Stored/serialized tokens | 212,061 | 278,491 | 1.3132589207822278 |

Both `STRUCTURAL_CHUNK_COUNT_REVIEW` and `STRUCTURAL_TOKEN_COST_REVIEW` remain set.
No embeddings or prices for embeddings were calculated.

## 22. Direct/integrated parity

For each saved source, direct adapter + serializer and integrated `build_shadow`
use the exact same immutable identity and policies. Complete canonical batch JSON
matches, covering source/graph hashes, nodes, edges, specs, tokens and recipes.
The offline replay uses synthetic ownership and no database. Synthetic PostgreSQL
tests separately validate the actual writer/job lifecycle.

## 23. Off-mode legacy parity

Tests execute ingestion from the committed E checkpoint and the current code on
separate owned SQLite fixtures. File and crawl document fields, chunk strings,
hashes, READY state, vectors and embedding invocation counts match. External
acquisition/embedding are deterministic test doubles; this is not live ingestion.

## 24. Shadow legacy-serving parity

The same comparisons pass with shadow enabled and with parser/serializer failure.
Failed file/crawl legacy runs do not shadow. Real PostgreSQL tests also compare
existing document/chunk rows and catalog counts before/after sidecar writes and
assert zero active shadow pointers and zero structural serving chunks/mappings.

## 25. Saved 23-page integrated replay

23/23 sources, 13,213 nodes, 6,700 edges, **3,242 specs / 278,491 tokens**, identical
to E. Structural node text: 894,386 bytes represented, zero unaccounted node bytes.
This is graph-evidence coverage, not a claim that Markdown syntax/spacing is evidence.
Final offline replay completed in 32.858 seconds; direct/integrated parity passed
23/23. This is a local transformation measurement, not production ingestion latency.

| Kind | Specs |
|---|---:|
| Prose | 1,525 |
| Heading | 754 |
| Commercial (`price_block`) | 405 |
| List | 259 |
| Directions | 105 |
| Review | 86 |
| FAQ | 78 |
| Timeline stage | 30 |

1,452 specs are <50 tokens; 3,188 touch at least one UNKNOWN-role primary node
(not necessarily exclusively UNKNOWN); zero contain inherited context only.
There are zero explicitly marked navigation/furniture specs and four analysis-only
link-dense candidates (at least three linked primary nodes, <100 tokens). No
candidate is discarded or reclassified. 3,156 adjacent complete small-unit pairs
fit a simple token sum but were kept separate by v1 unit/boundary rules; these are
overlapping theoretical candidates, **not** an asserted removable-chunk count.

## 26. Document-12 observation

Generic replay only: 1,072 nodes, 511 edges, 360 specs / 22,063 tokens versus legacy
103 chunks / 15,437 tokens. Ratios 3.495145631067961 and 1.4292284770356936; both flags.
98 heading specs, 227 tiny specs, 835 UNKNOWN-role text nodes; quality remains
unknown/manual-review. All 71,520 structural node bytes are represented. No runtime
ID/domain special case, deletion, blacklist, automatic quarantine or source rewrite.

## 27. Focused tests

Final focused F suite: **107/107 PASS**. Structural A/B/C/D/E: **510/510 PASS**
in the combined 601-test run before subsequent F-only additions, and included again
in canonical validation. Existing offline upload/tenant/security/exact-page tests
are included in the established canonical suite. No configured-DB legacy test suite
was launched against application data.

## 28. PostgreSQL results

Initial main acceptance: **32/32 PASS**, including actual migration upgrade,
downgrade/re-upgrade, valid indexes, source capture, graph staging, duplicate
idempotence/race, restart, cancellation, org/bot refusal and real PDF/DOCX.
PDF: 33 nodes / 11 specs / 88 tokens. DOCX: 42 nodes / 12 specs / 186 tokens.
Initial extra closure: 10 checks passed, then the source-version revision-ID
collision described above failed; guarded cleanup succeeded. After the scoped F
identity correction, final closure: **16/16 PASS**, including the six schema/index
checks, source-version/parser-recipe changes, a separate connection acquiring
document/job locks during parsing, and cancellation at the graph-commit boundary.
These are two successful runs (32 main and 16 closure), not 48 distinct scenarios.
All database runs verified owned schema/marker/tables/indexes absent,
unrelated objects unchanged, connections closed and process secrets cleared.

## 29. Complete-suite and final checks

Intermediate canonical suite: **2,693/2,693 PASS** (346.803 seconds; 2,593 prior +
100 F tests at that point). Final current-code canonical run: **2,700/2,700 PASS**
in **361.144 seconds**: all 2,593 existing tests plus all 107 F tests.
AST/import checks pass; migration head stays `20260916_01`, with no migration diff.
Frozen GOLD: 30 canonical fixtures load/validate; seven Docling raw-file hashes and
two E raw-file hashes match. Frozen text adapter, structural schema/repository,
serializer and source snapshot were not changed. Secret scan and `git diff --check`
pass. Network-denial guards wrap offline validation; zero live provider calls.

## 30. Limitations

Shadow is opt-in, synchronous after legacy publication, and consumes worker time
and sidecar storage. Bounds remain 1,000 manifest documents, 20 MiB source bytes,
existing parser/serializer limits, 500-row repository batches and Docling deadlines.
It is not a throughput or production-latency acceptance. READY-job redelivery is
the recovery mechanism; no new periodic retry service or UI was added. If audit
storage is unavailable, the durable pending record plus safe error log remains;
there can be no claim of a successful durable write during a DB outage. Old uploads
without verifiable owned immutable artifacts fail shadow only. Source-quality and
Docling extraction limitations from C/D/E remain visible; validated is not active.

## 31. Cost/scale decision status

Both review thresholds remain exceeded. The expansion comes from many complete,
short structural units and inherited literal context, including 754 headings and
405 commercial units. No content was removed to manufacture savings. No active
rollout or cost optimization is approved by this report.

## 32. Phase 4.1G boundary / final verdict

**SHADOW STRUCTURAL INGESTION VERIFIED. LEGACY SERVING PATH UNCHANGED.**
**NO STRUCTURAL EMBEDDINGS OR ACTIVATION. COST/SCALE REVIEW FLAGS PRESERVED.**
**READY FOR PHASE 4.1G ACTIVATION/CANARY DESIGN**, not activation itself.

Future separately authorized activation/canary design
must address cost/packing policy versioning, quality approval, embeddings, publication
and rollback, cache generation and operational limits. None is implemented here.
No structural embeddings/activation, retrieval or answer changes, production action,
deployment, F commit or push occurred.
