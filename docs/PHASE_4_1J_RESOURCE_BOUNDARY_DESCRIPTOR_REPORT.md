# Phase 4.1J — Source-Pinned Resource Boundary Descriptor Study

Date: 2026-09-16. Offline source-file/DTO study, not a serving implementation.

## Decision

**C — PHASE 4.1J — COMPLETE**

**SAVED SOURCE DOES NOT CONTAIN ENOUGH IDENTITY / BOUNDARY EVIDENCE**

**SOURCE-CAPTURE ENRICHMENT DESIGN REQUIRED**

The descriptor contract and conservative refusal behavior are tested, but this
saved corpus cannot supply verified fragment targets or complete root-subject
inventories. Separately, identity alone offers **zero additional packing** under
the unchanged H policy: all 46 identity-blocked pairs fail a later guard even
when the same subject is counterfactually assumed. Do not keep improving
identity solely to pursue the historical candidate-count target.

## 1. Phase I checkpoint and preservation

Starting H HEAD: `1168b6754ee5540ba72dc8ccea2290dab0632d84`.

I checkpoint: `76c142ffb14f0a591a7dcd271adff70abf6483d5`.

Local commit: `Phase 4.1I: add offline identity and packing study`.
Only the 12 I files listed in its report were staged. The audit verified all
300 prior preservation artifacts, no runtime consumer, no selector/v1/catalog
change, clean whitespace and no secret-shaped material. The previously accepted
133 focused / 759 A–H / 2,975 canonical results were accepted as authorized.
Working tree was clean immediately after that local commit. Nothing was pushed.

J froze a wider **684-file** preservation inventory: prior artifacts, H/I
outputs/GOLD/reports/source and committed application files. The only exclusions
from that inventory are the explicitly extended OSS ledger and test runner.
All 684 hashes remained unchanged before/after J evaluation. H was independently
replayed and its saved batch/graph/selection identities matched. J remains
uncommitted; HEAD is the I checkpoint.

## 2. Current OSS source study

Actual source and licenses were inspected, not only documentation. HEAD pins:

| Project | Current inspected commit | Source observations |
| --- | --- | --- |
| RAGFlow | `7bc159d64e565d7fa93cd56b866772dad66edf31` | Task chunks carry doc/kb ownership; NLP trees accumulate title paths and boundaries. Neither establishes every paragraph's semantic subject. |
| Onyx | `4ea423849cb0dc7e0df69096fbc650572bc08579` | Connector document ID, semantic_identifier, sections/link and chunk source_links offsets are distinct; semantic_identifier is primarily a document/UI identifier. |
| LlamaIndex | `fd4a517ad6490f0c8464a13fdf133760b696434a` | ref_doc_id follows SOURCE; parent/child relationships and IndexNode reference objects are not semantic-subject assertions. |
| Haystack | `0defdcff64950ca54f4dac0d21fe4eb30ed745d7` | source/split/parent/children IDs preserve hierarchy and copied metadata, not resource identity. |
| Docling Core | `cc39622c6a4bb2643a8631edd996d8874a8e6a47` | Item refs, exact internal target resolution, original text, provenance and hyperlinks are separate. A hyperlink does not verify an external anchor. |

RAGFlow/Onyx pins advanced since I; source was fetched at these new pins. The
other current HEADs matched I's downloaded source, which was reread; Docling's
TextItem hyperlink implementation was additionally fetched. No copied code,
dependency installation, or upstream execution. File/class/license/adaptation
details and repository links are in the J addendum to
`docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md`.

Local inspection covered resource_catalog/projector, resource models/schema,
coverage manifest, URL normalization, document/website/crawl identities,
structural links, review REFERS_TO construction, card/collection candidates and
the frozen mapping files. The crawler's fragment-stripping normalizer is not
used for J. No business ontology was added.

## 3. Files changed in J

- `backend/scripts/structural_resource_descriptors.py`
- `backend/scripts/structural_descriptor_corpus.py`
- `backend/scripts/evaluate_structural_resource_descriptors.py`
- `backend/test_structural_resource_descriptors.py`
- `backend/fixtures/structural_resource_descriptor_gold_v1/cases.json`
- `backend/fixtures/structural_resource_descriptor_gold_v1/manual_saved.json`
- `backend/fixtures/structural_resource_descriptor_gold_v1/manifest.json`
- `backend/scripts/test_scoped_rag_regressions.py` — one module registration
- `docs/PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md` — J addendum only
- `docs/PHASE_4_1J_RESOURCE_BOUNDARY_DESCRIPTOR_REPORT.md`

Research, preservation inventory and detailed results are ignored artifacts in
`.codex_structural_4_1j/`; not staged. No services, schemas, routes, worker,
configuration, parser, v1, H selector, or I implementation file changed.

## 4–5. Descriptor architecture and vocabulary

`SourcePin` contains the complete revision/source identity (development org/bot,
document, actual source version, immutable text hash, document-version ID),
original source org/bot/document, mapped crawl ID/version and canonical URL.
`BoundaryProof` contains DOCUMENT / SECTION / GROUP / CARD / REVIEW /
LINKED_BLOCK scope, root, ordered member IDs, half-open preorder interval,
source-byte envelope, evidence node IDs, target and assertion basis.

`StructuralResourceDescriptor` keeps that proof, resolution state, resource keys,
exact target result, conflict information/reason and deterministic canonical
hash. States: RESOLVED, PARTIAL, AMBIGUOUS, UNRESOLVED, STALE. Invalid scope or
boundaries raise a refusal; stale pins never enter node assignments.

Closed basis vocabulary: DOCUMENT_RESOURCE_ASSERTION, EXPLICIT_RESOURCE_LINK,
EXPLICIT_CARD_LINK, REVIEW_PRODUCT_LINK, CANONICAL_DOCUMENT_MAPPING,
EXPLICIT_RESOURCE_GROUP, VERIFIED_FRAGMENT_TARGET, CONTAINS_RELATION,
REFERS_TO_RELATION, MANUAL_FROZEN_GOLD. No fuzzy/title/path/proximity authority.

Explicit assertions supplied to this offline study are trusted, frozen reviewed
evidence inputs, not claims automatically inferred from their text. The local
automatic path derives only signature-terminated review blocks. Boundary and
target validation are independent. None of these values grants authorization.

## 6. Inventory of all 23 saved sources

Detailed inventory rows preserve source pin, node identity, provenance spans,
structural members, link target/state and whether a boundary is proven.

| Observed inventory | Count |
| --- | ---: |
| Document roots | 23 |
| Explicitly typed review groups | 86 |
| Linked headings / possible collection-child blocks, NOT proven cards | 147 |
| Explicit typed cards with captured ownership boundary | 0 |
| Exact cross-document references | 76 |
| Other unclassified references | 1,393 |
| Explicit navigation-role link nodes | 0 |

Zero explicit navigation-role nodes does **not** mean no navigation exists.
Flattened source contains it, but J does not label it by URL/path similarity.
The 147 linked headings are recorded as candidates, not converted into semantic
cards or linked-body ownership. Standalone links remain references only.

## 7–8. Native namespace and version reconciliation

J parses the same frozen UTF-8 bytes into a NEW `phase-j-native` namespace using
the exact captured source→development mapping (source 1/1 to development
538/674). This is local DTO identity only: no connection or row mutation.
Actual versions: **documents 13 and 14 = 2; all other 21 documents = 1**.
All 23 primary catalog mappings pass exact version/crawl/canonical/source-scope
checks. Catalog resource-row version and linked document version are kept
distinct. Captured website active-crawl membership is checked too.

The source hash is SHA-256 of the exact saved raw-text bytes being parsed,
anchored by the immutable snapshot/fingerprint and mapping files. It is not
guessed from a URL or a similarly named resource. A newer descriptor is never
applied to H's v1 source identities.

H and J node keys legitimately differ. An explicit parser-path/order/content/
attribute/provenance-location bijection proves equivalent payloads; edges are
compared as translated multisets because canonical hash sorting can reorder
them across namespaces. Every spec text, kind, ordinal, token count, logical
mapping, source range and output range is compared. This is reconstruction from
source bytes, not relabeling H. Old H/I files remain unchanged.

## 9. Single-resource root proof

A full-root descriptor requires an exact current mapping, one explicit primary
assertion, matching canonical pin, entire root member inventory, explicit
inventory completeness and no unresolved or competing source references or
inventory descriptors. Multiple assertions/conflicting subjects are ambiguous;
incomplete/unresolved inventory is partial. Document mapping alone is lineage.

Saved corpus: **0 roots proven; 23 refused**. No saved authoritative primary
subject + complete noncontradictory resource inventory exists. Product-looking
titles and canonical document URLs do not override embedded cross-sells/reviews.

## 10–12. Multi-resource, review and card boundaries

Validation requires a real root and exact same-source/version/revision members,
ordered contiguous preorder interval, exact byte envelope and evidence within
that interval. Sibling leakage, holes, missing/duplicate members and invalid
start/end bytes are refused. Explicit strictly nested descriptors override their
ancestor; nested abstention blocks inheritance. Equal or crossing conflicting
scopes remain ambiguous. Multi-node specs need every primary node resolved to
one resource; partial coverage cannot satisfy H's identity guard.

Reviews use the existing source-label/signature grammar. A unique signature
identifies the target-link evidence; the boundary ends at that signature's final
descendant. Trailing images/navigation under the same C group are excluded.
A nearby link outside the signature cannot identify the review. No signature or
multiple signatures means no inferred boundary. Fragment verification remains
separate, so all saved review descriptors currently abstain.

Cards/other linked groups require explicit frozen source-backed boundary
assertions. Linked heading + surrounding prose is insufficient. Synthetic GOLD
tests cover separate cards, nested groups, foreign siblings and distinct targets;
the saved corpus contains no authoritative card-boundary capture.

## 13–14. Link and fragment verification

The exact original href, base and fragment are separate. No normalization strips
query/fragment or matches a path prefix. Even an empty `#` is not silently erased.
Relative URLs require a separately pinned binding to the exact source link node;
J does not resolve them via a guessed base or fetch. Unsafe schemes/credentials
are refused. Duplicate targets/anchors are ambiguous; stale target pins refuse.

An accepted synthetic anchor proof names an exact saved node and literal quoted
HTML id/name declaration. Inert HTML parsing verifies an actual declaration;
heading text, prose mentioning an attribute, fenced examples and `reviews` as a
name are insufficient. This is a frozen target registry, not live HTML parsing.

Saved link results (1,469 references): **110 EXACT_RESOURCE**, **461
UNRESOLVED_FRAGMENT**, **898 MISSING_TARGET**, 0 ambiguous/unsafe/stale.
There are **523 fragment-bearing references**: 461 have an exact registered base
but unverified fragment; 62 lack even a captured registered base. **0 verified
fragments**. The 110 exact base references do not assign nearby body subjects.

Read-only inspection of all 23 saved raw texts found **0 literal HTML id/name
declarations**. Captured metadata has no saved raw HTML, anchor registry,
DOM-block map or JSON-LD identity payload in the inspected capture fields. No
current customer pages were visited. A review-looking target page is not proof
of the historical `#reviews` anchor.

## 15. Frozen GOLD

`STRUCTURAL_RESOURCE_DESCRIPTOR_GOLD_V1`: **72 hand-authored synthetic cases**
frozen before generator implementation/evaluation, plus two separately reviewed
saved-source descriptors frozen before evaluation. The manifest binds:

- cases SHA-256: `15d0ba8381adbec5815cb9712b0d309973a5895c81829cc3ae240061ff1296c2`
- manual SHA-256: `1e27dab5cd64ea03868987c78a94477e67643a22d443fcefb4cba9bd9413e66d`
- snapshot SHA-256: `4dc2bd9835b4e4e9a799a679dd08f9a36fc38cd419cab37be36d1abc71fcc662`

Expectations cover every requested scope, exact/stale/foreign pins, conflicting
root inventory, cards/reviews/nested blocks, exact/ambiguous/unsafe/relative/
fragment links and non-commerce cases. No customer-specific runtime rule.

## 16. Automatic descriptor result

86 bounded review descriptor attempts: **0 resolved, 0 partial, 0 ambiguous,
0 stale, 86 unresolved**. Their fragment targets lack proof. Root refusals are
reported separately (23), not fabricated as successful descriptors.
All 3,242 native v1 specs and all 3,230 J/I-retained candidates remain unresolved.
There are no automatic packing groups, no new heading decisions and no savings.

## 17. Manual frozen GOLD experiment and upper-bound limit

Two reviewed FAQ windows (saved documents 3 and 32) have explicit named-subject
assertions and exact primary document mappings. Their pins, node IDs, source
windows and reviewed assertion excerpts are in `manual_saved.json`. Boundaries
end at `View More`; document 3's following subscription furniture is excluded.
They do not assert a full root or invent any anchor.

Manual-only additions: **2 resolved descriptors / 6 resolved retained
candidates**. Two H pairs become same-resource; both still fail H's qualification
guard. Manual result: **3,230 candidates / 278,177 tokens / 0 packed groups**.

This two-block manual set is **not an exhaustive perfect-identity gold standard**.
It cannot honestly certify the other 44 pairs. To bound their possible cost
benefit without inventing proof, a separate counterfactual supplies the same
subject solely to inspect subsequent unchanged H guards. It is never mixed with
AUTO/MANUAL output or persisted as a descriptor. That stronger counterfactual
still enables zero pairs, establishing a zero packing-savings ceiling under the
present H rules. This is not a claim of automatically implementable identity.

## 18–19. H pairs and broader peer opportunities

| H's 46 unknown-identity pairs | AUTO | MANUAL |
| --- | ---: | ---: |
| SAME_RESOLVED_RESOURCE | 0 | 2 |
| DIFFERENT_RESOLVED_RESOURCE | 0 | 0 |
| PARTIAL / AMBIGUOUS / STALE_DESCRIPTOR | 0 | 0 |
| UNRESOLVED | 46 | 44 |
| Newly eligible after ALL H rules | 0 | 0 |

Same-subject counterfactual later refusals: **26 typed_attributes, 12
typed_container, 8 qualification**. All 46 remain ineligible. Before those
additional guards, 46 edges alone could close at most 46 of the 1,592-candidate
gap (2.89%); after the guards the actual ceiling is zero.

The other **3,173 adjacent pairs** were also inventoried without changing their
first failure: **2,841 atomic_kind; 321 parent; 11 section**. Conditional identity
diagnostics, assuming those prerequisites independently satisfied: AUTO all
3,173 unresolved; MANUAL 2 same-resource, 4 partial, 3,167 unresolved. Those two
same-resource cases remain blocked by existing structural rules. This is not
permission to merge typed units, span parents or erase section boundaries.

## 20. Cost and heading comparison

| Representation | Candidates | Tokens | New peer packing groups | Heading metadata-only | Resolved / unresolved candidates |
| --- | ---: | ---: | ---: | ---: | --- |
| Legacy | 1,092 | 212,061 | Not measured | Not applicable | Not evaluated |
| v1 | 3,242 | 278,491 | Not an H packing policy | 0 | 0 / 3,242 |
| H v2 | 3,232 | 278,234 | 0 | 10 | 0 / 3,232 |
| I simulation | 3,230 | 278,177 | 0 | 12 | 0 / 3,230 |
| J automatic | 3,230 | 278,177 | 0 | 12 | 0 / 3,230 |
| J manual GOLD experiment | 3,230 | 278,177 | 0 | 12 | 6 / 3,224 |
| Separate perfect-same-identity counterfactual ceiling, unchanged H guards | 3,230 | 278,177 | 0 | 12 | NOT evidence |

All I heading categories/decisions are preserved through the exact native-node
bijection: 742 heading candidates retained, 12 metadata-only proposals. Two
manual-context heading hypotheses are recorded only; no new classifier or
selector decision. Gap to historical review targets remains **1,592 candidates
and 2,498 tokens**. J saves **0 candidates / 0 tokens** beyond I. No vectors or
embedding costs were generated or measured.

## 21. Source-capture gaps and minimum future design

The saved Markdown retains hrefs and readable review signatures but not the
target HTML IDs, authoritative link-owner DOM windows, structured item identity
or complete root resource inventories needed here. Some headings/groups also
absorb unrelated following content. The snapshot cannot distinguish whether a
missing field was never captured or discarded during earlier extraction; this
report does not claim a historical acquisition component was proven at fault.

Minimum next design: immutable source-hash/version/crawl-bound anchor registry
(exact canonical base + fragment + target source location), and source-native
resource-block identity with DOM/item start/end and link ownership. Root scope
also needs one explicit primary resource assertion and a complete inventory
that distinguishes competing groups from navigation. A small approved metadata
capture can be preferable to retaining unrestricted HTML; any future capture
must exclude credentials. Define validation/authorization independently.

Do not recrawl as part of J. Design the enrichment and cost/representation choice
first: even perfect identities do not bypass H's atomic/attribute/qualification
rules, so enrichment alone will not meet the current count target.

## 22. Generalization

Synthetic hotel property/room/package, software plan, course/module, legal
section and generic resource cases pass through the same exact URL/pin/boundary
model. Resource keys are opaque. No product-name, domain, heading-similarity or
business ontology branch exists. Existing PDF/DOCX/Docling code is unchanged.

## 23. Evidence/mapping preservation

Each AUTO and MANUAL simulation verifies **18,111 translated logical mappings +
26 heading witnesses = 18,137 original mappings**. Source-interval coverage is
equal; **0 evidence bytes dropped**. Frozen I's 894,386 mapped node-evidence bytes
are unchanged through the exact source-map bijection. v1/H/I outputs and 684
preservation hashes remain unchanged. J results cannot publish an H selection.

Ignored detailed artifact: `.codex_structural_4_1j/study_final.json` (23,134,352
bytes), SHA-256 `5a2afa9644759b7905baa72f96ea3b96d44acc31f38a22677b331a02c7f261f2`.
It includes per-source inventory/descriptors, source pins, every pair outcome,
translations, cost totals and unapplied heading hypotheses.

## 24–25. Validation

- Focused J: **108/108 PASS** (72 frozen contract cases plus 36 packing/safety checks).
- Existing structural A–I: **892/892 PASS**, 133.638 seconds.
- Full canonical backend: **3,083/3,083 PASS**, 409.097 seconds
  (unchanged 2,975-test baseline + 108 J tests), exit 0.
- AST: 5 changed Python files PASS; 4 new-module imports PASS.
- Secret-shaped-material scan: PASS; no environment/corpus secrets copied.
- `git diff --check`: PASS; only normal existing Windows EOL notices.
- Preservation: **684/684 PASS**, including the original 300 artifacts.
- Evaluation and validation ran with external socket/connect/DNS denied. Local
  socketpair is allowed solely for event-loop internals. The canonical runner's
  existing HTTP/provider/configured-DB isolation remains in place; isolated
  in-memory test fixtures are not an application or persistent database.

Commands used the existing backend virtual environment with `-B` and the same
external-network-denial wrapper: focused unittest module
`test_structural_resource_descriptors`; all nine A–I structural unittest modules;
`scripts/test_scoped_rag_regressions.py`; and
`scripts/evaluate_structural_resource_descriptors.py`. Expected Redis DNS-denied
warnings in isolated canonical tests did not prevent a complete PASS; no live
Redis remediation or other service action was performed. The source-native
edge-multiset regression initially caught an evaluator comparison defect (edge
order legitimately changes with identity hashes); J's evaluator was corrected
before final validation, with no alteration to the frozen GOLD expectations.

No application DB, disposable PostgreSQL, live customer request, provider/model,
embedding, customer-site lookup, recrawl, catalog mutation, activation,
deployment or push. The only commit was the authorized I checkpoint; no J commit.

## 26–28. Limitations, next prerequisite and final decision

This is a provider-neutral offline proof study, not an automatic general DOM
extractor, security authority, runtime catalog, retrieval implementation or new
selector. Explicit frozen assertions require trustworthy review/source capture;
a self-declared DTO is not independent proof that arbitrary text has one subject.
Anchor support is deliberately limited to exact saved declarations; other
future capture types are not silently accepted. Manual coverage is two blocks,
not full-corpus human ground truth. No retrieval recall or live answer quality
was tested or claimed. No new heading decisions were adopted.

Exact next prerequisite: a **reviewed source-capture enrichment design** capable
of preserving immutable resource ownership boundaries and verified fragment
targets, together with an explicit decision about representation cost under the
unchanged typed-unit safety policy. Neither enrichment nor a future selector
revision is implemented here.

**C — PHASE 4.1J — COMPLETE — SAVED SOURCE DOES NOT CONTAIN ENOUGH IDENTITY /
BOUNDARY EVIDENCE — SOURCE-CAPTURE ENRICHMENT DESIGN REQUIRED.**
