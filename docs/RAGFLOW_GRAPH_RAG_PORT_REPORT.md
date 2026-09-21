# GraphRAG / KG port

Actual pinned `rag/graphrag/general/index.py:run_graphrag_for_kb`, light/general extractors, graph merging/indexing, entity resolution, and `search.py:KGSearch` are mapped. The explicit development API compiles the default light extraction with unchanged `GraphragConfig`; internal engine configuration also supports the copied general extractor/resolution. Graph query rewriting uses the shared Gemini adapter and original prompts. Graph/entity/relation/subgraph rows are stored through the existing Elasticsearch adapter, not a new graph database.

Storage adaptation: each compilation uses a unique private index and a CREATE-only immutable publication manifest. Readback validates the whole build before publication. Atomic publication conflicts cannot replace the prior build. Uncertain publication never deletes a possibly published index. Every returned generated row is hash-checked and its original supporting source inventory revalidated.

Pinned KG `source_id` is document-level, not an exact claim/chunk attribution. The adapter preserves that precision honestly: all referenced documents and their source/version/chunk support are listed; generated graph prose is never labelled original evidence. Cross-document merged-edge provenance is included, not narrowed to a row label. Foreign, stale, wrong-generation, deleted, corrupt and unauthorized-node cases fail closed.

Optional community extraction remains disabled: the pin requires a specific graspologic fork (`38e680cab72bc9fb68a7992c3bcc2d53b24e42fd`) and native dependency closure, not interchangeable PyPI graspologic. NER remains disabled without the pinned spaCy language models. The software modules and configuration are retained; requesting these uninstalled modes fails before provider calls. They are not live-supported claims. No GPU, new service or production data is required for the implemented light/general path.

Offline tests exercise actual extraction → merge → store → KG query rewrite/retrieval, not a hand-constructed graph substituted for runtime compilation. Live status: see `RAGFLOW_FULL_PORT_LIVE_REPORT.md`.
