# WOWMD Controlled Ecommerce Knowledge Test

Date: 2026-08-30 IST (application records use UTC on 2026-08-29)  
Project: current local `Chatbot-Saas` working tree  
Account: `test_customer@example.com`  
Bot: `WOWMD Joint Supplements Assistant` (ID `674`)

## Final verdict

**WOWMD CONTROLLED TEST PARTIALLY PASSED**

The exact-page product change, controlled ingestion, source isolation, lifecycle, activation, and real external widget all worked. The final answer-quality acceptance did not fully pass: the three dashboard responses missed indexed products and facts that are present in the stored page content, and the widget response was accurate for Joint Support but incomplete for the broader set of matching non-gummy products.

No RAG code was changed. The quality failure was diagnosed before stopping, as required.

## 1. Small product change

The existing **Crawl URL** dialog now exposes:

- **This page + child pages** — value `recursive`; remains the default and retains the existing `/v1/crawl` behavior.
- **This page only** — value `single_page`; invokes Firecrawl `/v1/scrape` for the submitted URL and returns exactly one page to the existing ingestion job.

The API field is `crawl_mode`, with a backend default of `recursive` so existing callers retain their behavior. Exact-page processing reuses the existing URL validation, tenant authorization, rate limiting, quota gate, durable job, staging, extraction, chunking, embedding, validation, promotion, cache invalidation, and knowledge lifecycle. It does not schedule discovered links and does not crawl broadly and delete afterward.

For audit transparency, links found in the scraped markdown are recorded as skipped with reason `single_page_mode`; they are never converted into pages or documents. Re-crawl reads the persisted mode from document metadata.

The submitted normalized URL remains the source identity, including the collection's meaningful `?page=1` query. Firecrawl did not return a separate canonical field for these ten responses, so `canonical_url` is null while `source_url` retains each exact supplied URL.

## 2. Files changed for this correction

Backend:

- `backend/schemas/schemas.py`
- `backend/routes/knowledge_routes.py`
- `backend/services/firecrawl_service.py`
- `backend/services/document_processing_service.py`
- `backend/test_exact_page_crawl_mode.py`

Frontend:

- `frontend/types/knowledge.ts`
- `frontend/services/knowledge-service.ts`
- `frontend/store/knowledge-store.ts`
- `frontend/components/knowledge/knowledge-bot-client.tsx`
- `frontend/tests/exact-page-crawl-mode.test.mjs`
- `frontend/package.json`

Report:

- `WOWMD_CONTROLLED_ECOMMERCE_TEST.md`

No RAG, model routing, embedding, chunking, billing, authentication, public-session, or unrelated ingestion architecture was changed.

## 3. Deterministic validation

| Validation | Result |
|---|---:|
| New backend exact-page contract tests | 5 passed |
| Existing Firecrawl unit tests | 4 passed |
| Phase D ingestion lifecycle | 6 passed |
| Phase H knowledge operations | 7 passed |
| Phase A tenant/chat security | 15 passed |
| Phase 11 security suite | 8 passed |
| Backend focused total | **45 passed** |
| Frontend exact-page contract | passed |
| Frontend Phase H knowledge contract | passed |
| TypeScript typecheck | passed |
| Python syntax/import validation | passed |
| ESLint | 0 errors; 2 pre-existing `<img>` warnings |

The new tests prove:

- request omission defaults to recursive mode;
- exact-page mode calls `/v1/scrape`, returns one page, retains `?page=1`, preserves returned canonical metadata, does not poll a crawl job, and classifies child links as skipped;
- recursive dispatch still calls the existing recursive function with the same options;
- tenant/admin scope, crawl rate limit, and document quota checks still execute before document/job creation;
- quota rejection prevents both document and job creation;
- frontend mode labels, default, store/service propagation, and API payload are present.

## 4. Real frontend ingestion run

The real dashboard was used for all ten submissions. For each URL, **This page only** was selected, **Start crawl** was used, and the next URL was not submitted until the previous source showed `completed`, `Active version 1`, and one page.

| # | Exact indexed URL | Chunks | Tokens | Server job duration |
|---:|---|---:|---:|---:|
| 1 | `https://www.wowmd.com/collections/joint-supplements?page=1` | 34 | 5,034 | 27.858 s |
| 2 | `https://www.wowmd.com/products/joint-support` | 57 | 9,808 | 27.808 s |
| 3 | `https://www.wowmd.com/products/turmeric-boost` | 61 | 11,428 | 33.931 s |
| 4 | `https://www.wowmd.com/products/turmeric-gummies` | 56 | 10,155 | 33.960 s |
| 5 | `https://www.wowmd.com/products/sea-essence-omega-3-fish-oil` | 64 | 15,456 | 33.775 s |
| 6 | `https://www.wowmd.com/products/collagen-complex` | 69 | 15,829 | 37.334 s |
| 7 | `https://www.wowmd.com/products/grass-fed-hydrolyzed-collagen-peptides` | 50 | 10,243 | 32.227 s |
| 8 | `https://www.wowmd.com/products/grass-fed-collagen-peptides-powder-chocolate` | 55 | 11,098 | 31.292 s |
| 9 | `https://www.wowmd.com/products/moringa` | 61 | 13,300 | 32.374 s |
| 10 | `https://www.wowmd.com/products/nutrimax-essentials` | 66 | 15,674 | 38.209 s |
|  | **Total** | **573** | **118,025** |  |

Post-run read-only verification:

| Record | Count |
|---|---:|
| Intended URLs | 10 |
| Stored bot documents | 10 |
| Ready/completed documents | 10 |
| Website roots | 10 |
| Website crawls | 10 |
| Ready ingestion jobs | 10 |
| Chunks | 573 |
| Unrelated WOWMD documents | **0** |

Every job reports `pages_crawled=1` and `documents_created=1`. `pages_discovered` is larger because exact-page audit records links present in the supplied page, but none of those links were crawled or ingested.

Stored text is substantive rather than an empty shell. Examples found in the persisted corpus include:

- Joint Support capsule ingredients, `Take 2 capsules once daily...`, and `$49.00`.
- Grass-Fed Hydrolyzed Collagen Peptides as a powder, `$75.00`, and one scoop mixed into 8–10 oz of a beverage.
- Moringa at `$42.00`, two veggie capsules daily, and the page's stated joint-comfort/flexible-movement copy.
- NutriMax Essentials at `$39.00` and two capsules daily with a meal.

## 5. Dashboard question results

All three questions were entered exactly through the dashboard Chat playground. All three persisted as successful `playground_stream` messages with `retrieval_attempted=true` and `had_knowledge_hit=true`. Streaming rows do not persist `response_time_ms`, so end-to-end browser timing is reported.

### Q1 — catalog grouped by form, price, and link

Latency: **28.354 s**

Answer recorded:

> We have a product called **Joint Support** available in the catalog. You can find more details about it at: https://www.wowmd.com/products/joint-support. The specific product form and listed price are not explicitly mentioned in the available information. We also have a general collection page for Joint Supplements, which you can view here: https://www.wowmd.com/collections/joint-supplements?page=1.

Sources shown:

- Joint Supplements, chunk 20, score 0.818
- Joint Support, chunks 10 and 3, scores 0.904 and 0.894

Assessment: **failed answer-quality acceptance**. It named only one product, did not group the catalog, and incorrectly said form/price were unavailable even though those facts are stored.

### Q2 — powders, form/flavor, price, and use

Latency: **27.460 s**

Answer recorded:

> Based on the information available, the product “Joint Support” does not have its form specified. The other products listed, “Peptide Eye Gel-Cream” and “Skin Hydration Cream,” are a gel-cream and a cream, respectively, not powders. Therefore, I cannot identify any powder products from the information provided.

Sources shown:

- Joint Support, chunks 45 and 43, scores 0.914 and 0.883
- CTA links to Peptide Eye Gel-Cream and Skin Hydration Cream from the retrieved page, even though those pages were not indexed as documents

Assessment: **failed answer-quality acceptance**. Two indexed collagen powder pages contain explicit form, price, and mixing directions, but neither was retrieved. The response also elevated irrelevant product CTAs from a Joint Support chunk.

### Q3 — four-product comparison

Latency: approximately **45 s** end to end. The browser observer's completion marker timed out because this response exposed retrieved-chunk cards without the expected source-card marker; the answer itself completed successfully and was recovered from the same dashboard session. The streaming database row has no latency value.

Answer recorded, summarized without changing its meaning:

- Joint Support: benefits described, but form, ingredient list, directions, and price said to be unspecified.
- Turmeric Boost: turmeric, ginger, and BioPerine plus stated joint/digestive/antioxidant support; form, directions, and price said to be unspecified.
- Turmeric Gummies: incorrectly said no catalog information was available.
- Sea Essence Omega-3 Fish Oil: relied on generic reviewer wording and said form, ingredients, directions, and price were unspecified.

Retrieved chunk cards came from Joint Supplements, Joint Support, and Turmeric Boost. The required Turmeric Gummies and Sea Essence product pages were not selected into the answer context.

Assessment: **partially answered but failed the requested comparison**. Some supported benefits/ingredients were returned, but most requested fields and two target product pages were missed.

## 6. Real external widget result

The bot was activated through **Publish & Deploy** in the real frontend. The external origin `http://127.0.0.1:4173` was added through Widget Customizer and saved. The existing independent customer-site fixture loaded `widget.js` from the frontend and used the public API at `http://127.0.0.1:8000`.

Only the required widget question was sent. Browser console result: no warnings or errors.

Latency:

- Browser end to end: **28.142 s**
- Persisted backend generation time: **22.259 s**

Answer recorded:

> The WOWMD® Joint Support is available in capsule form and is presented as supporting joints or mobility. Product form: capsules. Key listed ingredients: MSM, plant-based GlucosaGreen® glucosamine, turmeric, Boswellia serrata, white willow bark, hyaluronic acid, and black pepper extract. Serving/use: take 2 capsules once daily with 6–8 oz of water, preferably with a meal. Price: $49.00 one-time or $46.55 subscription. Direct link: https://www.wowmd.com/products/joint-support.

Sources shown:

- Joint Support — `https://www.wowmd.com/products/joint-support`
- Joint Supplements — `https://www.wowmd.com/collections/joint-supplements?page=1`
- Shop Subscribe & Save CTA — `https://www.wowmd.com/pages/subscribe-and-save`

Assessment: **operational and grounded, but incomplete**. The supplied details for Joint Support are supported by the page. The response omitted other indexed non-gummy pages that explicitly state joint or mobility support, including Moringa, both collagen powders, Collagen Complex, and Turmeric Boost.

Final persisted bot state is `active`; the allowed external origin is `http://127.0.0.1:4173`.

## 7. Diagnosed quality failure

The failure is not ingestion: the exact ten-document corpus is ready, content-bearing, embedded, and source-isolated.

The evidence points to **retrieval selection and multi-document coverage over noisy ecommerce pages**:

1. The requested facts exist in stored raw text and chunks.
2. All four test messages report retrieval attempted and a knowledge hit.
3. Dashboard retrieval selected only a small subset of documents and often selected navigation, image, review, or CTA-heavy chunks.
4. Q2 never selected either collagen powder document; Q3 never selected Turmeric Gummies or Sea Essence; the widget selected primarily Joint Support.
5. Generation therefore received incomplete or distracting context and truthfully reported many fields as absent—or, in Q2, surfaced unrelated CTA products.

This is a clearly diagnosed RAG-quality gap, but no RAG changes were made because this task requested the minimal crawl-mode correction followed by the controlled test, then a stop after reporting.

## 8. Scope confirmation

- Exact-page crawl mode: implemented and verified.
- Existing recursive mode: retained as default and covered by deterministic regression.
- Firecrawl/extraction/chunking/embedding/job/quota/tenant/staging lifecycle: reused.
- Broad crawl followed by deletion: not used.
- Manual ingestion API or direct database seeding: not used.
- RAG changes: none.
- Unrelated product/audit issues: not addressed.

## Final verdict

**WOWMD CONTROLLED TEST PARTIALLY PASSED**
