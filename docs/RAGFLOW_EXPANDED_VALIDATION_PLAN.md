# Frozen expanded RAGFlow validation plan

Retrieval algorithm freeze: ef97a2dca4874e1a53b409738b3037b418b3f9a8. The unseen holdout was authored after this freeze and before any evaluation. Subsequent explicit user authorization added only the Gemini transport; source-projection review also corrected required auxiliary payload fields before live execution. Final executable freeze: ed6dde00dc3742bf899cac3dbcd38fc7e0d4e2f3. Neither correction used holdout results. No post-result implementation change is allowed.

## Once-only quality run

1. Verify deployment health, configured dev-only model and zero model calls. Existing original corpus must still be present and no new holdout/mechanical sources may exist.
2. Run the SAME8 exactly once, **before** inserting any new documents. Request upstream `keyword=True` uniformly; all other query flags remain false. No case-specific option selection. Compare original default-path result to this explicitly labeled optional upstream mode, not as a controlled single-variable ranking benchmark.
3. Index GENERIC_HOLDOUT_B's six novel synthetic documents in each isolated tenant. Evaluate its eight questions once. The query scope includes ALL six holdout documents, not expected-answer document labels. Required sources/values are assessed only after retrieval. No corpus-specific synonym, query rewrite rule, threshold, model or cap change.
4. Separate bounded structural/security checks: actual parent materialization, real TOC generation/relevance, one real multi-turn rewrite, returned-row scope/hash validation, unauthorized tenant/version assertions, parent deletion, unchanged original source manifests. These are not more attempts on quality questions.
5. Model limit: twenty actual calls per service process, one transport attempt each. Sixteen quality requests need one upstream keyword call each; up to four calls remain for TOC/refinement. If optional JSON repair uses the remaining allowance, stop that gate rather than raising the budget or retrying the quality run. Record partial results honestly.

The helper executes only with the explicit expansion gate in the new Railway project. It obtains service authentication only inside Railway and never exports secrets. Result emission rejects any included access or Gemini credential. No old90, customer corpus or production resource. No automatic acceptance startup; remove the one-shot command afterward.

## Offline state

197 focused tests PASS; provenance PASS (79 mapped files, 83 source mappings); syntax PASS. All 35 prompt texts match the pinned originals under the actual upstream loader's strip(). Fifteen are byte-identical; twenty have terminal-whitespace-only normalization recorded as ADAPT. Internal upstream trailing spaces are intentionally retained, so a full diff whitespace check reports them. Non-vendored changes pass the whitespace check. No thresholds, weights, model embeddings/reranker, top-k or context limits changed.
