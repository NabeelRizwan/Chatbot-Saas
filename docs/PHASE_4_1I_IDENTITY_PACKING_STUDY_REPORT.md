# Phase 4.1I — heading answerability and explicit resource identity

Date: 2026-09-16. Offline study only; Phase I remains uncommitted.

## Decision

**C. PHASE 4.1I — COMPLETE**

**IDENTITY QUALITY STILL INSUFFICIENT**

Exact prerequisite: obtain a frozen, source/version-pinned descriptor that
explicitly proves the subject and boundaries of each relevant resource block
(or proves a single-resource root with a complete, noncontradictory inventory).
For fragment-bearing review links, require a verified target/anchor mapping;
do not manufacture it from URL similarity, title, or proximity. Re-evaluate the
46 unresolved pairs offline before proposing any identity-based selector change.
The descriptor must also reconcile original source versions without relabeling
H's frozen study graph: two captured document versions do not match H's study
version labels and their resource mappings are currently withheld.
No live catalog edit, recrawl, or automatic v2.1 implementation is authorized by
this report.

Identity evidence remains insufficient, so this result does **not** establish
that the current cost is irreducible, nor justify immediate cost acceptance or
embedding-staging work. The only measured incremental saving is two generic
heading candidates / 57 tokens. No actual saved-corpus peer became packable.

## H checkpoint and preservation

Audited the nine H files against the H report and the accepted validation:
106 focused H, 759 A–H structural, and 2,842 canonical tests. No runtime consumer,
DB/provider/embedding path, secret, environment file, ignored evaluation output,
or unrelated file was included. `git diff --check` passed.

Local H commit: `1168b6754ee5540ba72dc8ccea2290dab0632d84`

Message: `Phase 4.1H: add conservative offline structural selection v2`

Parent G: `6f797efe34bf91391906fd9a44137ca5ee999b5f`. No push.

An initial raw-versus-LF-normalized H JSON hash comparison was corrected in the
audit command; the artifact itself was not edited. I preservation inventory
contains 300 pre-existing service, source/corpus, GOLD, answer/grade and G/H
artifacts. All 300 remain byte-identical. Every saved document's v1 batch, graph
and H selection canonical hash was also replayed and matched exactly.

## Current-source research and local audit

Actual source and licenses were inspected before implementation. The appended
`PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` records per-rule file/function, repository,
pin, license, accepted/rejected pattern and rationale. No literal code copied;
pattern adaptation only. No framework dependency was installed.

| Project | Current source pin | Material distinction |
|---|---|---|
| Docling Core | `cc39622c6a4bb2643a8631edd996d8874a8e6a47` | Located item/reference identity versus contextual heading text; heading emission is not answerability proof. |
| RAGFlow | `701b82aa1e6baf4e79fd253658cc2e045b1655eb` | Document/knowledge ownership and retained mother context versus text-derived subject identity. |
| LlamaIndex | `fd4a517ad6490f0c8464a13fdf133760b696434a` | SOURCE/PARENT/CHILD and `ref_doc_id` identify source/hierarchy, not necessarily paragraph subject. |
| Haystack | `0defdcff64950ca54f4dac0d21fe4eb30ed745d7` | Detached source/split/parent metadata; hierarchy alone is not business subject. |
| Onyx | `a8804f2b8869499bb6f4932195a06575974debfe` | Connector/source identity versus display/semantic identifier, title and link context. |

Local source inspected: resource projector/model/schema, coverage manifest,
immutable structural graph and mappings, C's review/link rules, and canonical
crawl/navigation URL handling. Coverage-manifest title/path inference is not
adopted as authority. No application code changes.

The production snapshot's four catalog collections are empty. Its existing
frozen development projection has 23 resources, 23 primary document links, 91
terms and one catalog-state record. All resources have type `document` and a
`document:<id>` source key. They establish document ownership, not single-subject
page scope. The evaluator checks captured scope, explicit source-to-development
mapping, status, version, crawl, primary link, canonical URL and corpus fingerprint
before constructing H's existing offline study namespace. It does not grant
live access or inspect any database.

The final source-version guard exposed documents 13 and 14 as version 2 in the
snapshot/catalog versus version 1 in H's historical synthetic replay. I does not
rewrite H or relabel those versions. Their two resource mappings are explicitly
refused with `source_version_mismatch`; 21 of 23 document-only descriptors enter
the identity registry. All 23 source graphs still participate in the evidence
and cost study. Cross-tenant, stale catalog-to-document versions/crawls and
inconsistent canonical mappings remain hard refusals rather than silent repair.

## Heading model and frozen GOLD

Closed taxonomy: STRUCTURAL_LABEL_ONLY, INDEPENDENT_FACT, QUESTION_HEADING,
NUMERIC_FACT, QUALIFICATION, WARNING, RESOURCE_IDENTITY, SECTION_IDENTITY,
AMBIGUOUS. Unknown labels are retained, not declared disposable.

Signals include typed role/payload, semantic edges, visible punctuation/numbers,
small reviewed warning/qualification/fact vocabularies, explicit subject proof
and a complete same-descendant mapping witness. Existing pinned CommonMark grammar
separates visible text from href query punctuation and image-filename digits;
this view is classification-only. Marked-up labels never become generic
metadata-only headings merely because their visible text matches a label.

A metadata-only **proposal** requires both a closed generic non-factual label
and every original heading/context mapping coexisting in ONE retained nonheading
descendant with identical node identity, source slice and role. No scattered
union, missing ancestor, cross-document equal text, or missing witness suffices.
Warning/qualification/numeric/factual/question/identity or uncertain headings stay.
These are I proposals; H's label list and selection recipe are untouched.

HEADING_ANSWERABILITY_GOLD_V1: 30 hand-authored expectations frozen before first
implementation evaluation. Covers labels, orphan/duplicate headings, important
standalone/repeated facts, questions, numeric/timeline, qualifications, warnings,
proven/unproven names, collection labels, adversarial text and hotel/software/
course/legal examples. Resource GOLD similarly froze 29 expectations. Neither
GOLD expectation file was revised to fit results; later adversarial unit tests
are additional tests, not retroactively frozen annotations.

### Sample

56 / 754 headings, frozen before rule evaluation. For each independent stratum,
select the two lowest SHA-256(document ID + spec ID), then union. Covers all 23
documents and all 49 present strata across depth, token length, duplicates,
question/numeric raw-source features, descendants, commercial/list/timeline
proximity, repeated-label frequency and tiny status. This is not a full Cartesian
stratification or a random accuracy estimate. Original raw-source sampling bins
are unchanged, including punctuation inside URLs.

Final sampled categories: 49 ambiguous, 3 numeric, 2 questions, 1 warning,
1 structural-only. Manual source spot-checks exposed URL `?` and image filename
digits as false taxonomy signals; the classification view now excludes those
syntax artifacts. The frozen sample itself and GOLD stayed unchanged. This
sample has no independent 56-case semantic-accuracy ground truth.

### Full saved heading population

| Category | Count | Disposition |
|---|---:|---|
| STRUCTURAL_LABEL_ONLY | 12 | Metadata-only proposed, exact descendant witnessed |
| INDEPENDENT_FACT | 1 | Keep |
| NUMERIC_FACT | 52 | Keep |
| QUESTION_HEADING | 11 | Keep |
| QUALIFICATION | 10 | Keep |
| WARNING | 20 | Keep |
| RESOURCE_IDENTITY / SECTION_IDENTITY | 0 / 0 | No qualifying saved proof/closed label |
| AMBIGUOUS | 648 | Keep |
| Total | 754 | 742 retained; 12 proposed metadata-only |

94 have explicit answer-bearing/conservative retention signals; 648 remain
ambiguous, not empty. The two additions to H's ten are source headings
`### Directions` and `### DIRECTIONS` in documents 28 and 29. Their complete
three-mapping heading/context sequences survive in their own retained directions
candidate, including the original ancestor context and full use instructions.
No heading text, source association, qualifier or quantity is rewritten.

## Subject/resource model and frozen GOLD

Pure immutable DTOs: pinned resource key/version/anchor/canonical URL/mapped
sources; a frozen scoped registry; explicit root proof; and subject evidence
carrying state, subject set, structural group, deterministic basis, evidence
nodes and reason. States: RESOLVED, UNRESOLVED, MULTI_SUBJECT, PARTIAL.

- Single-resource root: exact authorized mapping **plus** a separately explicit
  single-resource assertion and complete inventory. Any known competing block
  invalidates the root assertion. A document-only catalog row is insufficient.
- Typed card/review: safe, exact registered links bind only the explicit group.
  Reviews use C's existing source-labeled review/signature boundaries; nearby
  unrelated links supply references only. Validated DESCRIBES or typed REFERS_TO
  must hit an exact authorized registered anchor. No URL fetch or normalization.
- Propagation: actual ancestor tree within the nearest proven group. Nested
  explicit or unresolved card/review groups stop outer inheritance. Siblings do
  not borrow another sibling's subject. CONTAINS alone is structure, not subject;
  an arbitrary cross-tree edge cannot relocate source ownership.
- Conflicts: multiple valid targets remain MULTI_SUBJECT; no winner is chosen.
  A candidate with any unproven primary evidence is PARTIAL and cannot pack.
- Authorization: registry inputs are already-frozen authorized descriptors;
  full org/bot/document/version/hash/revision identities are checked. This study
  is relevance metadata only, never a replacement for HardKnowledgeScope.

STRUCTURAL_RESOURCE_IDENTITY_GOLD_V1 covers all positive/negative source cases:
single/multi-resource, card/review links, multiple reviews, unlinked headings,
nearby links, repeated names, shared URL prefixes, identical names in different
documents, ambiguous/missing targets, cross-document relations, cross-tenant
rejection, nested/sibling/conflicting groups, partial candidates and no inventory.
Hotel room/package, software feature group/plan, course/module, legal policy and
generic document fixtures exercise the same generic identity contract.

## Saved identity and strict H packing results

| Population | Resolved subject | Unresolved subject | Multi / partial |
|---|---:|---:|---:|
| 3,242 v1 specs | 0 | 3,242 | 0 / 0 |
| 3,232 H candidates | 0 | 3,232 | 0 / 0 |
| 13,213 graph nodes | 0 | 13,213 | 0 / 0 |
| 2,209 H graph-only nodes (subset above) | 0 | 2,209 | 0 / 0 |

There are 110 exact registered link references and 1,359 unresolved references.
None establishes a qualifying saved subject group under this evidence policy.
References must not silently become positive subjects. No captured descriptor
proves a single-resource page root.

For example, source-labeled review links in document 13 point to canonical product
paths followed by `#reviews`, but the captured catalog stores base URLs only.
The current registry does not provide those fragment anchors; the study does
not strip the fragment and assert identity. Frozen review grouping can also
include trailing next-item image/count context; proving a business-subject scope
requires source-boundary evidence, not just trusting a group label. No graph,
adapter, mapping or corpus repair was attempted here.

All 46 H unknown-identity adjacent pairs (83 distinct specs):

- Same proven subject: 0.
- Different proven subjects: 0.
- Still unresolved: 46.
- Newly eligible under unchanged H guards: 0.

Other H pair refusals remain 2,841 atomic-kind, 321 parent and 11 section.
The study adapter changes only the identity evidence input; it inherits the exact
H `peer` and `pack` functions. Same revision, adjacency, parent/section, identity,
role, quality, semantic edges, warnings/qualifications, typed atomic units and
token/mapping caps all remain enforced. Calling H selection `run()` through the
study adapter is explicitly refused. Synthetic proven peer fixtures demonstrate
eligibility and lossless packing; those are not claimed to occur in this corpus.

## I SIMULATION — not accepted v2

| Measure | Legacy | Frozen v1 | Frozen H v2 | I SIMULATION |
|---|---:|---:|---:|---:|
| Candidates/specs | 1,092 | 3,242 | 3,232 | 3,230 |
| Stored candidate-string tokens | 212,061 | 278,491 | 278,234 | 278,177 |
| Heading candidates | Not classified | 754 | 744 | 742 |
| Packed groups | Not comparable | Not an H policy | 0 | 0 |
| Metadata-only headings | Not classified | 0 | 10 | 12 |
| Unknown-peer specs retained | Not classified | No selection state | 83 | 83 |
| Subject-resolved candidates | Not evaluated | 0 | 0 | 0 |
| Subject-unresolved candidates | Not evaluated | 3,242 | 3,232 | 3,230 |
| Tiny candidates (<50 tokens) | Not evaluated | 1,452 | 1,442 | 1,440 |
| Float32 vector lower bound, 768 dimensions | 3,354,624 B | 9,959,424 B | 9,928,704 B | 9,922,560 B |

Vector values are arithmetic estimates only, not embeddings generated, actual DB
footprint, ANN cost or latency measurements. I saves 12 candidates / 314 tokens
against v1; only 2 candidates / 57 tokens / 6,144 vector bytes against H.

Historical targets remain 1,638 candidates and 275,679 tokens. I remains above
them by **1,592 candidates / 2,498 tokens**. Do not treat G's hypothetical 606
suppressed headings as accepted savings. Even if every existing unknown pair
were later proven eligible, those 46 adjacency edges alone cannot bridge H's
1,594-candidate gap; caps/other guards could reduce that hypothetical saving.
This bound is not proof that all other costs are fundamentally irreducible.

## Evidence, determinism and validation

All 13,213 graph nodes / 6,700 edges retained. I graph-only count is 2,211 (two
additional headings are still in the graph and descendant context). Exact union
of mapped source byte ranges by node identity remains **894,386 bytes**.
Every one of 18,137 original logical mappings is accounted for: I has 18,111
candidate translations plus 26 same-descendant heading witnesses. Each translated
byte slice was checked against its original mapped source bytes. Evidence loss: 0.

| Validation | Result |
|---|---|
| New focused I tests | 133 / 133 PASS |
| Frozen A–H structural suite | 759 / 759 PASS |
| Complete canonical backend suite | 2,975 / 2,975 PASS (2,842 prior + 133 I) |
| Network-denied 23-document evaluation | PASS; exact v1/graph/H replay |
| AST / import checks, secret scan, final diff check | PASS |
| 300-artifact preservation inventory | PASS, all byte-identical |

The initial focused authoring run exposed a test-helper attribute typo and the
not-yet-appended ledger; both were completed without changing GOLD expectations.
Earlier complete suites passed 2,958 and 2,974 tests during test development;
the last complete suite passed 2,975 in 538.494 seconds. An intermediate saved evaluation
stopped at the new version guard; the final evaluator records and withholds the
two incompatible mappings instead of failing the entire study or making them
authority. The negative test requires empty resource/root-proof authority and
UNRESOLVED evidence for a mismatched source, plus the exact refusal ledger.
No previously committed tests were weakened
or removed. Existing offline suite DB fixtures are isolated; configured database
connections and external sockets/DNS/HTTP were denied. Local socketpair creation
alone is permitted for Python asyncio's in-process wakeup mechanism.

Validation sequence: the complete 2,975-test process had loaded its I tests before
the final catalog-version handling was changed from whole-study abort to explicit
mapping refusal. After that I-only change, **all 133 focused I tests** were rerun
on the final files (133/133 PASS), as was the complete 23-document saved evaluation
(PASS). No prior application, A–H or other test implementation changed; their
preservation hashes match. Do not describe the earlier full process as having
executed the later I branch. Final I coverage is supplied by that focused rerun.

Focused tests cover GOLD, missing/scattered witnesses, exact mapping and zero-loss
translation, deterministic annotations/simulation/sample, contradictory roots,
registry scope/version/hash/crawl guards, no title/URL-prefix inference, no fragment
guessing, review/FAQ/timeline/commercial/list/table/warning boundaries, source
revision and token caps, H frozen hash, no runtime consumers and no DB/provider
imports. Frozen catalog loader tests exercise real explicit namespace rebasing;
catalog-document identity still does not become a subject.

### Key frozen hashes (raw SHA-256)

- Source snapshot: `4dc2bd9835b4e4e9a799a679dd08f9a36fc38cd419cab37be36d1abc71fcc662`
- H output: `83d8c98dd7de9c82a6c65c309d4ed2367016612990ab6ee43aa3789e0e47fcd8`
- Frozen sample: `756dae53035252246c7aad3007ef2e9cc4893e12b67c8d812f6124e8aa9a70ff`
- Heading GOLD cases: `ceb24073f6bc3f1b3197ce9331b8390e3b8fe68fedb9ee2f7467495b23d5b628`
- Resource GOLD cases: `88cbbaf68565c7bfb2ae3dfaecc43675d780dea1bf22cb04a5ae92ee97d66464`
- Final I study output: `41c2168b881702a07dd1fc3da9bff2f4dcf356f3a2faf54fb9093be85f59dfc9`

Full source/mapping/catalog/sample hashes and per-node/spec/heading/pair ledgers
are in ignored `.codex_structural_4_1i/study_final.json`; sample inputs and the
300-file preservation inventory are in that same ignored directory. No source
metadata or secrets are copied into tracked GOLD or reports.

## I files changed

- `backend/scripts/structural_identity_study.py` — pure annotation/taxonomy and strict H study adapter.
- `backend/scripts/structural_identity_features.py` — rule-independent sample features/selection.
- `backend/scripts/structural_identity_gold.py` — synthetic source/registry fixture builders.
- `backend/scripts/evaluate_structural_identity_study.py` — frozen catalog validation, replay and I-only simulation.
- `backend/test_structural_identity_study.py` — focused tests.
- `backend/fixtures/heading_answerability_gold_v1/cases.json`
- `backend/fixtures/heading_answerability_gold_v1/manifest.json`
- `backend/fixtures/structural_resource_identity_gold_v1/cases.json`
- `backend/fixtures/structural_resource_identity_gold_v1/manifest.json`
- `backend/scripts/test_scoped_rag_regressions.py` — add only the I test module.
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — append I research.
- `docs/PHASE_4_1I_IDENTITY_PACKING_STUDY_REPORT.md` — this report.

## Limitations and scope closure

This is deterministic source/mapping evidence, **not** semantic retrieval recall,
model answer quality or production acceptance. A closed conservative taxonomy
can retain headings that a human could classify more precisely; it never makes
AMBIGUOUS disposable. No saved-page single-resource assertion can be invented
from the current document catalog. Exact-reference matching deliberately abstains
on unregistered fragment URLs. No cost-target tuning was applied.

No modification of v1, H policy, graph contracts, live shadow/ingestion, resource
catalog/aliases, retrieval, query understanding, conversations, prompts, models,
activation or runtime settings. No persistent DB connection, production access,
provider call, crawl, re-ingestion, embedding or external evaluation network.
No I commit, push or deployment. Stop at this measured Phase I decision.
