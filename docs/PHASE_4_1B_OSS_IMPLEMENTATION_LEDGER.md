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
