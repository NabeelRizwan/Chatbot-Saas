# Phase L.2 — Conversational Field Retrieval Report

Date: 2026-09-01  
Controlled bot: `674 — WOWMD Joint Supplements Assistant`  
Controlled corpus after validation: **10 READY documents / 573 READY chunks**  
Corpus mutations: **none** — no crawl, re-ingest, or stored-product edits were performed.

## 1. Exact pre-change failures

The mandatory baseline was captured through the real dashboard and a fresh real external widget session before Phase L.2 runtime edits.

### Dashboard baseline

Question:

> What are the ingredients of turmeric boost and how soon willl i see results?

Answer:

> Individual results for Turmeric Boost can vary, but some users may notice support for joint comfort or digestive balance within 4–8 weeks of consistent daily use, while others might need more time. The ingredients for Turmeric Boost are not available in the information I have.

- Browser wall latency: **26,317 ms**
- Persisted backend latency: **19,827 ms**
- Mode: factual
- Requested fields detected: `ingredients` only; `results_timeframe` was missed
- Retrieval: 6 chunks across 3 documents
- Failure: the results FAQ was found, but the complete ingredients section in the same document was not selected. Unrelated Sea Essence and Collagen content occupied context.

### Widget baseline — one continuous fresh session

1. `what turmeric products do you have`
   - Answer named Turmeric Boost and Turmeric Gummies, but also incorrectly presented Joint Support as a matching turmeric product.
   - Browser/backend latency: **27,354 / 21,944 ms**
   - Retrieval: 16 chunks across all 10 documents.
2. `wht ingredient of turmeric boost`
   - Answer said the ingredient list was unavailable.
   - Browser/backend latency: **34,930 / 29,372 ms**
   - Retrieval: 6 chunks across 2 documents; the complete Turmeric Boost ingredient section was absent.
3. `how much is it`
   - Answer said Turmeric Boost pricing was unavailable.
   - Browser/backend latency: **22,424 / 16,658 ms**
   - The older resolver produced `how much is wht ingredient of turmeric boost`; no requested `price` field was extracted.

The baseline therefore reproduced all three known failures: incomplete multi-field coverage, incomplete ingredient evidence, and failed same-chat price retrieval.

## 2. Why existing knowledge was sufficient

No knowledge refresh was needed:

- Turmeric Boost document `5129` already held the complete ingredient list in chunk `9164`.
- Its results timeframe was already present in chunk `9166`.
- Its customer-facing one-time and subscription prices were already in primary product content, including chunk `9163`.
- Turmeric Gummies document `5130` already held a reliable stored `og:price:amount` value and currency in document metadata.
- Each fact belonged to a tenant-scoped READY document with a canonical product URL.

The failures were query interpretation, evidence allocation, list completeness, and structured-evidence problems—not missing data.

## 3. Query-contract architecture

`services/query_contract.py` now creates one generic `QueryContract` for every turn. It carries:

- original, normalized, and resolved query
- intent and retrieval mode
- independently requested fields
- include/exclude constraints
- comparison entities and catalog scope
- conversation references
- resolved subject, document ID, and confidence
- ambiguity status and clarification prompt
- a stable cache fragment

The contract is created before caching and retrieval. Existing vector + lexical + RRF, document-first selection, breadth allocation, and the Generate → Critique → conditional Verify → Polish pipeline remain intact.

## 4. Conversational entity-resolution architecture

The resolver considers strong READY-document identity and recent dialogue context. It matches title, filename, canonical URL slug, structured title/name metadata, and conservative prior-turn subjects.

Explicit entity switches replace the active subject. Pronouns and natural references such as `it`, `its`, `this`, `that`, `they`, `them`, and ordinal/comparative references are resolved only when conversation evidence is sufficiently clear. Assistant text is a conservative fallback, not the primary source of identity, reducing entity poisoning.

The resolved document ID anchors factual retrieval before any corpus-wide supplemental retrieval. The cache identity includes the resolved contract, so identical text such as `how much is it` under different subjects cannot collide.

## 5. Ambiguity handling

A fresh field-only question with no identifiable subject returns a concise clarification before retrieval or generation. It does not choose the highest-scoring arbitrary document and is not cached as a product answer.

Verified live result:

> Which product or item would you like the ingredients for?

The stored turn recorded `retrieval_attempted=false`, `had_knowledge_hit=false`, and **532 ms** backend/UI-displayed latency.

## 6. Multi-field extraction

A generic, extensible field ontology centralizes natural-language aliases for price, ingredients/components, usage/directions, form, benefits/purpose, results timeframe, features, specifications, availability, duration, policy, eligibility, shipping, returns, amenities, syllabus, flavor, link, reviews, brand, SKU, and rating.

Minor typo normalization is generic. It corrects ordinary forms such as `wht`, `whts`, and repeated-letter mistakes without any corpus-specific product dictionary. Multiple fields are extracted independently; the dashboard acceptance contract correctly contained `['ingredients', 'results_timeframe']`.

## 7. Per-field evidence retrieval

For an identified entity, retrieval now allocates evidence separately for every requested field inside the resolved document. Field candidates receive structural and semantic evidence scores. Required-field evidence is selected before normal supplemental context receives any remaining budget.

The final dashboard multi-field turn selected 4 chunks from exactly 1 document:

- results-timeframe FAQ evidence
- complete ingredients evidence
- additional same-document supporting context

The final price follow-up selected 3 chunks from exactly 1 document and included one structured metadata evidence candidate.

## 8. Field completeness strategy

List-like fields are treated as sections rather than single keyword hits. The selector detects field headings, bullets/table-like content, list continuation, shared document/section identity, and safe adjacency. It gathers adjacent same-document evidence only when it plausibly continues the requested field.

Image galleries, navigation, unrelated siblings, and arbitrary neighbors do not qualify as completeness evidence. This is why the final ingredient response returned all four supported entries rather than only the first semantic match.

## 9. Structured metadata evidence architecture

Stored document metadata is inspected generically and tenant-locally—there is no answer-time website request. Supported paths include ordinary/nested price fields, OpenGraph price fields, schema-style `offers.price`, currency, availability, brand, SKU, rating, and product/page name.

Trusted values become synthetic evidence records tied to the original `Document`. They preserve:

- displayed value
- normalized numeric value where applicable
- currency
- field and label
- evidence origin
- document identity and canonical URL

They participate in the same evidence/context/source pipeline as text chunks. Internal metadata keys are never presented as customer-facing sources.

## 10. Price evidence architecture

Price recognition supports currency symbols and labeled stored metadata. Confidence depends on field structure and nearby semantic labels, not on arbitrary numbers.

The selector distinguishes one-time, subscription, regular/list, sale, bundle, and per-unit values when labels exist. Answer compaction preserves those labels. Shipping thresholds and refund-policy amounts are excluded as primary product prices when reliable primary/structured price evidence exists.

This specifically prevented `Free U.S. shipping over $60` from being reported as the Turmeric Gummies product price. Numeric normalization is retained for a later filter/latency phase, but Phase L.2 does not implement the full under/cheapest/range feature.

## 11. Evidence priority and noise handling

For exact entity + field turns, priority is:

1. trusted structured canonical field evidence
2. primary same-page field sections
3. structured tables/lists and safe continuations
4. relevant same-page FAQs
5. other same-document support
6. reviews/testimonials when explicitly requested

Image filenames/assets, navigation, generic marketing, recommendations, cross-sells, and unrelated sibling documents are down-ranked. Reviews and FAQs remain available for questions that actually request them.

Catalog discovery remains broad enough to find candidates, but final evidence is filtered to documents that match the catalog qualifier. This separates candidate discovery from final answer support.

## 12. Cache and history behavior

The existing Phase E history-aware cache remains. Its identity now also includes the query-contract fragment. It remains scoped by organization, bot, knowledge version, provider/model, history fingerprint, bot configuration, and resolved query/subject.

All live acceptance turns were cache misses, proving the final answers were produced through retrieval rather than replayed from earlier runs.

## 13. Field-coverage quality gate

After generation, the pipeline compares requested fields with:

- strong field evidence actually retrieved
- field coverage present in the draft answer

If retrieved support exists but the answer omits the field or incorrectly claims it is unavailable, one bounded pass through the existing verify mechanism corrects the draft. There is no retry loop. Mixed supported/missing-field answers retain supported claims and sources while honestly identifying genuine absence.

## 14. Source attribution behavior

Exact-entity answers use the canonical page belonging to the resolved document. Metadata-derived facts inherit that same source. Internal JSON keys and synthetic evidence implementation details are not exposed.

Verified canonical pages:

- [Turmeric Boost](https://www.wowmd.com/products/turmeric-boost)
- [Turmeric Gummies](https://www.wowmd.com/products/turmeric-gummies)

Sources are suppressed only when the final response contains no supporting business fact, such as the fresh ambiguity clarification. A missing field no longer suppresses sources for other grounded fields.

## 15. Dashboard final answers

Fresh dashboard conversation, exact wording:

**Turn 1**

> What are the ingredients of Turmeric Boost and how soon willl i see results?

Answer:

> Turmeric Boost contains Organic Turmeric (Curcuma Longa) Root, Turmeric 95% Curcuminoids (Curcuma Longa) Root, Organic Ginger Extract (Zingiber officinale) Root, and BioPerine® (Black Pepper Extract).
>
> Individual results vary, but some users may notice support for joint comfort or digestive balance within 4–8 weeks of consistent daily use, while others might need more time.

- Visible source: canonical Turmeric Boost page
- Resolved subject/document: Turmeric Boost / `5129`, confidence `1.0`
- Requested fields: `ingredients`, `results_timeframe`
- Retrieval: 4 chunks, 1 document, 0 structured candidates
- Cache: miss
- Browser/backend latency: **25,512 / 19,283 ms**

**Turn 2 — same conversation**

> how much is it?

Answer:

> A one-time purchase of Turmeric Boost is $33.00. If you choose to subscribe and save, the price is $31.35.

- Visible source: canonical Turmeric Boost page
- Resolved query: `how much is Turmeric Boost`
- Resolved subject/document: Turmeric Boost / `5129`, confidence `0.94`
- Requested field: `price`
- Retrieval: 3 chunks, 1 document, 1 structured candidate
- Cache: miss
- Browser/backend latency: **39,947 / 34,143 ms**

The runtime trace records query-contract, embedding, vector search, lexical search, document selection, RRF, expansion, ranking, retrieval, compression, prompt, generation, critique, optional verify/polish, and source-format stages through `ChatTrace`. The HTTP/database contract currently exposes aggregate backend latency, so the acceptance figures above do not falsely claim unavailable per-stage live numbers.

## 16. Widget exact three-turn final transcript

Completely fresh external widget session; wording was not altered.

**Turn 1** — `what turmeric products do you have`

> We have two turmeric products available:
>
> * **Turmeric Boost**: A premium turmeric formula made with organic turmeric, ginger, and BioPerine® in veggie capsules.
> * **Turmeric Gummies**: Daily wellness gummies formulated with turmeric root extract, curcumin, and black pepper extract, featuring a turmeric-ginger flavor.

- Sources: canonical Turmeric Boost and Turmeric Gummies pages only
- Contract: catalog mode, catalog scope `turmeric`
- Retrieval: 12 chunks, exactly 2 final supporting documents
- Browser/backend latency: **35,329 / 29,802 ms**

**Turn 2** — `wht ingredient of turmeric boost`

> Turmeric Boost contains Organic Turmeric (Curcuma Longa) Root, Turmeric 95% Curcuminoids (Curcuma Longa) Root, Organic Ginger Extract (Zingiber officinale) Root, and BioPerine® (Black Pepper Extract).

- Source: canonical Turmeric Boost page
- Subject/document: Turmeric Boost / `5129`
- Requested field: `ingredients`
- Retrieval: 4 chunks, 1 document
- Browser/backend latency: **21,960 / 16,447 ms**

**Turn 3** — `how much is it`

> Turmeric Boost is $33.00 for a one-time purchase. There's also a Subscribe & Save option available.

- Source: canonical Turmeric Boost page
- Resolved query: `how much is Turmeric Boost`
- Subject/document: Turmeric Boost / `5129`, confidence `0.94`
- Requested field: `price`
- Retrieval: 3 chunks, 1 document, 1 structured candidate
- Browser/backend latency: **19,284 / 13,515 ms**

All three turns were cache misses. The catalog answer excluded unrelated products, the ingredients were complete, and the final pronoun remained bound to Turmeric Boost.

## 17. Metadata-only price test

### Deterministic metadata-only fixture

The Phase L.2 suite creates a document whose price exists only in nested stored metadata and verifies that it becomes first-class price evidence with the correct numeric value, currency, document identity, and canonical source. No text-price fallback exists in that case. This test passed.

### Real frontend metadata acceptance

Question:

> How much are Turmeric Gummies?

Answer:

> Turmeric Gummies start at $55.00 for a single bottle. You can also get a 3-bottle pack for $49.50 per bottle, or a 6-bottle pack for $41.25 per bottle.

- Structured field used: stored price `$55.00 USD` (`og:price:amount`/currency path normalized into structured evidence)
- Canonical document: Turmeric Gummies / `5130`
- Source: canonical Turmeric Gummies page
- Retrieval: 4 chunks, 1 document, **1 structured metadata candidate**
- Cache: miss
- Browser/backend latency: **24,433 / 18,340 ms**

The current stored corpus also has primary text for its bottle bundle prices, so the real answer was corroborated by text. The deterministic fixture is the strict proof of metadata-only behavior; the real trace proves that stored metadata participated as top-level evidence. No value was hardcoded.

## 18. Ambiguous fresh-chat result

Fresh dashboard conversation, exact question:

> What are the ingredients?

Answer:

> Which product or item would you like the ingredients for?

- No source displayed
- No retrieval attempted
- No product guessed
- Backend/UI-displayed latency: **532 ms**

## 19. Before/after retrieval traces

| Scenario | Before | After |
|---|---|---|
| Dashboard multi-field | `ingredients` only; 6 chunks / 3 docs; timeframe found, ingredients missed; unrelated sibling context | `ingredients + results_timeframe`; subject doc `5129`; 4 chunks / 1 doc; both fields complete |
| Widget catalog | 16 chunks / all 10 docs; Joint Support leaked into answer | broad discovery followed by 12 chunks / 2 relevant supporting docs; only the two matching turmeric products answered |
| Widget ingredients | 6 chunks / 2 docs; complete subject section absent; unavailable response | subject doc `5129`; 4 chunks / 1 doc; complete four-item list |
| Widget price follow-up | malformed resolution; no `price` field; no knowledge hit | `how much is Turmeric Boost`; `price`; 3 chunks / 1 doc plus structured evidence; supported price returned |
| Gummies price | structured page value was not a retrievable evidence object | structured candidate synthesized from stored metadata, attached to doc `5130`, then combined with corroborating primary price text |
| Fresh field-only query | risk of arbitrary semantic document selection | pre-retrieval clarification; zero retrieval and zero source |

Final traces include original/resolved query, history, full query contract, cache decision, mode, selected chunk/document counts, structured-candidate count, match reasons, selected previews, compressed context, sources, and aggregate browser/backend latency. Stage timers remain internal `ChatTrace` observability data rather than part of the public response.

## 20. Test and regression results

All final commands completed successfully:

- Phase L.2 deterministic suite: **20/20 passed**
- Phase L suite: **15/15 passed**
- Phase J suite: **11/11 passed**
- RAG hardening final full rerun: **14/14 passed** in 80.795 s
- RAG pipeline: **15/15 suites, 35/35 validations passed**
- 50-query benchmark: **50/50 retrieval, 50/50 grounded, 45/45 URL/CTA accuracy, 0/50 hallucinations**
  - retrieval p50 **757.64 ms**, p95 **9,289.81 ms**, p99/worst **9,316.26 ms**
- Tenant/security/public-status/exact-page/streaming group: **52/52 passed**
- Phase F auth/secrets + Phase G atomic quota/analytics: **30/30 passed**
- Frontend widget DOM test: passed
- Frontend exact-page crawl-mode test: passed
- TypeScript `tsc --noEmit`: passed
- ESLint: passed with **0 errors, 2 pre-existing `<img>` optimization warnings**
- Python syntax compilation for all Phase L.2 runtime/test files: passed

One initial combined run had a nondeterministic semantic-ranking miss in the large-crawl test (`Module 28`). It passed immediately in isolation and the subsequent complete 14-test hardening rerun passed without changes. This transient first result is recorded for transparency; the final required regression run is clean.

## 21. No-hardcoding scan

The Phase L.2 runtime files were searched case-insensitively for:

`WOWMD`, `Turmeric Boost`, `Turmeric Gummies`, `turmeric`, `BioPerine`, `$33`, `$55`, and `wowmd.com`.

Result: **zero matches in runtime logic**.

Controlled names and values appear only in tests, this report, stored knowledge, and captured acceptance evidence. Domain-independence tests cover ecommerce, SaaS, hotel, education, and service-package equivalents.

## 22. Remaining limitations

- Phase L.2 does not implement general numeric catalog filters such as `under $40`, `between`, or global `cheapest`; it only preserves normalized structured price evidence for that later phase.
- Conversational resolution deliberately asks for clarification when evidence is weak. It does not attempt unrestricted coreference across an unbounded transcript.
- Structured evidence is limited to trusted fields already persisted by ingestion; it does not fetch live pages at answer time.
- Per-stage timing is collected internally by `ChatTrace`, while current chat API persistence exposes aggregate response latency. The acceptance report therefore records exact browser and backend totals without inventing per-stage live timings.
- Live LLM latency remains high and variable; latency redesign was explicitly outside this correctness phase.

## 23. Files changed

Phase L.2 changes are confined to:

- `backend/services/query_contract.py` — new generic query/evidence contract, subject resolution, field ontology, ambiguity rules, and structured evidence extraction
- `backend/services/intent_router.py` — centralized requested-field extraction through the canonical ontology
- `backend/services/rag_service.py` — contract-aware retrieval, per-field allocation/completeness, structured evidence, cache identity, coverage gate, sources, and traces
- `backend/services/conversational_engine.py` — generic field coverage patterns, label-preserving price condensation, and bounded verification support
- `backend/test_phase_l2_conversational_field_retrieval.py` — 20 deterministic Phase L.2 tests covering A–R and multiple domains
- `PHASE_L2_CONVERSATIONAL_FIELD_RETRIEVAL_REPORT.md` — this report

No frontend runtime file was changed. Phase J/L retrieval architecture, ingestion, widget streaming, tenant isolation, quota/security, controlled corpus data, and unrelated product areas were preserved.

## Final verdict

**CONVERSATIONAL FIELD RETRIEVAL CORE READY FOR PILOT**
