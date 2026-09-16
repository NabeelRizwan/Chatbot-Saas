# Phase 4.1H — Offline structure-chunk-v2

Date: 2026-09-16. Scope: local deterministic selection/packing only.
No activation, embeddings, serving chunks, persistent database, retrieval changes,
customer questions, provider calls, deployment or push.

## Checkpoint and scope

Phase 4.1G was audited and committed locally as
`6f797efe34bf91391906fd9a44137ca5ee999b5f`:
`Phase 4.1G: design structural activation and canary strategy`.
Parent F: `627be0338fc3f471833f75cf985c1b36e60ada28`.
Only its four recorded analysis/test/ledger/design files were committed, after
scope/secret review and `git diff --check`. The tree was clean afterward.
H remains **uncommitted**, based on that G checkpoint.

H files:

- `backend/services/structural_selection_v2.py` — isolated offline policy and immutable DTOs.
- `backend/scripts/structural_chunk_gold_v2.py` — deterministic synthetic fixture/query witnesses.
- `backend/fixtures/structural_chunk_gold_v2/cases.json` — frozen hand-authored expectations.
- `backend/fixtures/structural_chunk_gold_v2/manifest.json` — expectation checksum/contracts.
- `backend/scripts/evaluate_structural_selection_v2.py` — saved-file-only evaluator/cost math.
- `backend/test_structural_selection_v2.py` — focused tests.
- `backend/scripts/test_scoped_rag_regressions.py` — register H and previously separate G tests only.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — H source study.
- This report.

No existing runtime serializer, shadow observer, processing service, worker,
repository, database model/migration, legacy chunking or RAG file was changed.
No application runtime imports the new selector.

## OSS source study

Actual source was inspected before implementation; current default-branch commits
were resolved. Details, paths, functions, licenses, adaptation and rejection are in
the H section of the [implementation ledger](PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md).

| Project | Inspected revision | Adaptation / deliberate boundary |
|---|---|---|
| Docling Core | `1259eba96b8fefeadc4313f8c1af5c7304c28256` | Inherited headings, optional independent headings, contextualized token budget and metadata-compatible peers. We require stronger source/subject proof. |
| RAGFlow | `701b82aa1e6baf4e79fd253658cc2e045b1655eb` | Nonsearchable parents versus searchable children. No datastore or text-hash identity copied. |
| LlamaIndex | `fd4a517ad6490f0c8464a13fdf133760b696434a` | Explicit hierarchy and separate leaf selection. No AutoMerging retrieval/score substitution. |
| Haystack | `0defdcff64950ca54f4dac0d21fe4eb30ed745d7` | Parent/child/root metadata retained independently of embedding choice. No assumption all splitter levels must be embedded. |
| Onyx | `a8804f2b8869499bb6f4932195a06575974debfe` | Section payload/context separation and bounded accumulation. No cleaned-text mapping, cross-section identity inference or indexing integration. |

Literal code reused: **NO**. Patterns adapted: **YES**. No new dependency.
Docling/LlamaIndex: MIT; RAGFlow/Haystack: Apache-2.0; Onyx: MIT Expat outside `ee`.
Source-research network reads were separate from all offline evaluation/tests.

## Architecture, identity and ledger

Frozen `SerializationBatch` (complete structural graph + v1 specs) → versioned
`Selection` → offline `Candidate` values. There is no writer or embedding caller.
The input batch remains referenced immutably; exported selection JSON records its
hash and must be paired with that input (or its exactly reproducible saved source).

Policy is `structure-chunk-v2`, rule version `conservative-selection-1`; its recipe
binds v1 recipe, v2 policy, label/role rules and qualification pattern. Candidate
keys bind this recipe, ordered original member IDs, exact text and translations.
Input/graph/selection hashes distinguish content/revision and policy. v1 remains
`structure-chunk-v1`, with unchanged code, caps, GOLD and serialization hashes.

Every v1 spec has exactly one ordered ledger entry: `embedded`, `metadata_only`,
`packed`, or `unresolved`. No DROP state. Entries include reason, candidate ID,
prefix disposition, heading dependencies and, for metadata-only headings, exact
source-identity/range/role witnesses into one retained descendant. Candidates
record a translation for **every** original logical mapping, even shared output
bytes. Verification checks exact UTF-8 bytes, ownership, candidate keys, complete
membership, heading association, graph accounting and token/mapping bounds.

Graph-only means a node has no selected **primary** mapping; it is not deleted.
It may still supply inherited context. All nodes, relationships, attributes,
source/version/revision ownership, provenance, v1 exclusions and lineage remain.
The distinction does not grant permission to index or activate unknown-quality
knowledge.

## Heading and discoverability policy

Only a closed set of generic hierarchy labels (e.g. Ingredients, Details, Price)
with UNKNOWN semantic role, no typed attributes/semantic relationships and no
independent numeric/question/qualification content can be considered redundant.
Classification strips only leading Markdown heading syntax, never source bytes.
All original mapped heading/context slices must coexist as inherited mappings
in **one non-heading descendant** with the exact node/range/role identities.
Equal text elsewhere is insufficient. No eligible descendant means keep embedded.

Titles, orphan headings, independent assertions, questions, numbers, qualifiers,
protected roles and uncertain labels remain independently selected. Duplicate
same-text headings under different parents retain separate identities and witnesses.

This is deliberately stricter than G's exploratory simulation. G proved byte
coverage and body inheritance but did not establish independent-answerability
equivalence for every heading it hypothetically suppressed. H does not turn all
606 hypothetical removals into production policy: only 10 satisfy its proof.
The other 596 stay selected. G artifacts/results were not revised.

## Peer packing and prefix sharing

Packing requires consecutive v1 prose specs **and actual adjacent source siblings**,
same document/version/revision, one nonempty parent, same nonempty heading path,
and exactly one equal **validated DESCRIBES target** on their source/ancestor paths.
No inference from a title, nearest heading or repeated text. UNKNOWN is not identity.
Role, effective quality, typed attributes, semantic edges, qualifiers and complete
single-part units are checked. Lists/tables/reviews/FAQ/timelines/commercial units
are atomic and do not enter prose packing. Crossing any boundary is refused.

Caps remain 450 target / 250–650 merge range / 800 hard / 80 prefix / 60 overlap.
Packing is allowed below target for proven tiny peers, never because size alone
implies equivalence. Full candidate text must fit 650; mappings ≤256, selection
candidates ≤10,000 and logical translation total ≤100,000.

Only the **entire identical inherited heading prefix** may be shared within one
eligible packed candidate. Source node/revision, source/output ranges, role, usage
and exact bytes must all match. Different occurrences, qualifiers, table headers,
reviews, commercial conditions and overlap spans are not deduplicated. Every
logical association retains its own translation. No cross-candidate deduplication.

Synthetic explicit-subject tiny peers pack into one candidate with one shared
prefix; missing identity yields separate selected `unresolved` candidates.
The fixture partitions already merged v1 prose into verified lossless unit DTOs
to exercise this interface. It does **not** claim today's v1 emits those tiny units
separately. Actual saved-corpus packed groups and prefix deduplications: **zero**.

## Tiny and atomic-unit outcomes

All 1,452 v1 tiny specs have deterministic reason/axis records in the local output:
kind, role, parent, explicit subject, effective quality, qualifier, relationships,
heading/context dependencies, prefix disposition and outcome. No manual labeling.

| Tiny reason | Count |
|---|---:|
| Atomic directions / FAQ / list / commercial | 57 / 3 / 160 / 229 |
| Proven descendant heading → metadata-only | 10 |
| Independent heading | 87 |
| Protected heading | 95 |
| Uncertain heading answerability | 453 |
| Prose without proven peer | 355 |
| Unknown identity, retained unresolved | 3 |

All 405 commercial specs remain independent with their original 516 UNKNOWN-role
annotations; no price role inferred. List membership/parts, table cell/header
associations, review attribution/REFERS_TO, FAQ pairing, timeline stage metadata,
quantity/frequency, qualifications and link metadata remain in the unchanged graph
and mappings. Tests additionally exercise explicit different review resources,
non-title qualification/numeric/assertion headings and UTF-8 source ranges.

## Frozen GOLD and offline discoverability proxy

`STRUCTURAL_CHUNK_GOLD_V2`: 18 hand-authored cases; 22 query labels; 24 source-node
witnesses (including separate duplicate-heading identities). Expectations were
written and checksummed **before v2 execution**, and were not changed to fit output.
All prior GOLD sets and REAL_CORPUS_V1_EVAL_V1 are unchanged.

Cases cover redundant/independent/orphan/duplicate/numeric/question/qualification
headings, lists, tables, FAQ, review, timeline, warnings, quantities, commercial
evidence, explicit/unknown-subject peers and equal text from different locations.
Supplemental tests cover typed edges/boundaries, ownership, quality, budgets,
tampering, local-only execution and exact prefix translation.

GOLD source-witness presence: **v1 24/24; v2 24/24**. The proxy requires phrase
presence and exact mapped source identity, not any matching text anywhere.
Saved-corpus removed-heading checks: **20/20 exact mapped heading/context witnesses**
remain lexically present in their retained descendants; every selected mapping is
byte-verified. No critical witness was lost by this offline proxy.

These are **offline discoverability proxies**, not retrieval recall. No embeddings,
semantic search, ranking, answer generation or chatbot benchmark was run.

## Saved 23-page result

The evaluator reconstructs v1 offline from the saved snapshot and checks every
document's graph/serialization hash against F's accepted replay, then runs v2.
Snapshot: `.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json`.
Output (ignored, not committed): `.codex_structural_4_1h/selection_final.json`.
It contains all 23 per-document metrics, candidates/translations, complete ledger
and tiny-unit axes. It does not create serving data.

| Measure | Legacy | Frozen v1 | G hypothetical | v2 measured |
|---|---:|---:|---:|---:|
| Chunks/specs/candidates | 1,092 | 3,242 | 2,636 | **3,232** |
| Stored/serialized tokens | 212,061 | 278,491 | 263,830 | **278,234** |
| Standalone headings | — | 754 | 148 | 744 |
| Tiny candidates (<50 tokens) | — | 1,452 | 880 | 1,442 |
| Prefix tokens | — | 78,928 | — | 78,691 |

Ledger: 3,149 embedded + 10 metadata-only + 83 unresolved + 0 packed = **3,242**.
Selected: 3,149 embedded + 83 unresolved = **3,232**.
Adjacent peer outcomes: 0 eligible; 46 unknown-identity pairs; 3,173 ineligible
(2,841 atomic-kind, 321 parent, 11 section). A spec can appear in two adjacent
pairs, hence 46 uncertain pairs touch 83 distinct unresolved specs.

Selected kinds: prose 1,525; heading 744; commercial 405; list 259; directions 105;
review 86; FAQ 78; timeline 30. All non-heading kind counts are unchanged.

Complete graph: **13,213 nodes / 6,700 edges**, unchanged; 2,209 graph-only nodes.
**18,137** original mapping occurrences reconcile as **18,117** selected
translations + **20** metadata-only witnesses. Exact interval coverage is equal.
**894,386 unique mapped bytes per source-node identity** remain covered; **0 lost**.
This is preservation relative to v1, not a claim that v1 embeds every raw source
byte (e.g. existing graph-only links/exclusions stay graph-only).

### Largest candidate counts

| Saved document ID | Legacy chunks | v1 specs | v2 candidates | v1 tokens | v2 tokens |
|---|---:|---:|---:|---:|---:|
| 12 | 103 | 360 | 360 | 22,063 | 22,063 |
| 28 | 65 | 221 | 220 | 19,719 | 19,700 |
| 27 | 61 | 209 | 208 | 21,793 | 21,768 |
| 11 | 61 | 208 | 207 | 22,343 | 22,311 |
| 29 | 57 | 199 | 198 | 16,927 | 16,903 |

Document 11 is the largest token case. Existing source-quality uncertainty remains
unmodified; this offline result is not permission to activate document 12 or any
other source.

## Cost decision

v2/legacy candidate ratio **2.95970695970696** (+195.970695970696%);
token ratio **1.3120470053428024** (+31.20470053428024%).
Compared with v1: **10 fewer candidates (0.30845157310301907%)** and
**257 fewer tokens (0.0922830540304731%)**.

Historical review targets are both **unmet**:

- Count: 3,232 vs 1,638; exact gap **1,594 candidates**.
- Tokens: 278,234 vs 275,679; exact gap **2,555 tokens**.

Float32 vector payload lower bound is `candidate_count × dimension × 4`, not a
database/storage forecast. At an explicitly hypothetical 768 dimensions:
legacy **3,354,624 bytes**; v1 **9,959,424**; v2 **9,928,704** (30,720 saved).
At another dimension multiply proportionally. No vectors were made and no profile
was changed. ANN, row, mapping, graph, JSON, WAL/replication and index overhead are
excluded. Complete v1 graph plus v2 ledger also require storage; selection is not
graph-storage compression.

**FURTHER PACKING STUDY REQUIRED**, not automatic failure for exceeding 1,638.
Fidelity/discoverability evidence is positive, but only 0.31% candidate savings,
nearly 3× legacy vector count, token target also unmet, and no proved corpus peer
packing do not justify cost acceptance now. Saving the other 596 G-simulated
headings needs stronger answerability evidence; peer savings need source-backed
subject identity, not looser UNKNOWN rules. No target was gamed.

## Validation and preservation

Final guarded runs completed successfully (no skipped H tests on this workspace).

- Focused H: **106/106 PASS**.
- Structural A–G plus H: **759/759 PASS**, 102.677 seconds.
- Complete canonical backend suite: **2,842/2,842 PASS**, 351.736 seconds
  (all existing 2,700 + 36 newly registered G + 106 H).
- AST checks on all five changed/new Python files and imports of all three new
  helper/policy modules: **PASS**.
- `git diff --check`, untracked-file whitespace checks, secret-pattern scan and
  exact nine-file H scope review: **PASS**. Secret scanning is not a mathematical
  guarantee against every possible secret; the changes were also inspected.
- Frozen hashes below and all 23 saved v1 graph/batch replay hashes: **PASS**.
- GOLD: **18/18 decision cases and 24/24 source-witness proxies PASS**.
- Final branch: `main`; HEAD remains `6f797efe34bf91391906fd9a44137ca5ee999b5f`.
  Nothing staged, H uncommitted; no push or deployment.

Commands (from `backend`, existing local venv):

```text
.venv\Scripts\python.exe -B -m unittest test_structural_selection_v2
.venv\Scripts\python.exe -B -m unittest test_structural_selection_v2 test_structural_packing_analysis test_structural_shadow test_structural_chunk_serializer test_structural_docling_adapter test_structural_text_adapter test_structural_repository test_structural_contracts
.venv\Scripts\python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
```

Saved evaluation and suite runs used additional in-process socket/DNS denials;
only Windows asyncio's owned loopback socketpair handshake was allowed in suites.
Canonical tests also deny configured-database connections and HTTP/provider calls.
Existing isolated SQLite/test-double tests are not persistent application DB access.
No disposable PostgreSQL or application database connection was made.

Frozen checks (SHA-256; source hashes normalize CRLF to LF):

| Artifact | Hash |
|---|---|
| v1 serializer | `faaa9088ba523cbdc51f35fee79698ed71f407bba7ee343fb00e1ab2d18cddd4` |
| G analysis helper | `5feb0dd876af4258c02fcb65353a089794418d59fbdf2e7c048e7c3bdae1ce1b` |
| G tests | `71c886ab6ffd71398444b6c31283ba775a48cd2ed3efebb48a2b7fe7e3b28321` |
| G design | `c36552f854f20fbefdc6d3ceebfc6a755337df67bcaf86111c03ccfeadac4865` |
| G frozen analysis JSON | `4529c23621da2dc782d7833bb41da5cf28b5f4eee172ff8de38b2bdcac67fd5a` |
| Saved source snapshot (raw bytes) | `4dc2bd9835b4e4e9a799a679dd08f9a36fc38cd419cab37be36d1abc71fcc662` |
| V2 GOLD cases (raw bytes) | `9ab18fdd962ba225716a6566d63aeb2f0c134100927c3b279b8aa1669367dcea` |
| Final v2 evaluation JSON (raw bytes) | `83d8c98dd7de9c82a6c65c309d4ed2367016612990ab6ee43aa3789e0e47fcd8` |

## Limitations and exact next prerequisite

Lexical/source-byte witnesses cannot establish semantic embedding recall or answer
quality. No real-corpus peers have proven identity, so peer/prefix-saving evidence
is synthetic only. Generic-label classification intentionally misses some safe
optimizations. Original v1 extraction/UNKNOWN-role/source-quality limitations are
preserved, not repaired. The selector is bounded offline processing, not a request
path: source-map indexing avoids global text scans; peer checks may inspect graph
edges per spec (worst-case O(specs × edges) within frozen graph/spec caps).

Before embedding-staging design: perform a separate, authorized offline
heading-answerability and explicit resource-identity/packing study with new frozen
witnesses, or explicitly accept the measured remaining cost. Subject uncertainty
belongs to future identity work, not title guesses in chunking. Do not proceed to
activation or embeddings on this report.

## Final decision

PHASE 4.1H — COMPLETE

structure-chunk-v2 VERIFIED OFFLINE

FURTHER PACKING / IDENTITY WORK REQUIRED BEFORE EMBEDDING-STAGING DESIGN

Exact reason: lossless conservative selection leaves 3,232 candidates / 278,234
tokens, 1,594 candidates and 2,555 tokens above the review targets; no saved-corpus
peer identity is proved, and removing further independently answerable/uncertain
headings is not justified by the current witnesses. H is left uncommitted for review.
