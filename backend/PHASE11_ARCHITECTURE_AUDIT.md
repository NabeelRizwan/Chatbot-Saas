# Phase 11 — Enterprise Architecture Audit

**Date**: 2026-08-17  
**Scope**: Full Backend Audit for Enterprise Hardening (Phases 11A – 11J)  
**System**: Multi-Tenant Website Knowledge RAG Platform

---

## 1. Background Tasks Inventory

| Location | Trigger Endpoint / Function | Handler | Execution Type | Survives Restart? | Notes / Risks |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `backend/routes/knowledge_routes.py:80` | `POST /knowledge/upload` | `process_document_job(document.id)` | FastAPI `BackgroundTasks` | **No** | In-process asyncio task; lost if API restarts during upload. |
| `backend/routes/knowledge_routes.py:101` | `POST /knowledge/crawl` | `process_document_job(document.id)` | FastAPI `BackgroundTasks` | **No** | In-process asyncio task; lost if API restarts during crawl. |
| `backend/routes/public_routes.py:84` | `POST /public/chat/{bot_id}` | `track_widget_chat_message(...)` | FastAPI `BackgroundTasks` | **No** | Analytics logging lost if worker terminates abruptly. |

**Audit Recommendation**: Introduce a durable Redis-backed job system (`ARQ` worker) to queue and execute crawls, document processing, embedding generation, and maintenance tasks with persistent state in PostgreSQL / Redis.

---

## 2. Database Session Lifecycle & Connection Pool

| Component | Method | Pool Configuration | Session Management |
| :--- | :--- | :--- | :--- |
| `backend/database/connection.py` | `engine = create_engine(...)` | Hardcoded: `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True` | `SessionLocal = sessionmaker(...)` |
| `backend/database/connection.py` | `get_db()` | N/A | FastAPI dependency with `try...finally: db.close()` |
| Background Jobs (`document_processing_service.py`) | `process_document_job()` | Uses shared engine | Explicit `db = SessionLocal()` with `try...finally: db.close()` |
| Platform Keys (`llm_router.py`) | `_resolve_api_key()` | Uses shared engine | Context manager `with SessionLocal() as db:` |

**Audit Recommendation**:
- Parameterize database pool settings via environment variables (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`).
- Add DB health check and connection leak monitoring.

---

## 3. LLM API Call Points & Providers

| Component | Caller Function | Provider / Model | Retry & Backoff | Timeout / Error Handling |
| :--- | :--- | :--- | :--- | :--- |
| `backend/services/llm_router.py:84` | `generate()` | Gemini (`gemini-2.5-flash`), OpenAI, Claude, Grok | Currently direct API dispatch; basic error handling | Raises `LLMRouterError` on failure |
| `backend/services/llm_router.py:126` | `generate_stream()` | Gemini, OpenAI, Claude, Grok | Direct stream generator | Yields error fallback tokens |
| `backend/services/rag_service.py:1378` | `answer_question` (Draft) | Dispatched via `generate()` | Catch `Exception` and returns friendly fallback | Custom 429 quota message |
| `backend/services/conversational_engine.py:280` | `verify_answer()` | Dispatched via `generate()` | Single try/except | Verifies draft grounding |
| `backend/services/conversational_engine.py:340` | `polish_answer()` | Dispatched via `generate()` | Single try/except | Polishes response tone |

**Audit Recommendation**:
- Centralize LLM requests in a unified `llm_client.py` with exponential backoff, jitter, circuit breaker, timeout configuration, and non-retryable 4xx handling.

---

## 4. Embedding Generation Call Points

| Component | Function | Provider | Dimensions | Batching Support | Deduplication |
| :--- | :--- | :--- | :---: | :---: | :---: |
| `backend/services/embedding_service.py:124` | `generate_embedding(text)` | `gemini-embedding-001` (fallback OpenAI / SHA-256) | 768 | Individual single calls | In-memory 1,000 entry LRU cache |
| `backend/services/document_processing_service.py:392` | `process_document()` | Single chunk loop calls `generate_embedding()` | 768 | Single-call loop | Content-hash (SHA-256) skips unchanged chunks |
| `backend/services/rag_service.py:477` | `retrieve_relevant_chunks()` | Vector query generation | 768 | Single query embed | Cached in `_EMBEDDING_CACHE` |

**Audit Recommendation**:
- Add batch embedding generation (`generate_embeddings_batch(texts)`) with bounded concurrency and retry resilience.

---

## 5. Caching Systems Inventory

| Cache Name | Location | Key Structure | Storage | Invalidation Strategy |
| :--- | :--- | :--- | :--- | :--- |
| `global_semantic_cache` | `backend/services/conversational_engine.py:25` | `(bot_id, normalized_query)` | In-memory Dict | TTL (3600s) + `clear(bot_id)` on document upload/delete |
| `_RETRIEVAL_CACHE` | `backend/services/rag_service.py:384` | `(bot_id, query, top_k, mode)` | In-memory Dict | Max size 1,000 + `clear_retrieval_cache(bot_id)` |
| `_EMBEDDING_CACHE` | `backend/services/embedding_service.py:121` | `(text, provider_name)` | In-memory Dict | Max size 1,000 |

**Audit Recommendation**:
- Expand semantic & retrieval caches to include `organization_id` and `active_knowledge_version` in the key (`rag:{org_id}:{bot_id}:{version}:{query_hash}`).
- Ensure version updates trigger atomic cache invalidation for the bot.

---

## 6. Multi-Tenant Boundary & Scope Resolution

| Endpoint / Service | Tenant Scope Enforcement | Database Query Filtering | Security Level |
| :--- | :--- | :--- | :---: |
| `backend/services/rag_service.py:422` | `get_knowledge_scope(db, bot_id)` | `Chunk.bot_id == bot_id`, `Chunk.organization_id == org_id`, `Document.status == 'ready'`, `Chunk.status == 'ready'` | **High (Database-enforced)** |
| `backend/routes/knowledge_routes.py` | `_ensure_bot(db, bot_id, user)` | `require_org_role(db, user, bot.organization_id)` | **High** |
| `backend/routes/bot_routes.py` | `get_bot_or_404(db, bot_id, user)` | `Bot.organization_id == user.org_id` | **High** |
| `backend/routes/public_routes.py` | `get_public_bot_or_404(db, bot_id)` | Public widget by `bot_id` with usage rate limiting | **Medium** |

**Audit Recommendation**:
- Ensure all queries unconditionally derive tenant scope from authenticated context.
- Create centralized helper `get_authorized_knowledge_scope(db, bot_id, user_or_key)`.

---

## 7. Knowledge Versioning & Zero-Downtime State Machine

- **`Website`**: Persists `root_url`, `domain`, `status`, `crawl_status`, `active_crawl_id`.
- **`WebsiteCrawl`**: Tracks `version = latest + 1`, `status` (`processing`, `ready`, `failed`).
- **`Document` / `Chunk`**:
  - `status` (`ready`, `processing`, `processing_failed`), `content_hash` (SHA-256).
  - Failed recrawl sets `WebsiteCrawl.status = 'failed'` while keeping existing `ready` documents active.
  - Active version updates only when the new crawl completes successfully.

---

## 8. Summary of Hardening Tasks for Phase 11

1. **Phase 11A**: Architecture Audit (Completed).
2. **Phase 11B**: Redis + Durable Job Queue (`ARQ` worker infrastructure).
3. **Phase 11C**: Job State Machine (`QUEUED` $\rightarrow$ `CRAWLING` $\rightarrow$ `PROCESSING` $\rightarrow$ `EMBEDDING` $\rightarrow$ `VALIDATING` $\rightarrow$ `READY`).
4. **Phase 11D**: Rate Limiting & Concurrency Control (Redis token bucket & semaphores).
5. **Phase 11E**: LLM Client + Batch Embedding Pipeline (exponential backoff & circuit breaker).
6. **Phase 11F**: Tenant-Safe Caching & Configurable DB Pool.
7. **Phase 11G**: Structured JSON Logging, Health Endpoints (`/health/live`, `/health/ready`), Graceful Shutdown.
8. **Phase 11H**: SSRF & Crawler Resource Hardening.
9. **Phase 11I**: Enterprise Load Testing (100, 250, 500 concurrent chats) & Chaos Testing.
10. **Phase 11J**: Full Regression Validation (RAG suites, Crawl4AI suites, Stress suites).
