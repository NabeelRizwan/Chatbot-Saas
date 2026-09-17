# Phase 4.1M — general heading-policy closure

Date: 2026-09-17. Offline representation only.
**Decision A — heading policy closed; ready for small development canary DESIGN.**

## 1. Phase L checkpoint SHA

`693c5148717561fabe4ecf9322b8f99ddc4393de` —
`Phase 4.1L: add contextual retrieval-entry representation`.
Parent K: `2944933116429e47ce81c08e22561613dd7fc783`.

Audited the actual 11-file L scope against its report. All 731 pre-L protected
hashes, secret/whitespace/AST checks and `git diff --check` passed. The accepted
L results were 149 focused and 3,232 canonical tests. Only those 11 files were
committed locally; the tree was clean immediately afterward. No push. M remains
uncommitted and is not included in this checkpoint.

## 2. OSS heading/hierarchy recheck

The M addendum in `PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` records immutable
source links, exact functions/line ranges, licenses, kept patterns and rejections.
Current default-branch pins were resolved and actual implementation source read
before changing the heading policy:

- Docling Core `cc39622c6a4bb2643a8631edd996d8874a8e6a47` — MIT.
- Docling `1ceca3073e499dcc9da2dc802ac1f18bce672978` — MIT.
- LlamaIndex `fd4a517ad6490f0c8464a13fdf133760b696434a` — MIT.
- Haystack `ef9c9bba27dc40dd6d7854040c72283cbed326ec` — Apache-2.0.
- RAGFlow `03ca271f73de507e1dff531ec72c8ad8f05d4a4c` — Apache-2.0.
- Onyx `5fe6573c3c155e1a75b51de32d4988ee6c82164e` — MIT Expat, non-EE files.

Docling/Core directly distinguishes inherited headings and otherwise un-emitted
orphan headings. LlamaIndex/Haystack separate hierarchy storage from search-unit
selection. RAGFlow/Onyx distinguish contextual parent/title content from child
payloads. None supplies this application's exact tenant/version/byte-coverage
proof; that remains local. No upstream code copied, dependencies installed or
framework executed. Research network access is separate from network-denied
tests/evaluation.

## 3. Files changed

- `backend/services/structural_retrieval_entries_v2.py`
- `backend/scripts/structural_retrieval_heading_gold.py`
- `backend/scripts/evaluate_structural_retrieval_headings.py`
- `backend/test_structural_retrieval_headings.py`
- `backend/fixtures/structural_retrieval_heading_gold_v1/cases.json`
- `backend/fixtures/structural_retrieval_heading_gold_v1/manifest.json`
- `backend/fixtures/structural_retrieval_heading_gold_v1/v1_baseline_hashes.json`
- `backend/scripts/test_scoped_rag_regressions.py` — one registration.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — M source-study addendum.
- This report.

Ignored evidence and measurement JSONs live in `.codex_structural_4_1m/`.
Existing runtime/ingestion/retrieval/parser/v1 files are unchanged.

## 4. Measured L defect

L's digit/question/warning usefulness heuristic allocated a standalone entry to
every numbered section even when exact heading context was already carried by
the body entry. Its 1,000-section study therefore had 1,000 redundant headings
among 2,000 entries. This was allocation duplication, not missing graph/evidence.

M removes text-shape heuristics from its decision. During initial M validation,
a synthetic linked-heading regression caught a separate overstrict new check:
an inline link annotation was incorrectly required to be a hierarchy-path node.
The test failed before correction and now passes. Only actual heading nodes
must appear in `heading_path`; all linked text and provenance remain mandatory
exact mappings. Frozen GOLD expectations and v1 code were not changed.

## 5. v1 preservation

The entire L module remains byte-for-byte unchanged; no dispatch branch, patch,
monkeypatch or old version-name reuse. Its implementation hash remains
`0b32a7b29e930e72923ad43b7fbae167390a164d96e4b80a9f27fd1fe28aeaa8`.
Forty exact v1 full-batch hashes/recipes/counts/token totals were recorded before
v2 implementation in the new additive fixture directory. They are asserted by
tests. The frozen 23-document full-batch hashes are checked independently against
L's saved final output during M's 1x evaluator.

## 6. v2 policy/version

Explicit `structural-retrieval-entry-v2`, heading rule
`single-complete-admitted-context-witness-v2`. Its fingerprint includes all
policy fields, normalized v2 source hash and frozen v1 recipe (which includes
the unchanged source serializer/tokenizer). Every entry and batch receives a
new recipe-scoped identity; atoms retain their original exact identity.

Budgets remain target 500, soft 250–700, hard 800, context 80, max atom references
32 and maps 256. No grouping, source quality, resource, scope or token rules
were loosened. The new wrapper uses frozen L construction and validation; a
lossless rekeyed v1 validation view reuses its byte/ownership/budget checks.

## 7. Representation-coverage rule

A pure heading atom is contextual-only only if one selected non-heading body
entry carries every required source-backed heading byte and companion mapping
with the correct atom/node identity. Evidence from several entries cannot be
combined to fabricate a complete witness. The witness requires a real body
source part authorizing inherited heading context, not text equality or an
unrelated additional map. Numbers/punctuation/heading vocabulary are irrelevant.

## 8. Standalone-heading rule

Keep all original heading parts when no complete eligible witness exists.
Restore a source-backed standalone part if v1 suppressed it but v2's stronger
actual-selected-entry check cannot prove coverage. This uses the original exact
part text, companions and continuation identity; no new splitting or summary.
Orphans, context-budget omissions, partial inheritance and lexical-only/excluded
descendants do not count as a dense route. Typed FAQ/warning units are not
unpaired or reclassified to reduce counts. Empty headings remain graph-only.

## 9. Lexical guarantee

Every original atom and original `SerializationBatch` remains unchanged.
Contextual-only headings retain DENSE_AND_LEXICAL atom disposition because a
descendant entry maps them, plus an explicit CONTEXTUAL_ONLY allocation record.
The exact primary heading atom is independently available to a future lexical
index; its term does not require a duplicate standalone dense entry. Nothing
is indexed or written to FTS in this phase.

## 10. Context-witness rule

Witnesses require exact organization/bot/document/source-version/structural-
revision/crawl scope; matching source node and atom; full UTF-8 ranges;
original inherited source-part mappings; complete required companions;
80-token context bound; and compatible quality, proven resource, unresolved
ownership and navigation/quarantine barrier state. Ancestor heading paths can
reach nested sections; arbitrary equal text cannot. Indexed context membership
limits candidate inspection to local mapped entries, not corpus-wide matching.

## 11. GOLD inventory

`STRUCTURAL_RETRIEVAL_HEADING_GOLD_V1`: 42 cases frozen before v2 implementation.
LF-normalized case hash:
`de23126b411568c142c837fdb8b2f4e71e13821ac0995c96ec9cdde1036ac0f6`.

Covers numbered/roman/decimal headings, orphans, questions, warnings, numeric
facts, dates, ranges, legal clauses, error/module/version/price labels, Unicode,
duplicates, multiple descendants, partial context, omitted context, lexical-only
and excluded/quarantined descendants, nested/empty/very-long headings, quality/
resource/barrier boundaries, six generic domains, TXT, PDF/DOCX DTOs and typed FAQ.
Synthetic DTO fixtures explicitly separate heading allocation from parser role
inference; the separate typed FAQ and all original L fixtures preserve native
parser semantics. No existing GOLD changed.

## 12. Offline reachability proxy

An independent evaluator checks exact mapped source bytes, node/atom/scope,
lexical disposition and both reverse-lookup directions for every contextual-only
heading. It does not reuse the allocation predicate to decide expected results.
Foreign scope/version checks are negative tests. **This proves representation
reachability. It does NOT prove semantic dense recall.**

## 13. Saved-corpus v1/v2 comparison

Same frozen 23 documents, 201,377 source tokens, 13,213 graph nodes and 6,700
edges. Final 1x measurement uses the frozen final v2 implementation; an earlier
development measurement is not used for acceptance.

| Measure | Frozen v1 | v2 |
| --- | ---: | ---: |
| Searchable atoms | 3,242 | 3,242 |
| Entries | 1,120 | 1,030 |
| Entry tokens | 220,749 | 217,263 |
| Heading-only entries | 92 | 2 |
| Small entries (<250 tokens) | 837 | 747 |
| Mapping rows | 13,414 | 13,211 |
| Admitted / mapped evidence bytes | 894,386 / 894,386 | 894,386 / 894,386 |
| Unaccounted bytes | 0 | 0 |
| Lexical-only atoms | 0 | 0 |

752 heading atoms have complete contextual-only witnesses; two retain standalone
allocation: one has no descendant context entry; the other has an 85-token
original heading/context combination whose required ancestor heading is not
fully carried by the body entry under the 80-token context cap. Neither is kept
because of digits or wording. All 3,242 original atoms remain lexical-eligible. All 23 v1 hashes
equal L's frozen hashes; all 23 repeated v2 hashes match. The 90 fewer entries
are accepted only because exact witness/lexical/coverage checks pass, not because
lower count is inherently better. Reduced mapping-row count removes duplicate
representations, not original source mappings or admitted evidence bytes.
These are node-local evidence bytes; overlapping structural annotations can
refer to the same raw source interval. They are not a count of distinct facts
or unique raw-source bytes.

Ordered v1 batch digest:
`bfc73391f74b9f22eaa4f22aac2ed97d4e65cf2209bf9d48823659baa220bc65`.
Ordered v2 batch digest:
`5101cadbe166c65d12c5bf203099dc035bb2357d317274a045e52ebdf40209ee`.
Final v2 implementation hash:
`197ea1bb19ecec482352fde40c8b37300d5a85b82065030653b622c0b03a8243`.

## 14. Numbered-section scale result

The exact L Section fixture was reconstructed unchanged. At 1,000 sections:
3,001 atoms remain; v1 has 2,000 entries including 1,000 heading-only entries;
v2 has 1,000 body entries, **zero heading-only entries**, 19,000 search tokens
and 5,000 mappings. All 1,001 heading atoms (including the document heading)
have exact contextual witnesses and retain lexical identity. No source byte
is unaccounted for. This closes the measured digit-driven duplication defect.

Also ran Clause, Chapter, Article, Module, Step and Version at each of 10, 100,
500 and 1,000 sections: **28/28 study rows PASS**. Every label has the same
counts/coverage/fanout at each size; none is an implementation keyword. The
separate action-bearing Step GOLD follows the same coverage rule.

## 15. Document-size scaling

| Section count | Source tokens | Nodes / edges | Atoms | v1 entries | v2 entries | v2 tokens | v2 maps | Preparation s | Frozen v1 construction s | v2 revision s | Complete construction s |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 192 | 83 / 20 | 31 | 20 | 10 | 190 | 50 | 0.149301 | 0.037348 | 0.060526 | 0.097874 |
| 100 | 1,902 | 803 / 200 | 301 | 200 | 100 | 1,900 | 500 | 0.209319 | 0.401573 | 0.714897 | 1.116470 |
| 500 | 9,502 | 4,003 / 1,000 | 1,501 | 1,000 | 500 | 9,500 | 2,500 | 2.184852 | 4.942669 | 7.551930 | 12.494599 |
| 1,000 | 19,002 | 8,003 / 2,000 | 3,001 | 2,000 | 1,000 | 19,000 | 5,000 | 7.139932 | 10.919920 | 15.571937 | 26.491858 |

Every size: heading-only 0%; small-entry 100%; entry token min/p50/p95/max
19/19/19/19; maximum atom fanout 4; maximum mappings 5; unaccounted bytes 0.
Short protected sections remain short; no cross-section packing was introduced.

| Sections | Entries / 1k source tokens | Maps / 1k | Entry tokens / source tokens | Construction s / 1k |
| --- | ---: | ---: | ---: | ---: |
| 10 | 52.083333333 | 260.416666667 | 0.989583333 | 0.509761979 |
| 100 | 52.576235542 | 262.881177708 | 0.998948475 | 0.586997950 |
| 500 | 52.620500947 | 263.102504736 | 0.999789518 | 1.314944149 |
| 1,000 | 52.626039364 | 263.130196821 | 0.999894748 | 1.394161546 |

Counts scale exactly with section count. **Single-document timing is not
perfectly proportional at every size**: normalized cost rises between the small
and larger DTOs. The 100→500 step takes about 11.19x construction work for 5x
sections; both frozen v1 and v2 validation costs rise. The largest 500→1,000
step is approximately linear (about 2.12x complete construction and 2.06x v2
revision for 2x sections). Do not infer a universal linear runtime guarantee.
No heading-driven vector explosion remains. This bounded offline construction
cost is a capacity consideration for the later small canary design, not a
reason to remove coverage checks or an assertion about serving latency.

| 1,000-section label | Entries | Heading-only | Full construction s |
| --- | ---: | ---: | ---: |
| Section | 1,000 | 0 | 26.491858 |
| Clause | 1,000 | 0 | 26.758266 |
| Chapter | 1,000 | 0 | 27.017117 |
| Article | 1,000 | 0 | 26.496323 |
| Module | 1,000 | 0 | 26.491481 |
| Step | 1,000 | 0 | 26.435755 |
| Version | 1,000 | 0 | 26.468238 |

All 28 sequential study rows took 396.425039 seconds including unchanged source
preparation and verification. A document-study process memory peak was not
recorded; section 16's memory figures are for the separate saved-corpus workers.

## 16. 1x/10x/100x scaling

Two bounded local evaluator workers; every source is
actually reconstructed under a distinct namespace. No multiplication substitutes
for construction. Worker timings are summed work, not serial wall-time claims.
Full repeat-hash comparison is performed for all 23 sources at 1x. At 10x/100x
each independently scoped document is constructed once, with its hash recorded
in the ordered digest; those complete scale runs are not repeated twice.

| Scale | Distinct documents/scopes | Source tokens | Atoms | v2 entries | Entry tokens | Maps | Heading-only | Contextual-only headings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1x | 23 | 201,377 | 3,242 | 1,030 | 217,263 | 13,211 | 2 | 752 |
| 10x | 230 | 2,013,770 | 32,420 | 10,300 | 2,172,630 | 132,110 | 20 | 7,520 |
| 100x | 2,300 | 20,137,700 | 324,200 | 103,000 | 21,726,300 | 1,321,100 | 200 | 75,200 |

All counts, complete token/fanout histograms and allocation dispositions are
exactly proportional at 10x and 100x. Maximum fanout/maps remain 19/76. All runs
have zero unaccounted bytes and zero lexical-only atoms. At 100x, all 89,438,600
admitted node-local bytes remain mapped. No scope hash collisions.

| Scale | Namespace work s | Frozen v1 construction work s | v2 revision work s | Complete construction work s | Whole process wall s | Highest worker lifetime peak MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1x | 0.000026 | 17.950429 | 26.454372 | 44.404801 | 66.814704 | 660.960938 |
| 10x | 120.252078 | 192.437021 | 257.925003 | 450.362024 | 342.433893 | 607.246094 |
| 100x | 1,196.324767 | 1,915.597920 | 2,603.592280 | 4,519.190200 | 3,271.088196 | 629.906250 |

Each of the two workers also prepares the unchanged frozen parser/serializer
inputs once: approximately 12.3 seconds per worker. Whole wall time includes
that preparation, identity generation, construction, validation, metrics,
reachability checks and IPC; 1x additionally repeats all batches. The memory
column is the highest **individual worker** kernel-recorded lifetime peak, not
an aggregate process-tree peak. These are observed offline workstation figures.

10x and 100x construction-work ratios relative to 1x are 10.142192163 and
101.772558563 respectively: approximately linear measured work. No performance
optimization, parameter tuning or production-latency claim.

v2 10x ordered hash digest:
`89f11e0546461f1b951284d1e7b997e1202e35f3d079010a799d4851ec5d6574`.
v2 100x ordered hash digest:
`d3d8094321d956f908b0f8adcc5144d842e9a235fd8cfdd5f319ba8fb4a61217`.
All final runs report the same v2 implementation hash shown in section 13.
Frozen v1 ordered digests match the original L artifacts at **all three scales**,
not only 1x.

## 17. Normalized densities

| Metric | v1 1x | v2 1x |
| --- | ---: | ---: |
| Entries / 1,000 source tokens | 5.561707643 | 5.114784707 |
| Heading-only % | 8.214285714 | 0.194174757 |
| Small-entry % | 74.732142857 | 72.524271845 |
| Mapping rows / 1,000 source tokens | 66.611380644 | 65.603321134 |
| Entry tokens / source tokens | 1.096197679 | 1.078886864 |
| Maximum atom fanout | 19 | 19 |
| Maximum mappings / entry | 76 | 76 |

The same density values and full distributions hold exactly at 10x and 100x.

| Scale | Complete construction work s / 1,000 source tokens | v2-only revision work s / 1,000 source tokens |
| --- | ---: | ---: |
| 1x | 0.220505822 | 0.131367397 |
| 10x | 0.223641242 | 0.128080666 |
| 100x | 0.224414417 | 0.129289456 |

No absolute entry-count gate. The wrapper's additional validation is included,
not presented as a free allocation change.

## 18. Multi-tenant isolation

Identical text/title/URL across Org A/Bot A, Org A/Bot B and Org B/Bot A-equivalent
produces distinct atom, mapping, witness and entry identities. Cross-scope
construction, witness lookup, reverse lookup and validation reject. Scope is
separately caller supplied, never granted by source text or heading labels.

## 19. Version isolation

Source-version and structural-revision changes create distinct identities and
cannot witness old headings. Tests also cover bot/org/document scope and
foreign crawl-scoped entries. Policy changes change recipe/entry identities;
the old output remains immutable. Two partial entries cannot jointly satisfy
one full witness, even if their ranges add up to all the heading bytes.

## 20. Domain generalization

One unchanged policy covers commerce, hotel, software, course, legal, technical
and generic article examples. No customer, known product, saved ID, old count or
threshold runtime rule. Source-shape inspections and exact coverage are the
only heading allocation criteria. Step/action headings follow the same rule.

## 21. PDF/DOCX compatibility

Both frozen structural DTO formats use the same v2 policy with page-box
provenance. These are synthetic DTO compatibility tests, not fresh binary
conversion or a certification of arbitrary PDF/DOCX extraction fidelity.

## 22. Evidence/mapping preservation

Tests compare source graph, full evidence batch and atom tuples before/after.
Non-heading body texts, memberships, mapping ranges and boundary keys are
identical; only policy/recipe identities and ordinal positions change. Removal
of mixed heading/non-heading bodies is explicitly refused. Full legacy
validators plus v2 allocation validation run before returning any output.
All 740 pre-M protected hashes include the 731 pre-L files and nine frozen L
files (the authorized runner/OSS-ledger additions are excluded from the snapshot).

## 23. Focused tests

174/174 M + 149/149 L = 323/323 PASS, 71.092 seconds, external network denied.
Includes 42 GOLD checks, 42 repeats, 40 exact v1 baselines plus scope, budgets,
frozen data, link annotation, partial/split witnesses and scale regressions.
Four additional native-parser offline smoke cases (orphan question, orphan
warning, warning with body and orphan factual heading) also passed; no parser
semantics or source code were changed for those checks.
AST checks: 5/5 Python files PASS. Offline imports: 4/4 PASS. Final secret-pattern
scan and tracked/untracked whitespace scan: all 10 expected M files PASS.
`git diff --check`: PASS. Preservation: 731/731 pre-L and 740/740 pre-M hashes
PASS. All four final measurement files have the current v2 source fingerprint.
Exactly 26 report sections, with no pending measurements. No staged M files;
HEAD remains the local L checkpoint. No unrelated file changes.

Commands from `backend` (venv Python, `-B`; focused/canonical commands additionally
wrapped in external connection/DNS denial, with only asyncio's internal
loopback socketpair permitted):

```text
.venv\Scripts\python.exe -B -m unittest test_structural_retrieval_headings test_structural_retrieval_entries
.venv\Scripts\python.exe -B -W ignore::DeprecationWarning scripts/test_scoped_rag_regressions.py
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_headings.py --saved --scale 1 --workers 2 --output ../.codex_structural_4_1m/saved_1x_final.json
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_headings.py --saved --scale 10 --workers 2 --output ../.codex_structural_4_1m/saved_10x_final.json
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_headings.py --saved --scale 100 --workers 2 --output ../.codex_structural_4_1m/saved_100x_final.json
.venv\Scripts\python.exe -B scripts/evaluate_structural_retrieval_headings.py --document-scale --output ../.codex_structural_4_1m/document_scale_final.json
```

## 24. Canonical suite

**3,406/3,406 PASS**, 462.763 seconds, exit 0: unchanged 3,232 baseline plus
174 M tests. Includes all 1,000 previous A–J structural tests, all 149 L tests
and all M tests. External connections/DNS/HTTP and configured application DB
access were denied. Expected Redis-outage warnings reported the denied network;
they were not live access. Existing isolated in-memory test fixtures are not
application/customer/persistent DB access. This complete run overlapped roughly
documents 207–575 of the two-worker 100x measurement.

## 25. Limitations

- No embeddings, actual dense recall, query/FTS/RRF retrieval, structural
  expansion runtime or final-answer claim. Exact offline reachability only.
- No enriched source capture, Firecrawl, HTML sidecar or anchor registry.
- Revalidating DTOs and retaining exact evidence costs CPU/memory; the v2 wrapper
  currently constructs/validates v1 before allocation and reuses its validators.
  Work remains document-local and bounded; not a streaming/constant-memory parser.
- Timings are local synthetic/offline measurements, not production serving
  latency or embedding costs. Two-worker wall time is distinct from summed work.
  The canonical suite overlapped an early portion of the 100x run; a brief
  file-only inspection of the two retained headings also overlapped it. This
  was not an isolated hardware performance benchmark.
- Small protected sections legitimately stay small. Lower count alone is not
  better; every suppressed heading must satisfy its exact witness.
- Source topology/semantics are those already present in the frozen graph;
  this phase neither recaptures missing structure nor changes parser decisions.

## 26. Exact next step and measured decision

**A. PHASE 4.1M — COMPLETE**

**GENERAL CONTEXTUAL RETRIEVAL-ENTRY REPRESENTATION VERIFIED**

**HEADING POLICY CLOSED**

**SCALE / COVERAGE / MULTI-TENANT GATES PASS**

**READY FOR SMALL DEVELOPMENT EMBEDDING + HYBRID RETRIEVAL CANARY DESIGN**

The measured heading duplication is closed without changing evidence, v1,
body packing or scope boundaries. Exact coverage, 28 document-size studies,
actual 1x/10x/100x counts/distributions and all 3,406 tests pass. The largest
single-document step and multi-document construction scale approximately
linearly; the smaller-to-larger DTO timing transition is explicitly disclosed
in section 15. This is readiness for a bounded **design**, not live-retrieval,
embedding-recall, activation or production approval.

Exact next step: separately design a small development embedding + hybrid
retrieval canary, with immutable source/version pins, measured child-evidence
discoverability, scope/coverage gates and construction capacity review. Do not
implement or activate it in this task. Enriched source capture remains separate.

No canary implemented or activated. No provider/model call,
embedding, external/persistent database access, customer-corpus mutation, production action, push or
deployment. Only the separately authorized local L checkpoint was committed;
M remains uncommitted for review.
