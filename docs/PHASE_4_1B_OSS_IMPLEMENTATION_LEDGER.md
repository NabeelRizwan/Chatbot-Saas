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
