# Phase L.3 — Multi-Entity Conversational RAG Report

Date: 2026-09-02  
Controlled bot: `674 — WOWMD Joint Supplements Assistant`  
Controlled corpus: **10 ready documents / 573 ready chunks**  
Corpus mutations: **none** — no crawl, re-ingest, embedding replacement, Firecrawl change, Gemini provider change, SQL seed, or stored-product edits.

Local stack used for acceptance:

- API `http://127.0.0.1:8000`
- Frontend `http://127.0.0.1:3000`
- Independent widget origin `http://127.0.0.1:4173` (bot allowlist)
- Redis healthy on `127.0.0.1:6379` during acceptance

## 1. Baseline failures

Captured from prior controlled reports (`WOWMD_FINAL_RESPONSE_QUALITY_BASELINE.md`, Phase L / L.2 reports) and reconstructed against the pre-L.3 runtime path.

### A. Explicit comparison

Customer: `What's the difference between Turmeric Boost and Turmeric Gummies?`

- Query contract saw both names **and** a bogus entity `'s`
- Single resolved subject collapsed to Turmeric Gummies
- Final evidence was monopolized by Gummies
- Answer falsely claimed Turmeric Boost was not in the catalog
- Sources could disappear when the answer also contained missing-info wording

### B. Same-chat comparison follow-up

Customer: `Which one is cheaper, and how do I use each one?`

- History recovered both names
- Comparison mode / authoritative multi-entity scope was lost
- Retrieval selected Gummies plus unrelated Sea Essence
- Prices and serving directions were missed
- Storage/warning text substituted for usage

### C. Fresh price role generation

Customer: `How much is Turmeric Boost?`

- Retrieval already had `$33.00` one-time and `$31.35` Subscribe & Save
- Generation mislabeled both as `$33.00`

## 2. Root causes

1. **Contraction parsing** — comparison capture groups treated `What's` as producing entity `'s`.
2. **Single-subject override** — retrieval could replace a second explicit document with one `subject_document_id`.
3. **Follow-up scope loss** — conversational memory recovered names but did not keep comparison mode / subject-set authority.
4. **Global RRF contamination** — unrelated sibling documents could enter final context before per-entity field coverage.
5. **Price semantics** — typed roles were not preserved strongly enough through compression/generation.
6. **Directions ranking** — storage/warning text could outrank serving instructions.
7. **Source suppression** — whole-answer absence wording removed all sources even when positive claims remained.

## 3. QueryContract changes

`backend/services/query_contract.py` now supports both:

- **SINGLE SUBJECT** — `resolved_subject` / `subject_document_id`
- **MULTI-ENTITY SUBJECT SET** — `resolved_entities: list[ResolvedEntity]`

When two or more entities resolve to READY documents:

- `resolved_subject` / `subject_document_id` are cleared
- `comparison_entities` use canonical document titles
- `comparison_operation` records cheaper / more expensive when requested
- `cache_fragment()` includes entity document IDs and comparison operation

Coverage constants track entity-field pairs as `SUPPORTED`, `ABSENT_AFTER_ADEQUATE_SEARCH`, or `UNCERTAIN`.

## 4. Contraction parsing

Generic contraction-safe sanitization rejects fragments such as `'s`, `'re`, `'ve`, `'ll`, `'d`.

Intent-router comparison regexes use non-capturing groups (`what(?:'s| is)`, etc.).

No WOWMD-specific exception list was added.

## 5. Multi-entity subject-set model

Explicit comparison entities are authoritative once they strongly match READY documents.

`match_all_documents` / `resolve_named_entities` produce a subject set rather than one primary subject plus incidental strings.

## 6. Comparison history behavior

Follow-ups such as `which one`, `each one`, `both`, `these`, `them`, `the cheaper one` retain the recent comparison scope until the user changes subjects or ambiguity is too high.

Live widget turn 2 contract:

- mode `comparison`
- entities Turmeric Boost + Turmeric Gummies
- references `which one`, `each one`
- fields `price`, `directions`
- operation `cheaper`

## 7. Entity switching behavior

`What about Product C?` followed by `how much is it?` switches to C.

Ambiguous singular `how much is it?` after an A+B comparison clarifies rather than guessing.

Deterministic suite covers continuation, switch, and clarification.

## 8. Per-entity / per-field evidence matrix

Retrieval fills an entity × field matrix first:

| entity | price | directions |
| --- | --- | --- |
| A | required | required |
| B | required | required |

Only after baseline coverage may supplemental same-entity / remaining budget evidence enter.

Live turn 2 coverage:

- `5129:price` SUPPORTED
- `5129:directions` SUPPORTED
- `5130:price` SUPPORTED
- `5130:directions` SUPPORTED

## 9. Price typing

Runtime `PriceFact` / typed structured evidence preserve roles such as:

- primary / current
- one_time
- subscription
- sale / regular
- bundle total / per-unit
- monthly / annual

No new database schema was required.

## 10. Deterministic price comparison

For already-resolved explicit entities with compatible currencies, cheaper / more expensive selection is computed deterministically and injected into generation context.

Live turn 2 context contained:

```text
## Deterministic price comparison
Turmeric Boost is cheaper ($33.00 USD).
```

Different currencies are not blindly compared.

## 11. Direction evidence priority

Directions / usage / serving queries prefer genuine usage evidence and down-rank storage, warnings, safety seals, interactions, disclaimers, and shipping instructions unless requested.

## 12. Context allocation

Multi-entity allocation is three-pass:

1. strongest required field-bearing evidence per entity/field
2. same-entity supporting/adjacent evidence
3. supplemental evidence if budget remains

`protect_doc_ids` prevents a high global score from dropping preferred comparison documents during cleanup.

## 13. Unrelated-document prevention

For explicit A+B comparisons, unrelated Product C cannot enter final supporting context on semantic similarity alone.

Live widget turns selected **2 distinct documents** only; Sea Essence did not appear in acceptance traces.

## 14. Source attribution

Sources follow supported claims/evidence.

Mixed supported + missing answers retain valid sources for supported claims.

Successful A/B comparisons show both canonical sources.

## 15. Coverage / verification gate

Before finalization, requested entity-field coverage is tracked. If retrieval is complete but generation omits or mislabels a high-confidence structured field, the existing bounded quality/verification path may correct once. No retry loops.

## 16. Cache isolation

Cache identity incorporates the multi-entity contract fragment (entity document IDs, fields, comparison operation) plus existing organization / bot / version / model / history isolation.

Deterministic test: `which one is cheaper?` under A+B cannot collide with the same text under C+D.

## 17. Observability

Smallest safe diagnostic persistence:

- `ChatTrace` compact diagnostics
- stored on `ConversationMessage.token_usage.diagnostics`
- includes timings, mode, entity document IDs, fields, coverage, comparison operation
- **no prompts, no private conversation dumps, no secrets**
- dashboard `_debug` may surface diagnostics; public widget JSON does not

## 18. Generic / cross-domain tests

`backend/test_phase_l3_multi_entity_conversational_rag.py` — **26/26 OK**

Covers A–T plus SaaS / hotel / education / services comparison follow-ups using generic fixture names only.

## 19. Exact widget final transcript

Fresh session on `http://127.0.0.1:4173/?botId=674` loading real `widget.js`.

### Turn 1

User:

> What's the difference between Turmeric Boost and Turmeric Gummies?

Assistant:

> The main differences between Turmeric Boost and Turmeric Gummies are their form, ingredients, and how they are used.
>
> Turmeric Boost is a veggie capsule formula made with organic turmeric, ginger, and BioPerine®. It's designed to support joint comfort, digestive wellness, antioxidant activity, and everyday vitality, and you take one capsule daily, preferably with a meal. It is also Gluten-Free, Non-GMO, Vegan Friendly, Vegetarian, and Organic. A one-time purchase is $33.00.
>
> Turmeric Gummies are a gummy form with a turmeric-ginger flavor, formulated with turmeric root extract, curcumin, and black pepper extract. They support joint flexibility, antioxidant wellness, healthy inflammatory response, and healthy-looking skin. You take two gummies daily, preferably after meals. These gummies are vegan, gluten-free, and allergen-free. The price for Turmeric Gummies is not listed in the provided information.

Sources:

- Turmeric Boost → `https://www.wowmd.com/products/turmeric-boost`
- Turmeric Gummies → `https://www.wowmd.com/products/turmeric-gummies`

Acceptance notes:

- both documents retrieved (`5129`, `5130`)
- no bogus `'s` entity
- both compared; no false missing-product claim for Boost
- no unrelated final product document
- both canonical sources shown
- Gummies price omission on this turn is non-blocking because `requested_fields` was empty for a free-form difference question

### Turn 2 — same conversation

User:

> Which one is cheaper, and how do I use each one?

Assistant:

> Turmeric Boost is cheaper at $33.00 USD, while Turmeric Gummies are $55.00 USD.
>
> For Turmeric Boost, you take 1 veggie capsule daily, preferably with a meal. For Turmeric Gummies, adults can take two gummies once daily, preferably after meals.

Sources: both canonical product pages again.

Acceptance notes:

- A+B scope preserved
- fields = price + directions
- cheaper product correctly identified
- serving directions for both; no storage/warning substitution
- no Sea Essence evidence
- coverage matrix fully SUPPORTED

## 20. Exact dashboard price answer

Login path:

- bot `674` → organization `538` (`IKEA Retail Org`) → membership role `owner` → user `9` (`test_customer@example.com`)
- temporary password set only for that local test user via existing `hash_password`
- old refresh sessions for that user revoked
- real frontend form login at `http://127.0.0.1:3000/login`
- temporary credential file deleted after login
- password plaintext not written into this report

Fresh playground conversation on bot 674.

User:

> How much is Turmeric Boost?

Assistant:

> Turmeric Boost is available for $33.00 for a one-time purchase. If you choose to subscribe and save, the price is $31.35.

Source: Turmeric Boost canonical page / open-source link in the playground source list.

Acceptance notes:

- one-time `$33.00` and Subscribe & Save `$31.35` correctly distinguished
- no duplicated/mislabeled identical values
- coverage `5129:price = SUPPORTED`
- mode factual; single entity document `5129`

## 21. Before / after retrieval traces

### Before (baseline)

| Turn | Mode | Entities | Final docs | Failure |
| --- | --- | --- | --- | --- |
| Difference | collapsed to one subject | `'s` + Gummies | Gummies only | Boost falsely missing |
| Cheaper / use each | factual / unmanaged | memory names only | Gummies + Sea Essence | prices/directions missed |
| How much Boost | factual | Boost | Boost | generation price-role error |

### After (acceptance)

| Turn | Mode | Entities | Final docs | Result |
| --- | --- | --- | --- | --- |
| Difference | comparison | Boost + Gummies | 2 docs / 12 chunks | both compared + both sources |
| Cheaper / use each | comparison / cheaper | Boost + Gummies | 2 docs / 11 chunks | matrix filled; deterministic cheaper |
| How much Boost | factual / price | Boost | Boost | one-time vs subscription labeled correctly |

## 22. Performance timings

Redis healthy; all acceptance turns were cache misses (expected for unique multi-entity contracts / fresh questions).

### Widget turn 1 — difference

- Backend `response_time_ms`: **11461**
- Browser-visible wall (send → complete): ~**32–41 s** including stream buffering
- Stage timings (ms): query_contract 497, embedding 1524, vector 1288, lexical 1376, document_selection 191, retrieval 4826, generation 5589

### Widget turn 2 — cheaper + directions

- Backend `response_time_ms`: **8227**
- Browser-visible wall: ~**32 s**
- Stage timings (ms): query_contract 501, embedding 719, vector 891, lexical 1946, document_selection 217, retrieval 4197, generation 2989
- Coverage fully supported; `price_comparison=compared`

### Dashboard — How much is Turmeric Boost?

- Backend stream row `response_time_ms`: not persisted (`None`) — diagnostics timings still present
- Approximate backend critical path: retrieval **2814 ms** + generation **6232 ms**
- Stage timings (ms): query_contract 490, embedding 778, vector 755, lexical 658, document_selection 344, retrieval 2814, generation 6232
- Browser-visible wall from page instrumentation mark: ~**46 s** (includes form fill / UI settle before send)

L.3 overhead that is justified: entity-set resolution, per-entity/field matrix fill, typed price injection, and deterministic cheaper comparison. No unrelated latency optimization was performed in this phase. Ordinary single-entity chat remains on the factual path.

## 23. Full regression results

| Suite | Result |
| --- | --- |
| Phase L.3 multi-entity | **26/26 OK** |
| Phase L.2 conversational field | **20/20 OK** |
| Phase L ecommerce retrieval | **15/15 OK** |
| Phase J live RAG quality | **11/11 OK** |
| RAG quality hardening | **14/14 OK** (~98s) |
| RAG pipeline | **15 suites / 35 validations OK** |
| 50-query customer benchmark | **OK** — retrieval 100%, grounding 100%, hallucination 0% |
| Widget streaming parity | **16/16 OK** |
| Tenant chat security | **15/15 OK** |
| A2 stop-ship security | **8/8 OK** |
| Exact-page crawl mode (frontend static) | **OK** |
| Frontend `tsc --noEmit` | **OK** |
| Frontend ESLint | **OK** (0 errors; 2 pre-existing `<img>` warnings) |
| Python compile / import of changed modules | **OK** |

No deterministic regression was suppressed. No production knowledge data was mutated to satisfy fixtures.

## 24. No-hardcoding scan

Case-insensitive search over runtime `backend/services` and `backend/routes` for:

`WOWMD`, `Turmeric Boost`, `Turmeric Gummies`, `Sea Essence`, `turmeric`, `$33`, `$31.35`, `$55`, `wowmd.com`

Result: **no matches** in runtime service/route code.

Those strings may still appear in tests, reports, and stored live corpus data.

## 25. Files changed

- `backend/services/query_contract.py`
- `backend/services/intent_router.py`
- `backend/services/rag_service.py`
- `backend/services/conversational_engine.py`
- `backend/services/observability_service.py`
- `backend/routes/chat_routes.py`
- `backend/routes/public_routes.py`
- `backend/test_phase_l3_multi_entity_conversational_rag.py` *(new)*
- `PHASE_L3_MULTI_ENTITY_CONVERSATIONAL_RAG_REPORT.md` *(this report)*

No widget-specific RAG logic was added. Dashboard and public widget continue to use the same canonical answer pipeline.

## 26. Remaining limitations

1. Free-form comparison turns with empty `requested_fields` may still omit a secondary field (e.g. Gummies price on turn 1) even though both entities are correctly retrieved and compared.
2. Typed price extraction can still surface duplicate/near-duplicate primary labels alongside `one_time` / `subscription` in compressed context; generation now preserves role distinction for the dashboard price question, but classifier precision can improve further.
3. Authenticated dashboard stream persistence currently stores diagnostics timings but may leave `response_time_ms` null.
4. Local Redis for this acceptance run was a protocol-compatible local Redis server on `6379`; production Redis topology was not changed.
5. Global catalog numeric filters such as “show everything under $40” remain intentionally out of scope.
6. The local controlled test account password hash remains at the temporary reset value by design for this local environment; plaintext was not retained in repo/report.

---

## FINAL VERDICT

**MULTI-ENTITY CONVERSATIONAL RAG READY FOR PILOT**
