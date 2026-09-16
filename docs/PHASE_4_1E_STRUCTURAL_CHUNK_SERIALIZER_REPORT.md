# Phase 4.1E — offline structural chunk serializer

Date: 2026-09-16. Phase 4.1E remains **uncommitted**. No push or deployment.

Final validation: **PASS — Phase 4.1E complete, offline serializer verified.**
STRUCTURAL_CHUNK_GOLD_V1 frozen; saved-corpus shadow complete. Ready for the
separately authorized Phase 4.1F shadow integration, with the cost/scale review
flags in sections 27–28 explicitly outstanding. Not live rollout approval.

## 1. Phase 4.1D checkpoint

Starting Phase 4.1C HEAD: `6017dcdc1b87c0023c240c7f253f0a4e69a6e2a3`.
Phase 4.1D audited and committed locally:
`12d38f0196b29704c3f7b85aaed46a8cccf2ca78` —
`Phase 4.1D: add isolated Docling PDF and DOCX structural adapter`.

Fresh checkpoint structural tests: **388/388 PASS, 46.018s**. Optional Docling
requirements stayed separate; no model/customer/credential files were staged.
The staged check initially exposed PDF fixture bytes being interpreted as text:
Git reported PDF trailing spaces and warned about newline conversion. A scoped
fixture `.gitattributes` (`*.pdf binary`, `*.docx binary`) and the D report's
checkpoint note were added. No fixture bytes or expected hashes changed.
All seven staged fixture blob hashes matched the frozen manifest; staged
whitespace check passed. The checkpoint contains 19 intended D files. No push.

## 2–3. OSS study and provenance

The existing [OSS implementation ledger](PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md)
has a Phase 4.1E section with exact current commits, licenses, source files,
functions, adaptations and rejections for Docling Core, RAGFlow, LlamaIndex,
Haystack and Onyx. Actual upstream source was inspected before implementation.

Adapted concepts: source-item-first splitting; full-context token accounting;
compatible peer merges; explicit parent/source identities; metadata-aware
budgets; row/item boundaries; inherited headers; overlap with offsets; section
payloads separate from indexing models. Rejected: soft overflow, percentage
overlap, guessed headers/offsets, framework UUIDs/datastores, generated summaries,
retrieval windows and embedding/orchestration integration. **No literal upstream
chunker code copied; no new framework installed.** Existing MIT tiktoken is used
directly with a local-only loader; its installed encoding recipe is not copied.

## 4. Phase 4.1E files

- `.gitattributes` — LF policy for only the new frozen JSON inputs/generator.
- `backend/services/structural_chunking.py` — pure serializer/specs/validation.
- `backend/scripts/structural_chunk_gold_v1.py` — deterministic frozen input recipes.
- `backend/fixtures/structural_chunk_gold_v1/cases.json` — hand-specified expectations.
- `backend/fixtures/structural_chunk_gold_v1/manifest.json` — frozen input hashes.
- `backend/scripts/evaluate_structural_chunk_serializer.py` — offline metrics only.
- `backend/test_structural_chunk_serializer.py` — focused tests.
- `backend/scripts/test_scoped_rag_regressions.py` — register the new suite only.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — chunking study addendum.
- `docs/PHASE_4_1E_STRUCTURAL_CHUNK_SERIALIZER_REPORT.md` — this report.

Ignored research downloads, test logs and metric JSONs are under
`.codex_structural_4_1e/`; no source corpus, model or generated chunk payload is
added to Git. Prior DTOs, parsers, GOLD sets, application requirements, legacy
chunker, ingestion and retrieval files are unchanged from the D checkpoint.

## 5–6. Architecture and chunk-spec contract

`serialize_structural_document(StructuralDocument, ChunkPolicy)` returns a
validated `SerializationBatch`, never a database `Chunk`. It revalidates frozen
DTO input, groups structural units, selects exact source slices, partitions under
the full-text token budget, creates prospective mappings, and verifies output.

The batch retains the immutable **source graph once**: all attributes, original
links, provenance, quality, tree parents and version-pinned semantic edges.
Chunk specs refer into that graph; they must not be detached from it when using
their metadata. Empty structural items that cannot produce evidence text have
explicit `metadata_only_nodes`, not fabricated empty embeddings.

Each spec carries revision identity, deterministic SHA-256 chunk key, ordinal,
text, source-node identities, full heading-path identities, bundle members,
kind, bundle key, zero-based part index/count, whole-unit flag, independent
source-block completeness, original list/item indices, table-cell identities,
exact mappings, token/byte/prefix counts, policy, input hash and recipe hash.
No database primary key is required; mapping `chunk_id` is the prospective key.

## 7. Policy and deterministic recipe

Policy: **`structure-chunk-v1`**. Target 450, ordinary merge range 250–650,
hard maximum 800 including context, prefix maximum 80 including its separator,
optional prose overlap at most one complete sentence and 60 tokens.
These numerical defaults were not tuned to customer questions or cost gates.

The recipe fingerprints every policy parameter, installed tokenizer version and
factory/rank fingerprints, plus the normalized serializer source SHA. A later
implementation change cannot silently reproduce the same recipe identifier.
The input hash covers the complete canonical graph. Keys also bind revision,
bundle, ordered source slices and part index. No random IDs, clock or DB order.

## 8. Tokenizer

Installed **tiktoken 0.14.0 / cl100k_base**, matching the repository's local
encoding choice. Unlike the legacy helper, there is no word-count fallback.
The installed encoding factory executes with an isolated globals dictionary
whose BPE loader reads only the existing local cache and checks the upstream
SHA-256. No shared module mutation, asset download or provider request.
Missing/corrupt assets raise `SerializationError`. `encode_ordinary` treats
special-token-looking customer strings as ordinary data.

Actual complete serialized text is counted after prefixes, headers, qualifiers,
body, separators and overlap are assembled. These counts are **not provider
billing estimates**.

## 9–10. Prose and heading rules

Only adjacent sibling prose with identical parent/section, heading path,
explicit subject edges, semantic role and effective source quality may merge.
The accumulator stops around the target and below the conservative merge budget.
Excluded or intervening structural units are barriers. Atomic groups never merge
merely to fill the target. Unknown semantics stay unknown.

Heading identities retain the full source-established ancestry. The literal
prefix selects complete headings nearest-first, in ancestor order, within 80
tokens; it never invents a shortened summary. Large heading text is preserved
as its own evidence/multipart unit even when only its identity fits other parts.
Excluded/unsafe-link headings cannot reappear as inherited text. Only hierarchy
actually supplied by the parser is inherited; no PDF sibling-section inference.

## 11. Lists

Small complete lists remain one atomic unit. Larger lists partition at original
item boundaries. Oversized single items use exact continuation spans; list key,
source completeness and original indices remain with every part. Nested lists
retain distinct parent-list identities. Closed inline enumerations retain their
containing label, punctuation, item mappings and empty list-container metadata.
Source-block completeness never means global real-world exhaustiveness.

## 12. Tables

Specs remain typed table bundles, with cell identities pointing to immutable
row/column coordinates, spans, units, source headers and provenance. Text is
newline-delimited exact cell text, **not an inferred prose summary or guessed
header schema**. Bounded rows remain together; wide/oversized rows may continue
with explicit original cell identities. Actual required headers repeat as
`header`/`inherited` mappings, not new source occurrences.

If required repeated headers cannot fit the 80-token context budget, serialization
fails explicitly. It does not drop headers or claim a complete table. No numerical
policy relaxation was made for this adversarial case. The Docling merged-header
miss remains visible and is not guessed from row position.

## 13–15. FAQ, reviews and timelines

- Source-declared QA pairs share a bundle. Bounded question/answer text stays
  together; long answers split with question identity and part identity. A
  bounded question repeats literally; an overlarge question retains its full
  primary text and metadata identity rather than an invented summary.
- Reviews remain separate attributed evidence. The graph retains explicit
  `REFERS_TO` edges and pinned targets, including the earlier review-to-product
  witnesses. No testimonial is promoted to a product fact. Long reviews remain
  one multipart review bundle without prose overlap.
- Timeline stages have separate bundles and retain stage ID/order/label,
  source body and qualifications. Exact source-backed qualifiers repeat on
  continuation parts. Adjacent stages never merge into a context-free unit.

## 16–18. Commercial roles, quantities and qualifications

Commercial blocks preserve their original labels, amounts and existing typed
role/currency/condition metadata. Inline amount annotations map onto their
containing paragraph's exact bytes, not another numeric source occurrence.
Unknown roles remain unknown; no savings, discount, daily-cost or duration math.

Quantity/unit/frequency/range/qualifier attributes remain unchanged and their
containing instruction stays atomic when bounded. Exact source-backed condition
and qualifier strings may repeat as `qualifier`/`inherited` spans. Required
qualifiers too large for the context budget cause a typed refusal. Missing
structural association is not repaired by guessing. Warnings do not merge into
unrelated positive prose.

## 19–20. Links and overlap

Explicit validated source links are indivisible. A safe complete link that fits
is serialized whole. Unsafe/unchecked or oversized links remain in source-graph
metadata only, with an explicit excluded text range; no URL fetching or truncation
inside a Markdown link. Safe-link handling applies to inherited context too.

Only split prose may overlap: at most one complete previous sentence, at most 60
tokens, same unit/boundary, and only if the full next chunk still fits. A fragment
of a long sentence is not considered a complete sentence. Lists, tables, FAQ,
reviews, timeline stages, prices, directions and warnings have no prose overlap.

## 21. Provenance, isolation and coverage

Frozen `ChunkStructuralMapping` roles stay **body / heading / header / qualifier**.
The companion `MappedSpan.usage` distinguishes primary/inherited/overlap without
changing the approved DTO. Exact half-open UTF-8 node/output slices are checked
byte-for-byte, on codepoint boundaries; synthetic newline separators claim no
source bytes. Duplicate equal strings keep separate node occurrence identities.
Inline child annotations overlay exact source bytes only when provenance proves
containment; there is no substring-based source-location guess.

All node/mapping references bind the exact source and structural revision. This
pure serializer is not an authorization grant and accesses no datastore. Existing
same-org/bot and version-pinned edge validation remains authoritative. Customer
text is data, never executed or used to configure providers/routing/instructions.

Navigation/furniture and explicitly quarantined text are excluded with reasons.
Unknown/manual-review content remains in the offline output, **not activated**.
An excluded inline annotation inside a retained text node raises a typed error
instead of returning that excluded text through its parent. Excluded headings
cannot return through context. Coverage counts source-node spans separately
from unique raw source bytes, inherited repeats and raw Markdown syntax.

## 22. Bounds

| Bound | Default maximum |
|---|---:|
| Full chunk tokens / context tokens | 800 / 80 |
| Prose overlap | 1 complete sentence / 60 tokens |
| Input nodes / tree depth (unchanged DTO) | 10,000 / 32 |
| Mappings per chunk | 256 |
| Parts per atomic bundle | 256 |
| Chunks per document | 10,000 |
| Chunks per input node | 256 |
| Total bundle member references | 100,000 |
| Structural node-text bytes | 16 MiB |
| Serialized evidence bytes | 32 MiB and at most 8× source-node text bytes |
| Canonical source graph / full batch | 64 MiB |

If these bounds cannot preserve a unit, the API raises `SerializationError`; no
partial-success batch or silent truncation. The explicit count and byte expansion
bounds complement the token cap; provenance metadata is also bounded.

## 23. STRUCTURAL_CHUNK_GOLD_V1

Frozen new set: 27 deterministic domain-independent/adversarial recipes with
hand-written expectations, plus unchanged evaluation of all 30 original annotated
witnesses and three real synthetic PDF/DOCX artifacts. A raw-file SHA manifest
pins the JSON and recipe generator; scoped LF attributes protect those hashes
on Windows. GOLD is not regenerated from serializer output.

Cases include very long paragraphs/sentences, huge/nested lists and oversized
items, large/wide tables, long FAQ/review/stage, duplicate headings/paragraphs,
Unicode, long/unsafe links, warning barriers, mixed roles and nested sections.
Parser-derived fixtures and manually annotated roles are explicitly distinguished.
Neither old GOLD set nor REAL_CORPUS_V1_EVAL_V1 was changed.

## 24. Focused GOLD measurements

57 text/annotated cases; **314 specs / 94,521 tokens**. Min/p50/p95/max chunk tokens:
**1 / 442 / 455 / 797**. Structural input tokens: 96,802; ratio **0.9764364373**
(includes deliberate metadata-only links and explicit exclusions, not billing).

449,174 node-text bytes: 429,616 represented; 19,558 explicitly excluded;
**0 unaccounted**. Exact mappings, hard cap, stage separation and repeat hash
equality all passed. Max prefix 30 tokens, mappings 229, parts 41,
byte expansion 4.738738739×, chunks/input-node 9.25×.

| Structural property | Expected / retained |
|---|---:|
| Headings | 53 / 53 |
| Lists / items | 13 / 13; 295 / 295 |
| Cells / source headers | 508 / 508; 42 / 42 |
| Reviews / explicit review-reference edges | 8 / 8; 4 / 4 |
| FAQ questions | 4 / 4 |
| Timeline stages | 9 / 9 |
| Commercial / quantity nodes | 9 / 9; 5 / 5 |
| Warning nodes | 2 / 2 |
| Links | 14 / 14 metadata; 9 textual, 5 metadata-only |

## 25. PDF/DOCX results

Existing frozen artifacts were re-extracted only to obtain their verified DTOs
in memory; neither artifact nor expected GOLD changed. No OCR/network/LLM.

| Fixture | Nodes | Specs | Tokens | Token min/p50/p95/max | Cells retained | Headers retained | Unaccounted bytes |
|---|---:|---:|---:|---|---|---|---:|
| workshop.pdf | 33 | 11 | 88 | 1/8/14/14 | 6/6 | 2/2 | 0 |
| merged.pdf | 14 | 2 | 12 | 2/2/10/10 | 5/5 | 0/0 | 0 |
| workshop.docx | 42 | 12 | 186 | 4/13/33/33 | 9/9 | 2/2 | 0 |

Repeat serialization hashes match. Merged-cell spans remain intact; `Access`
still is **not** asserted to be a header. PDF text grouping stays exactly as
extracted. Workshop PDF has no inherited prefix where upstream supplied no
ancestor heading relation; DOCX max prefix is 10 tokens. Serializer does not
recover extraction/hierarchy losses. DOCX link identity retained 1/1.

## 26. Saved 23-page shadow

Read only the pre-existing local source snapshot; reused Phase 4.1C Markdown
parsing and serialized in memory. No DB connection/write, crawl, embedding or
chatbot. Network socket/DNS access was blocked for this measurement.

- 23/23 documents; **13,213 nodes → 3,242 specs**; **278,491 serialized tokens**.
- Chunks/document min/p50/p95/max: **59 / 171 / 221 / 360**.
- Chunk tokens min/p50/p95/max: **3 / 55 / 264 / 656**.
- Structural input tokens: **241,976**; serialized/input ratio **1.1509033954**.
- Node-text bytes **894,386/894,386 represented**, excluded 0, unaccounted 0.
- Unique raw-source evidence bytes **745,250** of **763,997** source bytes;
  18,747 remaining bytes are parser/source syntax/spacing, not missing DTO text.
- Headings **948/948**; lists **282/282**; item identities **749/749**.
  Eleven lists with 22 empty item nodes remain explicit metadata-only structures.
- Timeline stages **30/30**, separated; links **1,469/1,469** text and metadata.
- Reviews **86/86**; FAQ questions **78/78**; commercial nodes **536/536**;
  quantity nodes **139/139**. This saved Markdown parse supplies no table cells
  or explicit warning-role nodes; those are tested separately, not fabricated.
- Exact mapping and repeat hashes **23/23 PASS**; errors 0; max parts 1;
  max mappings 38; max prefix 77 tokens; max per-document byte expansion
  **1.584406845×**, chunks/input-node **0.335820896×**.

Structural input-token/node-byte totals can exceed unique raw-source totals
because inline annotations have their own node text; coverage unions do not
mistake their overlaid mappings for additional raw-source occurrences.

## 27–28. Inflation and review gates

Historical references only: 1,092 stored legacy chunks, 212,061 chunk-string
tokens, approximately 201,377 original source tokens. No live database remeasure.

- Chunk ratio: **2.9688644689×**; **3,242 > 1,638** review threshold.
- Token ratio: **1.3132589208×**; **278,491 > 275,679** review threshold by 2,812.
- Both gates require explicit cost/scale review; this is **not live rollout approval**.

Measured chunk kinds explain the increase: 1,525 prose, 754 heading, 405 commercial,
259 list, 105 directions, 86 review, 78 FAQ and 30 timeline specs. Complete small
structural units stay separate; literal heading inheritance also adds tokens.
All 10,225 unknown text nodes are retained, including source furniture not
positively labelled as such by the adapter. Dropping them or merging unrelated
units to pass a numeric gate would conceal evidence loss. No such tuning occurred.
Heading-only specs and unknown/furniture quality handling merit review in the
later integration slice, without changing the frozen v1 semantics silently.

## 29–30. Tests and validation

- Checkpoint A/B/C/D: **388/388 PASS**.
- Development combined structural run: **503/503 PASS, 82.463s**.
- Final non-Docling focused tests: **117/117 PASS, 9.255s**.
- Final A/B/C/D/E focused run: **510/510 PASS, 87.516s**
  (388 existing structural + 122 new serializer tests, including five Docling checks).
- Final complete canonical result: **2,593/2,593 PASS, 343.314s, exit 0**
  (all 2,471 accepted baseline tests + all 122 new tests; no skips/failures).
- Relevant existing legacy chunker: `test_rag_pipeline.test_3_structure_aware_chunking`
  executed as the existing AST-selected function only: **9/9 assertions PASS**.
  No DB/provider-bearing setup or other live functions were invoked.
- AST and imports: **5 files PASS**; original GOLD canonical hashes **30/30 PASS**;
  Docling artifact hashes **7/7 PASS**; new GOLD file hashes **2/2 PASS**.
- Secret-pattern scan: **0 matches** in task files; whitespace check PASS.
- Ledger/license review complete; optional/application dependencies unchanged.
- Final metric pass: **83/83 cases** (57 GOLD/witness + 3 Docling + 23 saved pages)
  have exact mappings, zero unaccounted node-text bytes, hard-cap compliance and
  identical repeat hashes. The saved-page parse plus two serializations per page
  took **24.583856600s** in this local measurement, not production latency.

Canonical command: backend `.venv/Scripts/python.exe -B -W ignore::DeprecationWarning
scripts/test_scoped_rag_regressions.py`, executed through the established in-memory
external socket/DNS deny wrapper. The wrapper allows only stdlib Windows
`socketpair`'s thread-local loopback handshake so asyncio can initialize; it
does not allow service connections. Existing configured-DB and HTTP/provider
guards remain intact. Docling workers have their own offline guards.
In-memory SQLite/synthetic unit-test fixtures are not application DB writes.

## 31. Known limitations and honesty boundaries

1. Cost/scale review thresholds exceeded as quantified above. No cost approval or
   production latency/answer-quality claim is made.
2. Only source-established semantics/heading relationships are preserved. Unknown
   content, PDF grouping and missing headers are not semantically repaired.
3. Explicit long qualifiers or required table-header context may refuse a unit
   under the 80-token prefix budget; typed errors are preferable to false completeness.
4. Unsafe/oversized links and empty structures may be metadata-only. Consumers
   must retain the batch graph with its chunk specs; it is not optional metadata.
5. Sentence detection is deterministic punctuation-based, not linguistic modelling.
   Unicode slices preserve codepoints/bytes, not a promised visual grapheme layout.
6. cl100k_base is a pinned local accounting strategy, not another provider's exact
   tokenizer or billing. Missing local assets block serialization.
7. Pure offline quality flags do not authorize tenant access or activate knowledge.
   Authorization, revision staging and persistence remain later integration work.

## 32. Next slice and scope confirmation

Next permitted work, only after review/authorization: Phase 4.1F shadow ingestion
integration. It was **not started**. Both cost-review flags must remain visible.

The serializer/evaluator calls no StructuralRepository or lifecycle API. Required
existing repository tests use their isolated synthetic/in-memory fixtures only.
No persistent customer/application DB, credentials, external provider/LLM/embedding
call, corpus change, new crawl, live
ingestion, resource activation, retrieval/context/generation/source-UI change,
Phase 3.7 chatbot benchmark, Railway action, push or deployment. Phase 4.1D alone
was committed as requested; Phase 4.1E remains uncommitted for review.
