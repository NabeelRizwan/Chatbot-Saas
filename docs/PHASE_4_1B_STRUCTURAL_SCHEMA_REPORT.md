# Phase 4.1B — structural PostgreSQL storage and scoped repository

Date: 2026-09-16. Branch: `main`.

**PHASE 4.1B — COMPLETE.** Structural PostgreSQL schema and scoped repository
verified. Phase 4.1B remains uncommitted for review; nothing was pushed/deployed.

## 1. Phase 4.1A checkpoint

Committed locally: `f83745bbe0c03eec20b9415153cf8ede9c6df1e1`.

Message: `Phase 4.1A: add structural contracts and frozen structural gold`.
The checkpoint contains exactly the ten previously reviewed Phase 4.1A files;
the index was empty before staging, the secret/whitespace audit passed, and
160/160 focused tests passed. The working tree was clean after that commit.
No push. Phase 4.1B is intentionally **uncommitted**.

## 2. OSS implementation research ledger

The accompanying `PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` records official source
files, pinned upstream commits, license links, adaptations and rejected
assumptions for Docling Core, RAGFlow/DeepDoc, LlamaIndex, Haystack and Onyx.
Implementation source—not documentation alone—was inspected before this slice.

## 3. Copied/adapted/reimplemented code provenance

**Literal source reuse: NO. Pattern adaptation: YES.** No upstream framework was
installed. The implementation is specific to the frozen Phase 4.1A DTOs and the
existing application's authorization/transaction boundaries. Local composite
resource FKs and the unchanged disposable PostgreSQL harness are reused as
implementation precedents. No copied code requires additional license notices.

## 4. Upstream licenses reviewed

- Docling Core / MIT: representable item identity, provenance, source origin and
  exact serialization. No Docling integration or dependency.
- RAGFlow / Apache-2.0: separate parser/source/indexing metadata and lifecycle;
  retain typed table/QA relationships and source positions. No parser execution.
- LlamaIndex / MIT: explicit parent and semantic endpoint identity, strengthened
  here with composite tenant/document/version/revision FKs. No auto-merging.
- Haystack / Apache-2.0: source versus split/revision identity and deterministic
  ordering. No splitting or sentence-window retrieval.
- Onyx / MIT outside separately licensed enterprise directories: content/source
  metadata is distinct from access context. No enterprise ACL code copied.

PostgreSQL/SQLAlchemy references and pinned license links are in the ledger.

## 5. Files changed in Phase 4.1B

- `backend/database/models.py`: three nullable compatibility columns only.
- `backend/database/structural_schema_v1.py`: frozen sidecar DDL and guards.
- `backend/migrations/versions/20260916_01_structural_sidecar.py`: new migration.
- `backend/services/structural_repository.py`: scoped persistence/lifecycle API.
- `backend/test_structural_repository.py`: offline boundary tests/fixtures.
- `backend/scripts/test_phase41_structural_postgres.py`: real PostgreSQL checks.
- `backend/scripts/test_scoped_rag_regressions.py`: new offline test registration.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md`.
- `docs/PHASE_4_1B_STRUCTURAL_SCHEMA_REPORT.md`.

No historical migration, Phase 4.1A DTO/gold, dependency, ingestion, retrieval,
planner, reviewer, generation, prompt, provider or production configuration edit.

## 6. Migration/schema

New head `20260916_01`, parent `20260912_01`. PostgreSQL only; no backfill or
automatic application startup migration. Apply the additive migration before
running code that maps the new nullable columns in a future authorized release.

## 7. Table definitions

| Table | Representation / relational identity |
| --- | --- |
| `document_versions` | Immutable captured source: org/bot/document, opaque version ID, source version, optional website/crawl, identity/URLs, format/MIME/fidelity, full SHA-256, capture time, owned text/artifact reference. |
| `document_structure_revisions` | Immutable processing recipe and build fingerprint, source reference, schema/parser/normalizer/chunk-policy/configuration versions, optional scoped job, quality, lifecycle, expected/actual counts, source/normalized/serialization hashes and timestamps. |
| `structural_nodes` | Source/revision-pinned node key, parent plus parent order/depth, preorder/leaf order, type/role, exact text, nullable display text, typed attributes/provenance/quality and content hash. |
| `structural_edges` | Full pinned endpoints, relation, field/role, provenance including method/version/basis/confidence, validation state, deterministic application key and DB-computed logical identity. |
| `chunk_structural_nodes` | Existing chunk and node ownership/version/revision, ordinal, node/output byte slices, mapping role and optional bundle/part identity. |

Compatibility fields: `Document.active_structure_revision_id`,
`Chunk.document_version_id`, `Chunk.structure_revision_id`. All nullable. Legacy
NULL rows remain valid. No repository method creates chunks, tags existing
chunks, changes their READY state, or activates a resource catalog.

Upgrade accepts correctly typed nullable columns already created by baseline
model metadata, but refuses incompatible existing definitions. Tables and
constraints are additive. Empty-sidecar downgrade removes only the new objects
and columns and retains legacy data. **Populated downgrade refuses to destroy
history**; rollback of deployed application behavior must not silently drop it.

## 8. Relational invariants

Composite FKs pin parent, node, edge, mapping and active-pointer identities to
org/bot/document/source version/processing revision. Partial unique source
indexes distinguish uploads with NULL crawl IDs from crawl captures. Conflicting
immutable source identities cannot overwrite existing rows.

Parent references also pin the parent's preorder/depth. A child must have a
different key, a greater preorder and depth exactly parent depth + 1; depth is
at most 32. Only a document root can be parentless, at preorder/depth zero.
Unique order plus the nonnegative decreasing parent chain gives one root and
acyclicity without recursive write-time graph scans. Node positions cap at
10,000; edge ordinals cap at 20,000.

## 9. PostgreSQL constraints and guards

Staging payloads are append-only/idempotent. Source identity cannot be updated
or individually deleted while its document exists. Sealed revisions and payloads
reject mutation/deletion; whole-document purge integration is not added here.
Heading/QA endpoint types and tree-edge duplication are checked by PostgreSQL;
the frozen DTO validates remaining structural/typed relationships before sealing.

The edge trigger computes SHA-256 over the full endpoint/kind/field/role/evidence
identity, excluding confidence and validation state. A fixed-size unique index
prevents duplicates even with a forged application edge key, without indexing
four long Unicode revision names together. Reusing a logical edge with changed
immutable provenance/confidence is a conflict, not an update.

Mappings require both an existing matching chunk and matching node. Slices must
be nonnegative, ordered, within node/output byte lengths and on UTF-8 boundaries.
Mappings never grant access to a target source.

## 10. Indexes

Indexes cover scoped source-version lookup (upload/crawl partial uniqueness),
revision state/one active revision, child order, node lookup, outgoing/reverse
edges, logical edge uniqueness, chunk/ordinal and node-to-chunk mappings. No
broad JSONB GIN index was added. All installed structural indexes were valid.

## 11. Repository API, scope and bounds

`StorageScope` is immutable, server-owned management scope: positive org/bot IDs
and 1–10,000 explicit permitted document IDs. It is **not an authorization
service or client-supplied permission proof**. No routes expose these methods.

| API | Boundary |
| --- | --- |
| `create_document_version`, `get_document_version` | Single owned source identity; explicit text/artifact fields, no arbitrary metadata merge. |
| `create_structure_revision`, `get_structure_revision` | Owned immutable source and recipe; identical fingerprint reuses the original revision. |
| `stage_nodes`, `stage_edges`, `stage_chunk_mappings` | Revalidated frozen DTOs, exact matching identity, staging only, batches at most 500. |
| `get_node` | Requires scoped document and revision as well as node key. |
| `list_nodes_bounded`, `list_edges_bounded` | Explicit limit at most 256; deterministic keyset order; both edge endpoints intersect management document scope. |
| `list_chunk_mappings_bounded` | At most 64 supplied chunk IDs and 256 returned mappings, ordered by chunk/ordinal. |
| `load_revision_bounded` | Explicit management snapshot bounds: 10,000 nodes / 20,000 edges / 100,000 mappings; overflow is an error, not silent truncation. |
| `validate_revision_counts`, `mark_revision_validated` | Exact counts, full DTO validation and canonical hashes before sealing. |
| `activate_revision`, `mark_revision_failed`, `mark_revision_cancelled` | Owned transactional lifecycle; no internal commit. |
| `list_active_nodes` | Explicit profile and `HardKnowledgeScope`; single-statement eligibility intersection with mapped READY chunks. |

Node writes use bounded multi-row INSERTs. Edge hydration uses a bounded pair of
bound arrays, not an unbounded OR-expression or one source fetch per edge.
Identity hydration projects six identity fields, never the source artifact/text.
Explicit management source reads still return the requested captured source.
There is no graph traversal, recursive expansion, N+1 **read hydration**, or
unbounded normal node/edge listing. Edge/mapping writes remain bounded per-row
operations; this slice makes no high-throughput ingestion claim.

## 12. Tenant isolation

Ownership comes from trusted scope and current database documents, never source
text, parser output, URL metadata or model output. SQL values are bound. DTOs are
revalidated even if constructed using Pydantic bypass methods.

## 13. Version isolation

Parent, edge and mapping endpoints are pinned to immutable source and processing
revision IDs, not names or text similarity. Source and processing versions are
separate; reprocessing never silently retargets an old edge. PostgreSQL rejects
cross-version/cross-revision parents and mappings, including existing foreign
revisions rather than testing only nonexistent IDs.

## 14. Lifecycle and serving eligibility

Management APIs can inspect owned staging/history. They must not be exposed as
customer serving APIs. `list_active_nodes` additionally uses the **existing**
`knowledge_scope.ready_chunks` predicates: org/bot/document/source ACL, document
READY/completed, chunk READY, active website/crawl/version and explicit embedding
profile. It joins the current structural pointer and matching immutable source
and only serves mapped, non-quarantined nodes. These checks happen in the same
SQL snapshot as the node-text read, rather than trusting previously hydrated IDs.
No semantic relationship expands permission. No serving edge-traversal API exists.

## 15. Activation transaction

Each write acquires the owned document row lock before revision locks. Activation
checks expected current source version **and** expected prior structural pointer,
requires validated current source/crawl and accepted quality, supersedes the old
active revision, activates the new revision and changes the document pointer in
one caller-owned transaction/savepoint. A partial unique index permits only one
active revision. Deferred constraint checks require final pointer/state agreement.

## 16. Concurrency and rollback

Real two-connection tests hold the document lock while another worker attempts
activation: exactly one commits; the loser receives `StructuralConflict`. Rollback
restores the previous active state/pointer. Failed/cancelled revisions cannot
activate. No chunk status/content or catalog promotion accompanies activation.

## 17. Idempotency

Same source/hash and same build fingerprint are idempotent; repeated node/edge/
mapping batches do not duplicate data. Changed parser/configuration yields a new
processing revision without mutating the captured source. Sealing records counts,
normalized content hash and the canonical **validated DTO snapshot** hash;
subsequent lifecycle transitions do not rewrite that snapshot hash.

## 18. Query plans

Final full-run fixture: 22 captured sources, 25 revisions, 1,139 nodes, 24 edges
and 2 mappings; the child-query hierarchy contains 1,025 nodes.

| Scoped bounded query | Natural plan / index | Rows returned / filtered out | Planning / execution ms | Shared hits / reads |
| --- | --- | --- | --- | --- |
| Children: org/bot/document/revision/parent, preorder cursor, ORDER BY preorder LIMIT 20 | Limit → Index Scan `ix_structural_nodes_children` | 20 / 0 | 0.269 / 0.050 | 6 / 0 |
| Outgoing edges: org/bot/revision/from-node + permitted target documents, ORDER BY edge key LIMIT 20 | Limit → Sort → Seq Scan (24-row table) | 1 / 23 | 0.194 / 0.041 | 4 / 0 |
| Reverse edges: org/bot/target revision/node + permitted source documents, ORDER BY edge key LIMIT 20 | Limit → Sort → Seq Scan (24-row table) | 2 / 22 | 0.215 / 0.054 | 4 / 0 |
| Mappings: org/bot/bounded chunk set, ORDER BY chunk/ordinal LIMIT 20 | Limit → Sort → Seq Scan (2-row table) | 1 / 1 | 0.173 / 0.035 | 1 / 0 |
| Active revision: scoped document/current pointer joined to owned active revision, LIMIT 1 | Limit → Nested Loop → Index Scans `ix_documents_id`, `document_structure_revisions_pkey` | 1 / 0 | 0.288 / 0.062 | 4 / 0 |

All loops were one. No unexpected large sequential scan. No planner switch or
forced-index plan was used. Full SQL query shapes and EXPLAIN capture are in the
disposable test script. These warm-cache PostgreSQL execution measurements do
not include remote round trips and are **not production latency/capacity claims**.

## 19. Phase 4.1A persistence round-trip

Eight frozen **synthetic** Phase 4.1A domains are persisted/reloaded: hotel,
software plan, course, legal policy, table, FAQ, reviews and timeline. Canonical
DTO equality covers identity, source spans, attributes, semantic edges, quality
and revision descriptors. Additional fixtures cover chunk mappings, repeated
identical text at distinct paths, multiple versions/revisions, and maximum-length
Unicode version IDs. No real saved-source fixture was inserted into PostgreSQL.

## 20. Focused PostgreSQL and offline tests

| Validation | Result |
| --- | --- |
| Phase 4.1A checkpoint gate | 160/160 PASS, 0.208 s |
| Final focused contracts + repository boundary tests | 182/182 PASS (160 existing + 22 new), 0.366 s |
| Full real PostgreSQL acceptance | 114/114 checks PASS, 567.975 s including remote setup/cleanup |
| Final real PostgreSQL metadata-only read smoke | 11/11 PASS (6 repeated migration/index checks + 5 targeted read checks), 170.197 s |
| Final complete canonical suite | 2,265/2,265 PASS (2,243 existing + 22 new), 254.477 s |
| Targeted existing ingestion/authorization/scope regressions | 65/65 PASS, 5.191 s; application DB and live HTTP blocked |
| AST/import smoke and migration graph | PASS; single head `20260916_01`, parent `20260912_01` |

The full PostgreSQL run includes the final schema, long-UTF-8-ID boundary,
bound-array edge hydration, all FK/lifecycle/mapping/race/round-trip checks and
query plans. The subsequent smoke specifically validates the last identity-only
projection adjustment on real PostgreSQL; no runtime change followed that smoke.
The PostgreSQL scripts report individual assertions/checks (not unittest method
counts), whereas the offline counts are unittest tests.

## 21. Complete canonical suite result

**2,265/2,265 PASS**, including every existing 2,243 test and all 22 new offline
repository tests. Earlier development runs also passed (2,263 and 2,264 tests as
coverage was added); they are not substituted for the final result. Expected
Redis-unavailable fallback messages appeared, with no test failures or Redis
configuration change. The REAL_CORPUS_V1 90-case live benchmark was not run.

Commands from `backend`, using the existing local virtual environment:

```text
.venv/Scripts/python.exe -B -W ignore::DeprecationWarning -m unittest test_structural_contracts test_structural_repository
.venv/Scripts/python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
.venv/Scripts/python.exe -B scripts/test_phase41_structural_postgres.py
.venv/Scripts/python.exe -B -c "from scripts.test_phase41_structural_postgres import main; raise SystemExit(main(read_smoke=True))"
```

Remote commands require the already-authorized disposable URL and opt-in only
in the process environment. No secret value is part of these documented commands.

Validation also includes migration graph, AST/import smoke with application
connections prohibited, tracked/new-file whitespace checks, secret-pattern scan,
and preservation hashes. Legacy Phase D/H and Phase I scripts that directly
initialize the configured database were not run against it; relevant offline
ingestion/auth/scope regressions and the new disposable lifecycle checks are used
instead. No test database safety guard was bypassed.

## 22. Migration graph status

PASS: one Alembic head `20260916_01`, parent `20260912_01`. AST and isolated
model/repository imports passed with application connections prohibited. Actual
upgrade, empty downgrade, re-upgrade and populated-downgrade refusal were tested
in the owned PostgreSQL schema. Historical migration files are unchanged.

## Disposable database and cleanup

PostgreSQL `18.6 (Debian 18.6-1.pgdg12+2)`; owned fixture vector extension `0.8.6`.
Only the user-confirmed disposable test target was authorized through session
environment variables. The unchanged Phase 3.1 harness rejects configured
application endpoints, existing user objects, stale owned schemas and competing
runs. It uses a unique schema, owner/marker/OID checks, explicit registration and
RESTRICT cleanup. Synthetic fixtures include three organizations and five bots
(two bots in each principal isolation-test organization).

Only fixed Phase 4 trigger/functions in the owned schema are removed before the
existing harness cleanup; tables/indexes/marker/schema are then ownership-checked
and removed. Unrelated objects must compare exactly to the preflight snapshot.
Extensions already present are retained; a vector extension prerequisite created
only inside the owned disposable schema is removed with ownership checks.

**Cleanup PASS for both the full run and final smoke**: owned schema absent;
marker/tables/indexes absent; unrelated objects unchanged; existing extensions
retained. Connections closed and engines disposed. The two temporary test
environment variables were removed by the child-process `finally` block before
exit; neither was saved in a file. Secret-pattern and whitespace checks passed.

During development PostgreSQL exposed an invalid immutable-index expression; it
was repaired in this new schema, ultimately replaced by trigger-computed bounded
SHA-256 identity. A reverse-edge test initially forgot the fixture's existing
local heading edge; the expectation now checks both returned document IDs and
separately checks restricted access. Every completed development run verified
owned cleanup, including those that failed before acceptance.

## 23. Preservation and limitations

- Preservation audit hashes 597 pre-existing tracked/source/corpus-snapshot files.
  Only the intended model and runner-registration files differ. Frozen DTOs,
  GOLD, corpus snapshots, old migrations and accepted Phase 3.7 code are unchanged.
- No persistent application/customer/Supabase DB migration or corpus write; no
  provider call, crawl, parse, ingestion, re-embedding, production action,
  deployment or push. The database secret is not in code, files or reports.
- This is a persistence foundation, not evidence that chatbot answers improve.
  Source parsing/semantic correctness and actual source-artifact custody remain
  adapter/ingestion responsibilities; a stored span is not an extraction proof.
- No runtime ingestion hook, structural chunk generation, publication/cache
  transition, graph traversal, retry/retention scheduler or end-user API is added.
  Sealed history is intentionally restrictive: future deletion/retention work
  must coordinate owned chunk/mapping/source cleanup before enabling integration.
- Large-history throughput/storage sizing and byte-admission budgets are not
  benchmarked. Reads/writes have explicit row/batch bounds, not production SLOs.
- The **new migration** is tested on its prerequisite schema, including legacy
  absent columns and pre-created compatible columns. The entire historical fresh
  bootstrap chain is not claimed tested: the old baseline imports current model
  metadata while the older resource migration unconditionally creates resource
  objects/unique constraints. That pre-existing interaction needs a separate
  bootstrap review; historical migrations were deliberately not changed here.

## 24. What remains for Phase 4.1C

The deterministic Markdown/text adapter: produce these frozen DTOs, preserve
source spans/identity and typed hierarchy, abstain on ambiguous semantics and
validate against frozen structural gold. No Phase 4.1C implementation, Docling
installation, live corpus reprocessing or ingestion/retrieval hookup was started.

## Final verdict

PHASE 4.1A CHECKPOINT — COMMITTED

`f83745bbe0c03eec20b9415153cf8ede9c6df1e1`

PHASE 4.1B — COMPLETE

STRUCTURAL POSTGRESQL SCHEMA AND SCOPED REPOSITORY VERIFIED

OSS IMPLEMENTATION REFERENCES RECORDED

READY FOR PHASE 4.1C DETERMINISTIC MARKDOWN/TEXT ADAPTER

Final branch/HEAD: `main`, `f83745bbe0c03eec20b9415153cf8ede9c6df1e1`.
Exactly the nine Phase 4.1B files listed above remain uncommitted; index empty.
No Phase 4.1B commit, push, deployment or Phase 4.1C work.
