# Document/tree navigation

Actual upstream `knowlege_compile/dataset_nav.py`, structure serialization, tree builder/projection and `harness/tools/navigation.py` are integrated. Compilation creates actual document graph/entity/relation rows and dataset navigation summaries from authorized leaves. Navigation calls the pinned `_navigate_tree_impl` and `_navigate_structure_impl`; there is no homemade tree or query-time hierarchy substitute.

The existing ES service holds all artifacts. Per-private-build locks serialize mutable graph writes; unique index ownership plus atomic manifest publication avoids sharing a mutable dataset between compilers. No fake Redis lock is presented as cross-process locking. Request-local caches have no durable checkpoint claim.

Document IDs, node IDs, scope filters and returned source pointers are checked before/after access. A selected source collection is an explicit subset of the server's active scope and receives its own sealed manifest; broader manifests cannot be reused for a narrower capability. Navigation returns real upstream result statistics plus generated artifact support inventory. That inventory is not advertised as exact claim-level citations.

Supported: generated RAPTOR-based document trees and dataset navigation. Partial: arbitrary user compilation templates (timeline/page-index/mindmap/hypergraph/wiki) have copied helper source but are not all connected to a product template/task runtime. Versioned wiki publishing is explicitly unavailable because no FileCommitService revision store is configured. Plain PDF has outlines but no fabricated page/bbox layout metadata. Optional OCR/vision is not activated.

Live execution must pass independently; source import or an HTTP health response alone is not navigation acceptance.
