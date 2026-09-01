# Phase 11A — Baseline Architecture & System Freeze

**Date**: 2026-08-17  
**Scope**: Phase 11A Baseline Validation & Architectural Freeze  
**Status**: COMPLETE & VERIFIED

---

## 1. Current Architecture Overview

The system operates as a multi-tenant Chatbot SaaS backend featuring Crawl4AI-based website ingestion, PostgreSQL/pgvector persistent knowledge storage, structure-aware semantic chunking, and Phase 9 multi-mode hybrid retrieval with Generate $\rightarrow$ Critique $\rightarrow$ Verify $\rightarrow$ Polish response generation.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          INGESTION & CRAWLING LAYER                         │
│  Customer Website ──► Crawl4AI (Chromium) ──► Normalization & Content Hash  │
│  ──► Structure-Aware Chunking ──► Vector Embeddings ──► PostgreSQL/pgvector │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ (Persistent Knowledge Base)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RETRIEVAL & RUNTIME PIPELINE                       │
│  User Query ──► Tenant Boundary Resolution (get_knowledge_scope)            │
│  ──► Intent Router ──► Hybrid Retrieval (Cosine + BM25 + SKU/Exact Boost)   │
│  ──► Diversity & Reranker ──► Context Budgeting & Untrusted Tagging         │
│  ──► LLM Generation ──► Critique ──► Verify ──► Polish ──► Grounded Response│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Dependencies & Runtime Stack

- **Framework**: FastAPI + Starlette + Uvicorn
- **ORM & Database**: SQLAlchemy 2.0 + psycopg2-binary + PostgreSQL (`pgvector` extension)
- **Crawler / Browser**: `crawl4ai` (v0.9.2) + Playwright Chromium
- **LLM SDKs**: `google-genai` (Gemini 2.5 Flash), `openai` (GPT-4o), Anthropic Claude, Grok
- **Embeddings**: `google-genai` (`gemini-embedding-001`), `openai` (`text-embedding-3-small`), 768-dim Vector storage
- **HTML / Doc Parsing**: BeautifulSoup4, PyPDF, python-docx, tiktoken

---

## 3. Worker & Background Execution Model

- **Current Implementation**: FastAPI `BackgroundTasks` (`add_task(process_document_job, document.id)`).
- **Execution**: In-process asynchronous task spawned on the API event loop.
- **Limitation**: Does not survive API server or process restarts. If the API container terminates midway through a crawl or embedding generation, the task is dropped and the document remains in `processing` state.

---

## 4. Database Connection Pool Configuration

- **Current Implementation**:
  - `pool_size=5` (hardcoded)
  - `max_overflow=10` (hardcoded)
  - `pool_pre_ping=True`
- **Session Handling**: `SessionLocal = sessionmaker(bind=engine)`, with `try...finally: db.close()` in request endpoints and service functions.

---

## 5. Redis & Cache Architecture

- **Current Implementation**:
  - `global_semantic_cache`: In-memory dictionary with TTL (`ttl_seconds=3600`) and LRU eviction (500 items max).
  - `_RETRIEVAL_CACHE`: In-memory dictionary (1000 items max).
  - `_EMBEDDING_CACHE`: In-memory dictionary (1000 items max).
  - `RateLimitMiddleware`: In-memory token bucket keyed by client IP.
- **Limitation**: Cache entries and rate limits are node-local and not shared across horizontally scaled API replicas.

---

## 6. LLM & Embedding Call Points

- **LLM Dispatch**: `services/llm_router.py` $\rightarrow$ `generate()` and `generate_stream()`.
  - Providers supported: Gemini, OpenAI, Claude, Grok.
  - API key priority: BYOK (`bot.provider_api_key`) $\rightarrow$ Platform Key Pool (`platform_api_keys` table) $\rightarrow$ Environment (`GEMINI_API_KEY`).
- **Embedding Generation**: `services/embedding_service.py` $\rightarrow$ `generate_embedding(text)`.
  - Provider: Gemini `gemini-embedding-001` (768-dim) with fallback deterministic vector generation.

---

## 7. Baseline Test Execution Results

All 6 test suites executed on the baseline repository passed with 100% success:

| Test Suite | File | Tests / Validations | Status | Duration |
| :--- | :--- | :---: | :---: | :---: |
| **Phase 9 Core RAG Pipeline** | `backend/test_rag_pipeline.py` | 15 Suites / 35 Validations | **PASS** | 2.8s |
| **Production Platform Suite** | `backend/test_production_platform_suite.py` | 5 Tests (Tenant isolation, persistence, zero-downtime, injection, 50-thread concurrency) | **PASS** | 20.4s |
| **Crawl4AI Proof of Life** | `backend/test_crawl4ai_proof.py` | 1 Live Crawl Test | **PASS** | 5.8s |
| **Crawl4AI Adapter Suite** | `backend/test_crawl4ai_adapter.py` | 9 Unit Tests | **PASS** | 5.7s |
| **Crawl4AI Ingestion Suite** | `backend/test_crawl4ai_ingestion.py` | 3 Integration Tests (Live docs crawl, incremental recrawl, CTA metadata) | **PASS** | 27.4s |
| **Real-World Stress Suite** | `backend/test_real_world_stress.py` | 8 Tests (Live IKEA dynamic crawl, multi-page catalog, CTAs, cross-page synthesis, tenant isolation) | **PASS** | 23.0s |

---

## 8. Identified Production Hardening Opportunities (Phases 11B–11J)

1. **Durable Queue**: Transition from FastAPI `BackgroundTasks` to Redis-backed `ARQ` worker queue.
2. **Job State Machine**: Explicit states (`QUEUED`, `CRAWLING`, `PROCESSING`, `EMBEDDING`, `VALIDATING`, `READY`, `FAILED`, `CANCELLED`).
3. **Distributed Rate Limiting & Concurrency**: Redis token bucket and semaphores for global & per-tenant limits.
4. **Resilient LLM Client**: Exponential backoff, jitter, circuit breaker, and 429 quota protection.
5. **Batch Embedding Pipeline**: Batch embeddings with bounded concurrency and retry resilience.
6. **Configurable DB Pool**: Environment variables for pool sizing, overflow, timeout, and recycle.
7. **Tenant-Safe Distributed Caching**: Cache keys incorporating `(org_id, bot_id, active_version, query_hash)`.
8. **Observability & Health**: `/health/live`, `/health/ready`, `X-Request-ID` correlation IDs, graceful shutdown.
9. **SSRF & Crawler Ceilings**: Private IP/metadata blocking and max browser/crawl limits.
10. **Load & Chaos Verification**: 100, 250, 500 concurrent chat testing and fault-injection simulations.
