# RAGFlow-derived engine architecture

## Completeness expansion (2026-09-21)

Authenticated Query now accepts bounded history and upstream options: refine_multiturn, cross_languages, keyword, toc_enhance (all off by default). Ordinary pinned query preparation runs before the unchanged Dealer; optional TOC follows Dealer, then actual child-to-parent expansion, then unchanged context/citations. Diagnostic standalone channels are explicitly labeled original-query probes, not model-prepared retrieval traces.

Ingest exposes bounded literal child delimiters and optional upstream keyword/question/TOC generation. Parents and TOCs retain exact organization/bot/source/version/generation identity and READY manifest linkage but are unavailable to normal search. Parent fetch requires an observed child's link; TOC leaves require a saved TOC link in its own document. Every returned row is revalidated, including requested document subset and content hash. Missing parents use upstream child fallback; unauthorized parents fail closed. TOC is generated navigation metadata, never quoted as source evidence.

The operator-injected async_chat callback is scope-checked before/after each call and its cache lasts one authorized operation. No environment/provider autodiscovery and no old provider key reuse. Missing optional model is rejected before ingest begins a new version. Model-backed live validation remains gated; parent expansion can run with existing CPU models alone.

Optional harness helpers are present, but no agentic tool executor, KG/composite-source store or RAPTOR/compiler summary tree is enabled. Those need the real model plus their coherent provenance-aware tool/artifact adapters. This is not a full-RAGFlow claim.

Subsequent explicit user authorization permits ONLY `RAGFLOW_DEV_GEMINI_API_KEY` on the exact new Railway project. The dev-only Gemini callback adapts pinned GoogleChat request mapping to API-key authentication, uses gemini-2.5-flash-lite, one transport attempt, 60-second timeout and a 20-call process budget. Client pools close within each request loop; no application/production credential fallback. Upstream templates, parsing and query transformations are unchanged. MiniLM embedding and reranker remain unchanged. This provider adapter is frozen before live evaluation; no evaluation result is used to change it.

Status: PARTIAL — executable local source pipeline with offline end-to-end validation; not full upstream or production acceptance.

## Separation

```text
Existing platform authorization / bot / history / quota
  └─ internal EngineSelection (default=current)
       ├─ CurrentRagEngineAdapter → unchanged rag_service
       └─ RagFlowDerivedEngineAdapter [explicit development opt-in]
            authorized SourceRef inventory
            → parse bytes / structure / upstream paragraph merge
            → upstream title/content embedding preparation + injected model
            → owned local Elasticsearch index
            → FulltextQueryer + Dealer
            → ES lexical + cosine KNN / release weighted fusion
            → upstream weighted rerank OR injected cross-encoder blend
            → upstream kb_prompt + whole-block budget guard
            → neutral exact-text evidence / full-ID citations
  → existing prompt/system builder + llm_router.generate (same bot/Gemini)
  → existing answer/source shape
```

The original public/widget routes remain unchanged. The new development router factory is intentionally not mounted in main.py. This avoids silently activating a new index/model dependency for current customers. Its response keys are reply, answer, sources and retrieved_chunks; it is not a replacement for public streaming/conversation persistence.

## Modules and interfaces

- backend/ragflow_derived/upstream: attributed actual copied/adapted release code, resources and ES query builder.
- contracts.py: frozen AuthorizedScope, SourceRef, Evidence; sanitized EngineError.
- parsing.py: supplied bytes only, no URL/image fetching; upstream Markdown/HTML + merge; pypdf/python-docx plain extraction wrappers.
- models.py: explicit callbacks implementing encode, encode_queries and similarity. No provider selected implicitly.
- storage.py: explicit ES client, scope/READY/version guards, immutable source manifest and owned delete.
- engine.py: ingest, update_source, delete_source, async retrieve, build_context and close. build_context returns context, evidence, sources/citations and excluded_units.
- services/rag_engine_adapters.py: lazy current adapter, optional new adapter, selector and READY authority translation.
- routes/rag_engine_dev_routes.py: existing login + bot membership + quota, operator-installed only.
- evaluation.py: future paired-query interface, no question set, GOLD or benchmark execution.

## Storage decision and semantic fidelity

Use a separate local Elasticsearch 8.11.3 service, matching the pinned upstream dev default, with the upstream dynamic mapping and scripted term similarity. PostgreSQL is retained for platform authority, not used as a pretend equivalent to the upstream search store. No database migration is required.

Each index key hashes organization, bot, index generation, embedding profile and dimension. Each source key hashes source ID, document ID and version. Text and title token fields, exact extracted text, order, headings, URL, hashes and vector fields are indexed. Title/content vectors retain upstream 0.1/0.9 weighting. Exactness means exact parsed/indexed evidence, not byte-for-byte original PDF/HTML markup.

The port retains FulltextQueryer normalization, token weights, phrase construction, synonyms and hybrid similarity; Dealer retrieval, relaxed lexical retry, ES KNN score recovery, thresholding and optional learned rerank. It does not call our Dense/FTS/RRF/Q1 modules. ES branch uses the pinned weighted-sum candidate request and a second scoped KNN call for cosine scores, then weighted token/cosine or learned scoring. No rank/score equivalence to our old engine is asserted.

Known release behaviors intentionally retained: KNN filter includes lexical query_string; empty hybrid retrieval does not adopt the post-release dense-only rescue; learned reranker sees tokenized text. Native model/ES quality remains unmeasured.

## Security and lifecycle

All operations need a server-issued scope and still_authorized callback. A callback must re-read current authority with its own fresh session, including READY/active-crawl identity, generation and embedding profile, and fail on mismatch. Never share SQLAlchemy sessions across Dealer's worker threads.

Every search (including relaxed retry, second KNN and vector fetch) uses the exact hashed index, bot/dataset and mandatory source-version/ready filters before ranking/limit. Selected rows are checked again for scope, document/source/version/generation, readiness and text hash. Foreign stronger matches are rejected in tests. The upstream MySQL existence TTL cache is bypassed with fresh authority; it cannot authorize cached deleted documents.

An atomic create-only manifest binds content/parser/title/index digest to a source version across processes. Partial new indexing is not searchable until the ready marker is set. A changed digest requires a new source version. Updates ingest a new authorized version; the caller changes its authoritative active inventory. Old rows remain inaccessible and may be explicitly deleted within owned source scope. This is not a distributed ingestion queue or a substitute for platform activation transactions. The in-process registry is only a write ledger, never authorization.

Chunk/citation hashes are identity, not permissions. Whole context retains exact text; snippets cannot modify routes, selectors or system instructions. The final generation prompt places evidence in a data section. This does not claim LLM prompt-injection immunity; adversarial generation testing is deferred, and no providers were called.

## Caps, errors and fallback

Default: input <=8 MiB; DOCX expanded bytes <=160 MiB; PDF <=1000 pages; scope <=10000 sources; 64 retrieval candidates; KNN 1024/2048; result <=48 units; context <=8192 tokens and 131072 UTF-8 bytes including JSON framing. Oversized blocks are excluded whole. A one-byte empty budget returns empty context, not oversized framing.

Error codes cover PARSER_FAILED, INDEX_FAILED, INGESTION_FAILED, RETRIEVAL_FAILED, EMBEDDING_UNAVAILABLE, TOKENIZER_UNAVAILABLE, RERANKER_UNAVAILABLE, PROVENANCE_FAILED and UNAUTHORIZED_SCOPE. Payloads/backend credentials are suppressed. A revoked/stale inventory fails scope authority. No automatic provider, cross-scope, general-data, old-engine or benchmark fallback is implemented. Explicit selection of current remains the safe rollback.

## Deliberate omissions / limitations

- DeepDoc OCR/layout, image/table model pipelines, multimodal embeddings, graph/RAPTOR, TOC/tree traversal and agentic multi-step retrieval are deferred, not claimed as ported.
- PDF/DOCX support here is basic text/table extraction, not DeepDoc parity; scanned PDFs without text fail explicitly.
- No LLM query rewrite, keyword generation, QA enrichment, semantic exclusion guarantee or multi-turn retrieval reformulation is added. History goes to existing generation. Generic query fixtures test execution/boundaries, not measured semantic quality.
- Metadata supports order/headings/type/source/version; full bounding-box/layout/page relation graphs are not produced.
- No upstream MySQL/Redis/MinIO/account/UI/workflow product layer. Existing object storage/crawler remains authoritative; only supplied bytes are ingested.
- Native SDK/tokenizer assets, Elasticsearch and real model callbacks require separate setup/validation. The in-memory test store is never a production backend.
