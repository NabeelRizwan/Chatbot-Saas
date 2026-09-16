# Phase 4.1C — deterministic Markdown/text structural adapter

Date: 2026-09-16. Branch: `main`. Implementation is offline-only and uncommitted.
**PHASE 4.1C — COMPLETE**, with the extraction limits below explicitly retained.

## 1. Phase 4.1B checkpoint

Starting HEAD: `f83745bbe0c03eec20b9415153cf8ede9c6df1e1`.

**Phase 4.1B checkpoint: `f0835c16f0b38ea2230e2470f4667b41256914c6`.**

Message: `Phase 4.1B: add structural PostgreSQL sidecar and scoped repository`.
Exactly the nine files listed in the Phase 4.1B report were committed. Audit:
182/182 focused tests passed in 0.394 s, secret-pattern scan and staged whitespace
check passed, one migration head `20260916_01`, no unexpected files. A graph
inspection initially used the wrong import working directory; rerunning from
backend with isolated imports passed without source changes. No database was
reconnected. Tree clean immediately after checkpoint. No push.

## 2. OSS implementation study

The Phase 4.1C addendum extends `PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` with
current official implementation files/functions, pinned commits, licenses,
adaptations and rejected assumptions for Docling/Core, RAGFlow/DeepDoc,
LlamaIndex, Haystack, Onyx and markdown-it-py.

No literal upstream modules were copied. The existing installed MIT
`markdown-it-py==4.2.0` is reused and explicitly pinned, not installed/upgraded.
Framework-specific metadata, datastore, ACL, chunking and renderer assumptions
are not adopted. No Docling integration/import/install. Source-level behavioral
comparison is documented; no whole-framework execution benchmark is claimed.

## 3. Files changed after the checkpoint

- `backend/services/structural_text_adapter.py` — pure source-to-DTO adapter.
- `backend/services/structural_text_rules.py` — conservative explicit source rules.
- `backend/test_structural_text_adapter.py` — focused real parser/negative tests.
- `backend/scripts/evaluate_structural_text_adapter.py` — offline GOLD alignment and saved-source observations.
- `backend/scripts/test_scoped_rag_regressions.py` — one test-module registration.
- `backend/requirements.txt` — declare already-installed Markdown parser version.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — 4.1C research addendum.
- `docs/PHASE_4_1C_MARKDOWN_TEXT_ADAPTER_REPORT.md` — this report.

Ignored local output: `.codex_structural_4_1c/evaluation.json`; aggregate metrics,
counts and hashes only. No parsed structures or customer metadata persisted.

## 4. Adapter architecture / isolation

Required inputs: immutable UTF-8 bytes/text; trusted `RevisionIdentity` including
organization, bot, document, source version and source hash; explicit format and
fidelity. Full SHA-256 is checked before parsing. Ownership never comes from
frontmatter, comments, links or instructions in source.

Pipeline: bounded syntax tokens → source-positioned local tree → conservative
explicit attributes/relationships → canonical frozen `StructuralDocument`.
No `StructuralRepository`, ORM, application configuration, DB or provider import.
Output has no mappings/chunks and is **staging**, not active/servable. Source
quality remains UNKNOWN/manual_review, not a fabricated usability decision.

## 5. Markdown grammar

CommonMark ATX/setext headings, paragraphs/line groups, ordered/unordered/nested
lists, blockquotes, fenced/indented code, thematic breaks and GFM delimiter tables.
Raw HTML/comments/code/frontmatter remain inert source; nothing is rendered or
executed. Emphasis and escapes remain in original source text. Explicit inline
links support escaped labels, balanced destination parentheses, optional titles,
fragments and unsafe schemes as retained data. Images/reference-style links stay
in raw text; they are not fetched or assigned fabricated link targets.

## 6. Plain text

Preserves ordered lines/paragraphs and explicit numeric, bullet or alphabetic
list markers, including nesting. Does not infer headings, tables, FAQ, timeline,
commercial semantics or review subjects from prose. Caller explicitly chooses
Markdown versus text; file contents cannot select a more permissive parser.

## 7. Deterministic identity and recipe

Policies: `markdown-structure-v1`, `text-structure-v1`; normalization policy
`source-utf8-v1`. The recipe includes policy, pinned grammar version, admission
bounds and the explicit target-registry identities. Node keys use the frozen
source/path/order/content-hash scheme. Repeated text/headings/items have distinct
paths/positions. No UUID, clock, network result or hash-table iteration controls
canonical output. Same input/configuration yields identical bytes and hashes.

## 8. UTF-8 provenance

A compact character-to-UTF-8-byte prefix array and parser line maps reference
the original artifact. CRLF/lone CR can be normalized for syntax recognition
without changing original spans/text. Exact node text is copied from those
coordinates; repeated strings do not use global `find` alignment. Delimiter
search inside the current link/code interval is not source-identity matching.

Every emitted text node in GOLD has an exact byte-slice round-trip: **139/139**.
Containers reference their bounded source block without duplicating descendants.
The caller must retain the immutable source artifact; DTO leaf text is not a
byte-for-byte Markdown pretty-printer or whitespace reconstruction format.

## 9. Hierarchy

Heading levels, not stack size or heading text, determine parent sections.
Skipped levels remain representable; equal headings stay separate. A heading
inside a list/quote cannot replace the outer section scope. Heading/body edges
refer to direct source-contained blocks, not semantic similarity.

## 10. Lists

Preserves container, order flag, every item, nesting and item count. Complete
means that the **source list block** was fully captured, never that it is the
globally complete ingredient/resource truth. Highlight cards are not substituted
for full lists. The explicit comma-enumeration extension requires a listing verb,
at least three bounded entries and a final conjunction; ambiguous clauses abstain.
The seven/five/four-item saved witnesses are retained in original order.

## 11. Tables

Only deterministic Markdown delimiter tables become table/row/cell nodes.
Cells keep exact spans, coordinates and explicit header references; recognized
unit tokens in headers remain associated. Parenthetical prose such as “optional”
is not a unit. Escaped pipes are retained. Ragged/malformed rows remain complete
inert source rather than GFM-style extra-cell deletion or missing-cell padding.

## 12. FAQ

Explicit question heading plus same-section answer blocks emits QA_PAIR.
Arbitrary headings and ordinary question-mark prose do not. The frozen unmarked
alternating question/answer fixture is annotation-only: its text survives, but
its **two hand-assigned QA pairs are not automatically inferred**. Positive
Markdown-heading FAQ and negative ordinary-prose tests are separate.

## 13. Links and review relationships

No DNS, fetch, URL canonicalization or permission inference. HTTP(S) “safe” means
representation syntax only; unsafe/control/credential-bearing links remain inert
and unresolved. Relative links remain unchecked. Original href/anchor/fragment
are retained. The exact-href registry is caller-supplied, version-pinned and
same-org/bot; duplicate distinct targets remain ambiguous.

A labeled review line, or a bounded review section with an explicit reviewer
signature, must contain exactly one association link in that same labeled block.
Nearby navigation/recommendation links cannot steal the subject. No VARIANT_OF,
similarity, shared-path collection membership, or inferred product-benefit edge.

GOLD review precision/recall is **4/4**, including the two anti-aging witnesses,
**with explicitly supplied fixture target identities**. Without that registry the
links remain unresolved; this is not measured catalog resolution. Local synthetic
targets are aligned by exact source byte intervals, never keyword similarity.

## 14. Timeline policy

Repeated explicit time-label layouts become ordered stages. Each retains its
label, heading/body grouping and literal qualification sentences. Unrelated
heading boundaries terminate stages; standalone durations in unrelated sections
are not merged into a timeline. No expected outcome or guarantee is calculated.
All **5/5** annotated stages, including the three saved chocolate stages, match.

## 15. Commercial policy

Original amount strings and directly bound labels are retained. Flattened offer
amounts remain UNKNOWN; dollar symbols do not imply an ISO currency. Explicit
one-time/subscription/regular/offer/fee labels can assign roles; a unique labeled
recurring price retains its literal denominator/frequency conditions. No savings,
price/day, duration or discount arithmetic. Grouped decimal amounts are not
truncated; ambiguous decimal-locale strings stay raw. **7/7** annotated tuples
match; all six ambiguous saved Resveratrol amounts retain UNKNOWN roles.

Amount nodes remain children of the original source paragraph: labels and
conditions outside the numeric span are retained there. Future serialization
must retain that source association, not flatten the numeric child alone.

## 16. Quantity policy

Explicit number/range/unit text is associated only within its clause or an
immediately linked serving instruction. No frequency copied from an unrelated
product sentence; water volume is not dosing frequency. No unit conversion,
dosage equivalence, bottle duration or servings calculation. Unsupported numeric
formats remain raw instead of parsing a misleading numeric suffix. All **6/6**
annotated quantity/unit/frequency/qualifier tuples match.

## 17. Bounds and errors

Defaults: source ≤20 MiB (existing upload default; caller can lower), ≤10,000
nodes, depth ≤32, ≤20,000 edges, ≤100,000 lines, ≤64 inline links per text block,
≤256 explicit target entries. Intermediate block tokens are capped at six times
the node budget. Parser recursion is bounded before the library can silently
discard a deep tail; tree output also validates depth and DTO limits. Large
numeric strings remain raw rather than oversized numeric attributes.

Oversize/invalid UTF-8/hash/depth/node/edge/target errors fail explicitly; no
partial DTO is reported as complete. Traversal is bounded by source/nodes and
depth; sibling/canonical sorting adds O(N log N). Local section scans can revisit
nodes up to the fixed depth bound, not across a corpus. This is not a sandboxed
CPU/RSS enforcement claim at the maximum 20 MiB envelope.

## 18. STRUCTURAL_GOLD_V1 extractor measurements

Real adapter output, not GOLD self-round-trip, is compared by exact excerpt
UTF-8 positions. Containment aligns grouped bodies/items; parser paths are not
forced to equal hand-annotation paths. Mutation test proves deleting actual list
attributes reduces recall. No semantic alignment or regenerated GOLD hashes.

This extractor evaluation explicitly selects Markdown mode for the 30 bundled
source excerpts (including synthetic Markdown). GOLD's manual descriptor is not
used as parser configuration; plain-text conservatism has separate focused tests.

| Feature | Matched / annotated | Result |
| --- | ---: | --- |
| Heading/body association | 11/11 | 100% recall |
| Full list membership/order | 8/8 | 100% recall |
| Review→target | 4/4; 4 emitted | 100% precision and recall with explicit fixture target registry |
| Timeline label/order/body/qualifiers | 5/5 | 100% recall |
| Quantity/unit/frequency/qualifier | 6/6 | 100% recall |
| Commercial amount/currency/role/conditions | 7/7 | 100% recall; UNKNOWN roles retained |
| Canonical link href/anchor/fragment | 8/8 | 100% recall |
| Emitted text provenance | 139/139 | Exact original UTF-8 slices |
| Repeated parse canonical stability | 30/30 fixtures | Identical serialization |
| Entire annotated text intervals covered contiguously by text-bearing nodes | 90/99 | 90.9091%; see limitation below |

The 9 interval misses span multi-block groups, newlines/blank lines and stripped
list markers. Inspection found uncovered non-whitespace bytes only in explicit
list marker syntax; payload text is retained. These misses are **not relabeled
100% byte reconstruction**. Container/source spans preserve those locations;
actual source reconstruction belongs to the later serializer slice.

Additional unannotated structures are counted, not treated as labeled positives
or false positives. Broader edge/role precision is not measured by 30 fixtures.
Quality classification and collection-membership extraction are not accepted here.

## 19. Non-commerce fixtures

All 8 parse deterministically with exact source-backed text. Hotel, plan, course,
legal nesting, explicit reviews and timeline features pass applicable annotated
gates. The table fixture lacks a Markdown delimiter and the long-cell adversary
has no table syntax; neither is falsely converted into a table/header. Their
manual cell identities are **not extractor successes**. Explicit GFM table tests
separately prove row/cell/header/unit handling. The unmarked FAQ caveat is above.

## 20. Adversarial fixtures

All 11 parse with deterministic hashes and exact emitted-text spans. Duplicate
headings/text/items stay distinct; unsafe links stay unsafe; ambiguous targets do
not resolve; recommendations do not produce review edges; malformed syntax stays
text; long items/cells are not truncated; instructions/frontmatter cannot change
ownership or configuration. The unavailable-location annotation now has supplied
bytes, so the extractor can genuinely locate them rather than copying the label.

## 21. Saved 23-page shadow analysis

Read only the local immutable saved `SOURCE_PRODUCTION_SNAPSHOT.json`; no crawl,
DB connection, customer write, embeddings or chatbot call. Parsed one source at a
time with synthetic ownership; no target registry, so no resolved cross-document
review edges. Output stores summaries/hashes only in the ignored directory.

| Observation | Final value |
| --- | ---: |
| Pages / parser errors | 23/23 / 0 |
| Source bytes | 763,997 |
| Nodes | 13,213 total across pages |
| Sections / headings | 862 / 948 |
| Lists / list items | 282 / 749 |
| Tables | 0 recognized delimiter tables |
| Links | 1,469 |
| Explicit review groups / timeline stages | 86 / 30 |
| Local heading/QA edges | 6,700 |
| UNKNOWN semantic roles | 12,276 / 13,213 = 92.9085% |
| Union of text-bearing source spans | 745,250 / 763,997 bytes = 97.5462% |
| Maximum depth | 7 |
| Wall time with allocation tracing | 13.325002 s |
| Peak traced Python allocation, excluding snapshot load | 27,056,494 bytes (~25.80 MiB) |

These are local parser observations, not production latency, extraction precision
over the full corpus, RSS limits, generated chunk counts or answer-quality gains.
UNKNOWN is deliberate abstention; headings alone do not create business roles.

## 22. Document 12 witness

Saved title is `www.wowmd.com is blocked`; the saved blocked-tail marker remains.
The full mixed artifact yields 1,072 nodes: 98 sections, 98 headings, 201 links,
7 lists/13 items, 638 paragraphs, 16 groups and a document root; max depth 5.
49,323/50,585 bytes are covered by text-bearing spans. No timeline or review group.
Source quality stays UNKNOWN/manual_review. No document-ID runtime condition,
domain block rule, deletion or quarantine was introduced.

## 23. Focused and relevant tests

- Checkpoint: 182/182 PASS.
- Final adapter + frozen contracts + repository: **296/296 PASS**, 0.522 s
  (114 new adapter tests + existing 160 contract + 22 repository tests).
- Existing guarded ingestion/auth/scope checks: **65/65 PASS**, 5.851 s.
- Existing `test_rag_pipeline.test_3_structure_aware_chunking`: **9/9 assertions
  PASS**, synthetic legacy chunking only; no new structural chunk serializer.
- AST/import smoke: five Python files PASS; adapter/evaluator do not import DB,
  structural repository or Docling.
- Frozen fixture and saved-corpus preservation checks, secret and whitespace
  scans are recorded in the final repository gate below.

Legacy lifecycle scripts that call `init_db()` or write the configured customer
database were not run. The guarded existing tests and unchanged canonical runner
provide the relevant offline coverage without bypassing the no-DB rule.

## 24. Complete canonical suite

Final run: **2,379/2,379 PASS**, **252.837 s**: all existing 2,265 tests plus
114 new adapter tests. Earlier implementation run: 2,375/2,375 PASS, 245.120 s.
The final run includes the four numeric-boundary regressions and their repair.
Expected existing Redis-unavailable fallback messages did not fail any tests.
No runtime change followed the final run.

Commands from `backend`:

```text
.venv/Scripts/python.exe -B -W ignore::DeprecationWarning -m unittest test_structural_text_adapter test_structural_contracts test_structural_repository
.venv/Scripts/python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
.venv/Scripts/python.exe -B scripts/evaluate_structural_text_adapter.py --snapshot ../.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json --output ../.codex_structural_4_1c/evaluation.json
```

## 25. Known limitations

- Conservative, English-oriented explicit labels/units; not a semantic NLP parser.
  Unsupported/ambiguous formats stay raw and unknown rather than guessed.
- No original DOM/layout, hidden tables, CSS commercial styling or missing-content
  recovery from saved Markdown. No Docling/PDF/DOCX work.
- Reference-style links/images remain raw; inline links receive typed records.
- No automatic catalog/URL target discovery or permission checking beyond typed
  same-owner input validation; registry authority belongs to future ingestion.
- GOLD grouping alignment does not imply identical hand-annotated ASTs. Unmarked
  table/FAQ/quality semantics and byte-perfect Markdown reconstruction remain
  unproved, as disclosed above.
- Source-quality detector, very-large-document performance, held-out broad
  precision and process-level resource isolation are not accepted by these tests.
- Phase 4.1B's previously documented historical bootstrap-chain risk is unchanged;
  this parser work does not validate or change migrations.

## 26. Preservation and next slice

Preservation inventory: 628 pre-existing tracked/saved-corpus files; only the
intended existing requirements, runner and OSS ledger paths changed. Frozen
STRUCTURAL_GOLD_V1, REAL_CORPUS_V1 snapshot/evaluation/answers/grades and all earlier
implementation remain unchanged. No application DB was inspected or modified;
this is file-hash preservation, not a claim to have re-counted live DB rows.

No source/repository write, source activation, live ingestion hook, structural
chunk generation, embedding, retrieval/FTS/RRF/planner/reviewer/generation change,
provider call, production/Railway action, deployment or push. Only Phase 4.1B was
committed; Phase 4.1C remains uncommitted for review.

Next separately authorized work can consume the frozen adapter DTO for subsequent
Phase 4 extraction/serializer work. Do not enable live persistence or ingestion
without lifecycle, quality, byte-budget, retention and activation integration.

Final repository gate: tracked and new-file whitespace checks PASS; secret-pattern
scan PASS (zero hits); AST/import isolation PASS; frozen fixture and corpus hash
preservation PASS. The eight intended Phase 4.1C paths above are uncommitted,
the index is empty, and HEAD remains the Phase 4.1B checkpoint.

## Final verdict

PHASE 4.1B CHECKPOINT — COMMITTED

`f0835c16f0b38ea2230e2470f4667b41256914c6`

PHASE 4.1C — COMPLETE

DETERMINISTIC MARKDOWN/TEXT STRUCTURAL ADAPTER VERIFIED

STRUCTURAL_GOLD_V1 EXTRACTOR METRICS RECORDED

SAVED REAL-CORPUS SHADOW PARSE COMPLETE

READY FOR NEXT PHASE 4 SLICE
