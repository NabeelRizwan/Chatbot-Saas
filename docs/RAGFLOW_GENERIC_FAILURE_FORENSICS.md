# RAGFlow generic failure forensics

## Read-only finding — 2026-09-21
Baseline dev commit: ad09618a86c4e74b2f0d8056659d1d97b0477610. Upstream: v0.27.2 / a024bea0cd93f39e6652a42bf84dd20c55bc560b.

Evidence: RAGFLOW_NATIVE_ACCEPTANCE_RESULTS.json (original channel candidates), RAGFLOW_GENERIC_FORENSIC_TRACE.json (four additional read-only Railway retrievals, raw query processing, actual model inputs/hashes and per-candidate scores). The latter ran on deployment 3fd19b77-a699-46d3-89ac-c0875b720f9e; decoded transport SHA-256 db5004c3fe521fb4c99460b96ace0e28cb4b8f842b01b3cca700dbd5890abfb2. All four preserve original query, models, weights, cutoff, top-k, data and scope. No external LLM. A malformed staged diagnostic command was detected/read back and replaced BEFORE execution. Diagnostic hook removed afterward; temporary non-secret script variable cleared.

**All expected supporting sources reached hybrid candidates AND reranking.** “Without reranker” is a separately scored/thresholded retrieval result, not raw pre-rerank candidates. Interpreting its empty output as an initial retrieval miss was incorrect.

## Exact questions
A. Where can I leave spent household power cells safely?
B. What are the opening hours for the museum and parcel collection?
C. Which community services offer book borrowing, classes or shared tools?
D. How can I reserve a room or a woodworking workshop session?

## Supporting chunk matrix
Ranks are lexical / vector / first hybrid request, from the saved baseline. Score ranks are the four diagnostic repeats before the cutoff. Every listed source is a real reranker input. No context exclusions occurred (0 in all four); citation exists exactly when admitted. For library, the answer-bearing borrowing chunk is shown rather than a navigation-like/card/tenant marker chunk.

| Category | Expected source ID | Channel ranks L/V/H | Term similarity | Neural score | Final blend | Score rank | Context + citation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| semantic_paraphrase | recycling | 1 / 1 / 1 | 0.036937887268439884 | 0.00001566529863339383 | 0.025861220677497937 | 1 | NO |
| multi_document | museum | 2 / 1 / 1 | 0.047825577687114526 | 0.34594663977622986 | 0.1372618963138491 | 2 | NO |
| multi_document | delivery | 1 / 2 / 2 | 0.11048389770387039 | 0.9428265690803528 | 0.3601866991168151 | 1 | YES |
| discovery | library | 3 / 1 / 1 | 0.026319681775967864 | 0.00040413058013655245 | 0.01854501641721847 | 5 | NO |
| discovery | fitness | 1 / 17 / 7 | 0.039479134493818555 | 0.000019906927263946272 | 0.02764136622385217 | 2 | NO |
| discovery | workshop | 2 / 3 / 3 | 0.05357386244588485 | 0.000504297495353967 | 0.037652992960725586 | 1 | NO |
| rerank_candidates | study | 2 / 2 / 2 | 0.05908145802913599 | 0.000014711122275912203 | 0.04136143395707796 | 2 | NO |
| rerank_candidates | workshop | 1 / 1 / 1 | 0.2054907279271829 | 0.08513496816158295 | 0.16938399999750292 | 1 | NO |

## Exact first removal decision
`upstream/search.py:Dealer.retrieval`: descending scored candidates are walked and `if sim[i] < similarity_threshold: break` cuts off the tail. With learned reranking the score is 0.7 * term_similarity + 0.3 * neural_similarity + rank_feature (zero here), cutoff 0.2. It is not raw vector similarity or raw neural score thresholding.

- A: recycling is rank 1 throughout retrieval but blend 0.025861220677497937 is below cutoff. Very low cross-encoder score on tokenized input plus sparse query-term/bigram overlap; no contextual paraphrase rewriting is enabled.
- B: museum is hybrid rank 1 but neural 0.34594663977622986 and weak term coverage yield 0.1372618963138491; parcel's 0.3601866991168151 survives. Single whole-query scoring does not reserve evidence for each requested source.
- C: library, fitness and workshop are all candidates; best relevant blend is only 0.037652992960725586. Broad disjunctive intent is scored against each individual chunk, without decomposition; all fall below cutoff.
- D: workshop and study are top 2 hybrid candidates. Their blends 0.16938399999750292 / 0.04136143395707796 both fail; workshop survived the separately scored no-reranker control, but not learned blend.
- Confidence: HIGH for the actual removal stage and scores. A counterfactual “a missing feature would fix it” is NOT established.

## Query preparation, expansion and model inputs
The JSON companion records exact normalized strings, tokens, weighted lexical expression, adjacent phrases, synonym lists, extracted keywords, raw vector input, 384-dimensional profile, per-candidate token/title fields and model-input hashes. Query terms are stemmed by Infinity. WordNet has broad senses (e.g. some ordinary tokens expand to unrelated meanings); no corpus-specific synonym changes are authorized.
The diagnostic `term_weights` entry is the direct weights call on normalized tokens; the actual expression also applies the upstream English stopword path and is the authoritative request. Neural inputs are tokenized content + title + important/question fields with upstream concatenation/deduplication, not natural source prose. Exact source text itself is intact.

## Upstream comparison and decisions
The pinned Dealer uses the SAME candidate query, tokenized reranker input, 0.7/0.3 blend and cutoff. No general per-source reservation or multi-intent coverage guarantee exists in this ordinary path. Porting omitted helpers must not be mislabeled as a proven remedy.
Missing normal surrounding units: configurable multi-turn rewrite, cross-language/keyword augmentation, model-backed ingestion keywords/questions, parent/child expansion and optional TOC enhancement with ingestion artifacts.
Optional advanced harness provides actual decomposition/fanout, sufficiency review, gap rewrite, multi-route research and structured navigation. Those require a chat model and additional coherent artifacts/adapters. Graph and RAPTOR are optional ingestion-backed subsystems, not automatic ordinary query rescue.
Post-release natural-text reranking and dense-only rescue commits are outside the authorized pin and remain unadopted. No scoring/threshold/model tuning was performed.
