# Full-port delivery matrix — current authoritative status

Pin: v0.27.2 / a024bea0cd93f39e6652a42bf84dd20c55bc560b. This section supersedes the historical expansion matrix below. Offline functionality is distinct from live acceptance. No claim of complete RAGFlow product parity is made.

| Subsystem | Delivered classification | Exact delivered path / limitation |
| --- | --- | --- |
| Text/HTML/Markdown parsing | FULLY PORTED selected CPU paths | Actual pinned Txt/HTML/Markdown parsers, merging and tokenizer; byte-only input, remote image fetching disabled for SSRF safety |
| DOCX/XLSX/CSV/JSON/JSONL/PPTX/EPUB | SUPPORTED / CONFIGURABLE | Actual upstream CPU parsers and DOCX merger; table/slide/sheet metadata preserved where parser exposes it; no invented binary layout coordinates |
| PDF text / outlines | SUPPORTED / CONFIGURABLE | Actual PlainParser; scanned pages do not become fake OCR text |
| DeepDoc OCR/layout/TSR | DEFERRED — model assets/native memory validation | Requires pinned ONNX assets, layout/OCR/table runtime; alternative GPU/provider parsers are not provisioned |
| Specialized book/law/paper/resume/email/QA pipeline templates | PARTIAL — exact limitation | Common CPU format parsing is present; template-specific grouping/enrichment/task orchestration is not universally exposed. Needs product parser configurations and format-specific parity fixtures; not synonymous with basic text parsing |
| Chunking / structural metadata | SUPPORTED / CONFIGURABLE | Actual upstream mergers and child split; headings/tables and exposed page/sheet/order metadata. Full PDF pipeline bounding boxes/title hierarchy depend on rich layout output |
| Embedding and indexing | FULLY PORTED selected algorithms / wrapped platform IO | Existing title/content blend, MiniLM profile and ES8.11.3. Immutable version markers/READY scope replace product DB |
| Lexical / vector / hybrid | FULLY PORTED selected ES algorithm | Actual Dealer/FulltextQueryer/ESQuery; no PostgreSQL/FTS/RRF/Q1 translation |
| Normal reranking | FULLY PORTED | Same actual cross-encoder, .2 threshold and .7/.3 blend. Candidate/top-k/context limits unchanged |
| Synonyms / normalization | FULLY PORTED selected path | Actual upstream query/synonym algorithms with native tokenizer and WordNet; Redis custom dictionaries not configured |
| Keyword / rewrite / follow-up / cross-language | SUPPORTED / CONFIGURABLE | Actual upstream prompts, conditional helper order and neutral callback; history never grants scope |
| Parent/child | SUPPORTED / CONFIGURABLE | Actual ingestion relationships and Dealer expansion; exact versioned parent evidence |
| TOC | SUPPORTED / CONFIGURABLE | Actual text-TOC generation, relevance and original leaf lookup; generated TOC is auxiliary |
| Context / original citations | SUPPORTED / CONFIGURABLE | Actual kb_prompt plus existing whole-unit final safety bounds; full original-source hashes and collision-resistant IDs |
| Document metadata | SUPPORTED / CONFIGURABLE | Actual manual/auto/semi-auto query operators; bounded READY-scoped catalogue. Product metadata-index pushdown/automatic ingestion schema UI not exposed |
| Tags | PARTIAL — exact limitation | Explicit tag indexing, actual aggregation/tag_query/tag_content algorithms and query rank-feature path. Full product tag-KB auto-labelling ingestion workflow is not configured; do not claim all tagged rows have auto-generated tag_feas |
| Agentic low/medium/high/ultra | SUPPORTED / CONFIGURABLE | Actual LangGraph executor, action session/state, decomposition, fanout, research, review, gaps, stopping and synthesis |
| Advanced reranking semantics | FULLY PORTED pinned tool behavior | Pinned agentic search tools do not pass normal cross-encoder callback; BM25/vector-only tools retain upstream route defaults. No invented uniform rerank |
| Document trees / navigation | SUPPORTED / CONFIGURABLE | Actual generated tree projection, dataset-nav compilation, tree descent and document outline runtime |
| Arbitrary mindmap/page-index/timeline/hypergraph/wiki templates | PARTIAL — exact limitation | Helper source mapped; product template/compiler/revision runtime not universally exposed. Versioned wiki fails explicitly without FileCommitService |
| KG extraction/storage/query | SUPPORTED / CONFIGURABLE | Actual light/general extraction, merging, indexing, KGSearch and optional entity resolution; owned ES artifacts; document-level lineage honestly labelled |
| KG NER / community | DEFERRED — native asset/dependency closure | Actual modules retained; spaCy language assets and pinned graspologic fork not installed; explicit refusal before calls |
| RAPTOR summaries / tree | SUPPORTED / CONFIGURABLE | Actual builder/serializer/projection, file scope; generated summaries plus original leaf support; single-leaf inputs legitimately produce no summary |
| RAPTOR retrieval | SUPPORTED / CONFIGURABLE | One upstream query across scoped leaves and summaries; actual cross-encoder for explicit mode; no custom fusion |
| RAPTOR dataset scope / durable incremental compilation | PARTIAL — exact limitation | File scope exposed; dataset-wide fake-document/revision lifecycle and durable checkpoints not adapted |
| Tables / structured retrieval | SUPPORTED / CONFIGURABLE for document text | Actual HTML/table/spreadsheet parser representations and retrieval; typed SQL analytics is separate and unavailable |
| SQL retrieval | DEFERRED — missing authorized structured backend | Needs a scoped SQL execution/validation adapter; never uses application/customer database |
| Multimodal image/audio/video | DEFERRED — model/assets/storage | Embedded images recognized/lazy interfaces copied; no vision caption, ASR, video understanding or OCR parity claimed |
| Neutral models | SUPPORTED / CONFIGURABLE | One authorized async chat/native-tool/usage abstraction with unchanged Gemini3.5 transport and upstream prompts |
| Tenant/provenance security | SUPPORTED / CONFIGURABLE, mandatory | Before/after checks for all routes, immutable artifacts, source hashes, manifest CAS and failure latching. Generated text is never verbatim |
| Generated answer citations | PARTIAL — exact limitation | Upstream final citation-pool order exposed with source support; model factual correctness/claim alignment is separately evaluated, not guaranteed by lineage |
| Persistent conversation/agent resume | PARTIAL — exact limitation | Caller-owned bounded history and request-local state; no shared Redis/checkpoint or cross-request durable memory |
| External web retrieval | DEFERRED — not authorized/configured | No implicit external corpus or provider fallback |
| Account/admin/billing/canvas/connectors | NOT APPLICABLE — product boundary | Existing SaaS remains authority; this is an internal retrieval engine, not a second RAGFlow product |
| Alternate search backends | NOT APPLICABLE — explicit ES choice | No assertion that Infinity/OceanBase/SQL behaviors are reproduced by ES |

Every supported software path must still pass the separately frozen native mechanical gate. New source mappings, dependency licenses, AST equality and offline security tests are documented alongside this matrix. No benchmark questions/case IDs/source targets enter the implementation. Custom quality heuristics added: **0**.

---

## Historical expansion matrix (retained for audit; not current status)
# Full pinned RAGFlow RAG completeness matrix

Pin: v0.27.2 / a024bea0cd93f39e6652a42bf84dd20c55bc560b. Scope: Python execution selected by dialog_service and task_executor, plus optional advanced modules. This is not a claim that the original port was full RAGFlow.

## Before expansion: source-traced inventory and port decisions

All upstream paths below are relative to the pinned repository. Dependencies include both algorithm helpers and storage/model prerequisites. Ordinary and optional paths are deliberately distinguished.

| Subsystem / status before | Upstream file + symbol / caller | Purpose, activation and dependencies | Local equivalent / semantic difference | Failure relationship / decision |
| --- | --- | --- | --- | --- |
| Parsing PARTIALLY PORTED | rag/app/naive.py:chunk; deepdoc/parser/*; task_executor.build_chunks | Format dispatch; PDF layout/OCR, DOCX images, text/HTML/Markdown/Excel; parser models, image storage | parsing.py: supplied text/HTML/Markdown; basic pypdf/python-docx, not full naive dispatcher | No missing source text in four failures. Retain working text path; OCR/layout/multimodal deferred (model/assets/infrastructure separate), not NOT REQUIRED. |
| Chunking PARTIALLY PORTED | rag/nlp/__init__.py:merge_paragraphs, tokenize_chunks, split_with_pattern; naive.chunk | Merging, positions and optional child delimiters; tokenizer, parsed blocks | upstream/chunking.py + parsing.py; child artifacts missing | Add actual child splitter and parent artifact integration, not a new heuristic. |
| Metadata PARTIALLY PORTED | task_executor.build_chunks; DocMetadataService; generator.gen_metadata | Optional auto metadata, important keywords/questions, tags; model, dataset metadata | Order/title/heading/type/source/version only | Port keyword/question generation callbacks and fields; metadata filter generation interface. Arbitrary SQL/DB mutation not imported. |
| Query normalization FULLY PORTED | rag/nlp/query.py:FulltextQueryer.question; Dealer.search | rmWWW, tokenizer, term weights, phrase construction, multilingual path | upstream/query.py; injected dependencies | Exact parity, no change. |
| Synonyms SIMPLIFIED | rag/nlp/synonym.py:Dealer.lookup/load; FulltextQueryer | Dictionary normalization, WordNet, optional Redis refreshed dictionary | runtime.NativeSynonyms sorted WordNet / simplified normalization | Replace with actual upstream Dealer, retain optional no-Redis configuration. Not a handcrafted paraphrase dictionary. |
| Multi-turn rewrite NOT PORTED | dialog_service.async_chat; generator.full_question | refine_multiturn + multiple questions; real prompt, chat callback | Raw query only | Port prompt/functions and exact conditional orchestration. Not a single-turn rescue guarantee. |
| Query optimization / expansion NOT PORTED | generator.cross_languages, keyword_extraction; async_chat | Optional languages / keyword setting; templates, sandbox, model | None | Port coherent prompt/parser/callback unit; default off, no invented rewrites. |
| Weighted keyword aspects NOT PORTED | advanced_rag/harness/keywords.py:extract_weighted_keywords; RAGTools.formalize | Agentic model-backed entity/alias/fact/qualifier extraction | None | Optional infrastructure port; do not silently enable in ordinary retrieval. |
| Lexical FULLY PORTED | FulltextQueryer + ESConnection.search | Boosted title/question/keyword/content token fields, phrases | upstream/query.py, es_query.py | Supporting documents already found; no channel tuning. |
| Vector FULLY PORTED | Dealer.get_vector, search; EmbeddingUtils | Same query vector, title/content embedding, KNN | engine.py, upstream/search.py | All expected sources in vector candidates; no model change. |
| Hybrid FULLY PORTED | Dealer.search/build_fusion_expr; ESConnection.search | Weighted sum, scoped lexical KNN filter, score recovery | upstream/search.py/es_query.py | Not RRF; preserve pin. |
| Empty-result retry FULLY PORTED | Dealer.search | Relax lexical minimum/threshold after empty set | upstream/search.py | No dense-only rescue at this pin; not first failure here. |
| Exact / broad / field requests WRAPPED | FulltextQueryer fields + user doc_ids + metadata filter in async_chat | Generic lexical/vector paths, caller scope; structured SQL optional | AuthorizedScope/document_ids; no full metadata/SQL path | No universal field-completion or category algorithm in Dealer; no custom addition. |
| Reranking FULLY PORTED | Dealer.rerank, rerank_by_model, retrieval | Token/model blend, candidate ordering, score threshold; selected model | upstream/search.py + CPU callback | Exact measured failure layer; preserve algorithms and constants. |
| Multi-document preservation NOT PORTED (agentic) | agentic_rag_graph:_expand_fanouts/_fanout_search/build_agentic_graph | Optional high/ultra planner fanout + evidence merge, SCA loops; LangGraph, RAGTools, action_session, tools | No equivalent in ordinary engine | No such guarantee in ordinary Dealer. Do not invent reservation; full tool executor requires scope-safe navigation and model gate. |
| Parent retrieval NOT PORTED | Dealer.retrieval_by_children; async_chat; task_executor.insert_chunks | Always called after retrieval; no-op without mom_id; parent available=0, mean child scores | None | Add actual method AND child/parent ingestion and strict linked-parent storage route. Cannot rescue zero surviving children. |
| TOC retrieval NOT PORTED | Dealer.retrieval_by_toc; async_chat toc_enhance | Highest aggregate-scoring document; model TOC relevance; task_executor.build_TOC, generator.run_toc_from_text | None | Add complete text TOC generation/ID mapping + relevance + scoped artifacts. Default off; not global multi-document rescue. |
| Document/chunk listing PARTIALLY PORTED | Dealer.chunk_list; RAGTools.fetch_full_document | Ordered chunks, explicit doc restriction; storage and authority | Only final evidence retrieval | Scope-safe exact ID/parent APIs; full agent document navigation remains optional integration work. |
| Context PARTIALLY PORTED | generator.kb_prompt/message_fit_in; async_chat | Whole retrieval block selection, message budget and framing | context.kb_prompt plus exact whole-block cap | Keep collision-safe full citation IDs / 131072-byte and 48-unit guards; port message_fit_in for model functions. No losses here. |
| Citation support PARTIALLY PORTED | Dealer.insert_citations; generator.citation_prompt; async_chat.decorate_answer | Generated-answer sentence/vector attribution + reference hydration | Dealer helper present; native API returns exact evidence citations, no chat generation | Port exact prompt helpers, not fabricate generated answers. Live generation model unavailable. |
| Graph NOT PORTED | graphrag/search.py:KGSearch.retrieval/query_rewrite; async_chat use_kg | Optional extracted entity/relation/community graph, n-hop/Pagerank; extractor, resolution, community reports, graph store, model | None | Inspect complete query path; optional graph not enabled. Cannot safely pretend synthetic aggregate graph doc_id='' is ordinary single-source evidence; requires lineage-aware composite adapter + ingestion. |
| RAPTOR NOT PORTED | advanced_rag/knowlege_compile/raptor.py:RecursiveAbstractiveProcessing4TreeOrganizedRetrieval; task executor/compiler | Optional watershed clustering + LLM summary hierarchy + embeddings; caches/limiter/task cancellation | None | Optional ingestion not automatic rescue. Source-leaf lineage and summary-vs-verbatim representation must be explicit; no fabricated summaries/embeddings. |
| Tree / structure NOT PORTED | harness/tools/navigation.py; compiled_expansion.py; exploration.py; flow/compiler/compiler.py | Optional navigate_tree/navigate_structure/read compiled nodes/expand leaves; build TOC/tree/graph artifacts | None | TOC infrastructure now prioritized; full compiled graph navigation not equated with plain parent lookup. |
| Agentic orchestration NOT PORTED | agentic_rag_graph.run_agentic_rag/build_agentic_graph; RAGTools.rag; dialog_service.rag_agent | reasoning modes low/medium/high/ultra; formalize, planner, fanout, tool actions, review, replan; model, graph, action_session and retrieval/navigation tools | None | Port standalone mode/keyword/reviewer/gap-rewrite interfaces with actual upstream dependencies; full executor kept disabled until coherent tool/scope integration, not a hand-written substitute. |
| Sufficiency / gap generation NOT PORTED | generator.sufficiency_select/multi_queries_gen; harness/orchestrator/sufficient_context.py/query_rewriter.py | Optional model review and follow-up queries with real prompts/parser/stats | None | Port callback infrastructure; no automatic custom loop in normal engine. |
| Tags / ranking metadata PARTIALLY PORTED | rag/app/tag.py:label_question; Dealer.tag_query/tag_content/all_tags; task ingestion | Optional tag corpus and PageRank features | Score helper copied; native rank_feature=None, no tag corpus | Not activated without actual tag artifacts; no fabricated labels. |
| Text-to-SQL NOT PORTED | dialog_service.use_sql; structured KB fields, agent structured_retrieve | Optional tabular DB mode + model/schema; MySQL/SQL AST/security | None | Not needed for these plain-text sources but RAG-relevant; deferred separate scoped structured-data adapter. |
| Web / memory / multimodal NOT PORTED | web_search_conn; dialog_service attachments; memory retrieval | Optional external APIs/credentials, attachments/vision, conversation memory | None | Explicitly unavailable here, not substitutes for missing customer corpus evidence; no external calls authorized. |
| Product-only NOT REQUIRED | frontend, billing, account/admin screens, unrelated connectors/UI | Product operations, not retrieval algorithms | Existing SaaS retained | Exclude; no reason to import a second account system. |

## Security and fidelity rules for expansion

All rewritten queries retain the original server-issued scope. No model output can change organization/bot/source/version/generation. Auxiliary TOC/parent rows are unavailable to ordinary candidate search; access requires READY manifests plus explicit relationship checks. Post-fetch row identity and exact-text hashes remain mandatory. Unauthorized relationships fail closed rather than falling back to broad search.

No score/weight/threshold/top-k/model/context-limit modification is authorized. Optional model-backed capabilities remain off by default; their real prompts and callbacks can be tested offline without pretending mocked outputs are live evidence.

## Completion ledger

Paths abbreviated as `advanced_rag/...` and `flow/...` above are under upstream `rag/`. `task_executor` means `rag/svr/task_executor.py`; `dialog_service` means `api/db/services/dialog_service.py`.

### Expanded implementation (before frozen live validation)

- **FULLY PORTED algorithms / WRAPPED authority:** actual synonym Dealer, ordinary conditional query preparation, prompt/template/JSON-repair/message-budget chain, child splitting, child-to-parent retrieval and mean-score/missing-parent fallback, text TOC generation/leaf mapping and optional relevance retrieval. Keyword/question ingestion uses upstream delimiters/fields. Model-backed features are integrated but require an explicit callback; offline doubles are NOT live acceptance.
- **PARTIALLY PORTED optional agentic infrastructure:** actual mode configuration, weighted keyword extraction, sufficient-context evaluator, gap rewriter, prompts and telemetry. NO full graph executor, fanout/tool-navigation session or automatic agentic API mode. Helpers are not full agentic RAG.
- **Still PARTIALLY PORTED:** format dispatcher (no full DeepDoc/OCR/layout), position-rich chunking, metadata schemas/filter execution, tag corpora/rank features, generated-answer citation decoration. Existing whole-block context safety caps remain; no generation endpoint was fabricated.
- **Still NOT PORTED:** KG ingestion/search, RAPTOR summary/tree ingestion, compiled-structure navigation, full RAGTools/action_session/LangGraph, SQL/web/memory/multimodal routes. Graph composite evidence and RAPTOR summaries need explicit source-leaf lineage and generated-artifact representation, not ordinary single-source verbatim evidence. Algorithms inspected, not reimplemented.
- **Blocked live gate:** real rewrite, keyword, TOC and reviewer model callbacks. No chat provider credential is authorized specifically for this new service; old keys are not reused. Graph/RAPTOR/compiler also require additional coherent scope-safe artifact/tool integration; a key alone does not complete them.

Ordinary pinned Dealer does not reserve each intent/document through its reranker cutoff. Parent expansion requires surviving children; TOC requires nonempty results and chooses the highest aggregate-scoring document. Neither is asserted to rescue the measured empty cases. Post-pin natural-text reranking and dense-only rescue remain deferred.

Pre-freeze validation: **192/192** focused tests passed, including 11 adapted upstream prompt tests (unchanged fixtures/assertions), two exact upstream AST method parity checks, existing parser/rerank tests and scoped integration/security tests. Provenance verifier PASS: 78 mapped files / 82 mappings, official blobs verified.

### Subsequent authorized provider boundary / final freeze

The user explicitly authorized an existing TEST Gemini key, to be set directly as `RAGFLOW_DEV_GEMINI_API_KEY` in the new project's backend. No secret value was retrieved. The adapter selects only this variable and this project; pinned GoogleChat's Gemini request/response mapping is adapted to API-key transport. MiniLM models remain unchanged. Twenty-call process ceiling, one transport attempt, safe exceptions and per-call client cleanup are infrastructure controls, not query-quality changes.

Final runtime freeze: **ed6dde00dc3742bf899cac3dbcd38fc7e0d4e2f3**. Validation harness: **f98ca701f6f2f991560421a574e942d2b6f231af**. Tests: **197/197**. Provenance: **79 distinct destination files / 83 source mappings**. This workstream adds **49 mapped upstream files: 15 COPY + 34 ADAPT** (35 prompts, 12 runtime Python files and 2 upstream test files). Twenty prompt ADAPTs differ only at terminal whitespace; all rendered prompt texts match the pinned loader output. Existing search/runtime/engine mappings were updated separately and are not counted as new files. Custom quality heuristics added: **0**.

The initial blocked live gate above is historical. The user subsequently set the dedicated test variable; the configured deployment is healthy. The once-only live runner then failed on the FIRST question with HTTP 503: one failed callback attempt, zero successful answers, no holdout/structural ingestion. The exact provider/SDK cause is suppressed and unproven; no retry or quality fix was made. SAME8 and GENERIC_HOLDOUT_B remain unscored. The job hook/gate are disabled. See `RAGFLOW_EXPANDED_LIVE_VALIDATION_REPORT.md`. No improved-quality claim is made. The frozen validation plan distinguishes uniform optional keyword mode from the original default baseline.
