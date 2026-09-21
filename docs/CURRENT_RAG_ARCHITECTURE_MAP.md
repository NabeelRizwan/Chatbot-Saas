# Current RAG architecture map

Date: 2026-09-21. Inspected actual source at main `1b8be711d7f59cafdf9c6552778f396731c0a76d`, not only historical reports. No existing file was changed.

## Preservation and boundary

The starting tree had no tracked modifications and 19 untracked Q2/Q4 diagnostic/experiment files. A local ignored preservation inventory (`.codex_ragflow_preservation.json`) covers all 579 initial tracked/untracked files. The accepted Q1 packing and Q3 discovery/follow-up scope code stays frozen. Rejected breadth/companion/supplemental/channel experiments are neither imported nor committed in this work.

Two existing paths must not be conflated: public chat uses the existing `rag_service.answer_question` orchestration; the accepted structural canary uses `canary_retrieval.run_query` and Q1 `materialize_compact`. This port replaces neither default path.

## Actual boundaries

Paths below are relative to the repository; arrows identify callers. KEEP means unchanged; BYPASS applies only to explicitly selected development RAGFlow retrieval.

| Area / files and symbols | Caller; input → output | Side effects / security boundary | Decision |
| --- | --- | --- | --- |
| Startup: backend/main.py, scripts/start_api.py | ASGI startup → FastAPI/router registry | Existing startup/config/default-plan initialization; tests stub its DB initialization | KEEP; optional router is not mounted |
| Routes: routes/chat_routes.py chat, dashboard_playground_chat; routes/public_routes.py public_chat/public_chat_stream | HTTP message/history/bot → answer/sources/stream events | Existing quota, public-session/origin/token and tenant access rules | KEEP external contracts |
| API-key/customer flow: services/auth_service.py; chat_routes.chat | API key → owned bot/customer | Client key is not an organization/scope grant | KEEP |
| Org/bot authority: services/bot_service.py get_bot_or_404; organization/auth services | Authenticated user + bot ID → authorized Bot | Membership/role/platform-admin boundary | KEEP; reuse before constructing internal scope |
| Source identity: database/models.py Document, Website, WebsiteCrawl, DocumentChunk | Upload/crawl jobs → versioned records | Organization + bot + document + crawl/version are authoritative | KEEP; translate identities, never take them from a model |
| Knowledge/upload: routes/knowledge_routes.py; routes/ingest_routes.py _ingest_document | Authorized file/text → queued/current knowledge | Resource quota, ownership, file/storage lifecycle | KEEP; no automatic replay into new index |
| Crawl: services/crawler_service.py CrawlPage; workers/crawl_worker.py execute_crawl_job | Authorized URL/job → canonical URL, title, markdown, metadata, links/status | Existing provider and crawl-version checks | KEEP crawler; pass already-owned markdown as kind=crawl |
| Parsing: existing extraction helpers/ingest route | Owned bytes → extracted text | Current blob storage and parser errors | BYPASS only for new-engine ingestion; text PDF/DOCX wrappers supplied |
| Chunking: services/chunking_service.py chunk_text_with_metadata | Text/title/source type → paragraph/section chunks | Existing size/overlap/metadata behavior | BYPASS; new port uses upstream parser/merge algorithms |
| Structural representation: services/structural_* and canary modules | Source snapshots/manifests → structural units/entries | Sealed source/version/profile provenance | KEEP frozen; not used to implement new packer |
| Embeddings: workers/embedding_worker.py execute_document_job, existing embedding/provider adapters | Current chunks → vectors/profile | Credential routing and per-bot profile | KEEP defaults; new engine accepts explicit document/query callbacks |
| Vector storage: PostgreSQL/pgvector models and retrieval services | Authorized vector query → candidates | Tenant/profile/dimension gates | BYPASS in optional engine; separate local ES index |
| Lexical: services/postgres_fts.py fts_candidates | Session factory/query/scope/profile/limit → ranked candidates | SQL filters before LIMIT | BYPASS; port uses ES query_string, not ILIKE or PostgreSQL FTS |
| Fusion: services/hybrid_retrieval.py weighted_rrf | Dense + FTS ranks → deterministic fused candidates | Shared authorized candidate scope | BYPASS; new engine uses RAGFlow weighted search/rerank, not RRF |
| Query: services/rag_planning.py prepare_query; services/query_contract.py | Question/history/state → resolved contract | Planner cannot grant scope | KEEP default; optional path uses FulltextQueryer, no old planner |
| Follow-up/discovery: services/discovery_scope.py preserve_discovery_scope | Contract/history → set-preserving scope | Accepted Q3 logic | KEEP frozen; not imported by new engine |
| Hard scope: services/knowledge_scope.py ready_chunks, ready_documents | Bot/org/allowed docs → READY query | Document ready/completed, chunk ready; active READY crawl/version for website rows | KEEP as authority; new ready_platform_scope translates eligible documents |
| Evidence: rag_service orchestration; canary_retrieval.run_query → compact_evidence_pack.materialize_compact | Candidates → bounded original evidence | Q1 exact 131072-byte / 48-unit canary cap | KEEP; new packer independently uses upstream kb_prompt + whole-block cap |
| Citations: current source materialization/public stream serializer | Retrieved evidence → user-visible sources | No source may widen scope | KEEP public path; new neutral citations have full chunk/source/version/hash |
| Gemini: services/llm_router.py generate; rag_service.build_rag_prompt / _get_system_instruction | Bot + prompt + system instruction → reply | Existing credential, retry and usage/provider selection | KEEP invocation; optional adapter supplies neutral evidence context |
| History: conversation routes/services and rag_service state | Session/turn/history → persisted conversation/answer | Existing owner/session rules | KEEP public persistence; dev endpoint passes explicit history only |
| Widget: public_routes widget config/session/chat/stream | Existing widget contract → reply/sources | Public token/origin/session checks | KEEP; no widget/UI edits |
| DB/migrations: database/models.py, Alembic | Current schema/lifecycle | Existing deployment migration process | KEEP; no new production/development SQL migration |
| Jobs/cache: existing ARQ/Redis, workers | Queued ingestion and caches | Current retry/ownership/configuration | KEEP; new local engine is synchronous ingestion, per-call retrieval; no auth cache |
| Tests/deploy: scripts/test_scoped_rag_regressions.py; existing Railway docs/config | Offline suites / existing deploy | No live provider or DB action | KEEP; optional dependencies/compose isolated under new paths |

## New handoff

`EngineSelection()` returns CurrentRagEngineAdapter. Explicit development opt-in permits RagFlowDerivedEngineAdapter. A trusted server callback resolves READY scope after normal bot authorization; a fresh-session callback revalidates scope during all new-engine reads and before returning an answer. No client-selected organization, source list, engine or index is accepted by the optional development router.

Current Python: 3.12.14. Existing backend requirements/venv, frontend dependencies, production variables, PostgreSQL data, credentials and Railway configuration were not changed. Optional dependencies are isolated in backend/requirements-ragflow.txt and the ignored local test venv.
