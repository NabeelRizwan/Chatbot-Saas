# Combined retrieval in the SaaS backend

The required ordering policy is focused native retrieval, pinned BGE scoring of
the first 32 full title/prose pairs per focus, round-robin interleaving, stable
identity deduplication and the original candidate tail. SaaS accounts, bot
permissions, quotas, provider routing and widget endpoints remain owned by the
existing platform.

`merge.py` adapts the unchanged round-robin loop from LangChain
`MergerRetriever.merge_documents`, commit
`d7508191bcf2af823ad8a168a15772710de5592b` (MIT). The framework invocation layer is
omitted because native retrieval already materializes each lane. The complete
source/license and recorded hashes are included under `vendor/` and
`vendor-manifest.json`; no broad LangChain dependency or dynamic code execution.

Title/prose assembly and stable descending order adapt RAGFlow
`rag/prompts/generator.py` and `rag/nlp/search.py`, commit
`a024bea0cd93f39e6652a42bf84dd20c55bc560b` (Apache-2.0; license included).
Relevance scores must come from the official Sentence Transformers CrossEncoder
and BAAI/bge-reranker-v2-m3 revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` (Apache-2.0). The private HTTP contract
verifies model identity, complete aligned scores and full input token lengths.
Model logits never replace native similarity or get blended with vector scores.

The SaaS calls the native RAGFlow service through `services/native_rag`. The
service uses the pinned upstream search implementation and Elasticsearch, with
the tested 128-candidate window and embedding profile. PostgreSQL owns the bot's
active source bindings and verified passage manifests; it does not supply the
vector or lexical candidates for this path. Each search is restricted to those
bound native document IDs. The adapter checks source authority before and after
retrieval, then verifies each returned passage and title against its manifest.
SaaS source URLs and lifecycle metadata are preserved. See
`deploy/native-ragflow/source-manifest.json` for the upstream revision and source
hashes, and `services/native_rag/config.py` for the required search policy.

Focused query planning is automatic integration glue, using the bot's configured
provider/model through `llm_router.generate_auxiliary`, including existing key
resolution, concurrency control and accounting. It sees only the already-resolved
query, never corpus bodies, expected answers or source permission identifiers.
Malformed output uses the complete original query and disables answer caching
for that degraded turn. Gemini final-answer generation remains unchanged.
If every focused search is empty while the original query retrieved sources,
those original candidates are still BGE-ranked under the original query; this
query-plan recovery is recorded and its answer is not cached as a healthy run.

Context admits full ranked passages under 4,000 cl100k source-content tokens and
a separate 65,536-character envelope, including the existing source headers and
host deterministic annotations. The SaaS pipeline uses this envelope rather
than the old 10,000-character default, which could prematurely shrink the measured
4,000-token source window. Callers may request a smaller ceiling for annotation
admission; they cannot raise the package's upper envelope. The
strict offline tokenizer fails closed when its pinned asset is absent/corrupt.
This additional envelope and the platform's existing deterministic fact annotations
mean this is not a claim of identical stock-test prompts or Gemini answers.

Frozen tests measured 43/45 IKEA witness coverage against 31/45 native coverage,
including two remaining misses. The 65-case replay checks the recorded plans,
candidate pools, ranking scores and context selection; it does not validate
live provider behavior or deployment performance.

The 28 September 2026 local widget verification exercised eight WOWMD questions
using fresh native searches and BGE inference. Six matched the saved reference's
key facts, one gave a supported alternative and one missed conflicting evidence.
That run used the native addon core over read-only SSH, local GPU scoring and
Codex test substitutions for planning and answers. It did not test a deployed
addon HTTP server, a full PostgreSQL/Redis stack or live Gemini calls. Those
deployment checks remain required; identical answers and production capacity
are not established by the saved tests.

This package has no feature-off switch or silent legacy-ranker fallback. The
private reranker endpoint and bearer token are required configuration. Missing
configuration, model mismatch, unavailable scoring or incomplete score responses
raise a typed technical failure for the platform's existing temporary-error
handling. A malformed query plan retains the original query and still uses BGE
ranking; it never selects the previous ranking pipeline.
