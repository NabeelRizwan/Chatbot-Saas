# Gemini vs Codex: Same-Evidence Control

Date: 2026-09-02

This report uses only the four completed audit turns recorded in `WOWMD_FINAL_RESPONSE_QUALITY_BASELINE.md`. No new chatbot request, retrieval, database query, provider call, frontend/widget test, or web lookup was performed.

## Control limitation

The saved audit captured the exact questions, conversation history, resolved queries, selected documents/chunks, structured evidence, final context sizes, visible sources, and production answers. It did **not** serialize the verbatim production bot/system instruction text. That text was not re-read or invented for this control.

The control answers therefore use the identical captured answerable evidence plus the response style specified for this control. They reliably test whether the supplied evidence could support a better answer, but they do not cleanly separate Gemini behavior from production response-policy effects.

**This Codex control is NOT a production OpenAI API benchmark.** It is only an offline control showing whether another capable model can produce a better answer from the same retrieved evidence. GPT API output will not necessarily match Codex.

## 1. Dashboard Q1

**QUESTION:**

> How much is Turmeric Boost?

**Captured input package:** No conversation history. Resolved query: `how much is turmeric boost`. Subject: Turmeric Boost, document 5129. Requested field: price. Structured evidence: `$33.00 USD`. Text evidence also contained `$33.00` one-time and `$31.35` Subscribe & Save. Visible source: Turmeric Boost.

**PRODUCTION GEMINI ANSWER:**

> The Turmeric Boost is $33.00 for a one-time purchase. It is also available for $33.00 with the Subscribe & Save option.

**CODEX CONTROL ANSWER:**

> Turmeric Boost is $33 for a one-time purchase, or $31.35 with Subscribe & Save.

| Criterion | Gemini | Codex control |
|---|---:|---:|
| Factual correctness | 3 | 5 |
| Completeness | 3 | 5 |
| Directness | 5 | 5 |
| Naturalness | 4 | 5 |
| Conciseness | 5 | 5 |
| Appropriate length | 5 | 5 |
| Conversational quality | 4 | 5 |
| Customer-support quality | 3 | 5 |

**BETTER: CODEX CONTROL**

**Classification: A. SAME EVIDENCE, CODEX MUCH BETTER.** The evidence was complete. Gemini assigned the wrong value to the subscription option. This is a generation/numeric-selection or response-policy failure, not a retrieval failure.

## 2. Dashboard Q2

**QUESTION:**

> Does Turmeric Boost contain ginger and black pepper, how should I take it, and how soon might I notice results?

**Captured input package:** No conversation history. Resolved query: `does turmeric boost contain ginger and black pepper, how should i take Turmeric Boost, and how soon might i notice results`. Subject: Turmeric Boost, document 5129. Requested fields: ingredients, directions, and results timeframe. Evidence contained Organic Ginger Extract Root, BioPerine® (Black Pepper Extract), one veggie capsule daily preferably with a meal, and a qualified 4–8 week timeframe. Visible source: Turmeric Boost.

**PRODUCTION GEMINI ANSWER:**

> Yes, Turmeric Boost contains Organic Ginger Extract Root and BioPerine® (Black Pepper Extract).
>
> To use it, take 1 veggie capsule daily, preferably with a meal, or as directed by your healthcare professional.
>
> Regarding results, some users may notice support for joint comfort or digestive balance within 4–8 weeks of consistent daily use, while others might need more time.

**CODEX CONTROL ANSWER:**

> Yes. Turmeric Boost contains Organic Ginger Extract Root and BioPerine® (Black Pepper Extract). Take 1 veggie capsule daily, preferably with a meal. Some users may notice joint-comfort or digestive-balance support within 4–8 weeks of consistent use, though results vary.

| Criterion | Gemini | Codex control |
|---|---:|---:|
| Factual correctness | 5 | 5 |
| Completeness | 5 | 5 |
| Directness | 5 | 5 |
| Naturalness | 5 | 5 |
| Conciseness | 4 | 5 |
| Appropriate length | 5 | 5 |
| Conversational quality | 5 | 5 |
| Customer-support quality | 5 | 5 |

**BETTER: ROUGHLY EQUAL**

**Classification: D. GEMINI EQUAL OR BETTER.** Both answers are correct, natural, concise, and complete. A provider change is unlikely to improve this case materially.

## 3. Widget Q1

**QUESTION:**

> What's the difference between Turmeric Boost and Turmeric Gummies?

**Captured input package:** No conversation history. Resolved query: `what's the difference between turmeric boost and turmeric gummies`. The contract recognized both product names but resolved only Turmeric Gummies as the subject. Final evidence contained six Turmeric Gummies chunks and no Turmeric Boost evidence. It supported Gummies ingredients, turmeric-ginger flavor, two-gummies-daily directions, and vegan/gluten-free/allergen-free attributes. No structured evidence or visible source was supplied.

**PRODUCTION GEMINI ANSWER:**

> I can provide you with details about our WOWMD® Turmeric Gummies, but I don't have any information on a product called "Turmeric Boost" in my catalog.
>
> Our Turmeric Gummies are formulated with turmeric root extract, curcumin, and black pepper extract to support joint flexibility, antioxidant wellness, healthy inflammatory response, and healthy-looking skin. They come in a turmeric-ginger flavor, and the recommended serving is two gummies daily, preferably after meals. They are also vegan, gluten-free, and allergen-free.

**CODEX CONTROL ANSWER:**

> I don't have enough information about Turmeric Boost to compare the two accurately. Turmeric Gummies contain turmeric root extract, curcumin, and black pepper extract; they have a turmeric-ginger flavor, are taken two daily after meals, and are listed as vegan, gluten-free, and allergen-free.

| Criterion | Gemini | Codex control |
|---|---:|---:|
| Factual correctness | 2 | 4 |
| Completeness | 1 | 1 |
| Directness | 2 | 4 |
| Naturalness | 3 | 4 |
| Conciseness | 3 | 4 |
| Appropriate length | 4 | 4 |
| Conversational quality | 3 | 4 |
| Customer-support quality | 2 | 4 |

**BETTER: CODEX CONTROL**

**Classification: B. BOTH MISS SAME FACT.** Neither answer can compare the products because Turmeric Boost evidence was absent. The control wording is more careful—it does not turn missing supplied evidence into the broader false claim that the product is absent from the catalog—but retrieval remains the binding limitation.

## 4. Widget Q2

**QUESTION:**

> Which one is cheaper, and how do I use each one?

**Captured input package:** History contained widget Q1 and its complete Gemini answer. Resolved query remained `which one is cheaper, and how do i use each one`. The contract recovered Turmeric Gummies and Turmeric Boost from history and requested price plus directions, but selected four Gummies chunks and two unrelated Sea Essence chunks. The final context contained no usable product price, no Turmeric Boost evidence, and only Gummies storage/interactions text rather than daily directions. No structured evidence or visible source was supplied.

**PRODUCTION GEMINI ANSWER:**

> I can only provide information about our WOWMD® Turmeric Gummies, as I don't have details on a product called "Turmeric Boost."
>
> Regarding Turmeric Gummies, I don't have the specific price listed in my current information. For usage, the available information includes general interactions and storage: keep out of reach of children, do not use if the safety seal is damaged or missing, and store in a cool, dry place. I don't have the specific daily serving directions at this time.

**CODEX CONTROL ANSWER:**

> I don't have the prices or daily-use directions needed to compare Turmeric Boost and Turmeric Gummies accurately.

| Criterion | Gemini | Codex control |
|---|---:|---:|
| Factual correctness | 1 | 4 |
| Completeness | 1 | 1 |
| Directness | 2 | 5 |
| Naturalness | 2 | 4 |
| Conciseness | 2 | 5 |
| Appropriate length | 2 | 5 |
| Conversational quality | 2 | 4 |
| Customer-support quality | 1 | 4 |

**BETTER: CODEX CONTROL**

**Classification: B. BOTH MISS SAME FACT.** The required prices and directions were not in the final supplied evidence, so neither model could answer. Gemini additionally mistook storage warnings for usage information and repeated an unsupported catalog-level claim. The control avoids irrelevant detail, but it cannot repair the retrieval failure.

## Final summary

1. **Questions limited by retrieval:** 2 of 4 (widget Q1 and widget Q2).
2. **Questions limited mainly by response style:** 0 of 4. Widget wording had style defects, but retrieval was the primary constraint. Dashboard Q1 was a generation/numeric-selection error rather than merely tone or verbosity.
3. **Questions with clearly better Codex-control wording:** 3 of 4 (dashboard Q1, widget Q1, and widget Q2).
4. **Did Gemini ever outperform Codex control?** No. It was roughly equal on dashboard Q2.
5. **Next best step:** **A. Fix retrieval.** The two most serious failures lacked the required product evidence. After that, address deterministic price-role handling; only then is a provider A/B test diagnostic.
6. **Would switching providers alone likely solve the problem?** **NO.** A different model cannot recover facts excluded from the final context. It might improve caution, concision, and the dashboard price selection, but it would not solve the two core widget failures.
