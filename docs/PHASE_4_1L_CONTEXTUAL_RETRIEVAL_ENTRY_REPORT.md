# Phase 4.1L — contextual retrieval-entry representation

Date: 2026-09-17. Offline implementation and evaluation only.

**Measured decision: B — representation needs revision.** Exact coverage,
determinism and scope gates pass, but the heading usefulness policy unnecessarily
duplicates purely numbered section labels as dense candidates (section 29).
Final validation results are recorded below. L is uncommitted. No push or deployment.

## 1. Phase K checkpoint

Audited K's two design/ledger changes, checked 702/702 preservation hashes,
secret patterns and whitespace, and created local commit
`2944933116429e47ce81c08e22561613dd7fc783`:
`Phase 4.1K: design general source capture and retrieval representation`.
Parent J is `95cd002c77a0b50b4eac57500063a5034de2e8db`.
Ignored K research/calculations were not committed. No K runtime change.

## 2. OSS implementation study

The L addendum in `PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` records exact
functions, immutable source links, licenses, adaptations and rejected patterns.
Docling/Core, LlamaIndex, Haystack and RAGFlow remained at the freshly rechecked
K pins; Onyx advanced to `a997e9a1d8542e98ea58104b1a9e95a7663978d1`.
Actual source implementations were reread before testing. No literal source
was copied, no framework runtime or dependency was added.

Docling similarities: structure-first units, contextual headings, compatible
adjacent accumulation and whole-text token accounting. Intentional divergences:
full trusted scope, exact byte mappings, immutable typed evidence, no context
deletion on overflow, no merge based merely on matching heading text. This is
a source-level comparison, not an executed HybridChunker benchmark.

## 3. Files changed in L

- `backend/services/structural_retrieval_entries.py`
- `backend/scripts/structural_retrieval_entry_gold.py`
- `backend/scripts/evaluate_structural_retrieval_entries.py`
- `backend/test_structural_retrieval_entries.py`
- `backend/fixtures/structural_retrieval_entry_gold_v1/cases.json`
- `backend/fixtures/structural_retrieval_entry_gold_v1/manifest.json`
- `backend/fixtures/structural_lexical_witness_gold_v1/cases.json`
- `backend/fixtures/structural_lexical_witness_gold_v1/manifest.json`
- `backend/scripts/test_scoped_rag_regressions.py` — one test registration
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — L addendum only
- this report

Ignored measurements/research live under `.codex_structural_4_1l/`. No existing
application runtime, parser, v1/H serializer, retrieval or ingestion file changed.

## 4. Three-layer architecture

The original `StructuralDocument` is source truth. Existing immutable v1 bundles
and their exact continuations supply typed evidence atoms. New retrieval entries
are independently identified search containers pointing to those atoms. An atom
is a v1 logical bundle, not necessarily one graph node: ordinary prose can have
several paragraph nodes; a list/table/FAQ may have several typed children.

The public builder accepts a validated `SerializationBatch` containing both
graph and evidence, plus separately supplied trusted scope. It does not infer
ownership from content. This reuses, rather than rewrites, existing safe splitting
and mappings. Entry grouping is NOT H's semantic evidence merging.

## 5. Entry, membership and span contracts

Frozen, extra-field-forbidden DTOs: `RetrievalEntryPolicy`, `RetrievalEntryScope`,
`EvidenceAtom`, `StructuralRetrievalEntry`, `RetrievalEntryMembership`,
`RetrievalEntryMappedSpan`, `RetrievalEntryBatch`, coverage rows and ledger.
Entries contain full revision/source/crawl scope, deterministic key/ordinal,
kind, text, section, ordered atom IDs, context nodes, memberships, byte maps,
token/byte/fanout counts, quality/resource/boundary IDs, policy/input/recipe hashes
and explicit `exact_routing_not_final_evidence` state. Continuations retain their
source part, common bundle/atom and part index/count. No ORM or DB primary key.

## 6. Policy fingerprint

`structural-retrieval-entry-v1`: target 500; soft 250–700; hard 800; inherited
context 80; atom references 32; mapping rows 256; continuation parts 256;
entries/document 10,000; serialized search text 32 MiB; full DTO input/output
128 MiB. Existing v1's stricter input and graph limits remain in force.

Fingerprint includes all policy values/rules, local tokenizer fingerprint,
normalized L implementation source hash and v1 serializer recipe. Input hash
also covers the complete evidence batch. Any implementation/policy change changes
the recipe and entry IDs; existing outputs are never mutated.

Final implementation hash:
`0b32a7b29e930e72923ad43b7fbae167390a164d96e4b80a9f27fd1fe28aeaa8`.
Default L/v1 recipe:
`79f7502cca503c68db515b0a84f091840656cee6837ac92ec873d6fa431b7317`.

## 7. Tokenizer and accounting

Local `cl100k_base`, installed tiktoken 0.14.0; asset checksum required and
downloads forbidden. Tokenizer fingerprint:
`c2fffeddfb073c31d3a3f743e66085ff2edbf39f0c5204e8b01fb8fc347a713f`.
Counts cover complete text including headings, headers, qualifiers and newline
separators. Context counts cover the union of inherited output spans. These are
local representation counts, not Gemini billing or provider-input validation.

## 8. Grouping algorithm

Revalidate one source graph/evidence batch and caller scope. Index atoms, source
parts, heading owners and boundaries. Walk ordered evidence parts; append only
compatible adjacent parts. Deduplicate an identical leading heading context by
node/range identity and remap its references to the retained exact bytes. Close
at a boundary or budget; after target, permit genuinely short compatible tails
up to soft max. A single intact unit may use hard max. Oversized units use the
unchanged v1 safe continuations. No summary, rewriting, query or semantic model.

Work is document-local; no corpus-global pairing/clustering. Per-entry matching
is capped at 32 atom references/256 maps; node ownership checks use sets. Graph
maps are built once per document. Canonical hashing, validation and range unions
add serialization/sorting overhead; this is not a constant-memory parser.

## 9. Boundary rules

Separate trusted organization/bot/document/source/version/revision/crawl scope;
nearest structural section and exact heading path; source quality; proven
DESCRIBES resource; explicit unresolved ownership; navigation/quarantine barrier.
Different known resources cannot share; conflicting resource ownership within
an existing atom fails closed. Unvalidated/rejected DESCRIBES assertions are
uncertain boundaries, never positive ownership. Unowned reviews/cards remain
separate by bundle. Ordinary UNKNOWN prose is not rejected simply for lacking
resource identity. No source relationship authorizes access.

## 10. Headings

Graph nodes never disappear. Fully inherited headings normally have no separate
dense entry but remain exact context and independently addressable atoms.
Orphan/unrepresented headings remain standalone; numeric/question/exclamation or
warning/must/never/shall headings conservatively remain independently useful.
Typed FAQ questions remain part of their FAQ atom, not artificially unpaired.
Duplicate text at different locations is not deduplicated across identities.

## 11. Lists

Retain original list and ordered item identities, mappings and completeness.
Whole bounded lists can share an entry with other compatible typed children.
Oversized lists inherit existing item-first continuation splitting and common
bundle identity; no vector is automatically assigned to every list item.

## 12. Tables

Preserve original table/row/cell nodes, spans, headers, units and provenance.
Bounded row/cell continuations retain required repeated header mappings. No
table-to-prose conversion or invented header; budget failure is explicit.

## 13. Reviews

Review atoms/attribution/provenance remain independent. Unresolved reviews do not
share containers across review ownership boundaries. Proven safe ownership may
permit search-container sharing without treating two reviews as one claim.

## 14. FAQ

Original Q/A pairing and separate pair identity survive. Several compatible
pairs may share a bounded entry in one section, with independent byte maps.

## 15. Timelines

Stage identity/order/label/body/qualifications remain in original atoms/graph.
Compatible stages can share search text without flattening their claims. Tests
verify exact continuation qualification retention, including repeated companions.

## 16. Commercial evidence

Original blocks, amounts, unknown roles and conditions remain exact. Sharing a
container does not equate prices, infer sale/subscription/daily roles or compute
discounts. No monetary inference layer was added.

## 17. Directions and quantities

Keep source instructions, quantities and role relationships; a directions atom
can share with ordinary prose while retaining its own kind/ID/mappings. Search
grouping does not transfer a dosage or quantity to a neighboring atom.

## 18. Warnings and qualifications

Mandatory inherited companions stay mapped. Verification checks every original
part span by node/role, not just total entry bytes. Headers/qualifiers cannot be
dropped to fit budgets; overflow rejects the batch, never silently truncates.

## 19. UNKNOWN

Searchable unknown prose is retained. No customer, industry, product, document-ID,
query or current-corpus branch exists. Labels remain source-side structural data.

## 20. Navigation, furniture and quarantine

Honor existing parser/quality signals and v1 exclusions; excluded content remains
in the original graph and explicit ledger. Unsafe inline link exclusions follow
exact containing source spans/parent provenance, not text search. L introduces
no new navigation classifier and does not relabel ordinary prose as furniture.

## 21. Lexical disposition model

Every admitted atom is DENSE_AND_LEXICAL or LEXICAL_ONLY, with original exact
evidence retained independently of entry text. Every graph node additionally has
GRAPH_ONLY or EXCLUDED_WITH_REASON where appropriate. The verifier accounts for
all node-local evidence bytes using admitted spans plus explicit exclusions.
Lexical-only batches are contract-tested with exact atom recovery and no invented
dense membership. Default successful construction admits all searchable atoms;
the saved corpus has no lexical-only atoms. No PostgreSQL/FTS write occurs.

## 22. Entry ↔ atom mappings

Immutable indexed dictionaries support entry→ordered atoms and atom→entries
without per-child I/O. Lookup requires the exact trusted scope; unknown IDs,
foreign tenants/bots/versions/revisions/crawls fail. Lexical-only lookup returns
an empty entry tuple while retaining the atom and its original evidence parts.

## 23. Exact provenance

Every represented source byte maps to exact node-local and entry-local UTF-8
ranges, usage (body/heading/header/qualifier/context) and original usage. Only
synthetic newline separators may be unmapped. Mid-codepoint, foreign-node,
altered-text, lost-required-span and boundary mismatches fail validation. Graph
and evidence remain unchanged, including duplicate source occurrences and links.

## 24. STRUCTURAL_RETRIEVAL_ENTRY_GOLD_V1

40 frozen cases across the requested structural behaviors, seven generic domains,
Markdown/TXT and PDF/DOCX DTO shapes. Expectations were frozen before construction
evaluation; manifest hash:
`2acd5b341fa760ddf3029d50f72b9d7084ca20f42a137ecd584acdbce17037a0`.
Fixture-format newlines are normalized to LF for manifest verification, so a
Windows autocrlf checkout does not invalidate unchanged frozen JSON cases.
No fixture content or expected hash was changed. All cases verify complete mappings/bounds/reverse lookup; each also has a separate
deterministic repeat test. No prior GOLD file changed.

## 25. STRUCTURAL_LEXICAL_WITNESS_GOLD_V1

13/13 exact witnesses PASS: list ingredient, review, FAQ answer, price, dosage,
timeline, warning, ordinary prose, hotel cancellation, software storage, course
module, legal clause and technical error. Each checks primary evidence presence,
lexical disposition, exact mapped entry where applicable, reverse recovery and
foreign-scope refusal. Manifest hash:
`e88474501c311217a418773202edd378bd57620aac292c5fdba2b075934ff26d`.
This proves offline addressability, NOT semantic recall or actual FTS execution.

## 26. Saved 23-document result

Frozen source files only, with existing source/version/crawl pins; no recrawl or
database. Full per-document results/hashes: ignored `saved_1x_final.json`.

| Measure | Result |
| --- | ---: |
| Documents / source tokens | 23 / 201,377 |
| Graph nodes / edges | 13,213 / 6,700 |
| Searchable logical atoms, including headings | 3,242 |
| Contextual search entries / tokens | 1,120 / 220,749 |
| Entry tokens min / p50 / p95 / max | 5 / 124 / 634 / 699 |
| Atom references per entry min / p50 / p95 / max | 1 / 4 / 9 / 19 |
| Atom references per entry mean | 4.228571429 |
| Heading-only / small (<250) / continuation entries | 92 / 837 / 0 |
| Lexical-only / graph-only / excluded admitted atoms | 0 / 0 / 0 |
| Dense+lexical / graph-only / excluded graph nodes | 11,014 / 2,199 / 0 |
| Mapping rows / maximum per entry | 13,414 / 76 |
| Admitted / mapped node-local evidence bytes | 894,386 / 894,386 |
| Unaccounted bytes / errors | 0 / 0 |
| Deterministic full-batch repeat hashes | 23/23 identical |

Graph-only nodes have empty structural text (`empty_structure`), not missing
searchable evidence. Excluded/quarantined examples are exercised in GOLD, not
invented for this corpus. Node-local byte totals can exceed raw-source bytes
because graph annotations represent overlapping source locations. Coverage is
100% of admitted node-local evidence, not a claim that overlapping annotations
are distinct raw-source facts. Headings referenced by several entries explain
why mean references/entry differs from unique atoms divided by entry count.

Ordered final batch-hash digest:
`bfc73391f74b9f22eaa4f22aac2ed97d4e65cf2209bf9d48823659baa220bc65`.
The preliminary measurement preceded the explicit-unvalidated-ownership guard
and set-indexed membership verification; final counts/tokens remained identical.
No counts or thresholds were tuned to this corpus.

## 27. Normalized scale metrics

| Metric | 1× final |
| --- | ---: |
| Entries / 1,000 source tokens | 5.561707643 |
| Entry tokens / source tokens | 1.096197679 |
| Atom references / entry, mean | 4.228571429 |
| Heading-only entries | 8.214285714% |
| Small entries | 74.732142857% |
| Continuation entries | 0% |
| Mapping rows / 1,000 source tokens | 66.611380644 |
| Max atom / mapping fanout | 19 / 76 |
| Entry construction seconds / 1,000 source tokens | 0.103341411 |
| OS peak working set, complete process | 607.589844 MiB |

The large small-entry share is disclosed, not hidden: section/heading paths,
standalone evidence-bearing headings and ownership/quality barriers are not
crossed to achieve a numeric target. This remains a canary-design consideration,
not proof of good or bad embedding recall.

## 28. Actual 1× / 10× / 100× results

| Scale | Documents/scopes | Source tokens | Nodes | Edges | Entries | Entry tokens | Mapping rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1× | 23 | 201,377 | 13,213 | 6,700 | 1,120 | 220,749 | 13,414 |
| 10× | 230 | 2,013,770 | 132,130 | 67,000 | 11,200 | 2,207,490 | 134,140 |
| 100× | 2,300 | 20,137,700 | 1,321,300 | 670,000 | 112,000 | 22,074,900 | 1,341,400 |

| Scale | Existing preparation s | Namespace generation s | Entry construction s | Construction s/1k tokens | Complete process s | OS peak MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1× | 11.802353 | 0.000020 | 20.810583 | 0.103341411 | 57.281965 | 607.589844 |
| 10× | 14.252947 | 136.592445 | 194.317769 | 0.096494520 | 368.667325 | 606.828125 |
| 100× | 14.787649 | 1,273.113495 | 1,834.536523 | 0.091099605 | 3,343.209823 | 612.269531 |

Fresh independent processes, sequential scale runs, identical policy and text;
every document was actually constructed, not multiplied from 1×. Synthetic
namespacing changes trusted identity, never evidence bytes. Counts and complete
token/fanout histograms are exactly linear at both 10× and 100×. All 2,300 scopes
are distinct; 100× has zero unaccounted evidence bytes. Construction-time ratios
versus 1× are 9.337449372 and 88.154017028, respectively: approximately linear
observed work, not an algorithmic speedup or production capacity claim. The 1× complete time includes
an extra repeat construction/hash comparison for each document; 10×/100× do not.
Construction includes ingress revalidation and output verification. Namespace,
existing parser/serializer preparation, metrics/hashing and repeat overhead are
not hidden inside the construction figure. OS peak includes all of them.
These are local offline measurements, not serving latency or production capacity.

Full ordered 100× batch-hash digest:
`f2c0e3c759fe5bca7d2b348d241c55a59fdfc54c5e765d591a3fc14bddfe02df`.
The complete process took 55.720164 minutes, including fixture namespacing and
metrics serialization. The brief final fixture-portability unit run also occurred
during this local evaluation; these are observational workstation timings, not
isolated hardware benchmarks. Percentiles use nearest-rank order statistics.

## 29. Single-document scaling

Each section has an ordinary paragraph and two list items. The same policy is
used for every size; no source/section/entry count target was tuned.

| Sections | Source tokens | Nodes / edges | Atoms | Entries | Entry tokens | Maps | Entries/1k tokens | Maps/1k tokens | L construction s | Existing preparation s |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 192 | 83 / 20 | 31 | 20 | 260 | 70 | 104.166667 | 364.583333 | 0.039013 | 0.165070 |
| 100 | 1,902 | 803 / 200 | 301 | 200 | 2,600 | 700 | 105.152471 | 368.033649 | 0.456392 | 0.232314 |
| 500 | 9,502 | 4,003 / 1,000 | 1,501 | 1,000 | 13,000 | 3,500 | 105.241002 | 368.343507 | 2.993498 | 1.847462 |
| 1,000 | 19,002 | 8,003 / 2,000 | 3,001 | 2,000 | 26,000 | 7,000 | 105.252079 | 368.382276 | 6.562484 | 4.826698 |

All are within existing source bounds, all have zero unaccounted bytes, max
fanout 4 and max maps 5. Entry-token min/p50/p95/max is 7/7/19/19 at every size;
all entries are small. Counts grow exactly linearly with section count, not
quadratically with heading/list/item count. Construction seconds/1k tokens rise
from 0.203192 to 0.345358; do not describe single-document work as perfectly
linear. The 500→1,000-section step doubles counts and takes 2.192246× construction
time. Whole-process peak: 1,006.542969 MiB; total: 18.144173 seconds. These costs
include retaining/revalidating exact DTOs and require capacity review before
any serving integration.

**Measured representation problem:** the heading decision in
`build_retrieval_entries` treats any digit as evidence of independently useful
heading content. Thus `Section 0` through `Section 999` each receive a standalone
entry even though their exact text is also inherited in the corresponding body
entry. At the largest size, **1,000 of 2,000 entries are redundant heading-only
candidates**. The body entries still preserve the paragraph and list as separate
atoms. This is an over-conservative source-heading policy, not evidence loss,
tenant leakage, an absolute entry-count threshold or a reason to weaken section
boundaries. No classifier was tuned or GOLD expectation rewritten to manufacture
a pass after observing it. This concrete unnecessary duplication withholds
canary-design readiness until an offline general heading-policy revision.

## 30. Multi-tenant and version isolation

Identical text/title/URL across tenant A/bot A, tenant A/bot B and tenant B/bot A
has distinct batch/entry/node identities; cross-scope lookups fail. Separate tests
cover source document, version, structural revision and crawl changes, immutable
old outputs, changed policy identities, missing trusted scope and forged foreign
memberships. Source instructions assigning a different organization remain inert
text. Scope is supplied by a trusted caller, not granted by the DTO itself.

## 31. Domain generalization

Unchanged policy on commerce, hotel, software, course, legal, technical and
generic article fixtures. Domain texts influence exact content/token length,
not runtime branches or tuned targets. Protected section/typed boundaries, not
a desired number of entries, determine packing opportunities.

| Frozen domain/format case | Atoms | Entries | Entry tokens | Unaccounted bytes |
| --- | ---: | ---: | ---: | ---: |
| Commercial | 3 | 1 | 21 | 0 |
| Hotel | 2 | 1 | 18 | 0 |
| Software | 2 | 1 | 18 | 0 |
| Course | 2 | 1 | 15 | 0 |
| Legal | 2 | 1 | 14 | 0 |
| Technical | 2 | 1 | 14 | 0 |
| Article | 2 | 1 | 13 | 0 |
| TXT | 1 | 1 | 11 | 0 |
| PDF DTO | 1 | 1 | 13 | 0 |
| DOCX DTO | 1 | 1 | 13 | 0 |

These small fixtures demonstrate compatibility, not domain-scale benchmarks.

## 32. PDF / DOCX results

Both structural DTO fixtures PASS with the same policy and page-box provenance.
These are synthetic frozen input shapes derived from existing table GOLD, not
new binary extraction or live Docling conversion. Existing adapter regressions
remain required; arbitrary PDF/DOCX extraction quality is not newly certified.

## 33. v1 / H / K comparison

| Representation | Count | Local tokens | Meaning |
| --- | ---: | ---: | --- |
| Frozen v1 | 3,242 | 278,491 | Original mapped evidence specs |
| H | 3,232 | 278,234 | Earlier protected evidence packing |
| I/J | 3,230 | 278,177 | Earlier resource study result |
| K target-500 envelope | 974 | 268,283 | Optimistic arithmetic only; not serialization |
| L | 1,120 | 220,749 | Actual scoped entries; all 3,242 original atoms retained |

L reduces search-container count by 65.453423812% and serialized search tokens by
20.733883680% versus v1, primarily through heading-as-context and compatible
entry sharing. It does not reduce exact atomic evidence. K's 974 was not a target
and did not implement these boundaries/mappings. Historical legacy 1,092 chunks
and the 1,638 threshold were not used as acceptance criteria.

## 34. Vector-count arithmetic only

If a later approved canary creates one vector per L entry, this dataset would
require 1,120 vectors instead of 3,242 per-v1-spec vectors. Linear copies imply
11,200 at 10× and 112,000 at 100×; these are representation-count arithmetic,
not measured embedding cost, semantic recall or index capacity. No actual
embedding/vector index was created, and future atomic FTS coverage is retained.

## 35. Focused tests and safety gates

149/149 final L tests PASS (6.618 seconds), network denied. Includes 40 GOLD,
40 deterministic repeats, 13 lexical witnesses, contracts/bounds/ownership,
scope/version/policy changes, prompt-text inertness, full-context accounting,
1/10/100 independent fixture namespaces, preservation/OSS checks and Windows
fixture-manifest newline portability.

731/731 pre-L preservation hashes PASS at both intermediate and final checks.
Final AST: 5/5 Python files PASS. Secret-pattern scan: all 11 changed/new files
PASS. `git diff --check` and explicit tracked/untracked whitespace scan PASS.
Main remains at the K checkpoint; L consists only of the 11 listed files and is
unstaged/uncommitted. Import validation is recorded with the final suite below.
No existing implementation was restored, reset, stashed or overwritten.

Reproduction from `backend` (local venv, `-B`; tests wrapped in external-network
denial and evaluators deny sockets/DNS themselves):

```text
.venv\Scripts\python.exe -B -m unittest test_structural_retrieval_entries
.venv\Scripts\python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_entries.py --saved --scale 1 --output ../.codex_structural_4_1l/saved_1x_final.json
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_entries.py --saved --scale 10 --output ../.codex_structural_4_1l/saved_10x_final.json
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_entries.py --saved --scale 100 --output ../.codex_structural_4_1l/saved_100x_final.json
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_entries.py --document-scale --output ../.codex_structural_4_1l/document_scale_final.json
```

## 36. Canonical backend result

Validation history: 3,223/3,223 PASS (467.224 seconds; baseline 3,083 plus
then-current 140 L tests); 3,231/3,231 PASS (414.560 seconds; 148 L tests).
After the final fixture-portability regression, the complete canonical run is
**3,232/3,232 PASS**, 314.539 seconds, exit 0
(unchanged 3,083-test baseline + all 149 L tests). Offline imports: 4/4 PASS.
The existing 1,000 structural A–J tests are included in the canonical runner;
K is design-only. External connections/DNS/HTTP are denied; only asyncio's
internal loopback socketpair is allowed. The runner separately forbids the
configured application DB and provider transport. Existing isolated in-memory
test fixtures are not customer or persistent database access.

## 37. Limitations

- No embedding/hybrid recall, reranking, expansion, final-answer or production
  latency result is claimed. Lexical eligibility is a future FTS contract only.
- Existing v1 evidence preparation is required and measured separately. Its
  parser/serializer costs were not optimized or rewritten in L.
- DTO revalidation/canonical hashes cost CPU and temporary memory. Processing is
  bounded per source, not constant-memory within a source. Corpus evaluation
  retains the prepared 23-document fixture set; peak memory includes that cost.
- Heading usefulness is a conservative source-side lexical rule, not semantic
  understanding. No dense suppression removes its exact graph/lexical access.
- Resource knowledge is limited to explicit input structure. No missing source
  anchor, resource boundary or scope is invented.
- Small protected sections legitimately remain small. Future dense discoverability
  of an individual child inside a larger entry must be measured, not assumed.
- Purely numbered structural headings are currently over-promoted to standalone
  entries. The scale fixture demonstrates the redundant candidates directly;
  source-context/lexical retention already covers their exact labels.
- PDF/DOCX cases cover DTO compatibility, not a fresh binary parsing study.

## 38. Exact next phase and final decision

**B. PHASE 4.1L — COMPLETE**

**RETRIEVAL-ENTRY REPRESENTATION NEEDS REVISION**

The digit-only usefulness shortcut redundantly promotes ordinary numbered
section labels. The 1,000-section fixture contains 1,000 unnecessary standalone
heading entries alongside fully contextualized body entries. Counts/coverage/
scope/determinism pass, but this generic heading behavior should be revised
before recommending a development embedding canary.

Exact next recommendation: a separately reviewed, narrow OFFLINE L heading-policy
revision. Freeze contrasting structural-label and independently factual-heading
cases before changing the policy; preserve all graph/lexical access, orphan
headings and exact mappings; change the recipe; rerun offline gates. Do not use
an absolute target count or current-customer tuning. Only after that closure
should SMALL DEVELOPMENT EMBEDDING + HYBRID RETRIEVAL CANARY DESIGN proceed.
No canary or later phase is implemented here.

No source capture, live retrieval, FTS/RRF change, structural expansion runtime,
DB mutation, provider/model call, crawl, production access, push or deployment
was performed. L remains uncommitted for review.
