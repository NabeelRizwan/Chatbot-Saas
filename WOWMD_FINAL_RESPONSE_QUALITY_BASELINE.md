# WOWMD Final Response-Quality Baseline

Date: 2026-09-02

Exactly four customer questions were submitted: two through the dashboard playground and two through one fresh external-widget session. No other chatbot questions were asked. The corpus, prompts, RAG code, model, embeddings, frontend, and widget were not changed.

# 1. Environment

| Component | Verified state |
|---|---|
| Backend | Current local source at `http://127.0.0.1:8000`; `/health` and `/health/ready` returned 200 |
| Frontend | Current real Next.js frontend at `http://127.0.0.1:3000`; dashboard showed backend target `http://127.0.0.1:8000` |
| Widget website/origin | Existing independent customer-site origin `http://127.0.0.1:4173`, the only origin currently persisted in bot 674's allowlist; it loaded the real current `widget.js` from port 3000 and public API from port 8000 |
| PostgreSQL/Supabase | Healthy; database and Alembic readiness passed |
| Redis | Healthy Redis-compatible local test runtime on `127.0.0.1:6379`; PING succeeded; slow log length 0; no Redis error statistics or rejected/failed commands |
| ARQ worker | Running; `chatbot-saas:ingestion-worker:heartbeat` existed with a live TTL |
| Provider/model | Gemini; `gemini-2.5-flash` generation and `gemini-embedding-001` query embeddings |
| Bot | 674 — WOWMD Joint Supplements Assistant; status `active` |
| Corpus | 10 READY/completed documents and 573 READY chunks; unchanged |
| Browser errors | No dashboard or widget console warnings/errors during the four turns |

Deployment limitation: no live Internet deployment was available—the existing Railway backend remains stopped from the previously reported expired-plan blocker. Bot 674's only persisted external origin is the independent local customer site at `http://127.0.0.1:4173`. The audit therefore used that actual configured origin with the real current embedded widget contract; it did not use a mocked chat component or call the public chat API directly.

Redis did not enter timeout fallback. Across the complete run, Redis command execution reported by `INFO commandstats` was measured in microseconds per command (selected averages: GET 2.89 µs, SET 13.39 µs, EVAL 48.30 µs, PING 1.29 µs). These are server execution times, not full application-stage timers.

# 2. Difficult question selected

## Question

> Does Turmeric Boost contain ginger and black pepper, how should I take it, and how soon might I notice results?

## Why it is difficult

This is a normal pre-purchase question requiring one entity to be resolved and three requested fields to be combined from separate sections: ingredients, directions, and a qualified results timeframe.

## Gold evidence

Source document: **Turmeric Boost**, document 5129, `https://www.wowmd.com/products/turmeric-boost`.

| Evidence | Gold fact |
|---|---|
| Chunk 9164, Ingredients | Organic Ginger Extract (Zingiber officinale) Root and BioPerine® (Black Pepper Extract) are listed; the complete list also contains Organic Turmeric Root and Turmeric 95% Curcuminoids Root |
| Chunk 9175, How to Use | Take 1 veggie capsule daily, preferably with a meal, or as directed by a healthcare professional |
| Chunk 9166, Results FAQ | Individual results vary; some users may notice support for joint comfort or digestive balance within 4–8 weeks of consistent daily use, while others may need more time |

This gold answer was recorded before the question was submitted and was not supplied to the chatbot.

# 3. Dashboard Q1

## Exact question

> How much is Turmeric Boost?

## Exact answer

> The Turmeric Boost is $33.00 for a one-time purchase. It is also available for $33.00 with the Subscribe & Save option.

Displayed source: **Turmeric Boost**.

## Retrieval summary

- Resolved subject: Turmeric Boost, document 5129, confidence 1.0.
- Intent/mode: `knowledge_query` / `factual`.
- Requested field: `price`.
- Cache: miss.
- Selected four chunks from one document: structured price pseudo-chunk `-5129991`, then chunks 9163, 9160, and 9161.
- Structured metadata supplied `$33.00 USD`.
- Chunk 9163 explicitly supplied `$33.00` one-time and `$31.35` Subscribe & Save.
- The 3,476-character final context therefore contained the correct facts. The answer selected the wrong value for the subscription price.
- Reconstructed final prompt: 6,921 characters, 787 words, approximately 1,731 tokens before provider tokenization.
- Calls: one Gemini embedding call and one main Gemini generation call. Critique ran heuristically; verification was not triggered; polish was a heuristic no-op. No retry was logged.

## Timing

| Measurement | Result |
|---|---:|
| Backend persisted wall time | 16,900 ms |
| Browser-visible time | Approximately 17 seconds; the UI rendered after the backend response and displayed 16,900 ms |
| Redis | Healthy; no timeout/error; per-request aggregate not exported |
| Query/retrieval sub-stages | Invoked, but exact milliseconds were not retained outside the in-memory `ChatTrace` |
| Gemini generation | Invoked once; exact duration was not exported for this turn |
| Persistence/usage/response assembly | Included in total; exact split not exported |

## Quality scores

| Criterion | Score / 5 |
|---|---:|
| Factual correctness | 3 |
| Retrieval completeness | 5 |
| Directness | 5 |
| Natural/human wording | 4 |
| Appropriate answer length | 5 |
| Conversation awareness | 5 |
| Source accuracy | 5 |
| Formatting/readability | 5 |

**GOOD LENGTH · NATURAL**

Problem: the response is admirably direct, but it converts the correct `$31.35` subscription evidence into `$33.00`. Root cause: **NUMERIC REASONING / GENERATION**, with additional risk from ambiguous price labeling in compressed context. Retrieval itself was complete.

# 4. Dashboard Q2

## Exact question

> Does Turmeric Boost contain ginger and black pepper, how should I take it, and how soon might I notice results?

## Exact answer

> Yes, Turmeric Boost contains Organic Ginger Extract Root and BioPerine® (Black Pepper Extract).
>
> To use it, take 1 veggie capsule daily, preferably with a meal, or as directed by your healthcare professional.
>
> Regarding results, some users may notice support for joint comfort or digestive balance within 4–8 weeks of consistent daily use, while others might need more time.

Displayed source: **Turmeric Boost**.

## Retrieval summary

- Fresh dashboard conversation; no previous messages were supplied.
- Resolved subject: Turmeric Boost, document 5129, confidence 1.0.
- Intent/mode: `knowledge_query` / `factual`.
- Requested fields: `ingredients`, `directions`, `results_timeframe`.
- Cache: miss.
- Selected four chunks from one document: 9166 (results), 9164 (ingredients), 9163 (directions/product block), and sibling 9190 (survey context).
- Per-field selection explicitly found all three requested fields; no structured metadata was needed.
- Final context: 3,388 characters.
- Reconstructed final prompt: 6,954 characters, 886 words, approximately 1,739 tokens.
- Calls: one Gemini embedding call and one main Gemini generation call. Critique ran heuristically; verification was not triggered; polish was a heuristic no-op. No retry was logged.

## Timing

| Measurement | Result |
|---|---:|
| Backend persisted wall time | 7,611 ms |
| Browser-visible time | About 8 seconds; captured in the 5–10 second observation window |
| Redis | Healthy; no timeout/error; per-request aggregate not exported |
| Query/retrieval sub-stages | Invoked; exact milliseconds not retained externally |
| Gemini generation | Invoked once; exact duration not exported |
| Persistence/usage/response assembly | Included in total; exact split not exported |

## Quality scores

| Criterion | Score / 5 |
|---|---:|
| Factual correctness | 5 |
| Retrieval completeness | 5 |
| Directness | 5 |
| Natural/human wording | 5 |
| Appropriate answer length | 5 |
| Conversation awareness | 5 |
| Source accuracy | 5 |
| Formatting/readability | 5 |

**GOOD LENGTH · NATURAL**

No material answer-quality problem. It answers first, qualifies the timeframe correctly, contains no retrieval jargon, and does not over-explain.

# 5. Widget Q1

## Exact question

> What's the difference between Turmeric Boost and Turmeric Gummies?

## Exact answer

> I can provide you with details about our WOWMD® Turmeric Gummies, but I don't have any information on a product called "Turmeric Boost" in my catalog.
>
> Our Turmeric Gummies are formulated with turmeric root extract, curcumin, and black pepper extract to support joint flexibility, antioxidant wellness, healthy inflammatory response, and healthy-looking skin. They come in a turmeric-ginger flavor, and the recommended serving is two gummies daily, preferably after meals. They are also vegan, gluten-free, and allergen-free.

Displayed sources: **none**.

## Retrieval summary

- Fresh external widget session; no prior conversation history.
- Query contract identified comparison entities `"turmeric boost"` and `"turmeric gummies"`, but also incorrectly extracted `"'s"` from “What's”.
- The resolver set Turmeric Gummies as the single resolved subject (document 5130).
- Intent/mode: `comparison` / `comparison`; requested fields were empty.
- Cache: miss.
- Selected six chunks, all from Turmeric Gummies: 9227, 9253, 9225, 9221, 9223, and 9254.
- Turmeric Boost document 5129 was excluded before final selection, so the generator could not compare the products.
- Final context: 3,930 characters; zero structured metadata candidates.
- Estimated final prompt size from the captured context is about 7,200 characters / 1,800 tokens.
- Calls: one Gemini embedding call and one main Gemini generation call. Critique ran heuristically; the “don't have” wording caused the heuristic to accept the answer. Verification was not triggered; polish was a heuristic no-op. No retry was logged.

## Timing

| Measurement | Result |
|---|---:|
| Backend persisted wall time | 6,871 ms |
| Browser-visible time | Approximately 7 seconds |
| SSE/buffering | Widget used `/public/chat/674/stream`; the backend generated the complete answer before emitting 48-character token blocks |
| Redis | Healthy; no timeout/error; per-request aggregate not exported |
| Query/retrieval/generation sub-stages | Invoked; exact milliseconds not retained externally |

## Quality scores

| Criterion | Score / 5 |
|---|---:|
| Factual correctness | 2 |
| Retrieval completeness | 1 |
| Directness | 2 |
| Natural/human wording | 3 |
| Appropriate answer length | 4 |
| Conversation awareness | 3 |
| Source accuracy | 1 |
| Formatting/readability | 4 |

**GOOD LENGTH · ACCEPTABLE**

Problems: it fails the comparison, falsely claims Turmeric Boost is absent, and provides no visible source. The Gummies paragraph is readable and grounded, but answering about only one product is not on-point. Root cause: **QUERY UNDERSTANDING / ENTITY RESOLUTION / RETRIEVAL / FIELD COVERAGE / SOURCE ATTRIBUTION**.

# 6. Widget Q2

## Exact question

> Which one is cheaper, and how do I use each one?

## Exact answer

> I can only provide information about our WOWMD® Turmeric Gummies, as I don't have details on a product called "Turmeric Boost."
>
> Regarding Turmeric Gummies, I don't have the specific price listed in my current information. For usage, the available information includes general interactions and storage: keep out of reach of children, do not use if the safety seal is damaged or missing, and store in a cool, dry place. I don't have the specific daily serving directions at this time.

Displayed sources: **none**.

## Retrieval summary

- Same widget session; history contained widget Q1 and its answer.
- The query contract recovered both entity names from history: Turmeric Gummies and Turmeric Boost.
- It nevertheless classified the turn as `knowledge_query` / `factual`, with no resolved subject, instead of preserving a two-entity comparison.
- Requested fields: `price`, `directions`.
- Cache: miss.
- Selected six chunks from two documents, but the second document was unrelated Sea Essence Omega 3 Fish Oil—not Turmeric Boost.
- Selected chunks: Gummies 9228, 9256, 9259, 9260; Sea Essence 9282 and 9288.
- The only direction-like Gummies chunk selected was storage/interactions chunk 9260. Price metadata, price chunk 9226, usage chunk 9235, and all Turmeric Boost evidence were absent.
- Final context: 3,137 characters; zero structured metadata candidates.
- Reconstructed final prompt: 7,122 characters, 896 words, approximately 1,781 tokens.
- Calls: one Gemini embedding call and one main Gemini generation call. Critique ran heuristically; the repeated “don't have” acknowledgements allowed it to pass. Verification was not triggered; polish was a heuristic no-op. No retry was logged.

Gold comparison available in storage but not retrieved:

- Turmeric Boost: `$33.00` one-time or `$31.35` Subscribe & Save; take 1 veggie capsule daily, preferably with a meal.
- Turmeric Gummies: `$55.00` for one bottle; take two gummies once daily, preferably after meals.
- Therefore Turmeric Boost is cheaper under the listed single-bottle prices.

## Timing

| Measurement | Result |
|---|---:|
| Backend persisted wall time | 18,858 ms |
| Browser-visible time | Approximately 19 seconds |
| SSE/buffering | Full answer was generated before simulated token delivery |
| Redis | Healthy; no timeout/error; per-request aggregate not exported |
| Query/retrieval/generation sub-stages | Invoked; exact milliseconds not retained externally |

## Quality scores

| Criterion | Score / 5 |
|---|---:|
| Factual correctness | 1 |
| Retrieval completeness | 1 |
| Directness | 2 |
| Natural/human wording | 2 |
| Appropriate answer length | 3 |
| Conversation awareness | 2 |
| Source accuracy | 1 |
| Formatting/readability | 4 |

**TOO LONG FOR THE INFORMATION DELIVERED · ROBOTIC**

Problems: it fails the numeric comparison, fails both use directions, repeats the false Turmeric Boost absence claim, substitutes storage warnings for directions, and shows no sources. Root cause: **FOLLOW-UP RESOLUTION / RETRIEVAL / FIELD COVERAGE / CONTEXT SELECTION / STRUCTURED METADATA / NUMERIC REASONING / SOURCE ATTRIBUTION**.

# 7. Conversation-memory result

Widget turn 2 partially remembered the conversation: the query contract recovered both Turmeric Gummies and Turmeric Boost from history. It did not operationalize that memory correctly. The turn fell back to factual mode with no resolved subject, so document selection lost both the intended comparison constraint and field-complete retrieval. Memory extraction passed; memory-guided retrieval failed.

# 8. Retrieval findings

What worked:

- Single-entity resolution was exact for both dashboard questions.
- Dashboard Q1 retrieved both the list price and discounted subscription price.
- Per-field evidence retrieval successfully assembled ingredients, directions, and results-timeframe evidence for dashboard Q2.
- Tenant/bot filters held: all selected chunks belonged to bot 674's READY corpus.
- Redis, database, vector model compatibility, and provider operation were healthy.

What did not:

- The comparison parser treated the contraction suffix `"'s"` as an entity.
- A resolved single subject overrode the explicit two-product comparison, excluding Turmeric Boost in widget Q1.
- Widget Q2 recovered two entities but did not retain comparison mode or constrain selection to those two documents.
- Requested `price` and `directions` fields did not force structured price evidence and best direction chunks for each entity.
- Sibling expansion introduced reviews, interactions, and an unrelated Sea Essence document while omitting the requested evidence.
- The source formatter emitted no widget sources for answers containing “don't have”, even when the answer also made positive product claims.

# 9. Response-style findings

- No answer used “According to the available information”, “Based on the provided context”, retrieval jargon, excessive headings, or unnecessary bullet lists.
- Dashboard Q1 and Q2 were direct and appropriately short.
- Dashboard Q2 sounded natural and customer-facing.
- Widget Q1 and Q2 used defensive catalog disclaimers before answering. The wording was acceptable in isolation, but robotic and misleading because the supposedly missing data exists.
- Widget Q2 repeated the prior turn's false absence statement and then over-explained missing information instead of answering first.
- No medically overconfident advice was produced.
- The main style defects were downstream of missing context; they should not be treated as prompt-only problems.

# 10. Latency findings

## Total timing

| Turn | Backend wall time | Browser-visible time | Cache | Context | Provider calls |
|---|---:|---:|---|---:|---:|
| Dashboard Q1 | 16,900 ms | ~17 s | Miss | 3,476 chars | 2 |
| Dashboard Q2 | 7,611 ms | ~8 s | Miss | 3,388 chars | 2 |
| Widget Q1 | 6,871 ms | ~7 s | Miss | 3,930 chars | 2 |
| Widget Q2 | 18,858 ms | ~19 s | Miss | 3,137 chars | 2 |

The two-provider-call count is determined from the exercised control flow: one query embedding plus one main answer generation. Critique was heuristic, verification was not invoked, and polish returned through its heuristic/no-op path. No provider retry, Redis retry, or timeout appeared in the captured runtime logs.

## Stage availability

| Stage | Audit result |
|---|---|
| Request/auth/quota | Invoked and successful; exact ms not externally exported |
| Query contract/history/entity resolution | Captured in full; exact ms not retained externally |
| Cache lookup | Miss on all four; exact ms not retained externally |
| Redis/rate limit/semaphore | Healthy; zero slow/error records; exact per-turn aggregate unavailable |
| Embedding | One Gemini call per turn; exact duration unavailable |
| Vector search | Invoked; exact duration unavailable |
| Lexical search | Invoked; exact duration unavailable |
| Document selection | Decisions captured; exact duration unavailable |
| Per-field/metadata evidence | Evidence captured; exact duration unavailable |
| RRF/reranking/expansion | Selected results and reasons captured; exact duration unavailable |
| Compression/context build | Final size captured; exact duration unavailable |
| Prompt build | Reconstructed size captured; exact duration unavailable |
| Main generation | One `gemini-2.5-flash` call; exact duration unavailable |
| Critique | Invoked as heuristic; exact duration unavailable |
| Verification | Not invoked |
| Polish | Invoked but heuristic/no-op; no LLM call |
| Source formatting | Result captured; exact duration unavailable |
| DB persistence/usage | Successful and included in backend total; exact split unavailable |
| SSE/browser delivery | Widget buffered the completed answer, then emitted fixed token blocks; exact browser overhead unavailable |

The application calculates detailed stage timings in `ChatTrace`, but dashboard code discards `_debug.timings_ms`, widget responses do not return it, and conversation records store only total `response_time_ms`. Because this audit prohibited code changes, unavailable stage timings were not fabricated. This is itself an observability gap.

Redis is not a meaningful latency contributor in this run. The unexplained variation between 6.9–7.6 seconds and 16.9–18.9 seconds lies inside stages whose per-turn timing is not externally retained, most plausibly provider generation and/or embedding latency. Exact attribution requires retaining existing `ChatTrace` timings in a secure diagnostic sink; it cannot be proven from total time alone.

# 11. Root-cause matrix

| Question | Problem | Root cause | Severity |
|---|---|---|---|
| Dashboard Q1 | Subscription price stated as $33 instead of $31.35 | NUMERIC REASONING; GENERATION; ambiguous compressed price labels | High |
| Dashboard Q2 | No material problem | None | None |
| Widget Q1 | Turmeric Boost falsely reported absent | QUERY UNDERSTANDING; ENTITY RESOLUTION; RETRIEVAL; FIELD COVERAGE | Critical |
| Widget Q1 | No visible source despite positive Gummies claims | SOURCE ATTRIBUTION | High |
| Widget Q2 | Correct historical entities recovered but not used as comparison scope | FOLLOW-UP RESOLUTION; CONTEXT SELECTION; RETRIEVAL | Critical |
| Widget Q2 | No correct price or usage directions; unrelated Sea Essence evidence selected | FIELD COVERAGE; STRUCTURED METADATA; NUMERIC REASONING; RETRIEVAL | Critical |
| Widget Q2 | Repetitive “I don't have” response | GENERATION / RESPONSE STYLE, caused by missing evidence | Medium |
| Q1 and Q4 | 16.9–18.9 second totals cannot be reconciled by stage | LATENCY / OBSERVABILITY | High |

# 12. Most important improvements

No changes were implemented. The top five changes to consider next are:

## MUST FIX

1. Fix comparison entity parsing so contractions such as “what's” cannot create a false `"'s"` entity, and explicit named products always receive one document allocation each.
2. Preserve multi-entity comparison scope across follow-ups. If history resolves Turmeric Boost and Turmeric Gummies, `price` and `directions` evidence must be collected for both before global/sibling candidates.
3. Make price evidence semantically typed—one-time, subscription, bundle quantity, per-bottle, and financing threshold—so `$31.35` cannot be relabeled as `$33` or `$35`.

## SHOULD IMPROVE

4. Tie source attribution to supported positive claims rather than suppressing every source when an answer also contains missing-information language.
5. Persist or securely export the existing per-turn `ChatTrace` timings so embedding, database retrieval, generation, verification, persistence, and delivery totals can be reconciled without changing request behavior.

## OPTIONAL

No response-style-only change belongs in the top five. Style polishing should follow retrieval correction; otherwise it would merely make incorrect answers sound better.

# 13. Overall verdict

**CORE RETRIEVAL ISSUE STILL EXISTS**

The single-entity dashboard path is strong, including a fully successful multi-field answer. The explicit widget comparison and same-session follow-up still fail at entity/document selection and field-complete retrieval. Response polish is not the correct next phase until those retrieval defects are fixed.
