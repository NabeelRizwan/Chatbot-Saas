# Expanded RAGFlow live validation — blocked at model boundary

Date: 2026-09-21 UTC. Project: `ragflow-derived-dev` (`068a5695-2cf6-4c7f-89fc-3d24a225e4a5`) only. Branch: `ragflow-derived-dev`. Runtime freeze: `ed6dde00dc3742bf899cac3dbcd38fc7e0d4e2f3`; deployed source: `244db9af54eadcdae1b2a152950aeeba543946cb`.

## Verdict

**DEVELOPMENT DEPLOYMENT HEALTHY / MODEL-BACKED ACCEPTANCE BLOCKED.** No improved retrieval-quality claim is supported. The once-only runner stopped on its first retrieval request. No automatic retry, parameter change, fallback provider, or post-result implementation change was made.

## Deployment and observed failure

- The user saved the dedicated test key directly in Railway. Only its variable name was inspected; its value was never retrieved, printed, downloaded or persisted locally.
- Deployment `01f2b592-9d7b-45d9-86b0-eb3f68ff2093` succeeded. Health confirmed real Elasticsearch 8.11.3, Infinity SDK 0.7.3 tokenizer, unchanged MiniLM embeddings and cross-encoder, parent/child support, and configured `gemini-2.5-flash-lite` callback. Initial callback counters were all zero.
- One-shot pre-deploy job `0d20e586-b0f4-43be-b190-c27ea36e1439` began at 14:41:58 UTC and failed at 14:41:59 UTC. Health and both authorized source inventories returned HTTP 200.
- First question: **How many days can members borrow printed library books?** The frozen request used `keyword=True`, with all other optional modes off. `POST /ragflow-dev/retrieve` returned **HTTP 503**, Railway proxy duration **422 ms**.
- Failure frames: `expanded_acceptance.py:39` -> `native_acceptance.py:66` (unexpected HTTP status). No successful result was appended.
- Subsequent health: **1 callback attempt, 1 callback failure, 0 recorded successful tokens**. This counter increments before SDK execution, so it is NOT proof that Gemini accepted a request or billed zero tokens.
- First established failing boundary: upstream keyword extraction's development model callback, before the normal Dealer retrieval. The adapter suppresses raw exceptions, and the client does not retain the error response body. Therefore authentication, quota, SDK/request validation, network failure and response/client cleanup cannot be distinguished from this record. Do not assert an invalid key or quota exhaustion without evidence.
- Partial report transport SHA-256: `ff9c02d6e4417e382e86f372b009f1f3dc77630c57dd7014016f2fa6d3651d41`; all four pieces were recovered and verified. Pretty-printed payload is `RAGFLOW_EXPANDED_VALIDATION_PARTIAL.json`.

## Bounded run accounting

| Gate | Result |
| --- | --- |
| SAME8 baseline | Existing 4 full / 1 partial / 3 empty |
| SAME8 expanded | 1 attempted, 0 successful results; remaining 7 NOT RUN |
| GENERIC_HOLDOUT_B | NOT RUN; no holdout documents ingested |
| New parent/TOC/rewrite component checks | NOT RUN |
| New live security/lifecycle checks | NOT RUN; not counted as PASS |
| New deployment health | PASS |
| Original source persistence across backend deployments | Starting inventories still contain A: 13 READY sources, B: 12 READY sources |
| Full after-run persistence/content comparison | NOT RUN; not overstated as a new content-equality test |
| Offline tests | Prior frozen implementation: 197/197 PASS; no code changed or redundant suite rerun for this failure |
| Upstream tests | 11 adapted upstream prompt tests plus 2 exact upstream method AST parity checks PASS within that suite |
| Provenance | Prior frozen verification: 79 destination files / 83 mappings PASS |

The failed request preceded the first ingestion instruction. Thus this run performed no holdout/structural fixture writes, no source replacement, and no lifecycle mutation. No live quality answer exists to score; 503 is a technical failure, not empty evidence or a retrieval regression. Frozen mode compares optional keyword augmentation to the original default path, not a controlled like-for-like ranking experiment.

## Forensic and completeness conclusions retained

The separate completed four-question forensic run established that ALL expected sources entered hybrid candidates and reranking. Their first loss was `Dealer.retrieval` at `if sim[i] < similarity_threshold: break`, with unchanged 0.7 term + 0.3 neural blend and 0.2 cutoff. A: recycling 0.025861220677497937; B: museum 0.1372618963138491 while parcel 0.3601866991168151 survived; C: best relevant source 0.037652992960725586; D: workshop 0.16938399999750292 and study 0.04136143395707796. Context exclusions were zero. See the complete saved forensic matrix and trace; this new provider failure does not revise those findings.

Expansion added actual upstream synonyms, query preparation/prompts/parsing, optional keyword/question ingestion, child/parent expansion, text TOC generation/relevance, and optional agentic helper interfaces. New mapped upstream files: **49 = 15 COPY + 34 ADAPT**; custom quality heuristics: **0**. New direct dependencies: Jinja2 3.1.6, json-repair 0.60.1, google-genai 1.55.0; MarkupSafe 3.0.3 is transitive. Apache attribution and explicit modifications remain recorded in the manifest.

Still partial: full parser/layout dispatcher, rich metadata/tag execution, generated-answer citation decoration. Still not integrated: full agentic executor/fanout/navigation, KG, RAPTOR/compiler, SQL/web/memory/multimodal routes. These require coherent scope/provenance-aware artifact and tool adapters, not simply a credential. No claim of full RAGFlow or live acceptance for these modes.

## Cleanup, scope and next step

The failed job container stopped. Its finally block removes process credentials. The service's future `preDeployCommand` is verified empty and the non-secret expansion gate cleared; no validation job remains enabled. The user-owned test credential remains only in Railway Variables and the authorized service process. The previously healthy deployment continues serving.

No runtime, prompt, threshold, weights, query rules, embeddings, reranker, candidate limits or evidence caps changed after the attempt. No old90, customer corpus, production project, main merge/push, force push or production deployment. Pre-existing unrelated work is preserved. Any subsequent checkpoint contains documentation/results only on the development branch.

**Next step:** a separately bounded provider-boundary diagnostic that records only an allowlisted exception class/status/category, without raw text or credentials. Establish the cause before repairing transport or authorizing a resume; do not rerun the acceptance automatically or tune retrieval to this failure.
