# Phase 4.1G — activation/canary and structural cost design

2026-09-16 · Design and offline analysis only · **NO-GO FOR ACTIVATION IMPLEMENTATION**

No activation, embeddings, database access, migrations, provider calls, crawling,
retrieval changes or deployment occurred. Nothing was pushed. Proposed fields,
states, limits and transactions below are **not implemented or configured**.

## 1. Phase 4.1F checkpoint and scope

Checkpoint: `627be0338fc3f471833f75cf985c1b36e60ada28` —
`Phase 4.1F: integrate structural shadow ingestion`.
Parent E: `b388b7f8fb142d67991c4e19b4b8c288bd3cefbb`.

Audited and committed exactly the twelve F files in its report. No unexpected
files, staging payloads/models, secrets, environment/config changes, activation,
structural embedding hooks, resource projection or serving-cache changes.
Frozen hashes passed (30 structural GOLD, seven Docling artifacts, two E files);
migration head remains `20260916_01`; `git diff --check` passed. Working tree was
clean immediately after the local F commit. Accepted F baseline: 2,700 tests;
PostgreSQL 32 main and 16 closure checks, previously completed with cleanup.
No database test was rerun for this design task.

G adds only this design, the OSS ledger addendum, an offline analysis script and
its offline tests. G remains uncommitted. Runtime F and frozen `structure-chunk-v1`
are unchanged. No production or customer database was read.

## 2. OSS study and local publication findings

See the [pinned source/license ledger](PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md#phase-41g--active-index-hierarchy-and-packing-source-study-2026-09-16).
Actual source, not only documentation, was inspected for all five required projects.

- RAGFlow separates non-searchable parent content and searchable chunks; insertion
  records permit cancellation cleanup. Its external-store compensation is not our
  atomic publication mechanism.
- Onyx separates future/present/past indexes and checks required work before a
  non-instant swap. Retention refuses active/referenced indexes. We reject its
  instant incomplete switch and any adoption of enterprise ACL assumptions.
- LlamaIndex and Haystack preserve hierarchy separately from leaf selection. Neither
  hierarchy builder means every parent must get an embedding. No auto-merging retrieval.
- Docling merges peers under common headings and a token ceiling, then contextualizes
  content. Our semantic/ownership boundaries must be stricter than heading equality.

Current repository constraints found by source inspection:

| Existing code | Provides | Does NOT yet provide |
|---|---|---|
| `structural_repository.activate_revision` | Scoped document lock/CAS; validated/current source; supersedes previous structural revision | Chunk/vector/profile/quality readiness, current website pointer check, cache/catalog publication, legacy rollback |
| `knowledge_scope.ready_chunks` | Organization, bot, document/chunk READY, crawl/version/profile scope | Selected representation predicate; a second READY set would currently be eligible |
| `rag_planning.prepare_query` | Corpus hash of document ID/version/time/content hash/crawl | Explicit representation generation or structural policy identity |
| `ResourceCatalogProjector.project` | Bounded 256-doc projection, bot lock, same caller transaction, trigger-owned catalog revision | Structural edges as authorization or an atomic serving-manifest switch |
| Legacy ingestion | Stage first; quota check before source/job promotion; old chunks become stale | Retained, explicitly identified rollback representation independent of later ingestion/cleanup |

**Do not call the structural activation helper alone or mark candidate chunks
READY under current selectors.** Both would lack required end-to-end safeguards.

## 3. Frozen v1 cost findings

| Representation | Chunks/specs | Tokens | Chunk ratio vs legacy | Token ratio vs legacy |
|---|---:|---:|---:|---:|
| Historical legacy | 1,092 | 212,061 | 1 | 1 |
| Frozen v1 | 3,242 | 278,491 | 2.968864468864469 | 1.3132589207822278 |
| Conditional selection simulation | 2,636 | 263,830 | 2.413919413919414 | 1.244123153243642 |

v1 exceeds count target **1,638** by 1,604 and token target **275,679** by 2,812.
Both historical review flags remain set, regardless of a hypothetical successor.
Simulation meets the token target but misses count by **998**. No embedding API
token bill or production latency is inferred from the local cl100k measurement.

## 4. Composition, inflation and evidence provenance

| Kind | v1 specs | <50 tokens |
|---|---:|---:|
| Prose | 1,525 | 358 |
| Heading | 754 | 645 |
| Commercial / price_block | 405 | 229 |
| List | 259 | 160 |
| Directions | 105 | 57 |
| Review | 86 | 0 |
| FAQ | 78 | 3 |
| Timeline stage | 30 | 0 |

23 documents; 13,213 nodes; 6,700 edges. v1 has 78,928 prefix tokens, 6,095 inherited
mapping occurrences and 5,195 repeated occurrences of exact inherited node slices.
Prefix token totals are not all removable duplication: subject/qualifier/header
context is often required independently in each retrieved leaf.

Inflation is partly independent short units plus repeated context. It is not proof
that 2,150 additional specs are unnecessary. v1 already packs compatible neighboring
prose inside `units()`; the remaining adjacency count overstates available savings.

No saved full v1 batches existed: F retained summaries/hashes. The helper rebuilt
the frozen deterministic path from the same local saved source **offline**, then
matched all 23 graph and serialization hashes to F's saved metrics before analysis.
No source acquisition, ingestion job or persistence occurred. Local output:
`.codex_structural_4_1g/packing_final.json` (ignored, counts/hashes/group ordinals).
Snapshot SHA-256: `4dc2bd9835b4e4e9a799a679dd08f9a36fc38cd419cab37be36d1abc71fcc662`.

## 5. Tiny-unit analysis

1,452 tiny specs: 1,449 have one primary parent, one has two and two have three.
Heading-path depths: 158 at depth 0, 680 at 1, 567 at 2, 36 at 3, 11 at 4.
All 1,452 lack a proven explicit subject relationship and have manual-review quality.
991 hit relationship/typed-attribute/qualification barriers; 461 do not, but that
does not establish identity compatibility. Role combinations: 1,185 UNKNOWN-only,
23 title, 241 commercial+UNKNOWN, three FAQ combinations.

Do not merge based on shortness, shared page, absent roles, or equal heading text.
Lists, FAQ pairs, reviews, timeline stages and different commercial roles remain
atomic boundaries even when tiny. The conditional heading selection reduces tiny
embedded candidates to 880, without changing any source graph or original spec.

## 6. Heading-only analysis and decision

754 standalone headings: 753 have non-heading descendants and complete exact-slice
coverage in inherited non-heading content; one has neither. There are 125 duplicate
heading-text occurrences within documents, which are **not** deduplication identity.
253 headings have an independent-answerability witness (number, question or assertion
word); this is an overlapping heuristic flag, not a semantic truth label. Zero match
the narrow generic navigation-title vocabulary; that does not prove no furniture.

Simulation moves **606** headings to metadata-only selection only when all their
mapped source bytes survive in retained non-heading specs, a descendant references
that heading, and no protected semantic role/typed attribute occurs. It retains
148 standalone specs: the orphan plus headings that fail those conservative checks.
Graph nodes, original v1 specs, lineage and mappings remain intact.

Proposed v2: independently embed orphan or independently answerable headings unless
their full content and necessary qualification are present in an appropriate evidence
leaf and retrieval tests prove discoverability is preserved. A duplicate contextual
heading can be unembedded but must remain addressable through graph/mappings.
Simulation proves byte coverage, **not** answer recall; the 606 decision is conditional
on v2 qualification/heading-only query tests and can be reduced if those tests fail.
No blanket deletion of headings or navigation-like titles is approved.

## 7. UNKNOWN-role analysis

3,188 specs touch UNKNOWN nodes: 1,525 ordinary-prose candidates, 1,663 typed units
or headings containing UNKNOWN annotations. Four are small link-dense navigation
candidates. 87 distinct UNKNOWN-prose text hashes repeat across documents, in 401
occurrences. Repetition can represent useful shipping/policy evidence; it is not
enough to label marketing boilerplate or discard anything.

Future quality study must label source-backed samples as useful prose, navigation,
layout furniture, recurring marketing, mixed or unresolved; evaluate false-positive
evidence removal separately from coverage. Preserve source offsets and graph roles;
require explicit, versioned review before a classifier changes embedding selection.
Current evidence does not support a reliable count of true useless furniture or
marketing boilerplate. UNKNOWN is never a discard rule.

## 8. Commercial-unit analysis

405 specs correspond to 405 distinct source bundles, not multipart splits of the
same bundle. They contain 516 monetary annotations; 52 specs contain multiple
amounts. All 516 typed monetary roles are UNKNOWN. `source_block_complete` is
unknown on all 405—not a measured finding of incompleteness. No same-primary-block
duplicate spec was found. Separate label-only source paragraphs may still exist;
this analysis cannot safely assign them to amounts without source-backed boundaries.

Retain complete mapped commercial blocks as atomic evidence. Do not collapse price,
subscription, bundle, regular/offer, fee or per-unit roles. Existing multiple amounts
remain distinguishable by exact mapping, labels and conditions; absence of role
classification is not permission to compute a sale price. Future reviewed tests
must prove label association, price role and quantity/qualification preservation.
No Phase 3.7 monetary heuristics are changed or reintroduced.

## 9. Strict peer-packing eligibility

3,156 theoretical adjacent complete pairs fit a 650-token sum. Strict analysis
finds **0 eligible pairs**. Across all 3,219 adjacent pairs, first rejection is:
2,841 atomic kind, 321 parent mismatch, 11 section mismatch, 46 no explicit subject.
These first-failure categories are mutually exclusive; they are not every possible
reason each pair would fail.

Future eligible peers must be adjacent source siblings, same immutable source and
revision, same nonempty parent/section, same explicit subject/resource, compatible
roles and identical effective quality. Reject semantic edges across the proposed
boundary, links requiring different attribution, warnings/conditions, typed units,
multipart fragments, or budget overflow. Equal missing subject is not equal identity.
No parent-wide or document-wide inferred product scope may authorize packing.

The helper's generic compatibility function is tested with positive synthetic peers
and negative boundary cases. The actual corpus has no approved merge; therefore no
claim is made that theoretical pairs are removable or that grouping improved recall.

## 10. Proposed `structure-chunk-v2` (not implemented)

Separate immutable graph storage from embedding selection. Start with the smallest
candidate: conditional duplicate-heading selection plus lossless existing units.
Only then consider approved, explicitly attributed prose peers. Maintain 450 target,
250–650 ordinary range, 800 hard cap, 80 context and 60 overlap unless a separately
reviewed policy version changes them. A new policy/selector fingerprint must record
heading decision rules, peer compatibility, exact-byte context deduplication and
tokenizer recipe. v1 output and identifiers remain reproducible forever.

Proposed packing emits a group ledger of component spec IDs and offset translations,
never a summary. Deduplicate only repeated identical mapped prefix slices within a
group; never strip differing qualifiers or source identities. No cross-document,
cross-version or semantic-type packing. Unembedded parents/links retain graph identity.
If required context cannot fit, retain v1 partitioning or fail closed; no truncation.

## 11. Simulated impact and cost decision

Conditional selection saves 606 vectors/specs (18.692165330043184%) and 14,661 tokens
(5.264443016111831%). It keeps 148 standalone headings, 880 tiny specs and all other
kind counts. No actual peer grouping occurred; shared-prefix deduplication was not
simulated and has no claimed savings. Source-slice unions remain exactly equal,
with zero newly unaccounted bytes for all 23 documents.

| Count goal | Maximum specs | Additional reductions beyond 2,636 | Evidence/compromise |
|---|---:|---:|---|
| 25% reduction from v1 | 2,431 | 205 | Even deleting every remaining heading would be insufficient; requires non-heading packing/removal not justified today |
| 40% reduction | 1,945 | 691 | Requires many atomic/identity-uncertain units to combine or be omitted; no approved mapping |
| 50% reduction | 1,621 | 1,015 | Same unsupported boundary changes at greater scale |
| Review target | 1,638 | 998 | Cannot be reached by the proven conservative selection alone |

Dropping all 754 headings yields 2,488 specs (23.25724861196792% reduction), still
short of 25%, and would lose orphan/qualified evidence. That is a rejected bound,
not an alternative policy. Token targets for 25/40/50% reduction would be
208,868 / 167,094 / 139,245; none is demonstrated or required for correctness.

Decision: implement/validate an offline v2 candidate first, then explicitly accept
its measured cost or authorize further evidence-backed packing. Do not optimize
away relationships to meet 1,638. Current data cannot promise the count target.

## 12. Fidelity invariants and witnesses

Every emitted byte maps to the same owned source slice (apart from explicit
separators); preserve original node IDs and source versions. Exact membership and
offset translations survive grouping and omitted-vector selection. Account for all
evidence bytes including graph-only spans; preserve complete lists, table header/cell
relations, review attribution, FAQ pairs, separate timeline stages, monetary roles,
quantities, warnings, qualifications and validated links. No LLM rewriting.

Worst five by v1 spec count, from offline IDs only:

| Witness | Legacy chunks/tokens | v1 specs/tokens | Conditional specs/tokens |
|---|---:|---:|---:|
| 12 | 103 / 15,437 | 360 / 22,063 | 330 / 21,598 |
| 28 | 65 / 15,655 | 221 / 19,719 | 186 / 18,787 |
| 27 | 61 / 16,202 | 209 / 21,793 | 175 / 20,742 |
| 11 | 61 / 15,647 | 208 / 22,343 | 174 / 21,071 |
| 29 | 57 / 12,061 | 199 / 16,927 | 163 / 15,839 |

Document 12: 1,072 nodes, 511 edges, 98 headings, 227 tiny v1 specs, UNKNOWN/manual
review. Only 30 headings satisfy conditional selection. It stays a negative/mixed
quality witness, not an automatically approved canary. No runtime ID/domain branch.

## 13. Future embedding-selection policy

Embed answer-bearing leaves, complete ingredient/list units, table row groups with
headers, attributed reviews, FAQ pairs, independent timeline stages, commercial
blocks and directions. Embedding membership is explicit and versioned, not inferred
from having a node row. Keep empty containers, pure hierarchy parents and
metadata-only links without vectors; retain their graph relationships. Keep
heading-only evidence when no safe retained leaf carries it. UNKNOWN stays eligible
subject to quality approval, not automatically excluded.

Embedding profile stays **Gemini / gemini-embedding-001 / version 1 / 768 dimensions**.
Tokenizer estimates are admission estimates, not a change in embedding model.

## 14. Future staging lifecycle

Validated graph → approved versioned specs/selection manifest → reserve embedding
budget → bounded provider batches → owned staging vectors/chunks/mappings → verify
complete hashes/counts/profile → READY **candidate manifest** → optional publication.

Current message-quota reservations are not an embedding-token reservation system;
embedding usage recording alone is insufficient. A future narrow, idempotent
reservation keyed by build/profile must track requested, reserved, consumed and
released capacity. Retain charges for actual completed provider work; release only
unused reservation after cancellation/failure. No refund fiction for spent tokens.

One durable build ID and batch keys; retry only failed/unacknowledged batches within
existing provider retry bounds and a proposed maximum three build attempts. Persist
successful vectors once. Partial failure/cancellation/profile mismatch leaves the
whole candidate non-serving. Revalidate source hash/version/crawl after network work.
Source change invalidates the build; never attach old vectors to new evidence.
Do all provider work outside publication/tenant locks. No mixed profile publication.

## 15. Representation identity and strategy

Propose an immutable manifest binding org, bot, document, source version/hash,
document-version ID, crawl ID, structural revision, parser recipe, chunk/selection
policy, tokenizer/serializer hash, profile tuple, schema version, expected chunk IDs,
content/mapping/vector digests and quality approval. Legacy gets a retained manifest
too; NULL structural identity is not enough to distinguish multiple legacy versions.
This requires future schema/repository work; existing sidecar tables alone do not
provide a complete serving/rollback manifest.

| Strategy | Decision |
|---|---|
| Per-document activation | Small atomic unit; choose after canary, always one representation per document |
| Per-bot canary manifest | Recommended first read isolation; explicit map for all compared documents, same query stack |
| Entire-bot atomic switch | Avoid for first rollout: larger locks/failure scope; a future generation manifest can bound pointer publication |
| Dual legacy+structural retrieval | Reject: duplicates, unequal ranking pools and mixed evidence undermine evaluation |

Canary compares identical document scopes in separate requests. Never silently fall
back to legacy within one selected structural document. Missing candidate means
canary refusal, not partial catalog absence. Per-document staged rollout may select
different representations across documents only through an explicit audited map;
each document's candidate pool remains representation-pure.

## 16. Cache and reader generation

Shadow rows remain invisible to cache/corpus/catalog identity. For active/canary
reads, derive keys from a DB-owned monotonic bot serving generation plus selected
manifest identities, query contract, hard scope, profile and existing config/history
identity. Include canary lane and manifest hash; never share entries between lanes.
Old cache keys must not be reached after publication even if Redis invalidation fails.

Publish DB generation in the same transaction as pointers/statuses; enqueue a bounded
post-commit invalidation event or best-effort purge. Redis and PostgreSQL are not an
atomic transaction: generation-key separation is the correctness mechanism.
Use one consistent read snapshot across candidate/evidence queries, pin its manifest,
then recheck generation and hard scope before response delivery. On change, bounded
retry once or explicit transient refusal; no stale authorization/evidence return.

Future work must audit every retrieval path (dense, FTS, fallback, field retrieval,
context expansion, resource document eligibility and cache hydration) for the same
selected-manifest predicate. No broadening beyond existing hard scope/profile/crawl.

## 17. Resource catalog consistency

Source descriptors remain document metadata: canonical identity, title, owned source
version and safe canonical URL. Structural CONTAINS/QA/HEADING/DESCRIBES relations
are evidence relations, never permissions. A safe link is not authorization to its
target. Later explicit canonical-link projection must independently resolve within
authorized READY resources and refuse ambiguity; no automatic graph-to-catalog pass.

Unchanged source identity normally needs no new catalog descriptor on representation
switch. Nevertheless candidate/source/catalog fingerprints must agree. If projection
must change, validate and commit it in the publication transaction using existing
bot-scoped projector and revision triggers. Pin catalog revision with the serving
manifest; invalidate catalog-dependent cache keys by generation, not mutable aliases.

## 18. Atomic activation transaction (future only)

Precompute full immutable candidate evidence and bounded projection outside locks.
Use the existing lock direction: tenant quota owner before promotion; source before
job/revision. Proposed total order for the new bounded publisher: organization →
bot/catalog owner → website → crawl → document IDs ascending → job → revision.
Uploads omit website/crawl. Current website promotion locks job before updating page
documents; therefore canary must initially require idle ingestion, and a concurrent
rollout must first align/conflict-test this ordering—do not claim existing code has
one global lock order. `_lock_quota_owner` calls rollback, so it must not be invoked
after assembling a publication transaction; reservation is already finalized or
quota locks are taken first with an explicit transaction-aware path.

Within one caller-owned transaction, with a proposed 5-second lock timeout and
bounded one-document first release:

1. Reauthorize tenant/bot/source; CAS expected serving generation and prior manifest.
2. Confirm document READY/completed, current source hash/version, website/crawl READY
   and active pointer/version; no delete/disable/cancellation.
3. Confirm structural revision validated; quality approved for exact immutable source.
4. Verify complete embedding-ready candidate manifest, profile/dimension/finite
   vectors, expected IDs/counts/hashes, and 100% valid mappings.
5. Confirm source/catalog identity; apply any necessary bounded projection.
6. Move selected staging chunks to READY; old selected set to retained/non-serving
   state; switch representation and structural pointer together. Retained means not
   available to ordinary queries, not deletion.
7. Publish bot/corpus generation, catalog revision linkage and audit/CAS receipt.
8. Commit once; purge old cache entries after commit. Any check failure rolls back all.

Candidate-manifest readiness is distinct from `Chunk.status=ready`. Keep inactive
candidate rows staging under current selectors; future canary reads may access them
only via an authenticated server-owned candidate manifest and the same hard-scope
checks. Never enable global staging reads or change existing customer READY rules.
Disallow activation while readers lack representation selection. Publication tests
must race cancellation, replacement, crawl promotion, delete, rollback and two admins.

## 19. Canary modes and flags

Future states: OFF → SHADOW → OFFLINE_EVAL → EMBEDDING_STAGING → CANARY_READ →
COMPARATIVE_EVAL → OPTIONAL_ACTIVE. These are proposed orchestration states, not
new accepted values for the current flag. Today `active` still fails configuration.

Use separate server-owned, default-empty exact org:bot:manifest allowlists, expiring
run IDs, operator authorization and an environment assertion that rejects production
for initial canary. No request payload, bot prompt, customer control or uploaded text
may choose a manifest/mode. Fail closed if scope/profile/version/generation differs.
Turning off canary blocks that lane immediately; it does not implicitly mutate data.

## 20. Canary population (future development clone only)

Use REAL_CORPUS_V1 development clone, never production first. Freeze a local canary
manifest from saved-corpus identities/hashes: one simple product, one complete
ingredient-list case, collection page, review attribution, timeline and price case;
include document 12 as quality-refusal/mixed-content witness. The top-count witnesses
above exercise capacity. Select by existing annotated evaluation evidence, not only
convenient size or heuristic roles. IDs/hashes belong in test configuration only.
Require human approval of selected source quality before embedding/read admission.

Concrete initial evaluation candidates from the saved snapshot: document 3 for a
single product, ingredient-list and timeline checks (18 list units, three timeline
stages); 31 for a second product/price comparison (27 commercial units); 25 for powder
directions and distinct timeline stages; 30 for collection navigation and nine review
units; 19 for denser attribution (18 reviews); 12 for refusal/manual-review. These
are test-selection witnesses, not runtime rules or automatically approved resources.
Human annotation must verify the specific list is complete and each review is correctly
attributed before declaring those acceptance categories passed.

## 21. Comparative evaluation

Same authorized documents, query understanding, embedding profile, hybrid weights,
reviewer, context budget and generator/model; only representation changes. Separate
lane caches, fixed inputs/seeds where supported, interleave timing runs and record
provider variability. First evaluate unit-level identity/mapping/field recall without
generation. After mechanics are safe, rerun frozen REAL_CORPUS_V1_EVAL_V1 unchanged.

Record candidate recall@10/@48, resource/source identity, required fields per entity,
rank inputs, complete evidence sets, source noise, supported answer/citation accuracy,
qualifications, latency p50/p95, vector count/storage, sidecar bytes and token cost.
Report per-case failures, not only averages. No new generator/model to explain a win.
Require zero critical correctness regression and no lost mandatory evidence cases;
rank/latency trade-offs need explicit acceptance, not assumed improvement.

## 22. Gates before any active canary

- Zero cross-tenant/bot leaks, unauthorized graph expansion or stale/deleted-source publication.
- Structural GOLD and versioned v2 tests pass; exact mappings 100% valid; zero
  unaccounted evidence bytes and no lost warning/list/price/timeline relations.
- Every selected vector has the unchanged profile and 768 finite dimensions; no
  partial candidate, mixed profile or mixed document representation.
- Actual PostgreSQL publication/reader races, crash recovery and rollback pass;
  new migrations approved separately and validated on disposable infrastructure.
- Cache lane/generation and resource projection consistency proven under failure.
- Quality approvals and immutable source identities valid; canary-only flags proven.
- Measured cost/storage/worker budgets explicitly accepted, including count exception
  if targets remain exceeded. No silent review-flag reset.
- Frozen final-answer regression passes before optional active customer rollout.

## 23. Rollback

Retain old legacy text/vector set and its immutable manifest for at least seven days
after a canary/activation and until explicit evaluation acceptance. Rollback checks
current authorization, source version/hash/crawl and expected active manifest under
the same lock order. Switch selected set/pointers, generation, catalog linkage and
audit atomically; invalidate by generation. No recrawl or old-vector regeneration.

Existing `activate_revision` only accepts validated structural revisions; it is not
a rollback API. Design a separate scoped CAS rollback operation, never silently
change superseded revisions back to validated or fake the source version.
If source changed, was disabled/deleted or prior manifest no longer matches, refuse
old-source rollback. Safe alternative: serve an already validated current-source
legacy representation, or make the affected source temporarily unavailable while
an authorized current-source rebuild occurs. Never resurrect old corpus data.

## 24. Bounded retention (proposal; no deletion performed)

Failed/cancelled incomplete candidates: keep audit seven days, reclaim owned partial
rows after 24 hours only if no active job/lease/reference. Validated shadow revisions:
retain latest two recipes per current source for 30 days, with aggregate storage cap
and explicit archival exception. Superseded active/legacy rollback manifests: minimum
seven days **and** through evaluation sign-off; referenced/in-flight generations pin
them longer. Security deletion/tombstone forbids access immediately and takes priority
over serving rollback. Artifact retention follows deletion/privacy policy, not an
unconditional seven-day right to keep customer data.

Cleanup rechecks tenant/bot/source ownership and all active/canary/job/mapping/read
lease references, uses 100 revisions/1,000 subordinate rows per transaction, limits
one worker per bot and emits dry-run/audit counts. Use explicit IDs, FK RESTRICT and
bounded passes; never broad recursive deletion. Source artifacts can be reclaimed
only when no retained source version/build/rollback manifest references them. Keep
an audit tombstone after payload deletion. No DROP DATABASE or schema-wide cleanup.

## 25. Source-quality approval

Usable+accept may proceed after matching-source checks. Mixed requires reviewed
boundaries with complete evidence accounting. Blocked/interstitial is denied.
Unknown/manual_review remains non-active until an explicit versioned policy or
authorized reviewer approves the exact source/revision; validation of graph integrity
does not imply trustworthy page quality. Approval records policy, actor, timestamp,
source hash and reasons; source change invalidates approval. Document 12 follows the
same rules. Do not replace the existing legacy page-quality checks.

## 26. Operational and cost limits

Measured maxima: 1,072 nodes, 609 edges, 360 specs, 22,343 tokens/document;
2,825,858 graph JSON bytes and 6,997,121 batch JSON bytes/document. Totals:
35,184,725 graph bytes and 78,368,315 batch bytes. JSON sizes are not PostgreSQL
on-disk/index sizes. F binary samples used 33 nodes/11 specs/88 tokens (PDF) and
42/12/186 (DOCX); not throughput evidence.

| Guard | Existing ceiling | Proposed initial development canary bound |
|---|---|---|
| Shadow documents/job | 1,000 | 23 authorized docs, sequential; one publication transaction/document |
| Nodes/edges per doc | 10,000 / 20,000 | 2,000 / 4,000; explicit review to exceed |
| Prospective specs/doc | 10,000 default serializer | 500; no truncation on overflow |
| Serialized tokens | Derived from spec bounds | 30,000/doc; 300,000 total candidate job |
| Embedding work | Existing cancellable batches | <=32 specs and <=16,000 estimated tokens/batch; one in flight; explicit token reservation |
| Serialized sidecar | 64 MiB batch cap | 8 MiB/doc, 100 MiB/job, one materialized batch at a time |
| Source artifact | 20 MiB parser admission | Preserve existing limit and ownership/hash checks |
| PDF conversion | 50 pages, 120 seconds | Same ceilings; one Docling child per canary worker/bot, one canary worker initially |
| Publication | Existing scoped locks | One doc, <=500 chunk candidates, 5-second lock acquisition timeout; no network inside |

All proposed limits are fail-closed development admission limits, not measured
production SLOs. Exceeding them leaves legacy active and produces an explicit review
result; it does not delete evidence or silently fall back mid-document. Vector-only
float32 payload lower bounds: legacy 3,354,624 bytes, v1 9,959,424, simulated 8,097,792
(count × 768 × 4); actual pgvector tuples/indexes/WAL and dual-retention storage add
overhead and must be measured before rollout.

## 27. Unresolved risks and limitations

The count target is unmet; explicit subject attribution is absent for merge candidates.
Byte coverage does not prove heading-only retrieval recall. Commercial roles remain
UNKNOWN, so price-label packing is not justified. All tiny units retain manual-review
quality. The helper's navigation/answerability/repetition flags are diagnostic, not
classifiers. No canary retrieval, answer benchmark, embedding, database publication,
rollback or production-capacity behavior was measured in G. The existing 3,156 count
is not a grouping plan. Shared prefix removal may harm qualifications/recall.

Current selectors/cache keys, retention identity, embedding reservations and lock
ordering need separately authorized implementation before activation. Future source
replacement/cleanup paths must respect retained manifests, not only the new publisher.
No design document can substitute for these future integration/race tests.

## 28. Validation and implementation sequence

G analysis tests: **36/36 PASS** (0.198 seconds). Offline full suite:
**2,700/2,700 PASS** (355.691 seconds), under external-network/configured-DB guards.
The full suite includes all existing structural A/B/C/D/E/F tests. Saved-source
baseline and all 23 graph/batch hashes matched; conditional mapping coverage passed
23/23. AST/import, frozen hashes, secret scan and whitespace checks passed.

Next authorized slice should be **offline structure-chunk-v2 selection/packing
implementation and validation**, not activation: preserve v1, implement mapping
ledgers and conservative heading selection, test discoverability/qualifications,
resolve or retain explicit subject uncertainty, rerun frozen structural evidence and
report cost. Request acceptance of the remaining count increase or a separate,
source-backed packing study. Do not promise 1,638.

Only afterward: approve manifest/reservation/retention schema → implement scoped
staging and representation selectors (default disabled) → disposable PostgreSQL
race/rollback/cache tests → development embedding canary → comparative unit metrics
→ frozen answer evaluation → separately authorized active rollout. No later slice
has been started here. This design is uncommitted for review.

## 29. Final recommendation

**PHASE 4.1G DESIGN — COMPLETE**

**NO-GO FOR ACTIVATION IMPLEMENTATION**

Prerequisite: implement and validate an explicitly versioned offline v2 candidate,
prove evidence/heading discoverability, and obtain an explicit cost decision for
the measured count gap. Then validate representation isolation, atomic publication,
quality approval, cache/catalog generation and rollback on disposable PostgreSQL
before authorizing an active canary. Legacy and shadow continue unchanged meanwhile.
