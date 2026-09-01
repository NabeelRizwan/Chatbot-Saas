# Phase J — Live RAG Quality, Catalog Intelligence & Latency Hardening

Date: 2026-08-28  
Project: current local `Chatbot-Saas` working tree  
Primary live corpus: bot `674` (`IKEA Deep Storage Assistant`), organization `538`

## Executive result

The four reported customer turns were reproduced against the active 154-chunk corpus before any Phase J code change. The failures were real and were not caused primarily by absent wardrobe facts. The active corpus contained concrete wardrobe products, but query routing, retrieval cleanup, catalog aggregation, context selection, and source construction prevented those facts from reaching the customer correctly.

After the targeted repairs:

- the two list requests route to `catalog` instead of ordinary factual retrieval;
- the follow-up resolver no longer turns assistant prose into entities such as `Yes Rs`;
- the wardrobe list enumerates five indexed products with grounded prices and direct product links;
- the broad storage request produces a representative grouped catalog instead of four arbitrary chunks or a facet dump;
- shoe-cabinet and bookcase pages are no longer displayed for wardrobe-only answers;
- an unknown kayak question returns no unrelated source pages;
- the final exact-query cache-miss timings were 4.08–7.56 seconds;
- a repeat of the full wardrobe turn was served from semantic cache in 71 ms with the same answer and sources.

## Gate 1 — Before-change diagnostic trace

### Conversation-level trace

| Turn | Original query | History signal | Old intent/mode | Old resolved query | Cache | Old total |
|---|---|---|---|---|---:|---:|
| 1 | `do you have hallway storage?` | none | `knowledge_query` / `factual` | unchanged | miss | 24,086 ms |
| 2 | `what about wardrobes` | hallway answer contained `Yes` and `Rs` | `knowledge_query` / `factual` | `Yes Rs what about wardrobes` | miss | 12,915 ms |
| 3 | `well wht all wardrobes do you have?` | prior wardrobe answer | `knowledge_query` / `factual` | raw typo-bearing query | miss | 14,354 ms |
| 4 | `list items u have for storage?` | prior wardrobe turns | `knowledge_query` / `factual` | raw typo-bearing query | miss | 22,787 ms |

### Before-change retrieval evidence

| Query | Vector/lexical evidence | Fused/final context defect | Old customer-facing sources |
|---|---|---|---|
| Hallway | Vector rank 1 was chunk `3676`, the exact `Hallway storage` section (`cos=0.735`). Lexical results also contained it. | `clean_retrieved_chunks` later sorted selected evidence by document/chunk index, so the best evidence was displaced by generic storage sections. | Storage root + shoe cabinets |
| Wardrobes | Relevant root chunks existed, including `BRIMNES` and the wardrobe category section. | Resolver pollution (`Yes Rs`) and ordinary factual depth selected generic wardrobe prose plus shoe page chunks `3734`/`3739`. | Storage root + shoe cabinets |
| All wardrobes | Root document contained BRIMNES, NODELAND, and PAX product chunks. | Request was not recognized as catalog. Final selected chunks were generic storage/FAQ chunks plus unrelated bookcase sibling chunks. | Storage root + bookcases |
| Storage list | Broad storage facts existed across root, boxes/baskets, hallway, bookcases, and food-storage pages. | Request was not recognized as catalog. Ordinary top-k selected a narrow/random subset and navigation-heavy chunks. | Storage root + boxes/baskets + food storage |

Representative old fused selections and scores:

- Hallway: chunks `3630` (0.740), `3632` (0.762), `3640` (0.762), `3651` (0.752), plus shoe chunks `3739` (0.531) and `3743` (0.522). The exact hallway chunk `3676` was not in final context.
- Wardrobe follow-up: root chunks `3633`, `3640`, `3642`, `3646`, plus shoe chunks `3734` and `3739`.
- Wardrobe list: root chunks `3629`, `3640`, `3678`, `3684`, plus bookcase sibling chunks `3707` and `3711`.
- Broad storage: root navigation/category chunks plus boxes and food-storage representatives; generation happened to choose only KUGGIS, DRÖNA, DRÖNJÖNS, and FJÄDERHARV.

### Before-change stage timings

The old production trace did not expose vector, lexical, RRF, and context-expansion sub-stages separately. Gate 1 therefore used read-only standalone probes for candidate lists and the existing end-to-end trace for the combined retrieval stage. A cold standalone embedding probe took 5,493 ms. No timing was fabricated for an old sub-stage that the code did not emit.

| Query | Combined retrieval | Generation | Critique | Verify | Polish | Total |
|---|---:|---:|---:|---:|---:|---:|
| Hallway | 6,833 ms | 13,108 ms | ~0 ms | not run | ~1 ms | 24,086 ms |
| Wardrobe follow-up | 1,502 ms | 11,280 ms | ~0 ms | not run | ~0 ms | 12,915 ms |
| Wardrobe enumeration | 1,392 ms | 12,865 ms | ~0 ms | not run | ~0 ms | 14,354 ms |
| Broad storage | 6,106 ms | 7,546 ms | ~0 ms | not run | 5,014 ms | 22,787 ms |

Redis was listening and then became unresponsive during the baseline run. Its two-second connection timeouts contributed to the worst baseline retrieval/cache totals. The local Redis process was restarted for the post-change measurement; no Redis/ARQ architecture was changed.

## Gate 2 — Active corpus coverage

Active knowledge facts:

- active knowledge version: `1`
- ready documents: `5`
- ready chunks: `154`
- root page: `https://www.ikea.com/in/en/cat/storage-organisation-st001/`
- other ready pages: bookcases/shelving, boxes/baskets, hallway shoe cabinets, and food storage

| Search term | Matching ready chunks | Documents | Representative evidence |
|---|---:|---|---|
| `wardrobe` | 20 | storage root, boxes/baskets | BRIMNES and NODELAND product chunks; wardrobe category links |
| `wardrobes` | 9 | storage root, boxes/baskets | bedroom storage, children's storage, storage FAQ |
| `PAX` | 9 | storage root | PAX / BERGSBO, PAX / MEHAMN/AULI, PAX / STORKLINTA |
| `clothes storage` | 2 | boxes/baskets | clothes-box/category evidence |
| `open wardrobe` | 1 | storage root | room/category navigation evidence |
| `wardrobe system` | 0 | none | exact phrase absent |

The dedicated `/cat/wardrobes-19053/` page was linked in the root page but was not a separate ready document. Nevertheless, the root document contained enough structured product evidence to answer the observed questions accurately.

Classification:

- Dedicated wardrobe page coverage: **A — not indexed**.
- The observed live answer failures: primarily **B — indexed but not retrieved/ranked correctly** and **C — retrieved but not selected into useful context**.
- The vague repeated generation was downstream of those B/C failures, with a secondary **D — selected context/prompt did not demand entity enumeration** effect.

No crawl or Firecrawl change was required for Phase J because the failing customer questions were answerable from active data.

## Root causes by original failure

### 1. Hallway answer

The answer was broadly true, but relevance order was destroyed after fusion: selected chunks were re-sorted by `(document_id, chunk_index)`. This displaced vector rank 1, the exact hallway section. Sources were then built from every selected retrieval candidate instead of the context that supported the answer.

### 2. `what about wardrobes`

The resolver searched assistant text for capitalized entities and extracted `Yes Rs`. It prepended those tokens to the actual subject switch. Ordinary factual retrieval then admitted shoe chunks, and source formatting exposed every retrieved document.

### 3. `well wht all wardrobes do you have?`

The catalog grammar used a fixed allow-list of nouns and did not recognize arbitrary tenant catalog nouns in this wording. The query stayed factual, catalog breadth/structured enumeration never ran, sibling expansion added unrelated bookcase text, and the model repeated the previous high-level PAX answer.

### 4. `list items u have for storage?`

Typo normalization existed but was not consistently returned to retrieval. The list grammar did not recognize `list items you have for <subject>`, so the request stayed factual. The old catalog fallback also selected chunk indexes 0/1/2 from every document, which favored navigation and page introductions rather than query-relevant representatives.

### 5. Latency

- remote Gemini generation dominated healthy runs;
- unavailable Redis attempts added repeated two-second timeouts during the baseline;
- a Markdown list containing a legitimate repeated color phrase (`dark grey dark grey/oak effect`) triggered an unnecessary second polish LLM call;
- the old prompt contained a large repeated rule/checklist section;
- stage observability stopped at combined retrieval/generation, hiding which retrieval operations were slow.

## Code changes

### `backend/services/intent_router.py`

- Added domain-agnostic catalog patterns whose subject is not a fixed noun allow-list.
- Recognizes typo-normalized forms such as `what all <subject> do you have` and `list items you have for <subject>`.
- Recognizes contextual list continuations including `which types`, `what other ones`, and `show me more` after a catalog turn.
- Resolves conversational subjects from user-authored turns only, preventing assistant capitalization/price pollution.
- Preserves named-entity attribute follow-ups such as `Invisalign` + `treatment duration` while allowing explicit plural category switches such as `wardrobes`.
- Evaluates broad availability catalogs before permissive filter patterns.

### `backend/services/rag_service.py`

- Preserves relevance order after fusion instead of sorting by document/chunk position.
- Fetches enough lexical candidates before ranking instead of applying a database-order limit first.
- Adds simple singular variants for plural catalog terms (`wardrobes` → `wardrobe`).
- Replaces arbitrary leading-chunk catalog aggregation with lexical plus best-per-document semantic representatives.
- Applies structured item boosts, query-specific penalties, and navigation/footer noise penalties.
- Limits sibling expansion to strong/query-relevant seeds.
- Keeps broad catalog breadth while letting context assembly choose one useful representative per document.
- Retains canonical URL, source type, document metadata, and match reasons through retrieval-cache serialization.
- Builds customer-facing sources from final context evidence, not every retrieval candidate.
- Extracts direct item CTAs from structured Markdown headings using safe HTTP(S) validation.
- Suppresses unrelated sources for honest unknown/absent-item answers.
- Condenses the RAG instruction prompt while preserving injection defenses, strict grounding, factual brevity, catalog behavior, policy behavior, and canonical URL rules.
- Adds production trace timings for embedding, vector search, lexical search, RRF, context expansion, ranking, context compression, generation, critique, verification, polish, and source formatting.

### `backend/services/conversational_engine.py`

- For concrete catalog nouns, prefers structured matching item headings over prose that only mentions the noun.
- For broad umbrella catalogs, takes one representative chunk per document and asks for 8–15 high-level groups instead of dumping material/color/filter facets.
- Normalizes Markdown bullet whitespace deterministically.
- Removes the unsafe/expensive “repeated short phrase” polish trigger because valid product names/specifications can repeat words.
- Leaves critique enabled and verification conditional; polish still runs when a genuine style defect is detected.

### Tests and report

- Added `backend/test_phase_j_live_rag_quality.py`.
- Added this `PHASE_J_LIVE_RAG_QUALITY_REPORT.md`.

## Why the changes are domain-agnostic

No IKEA term, wardrobe name, storage rule, product name, or IKEA URL was added to runtime logic. The implementation uses generic signals already present across supported domains:

- user vs assistant message authorship;
- request verbs and list/follow-up grammar;
- structured Markdown item headings;
- lexical coverage and singular/plural variants;
- document diversity;
- navigation/footer noise patterns;
- canonical/source metadata;
- answer-supporting evidence selection.

The same behavior applies to products, SaaS plans, services, healthcare treatments, courses, properties, menu items, tours, legal offerings, and documentation/policy pages.

## Exact four-query before/after

### 1. `do you have hallway storage?`

Before:

> Yes, we offer shoe organisers that are suitable for hallways, with prices starting from Rs. 89.

Sources before: storage root + hallway shoe-cabinet page.  
Latency before: 24,086 ms.

After:

> Yes, IKEA offers practical hallway storage solutions, including shoe cabinets, shelves, and other compact storage to help organise shoes, bags, and everyday essentials.

Sources after: storage root, exact supporting chunk `48`.  
Latency after: 5,874 ms.

### 2. `what about wardrobes`

Before:

> We offer a range of wardrobes, including the PAX wardrobe system, which is a modular solution for clothes and comes with a 10-year warranty.

Sources before: storage root + unrelated shoe-cabinet page.  
Latency before: 12,915 ms.

After:

> Wardrobes are a type of storage that can help keep clothes, shoes, and accessories in order. They can be combined with other storage types based on your needs.

Sources after: storage root only, exact wardrobe FAQ/section evidence.  
Latency after: 4,082 ms.

### 3. `well wht all wardrobes do you have?`

Before:

> We offer the PAX wardrobe system, which is a modular solution that allows you to combine different elements to store clothes. It also comes with a 10-year warranty.

Sources before: storage root + unrelated bookcase page.  
Latency before: 14,354 ms.

After:

> IKEA offers the following wardrobes:
> - **BRIMNES** Wardrobe with 3 doors, white, 117x50x190 cm, Rs. 16,990
> - **PAX / BERGSBO** Wardrobe combination, dark grey dark grey/oak effect, 235x60x201 cm, Rs. 60,100
> - **PAX / MEHAMN/AULI** Wardrobe with sliding doors, dark grey double sided/light green mirror glass, 200x66x236 cm, Rs. 64,500
> - **NODELAND** Wardrobe with 3 doors, black-brown, 120x52x202 cm, Rs. 17,990
> - **PAX / STORKLINTA** Wardrobe combination, dark grey/dark brown stained oak effect, 150x60x236 cm, Rs. 79,050

Sources after: storage root only; five supporting chunk references and direct CTAs for all five products plus the parent category.  
Latency after: 5,445 ms.

### 4. `list items u have for storage?`

Before:

> We offer various storage items, including KUGGIS boxes, DRÖNA fabric boxes, DRÖNJÖNS metal mesh baskets, and FJÄDERHARV paperboard inserts.

Sources before: storage root + boxes/baskets + food storage, despite the narrow four-item answer.  
Latency before: 22,787 ms.

After:

> IKEA offers a variety of storage items, including:
> - **Storage boxes & baskets:** small storage & organisers, paper & media boxes, clothes boxes, children's boxes & baskets, baskets, secondary storage boxes, bathroom organisers, the Pudda range, and sustainable hand-woven baskets.
> - **Food storage & organising:** food containers, container sets, fridge organisers, pantry/worktop organisers, jars/tins, spice stands, bottles/mugs, cool bags, wine racks, mix-and-match containers/lids, and storage accessories.
> - **Hallway storage:** shoe cabinets, shelves, and compact storage.
> - **Wardrobes:** BRIMNES, PAX / BERGSBO, PAX / MEHAMN/AULI, NODELAND, and PAX / STORKLINTA.

Sources after: boxes/baskets + food storage + storage root; each source materially supports one grouped claim.  
Latency after: 7,557 ms.

Mean exact-query latency improved from 18,536 ms to 5,740 ms (69.0%).

## Final detailed latency profile

Model for generation: `gemini-2.5-flash`.  
Query resolution: deterministic; no LLM call.  
LLM calls per final exact query: one generation call.  
Critique: deterministic heuristic, always executed.  
Verification: conditional and not triggered for the final four answers.  
Polish: executed as a no-op without a second LLM call for the final four answers.

| Stage (ms) | Hallway | Wardrobe | Wardrobe list | Storage list |
|---|---:|---:|---:|---:|
| Cache lookup | 0 | 0 | 0 | 0 |
| Intent/query resolution | 109 | 111 | 109 | 104 |
| Embedding | 1,133 | 501 | 529 | 510 |
| Vector search | 397 | 306 | 384 | 390 |
| Lexical search | 613 | 125 | 112 | 326 |
| RRF | 0 | 0 | 0 | 0 |
| Sibling/context expansion | 151 | 178 | 112 | 113 |
| Final ranking | 2 | 2 | 4 | 3 |
| Combined retrieval | 2,378 | 1,195 | 1,224 | 1,426 |
| Context compression | 0 | 0 | 1 | 1 |
| Prompt build | 0 | 0 | 0 | 0 |
| Generation | 3,384 | 2,771 | 4,106 | 6,021 |
| Critique | 0 | 0 | 0 | 0 |
| Verify | not run | not run | not run | not run |
| Polish | 0 | 0 | 0 | 0 |
| Source formatting | 0 | 0 | 0 | 0 |
| **Total** | **5,874** | **4,082** | **5,445** | **7,557** |

All simple queries met the 3–8 second target in the final healthy-provider run. The complex catalog queries remained below 10 seconds.

## Cache findings

- Cache identity remains scoped by organization, bot, knowledge version, provider/model, recent history fingerprint, and bot configuration fingerprint.
- `what about wardrobes` resolves to `wardrobes`.
- `well wht all wardrobes do you have?` resolves to normalized catalog text and has a different history fingerprint.
- Retrieval-cache read-back now retains match reasons, canonical URL, source type, and document metadata.
- Live cold full wardrobe list: 8,361 ms in the explicit cache test.
- Immediate same-history repeat: 71 ms, `cache_hit=true`, identical answer, identical sources.
- A different conversation history produces a different cache identity; cache was not disabled.

## Unknown-question result

Live query: `do you sell kayaks?`

Final answer:

> I can only help with questions about IKEA India's storage and organisation products and services. I do not have details about kayaks.

Latency: 4,914 ms.  
Sources: none.  
Result: no hallucinated kayak facts and no unrelated storage page presented as evidence.

## Benchmarks and multi-domain regressions

### New Phase J benchmark

`backend/test_phase_j_live_rag_quality.py` contains:

- 40 natural-language router queries across factual, entity, catalog, filter, comparison, policy, and purchase modes;
- typos/casual forms and the exact four reported turns;
- assistant-capitalization poisoning protection;
- named-entity attribute follow-ups;
- relevance-order preservation;
- structured catalog enumeration vs incidental prose mentions;
- canonical/direct CTA source formatting;
- retrieval-cache provenance read-back;
- semantic-cache history/config isolation;
- no unrelated sources for unknown answers;
- deterministic no-LLM polish for harmless Markdown spacing.

Result: **11/11 tests passed**; all 40 router benchmark cases passed.

### Existing 50-query benchmark

Final result:

- retrieval success: **98.0% (49/50)**
- grounding success: **98.0% (49/50)**
- URL/CTA accuracy: **97.8% (44/45)**
- hallucination rate: **0.0%**
- retrieval p50: **801.47 ms**
- retrieval p95: **979.70 ms**
- worst: **1,237.41 ms**

The sole miss is an invalid fixture expectation: `Which products support fast charging?` expects `ApexBook Pro 16`, but that seeded laptop text contains no charging support claim. The implementation correctly retrieved the `PowerStation 100W` fast charger and did not fabricate laptop support. The benchmark's aggregate thresholds still passed; the test was not changed to hide the mismatch.

### Domain coverage

The final adversarial suite covers real estate, restaurant, travel, legal, policy, comparison, purchase/navigation, large corpus behavior, missing information, cache versioning, and strict tenant isolation. The RAG quality suite separately covers healthcare, university programs, SaaS, and course/documentation examples.

No IKEA-specific runtime behavior was introduced.

## Exact validation results

| Command/suite | Result |
|---|---|
| `backend/test_phase_j_live_rag_quality.py` | 11/11 passed in 0.014s |
| `backend/test_rag_pipeline.py` | 15 suites / 35 validations passed |
| `backend/test_rag_quality_hardening_suite.py` | 14/14 passed in 62.667s |
| `backend/test_customer_query_benchmark.py` | passed in 47.996s; metrics above |
| `backend/test_customer_readiness_adversarial_suite.py` | 12/12 passed in 117.857s |
| `backend/test_phase10_deep_coverage_suite.py` | 6/6 passed in 21.835s |
| `backend/test_phase_i_streaming_sources.py` | 2/2 passed |
| `backend/test_phase_e_widget_streaming_parity.py` | 16/16 passed |
| `backend/test_db_pool_cache_suite.py` | 11/11 passed |
| `backend/test_phase11_security_suite.py` | 8/8 passed in 31.882s |
| Python `py_compile` on changed services | passed |
| `git diff --check` on Phase J files | passed; only existing LF→CRLF notices |
| Local API `/health` after restart | `{"status":"alive"}` |
| In-app browser dashboard reload | loaded `Chatbot SaaS Dashboard`; no console errors |

`backend/test_phase10_hard_production.py` crawled 50/50 live IKEA pages successfully but then stopped at database ingestion because its legacy test bot was created without an organization. Phase A correctly rejects that state with HTTP 409. This is a stale test-fixture incompatibility, not a Phase J RAG regression, and the Phase A ownership invariant was not weakened. The test-created bot `1144` and its one empty document were removed after the failed run.

No TypeScript/build run was required because Phase J changed no frontend source or source-rendering component. The existing public/widget source and streaming suites passed.

## Remaining limitations

1. The dedicated wardrobe category page is not an active ready document. Current answers rely on structured product snippets in the storage root page. A later non-Phase-J crawl can improve coverage without changing retrieval logic.
2. Remote provider latency is variable. The final healthy run met targets, but Gemini network/provider variance can still exceed them.
3. Retrieval sub-stage timings round sub-millisecond RRF work to `0 ms`; this means below 1 ms, not skipped.
4. Source selection is evidence/context based rather than sentence-level citation alignment. It now removes unrelated candidate documents and unknown-answer sources, but it does not attach a separate citation to every sentence.
5. Very large catalogs still require pagination or a user-driven narrowing interaction for exhaustive presentation; Phase J deliberately returns representative high-level groups for broad umbrella requests.
6. The old Phase 10 hard-production fixture needs an organization assignment before that standalone ingestion test can complete under current security invariants. It was not modified in this phase.

## Scope confirmation

Phase J did not modify authentication, BYOK encryption, organization roles, quotas, Stripe, email, Redis/ARQ architecture, atomic knowledge promotion, widget session security, migrations, Firecrawl provider behavior, ingestion architecture, or frontend design. The temporary local Redis process was used only to measure the real cache/concurrency path.

## Final verdict

**LIVE CHAT QUALITY ACCEPTABLE FOR PILOT**

This verdict is based primarily on the final live answers, relevant customer-facing sources, unknown-question behavior, and measured cache-miss latency—not on synthetic tests alone.
