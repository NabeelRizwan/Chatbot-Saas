# Phase 4.1N — development embedding + hybrid retrieval canary design

2026-09-17 · **DESIGN ONLY — no canary implemented or enabled**

**Decision A: bounded and implementable; ready for separately authorized Phase
4.1O implementation.** This is not embedding authorization, retrieval acceptance,
Phase 4 completion, or permission to activate production. All proposed tables,
states, budgets, SQL and algorithms below are future work, not current behavior.

## 1. Phase M checkpoint SHA

Local checkpoint: **`7dc87fccbb16cb8e33f85cf28f5e2dba8076cc25`** —
`Phase 4.1M: close general retrieval heading allocation`.
Parent L: `693c5148717561fabe4ecf9322b8f99ddc4393de`. Branch: `main`.

Audited all ten M files against the M report before staging. The two tracked
changes were one test-runner registration and the M OSS-ledger addendum; the
eight new files were the v2 module, two offline scripts, focused tests, three
GOLD files and M report. No unexpected files or staged changes existed.

- **740/740 protected raw-file hashes PASS**, including saved corpus, prior
  fixtures/reports and frozen L implementation. L source SHA-256 remains
  `0b32a7b29e930e72923ad43b7fbae167390a164d96e4b80a9f27fd1fe28aeaa8`.
- Secret-pattern scan: all ten files PASS; unstaged/staged `git diff --check`
  PASS. No credentials, vectors or ignored measurement payloads staged.
- Fresh network-denied focused recheck: **323/323 PASS, 74.345 seconds**, exit 0
  (174 M + 149 L). Accepted canonical result remains **3,406/3,406 PASS** from
  M; the complete suite and long scale studies were not needlessly repeated.
- Read the actual final 1x/10x/100x/document-scale artifacts: all carry current
  v2 implementation hash
  `197ea1bb19ecec482352fde40c8b37300d5a85b82065030653b622c0b03a8243`.
- M source imports and evaluator boundaries remain offline. Current source
  audit, preservation hashes and network-denied tests support no serving,
  DB, provider, embedding or corpus mutation by the checkpoint. This does not
  claim independent inspection of remote infrastructure; none was accessed.

Committed only those ten M files. Working tree was clean immediately after
checkpoint. Nothing pushed. N changes only this document and the OSS ledger;
both remain uncommitted. The M report is retained as its historical record.

## 2. OSS hybrid/hierarchical study and current implementation audit

Actual official source and licenses were read at freshly resolved pins. See
the [N implementation ledger](PHASE_4_1B_OSS_IMPLEMENTATION_LEDGER.md#phase-41n--hybrid-retrieval--hierarchy--isolated-index-study-2026-09-17)
for immutable links, functions/lines, license and keep/reject decisions.

| Project | Inspected pin | Design relevance |
| --- | --- | --- |
| RAGFlow | `1ff3d961119e52effa7b60916584af02785a8a6f` | Filtered parallel search units and later parent materialization; do not adopt raw-score blending or scope-relaxing fallback. |
| LlamaIndex | `fd4a517ad6490f0c8464a13fdf133760b696434a` | Fusion and parent replacement are distinct; do not adopt content-hash authority, zero-based fusion or generated queries. |
| Haystack | `286bf8b4083d5835fd59128d2379cfb5aa5a5ed1` | Explicit rank join and hierarchical lookup; do not sum repeated children into unlimited parent support or adopt score renormalization. |
| Onyx | `5fe6573c3c155e1a75b51de32d4988ee6c82164e` | Filters enter the search expression; current/future index identities are explicit. No index swap, dual-write or Vespa scoring adoption. |
| Docling Core | `cc39622c6a4bb2643a8631edd996d8874a8e6a47` | Contextual serialization retains source items separately; this is not hybrid search. |
| Docling | `629440ee795fda854a9f9667ca8c54b0013a5ad6` | Its chunking facade delegates to Core; it does not supply retrieval/canary authorization. |

Patterns adapted at design level only; **no copied code, framework replacement,
dependency installation or upstream code execution**. References do not prove
this application's tenant/version safety.

### Actual local hybrid path — unchanged

| Code/function inspected | Current behavior | Implication for canary |
| --- | --- | --- |
| `backend/services/rag_planning.py:prepare_query`, `resolve_plan`; `retrieval_contracts.py:HardKnowledgeScope`, `choose_scope_strategy` | Deterministic contract + optional AI plan; scope/profile comes from DB-owned identity. Corpus fingerprint includes document ID/version/time/content hash/crawl. Incomplete comparison can remain broad authorized discovery. | Produce one trusted execution snapshot for a paired query; do not independently ask a different planner in each lane. No Phase 5 fix. |
| `backend/services/knowledge_scope.py:ready_chunks`, `ready_documents`, `discover_documents` | Both org/bot owners, READY chunks/documents, completed processing, correct active website/crawl/version, permitted documents and optional hard-scope/profile. Discovery may use scoped body ILIKE. | Keep discovery/query understanding common and freeze its resulting scope. Current READY predicate has **no representation generation/lane filter**. |
| `backend/services/rag_service.py:retrieve_relevant_chunks`, `_adaptive_recall_budget` | Scope is resolved before recall; current mode-specific budgets are 25–50 initially, with bounded small-scope adaptive widening. Selection/reviewer budgets are distinct from final context. | Freeze actual per-query limits from the legacy control, not from the new entry count. Record discovery failures before retrieval. |
| `rag_service.py:_vector_candidate_ids` | Scoped/profile-filtered `Chunk.embedding.cosine_distance`, ordered before LIMIT; own closed session. FTS mode adds deterministic document/chunk tie-breaks. | Same cosine operator/profile. No global top-k then tenant filtering. |
| `backend/services/postgres_fts.py:fts_statement`, `fts_candidates` | Materialized `websearch_to_tsquery('english', bound_text)`; `ts_rank_cd`; scope/profile and `@@` before LIMIT; stable ties; empty/non-indexable sentinel. No ILIKE fallback. | Keep this lexical stack/query text. Implement a separate future atom relation, not change this service in N. |
| `backend/services/hybrid_retrieval.py:hybrid_config`, `weighted_rrf`, `recall_parallel` | Code defaults: lexical `legacy`, weights 1/1, k=60, ceiling 500 (validated maximum 2,000). PostgreSQL FTS is an explicit backend option. RRF fuses **integer chunk IDs**, one-based ranks, first duplicate per channel, deterministic ties. Independent channel failures are traced; both fail raises technical error. | Explicitly select PostgreSQL FTS for both experimental lanes. Do not claim environment defaults are the currently deployed values. Typed entry/atom IDs cannot be passed to chunk-ID fusion as if interchangeable. |
| `hybrid_retrieval.py:weighted_rank_union` | General immutable-identity rank union already exists for resources; no raw-score comparison. Tie order differs from `weighted_rrf`. | Reuse its formula/pattern only after tests prove required one-based dedup/tie semantics; a wrapper must preserve the current chunk-fusion tie rule. |
| `rag_service.py` after fusion; `_select_complete_field_evidence`, `_structured_evidence_item` | Document-first selection, bounded field/sibling evidence and structured metadata can add candidates beyond initial RRF. | Measure raw recall separately. A later structural adapter must never silently issue legacy-chunk supplemental queries or import legacy evidence into its pool. |
| `backend/services/retrieval_selection.py:SelectionPolicy`; `rag_planning.py:review_evidence` | Required bundles/document fairness precede caps. Reviewer maximum 48, preview 18,000 chars/2,400 per item, expansion seed maximum 20. | Keep these policies fixed where evaluated; a route is not 32 free reviewer slots. |
| `backend/services/conversational_engine.py:compress_and_rerank_chunks` | Deterministic keyword/semantic signals, duplicate handling, field completeness and character-budget context building. No cross-encoder invocation in this function. | Do not add a new reranker to improve only one lane. Reviewer is a separate auxiliary-model step. |
| `rag_service.py:retrieve_relevant_chunks_cached`; `backend/services/tenant_cache_service.py:TenantSafeCache` | Retrieval cache includes contract, org/bot, knowledge version, selection version and hybrid settings; hits revalidate scope/profile. Answer-cache caller incorporates contract/config identity, but neither cache has an explicit canary manifest/generation. | Do not reuse either cache namespace for canary. Cold-cache comparison first. |
| `backend/services/embedding_service.py:GeminiEmbeddingProvider`, `generate_embeddings_batch` | Gemini call sets output dimensions; no explicit task type/title/normalization in this implementation. Batch cache key is text/provider/model; dev deterministic fallback exists. `validate_embedding` checks length, not all finite-value/identity properties. | Future canary wrapper needs exact-input/profile/config reuse, cardinality/finiteness/nonzero checks, real-provider attestation and fallback disabled. Do not change the model or reinterpret cached vectors. |
| `backend/database/structural_schema_v1.py`; `services/structural_repository.py` | Immutable source versions, scoped revisions/nodes/edges and mappings to **legacy Chunk IDs**. Activation updates structural pointer/state. No retrieval-entry/atom/vector/lane manifest tables. | Reuse source provenance, not activation. New canary relations are required. Do not overload `Chunk` or write the active pointer. |
| `backend/services/structural_shadow_config.py` | Existing off/shadow modes; active explicitly refused. | Leave unchanged. Proposed canary modes are a separate internal execution contract, not new values in this setting. |

The saved final baseline summary reports 84 full-hybrid requests and six
non-retrieval requests. It is historical evidence, not a live configuration
inspection. N does not read secrets, connect to production or assert deployed
settings. Existing ANN definition is IVFFlat cosine (`lists=100`); existing GIN
is `ix_chunks_content_fts_en_v1`, migration `20260910_01`. Neither is altered.

## 3. Current verified Phase 4 representation

Same frozen source, not a new crawl:

| Measure | Legacy saved control | L contextual v1 | M contextual v2 |
| --- | ---: | ---: | ---: |
| Documents | 23 | 23 | 23 |
| Source tokens, local tokenizer | 201,377 | 201,377 | 201,377 |
| Dense units/candidates | 1,092 historical chunks | 1,120 entries | 1,030 entries |
| Serialized input tokens, local | 212,061 | 220,749 | 217,263 |
| Heading-only entries | Not a comparable legacy measure | 92 | 2 |
| Searchable structural atoms | Not a legacy identity | 3,242 | 3,242 |
| Entry mapped-span records | N/A | 13,414 | 13,211 |

13,213 graph nodes; 6,700 edges; 894,386/894,386 admitted **node-local** bytes
accounted, zero unaccounted. These bytes may overlap raw-source annotations;
they are not a count of unique facts. All 3,242 atoms remain lexically eligible.
M 10x: 230 scopes/10,300 entries; 100x: 2,300 scopes/103,000 entries, no collisions.
Those were actual offline builds, not live retrieval or embedding measurements.

M policy `structural-retrieval-entry-v2`, heading rule
`single-complete-admitted-context-witness-v2`; target 500, soft 250–700, hard
800, context 80 local tokens, 32 atom references and 256 mappings per entry.
M 1x ordered batch digest:
`5101cadbe166c65d12c5bf203099dc035bb2357d317274a045e52ebdf40209ee`.
Use exact M bytes/maps/policy, not a new serializer tuned on canary results.

**Representation reachability does NOT prove semantic dense recall.**

## 4. Multi-tenant invariants

Every identity contains org, bot, document/source, document version ID, numeric
source version, source SHA-256, optional paired website/crawl ID/version,
structural revision, run, lane, manifest and representation generation; vector
identity also contains the full embedding profile/configuration fingerprint.
Atom and entry hashes alone are never authority.

Trusted scope is `HardKnowledgeScope` intersected with the server allowlist,
the manifest's exact document set and the unchanged query execution decision.
`None` means discovery within that set; empty means no access, never all rows.
All joins/reverse lookups carry full composite scope. Identical URL, title,
name, text or vector in another scope must not be fetched, ranked, materialized,
cached, logged as a candidate or exposed as resource metadata.

Document READY + processing completed and current active READY website/crawl
version are mandatory. For uploads, website/crawl identities must all be NULL;
NULL is not a wildcard. Failed/deleted/processing/superseded sources and stale
hashes/revisions/generations cannot qualify. The canary revision may be sealed
**validated**, not active: never require or set the serving structural pointer.
It must be the exact approved revision named in the canary manifest.

Scope is enforced **in the candidate SQL before ordering/LIMIT**, and again
when materializing. Changed source/permission state invalidates the paired run;
do not quietly shrink one lane. No cross-tenant result is tolerable.

## 5. Canary isolation architecture

Internal operator runner only; no HTTP/widget/browser selection parameter.
No invocation of the public chat route during mechanical/retrieval evaluation.

```text
frozen source + current development eligibility + approved paired execution
                     |                      |
           LEGACY manifest          STRUCTURAL_CANARY manifest
           legacy chunk dense       M entry dense
           legacy chunk FTS         exact atom FTS
           chunk rank-only RRF      typed route rank-only RRF
                     |                      |
         independent exact evidence + stage traces + offline comparison
```

Each paired request selects exactly one lane. Separate candidate pools, session
ownership, manifests, generation IDs and caches. No union across lanes and no
automatic fallback from structural to legacy. Legacy serving remains untouched
if any canary operation fails. No dual writes, promotion or active publication.

N specifies a canary-owned PostgreSQL namespace for future development tests.
An ownership marker/run guard and an explicitly authorized development DB are
required before any future DDL. No database connection or migration occurs now.

## 6. Representation manifest

Two immutable lane manifests under one paired run. Canonical JSON + SHA-256;
all ordered arrays have explicit stable ordering. The digest excludes mutable
run status; status is a separately locked control record bound to this digest.

| Group | Required immutable data |
| --- | --- |
| Authority | manifest schema version, run ID, lane enum, generation ID, org/bot, operator approval reference, environment/DB-identity attestation, creation time, expiration ceiling |
| Sources | Exact allowed development document IDs; source-to-development map digest; source versions, exact source text hashes, document-version IDs, website/crawl IDs and versions; expected lifecycle; corpus/catalog fingerprint |
| Structure | Per-document revision IDs and graph/evidence batch hashes; source fidelity; parser/normalizer/serializer versions; original exclusions and coverage ledger digest |
| Search representation | M policy/implementation/recipe and entry batch hashes; all expected entry IDs/input hashes/counts; atomic policy `atomic-fts-v1`; atom IDs/counts/canonical-text hashes; mapping digest and primary-route policy |
| Profile | gemini / gemini-embedding-001 / integer version 1 / 768; exact provider request config, task type absence, normalization behavior, SDK/code fingerprint, query/document input serialization hashes |
| Lexical/ranking | PostgreSQL major/pgvector version at future preflight; english config, websearch parser, ts_rank_cd, expression fingerprint; RRF weights/k/tie rule; raw/routed candidate budgets and truncation policy |
| Quality/accounting | Development-only approval per source, quarantined/excluded evidence inventory, admitted-byte counts, expected vectors/FTS/mapping counts, build budget and reuse-policy identity |
| Comparison | Query-set/GOLD/contract/history hashes, resource-catalog hash, query-understanding and selection code/config hashes, reviewer/context/generator hashes for later stages |

Legacy manifest binds exact existing chunk IDs, source/version/hash, chunk text
and vector digests and profile/config provenance. It never labels legacy chunks
as M entries. Store a separate exact legacy-membership relation; no broad
document-only lookup that might include a later chunk generation.

Content cannot set approval, lane or status. Changing any immutable item creates
a new generation/manifest; it does not mutate the meaning of an existing cache
key. Expected counts alone are insufficient: verify ordered identity/hash sets.

## 7. Lane/state model

These are **proposed internal states**, not production configuration additions.

| State | Permitted work / transition |
| --- | --- |
| OFF | Default; no build or reads. Explicit operator approval can authorize a new immutable run. |
| EMBEDDING_STAGING | Manifest sealed, budget reserved, bounded resumable build. Candidate reads prohibited. |
| INDEX_READY | All expected vectors, atoms, maps, indexes, coverage and source checks pass in one publication transaction; still not serving. |
| CANARY_READ | Short-lived server-owned lease referencing INDEX_READY generation; mechanical/retrieval-only reads. |
| COMPARATIVE_EVAL | Paired read lease for two separately INDEX_READY lane manifests and one execution snapshot. |
| FAILED / CANCELLED / EXPIRED / STALE | No reads or publication; retain non-secret audit/accounting, permit owned cleanup. |

Read modes are leases, not permission to mutate sealed representation content.
Index-ready state is necessary, not sufficient: current allowlist, approval,
expiry and source eligibility must also pass. There is **no ACTIVE transition**.

## 8. Initial canary population

Use only the existing DEVELOPMENT REAL_CORPUS_V1 copy, historically org 538 /
bot 674. These IDs are fixture configuration, never runtime branching. Future
preflight must prove the target DB/environment and frozen ID map; do not assume
the old development DB is still authorized or unchanged. No URL belongs here.

Local read-only inventory of saved source/measurement files suggests this smoke
selection (source IDs below must be translated through the frozen mapping):

| Source ID / fixture label | Representative shapes | M entries / atoms / local input tokens |
| --- | --- | ---: |
| 3 — Turmeric Boost | Ordinary resource, ingredients/list, directions, price, attributed reviews, FAQ, qualified timeline | 54 / 186 / 11,854 |
| 23 — Collagen Complex | Capsule/resource contrast, directions, FAQ, warnings, mixed page furniture | 42 / 177 / 16,672 |
| 25 — chocolate collagen page | Second resource, quantity instructions and staged timeline comparison | 50 / 180 / 12,134 |
| 30 — Joint Supplements | Collection/multi-resource list and review attribution | 31 / 67 / 5,176 |
| 12 — historically titled blocked page | Mixed-source quality/refusal inspection, negative witnesses | 103 / 360 / 15,183 before approval |

Four ordinary documents: **177 entries, 610 atoms, 45,836 local tokens**. Including
the fifth: 280 entries, 970 atoms, 61,019 tokens. These are known representation
counts, not authorized embedding work. Select concrete source spans/atom IDs for
each witness before running retrieval; a heading regex alone is not GOLD.

Important: ID 12 is **not empty** and M already produced 103 entries from it.
Its title does not prove whole-document quarantine. Inspect its frozen quality
ledger, nominate exact admitted/refused spans, and get explicit development
approval; do not invent a new blocked-title rule or silently drop it in only
one lane. Add domain-neutral quarantined/deleted/foreign fixtures to prove
mechanics. Real source IDs/names remain fixture-only.

After smoke, all 23 documents may enter a separately budgeted paired retrieval
run, subject to unchanged source/quality pins. No recrawl or source enrichment.
If either lane cannot honor the common approved population, mark the affected
comparison blocked/ineligible rather than changing GOLD or the population.

## 9. Dense index design

Structural vectors correspond **only to the exact serialized M entry text**:
approximately 1,030 expected full-corpus inputs before refusal/failure. Never
embed every graph node, every atom, a whole document or legacy chunks in this
lane. Preserve the complete entry-to-atom map and its exact source-byte spans.

Store entries separately from vectors so failed vector work cannot make an entry
searchable. A vector row requires an exact approved entry input hash, manifest,
generation and profile foreign key. Validate 768 finite numeric coordinates,
nonzero norm, cardinality and result ordering; reject an incomplete batch rather
than zip away missing results. No deterministic or other-provider fallback.

The first small correctness run uses exact cosine ranking over the already
scoped relation **in both lanes** in disposable test storage. This deliberately
avoids making ANN recall a second variable. Existing serving IVFFlat settings
remain unchanged. A separate operational-plan comparison may use equivalent
ANN configuration in both test lanes later, reporting exact-vs-ANN recall; it
is not silently folded into the representation comparison.

Legacy vectors may be read/copied into its isolated control relation only when
their frozen exact input/profile/config provenance is verified. Existing model
columns alone do not prove that. If reuse provenance cannot be established,
stop the live build for separate authorization of a paired control build;
never silently re-embed or charge it to the 1,030-entry estimate.

## 10. Atomic lexical index design

One logical FTS record per admitted searchable EvidenceAtom, including atoms
without a dense entry. Expected full inventory is **3,242**, not 1,030. Atomic
rows bind complete scope, manifest/generation, atom/bundle ID, kind, source
parts, original exact provenance, canonical text and serializer digest.

Proposed `atomic-fts-v1` projection is mechanical, not model-written:

1. Read frozen atom source parts in part-index order. Retain their primary
   source-backed text and required typed companions (FAQ question/answer,
   header/qualifier, review attribution, timeline label, list membership).
2. Map every emitted segment to the original node and UTF-8 interval. Remove
   continuation overlap only when the **same scoped node interval** is repeated;
   never deduplicate equal strings from different occurrences/resources.
3. Context-only ancestor headings belonging to another atom remain that atom's
   independent record. Do not inject the entire contextual entry into each atom.
   Keep companion mappings even where their source node is shared.
4. Stable structural separators and ordering are versioned and separately
   marked as non-evidence. No semantic rewrite, summary, inferred fact, appended
   resource alias or provider-generated context. Freeze bytes before embeddings.

An atom's original frozen evidence bundle remains the authoritative payload;
the canonical lexical string is only an indexed projection with exact maps.
Original typed parts/continuations remain available in full for materialization.
All admitted atom IDs must have one row even when english FTS reduces the text
to no lexemes; distinguish stored eligibility from actual lexical matches.

Use the existing english `to_tsvector/coalesce`, `websearch_to_tsquery`,
`ts_rank_cd` semantics and parameter binding. Do not claim exact substring,
punctuation, SKU or currency preservation from stemming alone. Mechanical tests
must characterize those cases; a parser limitation is reported, not secretly
fixed with ILIKE or another analyzer in one lane. Check PostgreSQL tsvector size
limits before publication; oversized atom/index failure blocks the build—no
silent truncation, hidden splitting or missing row.

## 11. Typed routing key

Use tagged immutable keys, not shared naked integers:

```text
ENTRY = (org, bot, run, lane, generation, manifest, document, source_version_id,
         source_hash, crawl_identity, structural_revision, profile, "entry", entry_id)
ATOM  = (same scope, "atom_only", atom_id)
LEGACY= (legacy scope, "legacy_chunk", pinned_chunk_id)
```

The atom's primary route is frozen at build time, independent of the query:

- Prefer an entry with body membership for this atom; choose smallest source
  part index, then entry ordinal, then entry key.
- For a contextual-only heading, use M's exact `HeadingAllocation.witness_entry`.
- For another context-only membership, require a complete exact witness by the
  existing maps; choose smallest ordinal/key. Incomplete context is not authority.
- No valid entry means ATOM route. A valid atom with continuation parts can have
  one primary routing entry without claiming that entry covers the whole atom.
  Materialization must load all required parts or explicitly mark incomplete.

Exactly one primary route per atom. Many reverse memberships are retained for
provenance, but never cloned into several positive lexical votes. Missing or
foreign mapped entries are corruption/refusal, not a reason to pick a similar
entry or invent a parent. Hash equality cannot bridge generations.

## 12. RRF normalization

For each query, save raw dense ranks/distances and raw FTS atom ranks/scores.
All ranks are one-based. Validation checks full scoped identity before fusion.

1. Dense hits route to their ENTRY keys. Deduplicate by key in original ranked
   order; conflicting scope is a hard error.
2. Lexical atoms route by section 11. Deduplicate routing keys in best raw atom
   rank order, then deterministic document/key order. Renumber the unique route
   sequence contiguously from one. Preserve **every fetched atom hit** and its
   original rank separately; normalized rank is a different trace field.
3. Apply the current formula once per route/channel:

   `score(r) = dense_weight/(k+dense_route_rank) + fts_weight/(k+fts_route_rank)`

   A missing channel contributes zero. Defaults 1/1 and k=60; freeze the actual
   approved `HybridConfig` in both lane manifests, without changing production.
4. Sort by descending total, best channel rank, document ID, typed key. No raw
   distance/ts_rank_cd comparison, child-count multiplier or textual dedup.

**Bounded rule:** raw candidates per channel use the same paired limit C, capped
by the existing 500 default ceiling. At most C distinct routes per channel and
2C in the union. No refill scan to compensate for collapsed lexical children.
Record raw-hit count, unique-route count and collapse ratio. If 40 children hit
one entry, that entry gets **one** FTS contribution, never 40 contributions.
A duplicate cannot improve its rank unless it has an earlier genuine raw rank.

Raw Recall@48 is measured with a separate fixed-C=48 channel-audit track in both
lanes; this is not a change to production budgets. The operational-budget track
uses each query's unchanged legacy adaptive C and reviewer limit. Freeze C once
from the legacy snapshot; do not give structural entries a larger budget based
on new counts. If an operational C is below a reported k, label that metric
budget-censored and report actual candidate count. Do not conflate the tracks.

The existing `weighted_rrf` assumes integer chunks. O may add a **canary-only**
typed wrapper using the same arithmetic; its equivalence/tie/duplicate tests
must pass. Do not modify the serving RRF implementation.

## 13. Lexical witness preservation

Maintain an immutable hit ledger for every fetched lexical atom (at most C):
original atom ID/rank/score, exact hit spans when available, typed primary route,
entry memberships and final kept/dropped reason. Fusion never discards this
ledger, even if a parent route loses the top-k cut. A lexical match indicates
retrieval support, not truth, entity identity or satisfaction of an entire field.

Reserve a bounded evidence sidecar of the best **eight distinct lexical atom
witnesses** (or fewer if fewer hits), preserving raw rank, with at most two per
primary route in the first pass. Fill unused slots by original rank without
new DB queries. This rule is domain-neutral; no ingredient/price/timeline regex
selects winners. At most eight reserved evidence units, at most C metadata hits.

These are **not additional RRF votes**. Report pure top-10/top-48 routing recall
before reservation and evidence recall after reservation separately. Exact
companion parts count against the same evidence-byte/unit budgets. If they
cannot fit, record `witness_budget_incomplete`; never mark the field absent.
Witnesses beyond eight retain ledger identity and an explicit budget-drop reason.
The eight reservations are inside the 48-unit materialized/selection pool, not
eight extras; at most 40 other units fit when all eight are used. Their primary
routes need not already be in the pure fused top-48, so report the sidecar's
incremental retrieval separately. Up to eight extra atom identities may be
hydrated alongside the bounded route metadata, never unbounded parent expansion.

For paired post-fusion evidence evaluation, apply the same eight-unit rule to
legacy lexical chunks; do not quietly improve only the structural lane with a
larger pool. Keep today's unmodified serving-legacy output as an additional
reference, clearly separate from this symmetric experimental wrapper. No claim
of representation-only gain may rely on a control that lacks this equal rule.

The later unchanged selection/reviewer/context checks may reject irrelevant or
contradictory witnesses. Record every decision. Reservation preserves access
and auditability, not forced inclusion of unsupported text in a final answer.

## 14. Dense hit materialization

A dense entry is a routing container, **not answer evidence**. Bulk load at most
48 top routes, their exact atom memberships and span metadata under the same
scope/source/manifest snapshot. Keep heading/context provenance labeled as such.
Do not paste `entry.text` directly into the answer context or label inherited
headings as independent facts.

There are at most 32 atom references/256 mappings per entry: theoretical route
fanout at 48 is 1,536 references/12,288 maps before identity dedup. These are
explicit caps, not permission for unbounded child text. Initial materialization
budget: 48 evidence units and 128 KiB serialized source payload, with at most
20 routing seeds for any existing bounded supplemental selection. Oversized
atomic continuations are refused as incomplete units rather than sliced.

Measure (a) route can reach expected atom, (b) exact expected atom actually
materialized, and (c) complete evidence survived the common selection/context
budget. Do not equate their recalls. Pure retrieval stage may enumerate bounded
mapping IDs without hydrating all text; choose children with the frozen common
selection policy, lexical witnesses first, not GOLD-aware selection.

No new recursive graph expansion, sibling closure or Phase 6/7 coverage engine.
Only exact children and already-declared companions/continuations are materialized.

## 15. Atomic hit materialization

Return exact atom/bundle/source-part text, all required continuation parts,
source/version/revision, typed roles, source URL and node-local byte provenance;
include primary route and original FTS rank. Preserve review speaker/resource
attribution, list membership, numeric units, conditions, timeline stage labels
and commercial roles together. A generic label is not the fact it labels.

Atom-only routes remain valid without a vector and consume one evidence unit
plus all their companion bytes. One complete atom may be reached by multiple
entries but is materialized once **by scoped identity**, not text equality.
Revalidate source/lifecycle before exposing text; scope mismatch aborts the run.
Absent map, invalid UTF-8 interval or continuation overflow is technical failure,
not a generated absence claim. Do not add related resources inferred from text.

## 16. Embedding staging

Future flow: verify frozen inputs → approve immutable manifests and budgets →
reserve work → bounded real-provider batches → validate/stage responses → verify
complete vector/FTS/map identity sets → transactional INDEX_READY seal.

Proposed initial **development** envelopes, not provider limits or production
sizing guarantees:

| Limit | Small smoke | Full 23-document run |
| --- | ---: | ---: |
| Max documents | 5 | 25 |
| Max newly embedded entries | 300 | 1,200 |
| Max local estimated input tokens | 70,000 | 250,000 |
| Max entries/batch | 8 | 8 |
| Max local estimated tokens/batch | 4,000 | 4,000 |
| Max concurrent provider batches | 1 | 1 |
| Max retries per batch | 2 after initial attempt | 2 after initial attempt |
| Wall deadline | 60 minutes | 180 minutes |

Both batch limits apply; split the list of whole entries, never truncate entry
text. Reuse M's hard 800-token serialization limit. Local tokenizer values are
not Gemini billed tokens; require an independent operator-approved currency/
provider-token reservation before live execution. At that time verify the
account's real quota and retry-after behavior. No provider account was contacted
in N, so these envelopes are proposals, not a promise the account can fit them.

Honor retry-after only within remaining deadline/budget. Daily quota, permission,
invalid input, profile/dimension mismatch and source change stop immediately.
Record retries as potentially billable attempts. Avoid nested retries in an
outer runner and existing batch helper; one bounded retry owner only.

Source/version/approval checks before reservation, each batch, resume and seal.
Do not hold a document lock across network calls. A short final transaction
locks run + sources in stable order, revalidates and seals atomically; racing
cancellation/source replacement prevents publication. No active-pointer write.
Start with one local representation-construction worker and one source batch in
memory at a time. Preserve M's batch-byte/node/edge limits and section 31's run
caps; stage incrementally without making partial output readable. M's observed
individual worker peaks are not an aggregate-memory guarantee for this future
runner. Record its actual peak before increasing parallelism.

## 17. Embedding profile

Fixed approved space: **Gemini / gemini-embedding-001 / v1 / 768** (`version=1`
in current code/storage). Freeze exact request config from the audited path:
`output_dimensionality=768`; task type/title absent; no newly introduced
normalization or query-specific prefix. SDK/version and code digest recorded.
Cosine distance remains the metric. No model/provider/dimension tuning.

Both lanes use the same exact query-embedding input and vector for each paired
query. Its reuse key is full input/profile/config hash, independent of evidence
representation; query vectors are not evidence. Future query-embedding calls
need their own budget, separate from entry construction. Mechanical tests use
explicit synthetic vectors only and never claim semantic recall from them.

Disable deterministic fallback explicitly in the dedicated future canary
process and assert actual returned provider metadata. Do not trust a cache hit
that merely reports the desired provider. Clear/isolate the process cache
before a real build. Existing serving embedding code/config remains unchanged.

## 18. Embedding reuse

Reuse requires **all**: exact serialized input-byte SHA-256, provider, model,
profile version, dimensions, full embedding configuration/serialization recipe,
real-provider provenance and successful finite/vector validation. M headings
and context are part of input. Source text/atom/document hashes alone fail.

Use an idempotent vector-record key over that identity plus authorized ownership.
Initial canary reuse is confined to the same org/bot approved manifest lineage;
no cross-tenant shared cache or access side channel. A new generation may reuse
approved exact vectors but creates its own scoped vector binding. Reuse cannot
resurrect revoked source access. Store reused count and original charge reference.

Today's `(text, provider, model)` in-memory cache lacks the other dimensions:
**not adequate proof of reuse**. Existing legacy vectors require the strict
audit in section 9; no silent recomputation. Unknown provenance is a preflight
hold, not a reason to substitute another embedding profile.

## 19. Quota/cost accounting

Future internal ledger keyed by `(build_id, manifest_hash, profile_hash)` and
per-entry attempt IDs. Track planned entries/local tokens, reserved provider
budget, attempted, succeeded, failed, reused, actual consumption, unknown
consumption, and unused reservation released. Separate document and query work.

Transactional unique work claims + leases prevent two workers charging/embedding
the same pending entry concurrently. Network success followed by process death
can leave consumption unknown: mark it, reconcile when possible and conservatively
charge/reserve before an approved retry. Provider APIs do not automatically give
exactly-once billing. Do not claim idempotent storage makes external calls free.

Never refund already consumed work. Release only demonstrably unused capacity;
cancel/expiry releases unattempted work after outstanding leases settle. No
customer billing integration or billing-code change in N. Currency estimate
must record the account's approved rate at execution, not an invented current
price. Unknown provider usage/cost stays explicitly unknown.

## 20. PostgreSQL/schema requirements

Current `document_versions`, `document_structure_revisions`, `structural_nodes`
and `structural_edges` can represent immutable provenance. Existing repository
has composite scope FKs, bounded reads, staging validation and state guards.
Use sealed validated revisions without activation. If already present, reuse
read-only only after exact identities/hashes match; otherwise stage the frozen
graph in the explicitly authorized development/test schema and validate it.
Do not create fake `Chunk` rows just to satisfy an old mapping API.

`chunk_structural_nodes` cannot express M memberships: it requires integer
legacy chunks and their structural FK. `Chunk.embedding` is non-null and
`ready_chunks` has no representation selector. Neither is safe for lexical-only
atoms or an isolated M vector generation. JSON metadata is not a substitute.

Proposed additive canary relations (names provisional, semantics fixed):

| Relation | Purpose / integrity |
| --- | --- |
| `canary_runs` | Operator/environment/expiry/enablement epoch, locked state, leases and budget; no serving pointer |
| `retrieval_manifests` | Immutable lane/generation/profile/policy/config/digest; scoped unique key and FK to run |
| `retrieval_manifest_documents` | Exact current source/version/hash/crawl/revision pins, expected counts/digests and approval; full composite source FKs |
| `canary_legacy_members` | Legacy lane's exact pinned Chunk IDs, text/vector digests; authoritative allowlist, not a second live Chunk set |
| `canary_entries` | M ID/ordinal/text/input hash/recipe/quality/boundary and counts; unique full manifest/document/entry identity |
| `canary_entry_vectors` | 1:1 scoped entry binding, `vector(768)`, full profile/config hash, provenance and successful build identity |
| `canary_atoms` | Exact atom/bundle/source-part payload + canonical FTS projection, primary route, role and lexical disposition |
| `canary_entry_atom_memberships` | Both scoped FKs, body/context usage, source part/index/count; no textual identity shortcuts |
| `canary_entry_atom_spans` | Exact entry/node UTF-8 intervals + primary/inherited/overlap role; full node/revision/membership scope |
| `canary_embedding_work` | Idempotent claims/attempt ledger and consumed/reused/uncertain accounting |

Atom source mappings/parts can be immutable validated payloads in `canary_atoms`
with a digest; entry reverse lookup needs relational memberships. No generic
JSON indexes. Add composite FKs/checks/unique constraints and append-only seals;
neither a raw foreign ID nor a JSON scope label suffices. State transitions and
sealed payload writes require guarded transactions. All indexes/tables are
future migrations, **not created in N**; frozen v1 schema/migrations unchanged.

Deleting a run cascades only through its owned canary relations. Do not cascade
from a canary run into shared source/revision or legacy tables. Existing sealed
revision deletion guards remain intact; retained shared source history is not
an orphan-cleanup target. In a truly disposable schema, whole-schema cleanup
requires its separate verified ownership marker and no unrelated objects.

## 21. SQL authorization shapes

Illustrative parameterized shapes, not executed SQL or a migration. Real O tests
must compile/run them against explicitly authorized disposable PostgreSQL.

Define `eligible_sources` as a **materialized, bounded, authorized relation**
joining manifest document pins, documents, exact document_versions, exact
validated structure revision and current website/crawl state. Predicates include:

- `org=:org AND bot=:bot`, server run/lane/generation/manifest; approved run
  enabled, unexpired, INDEX_READY and valid read lease.
- Explicit authorized document/source IDs and execution-scope intersection.
- Document ready/completed and exact pinned numeric version/source identity.
- Source hash equals the frozen **raw source text** hash, not a guessed equivalence
  to legacy processed `content_hash`. Use the existing captured source SHA if
  validated; for mutable `raw_text`, verify its UTF-8 SHA in this bounded source
  relation. Max 25 documents, not a per-chunk global source-text scan.
- Upload NULL identity or matching READY website + active READY crawl, exact
  org/bot/website/crawl/version throughout; no `OR crawl IS NULL` wildcard.
- Exact sealed revision/hash/quality approval and approved profile/config.

Legacy path uses the same common eligibility + its exact member Chunk set and
current `ready_chunks`/profile predicates; structural path never requires an
active structural pointer or a dummy ready legacy chunk to make an atom valid.

```sql
-- DENSE: the eligible relation contains only this manifest's authorized rows.
WITH eligible_sources AS MATERIALIZED ( /* predicates specified above */ ),
eligible_vectors AS MATERIALIZED (
  SELECT e.full_scoped_entry_key, e.document_id, v.embedding
  FROM canary_entries e
  JOIN canary_entry_vectors v ON /* complete manifest/source/entry/profile FK */
  JOIN eligible_sources s ON /* complete manifest/source/revision FK */
  WHERE e.manifest_hash = :manifest AND e.generation_id = :generation
    AND v.profile_hash = :profile AND v.build_state = 'succeeded'
)
SELECT full_scoped_entry_key, document_id,
       embedding <=> CAST(:query_vector AS vector(768)) AS distance
FROM eligible_vectors
ORDER BY distance, document_id, full_scoped_entry_key
LIMIT :candidate_limit;

-- ATOMIC FTS: same eligibility; never rank an unauthorized atom first.
WITH eligible_sources AS MATERIALIZED ( /* same predicates */ ),
q AS MATERIALIZED (
  SELECT websearch_to_tsquery('english'::regconfig, :query_text) AS value
)
SELECT a.full_scoped_atom_key, a.document_id,
       ts_rank_cd(to_tsvector('english'::regconfig,
                             coalesce(a.canonical_text, '')), q.value) AS score
FROM canary_atoms a
JOIN eligible_sources s ON /* complete manifest/source/revision FK */
CROSS JOIN q
WHERE a.manifest_hash = :manifest AND a.generation_id = :generation
  AND a.lexical_eligible
  AND numnode(q.value) > 0 AND querytree(q.value) NOT IN ('', 'T')
  AND to_tsvector('english'::regconfig,
                  coalesce(a.canonical_text, '')) @@ q.value
ORDER BY score DESC, a.document_id, a.full_scoped_atom_key
LIMIT :candidate_limit;
```

The comments are deliberately not unscoped shortcuts to copy into runtime.
Implement the full composite joins above and test SQL authorization before
LIMIT. Bound query text as current FTS does (8,192 chars); bound all limits.
Empty/non-indexable queries retain current sentinel semantics, not exceptions
or proof of absent knowledge. User strings never enter identifier/SQL fragments.

Dense/FTS parallel reads may use separate sessions. Recheck one source/approval
fingerprint after both and before evidence release. Any mismatch invalidates
the entire pair, preventing mixed-snapshot results. No long network transaction.
Final gate is a linearized run/lease epoch check; turning OFF blocks new reads
and cancels in-flight reads before their result-release gate. Already returned
data is not retroactively retractable.

## 22. Indexes

Future indexes follow actual predicates, not broad JSON search:

- Run `(org,bot,state,expires_at)` and unique run ID/manifest generation.
- Manifest-document `(org,bot,manifest,generation,document,source_version_id,
  revision)` with exact source/crawl FKs; document/source pin lookup.
- Entry `(org,bot,manifest,generation,document,entry_id)` unique; ordinal index.
- Vector binding same key + profile hash. Exact scoped scan first; ANN optional
  later in isolated lane storage with the **same** cosine configuration on both
  sides and exact-recall comparison. Never alter serving IVFFlat/ANN parameters.
- Membership forward `(manifest,generation,document,entry_id,atom_id)` and reverse
  `(manifest,generation,document,atom_id,entry_id)` including org/bot keys; primary
  route uniqueness checked separately. Span-order index supports bulk hydration.
- Atom composite scope/ID and GIN expression index, proposed name
  `ix_canary_atoms_content_fts_en_v1`, exactly
  `to_tsvector('english'::regconfig, coalesce(canonical_text, ''))`.
- Work unique `(build,manifest,profile,entry_input_hash)` plus pending/lease lookup.

Verify existence/validity and natural `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
for both channels. Record forced-index capability separately if tested. A tiny
fixture sequential scan is not failure. GIN filtering before rank does not make
ts_rank_cd itself indexed. ANN global filtering can underfill a scoped pool;
the initial exact-scoped control avoids that confound.

## 23. Cache isolation

Initial comparative run disables retrieval/answer caches in its **internal
runner**, without changing production cache configuration. It may share one
strictly identical query vector between paired requests. Warm-cache performance
is a separately labeled experiment, never mixed with cold retrieval latency.

Future independent namespace:

```text
canary-v1 / org / bot / run / lane / manifest_hash / generation /
query_contract_hash / history_hash / profile_config_hash / hard_scope_hash /
current_corpus_source_generation / hybrid_selection_policy_hash
```

Include materialization policy and lexical normalization version as well.
Never reuse a legacy answer/retrieval cache entry. Every hit must first pass
server enablement/lease/expiry and current source/lifecycle/profile checks.
OFF/expiry/revocation makes the lane inaccessible immediately at the gate;
physical TTL cleanup is not the access-control mechanism. No cache code in N.

## 24. Failure semantics

| Failure | Required outcome |
| --- | --- |
| Embedding quota/provider error | Stop or bounded classified retry; no fallback; partial build inaccessible |
| Wrong dimension, non-finite/zero vector, wrong profile/order/count | Build failure, no partial publish |
| Source/hash/crawl/permission changed; stale manifest | STALE; invalidate both paired results; new approval/manifest needed |
| Missing/foreign atom mapping; inconsistent digest | Hard correctness failure; no nearest-text substitution |
| FTS/index build failure, unindexable oversized atom | Not INDEX_READY; leave legacy alone |
| Runtime one-channel failure | Record dense_only or fts_only diagnostics as current policy; cannot count as a healthy paired hybrid acceptance |
| Both channels fail | Explicit technical retrieval failure, not no evidence / false absence |
| Query parser empty/non-indexable | Successful defined lexical status, not channel outage; compare same behavior |
| Budget/materialization overflow | Explicit incomplete-evidence/capacity result; no silent truncation or absence claim |
| Cancelled/expired/OFF | No new reads/work, discard pending result release, account consumed work |

Full INDEX_READY pool required for reads; never query just the successful vector
subset. No rollback mutates legacy. Cleanup ownership failure blocks acceptance
until inspected; no broad schema/database deletion.

## 25. Cancellation/restart

At batch boundaries and after network returns, check run epoch/lease, source pins
and expiration. Cancellation wins the final publication CAS. Late results may
be recorded as consumed-but-unpublished; they cannot resurrect a cancelled run.

Resume only an unexpired EMBEDDING_STAGING generation with unchanged immutable
manifest, successful exact-input vector hashes and valid work leases. Reuse
only known successes; unknown attempts require reconciliation/budget approval.
FAILED/CANCELLED/EXPIRED/STALE runs do not silently resume—start a newly approved
generation with explicit safe reuse. Cleanup is idempotent and run-owned;
assert legacy table/data/vector hashes and shared source history unchanged.

## 26. Canary security

Future runner rejects production/prod, absent environment attestation, default
application DB fallback and targets outside the explicitly approved development/
disposable DB identity. An `APP_ENV=development` string alone is insufficient.
Require operator authorization, org/bot allowlist, exact manifest/run, expiry
and owned-schema marker. Unknown environment means refuse before credentials
or embedding work are used.

No browser field, bot text, metadata, uploaded instruction, query planner output
or source link can enable a lane, change SQL/profile or fetch a URL. Source text
is inert data. Parameterize searches. Separate development DB role and scoped
repository checks; public app role has no canary read API. Traces expose only
authorized IDs/approved fixture excerpts; keys, DSNs and raw provider errors are
redacted. No customer production DB, quota or bot settings are involved.

## 27. Retrieval GOLD

Three layers, with no final-answer GOLD edits:

**Layer 1 — mechanical, domain-neutral.** Freeze source, graph/entry/atom IDs,
exact expected source spans and negative neighbors before any retrieval results.
Include ingredient-like identifier, legal clause, error code, ordered list,
review speaker/resource, policy qualifier, numbered timeline, price with purchase
role, dosage/unit, orphan heading, lexical-only atom, split continuation and
identical-text foreign org/bot/stale revision fixtures. Synthetic vectors test
mechanics only; future authorized real embeddings test actual semantic recall.

**Layer 2 — real retrieval GOLD.** Derive a *new* immutable sidecar from unchanged
`REAL_CORPUS_V1_EVAL_V1`: expected/alternative resources, required fields,
qualifications, negative resources and source-backed supporting spans. Map its
old source IDs to development IDs through the frozen map. Resolve exact atoms/
entry paths by node provenance/source span, with manual review of ambiguous
overlaps; do not guess IDs from semantic similarity or match repeated text
without document/version/occurrence proof.

Current GOLD: 90 cases, version 1; semantic digest
`9b6bfad4939096b18e5cfa66ce7e6a1c1e1489718d8f294e29a7a09006c68257`;
file SHA-256
`e7d0314bd79bd6279f5b404ee28a9c2211e2d0ddf0313d938e10370b3f19f5b1`.
Frozen corpus fingerprint
`44b24a95b28ea2fa220f1f6dbf1f81d10042c769afff232f5baf4f3001a0b2c8`.
These files were read locally, not fetched from production.

Sidecar schema per case: original question/history hashes; required resources;
conjunctive obligations with alternative acceptable atom/span sets; exact M
entry routes; original legacy span/chunk mapping; typed relationship/qualifier
dependencies; authorized negatives; refusal expectation; mapping confidence;
human approval. Preserve alternatives instead of requiring one arbitrary entry
when several valid routes reach the same evidence. Unmappable obligations are
explicit coverage gaps, not deleted cases. Freeze before vector/FTS results.

GOLD is evaluator input only. Never feed required answer facts/expected IDs into
query understanding, candidate selection, normalization or materialization.
Keep expected authorization fixture scope distinct from relevance GOLD.

**Layer 3 — frozen 90-question answer benchmark.** Only after all mechanical
and retrieval gates pass and separate model-call budget approval. No execution
of any layer involving DB/providers in N.

## 28. Retrieval metrics

Per-query numerator/denominator and stage trace, then macro/micro and category
aggregates. Empty required sets are N/A, not automatic recall=1. Alternative
sets are satisfied once; duplicate routes/overlap cannot inflate a numerator.

| Metric | Definition / separation |
| --- | --- |
| Dense entry recall@5/10/48 | Fraction of required evidence obligations with at least one acceptable entry route in raw dense top-k; report raw entry-ID recall where unique GOLD exists |
| Atomic FTS recall@5/10/48 | Required atom/alternative-set coverage in raw lexical top-k before route collapse |
| RRF routing recall@10/48 | Required obligations reachable from pure fused top-k keys, before reservation; atom-only routes valid |
| Required evidence atom recall | Exact required atom/span sets actually materialized, then selected, then context-admitted, reported separately |
| Required resource/document recall | Required approved resources/documents present at each stage; multi-resource page ownership not inferred from document match alone |
| Wrong-resource rate | Selected units attributable to an incorrect resource / selected units; unknown attribution reported separately |
| Foreign-scope and stale hits | Counts at raw channel, routing, materialization and trace stages; any >0 hard failure |
| False-absence rate | Supported GOLD obligations labeled absent / supported obligations; selected-context empty is not corpus absence |
| Complete list coverage | All required members plus list identity/qualifier; partial-list rate also reported |
| Review attribution coverage | Required review text plus correct speaker/resource attribution; detached quote does not satisfy |
| Timeline-stage coverage | Stage label + duration/range + corresponding benefit and qualification |
| Commercial/price-role coverage | Amount/currency/unit/offer/conditions relationship together; bare number insufficient |
| Directions/quantity coverage | Exact amount/unit/frequency/preparation dependencies where supported |
| Qualification/warning coverage | Required exception/caution attached to its evidence, not merely somewhere in pool |
| Source noise | Selected source bytes/units outside approved relevant evidence; distinguish harmless context from wrong-resource text |
| Diversity / duplication | Distinct correct resources and atoms; repeated same scoped atom/ranges divided by emitted evidence references/bytes |
| Size/cost | Vectors, FTS rows, memberships vs span rows, fanout p50/p95/max, index/storage sizes, build wall/work, local/provider tokens and provider cost |
| Latency | Dense, FTS, parallel wall, normalization, RRF, materialization, current selection/context and total retrieval p50/p95; query embedding separate |

Report actual per-query C and returned counts. Statistical summaries use paired
fixed query order/counterbalanced lane order, one warmup per query excluded and
three cached-query-vector retrieval repetitions per lane after authorization;
no additional embedding calls for repetitions. Record hardware/DB version/load,
timeouts, cold/warm state and sample count. Do not call synthetic timings
production latency. Preserve critical individual failures rather than one score.

## 29. Legacy comparison

One source freeze, exact common authorized documents, profile/config, query
text/history and execution contract for each pair. Reuse current query
understanding unchanged. For retrieval-only evaluation, replay validated saved
execution snapshots where available, or freeze one execution result before lane
selection; any necessary new planner/model call needs later explicit approval.
N performs no such calls. Synthetic contracts are labeled mechanical, not AI
planner acceptance.

Record per lane: raw dense, raw FTS, normalized routes, pure RRF, reserved
witnesses, exact materialized children and selected evidence. Compare cold
retrieval first. No generator/reviewer required to prove these mechanics.
The query vector is shared only when exact input/profile matches.

If the common planner/discovery excludes a required resource, label **QUERY
UNDERSTANDING FAILURE**. Report both end-to-end denominator (all cases) and
conditional representation denominator (required source is eligible), with
excluded-case counts and reasons. Never erase planner failures from the report,
force expected resources into the runtime query or retune Phase 5 in this run.

### Downstream compatibility boundary

Current serving retrieval combines recall, document selection, field/sibling
queries and metadata evidence; it is not a pluggable entry store. O must first
stop at pure retrieval/materialization. Later answer evaluation needs a small
**internal, non-serving adapter** that presents exact children to the existing
unchanged selection/reviewer/context/generator policies. It must not call the
legacy all-in-one retrieval function on structural candidates.

Use a frozen per-manifest bijection from typed evidence keys to request-local
integer handles for APIs that currently require `(document_id, chunk_id)`.
These handles are **not ORM Chunk IDs**, are never queried against `chunks`,
never published or cached in serving caches, and reverse-map losslessly in
traces. Structured metadata evidence stays explicitly typed, never masquerading
as a source atom. Same metadata snapshot/eligibility in both lanes, separately
tagged so it cannot inflate raw-channel recall.

All supplemental field/sibling hydration must use the selected lane repository
with the same bounded policy and hard scope; no legacy-chunk fallback in the
structural lane. Reuse current deterministic field/proposition/selection
functions where compatible, not new query-specific boosts. If this cannot be
done without changing their decision semantics, **hold final-answer evaluation**
and seek a separately reviewed compatibility change. Do not claim the new
representation is proven end-to-end from pure RRF recall alone.

Apply identical reranking/reservation limits in the paired wrapper; label its
output separately from untouched serving-legacy reference output (section 13).
This makes any policy-wrapper effect visible rather than attributing it to
representation. No cross-encoder, new planner, new reviewer or new generator.

## 30. Quality gates

Mechanical gates before quality evaluation:

- ZERO tenant/bot/unauthorized metadata/stale-source/generation leaks at **every**
  stage; stronger foreign matches must never be candidate rows.
- 100% exact entry↔atom/source map validity and admitted-evidence accounting;
  exact declared exclusions retained, no missing lexical-only atom.
- All vectors exact profile/config/dimension, finite/nonzero, complete build;
  no partial canary pool, wrong-input reuse or deterministic fallback.
- Dense and atomic FTS functional on real PostgreSQL; correct scope-before-LIMIT,
  empty query/phrase/morphology/OR/exclusion/numeric handling, valid GIN.
- Typed routing, per-channel dedup, one-based formula, deterministic ties,
  bounded child support and witness ledger/reservation proven.
- Cache/run expiration/revocation isolation, cancellation, safe restart and
  owned deletion proven; legacy data/config/serving path unchanged.

Retrieval gates, evaluated per protected case/category (not only averages):

- No critical required-evidence regression relative to legacy at equal budgets;
  a critical obligation reached/materialized by legacy cannot silently disappear.
- False absence, complete lists, review attribution, timeline stages, price
  roles, directions/quantity and qualifications **not worse** on protected
  witnesses. New structural wins do not cancel a critical loss elsewhere.
- No new wrong-resource attribution. Ambiguous source relationships remain
  uncertain, not claimed as resolved by retrieval-entry context.
- Report all mixed outcomes exactly. Structural need not win every noncritical
  query; improvements and regressions require counts/case IDs and stage causes.

Budget censoring/unsupported GOLD mapping is a reported limitation or block,
not a pass. Failed gates stop progression; no weight/analyzer/prompt tuning
during acceptance to manufacture success.

## 31. Cost/scale gates

| Full saved corpus | Legacy | M structural |
| --- | ---: | ---: |
| Dense vectors expected | 1,092 existing | 1,030 prospective |
| Vectors / 1,000 source tokens | 5.422664952 | 5.114784707 |
| Local embedding-input tokens | 212,061 | 217,263 |
| Local input / source tokens | 1.053054718 | 1.078886864 |
| Raw float32 coordinate bytes only | 3,354,624 | 3,164,160 |
| Lexical records expected | 1,092 chunk rows | 3,242 atom rows |
| Entry mapped-span rows | N/A | 13,211 |

M uses 62 fewer prospective vectors but **1.02453067749374x** the legacy local
input tokens. Fewer vectors is not automatically lower embedding cost. Raw
payload excludes pgvector headers, table tuples, indexes, provenance, FTS and
mapping storage. Membership-row count is not the 13,211 span count; measure it.

Report measured total/ANN/GIN/mapping bytes, bytes/source token, tokens/source
token, vectors/1k tokens, mapping fanout, work/1k tokens, retrieval latency per
candidate and p50/p95 absolute times. No old 1,638 threshold. No provider-billed
token/dollar estimate inferred from local tokens alone.

Development capacity tripwires: refuse builds above section 16 reservations,
above 25 documents, above 5,000 atoms or 25,000 span rows; never truncate to fit.
A >2x paired retrieval p95 or >2x total indexed-storage/source-token ratio is a
review hold requiring explanation, not an automatic production rejection or
license to alter parameters. Record source-quality and outcome differences
before interpreting costs. Existing M single-document validation can be
superlinear over some sizes; build off the serving request path with bounded
workers. No production scale claim from 23 documents.

## 32. Future 90-question benchmark

Only after mechanical, paired retrieval, compatibility and budget gates pass:
run unchanged `REAL_CORPUS_V1_EVAL_V1`, with the same current bot/system prompt,
planner, reviewer, context builder, verifier/polish settings and generator/model
in both lanes. Freeze code/config/request hashes, not just model names.
Do not switch a provider or let one lane use a newer prompt.

Historical accepted baseline is **32 PASS / 29 PASS WITH MINOR ISSUE / 29 FAIL**,
confirmed in local `FINAL_PLANNER_COMBINED_MEASURED_SUMMARY.json`. Compare to it,
but also use a contemporaneous paired legacy control: provider nondeterminism,
cache state and elapsed time make historical counts alone insufficient proof.
Generation quotas for both arms need explicit later approval; no calls in N.

For conversational pairs, primary isolation evaluation replays the identical
frozen input history/state to both arms, with per-case hashes. Separate
lane-owned trajectory runs may be reported later but cannot be mixed with
representation-only results because prior answers can change subsequent scope.
Respect the frozen benchmark's follow-up ordering and refusal categories.
Gold answers never enter prompts. No extra customer questions or canary tuning.

## 33. Phase 4 completion definition

Phase 4 is complete only when:

1. M representation is checkpointed (done here).
2. This canary design is accepted by review (not self-authorized activation).
3. Approved structural canary builds completely with real profile vectors/FTS.
4. Real hybrid mechanics, mappings, isolation, lifecycle and cleanup pass.
5. Paired retrieval/cost/latency metrics and exact regressions are recorded.
6. Unchanged final frozen 90-question benchmark is rerun after retrieval gates.
7. Results are compared with both original 32/29/29 and paired legacy control.
8. No authorization/security regression or critical evidence regression remains.
9. Actual provider cost, construction cost, storage and latency are documented.
10. An explicit decision is made whether Phase 4 representation becomes the
    foundation for Phases 5–8, with known limitations and any deferred blockers.

“The new index works” alone is not completion. N closes design only. Phase 5
query-understanding repairs, Phase 6/7 expansion/coverage and source-capture
enrichment remain separate experiments and must not confound this comparison.

## 34. Implementation sequence and future test plan

O should be staged behind gates, without automatic live execution:

1. Freeze standalone canary contracts/manifests and retrieval GOLD sidecar from
   unchanged sources; prove offline preservation/import/no-provider boundaries.
2. Implement additive canary repository/schema under owned disposable scope;
   obtain fresh explicit DB authorization. Test synthetic vectors and FTS first.
3. Implement typed normalization, exact materialization, bounded witnesses and
   full trace; prove equivalence of rank arithmetic and shared selection limits.
4. Implement idempotent build/accounting/resume gates; mock provider behavior for
   mechanics, never call a fallback provider. Obtain separate embedding budget.
5. Audit strict legacy reuse and source/profile provenance; authorize smoke
   corpus/quality, then bounded real smoke embedding/retrieval only.
6. Review smoke; separately approve full 23-document build and paired retrieval.
7. Review metrics and downstream adapter parity before any final-answer quota.
8. Separately approve frozen final 90-question comparison; report completion or
   exact blockers. No production publication in O.

| Future tests | Exact assertions |
| --- | --- |
| Manifest identity / freezing | Every source, version, policy, input byte, config or generation change alters identity; mutable status cannot rewrite sealed payload |
| Tenant/bot/source/version | Identical text/vector with better score in foreign org/bot, inactive crawl, deleted/processing source, stale revision/profile/generation never appears before LIMIT or in metadata |
| Empty/invalid scope | None versus empty preserved; wrong run, unapproved source, expired lease and unsafe DB target refuse before I/O |
| M preservation | All 740 protected files, frozen batches, atom counts/maps/exclusions unchanged; no L/M policy mutation |
| Bidirectional maps | Full composite FKs, source UTF-8 range proof, continuation completeness, body/context distinction, malformed/foreign ID rejection |
| PostgreSQL dense/FTS | Exact scoped cosine; phrase/stemming/OR/negative/empty/numeric input; bound SQL injection-shaped query; ranking before LIMIT; late lexical witness; plan/index validity |
| Embedding | Exact 768 finite/nonzero vectors; wrong order/count/config/profile refused; strict input-hash reuse; no deterministic fallback; no cross-tenant reuse |
| Failure/race | Partial batch, quota, timeout, crash after paid work, duplicate worker claims, source change during call, cancellation-before-seal, expired restart; no partial INDEX_READY |
| Typed RRF | One-based ranks, zero missing channel, weights/k preserved, stable ties; many atoms→one entry yields one vote; atomic-only route; no multiplied reverse-map votes |
| Witness/coverage | Best eight bounded, provenance for all C; exact lexical witness survives normalization; blocked byte/unit admission recorded incomplete, never absent |
| Degradation | Dense-only, FTS-only and both-failed explicitly distinguished; no ILIKE or other-lane fallback; degraded run not full-hybrid acceptance |
| Cache | Lane/manifest/run/source/profile/contract changes miss; OFF revokes even warm hits; old serving cache inaccessible; corrupted result refused |
| Legacy comparison | Same query/history, source set, pre-retrieval scope, C/profile/weights and selection budgets; atom/entry recall distinct; no structural lookup reaches legacy fallback |
| GOLD / protected evidence | Source-pinned resource/atom matches, complete lists, attributed reviews, timeline stage/benefit/qualification, price role and quantity dependencies; unknown mapping not dropped |
| Downstream adapter | Stable typed-key↔local-handle bijection; no ORM lookup by handles; same reviewer/context/prompt decisions; supplemental hydration confined to chosen lane |
| Expire/delete/rollback | Run-owned cleanup only; no source/revision or legacy deletion; counts/hashes and serving output unchanged; cleanup fail blocks acceptance |
| Cost | Unique reservation, spent versus unused versus unknown accounting; retries bounded once; reused vectors not billed again locally; no claimed exactly-once external billing |

Acceptance test implementation belongs to O. N added no test code, canary
configuration, migrations, SQL execution or runtime imports.

## 35. Risks and explicit holds

- **Profile reuse provenance:** existing columns/cache do not prove exact input/
  config identity. Future preflight must attest it or stop for a separately
  authorized control build. Never make an unannounced provider call.
- **Different units:** route recall can look good while a needed child is never
  admitted. Keep raw atom, routed, materialized and final-context metrics separate.
- **Lexical compression:** many children collapse to one vote and can reduce
  route diversity; preserve witnesses, report collapse/budget censoring, no refill
  or boost tuned on this corpus.
- **FTS limitations:** stemming/tokenization may not preserve exact identifiers,
  punctuation or prices; test and report without a different lexical policy.
- **Quality/attribution:** a READY mixed/blocked-title page can contain useful and
  misleading text. Frozen quality evidence and per-source approval matter;
  title-based exclusion or invented resource ownership would be a new variable.
- **Downstream coupling:** existing field/sibling retrieval and integer evidence
  IDs are not plug-compatible with atoms. Hold final generation until the
  internal adapter proves no legacy leakage or decision-policy change.
- **Wrapper confound:** witness reservation is new experimental plumbing. Apply
  it symmetrically, preserve pure-channel metrics and untouched legacy reference;
  never credit representation for a one-sided policy advantage.
- **Planner confound:** wrong shared scope remains Phase 5, not a representation
  rescue. Conditional metrics cannot replace full-denominator reporting.
- **Cost/capacity:** local tokens are not billable tokens; maps/FTS can outweigh
  vector savings; finite-value checks and own-row memory/byte caps are necessary.
- **Lifecycle races:** separate recall sessions and cached responses must pass
  final source/epoch checks; changed evidence invalidates a pair.
- **Historic data:** saved projections lack some original source structure;
  canary cannot recover absent anchors, relationships or HTML by inference.
- **No operational verification in N:** current DB reachability, quota, installed
  extensions/indexes and deployed settings deliberately remain uninspected.
  Their fresh safe preflight is an execution gate, not evidence of readiness now.

## 36. Exact next phase and decision

**A. PHASE 4.1N DESIGN — COMPLETE**

**CANARY ARCHITECTURE BOUNDED AND IMPLEMENTABLE**

**READY FOR PHASE 4.1O DEVELOPMENT EMBEDDING + HYBRID RETRIEVAL CANARY IMPLEMENTATION**

Meaning: implement the isolated contracts/schema/runner and prove offline plus
authorized disposable mechanics first. Real-provider smoke requires separate
explicit target, source/profile/reuse approval and budget gates. A is not a
claim those future gates already pass. No unresolved algorithmic identity,
fusion, ownership or deletion decision is delegated to a future guess.

Design audit: current RAG/provider/schema/source files only read; public OSS
source research only; no database connection, vector creation, embedding/model
call, FTS/RRF implementation, canary runtime, source mutation, benchmark,
production access, push or deployment. One authorized local M checkpoint only.
N's design and ledger remain uncommitted for review. Stop here.

Final local checks for N: exactly the two documentation files above differ from
the M checkpoint; no backend/frontend implementation diff. All 740 preservation
hashes and the frozen 90-question GOLD file digest still match. All 36 required
sections present; secret-pattern/trailing-whitespace scan and `git diff --check`
pass. No N runtime tests or benchmarks were needed for this documentation-only
change; the fresh 323-test checkpoint recheck and prior 3,406-test result are
distinguished in section 1.
