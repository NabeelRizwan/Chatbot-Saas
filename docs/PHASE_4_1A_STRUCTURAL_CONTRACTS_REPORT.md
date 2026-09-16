# Phase 4.1A — Structural contracts and STRUCTURAL_GOLD_V1

Date: 2026-09-16. Scope: provider-neutral values, hand-annotated offline GOLD,
metric helpers and tests only. Final canonical validation is recorded below.

## Design checkpoint

Starting branch/HEAD: `main`, `d036dc30b15f8daa6bdc8327c42a897a55d77c51`.
Initial status contained only the untracked Phase 4 design document. Its content,
secret-pattern scan and staged whitespace check were reviewed; only that file
was staged. No generated benchmark artifacts or runtime changes were included.

Design commit: **`973dcba87ecac6830a134715b6ef6290c54a28c7`**

Message: `Phase 4: add structural ingestion architecture design`.

The design commit is local only. Phase 4.1A implementation is **uncommitted**;
no push/deployment occurred.

## Files

Committed separately:

- `docs/PHASE_4_0_STRUCTURAL_INGESTION_DESIGN.md`

Current implementation/report changes:

- `backend/services/structural_document.py` — immutable validated contracts and canonical serialization.
- `backend/services/structural_metrics.py` — deterministic offline structural comparisons.
- `backend/scripts/structural_gold_v1.py` — loader for explicit, manually supplied annotations; not a source parser.
- `backend/fixtures/structural_gold_v1/real_sources.json` — 11 saved-source excerpts/annotations.
- `backend/fixtures/structural_gold_v1/synthetic_sources.json` — 8 non-commerce and 11 adversarial fixtures.
- `backend/fixtures/structural_gold_v1/manifest.json` — frozen source-file and normalized-fixture hashes.
- `backend/fixtures/structural_gold_v1/README.md` — provenance, annotation conventions and metric limitations.
- `backend/test_structural_contracts.py` — 160 focused tests.
- `backend/scripts/test_scoped_rag_regressions.py` — one-line registration of the new test module; existing suites/guards unchanged.
- `docs/PHASE_4_1A_STRUCTURAL_CONTRACTS_REPORT.md` — this report.

## Contract model

Uses the repository's existing Pydantic dependency; no new dependency or version
change. Frozen models, immutable tuples, forbidden extra fields, strict integer/
boolean/string values and closed vocabularies are validated on construction and
JSON deserialization. Schema identifier: **`structural-v1`**. JSON Schema is
available through `StructuralDocument.model_json_schema()` without an ORM.

| Contract | Invariants |
| --- | --- |
| SourceIdentity / RevisionIdentity / NodeIdentity | Required organization, bot, document, source-version ID/number/hash, revision and node key; no parser metadata merge |
| StructureRevisionDescriptor | Separate immutable source identity and processing recipe; parser/normalizer/chunker versions, configuration hash, format/fidelity, state and quality; build fingerprint excludes mutable lifecycle state |
| StructuralNode | Approved 12 physical types and 13 semantic roles; exact source text, typed attributes, provenance; key includes complete source identity, path, occurrence and content hash |
| SourceLocation / SourceSpan | Explicit UTF-8 half-open range, parser item, page/bbox or unavailable reason; mutually exclusive coordinates and nonnegative/ordered ranges; full source identity |
| StructuralEdge | Exactly CONTAINS, REFERS_TO, VARIANT_OF, DESCRIBES, HEADING_FOR, QA_PAIR; both endpoints fully version-pinned, same org/bot, located evidence for validated edges, method/version/basis/confidence/state |
| SourceQuality | Seven approved quality classes and three dispositions; reason codes, detector version, evidence and optional confidence; blocked/error/unknown classifications cannot assert acceptance |
| ChunkStructuralMapping | Same-source/revision node and chunk identity, ordinal, node/output byte slices, role and optional complete bundle/part identity; no chunk production |
| StructuralDocument | One document root, unique keys/preorders, exact same-revision parents preceding children, ordered leaves, complete-list count checks, local table/header integrity, local-edge integrity and mapping bounds |

Validation bounds follow the design: 10,000 nodes, 20,000 edges, depth 32. Parent
validation is linear plus canonical sorting, not retrieval traversal. Nodes,
edges and mappings serialize in explicit canonical order; dictionary insertion
order is irrelevant. Ordered list/stage content is not silently sorted away.

Small attribute models retain list completeness, table coordinates/headers/units,
commercial amount strings and explicit roles/conditions, quantity ranges/units/
frequency/qualifiers, timeline labels/order/qualifiers, and original link/anchor/
fragment with safety and resolution status. No role, currency, serving equivalence,
duration, result or relationship is inferred.

Relationships are **not authorization grants**. These DTOs neither establish
current READY/active status nor query access permissions. Both-endpoint scope,
lifecycle and database foreign-key enforcement remain later repository work.
Source text—including prompt-injection-like text—remains inert data. Runtime
instructions are not created or modified.

## STRUCTURAL_GOLD_V1 inventory and freezing

**30 fixtures, 146 nodes, 17 explicit edges.** Eleven exact saved-source excerpts
contain **3,662 UTF-8 bytes**, not a replay or structural conversion of the 23-page
real corpus. Full-source SHA-256/version and excerpt-byte positions are recorded;
no source crawler metadata, vectors, customer answers or grades are copied.

| Group | Fixtures |
| --- | --- |
| Saved source: full enumerations | Joint Support seven ingredients; Collagen Complex five source/types; MyCovital four mushrooms |
| Saved source: associations | Anti-aging review→MyCovital; anti-aging review→Chocolate Collagen; three Chocolate Collagen timeline stages with heading/body and qualifications |
| Saved source: typed values/quality | Resveratrol offer/amount blocks; MyCovital scoop/gram/daily directions; plain collagen scoop/oz-range directions; canonical fragment link; blocked tail within mixed parent source |
| Non-commerce (8) | Hotel features/breakfast/check-in/out/cancellation; software plan price/storage/renewal; course syllabus/duration/certificate; nested legal sections/qualification; table headers/units/repeated rows; FAQ pairs; two reviews with distinct targets; qualified ordered timeline |
| Adversarial (11) | Repeated text; duplicate headings; malformed Markdown; unavailable location; ambiguous link; unsafe scheme; long list item; long table cell; navigation near content; review near unrelated link; embedded instruction-like text |

All annotations are manual expected values. The loader checks the declared exact
substring; it does not discover structure, run a quality detector, resolve links
or infer identity. Real source IDs appear only in test fixtures.

Each normalized document and both source files have frozen SHA-256 values in the
manifest. Tests never regenerate them. Manifest file SHA-256 (LF-normalized):
`0236aa9164f322c3c2cdb6c10612620df4662e6ff88af50ef21a83099062e940`.

## Structural metric helpers

Comparison uses normalized source-pinned node identities, parent membership and
explicit validated relations. Precision and recall are separate; a missing
denominator is **N/A**, not 100%. Wrong or missing associations are penalized.
Commercial/quantity/timeline comparisons include explicit DESCRIBES targets.

| Metric | Gold annotations available |
| --- | ---: |
| Heading/body pairs | 11 |
| Complete lists | 8 |
| Review→resource relations | 4 |
| Price/role tuples | 7 |
| Quantity/unit/frequency tuples | 6 |
| Ordered timeline stages | 5 |
| Safe canonical-link representations | 8 |
| Text-node provenance records | 91 |
| Document quality records | 30 |
| Collection-positive relations | 0 — N/A, not a demonstrated capability |

Self-round-trip retains every annotated feature exactly. **This is contract
fidelity, not measured extractor accuracy.** Ninety of 91 text nodes have located
provenance; the deliberate unavailable-location adversary is faithfully retained
but scores zero located coverage. Mutation tests detect heading/list/edge loss,
wrong review/price targets, role/frequency/qualifier changes and missing links.

Serialization coverage measures unions of node-local byte ranges in asserted
mapping DTOs; overlaps cannot inflate coverage. Dedicated tests cover no mapping,
partial mapping, full coverage and overlap. No actual chunks/mappings are generated
for GOLD; rendered-content fidelity and token limits cannot yet be accepted.

## Validation

Working directory for Python commands: `backend`.

| Check | Result |
| --- | --- |
| Focused: `.venv/Scripts/python.exe -B -W ignore::DeprecationWarning -m unittest test_structural_contracts` | **160/160 PASS**, 0.202 s |
| Initial canonical run, before additional boundary tests | **2206/2206 PASS**, 219.980 s (2083 existing + 123 then-new) |
| Final canonical: `.venv/Scripts/python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py` | **2243/2243 PASS**, 175.117 s (**2083 existing + 160 new**) |
| Applicable existing regression suites | Included unchanged in canonical run: Phase 3.7/planner, ingestion/crawl, scope, authorization, retrieval and prior phases |
| AST + isolated imports + JSON Schema export | PASS; five Python files parsed, 30 fixtures loaded; no new dependency or bytecode output |
| Frozen source/DTO hash and exact source-slice validation | PASS |
| Independent local saved-snapshot comparison | **11/11 PASS**: full-source hash, excerpt byte slice, source URL and version |
| Secret-pattern scan | PASS; no credentials or private source metadata in deliverables |
| `git diff --check` plus untracked-file whitespace checks | PASS |

An initial smoke invocation from the repository root could not import `services`;
the same check run from the required `backend` directory passed without any code
change. Existing suite output includes Redis-unavailable fallback warnings; these
did not fail tests. Configured application DB and live HTTP/provider paths remain
blocked by the existing canonical runner.

Preservation gate compared 588 previously existing tracked/real-corpus JSON files:
only the explicitly authorized test-runner registration changed. The saved source
snapshot, REAL_CORPUS_V1_EVAL_V1, saved answers/traces and grades remain byte-for-byte
unchanged. No database connection was needed for fixture preparation or preservation.

## Clarifications and known limitations

- The design leaves concrete DB key datatypes and some attribute enums open.
  V1 uses positive numeric tenant/document IDs, opaque version/revision names,
  decimal strings and a small explicit commercial-role enum. Unknown units are
  preserved verbatim; unknown currency/role is not inferred. No database schema
  choice is implied by these transport types.
- Synthetic fixture annotation positions are Unicode character offsets; only
  the fixture loader converts them to source UTF-8 bytes. Runtime contracts
  never label character or legacy enriched-token offsets as source bytes.
- Resveratrol's concatenated amounts lack sufficiently explicit individual
  price roles/currency in saved Markdown. Parent offer labels are preserved;
  assigning regular/sale meanings would fabricate structure. Roles remain unknown.
- Link validation checks representation/scheme consistency only. It is not DNS,
  canonical URL resolution, SSRF validation, fetching or authorization. Unsafe or
  ambiguous original links are retained without invented target edges.
- Model validation is the supported ingress; Pydantic's explicit construction/
  copy bypass APIs are not authorization boundaries. Future repositories must
  supply ownership from trusted server scope, not from source metadata.
- Cross-document target existence, current permissions and active source/revision
  require future repository checks. DTOs retain exact identities but cannot prove
  the referenced external row exists or is currently servable.
- Metrics assume explicit aligned source/path keys. Future adapters using a
  different path convention need reviewed alignment, not semantic winner picking.
- No Docling adapter, extraction accuracy, quality-detector confusion matrix,
  PostgreSQL constraints, live concurrency, rendered-chunk reconstruction,
  embedding cost or end-answer improvement has been evaluated here.

## Remaining Phase 4.1B work — not started

Design/implement additive version/revision/node/edge/mapping schema and scoped
repositories with composite ownership/version foreign keys, uniqueness, parent/
order checks, and disposable PostgreSQL concurrency/rollback/query-plan tests.
Runtime ingestion hooks, extraction/Docling, chunk serialization, embeddings,
activation and later retrieval phases require their own later authorization.

**Runtime ingestion, crawler, database models/migrations, chunking, embeddings,
FTS/RRF, query understanding, reviewer, generation, prompts and providers are
unchanged.** No real-corpus reprocessing, provider calls, production/Railway
access, live chatbot test, push or deployment. No Phase 4.1B or later work started.

## Final verdict

**PHASE 4.1A — COMPLETE**

**STRUCTURAL CONTRACTS AND GOLD FROZEN**

**READY FOR PHASE 4.1B SCHEMA DESIGN/IMPLEMENTATION**

Final branch/HEAD remains `main`, `973dcba87ecac6830a134715b6ef6290c54a28c7`.
Working tree intentionally contains the nine new implementation/fixture/report
files and the single test-runner registration edit listed above. Nothing from
Phase 4.1A is staged or committed.
