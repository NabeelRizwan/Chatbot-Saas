# Phase 4.1B implementation research ledger

Inspected official source on 2026-09-16, before schema/repository implementation.
No literal upstream code is copied. **Pattern adaptation: YES; literal code
reuse: NO** for every entry. Implementation is written against our Phase 4.1A
contracts, existing PostgreSQL/Alembic conventions and trusted tenant scope.

| Project / pinned source | License inspected | Implementation studied | Adaptation / rejected assumptions |
| --- | --- | --- | --- |
| [Docling Core](https://github.com/docling-project/docling-core/tree/a7ba70940ef39c64339c938b75791536c691958f): `docling_core/types/doc/items/node.py`, `common/reference.py`, `common/origin.py`, `document.py` | [MIT](https://github.com/docling-project/docling-core/blob/a7ba70940ef39c64339c938b75791536c691958f/LICENSE) | NodeItem self/parent/child references; RefItem/FineRef; document origin, provenance and serialization | Persist explicit source-pinned identity and provenance separately from text. Retain full SHA-256 and immutable source versions; do not adopt mutable positional references, truncated origin hashes, image loading or Docling dependency. |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/ddc676a3c60e819477a5eb31609a4ab296a246f7): `rag/app/qa.py`, `rag/app/naive.py`, `api/db/db_models.py` | [Apache-2.0](https://github.com/infiniflow/ragflow/blob/ddc676a3c60e819477a5eb31609a4ab296a246f7/LICENSE) | QA-pair chunk metadata; parser/table context configuration; Document content hash, parser identity, progress and lifecycle fields | Keep typed QA/table/provenance payloads and explicit processing versions/counts. Separate immutable source from processing state. Reject datastore replacement, parser execution, tokenization and application permission assumptions. |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/fd4a517ad6490f0c8464a13fdf133760b696434a): `llama-index-core/llama_index/core/schema.py`, `node_parser/relational/hierarchical.py`, `retrievers/auto_merging_retriever.py` | [MIT](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/LICENSE) | BaseNode/RelatedNodeInfo/NodeRelationship; explicit parent-child references; parent hydration during auto-merging | Persist independently addressable, version-pinned endpoints. Add mandatory composite tenant/version ownership rather than treating node_id as sufficient. Store tree parent once; reject reverse-edge duplication, auto-merging, score-based expansion and framework docstore. |
| [Haystack](https://github.com/deepset-ai/haystack/tree/0defdcff64950ca54f4dac0d21fe4eb30ed745d7): `haystack/dataclasses/document.py`, `components/preprocessors/hierarchical_document_splitter.py`, `components/retrievers/sentence_window_retriever.py` | [Apache-2.0](https://github.com/deepset-ai/haystack/blob/0defdcff64950ca54f4dac0d21fe4eb30ed745d7/LICENSE) | Detached hierarchy metadata; root/source/split identities; source-qualified ordered windows; serialization | Preserve source/version, processing revision and explicit reading order. Never merge parser metadata into trusted ownership. Reject runtime splitting/windows, hierarchy entirely in loose metadata and source_id alone as permission. |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/f4b2f659adf7b496df0e3a8e2ac0a703e405ba19): `backend/onyx/connectors/models.py`, `backend/onyx/db/models.py`, `backend/onyx/db/document.py` | [Root license](https://github.com/onyx-dot-app/onyx/blob/f4b2f659adf7b496df0e3a8e2ac0a703e405ba19/LICENSE): MIT Expat outside `ee`; enterprise directories have separate terms | Section/source/metadata separation; Document versus connector-credential ownership records; scoped existence/indexability checks | Separate factual structure from trusted scope and indexing lifecycle. Require caller-owned transactions and tenant-qualified lookups. Reject enterprise ACL copying, connector permission inheritance and implicit authorization from an edge. No `ee` code reused. |

## Relational mechanisms

Also inspected RAGFlow's `deepdoc/parser/pdf_parser.py` at the pinned revision:
layout/table position records and parser output assembly retain source locations
independently of later indexing. We preserve those concepts as typed provenance
and attributes; no DeepDoc parsing, OCR, VLM branch, tokenizer or execution code
is imported or copied.

None of these framework representations substitutes for our PostgreSQL ownership
constraints. Our repository's frozen `resource_schema_v1.py`, its composite tenant
keys and explicit migrations are the local implementation precedent.

- [SQLAlchemy composite adjacency](https://docs.sqlalchemy.org/en/20/orm/self_referential.html#composite-adjacency-lists): adapt the account-qualified parent-key pattern to full org/bot/document/version/revision identity. No recursive loader.
- [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html): composite FKs, unique keys, partial uniqueness for nullable source/crawl identity, and same-row checks. A parent-key FK also pins parent preorder/depth, so ordering cannot be invalidated by changing the parent later.
- [PostgreSQL constraint triggers](https://www.postgresql.org/docs/current/sql-createtrigger.html): deferred final-state pointer checks, plus mutation/lifecycle triggers. No cross-row CHECK functions or unbounded recursive tree scan.
- Row locks and compare-and-swap activation follow the application's document-lock convention, within the caller's transaction; no distributed lock service. Disposable-test isolation reuses the existing Phase 3.1 harness rather than inventing a database-selection fallback.

## Attribution and acceptance mapping

This is **pattern adaptation**, not a claim that these upstream projects already
implement our tenant/version schema or concurrency policy. No copied source blocks
require bundled third-party notices. No dependencies, models or licenses are installed.

Tests must preserve: Docling-style provenance round-trip; LlamaIndex-style explicit
relationships with stronger ownership/version FKs; Haystack-style source/split
separation; RAGFlow-style QA/table payload fidelity; Onyx-style content/access
separation. Database-native tests additionally prove parent ordering, immutability,
activation conflicts, rollback, idempotency and bounded query plans.

## Phase 4.1C addendum — deterministic Markdown/text adapter (2026-09-16)

Official implementation source was inspected before implementation. Current
upstream commit IDs were resolved through the official repositories. This extends
the ledger; it does not revise the prior storage acceptance or its pinned sources.

For **every row below: literal code copied/vendored = NO; pattern adapted = YES**.
The exception in terminology is markdown-it-py: its existing installed library is
executed as a dependency, not copied. Its current installed version, **4.2.0**, is
now explicitly declared/pinned in requirements; nothing was installed or upgraded.
No Docling, RAGFlow, LlamaIndex, Haystack or Onyx module is imported.

| Source project / repository / pinned commit | File, class or function inspected | License | What we used | What we rejected and why |
| --- | --- | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling/tree/e8c6092fe6ee995ce0719a71352b9f1fad5350cf) | `docling/backend/md_backend.py`: `MarkdownDocumentBackend._iterate_elements`, `_create_list_item`, `_create_heading_item`, `_flush_creation_stack`, `_starts_pipeless_table`, `_close_table`, `convert` | [MIT](https://github.com/docling-project/docling/blob/e8c6092fe6ee995ce0719a71352b9f1fad5350cf/LICENSE) | Typed list/container/item and heading boundaries; preserve inline links independently of body; require delimiter evidence for pipe tables; code is source data | No Marko/Docling dependency, image loading, underscore/dash shortening, rendered-text origin assumptions, or clipping extra table cells. Our malformed tables keep all text rather than silently losing cells. |
| [Docling Core](https://github.com/docling-project/docling-core/tree/a7ba70940ef39c64339c938b75791536c691958f) | `docling_core/types/doc/items/text.py`: `TextItem`, `TitleItem`, `SectionHeaderItem`, `ListItem`; `types/doc/document.py`: item creation, parent/provenance fields and `export_to_markdown` | [MIT](https://github.com/docling-project/docling-core/blob/a7ba70940ef39c64339c938b75791536c691958f/LICENSE) | Separate untreated source, structural role, parent references, source positions and display/export concerns | No export-as-original-source assumption, synthetic PDF coordinates, mutable source identities or renderer integration. Our frozen DTOs, byte provenance and tenant/version identity remain authoritative. |
| [RAGFlow / DeepDoc](https://github.com/infiniflow/ragflow/tree/2a610c732f3499a7583e9abfad6634febe00f4b9) | `deepdoc/parser/markdown_parser.py`: `MarkdownElementExtractor._line_start_offsets`, `_fenced_code_ranges`, `_markdown_table_ranges`, `_extract_list_block`, `_extract_text_block`, `extract_elements` | [Apache-2.0](https://github.com/infiniflow/ragflow/blob/2a610c732f3499a7583e9abfad6634febe00f4b9/LICENSE) | Cumulative cursor/line positions; protect fences/tables before section processing; retain heading/body and list grouping | No global text search to reconstruct repeated spans, delimiter chunk generation, HTML conversion or table detachment. Exact UTF-8 offsets are our own adapter layer. |
| RAGFlow, same commit | `rag/app/qa.py`: `mdQuestionLevel`, Markdown branch of `chunk`, row-to-question/answer assembly | Apache-2.0, same license | Explicit structural question/answer grouping and code-fence isolation | Upstream QA mode treats heading stacks as question context; our generic parser requires an actual question heading and associated body. Unmarked prose ending in `?` remains prose. No tokenizer/chunker/orchestration copied. |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/fd4a517ad6490f0c8464a13fdf133760b696434a) | `llama-index-core/llama_index/core/node_parser/file/markdown.py`: `MarkdownNodeParser.get_nodes_from_node`, `_build_node_from_split` | [MIT](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/LICENSE) | Heading-level stack pops on equal/higher levels; skipped levels need not equal stack depth; code headings stay inert; retain parent path/order | No flattening section text into TextNodes, implicit IDs, metadata-as-ownership, or header-text identity. Our path/order/hash distinguishes repeated equal headings. |
| [Haystack](https://github.com/deepset-ai/haystack/tree/0defdcff64950ca54f4dac0d21fe4eb30ed745d7) | `haystack/components/preprocessors/document_splitter.py`: `_concatenate_units`, `_create_docs_from_splits`; `hierarchical_document_splitter.py`: `build_hierarchy_from_doc` | [Apache-2.0](https://github.com/deepset-ai/haystack/blob/0defdcff64950ca54f4dac0d21fe4eb30ed745d7/LICENSE) | Incremental source offsets, ordered units and explicit parent links, separated from source identity | No overlap, sentence model download, splitting/chunk generation, arbitrary metadata merge or synthesized offset from repeated substring search. |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/f4b2f659adf7b496df0e3a8e2ac0a703e405ba19) | `backend/onyx/connectors/models.py`: `Section`, `TextSection`, `TabularSection`, `DocumentBase`; `backend/onyx/indexing/models.py`: `BaseChunk`, `DocAwareChunk` | [MIT Expat outside `ee`](https://github.com/onyx-dot-app/onyx/blob/f4b2f659adf7b496df0e3a8e2ac0a703e405ba19/LICENSE) | Connector section text/heading/link are distinct fields; source link offsets stay separate from indexed content and document ownership | No enterprise ACL reuse, source fetching/materialization, chunk enrichment, or inherited metadata authority. Cross-source targets must be supplied explicitly by the trusted caller. |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py/tree/a5950caef3434ed83045b43311aefcf7e0578aa3), installed release **4.2.0** | Installed `parser_block.py`, `rules_block/state_block.py`, `list.py`, `table.py`, `rules_inline/link.py`; reviewed actual installed code | [MIT](https://github.com/executablebooks/markdown-it-py/blob/a5950caef3434ed83045b43311aefcf7e0578aa3/LICENSE) | Reuse CommonMark block grammar, line maps, standard list nesting, heading/fence/quote boundaries and table recognition. Bounded token sink is an independent wrapper. | No HTML rendering, linkification, typographer, fetching or execution. Library's silent maxNesting tail omission is intercepted by typed token/depth bounds. Table row clipping/padding is rejected by checking raw cells. Unsafe links are retained by a separate cursor scanner instead of library link suppression. |

### Material normalization and association decisions

These are **independently implemented local policies**, informed by the above
patterns—not claims that upstream frameworks implement these exact rules:

| Mechanism | Pattern basis | Local invariant / intentional difference |
| --- | --- | --- |
| UTF-8 spans / repeated text | DeepDoc line cursors + Haystack incremental offsets | Byte-prefix array over immutable original text; line maps account for CRLF/lone CR without normalizing stored text. No global `find` for node provenance. Bounded delimiter search is used only inside the current source link/code span. |
| Heading hierarchy / title | LlamaIndex heading stack + Docling typed items | One physical section per heading; first top-level H1 is title; duplicate titles never merge. Body and explicit question/answer edges use same-section containment. |
| Lists | Docling item/group representation + CommonMark grammar | Complete syntax block counts only; three-or-more-entry comma enumeration requires a listing verb and explicit final conjunction; ordered alphabetic extension requires a contiguous indented sequence. No claim of globally exhaustive ingredients or inference from highlight cards. |
| Tables | Docling delimiter lookahead + markdown-it escaped pipes | Exact rows/cells, original headers and known explicit unit tokens; mismatched widths stay inert source. Never infer a table from unmarked one-column prose or pad/drop cells. |
| Links / reviews | Onyx section/link separation + Docling hyperlinks | Exact original href/anchor/fragment; credential/control/unsafe schemes cannot resolve. Review signature or explicit labeled review must bind exactly one link in that same structural block; nearby recommendations do not count. An exact-href, version-pinned server target registry is required for REFERS_TO. No fetch, canonicalization or ACL inference. |
| FAQ | RAGFlow QA grouping, deliberately narrower | Question heading with interrogative syntax plus directly associated answer blocks only. Ordinary prose and arbitrary headings are not QA. |
| Timeline | Docling group/order model + LlamaIndex boundaries | Repeated explicit time-label layout; separate stage heading/body/qualification, stop at unrelated section boundaries. No outcome or certainty inference. |
| Amounts / quantities | Source/typed-value separation in Docling + frozen local DTOs | Preserve original numeric strings and labels; no arithmetic. Roles only from directly bound labels/unique clause. Currency symbols do not imply ISO currency. Flattened adjacent amounts remain UNKNOWN, including Resveratrol. Frequency cannot cross arbitrary sentence/subject boundaries; water volume is not assigned dosing frequency. |
| Plain text | DeepDoc text/list boundary pattern | Lines/paragraphs and explicit lists only; no semantic heading, table, FAQ, review, price or timeline invention. Markdown mode must be explicitly selected by the caller. |
| Source quality | Frozen DTO separation of observations and disposition | Always unassessed/UNKNOWN + manual_review in this adapter; no word-based blocking, document-ID exception or quality detector. |
| Bounds / deterministic identity | Frozen Phase 4.1A contract + source/version separation across all projects | Source-byte/hash checks, capped nodes/depth/edges/tokens/targets/links; complete DTO or typed error. Caller owns identities; source metadata never configures parsing. Parser and dependency policies enter build fingerprint. |

No literal upstream source blocks were copied; dependency distribution retains
its own MIT notices. No framework/model installation was performed. The report
separates proven source-supported extraction from annotation-only GOLD semantics,
and source-level behavioral comparisons from any executable framework benchmark.

## Phase 4.1D source study — 2026-09-16

The following are implementation-source inspections, not blog summaries. No
literal upstream source was copied. Docling's public pinned converter and Core
serialization are executed; the other projects supply patterns only. Their
datastores, access control, orchestration, chunking and enrichment are not adopted.

| Source project / repository | File / class / function | Pin / license | Pattern studied / adapted? | Literal reuse? | What we keep / reject / why |
| --- | --- | --- | --- | --- | --- |
| [Docling](https://github.com/docling-project/docling/tree/014e8e357b24aa9d5113317fa454df8a70de9aeb) | `pyproject.toml`, `packages/docling-slim`, `document_converter.py`: `DocumentConverter`, `PdfFormatOption`, `WordFormatOption`, `initialize_pipeline`, `convert` | v2.127.0 / `014e8e357b24aa9d5113317fa454df8a70de9aeb`; MIT; Python >=3.10,<4 | Modular dependency selection + owned byte stream; YES | NO | Pin optional slim package and selected extras, not standard/all bundle; no public URL input, automatic format negotiation or plugin loading. |
| Docling, same pin | `pipeline/standard_pdf_pipeline.py`: `_init_models`, `_make_ocr_model`, `_build_document`; `datamodel/pipeline_options.py` | Same / MIT | Page stages, table/layout separation, timeout, feature gates; YES | NO | Local CPU layout + TableFormer; preserve text layer. Disable OCR, VLM, picture classification/description, chart/code/formula enrichment. Image-only/empty PDF explicitly rejected; not silently accepted as complete extraction. |
| Docling, same pin | `backend/msword_backend.py`: `convert`, `_get_or_create_list_group`, `_iter_paragraph_content`, `_get_hyperlink_target`, `_handle_tables`; `pipeline/simple_pipeline.py` | Same / MIT | Declarative DOCX tree, explicit numbering, merged cells, hyperlink items; YES | NO | Keep parser tree and source item refs; no fictitious DOCX PDF coordinates. Reject automatic first-row header assumption unless original OOXML explicitly marks it. No image/chart rendering subprocess or external fetch. |
| Docling, same pin | `models/stages/layout/layout_object_detection_model.py`; `models/inference_engines/common/hf_vision_base.py`; `models/inference_engines/vlm/_utils.py`: `resolve_model_artifacts_path`; `models/stages/table_structure/table_structure_model.py` | Same / MIT | Exact cache resolution / model download boundary; YES | NO | Require explicit local cache and SHA256 allowlist. Default download-on-first-use rejected. No OCR, VLM or other model artifacts provisioned. SafeTensors only. |
| [Docling Core](https://github.com/docling-project/docling-core/tree/a7ba70940ef39c64339c938b75791536c691958f) | `types/doc/document.py`: `DoclingDocument`, `iterate_items`, serialization; `items/text.py`: `TextItem`, `SectionHeaderItem`, `ListItem`; `items/group.py`: `ListGroup` | v2.96.1 / `a7ba70940ef39c64339c938b75791536c691958f`; MIT | Typed tree, stable refs, original vs sanitized text, list modes; YES | NO | Use original extracted text, explicit refs/children, order. Bound our own traversal instead of unbounded recursive iterator. Mixed numbered/bullet group becomes typed consecutive runs without deleting upstream group identity. |
| Docling Core, same pin | `items/table/table.py`, `items/table/table_data.py`: `TableItem`, `TableCell`, `RichTableCell`, `TableData`; `items/picture/picture.py`: `PictureItem`; `items/node.py`: `FloatingItem` | Same / MIT | Sparse merged cells, headers, captions/media refs; YES | NO | One node per actual cell, preserve spans and rich-cell children. Do not materialize computed padded grid, flatten table into Markdown or infer commercial roles/units. Media image bytes/remote paths do not escape the boundary. |
| Docling Core, same pin | `common/reference.py`: `ProvenanceItem`, `PageItem`; `base.py`: `BoundingBox`, `CoordOrigin` | Same / MIT | Page-local bbox origins + parser provenance; YES | NO | Preserve original TOPLEFT/BOTTOMLEFT origin and 72-point units. Convert t/b to numeric min/max without flipping Y or normalization. Retain item ref alongside real bbox; reject invalid coordinates, never invent PDF/DOCX UTF-8 offsets. |
| [RAGFlow / DeepDoc](https://github.com/infiniflow/ragflow/tree/98ebe5f66f2c2881ede11a2c1aad0b276f057f77) | `deepdoc/parser/pdf_parser.py`: `parse_into_bboxes`, page/table/figure positions; `docx_parser.py`: `RAGFlowDocxParser.__call__`, table serialization | `98ebe5f66f2c2881ede11a2c1aad0b276f057f77`; Apache-2.0 | Keep table/figure identity and page-local source metadata; YES | NO | Reject cumulative-page Y offsets, inferred header typing and table-to-prose flattening because frozen DTO needs page coordinates/cells. No DeepDoc installation. |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/fd4a517ad6490f0c8464a13fdf133760b696434a) | `llama-index-integrations/readers/llama-index-readers-file/llama_index/readers/file/docs/base.py`: `PDFReader.load_data`, `DocxReader.load_data` | `fd4a517ad6490f0c8464a13fdf133760b696434a`; MIT | Page/filename metadata separation from extracted text; YES | NO | Keep explicit page references; reject flattened docx2txt and arbitrary `extra_info` merge as our ownership source. No LlamaIndex dependency. |
| [Haystack](https://github.com/deepset-ai/haystack/tree/0defdcff64950ca54f4dac0d21fe4eb30ed745d7) | `haystack/components/converters/pypdf.py`: `_extract_links`, `_default_convert` | `0defdcff64950ca54f4dac0d21fe4eb30ed745d7`; Apache-2.0 (LICENSE inspected; API NOASSERTION) | Treat hyperlinks as data and distinguish 1-based page metadata; YES | NO | Preserve only links exposed by the pinned backend. Do not fetch, invent anchors, append URL prose, or silently catch and omit entire source blocks. No Haystack installation. |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/f4b2f659adf7b496df0e3a8e2ac0a703e405ba19) | `backend/onyx/file_processing/extract_file_text.py`: `_extract_pdf_text_pdfium`, `read_pdf_file` | `f4b2f659adf7b496df0e3a8e2ac0a703e405ba19`; MIT Expat outside `ee` (LICENSE inspected) | Own bytes once, isolate native parser, close page/document resources; YES | NO | Our subprocess has a hard parent deadline and dies on return/error. Reject empty-string fallback for encrypted/error sources, broad source metadata adoption, and framework-specific indexing. No Onyx/enterprise code copied. |

### Dependency and artifact separation

`requirements-structural-docling.txt` is optional and not included in application
requirements. Docling/Core/Parse/IBM-models are MIT. PyTorch/Torchvision include
BSD/Apache/MIT notices; Transformers Apache-2.0; OpenCV headless 4.13.0.92 Apache-2.0;
python-docx MIT, pypdf BSD, Pillow 12.3.0 MIT-CMU. Installed metadata/Windows wheel dependency
plan was inspected before installation; no alternate parser framework installed.
The initial TableFormer import revealed its optional `cv2` extra is required;
the declared `opencv-python-headless` extra was explicitly reviewed/pinned, not
replaced with OpenCV 5 (outside IBM-models' declared range).

Deliberate local artifacts, never checked into Git:

- Heron `docling-project/docling-layout-heron@8f39ad3c0b4c58e9c2d2c84a38465abf757272d8`, Apache-2.0: weights 171,658,996 bytes plus config/preprocessor.
- TableFormer accurate `docling-project/docling-models@fc0f2d45e2218ea24bce5045f58a389aed16dc23` (v2.3.0), CDLA-Permissive-2.0: weights 212,758,388 bytes plus config.
- Five exact files/checksums are the adapter allowlist. Downloaded once into ignored `.codex_structural_4_1d/models`; parsing only verifies/loads them. No general model downloader was run.

Our organization/bot/document/version/revision identity, authorization, staging
state and UNKNOWN/manual-review quality remain caller/frozen-DTO concerns. Docling
does not set ownership, activate knowledge, write sidecar rows, create retrieval
chunks or supply runtime instructions. No stored source text controls parser
configuration. DOCX/PDF semantics stay structural; no second business classifier.

Observed upstream boundaries retained as explicit adapter policy: the frozen
90-degree PDF retained text but reversed reading order, so nonzero page rotation
is refused rather than accepted as correct extraction. A mixed text/textless PDF
is also refused while OCR is unprovisioned. Native DOCX chart caches are not mapped
yet and are refused, not silently dropped. DOCX explicit header labels are bound
only after validating table count, dimensions and first-row source text against
the exported table sequence; upstream-flattened 1x1 layout tables cannot shift
header ownership. Any association mismatch fails visibly.

## Phase 4.1E chunking implementation study (2026-09-16)

Current upstream source, not summaries, was inspected before implementation.
All rows below are conceptual adaptations (literal code reused: NO). No framework
chunk model, datastore, retrieval, embedding or orchestration is adopted.

| Source / repository / pinned commit / license | File, class or function inspected | Pattern adapted (YES) | Rejected and why |
|---|---|---|---|
| [Docling Core](https://github.com/docling-project/docling-core/tree/a7ba70940ef39c64339c938b75791536c691958f), MIT | `transforms/chunker/hybrid_chunker.py`: `HybridChunker`, `_count_chunk_tokens`, `_split_by_doc_items`, `_split_using_plain_text`, `segment`, `_merge_chunks_with_matching_metadata` | Count contextualized text; structural items before sentence/character splitting; compatible peer merging | Dropping headings when their budget is exhausted, semchunk dependency and heading-only merge compatibility. Our full heading identities remain even when literal context cannot fit. |
| Same Docling Core revision/license | `hierarchical_chunker.py`: `HierarchicalChunker.chunk`, `TripletTableSerializer`; `base.py`: `BaseChunker.contextualize` | Ordered heading ancestry, source item membership, one visit per item, inherited context | DataFrame first-row/column header inference and flattened tables. Only extracted header flags/coordinates are authoritative. |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/bc9b29b6a0b57cccfa34a4f72e4bb15f3a77758d), Apache-2.0 | `rag/nlp/__init__.py`: `hierarchical_merge`, `tokenize_table`, `tokenize_chunks`, `_merge_paragraph_groups`, overlap helpers; `rag/app/naive.py`; `rag/app/qa.py` | Section ancestry, parser-specific atomic QA/table handling, metadata with every part, bounded row groups | Elasticsearch token fields, synthetic positions, percentage overlap, OVER_CAP merge and oversized-paragraph overflow. Hard cap applies to the complete output. |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/fd4a517ad6490f0c8464a13fdf133760b696434a), MIT | `llama-index-core/llama_index/core/node_parser/text/sentence.py`: `SentenceSplitter`; `sentence_window.py`: `SentenceWindowNodeParser`; `relational/hierarchical.py`: `HierarchicalNodeParser`, `_add_parent_child_relationship` | Metadata-aware remaining budget, structural/sentence-first fallback, explicit source/parent identities and separately identified overlap | Framework node UUIDs, expanding retrieval windows, AutoMerging and whitespace stripping that destroys exact source spans. |
| [Haystack](https://github.com/deepset-ai/haystack/tree/0defdcff64950ca54f4dac0d21fe4eb30ed745d7), Apache-2.0 | `haystack/components/preprocessors/document_splitter.py`: token/character/function splitting, `_create_docs_from_splits`, `_add_split_overlap_information`; `hierarchical_document_splitter.py`: `build_hierarchy_from_doc` | Source/page identity, exact offset bookkeeping, immutable caller metadata, overlap distinguished from another occurrence | Guessed offsets when transformed text cannot be found, tail merges beyond a hard budget, copied datastore documents and multiple redundant hierarchy levels. |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/f4b2f659adf7b496df0e3a8e2ac0a703e405ba19), MIT Expat outside `ee` | `backend/onyx/indexing/chunking/{document_chunker,text_section_chunker,section_chunker}.py`: section dispatch, accumulator, oversized section, `ChunkPayload`; `backend/onyx/indexing/models.py`: `BaseChunk`, `DocAwareChunk` | Section-local payload before document context, source-link offsets and continuation identity | Cross-section accumulation without semantic boundaries, cleaned text with lost bytes, generated blurbs/summaries, mini-chunk embeddings, datastore and enterprise code. |

License files/source headers were inspected; all these licenses permit adaptation,
but no literal upstream implementation is copied. Optional Docling remains separate.
The existing installed MIT-licensed `tiktoken` cl100k_base factory is executed with
an isolated globals dictionary and a local-only, checksum-verifying BPE loader.
This reuses the installed library's exact encoding recipe without copying it,
mutating its module, downloading an asset, or using the legacy word-count fallback.
Tokenizer distribution version, factory source hash and BPE digest are fingerprinted.

Our frozen `ChunkStructuralMapping` vocabulary remains unchanged: `body`, `heading`,
`header`, `qualifier`; the chunk-spec companion usage identifies `primary`,
`inherited` and `overlap`. Synthetic delimiters receive no source-byte claim.
Explicit structural attributes/edges are preserved, never reclassified by an LLM.

## Phase 4.1F — ingestion/lifecycle source study (2026-09-16)

Current upstream main commits were resolved before editing ingestion. Actual source
and license files were inspected. All entries: literal code reused: NO; pattern
adapted: YES. No upstream datastore, authorization, queue, or retrieval system is
adopted. Existing frozen adapters and structure-chunk-v1 remain authoritative.

| Project / pinned repository / license | Source / functions | What we used | What we rejected / why |
|---|---|---|---|
| [Docling](https://github.com/docling-project/docling/tree/77ab16d8a6510572d8c720d3df2ad1bc99c7fd92), MIT | `docling/document_converter.py`: `_convert`, `_get_pipeline`, `_process_document`, `_execute_pipeline`, `_unload_input_document` | Source-format policy dispatch, explicit conversion failures and backend cleanup, recipe identity separate from source identity | Shared in-worker model cache and network-capable input. Our existing byte-only short-lived child remains isolated; cancellation terminates only its owned child. |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/701b82aa1e6baf4e79fd253658cc2e045b1655eb), Apache-2.0 | `rag/svr/task_executor.py`: `collect`, `set_progress`, `insert_chunks`, `do_handle_task`, `handle_task` (including dry-run recording branch) | Durable stage outcomes, cancellation checkpoints, bounded batches, comparison telemetry distinct from serving publication | Redis orchestration, index writes, source-wide cancellation deletion, provider execution in dry-run, raw exception/text logging. Shadow must not delete legacy evidence or generate embeddings. |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/fd4a517ad6490f0c8464a13fdf133760b696434a), MIT | `llama-index-core/llama_index/core/ingestion/pipeline.py`: `get_transformation_hash`, `run_transformations`, `_handle_duplicates`, `_handle_upserts`, `_update_docstore`, `run` | Bind source and transform recipe; separate transformation from persistence; deterministic repeat identity | Global document-hash scan, delete-before-transform upserts, automatic vector-store writes and framework cache identity. Existing scoped repository handles immutable builds. |
| [Haystack](https://github.com/deepset-ai/haystack/tree/0defdcff64950ca54f4dac0d21fe4eb30ed745d7), Apache-2.0 | `haystack/components/writers/document_writer.py`: `DocumentWriter.run`, `run_async`, `close`, `close_async` | Explicit writer boundary, explicit duplicate policy, count outcomes and resource closure | Generic OVERWRITE/default store policy; a validated graph cannot silently be replaced. No framework registration or document store. |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/a8804f2b8869499bb6f4932195a06575974debfe), MIT Expat outside `ee` | `backend/onyx/indexing/indexing_pipeline.py`: `index_doc_batch_with_handler`, `index_doc_batch_prepare`, `_promote_new_staged_files`, `_delete_replaced_files` | Relational ownership before index work, publication transaction separate from post-commit side effects; per-document failure outcomes | Secondary serving index/LLM enrichment, connector credential assumptions and content hash skip that ignores our parser recipe. No enterprise code copied. |

Local adaptation: legacy promotion records a bounded shadow-pending manifest in
existing ingestion-job audit JSON; the observer parses outside promotion locks,
captures an immutable owned source, and writes graph + summary through the existing
structural repository. READY-job redelivery resumes only shadow work. Serving
Chunk rows, active pointers, catalog publication, cache generation and embeddings
are not part of the writer. Off mode is the default, including an empty allowlist.

## Phase 4.1G — active-index, hierarchy and packing source study (2026-09-16)

Current default-branch SHAs were resolved from official repository metadata and
the pinned source and root license files inspected. This is design research only.
For every row: **copied code: NO; adapted pattern: YES (proposal only)**. No new
dependency, upstream runtime integration or enterprise ACL implementation.

| Project / pinned source / license | Source functions studied | Keep in the proposed design | Reject / why |
|---|---|---|---|
| [RAGFlow](https://github.com/infiniflow/ragflow/blob/701b82aa1e6baf4e79fd253658cc2e045b1655eb/rag/svr/task_executor.py), Apache-2.0 | `build_chunks`, `insert_chunks`, `do_handle_task`: parser configuration, mother/child chunks, batch insertion, cancellation and recorded inserted IDs | Separate retained parent structure from searchable evidence; bounded batches and ownership-aware cleanup | External-store visibility and best-effort compensating deletes are not an atomic PostgreSQL representation switch. Parent `available_int=0` is an analogy, not our authorization rule. |
| [Onyx indexing](https://github.com/onyx-dot-app/onyx/blob/a8804f2b8869499bb6f4932195a06575974debfe/backend/onyx/indexing/indexing_pipeline.py), [index swap](https://github.com/onyx-dot-app/onyx/blob/a8804f2b8869499bb6f4932195a06575974debfe/backend/onyx/db/swap_index.py), [retention](https://github.com/onyx-dot-app/onyx/blob/a8804f2b8869499bb6f4932195a06575974debfe/backend/onyx/db/search_settings.py), MIT Expat outside `ee` | `index_doc_batch`, `_verify_indexing_completeness`, `_port_swap_ready`, `_perform_index_swap`, `delete_search_settings`, reclaim-state helpers | Validate all required indexing attempts before publication; immutable target identity; protect active/backfill references from cleanup | INSTANT/partial backfill switch, dual external index writes, connector/ACL assumptions and model changes. Our canary must never mix incomplete representations. |
| [LlamaIndex hierarchy](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py), [auto-merging](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py), MIT | `_add_parent_child_relationship`, `get_leaf_nodes`, recursive parser; `_get_parents_and_merge`, `_fill_in_nodes` | Store parents/relationships without requiring a vector for every node; explicit embedding selection | Parent substitution by retrieved-child ratio, score averaging and neighbor fill-in: different retrieval semantics, no proof of our scope/field completeness. Leaf helper itself does not enforce what an application embeds. |
| [Haystack hierarchy](https://github.com/deepset-ai/haystack/blob/0defdcff64950ca54f4dac0d21fe4eb30ed745d7/haystack/components/preprocessors/hierarchical_document_splitter.py), Apache-2.0 | `_add_meta_data`, `build_hierarchy_from_doc`, `run` | Detached metadata plus explicit parent/child/level identity; storage hierarchy separate from downstream embedding selection | Token-block hierarchy as semantic identity, automatic embedding of all returned levels. This component returns root and descendants; it does not choose embeddings for us. |
| [Docling HybridChunker](https://github.com/docling-project/docling-core/blob/a7ba70940ef39c64339c938b75791536c691958f/docling_core/transforms/chunker/hybrid_chunker.py), [hierarchy](https://github.com/docling-project/docling-core/blob/a7ba70940ef39c64339c938b75791536c691958f/docling_core/transforms/chunker/hierarchical_chunker.py), [contextualization](https://github.com/docling-project/docling-core/blob/a7ba70940ef39c64339c938b75791536c691958f/docling_core/transforms/chunker/base.py), MIT | `_merge_chunks_with_matching_metadata`, `chunk`, `HierarchicalChunker.chunk`, `BaseChunker.contextualize` | Inherited headings and bounded peer packing, with separately retained document items | Matching heading strings alone is insufficient: require immutable identity, subject/role/quality and relationship checks. Do not drop metadata/qualifiers to fit. No AutoMerging or new Docling integration. |

Local PostgreSQL patterns inspected: `StructuralRepository.activate_revision`
(document CAS, validated/current source, caller transaction), `ready_chunks`
(shared authorization/lifecycle filter), legacy upload/crawl promotion (staging,
quota-owner then source/job locking), catalog projector (bot lock, caller commit,
trigger-owned revision), and corpus fingerprint construction. None yet supplies
a complete structural serving publication or rollback transaction. The design
identifies missing contracts rather than claiming the existing helper activates
embeddings safely.

## Phase 4.1H — offline selection/packing implementation study (2026-09-16)

Current default-branch SHAs were resolved and actual source read **before v2
implementation**. Docling Core advanced since G; the other four pins remained
current. License/source files were inspected (unchanged pins reuse the inspected
local source). Every row: **literal code reused: NO; pattern adapted: YES**.
No dependency, framework datastore, runtime index, or retrieval integration added.

| Project / repository / upstream commit / license | File / class / function | Pattern studied and adapted | Rejected / why |
|---|---|---|---|
| [Docling Core](https://github.com/docling-project/docling-core/tree/1259eba96b8fefeadc4313f8c1af5c7304c28256), MIT | `docling_core/transforms/chunker/hybrid_chunker.py`: `HybridChunker._merge_chunks_with_matching_metadata`; `hierarchical_chunker.py`: `HierarchicalChunker.chunk`; `base.py`: `BaseChunker.contextualize` | Hierarchy retains item identity; headings become inherited context (`always_emit_headings=False` default), optional independent heading emission; metadata-aware token budget and compatible peers. Our adaptation separates immutable graph/v1 units from v2 selection, proves descendant source-byte witnesses, and budgets complete candidates. | Heading-string equality alone and automatic orphan/independent heading suppression do not prove our subject identity/discoverability. Our closed generic-label rule is stricter; no doc-item text rewriting. Chunkers do not themselves execute embeddings. |
| [RAGFlow](https://github.com/infiniflow/ragflow/blob/701b82aa1e6baf4e79fd253658cc2e045b1655eb/rag/svr/task_executor.py), Apache-2.0 | `insert_chunks`, mother/child insertion and `available_int=0` parent branch | Stored parent structure separate from searchable children. We retain all graph nodes, edges and original mappings while explicitly recording selected versus metadata-only units. | Text-derived mother IDs, Elasticsearch fields, external indexing and cleanup. Equal text is not equal source occurrence; our identity pins tenant/source/version/revision. |
| [LlamaIndex](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py), MIT | `HierarchicalNodeParser.from_defaults`, `_recursively_get_nodes_from_nodes`, `_add_parent_child_relationship`, `get_leaf_nodes`; `core/retrievers/auto_merging_retriever.py`: `_get_parents_and_merge` | Explicit parent/child links and metadata inheritance; all levels may remain stored without independently embedding every level. v2 keeps complete graph and total selection ledger. | Ratio-based parent substitution, neighbor retrieval and score merging: unrelated retrieval semantics. The leaf helper is explicit selection, not evidence that every caller indexes only leaves. |
| [Haystack](https://github.com/deepset-ai/haystack/blob/0defdcff64950ca54f4dac0d21fe4eb30ed745d7/haystack/components/preprocessors/hierarchical_document_splitter.py), Apache-2.0 | `HierarchicalDocumentSplitter._add_meta_data`, `build_hierarchy_from_doc` | Source-root/parent/child metadata, detached metadata copies, hierarchy separate from downstream selection. We preserve immutable ancestry rather than flattening it into text-only IDs. | Token-block identity, overlap-driven semantic equivalence and embedding all hierarchy levels. Splitter returns root and descendants; it does not choose our embedding policy. |
| [Onyx](https://github.com/onyx-dot-app/onyx/blob/a8804f2b8869499bb6f4932195a06575974debfe/backend/onyx/indexing/chunking/document_chunker.py), MIT Expat outside `ee` | `DocumentChunker.chunk`, `_collect_section_payloads`; sibling `text_section_chunker.py`: `TextChunker.chunk_section`, token accumulator/flush/oversize handling | Section payload separated from title/context, typed dispatch, token-aware accumulation, link-offset association. Our adaptation shares only byte-identical inherited heading prefixes with the exact same source mappings inside one packed candidate. | Cleaned/normalized text, cross-section accumulation without explicit subject proof, generated context, framework store and enterprise code. All logical mappings survive prefix sharing; qualifiers never participate in it. |

v2 peer identity is **only** one equal validated `DESCRIBES` target on the actual
source/ancestor path. A title, nearby heading, absent identity or equal UNKNOWN
label cannot establish it. All typed units, quality/relationship boundaries and
unproven cases remain selected. No upstream code was copied, so no new copied-code
notice is required; license provenance is recorded above.

## Phase 4.1I — explicit identity and heading-answerability study (2026-09-16)

Current official default-branch revisions and actual source/license files were
inspected before implementation. Docling Core advanced since H; other pins are
unchanged. Every row: **literal code reused: NO; pattern adapted: YES**. No new
dependency or upstream runtime code is imported. Evaluations deny network access.

| Project / repository / upstream commit / license | Actual file / class / function | What we keep / adapted rule | What we reject / why |
|---|---|---|---|
| [Docling Core](https://github.com/docling-project/docling-core/tree/cc39622c6a4bb2643a8631edd996d8874a8e6a47), MIT | `types/doc/items/node.py`: `NodeItem`, `DocItem`; `common/reference.py`: `RefItem`, `FineRef`, `ProvenanceItem`; `common/origin.py`: `DocumentOrigin`; `transforms/chunker/hierarchical_chunker.py`: `HierarchicalChunker.chunk`; `base.py`: `BaseChunker.contextualize` | Explicit parent/reference identity, located source provenance, heading context separate from independently selected content. I requires complete same-descendant heading/source witnesses and retains all immutable graph nodes. | Contextualized title text is not resource authority; default heading non-emission is not proof of non-answerability. Positional references and origin's truncated binary hash do not replace our full source/version/revision identity. |
| [RAGFlow](https://github.com/infiniflow/ragflow/tree/701b82aa1e6baf4e79fd253658cc2e045b1655eb), Apache-2.0 | `rag/svr/task_executor.py`: `build_chunks`, `insert_chunks`; `rag/nlp/__init__.py`: chunk metadata assembly | Carry explicit `doc_id`/`kb_id` and source positions; distinguish stored, non-searchable mother context (`available_int=0`) from child evidence. I retains source ownership independently of inferred relevance and preserves nonselected graph nodes. | Content-hashed mother identity and equal chunk strings cannot establish business subject or permission. No external-store, parser, indexing or authorization assumptions copied. |
| [LlamaIndex](https://github.com/run-llama/llama_index/tree/fd4a517ad6490f0c8464a13fdf133760b696434a), MIT | `llama-index-core/llama_index/core/schema.py`: `NodeRelationship`, `RelatedNodeInfo`, `BaseNode.source_node`, `parent_node`, `child_nodes`, `ref_doc_id`; `node_parser/relational/hierarchical.py`: `_add_parent_child_relationship`, `get_leaf_nodes` | Typed SOURCE/PARENT/CHILD references, independently retained hierarchy, source-node identity distinct from content. I propagation follows a bounded proven group's actual tree ancestry. | `ref_doc_id` identifies the source, not necessarily the subject of every paragraph; no framework docstore, auto-merging or title guessing. |
| [Haystack](https://github.com/deepset-ai/haystack/tree/0defdcff64950ca54f4dac0d21fe4eb30ed745d7), Apache-2.0 | `haystack/components/preprocessors/hierarchical_document_splitter.py`: `_add_meta_data`, `build_hierarchy_from_doc`; `document_splitter.py`: detached metadata, `source_id`, `split_id`, `split_idx_start` | Detached, auditable parent/child metadata. I immutable annotations carry source identity, resource version, group and evidence nodes without modifying the graph. | Split-local `source_id`/`__parent_id` is hierarchy, not business-subject authority. No flattening or copying parent metadata across an unresolved nested resource boundary. |
| [Onyx](https://github.com/onyx-dot-app/onyx/tree/a8804f2b8869499bb6f4932195a06575974debfe), MIT Expat outside `ee` | `backend/onyx/connectors/models.py`: `DocumentBase`, `Document.from_base`, `Section`, `HierarchyNode`; `backend/onyx/indexing/models.py`: `DocAwareChunk`, source-link offsets | Distinguish connector ID and raw hierarchy IDs from semantic/display identifier and title; retain section links and source-document association. I resolves exact registered links only inside explicit card/review boundaries, with authorized pinned targets. | Semantic-identifier-derived fallback IDs, arbitrary URL fetches, title matching, connector/ACL trust and enterprise code. A nearby link is a reference, not a subject assignment. |

Local audit: `resource_catalog.projection`, `resource_schema_v1.py` and the frozen
catalog model pin document/version/crawl mappings and filter through
`HardKnowledgeScope`; they are not permission grants from uploaded text.
`coverage_manifest_service.py` derives some type/parent relationships from titles
and URL paths: these are NOT adopted as subject proofs. `normalize_crawl_url`
normalizes tracking/fragment/host syntax for crawl identity: I instead compares
safe, complete canonical URLs exactly, without URL normalization or network.

The saved production export has no resource-catalog rows. The existing frozen
development projection contains 23 `resource_type=document` records and 23 primary
document links. I verifies their explicit source-to-development mapping and
version/crawl/source fingerprint. They prove source-document identity only, not
single-subject page inventory. No catalog rows, aliases or live mappings change.

The additional exact source-version check withholds two catalog descriptors:
saved documents 13/14 are version 2 but H's frozen synthetic replay labels them
version 1. Keep all original graphs, log the incompatibility, and do not claim
those mappings as subject authority. This is an I-only evidence refusal, not a
change to H, source data or any live resource registry.

I rules written locally: single-resource root identity requires a separate
explicit frozen single-resource assertion AND complete inventory; contradictory
known blocks invalidate it. Generic typed card links and C's existing
source-labeled review links may identify only their bounded group. Validated
`DESCRIBES`/typed `REFERS_TO` must target an exact registered anchor. CONTAINS is
structure only. Ambiguous targets stay MULTI_SUBJECT; unresolved children block
inheritance; partial multi-node candidates cannot pack. These are stricter local
adaptations, not claims that upstream frameworks implement this policy.

Heading taxonomy is a small reviewed closed vocabulary plus typed/source
features, not NLP or a model classifier. The existing pinned CommonMark grammar
isolates visible heading text from href query punctuation and image-filename
digits, without rendering, fetching or rewriting source bytes. Marked-up labels
cannot become generic metadata-only proposals. Generic labels additionally require
all exact heading/context mappings in ONE retained descendant, no typed payload
or semantic identity edge. Facts/questions/numbers/warnings/qualifications and
unproven labels remain independently selected. New labels are I proposals only;
H's frozen selection policy is not expanded. No license notice is needed for
copied code because no code was copied.

## Phase 4.1J — resource boundaries and exact reference targets (2026-09-16)

Current GitHub HEAD source was checked before J design. RAGFlow and Onyx moved
since I; their files were downloaded at the new immutable commits. The other
three HEADs still match I's downloaded source; those actual files were reread,
plus Docling's current TextItem hyperlink implementation. Research downloads
remain ignored. No upstream code executed and no new dependency installed.

| Project / repository | Actual file/class/function | Current commit | License | Pattern studied / keep / reject / why | Copied code | Adapted pattern |
| --- | --- | --- | --- | --- | --- | --- |
| [RAGFlow](https://github.com/infiniflow/ragflow) | `rag/svr/task_executor.py` chunk construction; `rag/nlp/__init__.py` Node.build_tree/_dfs | `7bc159d64e565d7fa93cd56b866772dad66edf31` | Apache-2.0 | Keep explicit doc/kb ownership and source-position hierarchy separate from text subject. Reject document-ID or accumulated title-path propagation as paragraph identity; merge/depth hierarchy is not a resource assertion. | NO | YES, distinction only |
| [Onyx](https://github.com/onyx-dot-app/onyx) | `backend/onyx/connectors/models.py` Section/DocumentBase; `backend/onyx/indexing/models.py` BaseChunk/DocAwareChunk | `4ea423849cb0dc7e0df69096fbc650572bc08579` | MIT for inspected non-EE files | Keep connector ID, section.link and source_links offsets. semantic_identifier is a UI document identifier; parent hierarchy is source organization, not an assertion that every section describes one entity. Reject first-section link as blanket body subject. | NO | YES |
| [LlamaIndex](https://github.com/run-llama/llama_index) | `llama-index-core/llama_index/core/schema.py` source_node/ref_doc_id/IndexNode and relationships | `fd4a517ad6490f0c8464a13fdf133760b696434a` | MIT | Keep typed source/parent/child references and explicit reference objects. ref_doc_id follows SOURCE; IndexNode can point to arbitrary objects. Neither proves semantic subject or permits invoking referenced objects in J. | NO | YES |
| [Haystack](https://github.com/deepset-ai/haystack) | `haystack/components/preprocessors/hierarchical_document_splitter.py` build_hierarchy_from_doc; document_splitter metadata | `0defdcff64950ca54f4dac0d21fe4eb30ed745d7` | Apache-2.0 | Keep explicit parent/children/source/split IDs and copied metadata isolation. Reject source_id/parent_id as entity identity; recursive split boundaries are not semantic ownership. | NO | YES |
| [Docling Core](https://github.com/docling-project/docling-core) | `docling_core/types/doc/items/node.py` NodeItem; `common/reference.py` RefItem/FineRef/ProvenanceItem; `items/text.py` TextItem.hyperlink | `cc39622c6a4bb2643a8631edd996d8874a8e6a47` | MIT | Keep exact item refs, parent/children, original text/provenance and explicit hyperlink values. Internal JSON pointers resolve exact objects; hyperlinks alone do not verify external fragments or the subject of neighboring body text. Reject fetching and heading-slug guessing. | NO | YES |

Local source inspected: resource_catalog projection, resource_models,
database/resource_schema_v1, coverage_manifest_service, normalize_crawl_url,
structural_document, structural_text_adapter/LinkTarget, structural_text_rules,
Website/WebsiteCrawl/Document, and frozen source-to-development mappings.
Document-primary mappings are lineage only. The crawler URL normalizer strips
fragments; it is deliberately NOT used for J identity. C's explicit review
signature supplies a reference, but the group can contain trailing neighboring
images/navigation. J caps the member interval at the signature's descendants.
Generic cards/linked sections require independently frozen source boundary
assertions; linked headings are inventory candidates only.

J's exact source/version/hash/crawl/revision pins, closed evidence vocabulary,
root-inventory refusal, explicit anchor declaration validation and separate
manual-study namespace are local study adaptations. No business ontology,
runtime catalog mutation, authorization delegation or source acquisition was
copied or introduced. No copied-code license notice is required.

## Phase 4.1K — source capture and three-layer retrieval design (2026-09-16)

Official GitHub default-branch HEADs were resolved again before design. Actual
implementation files and LICENSE files were fetched at these immutable pins and
read; no upstream package, browser, model or code was executed. Haystack and
Onyx advanced since J. The additional Docling repository is distinct from Core.
Research copies and their SHA-256 inventory are ignored local artifacts under
`.codex_structural_4_1k/research`. **Every adaptation below is a design decision,
not an implementation.** No external framework datastore, queue, ACL, tenant
model, business ontology or authorization rule is adopted.

| Project / pin / license | Source file / function (actual implementation) | Pattern studied; what we keep | What we reject; why | Literal code reused? | Pattern adapted? |
| --- | --- | --- | --- | --- | --- |
| Docling Core `cc39622c6a4bb2643a8631edd996d8874a8e6a47`, MIT | [HierarchicalChunker.chunk](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/hierarchical_chunker.py), [BaseChunker.contextualize](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/base.py) | Stored document items, heading ancestry and embedding text are distinct; headings are contextual by default. Keep item references and budget inherited context separately. | Do not equate a heading string with resource identity, or suppress independently answerable/orphan headings without coverage. | NO | YES, design only |
| Docling Core, same pin/license | [HybridChunker](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/hybrid_chunker.py): `_count_chunk_tokens`, `_split_by_doc_items`, `_split_using_plain_text`, `_merge_chunks_with_matching_metadata`; [HuggingFaceTokenizer](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/tokenizer/huggingface.py) | Count contextualized text; bounded peer accumulation; retain doc-item associations. Limit comes from tokenizer; default tokenizer is MiniLM, not a universal 512-token rule. | Reject dropping headings/captions on overflow, merging solely on heading equality and automatic model downloads. K proposes independent bounded routing entries, not relaxed evidence merging. | NO | YES, design only |
| Docling `d4fa979af44a878700f8576eaba7e27dd9330005`, MIT | [HTMLDocumentBackend](https://github.com/docling-project/docling/blob/d4fa979af44a878700f8576eaba7e27dd9330005/docling/backend/html_backend.py): `_get_html_id`, `_use_hyperlink`, HTML conversion | Literal HTML IDs and owner-local link handling are useful source signals. Preserve declarations before lossy normalization, with provenance. | Do not adopt rendering/browser paths, arbitrary hyperlink schemes or script removal as a complete privacy gate. Generated internal element IDs are not declared fragment anchors. Removing scripts before capture also loses JSON-LD. | NO | YES, design only |
| LlamaIndex `fd4a517ad6490f0c8464a13fdf133760b696434a`, MIT | [HierarchicalNodeParser](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py): `from_defaults`, `_recursively_get_nodes_from_nodes`, `_add_parent_child_relationship`, `get_leaf_nodes`; [AutoMergingRetriever](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py): `_get_parents_and_merge`, `_fill_in_nodes` | Hierarchy storage, vector selection and returned context can differ. Defaults form 2048/512/128 levels; explicit leaf selection is separate. Keep explicit membership, not vectors for every level. | Reject automatic parent substitution above a 0.5 child ratio, averaged scores and unscoped docstore expansion. A parent hit is not complete factual evidence. No AutoMerging integration. | NO | YES, design only |
| Haystack `95458a7dc7c59a4d0a46567b674b6a772062ffe3`, Apache-2.0 | [HierarchicalDocumentSplitter](https://github.com/deepset-ai/haystack/blob/95458a7dc7c59a4d0a46567b674b6a772062ffe3/haystack/components/preprocessors/hierarchical_document_splitter.py): `_add_meta_data`, `build_hierarchy_from_doc`; [DocumentSplitter](https://github.com/deepset-ai/haystack/blob/95458a7dc7c59a4d0a46567b674b6a772062ffe3/haystack/components/preprocessors/document_splitter.py) | Root/intermediate/leaf hierarchy with detached metadata; source/split IDs and offsets. Default ordinary split length is 200 units (default words), not 200 embedding tokens. | Reject treating overlapping levels as distinct facts or embedding every returned node. Source IDs alone are not tenant/version authorization. | NO | YES, design only |
| Haystack, same pin/license | [SentenceWindowRetriever](https://github.com/deepset-ai/haystack/blob/95458a7dc7c59a4d0a46567b674b6a772062ffe3/haystack/components/retrievers/sentence_window_retriever.py): `_retrieve_context_for_document`, `_build_filter_conditions`, `merge_documents_text` | Fetch context after hits, constrained by source IDs and split interval; configurable default window 3 each side. Keep bounded, source-ordered expansion and overlap awareness. | Reject copying default source-only filters, unconditional neighbor text and concatenation when offsets are absent. Our expansion rechecks full HardKnowledgeScope and exact provenance. | NO | YES, design only |
| RAGFlow `7bc159d64e565d7fa93cd56b866772dad66edf31`, Apache-2.0 | [rag/app/naive.py](https://github.com/infiniflow/ragflow/blob/7bc159d64e565d7fa93cd56b866772dad66edf31/rag/app/naive.py): `chunk`; [rag/nlp/__init__.py](https://github.com/infiniflow/ragflow/blob/7bc159d64e565d7fa93cd56b866772dad66edf31/rag/nlp/__init__.py): `tokenize_chunks`, `split_with_pattern`, `naive_merge`; [task_executor.py](https://github.com/infiniflow/ragflow/blob/7bc159d64e565d7fa93cd56b866772dad66edf31/rag/svr/task_executor.py): `insert_chunks` | Parent content and searchable child tokens are separate; title/keyword fields remain available. Keep explicit membership, source positions and independent lexical discovery. | Reject text-hashed mother IDs across source occurrences, configurable regex delimiters as semantic boundaries and soft over-cap splitting. Top-level absent-config default 512 differs from several fallback 128 paths; neither is a universal recommendation. | NO | YES, design only |
| RAGFlow, same pin/license | [Dealer.search/get_filters/retrieval_by_children](https://github.com/infiniflow/ragflow/blob/7bc159d64e565d7fa93cd56b866772dad66edf31/rag/nlp/search.py) | Keyword+dense channels, explicit dataset/document filters and child-to-parent lookup; missing parents retain children. Keep exact lexical reach and missing-parent fallback. | Reject weighted raw-score assumptions, averaged parent scores and parent substitution. Tenant index/kb/doc filters do not establish our immutable source-version/profile rules; do not import their ACL model. | NO | YES, design only |
| Onyx `c564d334dd2635471947e5d3a5a1eca3f2d808af`, MIT Expat for inspected non-EE files | [connectors/models.py](https://github.com/onyx-dot-app/onyx/blob/c564d334dd2635471947e5d3a5a1eca3f2d808af/backend/onyx/connectors/models.py): `Document`, `Section`, `IndexingDocument.processed_sections`; [indexing/models.py](https://github.com/onyx-dot-app/onyx/blob/c564d334dd2635471947e5d3a5a1eca3f2d808af/backend/onyx/indexing/models.py): `BaseChunk`, `DocAwareChunk`, `IndexChunk` | Connector source, processed sections, search text and embeddings are separate contracts. Keep source associations/link offsets and independently versioned derived representations. | Reject semantic display identifiers as ownership, arbitrary source metadata, first-section link as universal citation, generated summaries as exact evidence and enterprise ACL assumptions. | NO | YES, design only |
| Onyx, same pin/license | [DocumentChunker](https://github.com/onyx-dot-app/onyx/blob/c564d334dd2635471947e5d3a5a1eca3f2d808af/backend/onyx/indexing/chunking/document_chunker.py): `chunk`, `_collect_section_payloads`; [TextChunker](https://github.com/onyx-dot-app/onyx/blob/c564d334dd2635471947e5d3a5a1eca3f2d808af/backend/onyx/indexing/chunking/text_section_chunker.py): `chunk_section`, `_handle_oversized_section`; [Chunker](https://github.com/onyx-dot-app/onyx/blob/c564d334dd2635471947e5d3a5a1eca3f2d808af/backend/onyx/indexing/chunker.py) | Content budgets subtract title/metadata/context; typed dispatch and source-order accumulation produce search payloads with link offsets. | Reject cross-boundary accumulation without our provenance gates, text cleaning as an exact byte mapping, and silently dropping context to fit. No embedding-context/model default is adopted. | NO | YES, design only |

Local compatibility inspected: `HardKnowledgeScope.identity/intersect`,
`knowledge_scope.ready_chunks`, existing rank-only `weighted_rrf`, frozen
`StructuralChunkSpec`/`SerializationBatch`, J source-native reconstruction and G's
publication requirements. K does not alter them. Future entry/atom identity,
serving-generation publication and parent/child authorization are missing
integration contracts, not capabilities claimed to exist today.

No literal implementation copied; no additional copied-code notice required.
See `PHASE_4_1K_GENERAL_RAG_ARCHITECTURE_DESIGN.md` for the independent capture and
representation decisions, arithmetic limitations and exact next offline slice.

## Phase 4.1L — executable offline retrieval-entry adaptations (2026-09-17)

Default-branch pins were rechecked before implementation. The K-pinned code
below was reopened at the same pins; Onyx advanced and its new pinned files and
license were read. No framework runtime was executed or added as a dependency.
Research network access ended before offline tests/evaluation. Every row below:
**literal code reused: NO; pattern adapted: YES** (independent local code).

| Project / current inspected pin / license | Exact implementation | Executable pattern kept in L | Rejected behavior and reason |
| --- | --- | --- | --- |
| Docling Core `cc39622c6a4bb2643a8631edd996d8874a8e6a47`, MIT | `HierarchicalChunker.chunk`, `BaseChunker.contextualize`, `HybridChunker._count_chunk_tokens`, `_merge_chunks_with_matching_metadata`, `_split_by_doc_items`, `_split_using_plain_text`; immutable source links in K table above | Structure-first units, heading-as-context, bounded adjacent accumulation, complete contextual token counting. Exact inherited headings are deduplicated by node/range identity, not text. | No metadata-only merge authorization, context/caption dropping, token-estimate-only cap, model download or semantic evidence merging. Existing exact typed bundles and header/qualifier mappings remain authoritative. |
| Docling `d4fa979af44a878700f8576eaba7e27dd9330005`, MIT | `HTMLDocumentBackend._get_html_id`, `_use_hyperlink` (K source pin) | Retain explicit source/provenance references as data; source structure is separate from search text. | No HTML acquisition, DOM sidecar implementation or generated anchor identity in L. Those belong to a separate capture slice. |
| LlamaIndex `fd4a517ad6490f0c8464a13fdf133760b696434a`, MIT | `HierarchicalNodeParser._recursively_get_nodes_from_nodes`, `_add_parent_child_relationship`, `get_leaf_nodes`; `AutoMergingRetriever._get_parents_and_merge`, `_fill_in_nodes` (K source links) | Distinct graph, routing entries and exact evidence; scoped explicit parent/child membership and immutable reverse lookup. | No AutoMerging retrieval, 0.5 substitution threshold, average-score parent replacement, unscoped docstore or vectors at every hierarchy level. A routing container is not final evidence. |
| Haystack `95458a7dc7c59a4d0a46567b674b6a772062ffe3`, Apache-2.0 | `HierarchicalDocumentSplitter._add_meta_data`, `build_hierarchy_from_doc`; `DocumentSplitter`; `SentenceWindowRetriever._build_filter_conditions`, `_retrieve_context_for_document`, `merge_documents_text` (K source links) | Detached immutable source/split identity and ordered bounded memberships; exact source ranges are retained for future neighboring-context selection. | No source-only authorization, runtime window expansion or offset-free concatenation. L accepts separately supplied tenant/bot/version/revision/crawl scope. |
| RAGFlow `7bc159d64e565d7fa93cd56b866772dad66edf31`, Apache-2.0 | `rag/app/naive.py:chunk`; `rag/nlp/__init__.py:tokenize_chunks,naive_merge`; `rag/svr/task_executor.py:insert_chunks`; `rag/nlp/search.py:Dealer.retrieval_by_children,search,get_filters` (K source links) | Search container versus independently addressable children; lexical eligibility and child→container mappings survive reduced dense-entry counts. | No global text-hashed parent identity, arbitrary regex chunk boundaries, score comparison, parent substitution or datastore writes. All local IDs include trusted source scope and recipe. |
| Onyx `a997e9a1d8542e98ea58104b1a9e95a7663978d1`, MIT Expat for inspected non-EE files | [connectors/models.py](https://github.com/onyx-dot-app/onyx/blob/a997e9a1d8542e98ea58104b1a9e95a7663978d1/backend/onyx/connectors/models.py): `Document`, `Section`, `IndexingDocument.processed_sections`; [indexing/models.py](https://github.com/onyx-dot-app/onyx/blob/a997e9a1d8542e98ea58104b1a9e95a7663978d1/backend/onyx/indexing/models.py): `BaseChunk`, `DocAwareChunk`, `IndexChunk` | Separate source, processed representation, search text and future embedding identity; exact atom references replace assumptions that all text in a search container is one fact. | No display-title ownership, free-form connector metadata as authority or generated summaries as evidence. No enterprise code adopted. |
| Onyx, same pin/license | [DocumentChunker.chunk/_collect_section_payloads](https://github.com/onyx-dot-app/onyx/blob/a997e9a1d8542e98ea58104b1a9e95a7663978d1/backend/onyx/indexing/chunking/document_chunker.py), [TextChunker.chunk_section/_handle_oversized_section](https://github.com/onyx-dot-app/onyx/blob/a997e9a1d8542e98ea58104b1a9e95a7663978d1/backend/onyx/indexing/chunking/text_section_chunker.py), [Chunker](https://github.com/onyx-dot-app/onyx/blob/a997e9a1d8542e98ea58104b1a9e95a7663978d1/backend/onyx/indexing/chunker.py) | Source-order section accumulation and budget including contextual prefix/suffix. L separately caps all inherited context and verifies complete exact byte maps after grouping. | No cleaned-text alignment, cross-section accumulation, silent qualifier deletion or provider-specific token budget. |

Implementation is confined to the new offline representation module, evaluator,
fixtures and tests. No current query/runtime/DB/ingestion behavior changes.
No literal source copied; no additional copied-code notice required. Docling
comparison is source-pattern comparison, not execution of HybridChunker or a
claim of matching its chunk counts.

## Phase 4.1M — heading allocation / hierarchy recheck (2026-09-17)

Actual official default-branch HEADs were resolved and the functions below were
reread before v2 implementation. LICENSE files were fetched at the same pins.
Research-only network use ended before offline evaluation. No framework was
installed or executed. **Literal code reused: NO. Pattern adapted: YES.**

| Repository / pin / license | Exact current implementation | Pattern adapted / rejected |
| --- | --- | --- |
| Docling Core `cc39622c6a4bb2643a8631edd996d8874a8e6a47`, MIT | [HierarchicalChunker.chunk](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/hierarchical_chunker.py), lines 192–297; [BaseChunker.contextualize](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/base.py), lines 82–106 | Headings update hierarchy, then accompany child chunks. With `always_emit_headings`, un-emitted leaf headings get a metadata-bearing empty-body unit at scope/end boundaries. Adapt explicit coverage plus orphan retention. Reject heading-emitted flags alone as proof of exact bytes, lexical identity or tenant/version authority. |
| Docling `1ceca3073e499dcc9da2dc802ac1f18bce672978`, MIT | [HTMLDocumentBackend._handle_heading](https://github.com/docling-project/docling/blob/1ceca3073e499dcc9da2dc802ac1f18bce672978/docling/backend/html_backend.py), lines 2501–2572 | Heading levels update parent groups with source provenance; this is source structure, not a decision to embed every heading. Keep the distinction. No HTML capture/normalization change or generated structural identity adopted. |
| LlamaIndex `fd4a517ad6490f0c8464a13fdf133760b696434a`, MIT | [HierarchicalNodeParser._recursively_get_nodes_from_nodes; get_leaf_nodes](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/node_parser/relational/hierarchical.py), lines 25–31, 160–205 | Stores hierarchy separately; leaf selection is explicit, not automatic indexing of every ancestor. Adapt separation of stored evidence and search allocation. Reject blanket leaf-only indexing: an orphan or unrepresented heading still needs access. |
| Haystack `ef9c9bba27dc40dd6d7854040c72283cbed326ec`, Apache-2.0 | [HierarchicalDocumentSplitter._add_meta_data; build_hierarchy_from_doc](https://github.com/deepset-ai/haystack/blob/ef9c9bba27dc40dd6d7854040c72283cbed326ec/haystack/components/preprocessors/hierarchical_document_splitter.py), lines 94–134 | A split yielding one child keeps the current node instead of manufacturing another hierarchy level. Adapt avoiding redundant search representations, not deletion of source evidence. This splitter is not an exact-heading coverage oracle and is not copied as one. |
| RAGFlow `03ca271f73de507e1dff531ec72c8ad8f05d4a4c`, Apache-2.0 | [tokenize_chunks; naive_merge](https://github.com/infiniflow/ragflow/blob/03ca271f73de507e1dff531ec72c8ad8f05d4a4c/rag/nlp/__init__.py), lines 458–483, 1450–1510 | Optional mother payload versus child lexical records distinguishes context from search units. Adapt independent lexical identity. Reject delimiter-driven splitting, short-text position loss and model truncation as evidence coverage guarantees. No FTS/runtime change. |
| Onyx `5fe6573c3c155e1a75b51de32d4988ee6c82164e`, MIT Expat for these non-EE files | [DocumentChunker.chunk/_collect_section_payloads](https://github.com/onyx-dot-app/onyx/blob/5fe6573c3c155e1a75b51de32d4988ee6c82164e/backend/onyx/indexing/chunking/document_chunker.py), lines 50–122; [TextChunker.chunk_section](https://github.com/onyx-dot-app/onyx/blob/5fe6573c3c155e1a75b51de32d4988ee6c82164e/backend/onyx/indexing/chunking/text_section_chunker.py), lines 36–80 | Title prefix is carried into doc-aware payloads; title-only documents can retain an empty payload; section text accumulates within its budget. Adapt context versus standalone fallback. Reject cleaned-text equality, title strings or section skipping as substitutes for exact mapped identity and scope. |

Local adaptation is stricter than these patterns: one admitted, complete,
same-scope descendant entry with original inherited mappings and compatible
quality/resource/barrier ownership must witness all required heading bytes and
companions. Lexical atom and graph remain independent. Numbers, question marks,
colons and words such as “Section” do not authorize dense suppression/promotion.
Pure heading atoms are revised; typed FAQ/warning units retain their existing
semantic identity. Frozen L packing/validator code is reused unchanged; v2 has
an independent implementation/recipe identity. No copied-code notice required.

## Phase 4.1N — hybrid retrieval / hierarchy / isolated index study (2026-09-17)

Design only. Resolved the official default-branch commit again, then read actual
source and LICENSE at each pin. This is not a repeat of the M heading study.
No upstream package installed, source executed, or code copied. The following
patterns inform the proposed internal canary, not today's serving path.

| Project / pin / license | Source file / function | Pattern | Copied code? | Adapted? | Keep / reject / why |
| --- | --- | --- | --- | --- | --- |
| RAGFlow `1ff3d961119e52effa7b60916584af02785a8a6f`; [Apache-2.0](https://github.com/infiniflow/ragflow/blob/1ff3d961119e52effa7b60916584af02785a8a6f/LICENSE) | [rag/nlp/search.py](https://github.com/infiniflow/ragflow/blob/1ff3d961119e52effa7b60916584af02785a8a6f/rag/nlp/search.py): `build_fusion_expr` 37–44, `Dealer.search` 243–365, `retrieval_by_children` 1085–1139 | Filtered hybrid recall; separate candidate/result limits; child-to-parent materialization with missing-parent fallback | NO | YES, design | Keep explicit filtering, bounded recall and traceable child/parent linkage. Reject weighted raw-score fusion, empty-result scope relaxation and replacing children with parent content/average scores: our one-based rank-only RRF, exact child witnesses and immutable scope remain authoritative. |
| LlamaIndex `fd4a517ad6490f0c8464a13fdf133760b696434a`; [MIT](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/LICENSE) | [fusion_retriever.py](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/retrievers/fusion_retriever.py): `QueryFusionRetriever._reciprocal_rerank_fusion` 113–148; [auto_merging_retriever.py](https://github.com/run-llama/llama_index/blob/fd4a517ad6490f0c8464a13fdf133760b696434a/llama-index-core/llama_index/core/retrievers/auto_merging_retriever.py): `_get_parents_and_merge` 56–118 | Rank fusion and parent lookup are separate operations | NO | YES, design | Keep separation of recall, normalized identity and materialization. Reject content-hash authority, zero-based `rank+k` convention, query generation and ratio-driven replacement of children by parents. Do not change our formula/planner or infer scope from an upstream docstore ID. |
| Haystack `286bf8b4083d5835fd59128d2379cfb5aa5a5ed1`; [Apache-2.0](https://github.com/deepset-ai/haystack/blob/286bf8b4083d5835fd59128d2379cfb5aa5a5ed1/LICENSE) | [document_joiner.py](https://github.com/deepset-ai/haystack/blob/286bf8b4083d5835fd59128d2379cfb5aa5a5ed1/haystack/components/joiners/document_joiner.py): `_rrf` 214–218; [utils/misc.py](https://github.com/deepset-ai/haystack/blob/286bf8b4083d5835fd59128d2379cfb5aa5a5ed1/haystack/utils/misc.py): `_reciprocal_rank_fusion` 156–188; [auto_merging_retriever.py](https://github.com/deepset-ai/haystack/blob/286bf8b4083d5835fd59128d2379cfb5aa5a5ed1/haystack/components/retrievers/auto_merging_retriever.py): `run/_try_merge_level` 130–169 | Weighted rank join by identity; recursive parent replacement above a child ratio | NO | YES, design | Keep explicit channel weights and distinct routing versus evidence. Reject its score renormalization, duplicate-ID summation within one list, and recursive ratio-based promotion. Each of our routing keys gets at most one contribution per channel; evidence children survive independently. |
| Onyx `5fe6573c3c155e1a75b51de32d4988ee6c82164e`; [MIT Expat outside EE](https://github.com/onyx-dot-app/onyx/blob/5fe6573c3c155e1a75b51de32d4988ee6c82164e/LICENSE) | [vespa_document_index.py](https://github.com/onyx-dot-app/onyx/blob/5fe6573c3c155e1a75b51de32d4988ee6c82164e/backend/onyx/document_index/vespa/vespa_document_index.py): `hybrid_retrieval` 899–955; [db/search_settings.py](https://github.com/onyx-dot-app/onyx/blob/5fe6573c3c155e1a75b51de32d4988ee6c82164e/backend/onyx/db/search_settings.py): `get_current_search_settings`, `get_secondary_search_settings`, `active_secondary_port_target`, `get_active_search_settings` 153–221 | Filters enter the search expression; explicit PRESENT/FUTURE search settings distinguish index identities | NO | YES, design | Keep server-selected index identity, candidate caps and pre-ranking scope. Reject swapping/promoting a future index, dual writes, title-vector expansion, Vespa alpha/recency scoring and enterprise authorization assumptions. N's lane is non-serving and cannot promote itself. |
| Docling Core `cc39622c6a4bb2643a8631edd996d8874a8e6a47`; [MIT](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/LICENSE) | [hybrid_chunker.py](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/hybrid_chunker.py): `_merge_chunks_with_matching_metadata` 324–368, `chunk` 370–393; [hierarchical_chunker.py](https://github.com/docling-project/docling-core/blob/cc39622c6a4bb2643a8631edd996d8874a8e6a47/docling_core/transforms/chunker/hierarchical_chunker.py): `chunk` 192–297 | Budgeted contextual search serialization retains source items/headings separately | NO | YES, design | Keep exact source references separate from embedding input. Reject importing a new chunker or interpreting “HybridChunker” as a dense/lexical search implementation. It proves no RRF, tenant isolation, shadow index or retrieval recall. M remains frozen. |
| Docling `629440ee795fda854a9f9667ca8c54b0013a5ad6`; [MIT](https://github.com/docling-project/docling/blob/629440ee795fda854a9f9667ca8c54b0013a5ad6/LICENSE) | [docling/chunking/__init__.py](https://github.com/docling-project/docling/blob/629440ee795fda854a9f9667ca8c54b0013a5ad6/docling/chunking/__init__.py), 9–15 | Public chunking facade imports Core chunkers | NO | YES, design boundary | Keep the distinction between conversion/chunking and retrieval. Reject claiming this facade supplies search normalization, canary publication or vector lifecycle. No ingestion/source-capture change. |

The detailed local design is [Phase 4.1N](PHASE_4_1N_DEVELOPMENT_HYBRID_CANARY_DESIGN.md).
Upstream state machines are architectural evidence, not security guarantees for
our application. Exact composite identity, fail-closed eligibility, one primary
route per lexical atom, witness reservation and non-serving generation isolation
are local requirements. No literal upstream code or new dependency is proposed.
