# RAGFlow full development port — completeness and live validation

## Identities and scope

- RAGFlow version: **v0.27.2**.
- Pinned commit: `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.
- Previous development baseline: `3edb10d2734832a7b61a93485b22bab1aaebe549`.
- Full quality implementation commit: `395d46be835610c6228252fee543cc3284b7f776`.
- Upstream source closure commit: `efc6db8`.
- Frozen validation commit: `3645f122dafd8e032c9277cabccc318b90631cb6`.
- Only branch pushed: `origin/ragflow-derived-dev`.
- Only Railway project: `068a5695-2cf6-4c7f-89fc-3d24a225e4a5` (`ragflow-derived-dev`). Backend `92349a32-e92d-4795-b86e-338929b03059`; development environment `31650c5f-fc5f-4954-9094-6d06383b3d17` happens to be named `production`.
- Actual production project `4ca162fa-755c-4c70-b3aa-7f4166a1fb36`: **not accessed or changed**.
- Completeness matrix SHA256: `d0ab3aef837a667df05a589e36b74fdd461119e08768878f7eed96770f570d21`.
- HOLDOUT_C SHA256: `9f59dc55fd173d01ea02c0dcff74aea896d624619680f3a835cd346c42ad001c`.

This is an internal engine port, not complete RAGFlow product parity. Source presence, passing deterministic tests, healthy startup and successful live execution are separate claims. The frozen matrix is authoritative for exact limitations; this report records actual deployment/validation results.

## Offline validation

**473/473 PASS**, with network connections denied. Breakdown by non-overlapping file groups:

| Group | Passed / total |
| --- | --- |
| Copied/adapted upstream parity test modules (95 newly added + 58 existing) | 153/153 |
| Full-mode security, artifact safety, full boundaries, platform boundary modules | 60/60 |
| Remaining generic functional, parser, integration-boundary, observation, provider-double and validation-driver modules | 260/260 |

Additional exact algorithm AST parity: **13/13** critical symbols. Full provenance gate: **175 mappings / 171 destination files**, official pinned Git blobs verified. Deployment syntax/secret-pattern preflight passes. One existing Starlette deprecation warning remains. Imported pinned sources retain their own EOF/trailing prompt whitespace; `git diff --check` warnings on those vendor lines are recorded rather than changing the prompts. New validation-driver staged whitespace check passes.

Tenant isolation and provenance: **PASS offline**. Adversarial tests cover foreign org/bot/source/document/node/generated artifact, stale versions, deleted sources, wrong generation, model-supplied foreign IDs, exact hashes, whole manifest validation, uncertain publication, and caught-provider/storage failures. This does not substitute for native live checks.

## Delivered capabilities

| Area | Delivered status |
| --- | --- |
| Parsing | Actual pinned text/HTML/Markdown and CPU DOCX/XLSX/CSV/JSON/JSONL/PPTX/EPUB/PDF-text parsers; supported/configurable |
| Layout | Exposed parser sheet/slide/outline/heading/table metadata; full DeepDoc OCR/layout/TSR deferred, no invented coordinates |
| Chunking | Actual upstream merging, splitting and parent relationships; preserved normal budgets |
| Metadata | Actual manual/auto/semi-auto query filter semantics over a bounded READY-scoped catalogue; metadata indexing supported |
| Embedding | Existing real MiniLM and title/content behavior unchanged |
| Indexing | Existing ES8.11.3; new immutable scope-owned artifact indexes and manifest publication |
| Lexical/vector/hybrid | Actual pinned Dealer, query and ES paths; unchanged normal algorithms |
| Reranking | Existing real cross-encoder in normal/RAPTOR; actual agentic tools preserve upstream route-specific behavior |
| Context | Actual upstream context construction with existing whole-evidence safety bounds |
| Citations | Original evidence hashes/identities preserved; generated objects labelled and linked to original support |
| Keywords/rewrite/follow-up/cross-language/synonyms | Actual upstream functions, prompts and conditional orchestration; optional/configurable |
| Parent/child and TOC | Ingestion artifacts plus actual query-time lookup/expansion, not query-time fabricated relationships |
| Document tree/navigation | Actual tree projection, dataset-nav compilation and navigation tools; optional compiled artifacts |
| Agentic fanout/decomposition/research/review/gap queries/executor/state graph/navigation | Actual coherent LangGraph/action-session runtime; all four thinking modes execute in offline tests |
| KG ingestion/storage/retrieval/lineage | Actual light/general graph extraction, merging, indexing and KGSearch; source-document provenance explicitly labelled |
| RAPTOR summary/tree/storage/retrieval/lineage | Actual upstream recursive builder and serializer, file-scope compilation, scoped source+summary retrieval and leaf lineage |
| Tables/structured documents | Actual parser table representations and document retrieval/navigation; not a new SQL analytics engine |
| Metadata/tags | Metadata filtering supported; explicit tags and actual tag query/rank-feature paths present; full tag-KB auto-labelling ingestion workflow partial |
| Compiled structures | Structure/dataset navigation supported; arbitrary product compiler templates and durable wiki/revision service partial |
| Multimodal | Interfaces/lazy embedded-image handling present; OCR/VLM/audio/video understanding deferred |

Generated graph/summary support is **not a proof of claim-level factual alignment**. Graph provenance is document-level, not fabricated exact sentence attribution. Upstream agentic final citation-pool order remains exposed separately from expanded original support.

## Provenance and fidelity totals

- Newly used distinct upstream source paths: **88** (93 new mappings).
- Total distinct upstream paths mapped: **158**.
- Destination files: **171**; mapping records: **175**.
- COPY: **28**; ADAPT: **141**; WRAP: **2**; pre-existing narrow REIMPLEMENT boundary mappings: **4**.
- Custom quality heuristics added: **0**.
- Quality datasets used to choose implementation algorithms: **NO**. Existing evaluation definitions were read after implementation only for holdout distinctness and mode selection.
- Provider: **gemini-3.5-flash-lite**, existing development key only.
- Normal threshold **0.2 unchanged**; normal term/neural blend **0.7/0.3 unchanged**.
- Embedding **sentence-transformers/all-MiniLM-L6-v2 unchanged**, real CPU model.
- Reranker **cross-encoder/ms-marco-MiniLM-L6-v2 unchanged**, real CPU model.
- No hidden normal-mode fallback from advanced modes, no question-specific parameters, no old Dense/FTS/RRF/Q1 translation.

## Runtime results

Development deployment **PASS**: deployment `1c30ea90-1b74-4df4-b961-c6b9e592f16d`, frozen commit `3645f12`, succeeded on 2026-09-21 at 18:33 UTC. Health reports ES8.11.3, both unchanged real CPU models, full software readiness, Gemini3.5 configured and zero provider calls at startup.

**FINAL VERDICT: DEVELOPMENT PORT DEPLOYED; FULL LIVE ACCEPTANCE BLOCKED BY GEMINI NATIVE-TOOL REQUEST COMPATIBILITY.** No post-result implementation/prompt/quality changes or validation retry were performed.

Setting the temporary pre-deploy command then redeploying produced `a006f395-cd19-4938-ab20-d6b033f1d5d3` but did not execute the command: old-deployment proxy history contains only the operator health GET, no test POST; no validation log records exist. The connector's environment-commit operation did not create a further deployment. Report-only commit `ea0f50c9af25c69e34c45015292d9a4322941b38` then applied current service settings through a fresh GitHub deployment without changing any frozen implementation, fixture, mode or evaluation hash.

The real one-shot job was deployment `154afa01-9cf6-4516-b6aa-93f51cc55be9`, executed 2026-09-21 18:40:22–18:41:54 UTC (elapsed **91.81622000038624 seconds**; Railway delivery timestamps lag/batch some lines). It ran against the healthy `a006f395` backend. The CREATE-only run marker prevents replay. It failed during the mechanical gate, so the replacement deployment was marked FAILED; the previously healthy backend remained available.

| Native mechanical check | Result | Actual observation |
| --- | --- | --- |
| Normal parent/TOC | PASS | Two exact evidence units; correct seven-day calibration fact in original parent text |
| Structure compilation | PASS | Seven source leaves, four generated rows, sealed publication |
| RAPTOR compilation | PASS | Seven leaves, one generated summary row, sealed publication |
| KG compilation | PASS | One completed document, seven original leaves, fourteen generated rows, document-level lineage |
| Navigation | PASS mechanical | Routed `doc-full-mechanical`; two generated artifacts and seven validated supporting original units; chunk-pointer count 0, not a claim of section-level routing success |
| RAPTOR retrieval | PASS mechanical | One selected generated summary with seven original support units |
| KG retrieval | PASS mechanical | Entity/relation context, twelve inspected generated artifacts and seven original support units |
| Agentic medium executor | FAIL | API 503 `CHAT_MODEL_UNAVAILABLE`, stage `Gemini native tool transport`; no final accepted answer |
| Post-mode adversarial live checks | NOT REACHED | Stop gate triggered first; offline security tests still pass |
| Final all-candidate DB revalidation | NOT REACHED | Positive response scope/version/hash checks passed; final aggregate pass was not reached |

**Exact observed failure:** two safe provider diagnostics reported `ClientError`, HTTP **400**, `INVALID_ARGUMENT`, category `INVALID_REQUEST`, phase `request`, retryable **false**. Call path: pinned `action_session._run_action_node` → `_llm_once_with_tools` → `_acompletion` → authorized neutral callback → `DevGemini.async_completion` → `Gemini35Provider.native_completion`. This is a native tool request/transport compatibility failure, not evidence of quota exhaustion or a retrieval-ranking failure. Sanitized diagnostics do not identify which request field Gemini rejected; no exact rejected-field cause is asserted without evidence. Text-mode callbacks succeeded earlier in the same run.

The fatal model error was latched and surfaced; no lower-quality answer or fallback was silently accepted. Upstream concurrent/fallback research paths subsequently logged the same latched exception. Railway reported **1,535 dropped runtime log messages** at its 500-lines/second limit. The validation job's separate 23-piece result envelope is complete and hash-verified; runtime log completeness is explicitly not claimed. Reducing failure-log amplification would require separate handling, not a quality-result tweak here.

Provider callback attempts: **16**; failures: **2**; reported usage from successful callbacks: **17,817 tokens**. This does not assert billable usage for failed requests or unseen provider-side token consumption. All calls used only the already-authorized development Gemini key. No other model/provider was used.

Quality evaluation results:

- SAME8: **NOT RUN (0/8 normal and 0/3 intended advanced)**.
- HOLDOUT_B: **NOT RUN (0/8 normal and 0/2 intended advanced)**.
- HOLDOUT_C: **created/frozen; NOT RUN (0/6 normal and 0/4 intended advanced)**; its four documents were not ingested because the gate stopped first.
- Old 90-case benchmark: **NOT RUN**.
- No quality scores, improvement claims or comparative recall claims are inferred from mechanical fixture success.

Preservation: all pre-existing synthetic source entries remained identical. Tenant A inventory 21 → 22; tenant B 18 → 19, only the new `full-mechanical` source added in each. Existing documents were not replaced or re-embedded. New source/TOC rows and the three tenant-A compiled collections are retained for audit, along with the one-shot marker; they were not deleted. No production/customer corpus was used. Generated rows remain labelled and cannot masquerade as original evidence.

Cleanup: temporary pre-deploy command removed; one-shot variable changed to `DISABLED_AFTER_ONE_SHOT`; future callback ceiling restored to 20. Changes apply with the final report-only deployment. No credentials were fetched, printed or persisted outside Railway; the job's process secret cleanup ran and its process ended. No new service, GPU, replica, volume resize or paid upgrade.

Evidence: `docs/RAGFLOW_FULL_PORT_LIVE_RESULTS.json` contains the exact gzip+base64 result payload plus safe provider diagnostics. Decoded payload SHA256 **`e64d831b29a1781262751373c5eb116226e85597ea14ee1576c03d8746a90160`**, 366,711 bytes. Outer transport SHA256 **`85b18ae2b027a79ceba53b131c20ffce366529a0a2533ef7f4b5fec36292e7ba`**. This is a partial mechanical report, not a successful full acceptance artifact.

**Next required work:** narrow, separately bounded Gemini native-tool request compatibility diagnosis/closure, using the actual upstream tool schemas and safe provider validation details, followed by a new explicit freeze/continuation plan. Keep all retrieval algorithms, prompts, model, datasets and scoring unchanged. Do not rerun successful lanes or start the old90/custom tuning on this result.

## Remaining differences and requirements for closer parity

1. **DeepDoc OCR/layout/table recognition:** needs pinned model assets, native/ONNX runtime and measured CPU/RAM. No GPU or paid service was provisioned merely to claim parity.
2. **Specialized book/law/paper/resume/email/QA pipelines:** shared CPU format parsing is not every product-specific template. Full parser configuration/task orchestration and separate format-parity fixtures remain.
3. **Vision/audio/video:** needs authorized VLM/ASR/media storage and source-lineage adapters; no fake multimodal text.
4. **KG NER/community:** spaCy language assets and pinned graspologic/native numerical closure are not installed; modes explicitly refuse before provider use. Light/general KG remains the delivered path.
5. **Arbitrary compiled templates and durable wiki:** requires owned FileCommitService/revision lifecycle and product compiler configuration. Copied helper source alone is not enabled workflow parity.
6. **RAPTOR dataset-wide/incremental operation:** delivered file scope; dataset-wide fake-document/revision lifecycle and durable checkpointing are not adapted.
7. **Metadata/tag operational breadth:** no full product metadata UI/index pushdown or automatic tag-KB ingestion workflow; explicit metadata/tags and query algorithms are present.
8. **Structured SQL:** needs a separate scoped SQL authorization/backend adapter. Application/customer DBs are not used as a shortcut.
9. **Distributed/durable task or conversation state:** operation-local state/history only; requires scoped task queue/cache/checkpoint persistence for cross-request resume.
10. **Generated answer claim attribution:** original support and model citation order are available; precise generated-claim/source entailment is not guaranteed by lineage.
11. **External web retrieval:** not configured or authorized. Alternate search backends and full RAGFlow account/billing/UI are outside the explicit engine/product boundary.

## Preservation and exclusions

All 28 pre-existing modified/untracked files matched their starting hashes before commit and were excluded. Working tree is intentionally not clean because that work remains. Local `main` stays `06f2d5d4c78805f54e818cc3886cf2438e5990cf`; local `origin/main` stays `7c8236001ccc552c89c860b2db6a4d4c369ee211`. No merge/main push/force push. No customer database/corpus, no production secret access, no production deployment, no old 90-case benchmark, no custom retrieval tuning.

See the frozen validation plan, full inventory, completeness matrix, agentic/KG/RAPTOR/navigation reports, dependency/license matrix and source manifest for exact paths and implementation limitations.
