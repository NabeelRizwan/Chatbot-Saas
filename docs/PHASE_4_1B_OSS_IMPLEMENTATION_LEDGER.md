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
