# RAPTOR / summary-tree port

Actual pinned `RecursiveAbstractiveProcessing4TreeOrganizedRetrieval`, `RaptorService`, configuration, tree projection and duplicate-name rewriting are mapped. File-level compilation preserves upstream adjacent-vector clustering, summary prompts, stopping conditions and model calls. No custom clustering or summarization policy was created.

Two explicit products exist: searchable RAPTOR summaries and generated document-tree/navigation artifacts. The serializer retains the `source_chunk_ids` already returned by the upstream builder; a sidecar derives parent lineage from actual child edges. It rejects dangling/cyclic/foreign references. It does not invent a tree around retrieval results.

Summary rows live in an owned private Elasticsearch index. RAPTOR retrieval issues one unchanged ES query across authorized source leaves plus authorized summaries; it does not create a custom two-result fusion. Original source rows remain separately hash-verified. Generated summary text, lineage and original supporting evidence are returned separately. Normal mode does not implicitly include summaries.

Bounds: at most 10,000 source leaves and generated rows per development compilation, exact authorized inventory, explicit per-operation deadline, file-scope config only. Upstream returns no summary for a single input leaf; no fake summary is fabricated. Structured-source auto-disable remains upstream behavior. Dataset-wide RAPTOR compilation, incremental resume and distributed worker orchestration are not exposed by this adapter.

Offline tests execute the actual small- and larger-tree builders, leaf linkage, source/version restrictions, publication conflict/uncertain-publication handling, and joint retrieval. The 13-symbol AST gate includes the entire RAPTOR builder class. Live status: see `RAGFLOW_FULL_PORT_LIVE_REPORT.md`.
