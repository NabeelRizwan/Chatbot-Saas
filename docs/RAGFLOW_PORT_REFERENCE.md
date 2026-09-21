# RAGFlow port reference

## Current full-port extension

The historical mappings below are retained for audit. Current delivered status is
`RAGFLOW_FULL_RAG_COMPLETENESS_MATRIX.md`; the fresh source audit is
`RAGFLOW_COMPLETE_RAG_INVENTORY.md`. Newly mapped pinned modules include the
complete coherent agentic executor/tool dependency closure, KG extraction and
search, RAPTOR/tree generation, real document navigation, CPU rich parsers and
metadata operators. `third_party/ragflow_port_manifest.json` records exact
upstream Git blob IDs/SHA-256 and local destination SHA-256 for every source
mapping, including copied upstream regression tests.

Boundary adapters are `advanced.py`, `full_runtime.py`, `artifacts.py`,
`compilation.py`, `modes.py`, `structured_parsing.py`, and the neutral model
transport. These provide server authorization, immutable source/artifact
ownership, byte-only input, operation lifetime and explicit capabilities; they
do not replace upstream ranking, clustering, prompts or state transitions.
See the agentic, navigation, KG, RAPTOR, runtime and dependency reports for
call graphs, restrictions and exact deferred requirements. Historical statements
that those modes are wholly absent no longer describe this delivery.

`verify_ragflow_full_algorithms.py` compares 13 critical algorithm ASTs with the
pin. `verify_ragflow_port.py` verifies every mapping and original Git blob.
No later upstream algorithm commit is imported. External license notices were
consulted only for attribution.

## Pin and provenance

### Completeness expansion — 2026-09-21

See the generic failure forensics and full RAG completeness matrix for the measured failure layer and normal/optional execution inventory. This remains a partial port, not all RAGFlow.

New coherent units: complete upstream prompt generator/templates; actual synonym Dealer; selected tokenize/child splitter; task_executor.build_TOC; Dealer.retrieval_by_toc/retrieval_by_children; conditional preparation from dialog_service.async_chat; optional mode/keywords/SCA/rewriter/stats interfaces. Exact source symbols/ranges/hashes and destination hashes, including test adaptations, are in the manifest.

Adaptations are package paths, explicit operator async chat callback replacing product model DB resolution, request-local scoped cache replacing Redis, scoped SHA256 auxiliary identities, async service integration and sensitive-log suppression. Generic security constrains delimiter input and enforces authority/READY/relationship/hash validation. No retrieval-quality heuristics, threshold/weight/top-k/model or context-cap changes. Parent/TOC unavailable rows are auxiliary only; generated TOC is never verbatim evidence. Default same-version ingestion retains its prior digest.

Official repository: https://github.com/infiniflow/ragflow

Release: **v0.27.2**, exact commit **a024bea0cd93f39e6652a42bf84dd20c55bc560b**. Release metadata published 2026-09-10T11:11:35Z; lightweight tag resolves to that commit. [Official release](https://github.com/infiniflow/ragflow/releases/tag/v0.27.2). The pin is an ancestor of observed official main **83c47d02518265f8bdec9ec226a2531f4a59f340**. This observation is recorded, not a floating dependency.

Root LICENSE is Apache-2.0; no root NOTICE is present at the pin. All copied Python headers remain, modified files carry modification notices. Our third_party/ragflow/NOTICE explicitly identifies itself as our attribution, not an upstream file. third_party/ragflow_port_manifest.json records canonical git-blob SHA-256, destination-byte SHA-256 and exact ranges. scripts/verify_ragflow_port.py verifies both sides against the local official clone.

## Release-to-main safety review

No post-release patch is included. Relevant inspected commits:

| Exact later commit / PR | Changed paths relevant to review | Reason / applicability / decision |
| --- | --- | --- |
| 3a9b84495c94b282f1a98ea172f305d994c08991 / #19524 | common/doc_store/ob_conn_base.py; memory/utils/ob_conn.py; rag/utils/ob_conn.py; associated tests | Column-name SQL injection hardening. OceanBase not selected/imported: not applicable, OMIT. |
| 5c91e65dde33075542b01e503e6c64e039cbe85a / #19502 | rag/nlp/search.py; rag/utils/infinity_conn.py; agentic/harness callers; Go retrieval; tests | Adds dense-only rescue after two empty hybrid passes. Relevant recall limitation, but no silent rank/behavior change from pin; NOT ADOPTED. |
| 941edd12696a1a1fbb045426a7d34ce18228587c / #16961 | rag/nlp/search.py; internal/service/nlp/reranker.go; rerank input tests | Natural-text neural reranker input instead of tokenized content. Relevant quality issue, NOT ADOPTED; disclose and evaluate independently later. |
| 85f3e89619948c228ed99f81ac28b7853f5dc249 / #19521 | rag/nlp/__init__.py; test_docx_chunk_order.py | Flushes pending text before DOCX table/image blocks. Affected _build_cks path not ported; our ordered python-docx wrapper has its own generic order test. NOT ADOPTED. |
| 9e932547e5b8ed35f47647c0fc9ac91b3cefde30 / #19578 | document_api.py and Azure/GCS/MinIO/OSS connectors | Preserves object-store retry errors. Existing platform storage retained, none of these connectors imported. NOT ADOPTED. |

Other reviewed parser changes concerned OCR/textless PDF figures, DOCX textboxes, XLSX sparse/type handling, EPUB and Go services outside this selected path. They are not treated as proof those optional layers are safe/complete here. PR numbers above come from official commit messages. Source links resolve via the full pin below; no main source is vendored.

## Actual upstream call chain and selected coherent subset

Upstream task_executor.do_handle_task (1443-1777) selects parser/chunker, prepares documents and invokes embedding/indexing. rag/app/naive.py chunk (1069-1475) dispatches formats; DeepDoc/plain format parsers and rag/nlp merge/tokenization produce searchable chunk dictionaries. EmbeddingUtils prepares titles/content and combines vectors before DocStore insertion.

The product dialog path (api/db/services/dialog_service.py, approximately 734-807) optionally rewrites multi-turn queries / translates / extracts keywords, invokes Dealer.retrieval, optional TOC/child expansion, web/KG enrichment, then kb_prompt. Dealer constructs FulltextQueryer + MatchDenseExpr + FusionExpr, calls ESConnection.search, prunes deleted parents, recovers clean cosine scores for ES, performs token/cosine or learned rerank, and returns selected chunks. kb_prompt renders ID/title/URL/content.

Our engine owns a complete ordinary text/HTML/Markdown + basic document path through these actual algorithms. Product identity/queues/settings are replaced with narrow platform adapters. Optional advanced retrieval is not claimed complete. The interface supports generic queries without injecting known cases or labels.

## Per-component mapping

All entries below refer to the exact pinned commit above. Direct dependencies include their important transitive/runtime requirements; see the dependency matrix for individual licenses and versions. COPY means byte-identical; ADAPT includes namespace moves or selected functions. WRAP/REIMPLEMENT are explicitly not claims of copied algorithm equivalence.

### 1. License text

- Upstream: [LICENSE](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/LICENSE), range **1-201**.
- Symbol(s): file data.
- Input → output: Redistribution → Apache terms.
- Direct/transitive dependencies: None. Service: None. Database/index: No store.
- Current equivalent: Attribution.
- Decision: **COPY** → `third_party/ragflow/LICENSE`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: manifest verifier.

### 2. Delimiter grammar

- Upstream: [rag/nlp/delim.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/delim.py), range **1-179**.
- Symbol(s): normalize_text_newlines (91-95); has_wrapped_delimiter (98-107); parse_delimiter_field (110-162); compile_delimiter_pattern (165-179).
- Input → output: Delimiter configuration → compiled protected split boundaries.
- Direct/transitive dependencies: stdlib re. Service: None. Database/index: No store.
- Current equivalent: Current section splitter.
- Decision: **COPY** → `backend/ragflow_derived/upstream/delim.py`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported txt/Markdown tests.

### 3. Expression/storage contract

- Upstream: [common/doc_store/doc_store_base.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/common/doc_store/doc_store_base.py), range **1-277**.
- Symbol(s): SparseVector (26-55); MatchTextExpr (58-69); MatchDenseExpr (72-87); MatchSparseExpr (90-103); MatchTensorExpr (106-119); FusionExpr (122-126); OrderByExpr (132-145); DocStoreConnection (148-277).
- Input → output: MatchText/MatchDense/Fusion/OrderBy → backend request contract.
- Direct/transitive dependencies: numpy/types. Service: ES via adapter. Database/index: Search index.
- Current equivalent: Current typed candidate interfaces.
- Decision: **COPY** → `backend/ragflow_derived/upstream/doc_store.py`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ES DSL and engine tests.

### 4. Float/percentage normalization

- Upstream: [common/float_utils.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/common/float_utils.py), range **1-83**.
- Symbol(s): get_float (18-47); normalize_overlapped_percent (50-58); format_minimum_should_match_percent (61-83).
- Input → output: Numeric input → safe normalized weights/minimum match.
- Direct/transitive dependencies: stdlib. Service: None. Database/index: No store.
- Current equivalent: Current ranking config.
- Decision: **COPY** → `backend/ragflow_derived/upstream/float_utils.py`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported search/parser tests.

### 5. Whitespace/markdown helpers

- Upstream: [common/string_utils.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/common/string_utils.py), range **1-77**.
- Symbol(s): remove_redundant_spaces (20-46); clean_markdown_block (49-73); is_content_empty (76-77).
- Input → output: Text → normalized utility representation.
- Direct/transitive dependencies: stdlib re. Service: None. Database/index: No store.
- Current equivalent: Current text helpers.
- Decision: **COPY** → `backend/ragflow_derived/upstream/string_utils.py`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported reranker tests.

### 6. Rank-feature parsing

- Upstream: [common/tag_feature_utils.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/common/tag_feature_utils.py), range **1-85**.
- Symbol(s): parse_tag_features (22-61); validate_tag_features (64-85).
- Input → output: Serialized tag features → validated feature map.
- Direct/transitive dependencies: stdlib json/numbers. Service: None. Database/index: No store.
- Current equivalent: Current structured ranking.
- Decision: **COPY** → `backend/ragflow_derived/upstream/tag_feature_utils.py`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported search tests.

### 7. Generic multilingual query helpers

- Upstream: [common/query_base.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/common/query_base.py), range **1-74**.
- Symbol(s): QueryBase (20-74).
- Input → output: Query → normalized/token-spaced string.
- Direct/transitive dependencies: stdlib re. Service: None. Database/index: No store.
- Current equivalent: query_contract generic helpers.
- Decision: **COPY** → `backend/ragflow_derived/upstream/query_base.py`.
- Modifications: Unmodified pinned source.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: engine query categories.

### 8. Index mapping

- Upstream: [conf/mapping.json](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/conf/mapping.json), range **1-212**.
- Symbol(s): file data.
- Input → output: Chunk fields → typed ES templates/scripted similarity.
- Direct/transitive dependencies: Elasticsearch. Service: ES 8.11.3. Database/index: Separate ragflow_<scope> index.
- Current equivalent: PostgreSQL chunk/vector schema.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/mapping.json`.
- Modifications: Unmodified pinned source.; newline normalization only
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: mapping/DSL offline; native deferred.

### 9. Markdown structure extraction

- Upstream: [deepdoc/parser/markdown_parser.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/deepdoc/parser/markdown_parser.py), range **1-567**.
- Symbol(s): RAGFlowMarkdownParser (32-157); MarkdownElementExtractor (160-567).
- Input → output: Markdown → fenced/list/table/text sections.
- Direct/transitive dependencies: Markdown, delimiter module, re. Service: None. Database/index: No store.
- Current equivalent: structural Markdown adapter.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/markdown_parser.py`.
- Modifications: Namespace-only import relocation; retains fenced/table/heading extraction.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported Markdown + engine fixtures.

### 10. HTML parsing and bounded block merge

- Upstream: [deepdoc/parser/html_parser.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/deepdoc/parser/html_parser.py), range **1-319**.
- Symbol(s): get_encoding (27-30); RAGFlowHtmlParser (37-319).
- Input → output: HTML bytes/text → ordered text/table chunks.
- Direct/transitive dependencies: BeautifulSoup, chardet, tokenizer. Service: None. Database/index: No store.
- Current equivalent: existing crawl markdown/extractors.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/html_parser.py`.
- Modifications: Namespace/decode adapter and injectable tokenizer; HTML block/table/whitespace algorithms unchanged.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported HTML including shared Go fixture.

### 11. Paragraph merge strategies

- Upstream: [rag/nlp/__init__.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/__init__.py), range **1271-1394**.
- Symbol(s): MergeStrategy (1271-1283); _merge_paragraph_groups (1286-1361); merge_paragraphs (1364-1393).
- Input → output: Paragraphs + token budget → OVER_CAP/UNDER_CAP groups.
- Direct/transitive dependencies: token counting, stdlib. Service: None. Database/index: No store.
- Current equivalent: chunking_service.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/chunking.py`.
- Modifications: Extract pure merge strategy/grouping functions without image/PDF/product import graph.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported txt + mixed block tests.

### 12. Plain text parser

- Upstream: [deepdoc/parser/txt_parser.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/deepdoc/parser/txt_parser.py), range **1-64**.
- Symbol(s): RAGFlowTxtParser (30-64).
- Input → output: Text + delimiter → chunks.
- Direct/transitive dependencies: delimiter, merge, decode/token helpers. Service: None. Database/index: No store.
- Current equivalent: current text ingestion.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/txt_parser.py`.
- Modifications: Relocate imports; parser split/merge behavior unchanged.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported txt tests.

### 13. Term importance / OOV weighting

- Upstream: [rag/nlp/term_weight.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/term_weight.py), range **1-274**.
- Symbol(s): _alphabetic_oov_frequency (30-53); Dealer (56-274).
- Input → output: Tokens → term weights.
- Direct/transitive dependencies: tokenizer, ner.json, stdlib math. Service: None. Database/index: No store.
- Current equivalent: current lexical tokens.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/term_weight.py`.
- Modifications: Dependency-inject tokenizer; retain weighting/OOV formulas, package resource path.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: FulltextQueryer engine execution.

### 14. FulltextQueryer

- Upstream: [rag/nlp/query.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/query.py), range **1-231**.
- Symbol(s): FulltextQueryer (28-231).
- Input → output: Question → MatchTextExpr, keywords, token/vector similarity.
- Direct/transitive dependencies: term_weight, tokenizer, synonyms, numpy, sklearn. Service: None directly. Database/index: ES query contract.
- Current equivalent: current query planner / PostgreSQL FTS.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/query.py`.
- Modifications: Retain weighted query/phrase/token/hybrid formulas; injectable tokenizer/synonym; remove Redis global.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: engine + upstream rerank tests.

### 15. Dealer retrieval/rerank/citations

- Upstream: [rag/nlp/search.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/search.py), range **1-812**.
- Symbol(s): build_fusion_expr (36-43); index_name (46-47); Dealer (50-1022).
- Input → output: Question/model/scope → scored chunks.
- Direct/transitive dependencies: query, DocStore, numpy, thread executor. Service: Scoped ES adapter. Database/index: Only authorized index/version.
- Current equivalent: rag_service retrieval / hybrid_retrieval.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/search.py`.
- Modifications: Retain search/retrieval/weighted rerank/citation algorithms; inject store/queryer/backend flags; replace MySQL deletion cache with fresh adapter guard; omit SQL/graph/tagging/TOC product entrypoints.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ported rerank + end-to-end fixtures.

### 16. Embedding text/vector preparation

- Upstream: [rag/svr/task_executor_refactor/embedding_utils.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/svr/task_executor_refactor/embedding_utils.py), range **1-217**.
- Symbol(s): EmbeddingUtils (38-217).
- Input → output: Chunks → title/content texts → blended vector attachment.
- Direct/transitive dependencies: numpy, truncate/token utilities. Service: Injected embedding model. Database/index: q_<dimension>_vec.
- Current equivalent: current embedding worker.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/embedding_utils.py`.
- Modifications: Namespace-only token counter adapter; preserve title/content preparation and weighted vector combination.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: ingestion/profile/vector validation tests.

### 17. kb_prompt

- Upstream: [rag/prompts/generator.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/prompts/generator.py), range **37-38;140-175**.
- Symbol(s): get_value (37-38); kb_prompt (140-175).
- Input → output: Scored chunks + budget → ID/title/URL/exact-content blocks.
- Direct/transitive dependencies: token counting, regex. Service: None. Database/index: No store.
- Current equivalent: current prompt evidence serialization.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/context.py`.
- Modifications: Extract kb_prompt; stable full IDs replace collision-prone modulo500 IDs; no upstream generation/prompt product imported.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: whole-block/citation/context cap tests.

### 18. Elasticsearch search/store boundary

- Upstream: [rag/utils/es_conn.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/utils/es_conn.py), range **179-317**.
- Symbol(s): _is_query_string_clause (63-64); _remove_query_string_must_clauses (67-72); _build_knn_filter_query (75-97); ESConnection (101-654).
- Input → output: Expressions/scope → real ES DSL/results.
- Direct/transitive dependencies: elasticsearch-dsl, elasticsearch, transport. Service: Loopback ES. Database/index: Pinned mapping and scoped vector field.
- Current equivalent: current pgvector/FTS.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/es_query.py`.
- Modifications: Preserve ES DSL/filter/knn/weighted query construction; explicit injected client; remove singleton/global pool, payload logging, mutable caller conditions, unneeded >10k pagination, opaque retry wrappers; fail structured at platform boundary.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: actual DSL capture, source marker/guard tests.

### 19. Upstream unit regression assertions

- Upstream: [test/unit_test/deepdoc/parser/test_txt_parser.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/test/unit_test/deepdoc/parser/test_txt_parser.py), range **1-108**.
- Symbol(s): _fake_word_tokens (34-35); _nonempty (38-39); test_over_cap_accumulates_adjacent_paragraphs (42-51); test_oversize_unit_not_atom_split (54-60); test_delimiter_text_not_in_chunk (63-69); test_consecutive_delimiters_do_not_leak_delimiter_text (72-79); test_token_size_zero_keeps_each_paragraph_alone (82-86); test_delimiter_boundary_when_segment_exceeds_cap (89-94); test_keep_delimiters_preserves_delimiter (97-104); test_empty_text_returns_empty (107-108).
- Input → output: Generic test fixtures → pinned expected parser/rerank behavior.
- Direct/transitive dependencies: pytest + corresponding ported component. Service: None. Database/index: Fixture only.
- Current equivalent: Current architecture regression tests.
- Decision: **ADAPT** → `backend/tests_ragflow/test_upstream_txt.py`.
- Modifications: Point original assertions at port namespace; remove product/global module stubs; pytest-scoped tokenizer fixture.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: the mapped test itself.

### 20. Upstream unit regression assertions

- Upstream: [test/unit_test/deepdoc/parser/test_markdown_parser.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/test/unit_test/deepdoc/parser/test_markdown_parser.py), range **1-260**.
- Symbol(s): markdown_element_extractor (28-43); markdown_parser_module (47-62); TestMarkdownElementExtractorFences (66-127); TestMarkdownElementExtractorTables (131-177); TestMarkdownTableDedup (181-244); TestMarkdownElementExtractorDelimiterHeaders (247-260).
- Input → output: Generic test fixtures → pinned expected parser/rerank behavior.
- Direct/transitive dependencies: pytest + corresponding ported component. Service: None. Database/index: Fixture only.
- Current equivalent: Current architecture regression tests.
- Decision: **ADAPT** → `backend/tests_ragflow/test_upstream_markdown.py`.
- Modifications: Point original assertions at port namespace; remove product/global module stubs; pytest-scoped tokenizer fixture.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: the mapped test itself.

### 21. Upstream unit regression assertions

- Upstream: [test/unit_test/deepdoc/parser/test_html_parser.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/test/unit_test/deepdoc/parser/test_html_parser.py), range **1-233**.
- Symbol(s): _find_project_root (61-67); _FakeTokenizer (83-101); _token_count (108-109); test_oversized_english_block_preserves_original_text (112-126); test_oversized_chinese_block_is_split_and_preserved (129-139); test_small_blocks_are_merged_unchanged (142-147); test_parser_txt_extracts_bodyless_html_fragment (150-155); test_parser_txt_keeps_text_before_first_block (158-168); test_parser_txt_keeps_loose_text_between_and_after_blocks (171-177); _merge_one_block (193-202); test_unified_html_semantics_parity (206-207); test_merge_block_text_loose_text_newline_join (210-233).
- Input → output: Generic test fixtures → pinned expected parser/rerank behavior.
- Direct/transitive dependencies: pytest + corresponding ported component. Service: None. Database/index: Fixture only.
- Current equivalent: Current architecture regression tests.
- Decision: **ADAPT** → `backend/tests_ragflow/test_upstream_html.py`.
- Modifications: Point original assertions at port namespace; remove product/global module stubs; pytest-scoped tokenizer fixture.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: the mapped test itself.

### 22. Upstream unit regression assertions

- Upstream: [test/unit_test/rag/nlp/test_search_rerank.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/test/unit_test/rag/nlp/test_search_rerank.py), range **1-142**.
- Symbol(s): _dealer (39-58); _sres (61-70); test_rerank_by_model_includes_question_tks (73-90); test_rerank_by_model_does_not_repeat_fields (93-106); test_all_rerank_paths_include_question_tks (111-126); test_rerank_by_model_handles_missing_question_tks (129-142).
- Input → output: Generic test fixtures → pinned expected parser/rerank behavior.
- Direct/transitive dependencies: pytest + corresponding ported component. Service: None. Database/index: Fixture only.
- Current equivalent: Current architecture regression tests.
- Decision: **ADAPT** → `backend/tests_ragflow/test_upstream_rerank.py`.
- Modifications: Point original assertions at port namespace; remove product/global module stubs; pytest-scoped tokenizer fixture.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: the mapped test itself.

### 23. Term feature resource

- Upstream: [rag/res/ner.json](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/res/ner.json), range **1-10880**.
- Symbol(s): file data.
- Input → output: Term → numeric/category features.
- Direct/transitive dependencies: term_weight. Service: None. Database/index: Packaged immutable JSON.
- Current equivalent: None reused.
- Decision: **COPY** → `backend/ragflow_derived/upstream/res/ner.json`.
- Modifications: Pinned upstream resource/fixture; final newline normalized if required.
- License: Apache-2.0 (upstream repository license; no per-file exception found); retain attribution; changed notice for adapted code. Tests: hash/provenance and query tests.

### 24. Pinned synonym resource

- Upstream: [rag/res/synonym.json](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/res/synonym.json), range **1-10546**.
- Symbol(s): file data.
- Input → output: Word → synonym list.
- Direct/transitive dependencies: runtime.NativeSynonyms. Service: None. Database/index: Packaged immutable JSON.
- Current equivalent: None reused.
- Decision: **COPY** → `backend/ragflow_derived/upstream/res/synonym.json`.
- Modifications: Pinned upstream resource/fixture; final newline normalized if required.
- License: Apache-2.0 (upstream repository license; no per-file exception found); retain attribution; changed notice for adapted code. Tests: hash/provenance verification.

### 25. Shared upstream parser fixture

- Upstream: [internal/parser/parser/testdata/unified_html_cases.json](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/internal/parser/parser/testdata/unified_html_cases.json), range **1-12**.
- Symbol(s): file data.
- Input → output: HTML → expected extracted text.
- Direct/transitive dependencies: ported HTML test. Service: None. Database/index: Fixture only.
- Current equivalent: No runtime equivalent.
- Decision: **COPY** → `backend/tests_ragflow/upstream_html_cases.json`.
- Modifications: Pinned upstream resource/fixture; final newline normalized if required.
- License: Apache-2.0 (upstream repository license; no per-file exception found); retain attribution; changed notice for adapted code. Tests: shared semantic parity tests.

### 26. Dictionary + WordNet expansion

- Upstream: [rag/nlp/synonym.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/synonym.py), range **34-101**.
- Symbol(s): Dealer (34-101).
- Input → output: Token → bounded synonym list.
- Direct/transitive dependencies: JSON + NLTK WordNet. Service: No Redis in port. Database/index: Packaged synonym data.
- Current equivalent: current query expansion.
- Decision: **ADAPT** → `backend/ragflow_derived/upstream/runtime.py`.
- Modifications: Dealer.lookup: pinned dictionary and WordNet; remove Redis/live reload; lazy initialization; deterministic sorted synonym selection; local token/decode/thread helpers.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: injected deterministic synonym tests; native assets deferred.

### 27. Release tokenizer wrapper

- Upstream: [rag/nlp/rag_tokenizer.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/nlp/rag_tokenizer.py), range **20-64**.
- Symbol(s): RagTokenizer (20-35); is_chinese (38-39); is_number (42-43); is_alphabet (46-47); naive_qie (50-51).
- Input → output: Text → tokens/fine tokens/frequencies.
- Direct/transitive dependencies: infinity-sdk 0.7.3, datrie, hanziconv, NLTK. Service: No Infinity server. Database/index: SDK dictionaries.
- Current equivalent: current tokenizer.
- Decision: **WRAP** → `backend/ragflow_derived/upstream/runtime.py`.
- Modifications: Lazy Infinity SDK 0.7.3 tokenizer, fixed Elasticsearch behavior; remove global settings/import-time instance; structured missing native dependency error.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: injected tests; native install blocked.

### 28. Elasticsearch search/store boundary

- Upstream: [rag/utils/es_conn.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/utils/es_conn.py), range **101-654**.
- Symbol(s): _is_query_string_clause (63-64); _remove_query_string_must_clauses (67-72); _build_knn_filter_query (75-97); ESConnection (101-654).
- Input → output: Expressions/scope → real ES DSL/results.
- Direct/transitive dependencies: elasticsearch-dsl, elasticsearch, transport. Service: Loopback ES. Database/index: Pinned mapping and scoped vector field.
- Current equivalent: current pgvector/FTS.
- Decision: **WRAP** → `backend/ragflow_derived/storage.py`.
- Modifications: Use adapted actual Elasticsearch search DSL; implement explicit local client, immutable version markers, ready activation and mandatory platform scope guard instead of product singleton/connection lifecycle.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: actual DSL capture, source marker/guard tests.

### 29. Format/chunk dispatch interface

- Upstream: [rag/app/naive.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/app/naive.py), range **1069-1475**.
- Symbol(s): chunk (1069-1475).
- Input → output: Owned file bytes/type → structured exact text chunks.
- Direct/transitive dependencies: Upstream Markdown/HTML + merge; pypdf, python-docx. Service: None. Database/index: No source fetching.
- Current equivalent: current parser/chunking.
- Decision: **REIMPLEMENT** → `backend/ragflow_derived/parsing.py`.
- Modifications: Format dispatch and basic PDF/DOCX wrappers replace heavy DeepDoc layout/product dependencies. Markdown/HTML parsers and paragraph merge are actual ported upstream code, not reimplementations.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: PDF/DOCX/text/HTML generic fixtures.

### 30. Embedding model interface

- Upstream: [rag/llm/embedding_model.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/llm/embedding_model.py), range **148-221**.
- Symbol(s): Base (148-221).
- Input → output: Document/query text → vectors.
- Direct/transitive dependencies: Callable adapter, numpy, ported truncation. Service: Explicit operator model only. Database/index: Profile and dimension out-of-band.
- Current equivalent: existing embedding provider routing.
- Decision: **REIMPLEMENT** → `backend/ragflow_derived/models.py`.
- Modifications: Provider-neutral encode/encode_queries callback contracts; use ported embedding input truncation. No upstream provider SDK or credentials.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: mismatch/nonfinite/zero validation.

### 31. Reranker model interface

- Upstream: [rag/llm/rerank_model.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/llm/rerank_model.py), range **57-129**.
- Symbol(s): Base (57-129).
- Input → output: Query + texts → normalized scores.
- Direct/transitive dependencies: Callable adapter, numpy. Service: Explicit operator model only. Database/index: No store.
- Current equivalent: current selection/reviewer.
- Decision: **REIMPLEMENT** → `backend/ragflow_derived/models.py`.
- Modifications: Provider-neutral similarity callback normalized [0,1]; no provider implementation imported; ported Dealer performs blending.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: missing/failure/nonfinite/tie tests.

### 32. Ingestion/retrieval orchestration contract

- Upstream: [rag/svr/task_executor.py](https://github.com/infiniflow/ragflow/blob/a024bea0cd93f39e6652a42bf84dd20c55bc560b/rag/svr/task_executor.py), range **744-793;1443-1777**.
- Symbol(s): embedding (744-793); do_handle_task (1443-1777).
- Input → output: Owned source/model/config → indexed source and neutral evidence.
- Direct/transitive dependencies: Ported parser/embedding/search/context; scoped store. Service: ES; injected models. Database/index: Manifest + versioned chunks.
- Current equivalent: current worker and rag_service.
- Decision: **REIMPLEMENT** → `backend/ragflow_derived/engine.py`.
- Modifications: Synchronous local ingestion, versioned indexing, async Dealer retrieval and neutral evidence assembly replace upstream distributed executor. Calls actual ported parsers, EmbeddingUtils, Dealer and kb_prompt.
- License: Apache-2.0; retain attribution; changed notice for adapted code. Tests: full synthetic pipeline.

## Relevant components not copied

| Pinned upstream component | Decision / replacement / reason |
| --- | --- |
| deepdoc/parser/pdf_parser.py and vision/OCR/layout model pipeline | DEFER full DeepDoc; WRAP pypdf text extraction. No OCR/model assets or related binaries vendored. This is not layout/table-image parity. |
| deepdoc/parser/docx_parser.py RAGFlowDocxParser; naive.Docx | WRAP python-docx ordered paragraphs/tables; image/textbox enrichment deferred. |
| rag/nlp/__init__.py tree_merge/hierarchical_merge/naive_merge_docx; media-context helpers | OMIT from selected basic pipeline; paragraph merge retained. No document tree generation/parent-child expansion advertised. |
| rag/nlp/search.py methods after retrieval (SQL, tags, TOC/tree retrieval) | DEFER. Ordinary Dealer pipeline does not require product SQL/KG/TOC runtime. Native graph/multi-hop quality is unclaimed. |
| rag/prompts/generator.py full_question (256-289), keyword_extraction (226-238), cross_languages (292-318), multi_queries_gen (1009-1018) | DEFER optional model-backed retrieval transformations; no auxiliary provider calls. History only reaches existing generation. |
| rag/advanced_rag/agentic_rag.py RAGTools, retrieval harness tools | DEFER optional agentic mode, not imported under claim of standard retrieval. Requires model/tool budget and separate security validation. |
| rag/llm provider classes and LLMBundle product model registry | REIMPLEMENT small model contracts; KEEP platform provider/credential ownership. No provider catalog imported. |
| common/settings, api/db MySQL services, Redis task queues/cache, MinIO/object storage | KEEP OURS for business/authority/storage; REIMPLEMENT local execution and explicit index client. No global application settings imported into engine. |
| Infinity/OceanBase/GaussDB/SereneDB search connections | OMIT alternate stores; selected ES DSL preserves release search behavior more closely than a PostgreSQL rewrite. Retained dead settings branches are not supported backend promises. |
| RAGFlow account/frontend/admin/billing/workflow builder/marketplace/connectors/demos | OMIT product-only components. Existing platform remains authoritative. |

The new adapter's full-ID citations replace upstream short modulo IDs for collision safety. Upstream answer-citation insertion helpers remain in Dealer but are not used to post-process Gemini answers: the engine returns cited evidence, while generation stays ours. No claim that generated answer citation placement is validated without a live/model test.
