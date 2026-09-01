# Phase L — Ecommerce Multi-Document Retrieval, Filtering & Latency Hardening

Date: 2026-08-31 IST  
Project: current local `Chatbot-Saas` working tree  
Controlled account: `test_customer@example.com`  
Controlled bot: `WOWMD Joint Supplements Assistant` (ID `674`)

## Final verdict

**CONTROLLED ECOMMERCE RAG ACCEPTABLE FOR PILOT**

The live dashboard and external-widget answers now satisfy the controlled answer-quality acceptance criteria. Catalog breadth, powder filtering, four-entity comparison coverage, grounded fields, canonical links, and visible source attribution all worked against the unchanged ten-document corpus.

Latency improved materially for the four-entity comparison and widget, and the measured retrieval stage was reduced from about 6.4 seconds to about 2.4 seconds in the instrumented comparison. End-to-end latency remains above the preferred Phase L targets on this local stack because the external Gemini generation call dominates and local Redis is unavailable. This is a documented pilot limitation, not a hidden pass.

## 1. Exact root causes of the four failures

### Q1 — broad catalog

- The qualified phrase “joint-support and related products ... in this catalog” was classified as an ordinary factual query.
- There was no document-candidate stage and no requested-field extraction for form, price, or link.
- Global chunk ranking spent the small context budget on the collection page and Joint Support instead of allocating breadth across relevant product documents.
- The generator correctly could not report fields that retrieval failed to supply.

### Q2 — powder filter

- Follow-up resolution replaced each pronoun with the entire preceding question, producing a duplicated resolved query.
- “Powder” and “rather than capsules, softgels, or gummies” were not represented as structured include/exclude attributes.
- The global top chunks came from Joint Support cross-sell sections, so two unindexed recommendation cards were elevated while both indexed powder documents were absent.

### Q3 — explicit comparison

- The entity parser split the sentence into two long fragments rather than the four product names.
- Consequently, entity-to-document matching was not possible and global RRF allowed only Joint Support and Turmeric Boost product evidence to dominate.
- Turmeric Gummies and the Sea Essence primary product block received no fair evidence opportunity. Missing fields were therefore reported before their documents had been searched.

### Widget — broad negative-filter comparison

- “Compare the matching options by product form...” was mistaken for an explicit named-entity comparison; requested output fields became bogus entities.
- “Non-gummy” and “supporting joints or mobility” were not structured as exclusion/inclusion constraints.
- The final context was concentrated on Joint Support and the collection page.
- Separately, the widget visibly capped source chips at five even when the backend returned more supporting product pages.

## 2. Pre-change document-level trace

Gate 1 was captured before RAG edits. The ten READY documents were the only global search scope; there was no explicit pre-chunk document-candidate stage.

| Query | Original/resolved query | Mode and parsed contract | Vector/lexical/RRF outcome | Final context |
|---|---|---|---|---|
| Q1 | Exact original; unchanged | `factual`; no entities, filters, or requested fields | 73 pre-clean candidates; global winners concentrated on collection/Joint Support | 3 chunks, 2 documents, 2,869 chars: `Joint Supplements` and `Joint Support` |
| Q2 | Exact original; resolved query duplicated the whole preceding question for multiple pronouns | `filter`, but filter text was the raw sentence; no include/exclude attributes or requested fields | Joint Support cross-sell/recommendation chunks won | 2 Joint Support chunks, 1,459 chars; no powder document |
| Q3 | Exact original | `comparison`, but only two malformed sentence-span entities | Global vector/lexical/RRF retained collection, Joint Support, and Turmeric Boost; no exact four-document allocation | 12 chunks, 3 documents, 7,146 chars; Turmeric Gummies and Sea primary evidence absent |
| Widget | Exact original | Incorrect `comparison`; output fields parsed as entities; no negative filter | Joint Support and collection dominated | 4 chunks, 2 documents, about 9,500 chars |

Pre-change supporting document URLs represented in context were:

- Q1: `https://www.wowmd.com/collections/joint-supplements?page=1`, `https://www.wowmd.com/products/joint-support`
- Q2: `https://www.wowmd.com/products/joint-support`
- Q3: collection page, Joint Support, and `https://www.wowmd.com/products/turmeric-boost`
- Widget: Joint Support and the collection page

The Q3 final rank used six collection chunks, four Joint Support chunks, and two Turmeric Boost chunks. The widget used two Joint Support and two collection chunks. This confirmed document monopoly rather than missing stored facts.

## 3. Chunk and noise analysis

Read-only measurement over all 573 controlled chunks found:

| Noise signal | Chunks | Share |
|---|---:|---:|
| Review/reviewer copy | 133 | 23.2% |
| Cross-sell / “You may also like” | 45 | 7.9% |
| Generic marketing boilerplate | 65 | 11.3% |
| Subscribe CTA blocks | 17 | 3.0% |
| Navigation-heavy | 10 | 1.7% |
| Image-dominated | 9 | 1.6% |

The primary detail chunks contain the required prices, product descriptions, forms, directions, and benefits; adjacent ingredient chunks contain the remaining ingredient lists. Cross-sell chunks have usable structural metadata such as `section: "You may also like"`, so they can be down-ranked at retrieval time without changing ingestion.

Reviews were not globally removed. They are down-ranked for specification/price/directions questions and remain eligible for review queries.

## 4. Retrieval architecture changes

The existing pgvector + lexical + RRF pipeline remains in place. Phase L adds a small document-first layer:

1. Route the query and extract explicit entities, include/exclude attributes, and requested fields.
2. Load tenant-scoped READY document identities once.
3. For explicit comparisons, match each entity to its strongest title/URL document.
4. For catalog/filter queries, score relevant documents using title/URL, primary content, attributes, requested fields, and existing semantic rank.
5. Select compact field-bearing evidence inside each candidate document.
6. Merge that evidence with the existing vector/lexical/RRF candidates.
7. Allocate context breadth-first for catalog/comparison/filter modes and relevance-depth-first for ordinary factual modes.

The comparison path now loads chunk bodies only for selected documents. Avoiding repeated document metadata and embedding-column transfer reduced measured comparison document selection from 3,113 ms to 286–309 ms.

## 5. Filter behavior

The router now represents Q2 as:

- include: `powder`
- exclude: `capsule`, `softgel`, `gummy`
- requested fields: form/flavor, price, directions

Candidate documents are established before field chunks are chosen. Plural/singular attribute forms are normalized, primary evidence is required for inclusion, and an incidental ingredient word cannot override a conflicting primary form.

The behavior is domain-neutral and is covered for retail attributes, SaaS plans with SSO, hotels with breakfast, and short courses.

## 6. Catalog behavior

Qualified catalog language now routes to catalog mode. Document relevance is still required, but representative evidence is allocated across relevant documents before duplicate depth is allowed. Domain nouns such as `tour`, `course`, `treatment`, and `plan` remain relevance signals rather than being discarded as generic list boilerplate.

Q1 now returned eight relevant product pages grouped into capsule/softgel, powder, and gummy forms with listed prices and direct canonical links.

## 7. Comparison behavior

The entity parser now extracts the initial comma/Oxford list from an explicit comparison sentence. Q3 resolves to exactly four entities, each maps to its matching READY document, and each receives its strongest primary field-bearing block before any document receives extra depth.

The final live answer represented all four named products and all requested fields. The Sea Essence primary block, including `Take 1 softgel, 2–3 times daily`, is now ahead of incidental high-overlap FAQ/review evidence.

## 8. Cross-sell and CTA behavior

- Cross-sell detection uses section/heading metadata and generic recommendation language.
- Cross-sell chunks do not become catalog entities unless the user actually asks for recommendations.
- Safe purchase/booking/tour CTAs remain available for action queries.
- Source CTA metadata must match the canonical page or item identity when identity is available.
- Legacy/synthetic sources with no identity still preserve safe HTTP(S) CTAs, maintaining the existing widget security contract.

Peptide Eye Gel-Cream and Skin Hydration Cream are no longer presented as indexed products in Q2.

## 9. Source attribution changes

Canonical/source URLs from supporting indexed documents are the primary source contract. Unrelated subscribe and recommendation CTAs are suppressed. Mixed comparisons that honestly mark one field unavailable no longer suppress all otherwise valid sources.

The external widget source-chip bound was increased from five to twelve so a supported multi-document answer does not silently lose visible attribution. The final widget showed all eight discussed product-page links, and browser console inspection found no warnings or errors.

## 10. Latency before changes

| Query | Prior controlled browser result | Instrumented pre-change notes |
|---|---:|---|
| Q1 | 28.354 s | 17.733 s direct rerun; cache lookup 4.012 s, retrieval about 2.1 s, generation 11.375 s; 2 context documents |
| Q2 | 27.460 s | 20.368 s direct rerun; retrieval 7.352 s, generation 12.870 s; 1 context document |
| Q3 | about 45 s | 27–28 s direct reruns; generation about 16–17 s plus one 5 s polish timeout; 3 context documents |
| Widget | 28.142 s | 21.331 s direct rerun; retrieval 2.868 s, generation 14.313 s; 2 context documents |

Each request used Gemini `gemini-2.5-flash` for one main answer-generation call. The primary latency causes were incomplete/noisy retrieval followed by provider generation, with repeated unavailable-Redis connection timeouts adding about four seconds on cold cache access.

## 11. Read-only controlled evidence matrix

This matrix was read from the unchanged stored product chunks. It is test evidence only and is not present in runtime logic or prompts.

| Product / source | Form and listed one-time price | Key ingredients | Stored use directions | Page-stated purpose/benefits |
|---|---|---|---|---|
| [Joint Support](https://www.wowmd.com/products/joint-support) | Capsules; $49 | MSM, GlucosaGreen glucosamine, turmeric, Boswellia, white willow bark, hyaluronic acid, black pepper extract | 2 capsules once daily with 6–8 oz water, preferably with a meal | Joint cushioning, flexible movement, daily mobility, everyday comfort |
| [Turmeric Boost](https://www.wowmd.com/products/turmeric-boost) | Veggie capsule; $33 | Organic turmeric root/curcuminoids, ginger extract, BioPerine | 1 veggie capsule daily, preferably with a meal | Joint comfort, digestive wellness, antioxidant activity, everyday mobility |
| [Turmeric Gummies](https://www.wowmd.com/products/turmeric-gummies) | Gummies; $60 | Turmeric root extract, curcumin, black pepper extract | 2 gummies daily, preferably after meals | Joint flexibility/mobility, antioxidant wellness, healthy inflammatory response, skin support |
| [Sea Essence Omega-3 Fish Oil](https://www.wowmd.com/products/sea-essence-omega-3-fish-oil) | Softgel; $37 | Purified fish oil, omega-3, EPA, DHA | 1 softgel 2–3 times daily, preferably with a meal | Heart/brain/joint health, everyday mobility, cognitive wellness, healthy aging |
| [Collagen Complex](https://www.wowmd.com/products/collagen-complex) | Capsules; $49 | Hydrolyzed bovine, chicken, marine, eggshell-membrane, and avian-sternum collagen | 3 capsules daily, preferably with a meal | Skin elasticity, joint comfort, hair/nail wellness, connective-tissue health |
| [Grass-Fed Hydrolyzed Collagen Peptides](https://www.wowmd.com/products/grass-fed-hydrolyzed-collagen-peptides) | Unflavored powder; $75 | Bovine-hide collagen peptides, Types I and III | 1 level scoop in 8–10 oz chilled water, coffee, smoothie, or other beverage | Skin elasticity, joint comfort/mobility, muscle recovery, bone wellness |
| [Grass-Fed Collagen Peptides Powder (Chocolate)](https://www.wowmd.com/products/grass-fed-collagen-peptides-powder-chocolate) | Chocolate powder; $75 | Hydrolyzed Type I and III collagen peptides | 2 scoops in 8–10 oz water or another beverage, daily | Skin hydration/elasticity, joint comfort/movement, bone-supporting nutrition |
| [Moringa Green Energy](https://www.wowmd.com/products/moringa) | Veggie capsules; $42 | Nutrient-dense moringa with naturally occurring vitamins, minerals, antioxidants | 2 veggie capsules once daily, 20–30 minutes before a meal with 8 oz water | Daily vitality, joint comfort, relaxation, nutritional balance |
| [NutriMax Essentials](https://www.wowmd.com/products/nutrimax-essentials) | Capsules; $39 | Vitamins, minerals, and herbal extracts | 2 capsules daily with a meal | Immune/antioxidant support, energy, heart/vitality, muscle and joint health |

## 12. Exact dashboard before/after

### Q1

- Before: named only Joint Support and said form/price were unavailable.
- After: grouped eight relevant indexed products by capsule/softgel, powder, and gummy form; included correct listed prices and direct product links.
- After sources: product pages for Joint Support, Turmeric Boost, both collagen powders, Collagen Complex, Moringa, Sea Essence, NutriMax, Turmeric Gummies, plus the indexed collection page used as catalog evidence.

### Q2

- Before: claimed no powders and surfaced two unindexed cross-sell products.
- After: returned exactly the two indexed powders: unflavored Grass-Fed Hydrolyzed Collagen Peptides and chocolate Grass-Fed Collagen Peptides Powder, both at $75, with their distinct one-scoop/two-scoop directions.
- After sources: exactly the two canonical powder product pages.

### Q3

- Before: omitted the Turmeric Gummies document and Sea primary product evidence and reported most fields missing.
- After: gave separate supported entries for Joint Support, Turmeric Boost, Turmeric Gummies, and Sea Essence with form, ingredients, stated benefits, use directions, price, and direct link.
- After sources: exactly the four named canonical product pages.

## 13. Exact widget before/after

- Before: answered only Joint Support, with the collection and a subscribe CTA also shown.
- After: returned eight strongly supported non-gummy pages: Turmeric Boost, Joint Support, chocolate collagen powder, Sea Essence, Collagen Complex, unflavored collagen powder, Moringa, and NutriMax. Turmeric Gummies was excluded.
- Each entry included form, page-listed ingredients, page directions, price, and canonical URL.
- The final widget showed all eight corresponding source links after the source-cap correction.
- Console warnings/errors: none.

## 14. Latency after changes

| Query | Real browser end to end | Persisted backend response time | Result |
|---|---:|---:|---|
| Q1 | 32.363 s | 26.556 s | Correct; latency target missed |
| Q2 | 25.941 s | 19.944 s | Correct; modestly faster; target missed |
| Q3 | 28.630 s | 23.079 s | Correct; materially faster than ~45 s; target missed |
| Widget, final source-complete run | 26.258 s | 20.912 s | Correct and faster than prior 28.142/22.259 s; target missed |

An earlier cold widget run on the final retrieval logic took 47.495 s browser / 33.688 s backend, illustrating provider variability. The optimized instrumented Q3 trace was:

- embedding: 716 ms on the warm direct probe (4.7 s on another provider call)
- vector: 398 ms
- lexical: 697 ms
- document selection: 286 ms
- context expansion: 143 ms
- complete retrieval: 2.401 s
- compressed context: 8,476 chars
- prompt/model calls: one main Gemini 2.5 Flash call; no verification or polish LLM call
- generation: 19.222 s
- cache lookup with local Redis absent: about 4.014 s

Correctness was not reduced to force a timer. Production should run the configured Redis service, and provider latency should be monitored before increasing pilot traffic.

## 15. New generic regressions

`backend/test_phase_l_ecommerce_retrieval.py`: **15/15 passed**.

Coverage includes all requested A–M patterns:

- four named entities/four document coverage;
- catalog diversity;
- attribute include/exclude filtering, including `non-` forms;
- price and directions evidence priority;
- comparison monopoly prevention;
- cross-sell suppression;
- canonical source mapping and mixed missing-field honesty;
- review down-weighting and review-query retention;
- ecommerce, SaaS, hospitality, and education domain independence.

## 16. Existing regression results

| Validation | Exact result |
|---|---:|
| Phase J contracts | 11/11 passed |
| RAG quality hardening | 14/14 passed |
| RAG pipeline script | 15 suites / 35 validations passed |
| 50-query customer benchmark | 50/50 retrieval and grounding; 45/45 URL/CTA; 0 hallucinations; p50 757.19 ms, p95 892.35 ms, worst 919.90 ms |
| Customer adversarial suite | 10 unaffected cases passed in the full run; the CTA regression and cache-version case passed on targeted rerun. The latter required a temporary organization 30 fixture because the one-account cleanup had removed the test's hardcoded FK prerequisite; the temporary fixture was removed afterward. |
| Phase 10 deep coverage | 6/6 passed |
| Phase I streaming sources | 2/2 passed |
| Phase E widget streaming parity | 16/16 passed on final full rerun |
| Phase A tenant/chat security | 15/15 passed |
| Phase A2 stop-ship security | 8/8 passed |
| Phase 11 security | 8/8 passed |
| Exact-page backend mode | 5/5 passed |
| Frontend exact-page contract | passed |
| Frontend widget DOM contract | passed |
| TypeScript typecheck | passed |
| ESLint | 0 errors; 2 pre-existing `<img>` warnings |
| Python syntax/import validation | passed |

## 17. Runtime no-overfitting search

The added runtime diff was searched case-insensitively for:

`WOWMD`, `Joint Support`, `Turmeric Boost`, `Collagen`, `Moringa`, `wowmd.com`, `$49`, `$75`

Result: **`NO_PHASE_L_RUNTIME_HARDCODE_HITS`**.

The controlled names, URLs, prices, and evidence appear only in this report/test evidence and live stored data, never in retrieval/runtime logic.

## 18. Files changed in Phase L

- `backend/services/intent_router.py`
- `backend/services/rag_service.py`
- `backend/services/conversational_engine.py`
- `backend/test_phase_l_ecommerce_retrieval.py` (new)
- `frontend/public/widget.js`
- `PHASE_L_ECOMMERCE_RETRIEVAL_REPORT.md` (new)

## 19. Remaining limitations and scope confirmation

- End-to-end latency remains above preferred targets and is dominated by provider generation plus local Redis connection timeouts. Retrieval selection itself is now near the requested range in the instrumented comparison.
- Broad eight-item answers are necessarily longer than the prior incomplete single-item response. A future provider/response-budget phase could evaluate shorter tables or model-specific output caps, but Phase L did not trade away required fields.
- Candidate evaluation is bounded to 500 READY documents and 1,500 chunks in the document-first audit layer; very large catalogs may need database-side summaries or indexed structured attributes in a separate phase.
- Filter understanding is lexical/structural and generic; numeric range operators across inconsistent prose remain a future structured-extraction problem.
- No WOWMD page was crawled or reingested. The corpus remains exactly 10 READY documents and 573 READY chunks.
- Firecrawl, exact-page ingestion, extraction, chunking, authentication, quotas, Redis/ARQ architecture, migrations, widget security, and frontend layout were not redesigned.

## Final verdict

**CONTROLLED ECOMMERCE RAG ACCEPTABLE FOR PILOT**
