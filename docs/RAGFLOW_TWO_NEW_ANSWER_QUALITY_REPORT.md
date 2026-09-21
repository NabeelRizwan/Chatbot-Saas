# Two New RAGFlow Answer-Quality Tests

Date: 2026-09-21 UTC / 2026-09-22 Asia/Calcutta.

## Outcome

NORMAL: CORRECT; retrieval and citation PASS. AGENTIC: all seven requested factual requirements present (FULL factual score, 7/7), but final citation mapping FAILS. This is not a clean end-to-end acceptance of the hard answer. No question was rerun, and no runtime/prompt/retrieval code was changed after results.

## Frozen test engine

- Branch: ragflow-derived-dev.
- Existing source checkpoint: 05ceb975125a4706ff97852e78377934c8531666.
- Frozen test-harness commit: e4182faae05f9b543639efcb7541ac2bee1dfe8b.
- Measured deployment: faacb26d-d86a-408d-80a0-8428f79622fa (SUCCESS).
- Initial deployment before the job: 210003c7-612c-4a63-a14f-3a58d51df697.
- Development project only: 068a5695-2cf6-4c7f-89fc-3d24a225e4a5; backend 92349a32-e92d-4795-b86e-338929b03059.
- The project environment is named production, but it belongs exclusively to ragflow-derived-dev, NOT Chatbot-SaaS-Production.
- RAGFlow v0.27.2 / a024bea0cd93f39e6652a42bf84dd20c55bc560b.
- Retrieval quality freeze: 395d46be835610c6228252fee543cc3284b7f776; provider repair freeze: 9571d6b9a02eec716eb8d8a099d1409a2e4384c9.
- Gemini: gemini-3.5-flash-lite; existing Railway development key only; no key fetched, logged or persisted locally.
- Embedding: sentence-transformers/all-MiniLM-L6-v2 / 1110a243fdf4706b3f48f1d95db1a4f5529b4d41; 384 dimensions.
- Cross-encoder: cross-encoder/ms-marco-MiniLM-L6-v2 / 233902d25c440f23af6f7d6e94d2946bac0bee0a.
- Threshold 0.2; blend 0.7 lexical / 0.3 vector-or-model; candidates 64; top_n 12; kNN top_k 1024 / num_candidates 2048.
- Normal context defaults: 8192 tokens / 131072 bytes / 48 units. Existing synthesis helper retains its own unchanged upstream framing/citation limits.
- Normal mode: engine.retrieve with default options and the real reranker, engine.build_context, then the unchanged upstream _compose_answer_from_evidence. No formalize/planner/action/review graph is invoked. This is an engine-level ordinary answer test, not a widget/UI test; no new answer API was installed.
- Agentic mode: engine.research(thinking_mode=high), existing planner/fanout/tools/SCA/research/synthesis graph. No document targeting, manually supplied subquestions or expected answers.
- 196 frozen file hashes verified before and after. Only standalone fixture/harness/tests and development Docker copy allowlist were added before the attempt; engine/provider/prompts/graph were unchanged.
- Focused offline validation: 188 passed (including 15 new harness tests), network denied. git diff --check PASS.

## New isolated corpus and security

Organization synthetic-answer-test-org; bot synthetic-answer-test-bot; generation answer-test-v1. Six distinct sources/documents, each version 1, each parsed into one READY chunk through the existing markdown parser and real MiniLM embedding pipeline. Both questions have the same authorized six-document scope. No answer document or evaluation checklist was indexed.

The existing application a/b authorization system is unchanged. The standalone job issues one exact immutable test scope, guarded by an ES CREATE-only ownership marker and fresh checks on each engine/store operation. Existing READY/source-version/provenance filters are unchanged. The test index had to be absent. The marker permanently prevents reruns and was closed/revoked afterward.

Normal authorized candidate observations: 2; hard: 151. Dropped trace events: 0 for both. Every observed candidate was checked against exact org/bot/generation/source/document/version, READY state and text hash. Scope PASS. No cross-tenant results.

Corpus/vector inventory before and after: 6 chunks; SHA-256 99190caf2227c1155fc69e35945799e4b85f83b9d18e01c35b26acbcd81be921. Existing a/b source-authority records unchanged. No old benchmark or customer data was queried.

## Normal question

> What time does Harborview Library close on weekdays?

Final answer (verbatim):

> Harborview Library closes at 7:00 PM on weekdays [ID:0].

Expected: 7:00 PM. RESULT: CORRECT. RETRIEVAL: PASS. CITATION: PASS. Unsupported facts: NO.

The sole retained source is Harborview Library Information, version 1. Original supporting text says open until 7:00 PM Monday through Friday. Chunk 0ff6e5874282e462e82abee67b4c6dc7998c2c22ee918eb2b6b697c742fcca94. Final synthesis context ID 0 maps to this exact original chunk; its citation is valid.

Two candidates were reranked. Harborview cross-encoder score 0.9992652535438538; lexical similarity 0.10353017468759673; final blended score 0.37225069834447383. The other candidate scored 0.000012887323464383371 on the real reranker and was not included in final evidence. Actual context and complete candidate/rerank records are in the trace.

Gemini calls: 1; failures: 0; reported tokens: 2116. Total question latency: 0.8467566631734371 seconds; callback: 0.7166984267532825 seconds; reranker: 29.57059070467949 ms. Latencies exclude startup/ingestion.

## Very hard question

> I am a Pro member and want to use the Orion Battery Laboratory at 8:00 PM on Wednesday. How much do I pay each month, what is the maximum length of my booking, which certification do I need, when can I take the required training, and how far in advance must I cancel the reservation?

Final answer (verbatim, citation spacing preserved):

> As a Pro member, you pay 28 credits per month [ID: 2]. Because your booking at 8:00 PM falls after 7:00 PM, it is considered an after-hours reservation, limiting your booking length to 90 minutes regardless of your normal workshop reservation allowance [ID: 4]. To use the Battery Laboratory, you must hold a valid Level B Electrical Safety Certification [ID: 1]. Training for this certification is offered on Tuesday at 6:30 PM [ID: 3] and Thursday at 7:30 AM (as supported by the research summary). Finally, because all Battery Laboratory bookings are classified as hazardous-workshop reservations, you must cancel the reservation at least 18 hours before the booking begins [ID: 0][ID: 1].

| Required fact | Result | Original source |
| --- | --- | --- |
| 28 credits/month | PASS | Orion Makerspace Membership Plans |
| 8 PM is after-hours | PASS | Orion After-Hours Laboratory Rules |
| 90-minute maximum, not three hours | PASS | Orion After-Hours Laboratory Rules |
| Level B Electrical Safety Certification | PASS | Orion Battery Laboratory Safety Manual |
| Tuesday 6:30 PM and/or Thursday 7:30 AM | PASS | Orion Training Schedule |
| Hazardous-workshop classification | PASS | Orion Battery Laboratory Safety Manual |
| At least 18 hours cancellation notice | PASS | Orion Reservation and Cancellation Policy |

TOTAL: 7/7. QUALITY: FULL on the prescribed factual rubric. UNSUPPORTED/FABRICATED FACTS: NO: all factual values occur in the authorized original source records, including Thursday. CITATIONS: FAIL, independently of factual completeness.

The answer does not explicitly explain that Thursday after this particular Wednesday is too late to obtain certification for that booking; the source requires training before laboratory use. The final answer also contains the awkward phrase “as supported by the research summary.” Neither issue was corrected or retested.

## Natural agentic execution

13 actual Gemini calls; zero provider failures; 42641 reported tokens. Normal graph return; emergency ceiling not reached. Total question latency 14.476714013144374 seconds; sum of callback durations 14.937343252822757 seconds (parallel calls overlap).

Call 1: upstream weighted keyword formalization. Call 2: model-generated five fanout directions (not supplied by the harness). Call 3: model-generated slots, including an additional web slot. Calls 4–6: research/state updates. Call 7: SCA identified missing training/cancellation information. Call 8: upstream gap rewriting. Calls 9–12: additional research/native action continuations. Call 13: actual final synthesis.

Executed tools: navigate_tree and retrieve. Six navigation-prefix tree attempts missed because this newly ingested corpus has no compiled tree; unchanged upstream prefix retrieval ran. One further retrieve was model-selected and dispatched through _tool_node. No web search executed: no web connector was provided. No forced tool choices.

The final stored SCA verdict remains INSUFFICIENT, and the generated web slot remains unresolved; upstream nevertheless returned a final answer through its normal partial-answer terminal route. This is not an emergency-budget abort.

Real cross-encoder ran for the NORMAL path. The hard graph chose its existing retrieve/navigation routes; recorded cross-encoder invocations for that graph: 0. Do not interpret this test as exercising an agentic cross-encoder or every hybrid tool. No reranker or route was altered to force coverage.

All five original Orion documents appear in the hard evidence inventory. Fifty backend search records and 151 authorized candidate observations are saved. Generated research summaries are not treated as original documents for this evaluation.

## Citation failure: exact evidence

The final synthesis helper sorts citation excerpts by relevance and renders a new numeric ID sequence. The returned advanced citation_pool still enumerates the earlier unsorted tools.kbinfos chunk list. Consequently every numbered source binding in this run differs:

| ID | Final synthesis context | Returned citation_pool |
| --- | --- | --- |
| 0 | Orion Reservation and Cancellation Policy | Orion Battery Laboratory Safety Manual |
| 1 | Orion Battery Laboratory Safety Manual | Orion Makerspace Membership Plans |
| 2 | Orion Makerspace Membership Plans | Orion Training Schedule |
| 3 | Orion Training Schedule | Orion After-Hours Laboratory Rules |
| 4 | Orion After-Hours Laboratory Rules | Orion Reservation and Cancellation Policy |

For example, the answer cites ID 2 for 28 credits/month. Gemini saw Membership Plans as ID 2, but the returned pool resolves ID 2 to Training Schedule. The 90-minute answer cites ID 4, whose returned pool instead resolves to Cancellation Policy. This is a real source-binding failure, not a missing corpus fact.

Read-only code locations: backend/ragflow_derived/upstream/advanced_rag/agentic_rag_graph.py::_compose_answer_from_evidence (sorted cite_chunks + kb_prompt enumeration), versus backend/ragflow_derived/advanced.py::research (enumeration of tools.kbinfos for citation_pool). No repair was made.

Separately, the final Training Schedule excerpt omits Thursday while the authorized original chunk contains both Tuesday and Thursday. The model uses Thursday from its research summary and does not attach a direct citation to that phrase. The original-source inventory verifies the value, but a generated summary alone is not a valid citation.

## Saved trace and cleanup

docs/RAGFLOW_TWO_NEW_ANSWER_QUALITY_TRACE.json contains an ordered gzip+base64 envelope. Concatenate parts[].data, base64-decode, then gunzip. Decoded SHA-256: 86b5fda802349b46b17d9178bead6f11c0567613923288ab93b2a86cc07c1c3a. All parts and the decoded hash were verified.

Trace includes exact questions, modes, prepared queries/planning outputs, actual selected/dispatched tools, scoped candidates, rerank scores, original evidence, context/model inputs, final answers, citations, counts and timings. No API key, credentials or opaque provider thought-signature bytes were serialized. The trace was inspected for unsafe credential/signature keys.

The new one-shot authority is closed. The new dev run gate is disabled and the pre-deploy command is cleared. Existing synthetic sources are retained; no prior corpus was deleted. The report-only checkpoint applies this cleanup without another question.

CODE CHANGED AFTER RESULTS: NO. RETRIEVAL TUNED: NO. PROMPTS CHANGED: NO. THRESHOLD CHANGED: NO. OTHER QUALITY DATASETS RUN: NO. PRODUCTION PROJECT TOUCHED: NO. Main was not merged or pushed.

## Final conclusion

Normal RAGFlow answered the simple question correctly with valid source attribution. Agentic RAGFlow autonomously gathered all five relevant documents and returned all seven requested facts, but the hard answer fails end-to-end citation correctness. No tuning, retries or fixes were performed.
