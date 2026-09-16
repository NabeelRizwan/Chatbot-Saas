# Phase 4.0 — Structural ingestion, document relationships and source fidelity

Status: **DESIGN COMPLETE — NOT IMPLEMENTED**. Research/code inspection: 2026-09-16. All sizes, rollout switches and acceptance thresholds below are proposed design decisions, not measured performance or existing functionality.

Phase 3.7 checkpoint: `d036dc30b15f8daa6bdc8327c42a897a55d77c51`, on `main`, parent `7c8236001ccc552c89c860b2db6a4d4c369ee211`. Message: `Phase 3.7: harden planner intent contract after real-corpus baseline`. Only the three approved planner/test files were committed. No push or deployment.

## 1. Baseline evidence and checkpoint audit

The frozen REAL_CORPUS_V1_EVAL_V1 baseline is **90/90: 32 PASS, 29 PASS WITH MINOR ISSUE, 29 FAIL**. Corpus: **23 READY documents, 1,092 chunks/vectors, 23 resources/mappings, 91 terms**. GOLD hash: `9b6bfad4939096b18e5cfa66ce7e6a1c1e1489718d8f294e29a7a09006c68257`.

Evidence authority is the ignored local `.codex_real_corpus_v1/PHASE_3_7_REAL_CORPUS_BASELINE_REPORT.md`, especially sections 23–28, its verbatim combined answer review, saved traces and frozen source snapshot. The 90-case baseline spans technical contract-repair segments; it is not 90 reruns on the final checkpoint. Original answers/grades are not rewritten by this design.

Checkpoint audit: actual diff reviewed; exactly `backend/services/rag_planning.py`, `backend/test_planner_intent_contract.py`, `backend/scripts/test_scoped_rag_regressions.py`; empty initial index; no environment, production configuration, corpus, credentials or traces staged. Closed canonical/alias/field vocabulary, strict unknown rejection, preserved requested fields and unchanged hard authorization confirmed. Fresh offline focused run: **31/31 PASS, 0.142 s**, configured DB/live HTTP blocked. Prior full suite **2083/2083 PASS** remains applicable because sealed source hashes match. `git diff --check` and staged check passed. Prior 181-artifact preservation gate passed before commit; saved cleanup proves temporary profile removal. No live test rerun.

| Witness | Proven loss/boundary | Phase 4 implication, without overstating causality |
| --- | --- | --- |
| 17, 56, 58: Joint Support ingredients | Full lead was recalled; document cap or context reduction preferred four ingredient cards over seven-item source material | Preserve full-list membership and distinguish cards; later selection/coverage still needs Phases 6–8 |
| 18: Collagen Complex sources | Subject/query mode and final evidence omitted a source type | Preserve complete source list; do not claim ingestion fixes wrong query scope |
| 75: MyCovital ingredients | Full four-mushroom chunks 1227/1228 lost document cap | Expose complete list as a bounded unit; selection remains a separate defect |
| 53 versus positive control 85 | Collection review/product link disappeared in one context and survived in another | Materialize the witnessed review-to-product association, not just adjacency |
| 67, 69: timeline | Query scope/document cap/reviewer dropped stage material; 69's 1003/1004 reached reviewer | Preserve ordered stages and their bodies/qualifiers; no promised end-answer fix from parsing alone |
| 27 versus 64: commercial roles | 27 lost roles in condensation; 64 misassociated a daily amount despite supplied roles | Preserve labeled price/offer structure; generation/coverage errors remain later work |
| 40, 57, 61: quantities/directions | Query fields/comparison members or final context lost useful clauses | Preserve quantity/unit/frequency/compatibility clauses together; no field-parser change here |
| Broken endings: 10 answers; source noise: 29 | Answer-formatting noise is not evidence that all source URLs were lost at ingestion | Make links round-trip intact; formatting fixes belong later |
| Document 12 blocked-page title, 103 READY chunks | Existing corpus includes a mixed source-quality witness | Page/block quality annotations; never a domain-wide blacklist or silent deletion |

The largest earliest failure class is **query understanding: 17/29 failures**, outside this phase. Other earliest causes: relationships 1, selection 4, reviewer 1, context 5, generation 1. Structural ingestion is enabling infrastructure, not a claim to repair all 29 failures.

## 2. Goals

Preserve source-backed structure, complete bounded evidence units, source locations, explicit links and qualified relationships before embedding. Make the result independent of fetch provider, extraction library and generation model. Keep PostgreSQL, current embedding profile, hybrid recall and hard scope. Support PDF/DOCX/TXT and existing website intake; do not silently expand accepted upload formats.

A source statement remains a source statement: a testimonial is not a verified benefit, a heading is not its body, an unlabeled number is not a price, and a product link is not permission to fetch or disclose its target.

## 3. Non-goals

No query-understanding/semantic optimizer changes (Phase 5), reranker/budget tuning (6), automatic parent/neighbor/relationship retrieval expansion (7), or coverage recovery/final-pack behavior (8). No changes to prompts, generation, provider/model, embeddings/dimensions, ANN, FTS/RRF, auth, billing, credential pools, crawler coverage or deployment architecture. No graph database, framework replacement, LLM enrichment, fabricated product ontology or benchmark-specific runtime rules.

This task performs **no installation, migration, crawl, structural reprocessing, chunk generation, embedding, database access or application runtime edit**. The future changes described below require separate implementation authorization.

## 4. Official OSS research and adaptation ledger

Sources reviewed on 2026-09-16. `main` links are moving references, not a dependency lock; implementation must pin tested releases/commits, licenses and any local model artifacts. These are architectural adaptations, not copied framework implementations.

| Project / primary source | Pattern studied | Adapt | Reject / reason it fits this app |
| --- | --- | --- | --- |
| Docling — [document model](https://docling-project.github.io/docling/concepts/docling_document/) and [format support](https://docling-project.github.io/docling/usage/supported_formats/) | Typed items, hierarchy, reading order, body/furniture and provenance; Markdown/HTML/PDF/DOCX conversion | Docling as an isolated extraction adapter into our own normalized model; retain original item references/locations when available | Do not make Docling JSON our database schema or claim Markdown recovers missing DOM/layout. Our contract owns versions, tenancy and source fidelity |
| Docling — [chunking](https://docling-project.github.io/docling/concepts/chunking/) | Structural elements with heading/caption metadata, token-bounded splitting/peer merging, repeated table headers | Structural-first splitting, compatible-peer merge, distinct raw content/context serialization and source mappings | Do not blindly accept peer merging or overflowing headers; our subject/role boundaries and hard token limit take precedence |
| RAGFlow — [DeepDoc source](https://github.com/infiniflow/ragflow/blob/main/deepdoc/README.md), [parser routing](https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/ingestion_pipeline/configure_parser_component.md), [QA parser](https://github.com/infiniflow/ragflow/blob/main/rag/app/qa.py) | Layout/table/position extraction, format-specific parsing, grouped question-and-answer units | Route by actual source format; preserve tables, QA pairs and positional provenance before chunking | Do not adopt its datastore, orchestration or every heuristic. Markup stripping is unsuitable when it erases anchor relationships; not every heading is a question |
| LlamaIndex — [hierarchical parser](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py), [AutoMerging source](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py) | Explicit parent/child nodes; retrieval can replace children with a parent and fill gaps | Store a navigable structure with leaf evidence and unembedded parents, enabling later bounded expansion | No AutoMerging retrieval now, recursive fetch-until-stable, score averaging, or framework docstore. Future traversal must reapply our scope |
| Haystack — [DocumentSplitter](https://docs.haystack.deepset.ai/docs/documentsplitter), [hierarchical splitter source](https://github.com/deepset-ai/haystack/blob/main/haystack/components/preprocessors/hierarchical_document_splitter.py), [sentence-window source](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/sentence_window_retriever.py) | Source/split identity, offsets, hierarchy metadata and configurable neighboring windows | Stable source/version/order identity and exact spans; bounded neighbor references for later use | Do not equate every level with another embedding or enable window retrieval now. A source_id alone is not a tenant/version authorization boundary |
| Onyx — [connector models](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/models.py), [indexing models](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/indexing/models.py), [access documentation](https://docs.onyx.app/security/architecture/access_controls) | Sections carry text, heading and link; indexed chunks carry document, tenant/access and source-link metadata | Keep source links and permission context distinct from content/relevance; bounded, materialized indexing representation | No search-engine migration or adoption of enterprise ACL implementation. Keep our existing server-owned authorization; foreign source metadata cannot grant access |

Our selected small schema, thresholds, source-quality policy and transactional rollout below are **design proposals inferred from this repository and baseline**, not claims that these projects implement our exact design.

## 5. Current code integration points

| Existing component | Actual behavior and implication |
| --- | --- |
| `backend/services/firecrawl_service.py` | Single-page and recursive requests ask for Markdown. Retain fetch/crawl behavior. Treat the returned Markdown as the source artifact, not original HTML |
| `backend/services/document_processing_service.py` | Extracts files, validates pages, stages chunks/embeddings, then promotes under quota/job/document/website locks. `Document.raw_text` holds normalized text. Extend this path later; no parallel lifecycle |
| `backend/services/page_quality.py` | Already rejects unsuccessful status, empty text and blocked/error/verification leads. Preserve its fail-closed guarantees; add explainable quality records, not a replacement that accepts everything |
| `backend/services/chunking_service.py` | Existing 650-token target/120 overlap, Markdown sections, h1/h2/heading metadata and synthetic prefixes. No persistent typed AST or semantic relationships. Its start/end token counters describe enriched chunk output, not exact immutable source offsets |
| `backend/services/coverage_manifest_service.py` | URL-path-based parent/sibling/category hints. These are not proof that a collection contains a product or that a review refers to one. Retain as explicitly heuristic metadata, not strong factual edges |
| `backend/database/models.py` | Mutable current `Document`, integer version, `Website.active_crawl_id`; chunks have lifecycle, crawl/job and embedding profile but no immutable document-version FK or structural-node links |
| `backend/database/resource_schema_v1.py`, `backend/services/resource_catalog.py` | Tenant-qualified resource keys, version/crawl anchors, revision triggers. Projection is explicit, caller-transaction-owned and capped at 256 documents; metadata identity is not answer evidence. Do not edit the frozen schema definition |
| `backend/services/knowledge_scope.py`, `backend/services/retrieval_contracts.py` | Authoritative READY/completed, tenant/bot, active crawl/version, document/source and profile filtering. Future structural reads must intersect this boundary; edges cannot expand it |

## 6. Chosen architecture and rejected alternatives

Choose a **versioned structural sidecar in existing PostgreSQL**, with small typed relational keys/edges and schema-validated JSONB for format-specific attributes/provenance. Existing `Document`, `Chunk`, resource catalog, jobs, storage and embedding pipeline remain primary. Retain original source artifacts and a provider-neutral normalized structure; only bounded leaf/evidence chunks receive embeddings. Docling is an adapter, never the authorization or business-semantics engine.

| Storage option | Evaluation | Decision |
| --- | --- | --- |
| A. Separate relational table for every node/relation type | Strong typing, but numerous joins/migrations and type proliferation | Reject for initial implementation |
| B. Typed edge table for everything, including tree adjacency | Good cross-document integrity, but duplicates tree order/parentage and requires unnecessary traversal | Use only for non-tree semantic links |
| C. Entire structure in metadata JSON with a few indexes | Easy staging, but weak endpoint FKs, expensive graph slicing and poor cross-version checks | Keep serialized audit artifact, not authoritative relationship store |
| D. Hybrid: normalized version/revision/node/edge/mapping rows + bounded JSONB | Composite tenant FKs, indexed bounded reads, additive rollout and easy provenance inspection | **Selected** |
| Graph DB/framework-owned index | New consistency/security/deployment burden with no demonstrated requirement | Reject |

## 7. Normalized structural schema

Propose **five additive tables**, plus nullable linkage/pointer fields on existing tables. Names are proposals, not migrations. Separate a source version from a parser/chunker revision: reprocessing identical source must not invent a new crawl or overwrite source history.

| Table | Minimum fields / constraints |
| --- | --- |
| `document_versions` | `id`, non-null `organization_id, bot_id, document_id`; `source_version` (existing Document.version), `crawl_id/website_id` nullable, `source_identity`, canonical/source URL, immutable `source_text` or owned source-object reference, MIME/format, `source_sha256`, `captured_at`, fidelity level. Composite FK to current document identity. Unique tenant/document/source-version/crawl identity; nullable crawl uniqueness handled explicitly, not default NULL semantics. Hash mismatch for the same source version is an integrity conflict, not silent overwrite |
| `document_structure_revisions` | `id`, tenant/document/version FK, `build_fingerprint`, schema/parser/normalizer/chunker versions and configuration hashes, `ingestion_job_id`, `state`, quality assessment, expected/actual counts, source/normalized/serialization hashes, optional owned audit artifact reference, created/completed timestamps. Unique `(document_version_id, build_fingerprint)`; immutable content once validated |
| `structural_nodes` | `id`, tenant/document/version/revision FKs, stable `node_key`, `parent_id`, `preorder`, optional leaf reading order, `node_type`, `semantic_role`, exact `text` for leaves, normalized display text if different, `source_spans`, validated `attributes`, `provenance`, quality annotation, content hash. Unique `(revision_id,node_key)` and `(revision_id,preorder)` |
| `structural_edges` | `id`, shared non-null org/bot, full version-pinned `from_node` and `to_node` composite FKs, relation kind, field/role if applicable, evidence spans/anchor-node IDs, method/version, confidence or deterministic basis, validation state. Unique endpoints/kind/evidence key. Endpoint type compatibility checked before READY |
| `chunk_structural_nodes` | Tenant/document/version/revision + existing `chunk_id` + `node_id`, ordinal, node-local source slice and output slice, role `body/heading/header/qualifier`, optional bundle key/part metadata. Composite FKs on both sides; exact coverage manifest. Many-to-many because chunks may combine nodes or split a long node |

Existing `Document` gains nullable `active_structure_revision_id`; existing `Chunk` gains nullable `document_version_id`, `structure_revision_id` and compact schema/policy metadata. Legacy NULLs remain valid only in the explicit legacy read path. Add the necessary tenant-qualified unique keys on Chunk and the new tables before composite FKs. A document pointer must reference a revision belonging to **that document and tenant**, not any revision ID.

Version rows archive source; revisions represent processing. Revision state is `staging → validated → active → superseded` or `failed/cancelled`; source-quality quarantine is a separate decision, not fake success. Nodes/edges inherit readiness from their immutable revision and current source eligibility instead of duplicating mutable READY flags on every node. Chunk readiness still uses the existing lifecycle. Old source and revision rows remain nonservable after supersession.

### Node vocabulary

Physical types: `document`, `section`, `heading`, `paragraph`, `list`, `list_item`, `table`, `table_row`, `table_cell`, `group`, `link`, `media`. Closed semantic roles annotate these: `title`, `faq_question`, `faq_answer`, `review`, `product_card`, `price_block`, `directions`, `ingredients`, `timeline_stage`, `warning`, `navigation`, `furniture`, `unknown`. Products are one domain role, not a hardcoded catalog.

This avoids a separate physical class/table for every business field. A timeline stage is a group with its original heading, body and qualifiers; a review is a group of source-attributed text and its explicit link, not a product fact. A list is an ordered container whose membership survives independently of its compact rendered chunk.

Source spans use half-open offsets against the immutable source artifact with an explicit coordinate system (`utf8_bytes`, parser item reference, or page+bbox). Never reinterpret the old enriched-token offsets as source offsets. Unknown locations are marked unavailable; no fabricated PDF coordinates for Markdown. Tree containers need not duplicate all descendant text. Original and normalized text are tied by mapping spans and hashes.

IDs are tenant/version/revision scoped; stable node keys derive from parser path, occurrence/reading order and content hash, not text hash alone. Identical repeated text must not collapse distinct nodes or tenants. Reparse with a different policy produces a new revision, not mutated node meaning.

## 8. Relationship schema and extraction policy

Store tree parentage once; derive `PARENT_OF/CHILD_OF` from `parent_id` and `NEXT/PREVIOUS` from bounded ordered siblings/leaves. Do not store redundant reverse edges. Enforce same-revision parent FKs, one root and acyclicity: parent preorder is strictly smaller than child preorder, validated against the referenced parent's actual order; a composite FK/check or bounded constraint trigger must enforce that invariant. Semantic edges are not necessarily a DAG.

Small edge vocabulary:

- `CONTAINS`: collection/group explicitly contains a linked resource/card, not merely a shared URL prefix.
- `REFERS_TO`: review/citation refers to an explicitly linked resource.
- `VARIANT_OF`: only explicit variant identity/structured relation; similar names or sibling paths are insufficient.
- `DESCRIBES` with typed field: price, directions, ingredients, reviews, timeline, etc. Equivalent to the proposed separate `PRICE_FOR/DIRECTIONS_FOR/INGREDIENTS_FOR/REVIEW_FOR/TIMELINE_FOR` types without duplicating the schema.
- `HEADING_FOR` and `QA_PAIR` where tree structure alone is insufficient to express a proven association.

Targets are **version-pinned structural nodes**, typically another document's root or an identified resource block. Existing resource IDs may be resolved through authorized catalog mappings for navigation, but are not an alternative permission-bearing endpoint. Store unresolved URL targets in link-node attributes with `resolution=unresolved/ambiguous`; no fake target row and no automatic fetch. A target must be uniquely matched by approved canonical URL/explicit identity within the same authorized org/bot/source scope. A broken or unknown link stays unknown.

| Evidence source | Allowed deterministic conclusion | Prohibited inference |
| --- | --- | --- |
| Explicit AST/DOM parent, heading level, list/table membership | Tree/order/header-body/list membership | Heading text alone authorizes arbitrary later body mentions |
| Review block's explicit View Product anchor | That review refers to uniquely matching product document/root | Every nearby product link is the review subject |
| Product card link inside main collection content | Collection contains linked card/resource | Footer/navigation recommendation proves catalog membership/variant identity |
| Price label/table header + amount in same block | Preserve label, role, amount, currency/unit and conditions with source spans | Cheapest/latest amount is single-bottle price; crossed-out meaning without source markup |
| Serving label + quantity/unit/frequency clause | Preserve original text and explicit association | Derive bottle duration from guessed serving size or normalize away ranges |
| Timeline heading/body in one structural group | Ordered stage and qualifier association | A heading promises an outcome; individual results are guaranteed |

Initial Phase 4 uses **zero generative/model-inferred relationship calls**. Docling's local layout/OCR models, when applicable, are extraction models and not free-form LLM reasoning; record their provenance/confidence separately. No VLM, external OCR API or downloaded model at request time. Later optional inference would require separate approval, bounded inputs/calls, typed outputs, evidence spans and quarantine pending validation; confidence cannot bypass endpoint authorization or turn suggestions into facts.

## 9. Authorization, source safety and cache invariants

1. Every new row has non-null org/bot/document/version ownership; missing/mismatched ownership fails closed. IDs supplied by source text or a model never populate ownership columns.
2. Composite FKs enforce tenant/bot consistency at write time. They **do not** prove present read authorization. Resolve both endpoints through existing `HardKnowledgeScope` and `knowledge_scope` predicates before exposing even names/links.
3. Current document READY/completed, active website/crawl/version and source restrictions must hold for **both** endpoints. Target version/revision must still be current. Upload and website paths retain their distinct rules; a link cannot resurrect superseded/deleted knowledge.
4. Structural facts do not have embeddings by themselves. Evidence admitted through a chunk must satisfy the request's provider/model/version/dimension compatibility; structural traversal may not bypass this by reading raw node text directly. Require authorized eligible chunk mappings for both evidence endpoints, or treat target only as an undisclosed unresolved reference.
5. Current hard permitted-document/source sets are ceilings. Cross-document relationships are relevance data, not authority to widen those sets. Future ACL restrictions are intersected, never copied from the more permissive endpoint.
6. Sanitize metadata by an explicit allowlist. Saved crawler metadata includes unrelated site verification/checkout fields; none belongs in evidence, telemetry or a committed fixture. Preserve private source artifacts under existing owned storage controls, not public URLs.
7. Treat all document text, HTML and links as untrusted data. Disable script/external-resource execution, XML external entities and parser network egress; cap decompression, nesting, CPU and memory. Never run stored instructions. Keep factual source text separate from runtime prompts.
8. Preserve original link value privately plus a validated HTTP(S) source/navigation form. Reject unsafe schemes/embedded credentials; do not truncate into a different URL. Fragments remain anchors, not document identity; retain meaningful query parameters/variants. Reuse current canonical-origin validation, not an unreviewed new URL normalizer.
9. Shadow revisions cannot affect cache identity or answers. Before any future active representation change, include the active structural revision/policy in the corpus/cache generation identity and revalidate current eligibility on cached reads. Source hash alone is insufficient when the same source is re-chunked. This is a required lifecycle compatibility step, not RRF/query tuning.

## 10. Ingestion pipeline and transaction boundaries

Use the existing durable job and staging lifecycle; the following stages are proposed additions within it, not a second ingestion architecture:

1. **Acquire source** via current approved crawl/upload path, or explicitly authorized owned saved snapshot. Apply existing SSRF, MIME/size and quota checks. No relation-triggered crawl.
2. **Capture immutable source version** and hash; run existing page-status/lead checks plus preliminary quality annotation. Inspect metadata without blindly copying it to evidence.
3. **Extract structure** outside DB locks. Markdown/TXT uses deterministic AST/line parsing; HTML if genuinely available uses inert DOM parsing. PDF/DOCX uses the isolated Docling adapter with pinned settings/models. No OCR on already textual Markdown. Preserve raw links independently if adapter serialization loses them.
4. **Normalize and validate** our structure, exact source spans, headings, lists, tables, semantic role evidence and post-parse block quality. An adapter failure is explicit; do not silently label plain-text fallback as high-fidelity.
5. **Generate local relationships and bounded chunk specifications**. Resolve cross-document links against the authorized catalog only; unresolved relations remain stored as links. Build pending resource descriptors, but do not publish new catalog entries before source activation.
6. **Stage structure and chunks** in bounded owned batches; heartbeats/cancellation remain active. Shadow mode stops after structure/spec validation without writing chunk rows or calling embeddings. Active mode uses existing embedding batches/profile and FTS on staged Chunk content, with exact embedding-input hashes.
7. **Validate completion**: counts, hashes, source coverage, endpoint integrity, quality policy, all vectors/profile, token caps and quota. Any failure preserves the prior active corpus.
8. **Atomic promotion**: reuse the current lock order (quota/affected organization before website/crawl, job, sorted documents). Recheck source/current revision compare-and-swap and cancellation. Mark new chunk set READY, old set stale; switch structural pointers, source/crawl state and catalog projection/revision together. No fetch, parsing or embedding inside this transaction.

The current projector reads READY document anchors and caps a batch at 256, so pending projection cannot simply be invoked on unready sources. Initial rollout keeps an activation group at or below that cap and runs projection **after in-transaction READY transition but before commit**. Large crawl support must use pre-staged catalog projection plus atomic publication or an explicitly validated bounded grouping policy; never publish partial inconsistent catalogs or secretly bypass the cap. The existing normal-crawl atomicity must not be weakened to accommodate the new feature.

Two concurrent jobs for one source cannot both activate: compare expected current source/revision under lock; losing job is superseded/cancelled and cleans only its own staging. Source changes while a shadow build runs invalidate that build's activation eligibility. Cross-document targets that change are unresolved until explicitly revalidated; never retarget by a now-similar title.

## 11. Structure-aware chunk rules

Proposed initial policy `structure-v1`, independently versioned from the parser. Count **final serialized embedding input**, including prefixes, with the existing local tokenizer; it is an engineering token estimate, not a claim to exactly match Gemini billing tokens.

| Parameter/rule | Proposed bound |
| --- | --- |
| Target | 450 tokens; ordinary merge range roughly 250–650 |
| Hard maximum | 800 tokens including inherited title/heading/table header/qualifier text; also enforce existing provider byte/token constraints |
| Prose overlap | One complete sentence up to 60 tokens, same section/subject only; no automatic overlap across typed units |
| Metadata prefix budget | At most 80 tokens, counted in cap; full heading path stored as metadata even when a display prefix cannot fit |
| Parents | Store structure/reference only; no automatic parent embeddings or repeated full-subtree text |
| Neighbors | Store order/reference only; no new retrieval expansion. Future requests require hop/node/token limits and hard scope |

Merge adjacent small paragraphs only if document version, section, subject/resource attribution, role and quality boundary agree. Never merge separate reviews/products, unrelated FAQ pairs, price roles/variants, warning-versus-promise, or distinct timeline stages merely to fill a size target. Small complete units may remain small.

- **Lists:** preserve container and every item. Prefer one chunk for a complete bounded list plus identity/label. Store `source_block_complete` and item count; distinguish explicit full-list claims, highlights/cards and unknown scope. Completeness of the source block does not prove the list exhausts all real-world ingredients.
- **Long lists/tables:** split only at item/row boundaries; retain group ID, original item/row indices and total part count. Repeat actual headers/qualifiers as mapped context, not invented facts. A long individual item/cell is split into bounded exact spans with continuation markers and completeness metadata; never truncate it. Reconstruction must recover every source span even if later retrieval does not load every part.
- **Tables:** keep row/column indices, header cells, row/column spans and units; render a bounded row group with header mapping. Missing or ambiguous headers stay unknown. Very wide rows retain full cell content through mapped fragments rather than quietly dropping the header's meaning.
- **Reviews:** keep review text, attribution/qualification and its exact product-link evidence together where possible. Link metadata retains the complete target even if text splits.
- **Timeline:** one stage is a group of heading, associated body, qualification and order. If oversized, fragments retain stage ID and qualifier references. Do not attach a following stage's heading to the preceding body as its label.
- **Quantity/commercial blocks:** keep values with their subject, label, denominator, units, frequency and conditions. Store amounts as decimal strings plus source text; unknown currency/role remains unknown. No computed price difference, dosage equivalence or inferred daily duration during ingestion.
- **FAQ:** retain question and corresponding answer as a unit; split only over the hard cap with explicit pair/part identity. A heading with no body is not enough answer evidence.
- **Links:** preserve href separately and round-trip source spans. Render only complete escaped link tokens; an oversized URL stays in validated source metadata rather than broken Markdown. Exact source anchors are retained.

Expose the existing compatible `TextChunk` contract to storage. Newly added structural metadata is namespaced and cannot overwrite authoritative IDs/profile/lifecycle fields. Existing h1/h2/heading and source fields remain available to legacy consumers. Changing the leaf text requires new embeddings; adding sidecar metadata alone does not.

## 12. Source-quality representation

Record document and block quality separately: `usable`, `mixed`, `blocked`, `interstitial`, `navigation_only`, `error`, `unknown`, plus detector version, reason codes, exact bounded evidence spans, extraction confidence and disposition `accept/quarantine/manual_review`.

Preserve existing fail-closed HTTP/lead rejection. A cookie banner alone does not prove a whole page unusable; a later discussion of blocked accounts does not make a block page. Use response status, title/lead, presence of substantive main content and parser structure jointly. Proven boilerplate may be excluded from embedding while retained in source/structure audit. Ambiguous mixed pages require review; no silent domain exclusion or fabricated successful ingestion.

Document 12 is an **evaluation fixture**, never a runtime condition. Its existing READY state is not modified by this design. A future offline replay should explain a suspicious title and distinguish meaningful retained blocks without retroactively rewriting the frozen corpus. Any later quarantine/activation decision is explicit, page-specific and auditable.

## 13. Saved-source feasibility, migration and backfill

Read-only inspection of local `SOURCE_PRODUCTION_SNAPSHOT.json` (an already saved file, **no production connection**) found:

- 23/23 website documents have nonempty `raw_text`, Markdown headings and Markdown links.
- Total source: **761,385 characters / 763,997 UTF-8 bytes / 201,377 cl100k_base tokens**.
- No raw HTML field or HTML metadata payload; no file/object source references for these website documents.
- Existing 1,092 chunk texts total **212,061 tokens**, median **116**, range **7–719**. These are counts of stored strings, not generated new chunks or provider measurements.

**Yes: first structural validation can reprocess the saved Markdown without recrawling.** It can recover explicit headings, lists, link targets, textual tables and source adjacency still present. **No: it cannot recover original DOM grouping, CSS strike-through, JSON-LD, rendered layout, omitted accordions or missing HTML tables.** Mark fidelity `extracted_markdown`; do not claim original-web fidelity or infer missing price roles. Existing saved production IDs must be remapped by the already authorized source-to-development mapping, never used to reconnect or write production.

Future migration/backfill sequence:

1. Add nullable linkage and new tables/indexes only via a new migration; do not alter historical migrations/frozen catalog schema. Validate PostgreSQL constraints/index plans in the disposable harness, not an application DB.
2. Deploy code with all structural flags off; legacy behavior and data unchanged.
3. Build immutable source-version snapshots and shadow revisions for an explicitly selected development org/bot. Keyset pagination, one document at a time, max 32 per task slice and resumable idempotency; do not load all chunk vectors. Source hash and tenant mapping are checked before processing.
4. First validate structure/specs offline with **zero embeddings**. Frozen REAL_CORPUS_V1 and GOLD stay unchanged. Put subsequent experimental chunks in separately named disposable/clone fixtures with scoped identity, not over the baseline.
5. After structural gates and explicit authorization, canary new representations with existing profile; activate only after complete vectors, scope/catalog/cache compatibility and rollback prerequisites are verified.
6. No startup/chat auto-backfill, mass production recrawl or automatic fleet-wide activation. Reuse owned saved sources; unavailable source artifacts are `source_missing`, not reconstructed by concatenating lossy old chunks.

## 14. Feature flags and rollout

Proposed server-controlled flags, **not created or enabled now**:

- `STRUCTURAL_INGESTION_MODE=off|shadow|active`, default off, with an explicit org/bot allowlist.
- `STRUCTURAL_READ_MODE=legacy|active_revision`, default legacy. Initially controls only validated chunk/node metadata and lifecycle selection, not graph expansion.
- `STRUCTURAL_PARSER_POLICY` and `STRUCTURAL_CHUNK_POLICY`: version identifiers in build hashes, not arbitrary unvalidated configuration.
- No `infer_relationships_with_llm` switch in v1. Do not add client-controlled overrides.

Off means no added ingestion/read work. Shadow does not change answers, chunks, embeddings, catalog projection, caches or active pointers. Active writes/read compatibility must roll out together on supported workers/API replicas before any activation. No mixing different representations of one document in one evidence bundle. Legacy NULL mappings return ordinary legacy evidence with `structure_unavailable`, never a guessed hierarchy.

## 15. Observability and bounded reads

Record per job/source/revision: source format/fidelity/hash; parser/config/schema versions; parse/normalize/chunk/embed/activation timings; peak memory; node/edge/type counts; unresolved/ambiguous relation counts; source-span/list/link coverage; quality reasons; chunk token histograms; oversize/split counts; embedding input hashes/profile/count/cost; expected versus published counts; rollback/supersession reason. Log IDs, counts and safe categories, not raw customer text, tokens, private URLs or metadata dumps.

New indexes start with org/bot: versions `(org,bot,document,source_version)`; revisions `(org,bot,document,state)`; nodes `(org,bot,revision,parent,preorder)` and unique node keys; edges `(org,bot,from_revision,from_node,kind)` and reverse endpoint index; mappings `(org,bot,chunk,ordinal)` and `(org,bot,revision,node)`. Do not add broad JSON GIN indexes without a demonstrated query. Batched hydration replaces N+1 reads; no whole-tree scan per chat.

Future Phase 7 interface can fetch at most 48 seed chunks' mappings in one batch and explicitly bounded neighbors/parents, but Phase 4 does not enable traversal. An over-limit tree is a visible budget outcome, not silent partial evidence called complete.

## 16. Failure handling

| Failure | Required behavior |
| --- | --- |
| Parse/OCR timeout, memory limit or unsafe archive | Fail owned revision; retain old active corpus; safe typed error and cancellation cleanup |
| Adapter drops links/list items/locations | Fidelity/coverage gate fails; no automatic high-fidelity activation; raw source retained |
| Unknown role or ambiguous target | Preserve unclassified source/link and explicit uncertainty; never guess a relationship |
| Embedding partial failure/profile mismatch | No promotion; bounded existing retry policy only; no provider switch or mixed vectors |
| Quota exceeded at promotion | No partial activation; preserve current knowledge and existing reservations/accounting rules |
| Concurrent job/source/catalog change | Compare-and-swap fails; revalidation/new job required, not last-writer-wins |
| DB rollback/worker crash | Idempotent job/revision ownership permits resume; remove only owned unactivated staging after existing retention checks |
| Missing target permission/version | Hide relation target/evidence, record denied/stale category; no fallback through a different tenant/source |

All new readers return typed `unavailable/stale/denied` states; they do not convert technical failures into business absence claims. No wide exception handler that quietly swaps to lossy extraction while reporting success.

## 17. Performance and cost envelope

Estimates to validate, not observed Docling benchmarks:

- Deterministic markup normalization is approximately O(source bytes + nodes + links), with indexed/batched URL resolution, not all-pairs document comparisons. OCR/layout costs scale with pages/pixels and need separate worker limits.
- Initial conservative admission caps: existing upload size limit retained; 10,000 nodes/20,000 explicit edges per document, depth 32, 64 candidate semantic links per block, 256 URL resolutions per batch. Limits produce visible partial/quarantine states, never silently complete documents. Streaming/page-batched processing avoids a whole-corpus object graph.
- Proposed worker envelopes for validation: Markdown/text 1 CPU, 256 MiB working-memory budget, 30 s/document; PDF/DOCX isolated worker up to 2 CPU/4 GiB, 180 s/100-page slice. These are containment targets, not guaranteed sufficient capacities; measure cold/warm model load and adjust only by explicit approval. No model auto-download during a job.
- At an illustrative 150–500 normalized nodes/page, 23 pages imply ~3,450–11,500 nodes; 10,000 pages ~1.5–5 million. Semantic edges may be ~0.1–0.5 nodes; chunk mappings scale with rendered spans. These are scenarios, not counts extracted in this task. Parent rows hold references, not repeated full text.
- Assuming roughly 0.6–1.2 KiB per node row plus 1–2x row bytes for indexes/edges/mappings, 23-page structural overhead is roughly **4–40 MiB**; million-node corpora require measured GB-scale budgeting. Raw immutable snapshot duplication, TOAST, WAL, audit IR and retained revisions are additional. Do not call logical upload quota physical DB storage.
- Initial leaf-chunk expectation is broad: roughly **500–1,300** on this 201k-token source, depending on atomic units. This is not a promised reduction from 1,092. Only measured generated specs establish counts. Parent/edge rows create **no embeddings**; shadow creates none at all.
- Canary cost review gates: embedding input tokens >1.3x stored baseline (**275,679 tokens**) or chunks >1.5x (**1,638**) require explanation/approval, not trimming evidence to manufacture a pass. At 768 float32 values, raw vector payload is 3,072 bytes/chunk before DB/index overhead; existing vectors alone ~3.20 MiB. Profile/model remains unchanged.
- Extra generative LLM calls: **0**. Reuse a vector only when the exact serialized input hash and full provider/model/version/dimension profile match; source-text equality alone is insufficient.
- Off/shadow request-path cost: zero new structural reads. Active compatibility should use at most one batched metadata read for the selected chunk pool; target <5 ms local DB execution and no material (>5%) retrieval p95 regression on a same-host synthetic comparison, to be measured, not asserted. No graph traversal or reranking introduced here.

## 18. Structural evaluation metrics

Create a separate versioned **STRUCTURAL_GOLD_V1**, drawn from saved source spans plus synthetic non-commerce documents. Do not edit, repurpose or leak answer GOLD into runtime extraction. Record unavailable source structure separately from extraction failures.

| Metric | Definition / proposed first gate |
| --- | --- |
| Heading/body retention | Correct annotated heading→body pairs retained / available gold pairs; 100% critical fixtures, >=98% broader held-out sample |
| Full-list retention | Ordered gold item coverage and list association; 100% critical lists, zero substitution of highlights for a full list |
| Review→product accuracy | Correct supported resolved edges / emitted edges; 100% precision critical set, >=95% recall when anchors survive source; no guessed edge for missing links |
| Collection→product accuracy | Same precision/recall evaluation, with navigation/cross-sell negatives separately labeled |
| Price-role preservation | Exact amount/currency/role/conditions/subject tuples; 100% critical annotated tuples, zero promotion of unknown roles |
| Quantity/unit preservation | Exact subject/value/range/unit/frequency/qualifier association; 100% critical fixtures |
| Timeline preservation | Every stage heading/body/order/qualification retained; 100% critical timelines, zero body shifted to adjacent stage |
| Canonical links | 100% retained safe original targets/anchors after round-trip; zero fabricated/truncated links |
| Provenance | 100% answerable leaf content has an exact source slice or honest parser/page/item provenance; no invented coordinates |
| Source-quality detection | All blocked/error fixtures flagged; zero whole-domain suppression; mixed/content-about-blocking negatives not blanket rejected; report confusion matrix and abstentions |
| Serialization | Reconstruct source-visible ordered evidence from mapped parts without missing list/table/qualifier spans; hard cap 800 on every rendered chunk |
| Isolation/lifecycle | Zero foreign org/bot/ACL/source/stale/crawl/profile results, including after target update and cache hit |

Also measure node/edge count, mapping coverage, deterministic replay hash equality, unreadable/unknown rates, CPU/memory and embedding budget. Report precision and recall separately; dropping every uncertain edge is not a successful relationship extractor.

## 19. REAL_CORPUS_V1 and non-domain acceptance plan

No tests in this section are executed by this design task.

1. Keep frozen 90-case questions, expected resources, answers and grades intact; create separately named Phase 4 evaluation outputs on a clone/owned test fixture. Before any future live calls, require separate quota/credential/run authorization. Offline structure gates come first.
2. Critical source fixtures: full Collagen Complex source list, all Joint Support ingredients, MyCovital four-mushroom list; anti-aging review anchors (53 and 85); chocolate timeline stage/body/qualifier boundaries (69); Resveratrol price-role labels (27); subscription/day role association witness (64); scoop/capsule/gram/frequency clauses (40/57/61); safe canonical links; mixed blocked-page witness. Source document IDs may occur in tests, never runtime rules.
3. Add held-out hotels (breakfast/check-in/cancellation), plans (storage/renewal), courses (syllabus/certificate), legal numbered lists, multi-page tables and generic FAQ/reviews. Include unlabeled prices, shared footer links, repeated names, variants, malformed Markdown, enormous lists, table-cell spans and malicious embedded instructions.
4. Exercise version churn, concurrent activation/cancellation/quota failures, orphan targets, same-name foreign tenant, cross-bot links, restricted sources, mismatched profiles and rollback. Real PostgreSQL constraints/query plans must be tested later with an explicitly disposable DB; SQLite-only tests are insufficient.
5. Run current offline canonical regression suite plus new structure tests. First compare exact source→nodes→chunk-spec retention with no provider calls. Only after that compare unchanged retrieval/evidence/generation on separately authorized canary data.

**Expected Phase 4-only impact:** better observable list/stage/link/role/provenance retention and potentially more cohesive bounded leaf chunks; measurable source-quality classification. Cases 17/18/27/40/50/53/56/57/58/61/62/67/69/75 may benefit indirectly, but are **not promised PASS** because their proven losses often occurred downstream. Case 53's durable edge needs Phase 7 consumption to guarantee attribution; 69's valid reviewer can still reject a stage.

**Not expected from Phase 4 alone:** unnecessary clarification and comparison/goal/filter semantics (8/35/40/43/52/54/57/60/61/63/65/67/71/74/90: Phase 5), document-cap/ranking losses (17/48/75/79: Phase 6), reviewer/context expansion and preservation (Phases 7–8), generation role error 64 and broken final citation wording (Phase 8 acceptance/any separately approved generation repair). Do not relabel these as ingestion defects to claim improvement.

## 20. Implementation sequence and module boundaries

Each item is future work after approval; no implementation starts here.

1. **Contracts and fixtures:** add provider-neutral structural DTOs/JSON schema and STRUCTURAL_GOLD_V1; validate exact spans, vocabulary, bounds and source fidelity. Pure offline code first.
2. **Schema and repository:** additive version/revision/node/edge/mapping tables and scoped repositories; disposable PostgreSQL FK/concurrency/rollback/query-plan tests. No application migration during development validation.
3. **Deterministic source adapters:** saved Markdown/TXT and inert HTML-if-available; role/anchor extraction with explicit uncertainty. Prove no-recrawl replay and all critical structure gates.
4. **Docling adapter:** dependency/license/model pinning and sandboxed PDF/DOCX conversion; adapter conformance, provenance and fallback tests. Keep large parsing dependencies out of API request paths.
5. **Chunk serializer:** bounded list/table/FAQ/review/timeline rules; compatible TextChunk output and complete chunk→node mappings. Dry-run token/cost report before embeddings.
6. **Existing-worker shadow hook:** source capture, staging, cancellation and metrics only; no active catalog/chunk/embedding changes.
7. **Activation compatibility:** existing quota/locks, version-pinned metadata reads, catalog atomicity, cache generation and rollback; adversarial/concurrent acceptance before enabling canary writes.
8. **Authorized canary evaluation:** isolated clone, existing embedding profile, then frozen 90-case evaluation under unchanged query/ranking/reviewer/generation. Publish structural and answer metrics separately; rollout requires explicit approval.

Likely future modules: `structural_document` (DTOs), `structural_extractors` (adapters), `structural_relationships` (typed deterministic edges), `structural_chunking` (serializer), `structural_repository` (scoped persistence), new migration/schema definition, and small hooks in existing document processing. These are proposed boundaries, not files created now. Keep `knowledge_scope` as the single authorization authority; do not copy divergent predicates into every adapter.

## 21. Rollback strategy

Schema additions stay in place on initial rollback; do not drop populated tables or downgrade shared extensions. Disable shadow/active writes first and drain/cancel owned jobs. Off/shadow needs only flag rollback because active data never changed.

For activated **same-source-version** representation changes, retain the previous exact chunk/vector set and revision for a time-limited approved rollback window. Under the same promotion locks, recheck current source/permissions, atomically restore the prior representation pointer and READY/stale flags, update catalog/cache generation and audit the action. Never restore deleted/disabled data or a previous crawl merely because a revision exists.

If source/crawl changed, old-source chunks are **not a safe rollback target**. Keep the current source, run the legacy serializer in a separately authorized staging job and promote only after normal checks, or retain current compatible chunks while disabling structural reads. Application code rollback must be tested against additive columns and current chunk format. Cleanup later removes only unreferenced owned revisions under retention policy; no broad recursive or cross-tenant delete.

## 22. Risks, open decisions and completion record

- **Missing original structure:** saved Markdown cannot recover erased DOM/layout/commercial styling. First validation is explicitly Markdown-fidelity; a richer future fetch is a separate approval, not a hidden requirement to recrawl.
- **Parser confidence and local model footprint:** Docling version/model/license/CPU limits need pinned conformance tests; no performance claim is established here.
- **Semantic labels:** full list versus highlights, product cards versus navigation and price roles may be ambiguous. Preserve source + unknown/abstention; avoid customer-specific templates disguised as generic logic.
- **Projection size:** initial activation cap and eventual large-crawl staging/publication protocol must be proven before enabling structural writes for large crawls. Existing atomicity cannot be relaxed.
- **Version/storage growth:** immutable sources/revisions and retained rollback vectors need measured retention/budget policy. Design estimates are not production capacity sizing.
- **Safety versus recall:** quarantine can hide useful mixed content; require explicit reasons, block-level evidence and false-positive tests.
- **Downstream consumption:** structural metadata alone does not ensure selection/reviewer/generation use it. Separate phase gates prevent overstating end-to-end fixes.
- **Legal/security review:** before dependency integration, review parser/model licenses, vulnerability exposure and artifact integrity. No wholesale framework or enterprise-permission code adoption.

Completion: Phase 3.7 checkpoint committed locally; this design is a new uncommitted documentation file. Runtime, ingestion, dependency files, corpus/GOLD, production and Railway remain unchanged during design. No migration, provider call, live benchmark, crawl, chunk/embedding regeneration, Phase 4 implementation, push or deployment occurred.

**PHASE 3.7 CHECKPOINT — COMMITTED**

**PHASE 4.0 STRUCTURAL INGESTION DESIGN — COMPLETE**
