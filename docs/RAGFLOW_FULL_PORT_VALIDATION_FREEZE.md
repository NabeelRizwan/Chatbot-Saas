# Full RAGFlow development port: pre-result freeze

This file was authored before any live call in this workstream. No SAME8/HOLDOUT_B/old90 evaluation was used to choose implementation algorithms. Existing evaluation definitions were read only after implementation to select modes and define a different HOLDOUT_C.

- Upstream: RAGFlow v0.27.2, `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.
- Starting branch: `ragflow-derived-dev`; starting HEAD `3edb10d2734832a7b61a93485b22bab1aaebe549`.
- Pinned source closure commit: `efc6db8`.
- Full quality implementation commit: `395d46be835610c6228252fee543cc3284b7f776`.
- Completeness matrix SHA256: `d0ab3aef837a667df05a589e36b74fdd461119e08768878f7eed96770f570d21`.
- HOLDOUT_C SHA256: `9f59dc55fd173d01ea02c0dcff74aea896d624619680f3a835cd346c42ad001c`.
- Complete file hashes, mode selections and budgets: `dev/ragflow/full_port_freeze.json`.

## Offline gates

473/473 tests pass, no sockets/provider calls. Included: 95 newly adapted pinned upstream tests, real agentic executor low/medium/high/ultra execution with deterministic provider doubles, parser/metadata/graph/RAPTOR/navigation tests, fail-closed security and provenance tests, and 10 validation-driver tests. One existing Starlette deprecation warning remains.

175 manifest mappings / 171 destination files / 158 distinct upstream source paths; 88 newly used upstream paths. COPY 28, ADAPT 141, WRAP 2, pre-existing narrow REIMPLEMENT boundary entries 4. Actual pinned Git blobs and destination hashes verified. Critical algorithm AST parity: 13/13. Deployment syntax/secret-pattern check passes. No arbitrary quality heuristics added.

All 28 pre-existing modified/untracked artifacts retain their starting SHA256 and are excluded from these commits. Neither main ref changes. Adapter/test whitespace checks are clean except for intentionally retained copied upstream whitespace: EOF blank lines and trailing spaces inside pinned prompts. These are not silently changed to manufacture a clean vendor diff.

## Frozen one-shot execution

Only development project `068a5695-2cf6-4c7f-89fc-3d24a225e4a5`, backend `92349a32-e92d-4795-b86e-338929b03059`. No production access. No additional infrastructure, GPU, paid upgrade, volume resize or replicas.

1. Deploy the frozen software and verify health, provider identity, real MiniLM/cross-encoder and ES 8.11.3.
2. Run mechanical parent/TOC, real structure/RAPTOR/KG compilation, navigation/RAPTOR/KG/agentic checks, then foreign-document rejection checks. Any failure stops the quality stage.
3. Add HOLDOUT_C's four unseen municipal-floodgate documents to the two synthetic tenants. New mechanical/C fixtures uniformly use the existing upstream newline child delimiter; no expected-answer-dependent ingestion rules.
4. Normal mode: SAME8 (8), HOLDOUT_B (8), HOLDOUT_C (6), optional helpers uniformly off. Whole dataset document scopes; expected answer documents are never query scope.
5. Intended advanced modes: SAME8 multi-document/discovery/multi-option (agentic high); HOLDOUT_B multi-document/multi-domain timeline (agentic high); C graph/navigation/agentic/RAPTOR, one question each. No blind cross-product of modes/questions.
6. Score original supporting-source coverage and normalized literal expected fragments after responses. Generated text is separately labelled and never counted as original evidence. Report raw outcomes without tuning.

Maximum 160 Gemini callback attempts per backend process; 900 seconds per advanced operation; 960 seconds per HTTP request; two hours to start new non-GET operations. Existing upstream internal retry/stopping rules remain unchanged. No automatic validation rerun; CREATE-only marker prevents replay. Compressed, secret-scanned result checkpoints preserve observations. No quality call if the mechanical gate fails. Final read-only candidate revalidation and original inventory comparison run after successful execution.

Existing Railway CLI has no SSH key. Use the already-established connector transport: a temporary explicit pre-deploy validation command only after the full software deployment is healthy, then remove it. This is not a permanent startup hook. Secrets remain inside the development service Variables and process. No runtime or prompt modification follows results.

## Scope of acceptance

This is not full product parity. DeepDoc OCR/vision/audio assets, community clustering/NER dependencies, durable wiki/template workflows, structured SQL and distributed task persistence remain specifically partial/deferred in the frozen matrix. Imported optional source does not count as a deployed working mode. The live report must distinguish offline capability from successful real execution, and stop rather than conceal a runtime failure.
