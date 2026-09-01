# Repository-Wide Product & Engineering Audit

Audit date: 2026-08-20  
Repository audited: Chatbot-Saas  
Audit mode: reconnaissance only; no source code was changed

## Executive assessment

This repository is not a superficial chatbot demo. It contains a substantial FastAPI/PostgreSQL/pgvector backend, multi-page Firecrawl ingestion, structure-aware chunking, hybrid retrieval with Reciprocal Rank Fusion, seven query modes, conversation persistence, organizations and roles, rate limiting, semantic caching, provider routing, a Next.js dashboard, and an embeddable streaming widget.

It is nevertheless not ready to sell as a safely embeddable, polished multi-tenant SaaS. The strongest engineering is concentrated inside the RAG and ingestion services. The highest-risk failures occur at the seams between those services and the customer product:

1. Bots with no organization create a critical authorization bypass. Bot and knowledge access checks are conditional on organization_id being non-null, while the authenticated create flow can create exactly such bots.
2. Every dashboard/playground chat route calls an unimported ensure_can_send_message symbol and will fail at runtime.
3. The main frontend bot client discards most fields from the advanced builder, including widget configuration, status, capabilities, tone, description, avatar, and category. The UI reports success for settings that did not persist.
4. Draft or disabled bots remain publicly discoverable and usable because public bot resolution checks only existence.
5. Generated iframe, cURL, and public bot links point to a frontend route that does not exist; the conversation share route is stored under a literal percent-encoded directory and is also broken.
6. ARQ is present in code and tests, but the live dispatcher is a pass statement and Docker Compose has neither Redis nor a worker. Ingestion runs in the API process via FastAPI BackgroundTasks.
7. Billing is a data model and quota skeleton, not a commerce system. Checkout is a placeholder, there is no payment provider integration or portal, and the webhook is unsigned and reflects its payload.

The core can become a commercial product without being replaced, but the correct next move is contract repair, tenant hardening, and end-to-end acceptance work—not another retrieval rewrite.

### Method and confidence

The audit searched the repository broadly and traced active imports from backend/main.py and frontend/app. It inspected routes, models, services, workers, stores, API clients, widget code, deployment files, and tests. Findings cite concrete file and line evidence.

Read-only static validation performed:

- All 102 Python files parsed successfully with Python AST.
- TypeScript completed with zero errors using tsc --noEmit --incremental false.
- ESLint completed with zero errors and two warnings, both use of unoptimized img elements in advanced-bot-builder.tsx:255 and platform-client.tsx:934.

No live database, Redis, Firecrawl, LLM, browser, or destructive test suite was run. Therefore, this report distinguishes code-path verification from live operational proof. Existing JSON result artifacts and mocked suites were not treated as proof of the deployed system.

Severity meanings:

- CRITICAL: exploitable tenant/security failure or a primary product flow that cannot safely operate.
- HIGH: major customer flow is broken, materially misleading, or creates serious production/revenue risk.
- MEDIUM: meaningful reliability, quality, scale, or UX deficiency with a workaround.
- LOW: cleanup, polish, documentation, or localized maintainability issue.

## 1. Verified Architecture

### Runtime topology

| Layer | Verified implementation | Operational assessment |
|---|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Zustand, Axios; App Router pages under frontend/app | Active and type-correct, but several UI/API contracts are disconnected |
| Widget | Standalone shadow-DOM script at frontend/public/widget.js | Active embed path; streams from public FastAPI routes |
| API | FastAPI application in backend/main.py | Active; mounts auth, organizations, billing, bots, ingestion, knowledge, chat, public, analytics, and conversations |
| Database | PostgreSQL through SQLAlchemy with pgvector Vector(768) | Active design; startup creates and mutates schema directly |
| Crawling | Firecrawl v2 API through backend/services/firecrawl_service.py | Active knowledge path; polls external crawl jobs synchronously |
| Document processing | PDF, TXT, DOCX extraction; semantic/structure-aware chunking | Active; no OCR and no CSV/XLSX/Markdown support |
| Embeddings | Gemini or OpenAI adapters, 768-dimensional vectors, batching and in-memory cache | Active, but silently substitutes deterministic fallback vectors |
| Retrieval | Vector search plus lexical ILIKE search, RRF, sibling and cross-page expansion | Active; lexical branch is not PostgreSQL full-text search |
| Answering | Intent/retrieval modes, prompt construction, synchronous critique/verify/polish, provider router | Active; streaming takes a materially weaker direct path |
| Caching | In-memory and optional Redis rate limits, semaphores, retrieval cache, tenant-scoped semantic cache | Partially active; cache keys and multi-process invalidation have gaps |
| Jobs | IngestionJob state model, workers, ARQ imports/settings, FastAPI BackgroundTasks fallback | ARQ is not connected; production path is in-process |
| Deployment | Docker Compose for Postgres, backend, frontend | Incomplete for the architecture because Redis and workers are absent |

Evidence: backend/main.py:34-40, 63-83; backend/database/models.py:240-276; backend/services/document_processing_service.py:30, 245-310; backend/services/rag_service.py:382-419, 1237-1255; backend/services/queue_service.py:19-31, 82-97; docker-compose.yml:3-46.

### Actual primary request flows

#### Customer signup and session

Frontend auth form → frontend/services/auth-service.ts → POST /auth/register or /auth/login → password verification and refresh-session creation → access and refresh tokens stored by Zustand persist → DashboardShell checks/refreshes the session.

Passwords use PBKDF2-HMAC-SHA256 and refresh tokens are hashed in the database. Access tokens are custom HMAC JWTs. Both tokens are persisted in browser localStorage through Zustand, not in HttpOnly cookies. Evidence: backend/services/auth_service.py:18-51, 91-125; frontend/services/auth-service.ts:15-25; frontend/store/auth-store.ts:34-47; frontend/components/layout/dashboard-shell.tsx:17-52.

#### Bot creation and editing

AdvancedBotBuilder → bot-service.ts → /bot/create or /bot/{id} → bot_service → optional organization-role and quota check → Bot database row → optional platform-key allocation.

The backend schema and service support rich fields, but bot-service.ts sends only a small subset. This is the principal frontend/backend contract break. Evidence: backend/schemas/schemas.py:17-67; backend/services/bot_service.py:126-157, 173-240; frontend/components/bots/advanced-bot-builder.tsx:35-128; frontend/services/bot-service.ts:24-60.

#### Knowledge upload

Knowledge UI → multipart POST /knowledge/bots/{bot_id}/documents → optional auth/tenant check → extension/MIME validation → file storage and Document row → IngestionJob → API BackgroundTasks → document extraction → chunking → embedding → Chunk rows → ready state.

The job and worker abstractions exist, but dispatch does not enqueue to Redis. Evidence: backend/routes/knowledge_routes.py:75-102; backend/services/document_processing_service.py:39-117, 245-633; backend/services/queue_service.py:42-97.

#### Website ingestion

Knowledge UI → POST /knowledge/bots/{bot_id}/crawl → root Document and job → process_document → Website/WebsiteCrawl version → Firecrawl crawl API and polling → one Document per page → chunk and embed each page → partial commits → crawl status update.

Firecrawl is the active path. Crawl4AI is referenced by tests and demos but is not imported by the active knowledge processor. Evidence: backend/services/document_processing_service.py:21, 30, 287-310; backend/services/firecrawl_service.py:228-460; repository-wide references to services.crawl4ai_service occur only in tests/demos.

#### Public widget chat

External page script → frontend/public/widget.js → GET /public/widget/{bot_id} → sessionStorage session/history → POST /public/chat/{bot_id}/stream → RAG stream → SSE tokens → widget text bubble → conversation/analytics persistence.

The browser supplies bot_id and session_id. There is no embed secret and no origin allowlist. Evidence: frontend/public/widget.js:341-405, 502-577; backend/routes/public_routes.py:22-50, 114-173.

#### Retrieval and answer generation

Question/history → intent classification → one of FACTUAL, ENTITY, CATALOG, FILTER, COMPARISON, POLICY, PURCHASE → query rewrite → vector and lexical candidates → RRF → sibling/cross-page expansion → structured prompt → LLM.

The synchronous path critiques every generated RAG answer and conditionally verifies and polishes flagged answers. The streaming path directly streams provider output and does not run critique, verification, or polishing. Evidence: backend/services/intent_router.py:272-337, 450-506; backend/services/rag_service.py:382-419, 1495-1578, 1600-1685, 1690-1988.

### Verification of the stated baseline

| Claimed baseline | Verdict | Evidence-based qualification |
|---|---|---|
| FastAPI, PostgreSQL, pgvector | COMPLETE | Active application and Vector(768) model |
| Firecrawl ingestion | COMPLETE | Active processor imports Firecrawl service |
| Deep multi-page crawling | COMPLETE | Firecrawl crawl with default max 20 pages/depth 2 |
| Structure-aware extraction/chunking | COMPLETE | Structured metadata and hierarchy-aware chunking are active |
| Embeddings | PARTIAL | Real providers exist, but silent deterministic fallback can corrupt vector-space consistency |
| Hybrid vector + lexical retrieval | COMPLETE | Both active; lexical branch is ILIKE, not true full-text indexing |
| Reciprocal Rank Fusion | COMPLETE | Active hybrid fusion |
| Seven Phase 9 modes | COMPLETE | All seven modes are classified and used |
| Sibling/context expansion | COMPLETE | Active |
| Cross-page synthesis | COMPLETE | Active |
| Knowledge coverage manifests | PARTIAL | Manifest is computed during crawling but discarded rather than persisted or shown |
| Canonical/CTA grounding | PARTIAL | Metadata/prompt support exists; the widget renders the result as non-clickable text |
| Follow-up resolution | COMPLETE | History-aware classification, query rewrite, and prompts exist |
| Generate → Critique → Verify → Polish | PARTIAL | Synchronous only; verify/polish conditional; absent from streaming |
| Redis | PARTIAL | Optional cache/rate-limit/semaphore support; absent from Compose |
| ARQ/background jobs | BROKEN | ARQ code exists, but live dispatch is pass and no worker is deployed |
| Job state machine | PARTIAL | States and tests exist; cancellation cannot interrupt active work |
| Tenant isolation | BROKEN | Strong for normal organization rows, critically bypassed for null-organization records |
| Knowledge versioning | PARTIAL | Version models exist; active promotion and retrieval filters do not provide true zero-downtime version isolation |
| Rate limiting | PARTIAL | Global/public non-stream enforcement exists; public streaming skips per-route limiter |
| Semantic caching | PARTIAL | Tenant/bot/version/model scoped, but omits conversation history and important bot configuration |
| LLM/embedding resilience | PARTIAL | Synchronous LLM path is resilient; streaming bypasses it; embeddings silently fall back |
| DB pooling | COMPLETE | Pool size, overflow, pre-ping, and metrics exist |
| Observability/tracing | PARTIAL | ChatTrace and metrics hooks exist; console prints and incomplete truth semantics remain |
| Existing widget architecture | COMPLETE | Functional standalone shadow-DOM embed architecture |

## 2. Existing Feature Matrix

| Product capability | Status | What is actually true |
|---|---|---|
| Signup | COMPLETE | Creates user, organization, owner membership, free subscription |
| Login/logout/refresh | PARTIAL | Core works; refresh race and access-token revocation gaps remain |
| Password change | PARTIAL | Works but does not revoke other sessions |
| Password reset/email verification/MFA | MISSING | No implementation found |
| Profile and preferences | PARTIAL | Stored and editable; notification preferences have no delivery subsystem |
| Multiple organizations | COMPLETE | Memberships and organization selection exist |
| Roles and permissions | PARTIAL | Enforced server-side, but role order and frontend role representation are inconsistent |
| Team invitations | PARTIAL | Token workflow exists; no email delivery |
| Bot list/view/delete | COMPLETE | Connected for organization-scoped bots |
| Bot create | PARTIAL | Basic fields work; null organization is allowed and advanced fields are discarded |
| Bot edit/save | BROKEN | UI claims to edit fields that are not sent |
| Bot duplicate | PARTIAL | Deep synchronous copy exists; copies BYOK key and incomplete version metadata |
| Bot status/activation | BROKEN | UI field does not persist and public routes ignore status |
| Model/provider selection | PARTIAL | Backend supports four providers; frontend types and provider defaults are inconsistent |
| BYOK | PARTIAL | Works at backend, but keys are plaintext and switching back to platform mode fails in UI |
| Platform-managed keys | PARTIAL | Encrypted pool/allocation exists; allocation errors are swallowed |
| System/business instructions | COMPLETE | Sent and used |
| Tone/personality | BROKEN | Backend supports tone; main frontend client does not persist it |
| Capabilities | BROKEN | UI toggles do not persist; web_search toggle does not perform web search |
| Welcome message | COMPLETE | Basic builder path persists and widget uses it |
| Suggested questions | MISSING | Widget hardcodes generic starters; no bot setting or API contract |
| Widget customization | BROKEN | Customizer calls update with fields that bot-service drops |
| Widget embed | PARTIAL | Script embed works; origin controls, links, retry, and richer rendering are absent |
| Hosted/iframe chat | BROKEN | Generated route /public/chat/{bot} does not exist in Next.js |
| File upload | PARTIAL | PDF/TXT/DOCX work; UI falsely accepts CSV/XLSX/MD |
| Website deep crawl | PARTIAL | Backend works, UI exposes only coarse status and no coverage/failure detail |
| Crawl progress/cancel | PARTIAL | Backend endpoints exist; UI does not use them and cancel is cooperative only |
| Re-crawl/version promotion | PARTIAL | Reindex exists; old chunks are deleted before success |
| Knowledge deletion | PARTIAL | DB rows delete; uploaded file is left on disk |
| Retrieval and grounded chat | PARTIAL | Strong core; cache, streaming, fallback-vector, and strict-grounding gaps remain |
| Sources and CTA metadata | PARTIAL | Returned by non-stream API; streaming/widget do not render clickable sources |
| Dashboard playground chat | BROKEN | Runtime NameError in every authenticated chat route |
| Conversation inbox | PARTIAL | Rich CRUD UI exists; no pagination, bulk export omits messages, PDF export is unsafe |
| Public conversation sharing | BROKEN | Backend works; frontend dynamic route directory is malformed |
| Analytics | PARTIAL | Real session/message data exists, but several derived metrics are mislabeled or heuristic |
| Billing plans/subscription records | PARTIAL | Free plan and data model exist |
| Checkout/payment/portal | MISSING | Provider explicitly returns not_configured; no Stripe/payment code |
| Plan enforcement | PARTIAL | Several quotas work, but checks are non-atomic and deep crawls bypass document count |
| Integrations | NOT APPLICABLE | No integration system is promised by the active product; README claims are stale |
| Notifications/email | MISSING | No delivery service found |
| Platform admin key management | PARTIAL | Backend and UI exist; bootstrap/admin UX and operational controls need hardening |
| Health/readiness | BROKEN | /health always claims database connected |
| Production job workers | BROKEN | Not deployed or dispatched |
| Frontend UI/E2E tests | MISSING | No test runner, test dependencies, or UI tests |

## 3. Backend Gaps

### CRITICAL

1. Null-organization objects bypass authorization. Bot creation accepts organization_id=None and skips both role and plan checks. Bot lookup performs authentication and role checks only when bot.organization_id is truthy. Knowledge helpers follow the same pattern and use optional authentication. An authenticated user can create a bot that disappears from their normal list; any user—or for knowledge endpoints, an unauthenticated caller—who learns the IDs can read or mutate it. Evidence: backend/services/bot_service.py:95-103, 126-145; backend/routes/knowledge_routes.py:27-46, 75-220.

2. All authenticated/playground chat endpoints reference an undefined name. chat_routes.py imports enforce_rate_limit but not ensure_can_send_message, then calls the missing symbol at lines 24, 53, 93, and 143. The result is a runtime 500 before RAG executes. Python syntax parsing and TypeScript checking cannot detect this. Evidence: backend/routes/chat_routes.py:1-24, 53, 93, 143.

### HIGH

3. Public bot status is not enforced. get_public_bot_or_404 selects by ID only, so draft/disabled bots still expose config and chat. Evidence: backend/routes/public_routes.py:22-31.

4. ARQ is disconnected. queue_service defines create_pool, then never calls it in dispatch; dispatched_to_redis is unused and both dispatch branches contain pass. Work is always attached to the API process as BackgroundTasks. Evidence: backend/services/queue_service.py:19-31, 82-97.

5. Knowledge replacement is not zero-downtime. Existing chunks are deleted and committed before new embeddings are safely complete. Reindex does the same. A provider or worker failure can remove previously working knowledge or expose a partial corpus. Evidence: backend/services/document_processing_service.py:400-440, 539-580; backend/routes/knowledge_routes.py:173-185.

6. Semantic caching is context-unsafe. TenantSafeCache keys include org, bot, knowledge version, model, and normalized question, but omit conversation history, system prompt, tone, capabilities, and provider mode. A context-dependent follow-up can reuse an answer produced for another conversation with the same question. The synchronous path also reads nonexistent bot.llm_model and therefore usually keys the model as default. Evidence: backend/services/tenant_cache_service.py:38-52; backend/services/rag_service.py:1287-1297.

7. Streaming bypasses centralized LLM resilience. Synchronous generation uses execute_with_resilience with circuit breaking, bounded retries, and a distributed concurrency guard. generate_stream invokes the provider directly. The user-facing widget therefore takes the less reliable path. Evidence: backend/services/llm_router.py:84, 129, 142-176; backend/services/llm_client.py:189-274.

8. Billing webhook has no authentication or signature verification and reflects the supplied payload. Evidence: backend/routes/billing_routes.py:44-47; backend/services/billing_service.py:105-112.

9. BYOK secrets are plaintext. Bot.provider_api_key is a Text column, while the separate platform-key pool has encryption machinery. Evidence: backend/database/models.py:179-201, 412-468.

### MEDIUM

10. Embedding failures silently become deterministic vectors and are stored as success. This keeps development flows alive but can mix unrelated vector spaces when credentials, providers, or network conditions change. The cache key also uses the requested provider value, which is often None, rather than effective provider/model/org. Evidence: backend/services/embedding_service.py:31-32, 127-149, 177-232.

11. Public streaming skips the explicit public_chat rate limiter. Non-stream invokes enforce_rate_limit at lines 66-71; stream starts at line 114 and proceeds directly to the usage check. The global IP limiter remains, but tenant/bot quota behavior differs by transport. Evidence: backend/routes/public_routes.py:65-72, 114-123.

12. Usage enforcement is check-then-record rather than atomic. Concurrent requests can all pass a limit before any records usage. Deep crawling checks one initial document but can create many per-page Documents, bypassing max_documents. Remote documents have no file size, so crawled corpus storage is not counted. Evidence: backend/routes/public_routes.py:72-105, 121-169; backend/routes/knowledge_routes.py:118-129; backend/services/document_processing_service.py:342-478.

13. Cancellation does not cancel work. It updates the IngestionJob state, while blocking crawl/extraction/embedding continues. Workers check state only at coarse boundaries. Evidence: backend/services/queue_service.py:146-169; backend/workers/crawl_worker.py.

14. Crawl audit data is discarded. crawl_website_with_audit computes failure reasons, discovered links, pages, and max depth, while the active wrapper returns pages only. document_processing_service hardcodes pages_failed and duplicate values and does not persist the coverage manifest. Evidence: backend/services/firecrawl_service.py:417-460; backend/services/document_processing_service.py:477-519.

15. Active-crawl/version semantics are incomplete. website.active_crawl_id is switched before successful processing; retrieval filters ready rows but not the active crawl; stale pages absent from a later crawl are never retired. Partial commits can be retrieved. Evidence: backend/services/document_processing_service.py:287-305, 381-478, 606; backend/services/rag_service.py:443-494.

16. Lexical retrieval uses broad ILIKE expressions across chunk text/title/filename rather than indexed PostgreSQL full-text search. This can become an expensive full scan as tenant corpora grow. Evidence: backend/services/rag_service.py:472-529.

17. Public chat sessions trust a client-supplied session_id. A guessed or deliberately reused value merges visitor conversations; no server-issued session credential binds a visitor to a transcript. Evidence: backend/schemas/schemas.py:196-201; backend/routes/public_routes.py:74-105.

18. Bot clone is synchronous and potentially huge. It copies every document and chunk in the request, including plaintext BYOK credentials, but omits parts of website/crawl/version and embedding metadata. Evidence: backend/services/bot_service.py:263-340.

19. Platform-key allocation errors are swallowed after bot commit. Bot create/update/clone can appear successful but lack a usable model key. Evidence: backend/services/bot_service.py:150-157, 234-240, 292-298.

20. Conversation list/export operations are unpaginated. Export returns session metadata only, not transcripts, despite the UI presenting conversation export. Evidence: backend/routes/conversation_routes.py:21-95, 97-155.

21. Conversation patch accepts an unvalidated JSON body. Status, tags, title, pin state, and shared_token can be arbitrary, including client-chosen token collisions. Evidence: backend/routes/conversation_routes.py:232-291.

22. Uploaded file deletion removes the database record but not file_path from disk. Evidence: backend/routes/knowledge_routes.py:143-158.

23. File validation relies on extension/MIME agreement, not file signatures. Evidence: backend/services/document_processing_service.py:84-96.

24. Message and history schemas lack content/count upper bounds. Only minimum message length and top_k bounds are present, enabling unnecessarily large request bodies and history processing. Evidence: backend/schemas/schemas.py:177-182, 196-201.

25. Database migration is application startup logic. create_all plus hundreds of ALTER/CREATE statements run on boot; errors are logged and startup continues. There is no Alembic history. This makes rollout order, rollback, and schema-state proof weak. Evidence: backend/main.py:32-42; backend/database/connection.py:54-430.

### LOW

26. /health always returns healthy/database connected without probing the database, Redis, queue, Firecrawl, or provider readiness. Evidence: backend/main.py:86-88.

27. CORS defaults to wildcard. This is compatible with a public widget, but it also applies broadly and has no per-bot allowed-origin model. Evidence: backend/main.py:16-19, 63-68.

28. Retrieval cache contains two functions with the same name; the earlier definition is overwritten. Evidence: backend/services/rag_service.py:348-419.

29. Console print statements remain in hot RAG paths, including quota and stream errors. They are not structured, correlated, or consistently sanitized. Evidence: backend/services/rag_service.py:1488-1491, 1525, 1840-1843.

30. README describes Node/Express/GraphQL, omnichannel integrations, port 4000, and files/screenshots that do not exist. The running backend is FastAPI on 8000. Evidence: README.md:48, 64, 90-93, 149-165, 201.

## 4. Frontend Gaps

### CRITICAL

1. Advanced bot settings are silently discarded. createBot sends organization, name, provider/model/key, system prompt, and welcome message only. updateBot sends even fewer. Description, category, avatar, tone, status, capabilities, AI usage mode, and widget_config are not transmitted. Evidence: frontend/services/bot-service.ts:24-60 versus frontend/components/bots/advanced-bot-builder.tsx:35-128.

2. Widget customization never persists through the active edit page. WidgetCustomizer submits snake_case widget_config and welcome_message and displays a success toast; updateBot expects camelCase welcomeMessage and omits widget_config entirely. Evidence: frontend/components/bots/widget-customizer.tsx:24, 107-122; frontend/services/bot-service.ts:49-60.

### HIGH

3. The create flow can send no organization. selectedOrganizationId is loaded asynchronously and createBot converts a falsy value to undefined, directly triggering the backend’s unsafe legacy path. Evidence: frontend/app/bots/create/page.tsx:20-25; frontend/services/bot-service.ts:30.

4. The dashboard playground calls the broken backend chat routes. Both AdvancedBotBuilder and the knowledge playground use /chat/{bot_id}; every route currently fails on the missing backend import. Evidence: frontend/components/bots/advanced-bot-builder.tsx:170-180; frontend/services/chat-service.ts; backend/routes/chat_routes.py:93.

5. Generated deployment artifacts are wrong. Iframe, cURL, and share link snippets use window.location.origin/public/chat/{bot_id}. No frontend page implements that route, and cURL should target API_BASE_URL. Evidence: frontend/components/bots/advanced-bot-builder.tsx:719-729, 773-783, 823-825; frontend/app route inventory.

6. Public conversation sharing is routed through a literal frontend/app/public/share/%5Btoken%5D directory rather than [token]. useParams cannot receive the expected dynamic segment under that structure. Evidence: frontend/app/public/share/%5Btoken%5D/page.tsx:24-33.

7. Switching BYOK back to platform management does not clear the backend key. The UI sets an empty key, while updateBot maps input.providerApiKey || undefined, so the field is omitted instead of explicitly cleared. Evidence: frontend/components/bots/advanced-bot-builder.tsx:49, 80-84, 118-134; frontend/services/bot-service.ts:57.

8. PDF transcript export injects raw conversation content into a new HTML document. User and assistant text are concatenated into markup with no escaping and passed to document.write. A stored transcript can execute HTML/script in the dashboard user’s context. Evidence: frontend/components/inbox/inbox-client.tsx:489-540.

### MEDIUM

9. The knowledge UI advertises CSV, XLSX, and MD although the backend supports PDF, TXT, and DOCX only. Evidence: frontend/components/knowledge/knowledge-bot-client.tsx:33, 74, 168; backend/services/document_processing_service.py:39-44.

10. Bot normalization loses advanced backend fields. BackendBotResponse/normalizeBot do not preserve the complete rich bot response, and the provider type recognizes only Gemini/OpenAI while the builder presents Claude/Grok. Evidence: frontend/types/bot.ts:1-51; frontend/lib/bot-utils.ts:3-44.

11. Provider defaults are invalid for Claude/Grok. Non-Gemini selection defaults to an OpenAI model, which the backend provider/model allowlist rejects. Evidence: frontend/components/bots/advanced-bot-builder.tsx:88-92; backend/services/bot_service.py:16-40.

12. Create setup reports completion after Promise.allSettled regardless of rejected uploads and while accepted ingestion jobs are still processing. Evidence: frontend/app/bots/create/page.tsx:27-42.

13. Top navigation search and notification bell are decorative controls with no useful handler. Evidence: frontend/components/layout/top-navbar.tsx:75-85.

14. Frontend auth hardcodes every user’s role to owner. Organization role is a membership property and can differ per organization. This creates incorrect permission affordances and hides role-specific UX. Evidence: frontend/services/auth-service.ts:15-25, 86-95; frontend/store/auth-store.ts:5-12.

15. Access and refresh tokens are persisted to localStorage. Any successful XSS, including the PDF export issue, can steal both. Evidence: frontend/store/auth-store.ts:34-47.

16. The knowledge screen does not use job status/cancel endpoints. It polls documents on a fixed interval and cannot show stage, true crawl progress, failed pages, coverage, or cancellation state. Evidence: frontend/components/knowledge/knowledge-bot-client.tsx; frontend/store/knowledge-store.ts; backend/routes/knowledge_routes.py:196-226.

17. Billing, usage, and subscription routes all render the same billing view, which only displays plan/usage data and no upgrade action. Evidence: frontend/app/billing/page.tsx, frontend/app/usage/page.tsx, frontend/app/subscription/page.tsx; frontend/components/platform/platform-client.tsx.

18. PlatformClient over-fetches almost the entire organization surface for every view and fails the whole page if primary Promise.all requests fail. It also performs per-bot analytics calls. Evidence: frontend/components/platform/platform-client.tsx:366-405.

19. Conversation lists have no pagination and will progressively degrade. The UI loads and filters the full server response. Evidence: frontend/components/inbox/inbox-client.tsx; backend/routes/conversation_routes.py:21-95.

20. Error handling is inconsistent. Clone only shows success when response.ok and gives no failure feedback; several organization/team actions catch weakly or simply reload. Evidence: frontend/components/bots/advanced-bot-builder.tsx:139-154; frontend/components/platform/platform-client.tsx.

### LOW

21. Dashboard exposes “Backend target” and a local URL as customer-facing copy. Evidence: frontend/components/dashboard/dashboard-home.tsx:136-138.

22. Dashboard suggests uploading PDF/CSV FAQs even though CSV is unsupported. Evidence: frontend/components/dashboard/dashboard-home.tsx:214; backend/services/document_processing_service.py:39.

23. Brand naming is inconsistent: “Chatbot SaaS,” “Antigravity AI,” and generic “Powered by AI” appear across the dashboard, public share page, and widget.

24. The edit tabs are internal component state and do not update URL/deep-link state. Reloading loses the selected configuration section.

25. No frontend test script or test dependency exists. package.json defines dev/build/start/lint/typecheck only.

## 5. Widget Gaps

### What works

- A single script can initialize from data-bot-id and data-api-base-url.
- Shadow DOM limits CSS collisions.
- A UUID-like session ID and transcript are stored per bot/session in sessionStorage.
- The widget sends recent history, prefers SSE streaming, and falls back to non-stream chat.
- It has typing/loading state, close and send labels, responsive mobile fullscreen styling, desktop sizing, and abort-on-close.
- Multiple ordinary visitors receive separate random browser-side session IDs.

### Blocking and material gaps

| Severity | Gap | Evidence/impact |
|---|---|---|
| CRITICAL | No origin authorization | Any site can embed/use any known active or draft bot ID. CORS is wildcard and no bot allowed-domain model exists. backend/main.py:16-19, 63-68; backend/routes/public_routes.py:22-31 |
| HIGH | Draft/disabled bots still work | Public bot lookup checks ID only |
| HIGH | CTA and source links are not clickable | Assistant bubbles use textContent, so Markdown and URLs remain plain text. frontend/public/widget.js:415-419, 461-465 |
| HIGH | Widget settings do not persist | Frontend update contract drops widget_config |
| HIGH | Streaming lacks per-bot route limiter and resilience | Public stream skips explicit limiter; LLM stream bypasses centralized safeguards |
| MEDIUM | Hardcoded suggested questions | Generic starter text is embedded in the script and is not configurable; clicking fills input rather than sending. frontend/public/widget.js:443-458 |
| MEDIUM | No retry control | Network/provider failures produce an error string; there is no retry button or recoverable message action |
| MEDIUM | Aborted turns remain in history | Closing aborts the response after the user message has already been stored, leaving a one-sided turn. frontend/public/widget.js:561-676 |
| MEDIUM | Session identity is spoofable | session_id is supplied by the client and accepted without a server-bound token |
| MEDIUM | No rich rendering | Lists, comparisons, headings, code, and citations lose formatting because all content is textContent |
| MEDIUM | Streaming never exposes source cards | Non-stream ChatResponse has sources/retrieved_chunks; the SSE protocol sends token/done only |
| LOW | Storage is tab-scoped | sessionStorage survives navigation in the tab but not browser restarts and is not synchronized across tabs |
| LOW | Branding is fixed/inconsistent | “Powered by AI” has no verified tenant-controlled setting |
| LOW | Launcher accessibility is incomplete | Close/send have aria-labels; the primary launcher has no equivalent explicit label |

The raw script embed path can be demonstrated today, but “safely embedded” is not yet true because tenant-approved origins, status enforcement, secret handling, clickable grounded CTAs, and reliable stream behavior are not complete.

## 6. RAG / Chat Quality Gaps

### Strengths that should be preserved

- Query-aware FACTUAL, ENTITY, CATALOG, FILTER, COMPARISON, POLICY, and PURCHASE retrieval.
- Conversation-history-based pronoun resolution and query rewriting.
- Vector plus lexical candidate retrieval and RRF.
- Sibling and cross-page expansion for entity/catalog/policy synthesis.
- Context budgets separated from answer-size instructions.
- Prompts explicitly ask for real names, balanced comparisons, honest missing-information behavior, canonical purchase/navigation URLs, and no fabricated CTA.
- Synchronous critique flags hallucination, grounding, and missing-business-information issues before conditional verification/polish.
- The test corpus targets catalog completeness, comparisons, CTA grounding, follow-ups, missing information, injection, tenant isolation, and scale.

### Quality risks

1. The customer-facing streaming path skips critique, verification, and polish. A result that would be repaired in non-stream mode is emitted token-by-token without those checks. Evidence: backend/services/rag_service.py:1538-1568, 1647-1675 versus 1690-1988.

2. Context-dependent answers are semantically cached without history. Questions such as “What about its warranty?” can collide across visitors or earlier entities within the same bot. This can create both wrong answers and contextual leakage. Evidence: backend/services/tenant_cache_service.py:38-52.

3. The web_search capability is not web search. It only disables strict grounding when the flag is true; no search provider or retrieval call is connected. Customers can enable a feature that instead permits pretrained, ungrounded model answers. Evidence: backend/services/rag_service.py:1322-1331, 1731-1740; no active web-search service found.

4. Deterministic fallback embeddings can mix with real embeddings. Retrieval scores then become semantically meaningless while rows still look ready.

5. Retrieval version selection is advisory, not corpus-isolating. The semantic cache version may advance, while SQL retrieval still selects all ready document/chunk rows rather than the promoted active crawl.

6. Streaming loses sources. Even when retrieval found canonical URLs, the widget receives only text tokens and cannot render verified source/CTA objects.

7. CTA extraction/grounding is backend metadata, not an end-to-end experience. Relative/complex links may be missed depending on Firecrawl markdown, and the final widget cannot make any returned link interactive.

8. Strict-grounding behavior is inconsistent. When a bot has sources, the strict branch attempts generation even with “No relevant business information”; retrieval exceptions can be swallowed and still lead to generation. Trace fields can mark retrieval used even when no useful evidence was returned.

9. Lexical ILIKE matching is recall-friendly but can be noisy for broad catalog queries and expensive at scale. It is not language-aware full-text ranking.

10. get_active_knowledge_version takes the latest ready website crawl or max document version, but uploaded document versions are not meaningfully advanced. A mixed website/file corpus does not have a single reliable atomic version.

11. The synchronous pipeline polishes only when critique requests verification. The stated four-stage name should not be interpreted as four unconditional passes.

12. generate_proactive_followups is imported but unused, so the UI cannot surface model-generated follow-up suggestions. Evidence: backend/services/rag_service.py:15; backend/services/conversational_engine.py:321.

13. The dashboard non-stream route returns internal _debug intent, confidence, cache, and timing details to ordinary authenticated users. This is useful in development but not a polished customer contract. Evidence: backend/routes/chat_routes.py:122-129.

### Expected behavior by question class

| Question class | Code-path expectation | Primary remaining failure mode |
|---|---|---|
| Narrow fact | Focused vector/lexical retrieval | Mixed/fallback embeddings or stale partial version |
| Detailed question | Larger context and synthesis | Streaming skips verification |
| Catalog/service list | CATALOG mode and breadth expansion | Crawl max-page/stale-page gaps can make list incomplete |
| Comparison | COMPARISON mode and balanced prompt | Widget loses comparison formatting |
| Filter/recommendation | FILTER mode | Available attributes depend on extraction quality; no structured facet guarantee |
| Policy | POLICY/cross-page synthesis | Old and new crawl pages can coexist |
| Purchase/navigation | PURCHASE plus canonical/CTA metadata | Final links are plain text and sources absent in stream |
| Pronoun follow-up | History rewrite and memory | Semantic cache omits history |
| Unknown information | Strict grounding and fallback | web_search toggle disables strictness without actual search |
| Broad business question | Cross-page retrieval | Default crawl cap and no customer-visible coverage proof |

## 7. Authentication / Tenant Gaps

### CRITICAL

- Null organization authorization bypass, described in Sections 3 and 11.

### HIGH

- The frontend represents every user as role owner after login/register/refresh, while backend permissions are per-organization. This can show controls a user cannot execute and conceal real membership context.
- JWT access and refresh tokens are in localStorage. Combined with the transcript export injection, this turns a UI content bug into account takeover risk.
- Public bot usage has no tenant-configured allowed-origin boundary and no server-issued session credential.

### MEDIUM

- Refresh rotation is not row-locked. Two simultaneous refreshes can both find the same unrevoked session before either commits, weakening one-time rotation. Evidence: backend/services/auth_service.py:103-125.
- Password change validates and replaces the password but does not revoke active refresh sessions. Evidence: backend/routes/auth_routes.py:43-54 versus session endpoints at 58-91.
- Revoking refresh sessions does not revoke already-issued access tokens; no access-token jti/session lookup exists.
- The first registered user becomes platform admin through count()==0. Concurrent first registrations can race, and an accidentally exposed empty deployment grants admin to the first visitor. Evidence: backend/routes/auth_routes.py:98-112.
- JWT falls back to dev-change-me-before-production outside the explicit production guard. A misclassified environment can run with a known secret. Evidence: backend/services/auth_service.py:18; backend/main.py:22-27.
- ROLE_ORDER puts member above editor. A member satisfies endpoints requiring editor, which conflicts with ordinary role semantics and frontend expectations. Evidence: backend/services/organization_service.py:11, 85-91.
- Invitation tokens are generated and accepted, but no email delivery exists; administrators must copy tokens manually.
- No password reset, email verification, MFA, suspicious-login notification, or account recovery path exists.

### What is correctly scoped

For non-null organization rows, most organization, bot, analytics, billing, conversation, and knowledge operations call require_org_role or derive organization-scoped queries. RAG retrieval itself filters by bot_id and is covered by dedicated isolation tests. The critical conclusion is not that tenancy is absent; it is that the nullable legacy branch invalidates the guarantee.

## 8. Knowledge Management Gaps

### Backend capability not fully exposed

- IngestionJob status and cancellation endpoints exist, but the frontend does not consume them.
- Website, WebsiteCrawl, canonical URL, content hash, depth, status, version, first/last seen, and active_crawl_id fields exist, but the UI shows a flat Document list.
- Firecrawl computes a coverage audit/manifest, but the active wrapper drops it and there is no UI for discovered, crawled, skipped, failed, duplicate, or stale URLs.
- Backend can deep-crawl multiple pages; the customer copy says “page” and provides no scope preview.

### Correctness and lifecycle gaps

1. Reindex deletes working chunks before replacement succeeds.
2. Website active_crawl_id changes before full success.
3. Each page is committed independently, so partial crawl results are queryable.
4. Pages missing from a subsequent crawl are not marked stale/removed.
5. Unchanged pages can be reassigned to a new crawl without a truly atomic corpus promotion.
6. Crawl version, Document.version, and retrieval-ready status do not form a single enforceable knowledge snapshot.
7. File deletion leaves physical files behind.
8. Upload MIME checking does not inspect magic bytes.
9. PDF extraction has no OCR; scanned PDFs will produce weak/empty knowledge.
10. DOCX extraction focuses on paragraphs and does not prove table/header/footer coverage.
11. Website page embeddings are generated page/chunk at a time and omit organization_id in calls, reducing batching and tenant-aware concurrency behavior.
12. Stored embedding_provider/model fields are hardcoded to Gemini identifiers even when effective configuration/fallback differs.
13. Crawl job result fields such as pages_failed and duplicates_removed are hardcoded or incomplete.
14. Firecrawl polling uses blocking time.sleep for up to the crawl timeout inside an API-process background task.
15. Default crawl limits of 20 pages and depth 2 can silently under-cover larger customer sites without a surfaced coverage warning.

### Frontend gaps

- CSV/XLSX/Markdown are advertised but rejected.
- Upload progress is locally simulated/coarse rather than tied to server stages.
- No failed-page list, retry-page action, recrawl diff, stale-page control, version history, coverage percentage, or active-version indicator.
- No server-backed progress/cancel control.
- Setup completion can be announced despite rejected uploads or pending indexing.
- Source URLs and chunk counts are visible, but there is no explanation of what “ready,” “processing,” and partial crawl status guarantee.

## 9. Analytics Gaps

### Real data path

Public widget chat creates/updates ConversationSession and ConversationMessage records through analytics_service. Records include user message, assistant response, status, fallback flag, knowledge-hit flag, latency, optional token usage, organization, bot, channel, and session. Organization analytics endpoints query those tables and Documents, and the dashboard consumes their response.

Evidence: backend/services/analytics_service.py:14-101; backend/routes/public_routes.py:90-105, 140-169; backend/routes/analytics_routes.py.

### Misleading or incomplete metrics

| Metric/feature | Assessment |
|---|---|
| Total conversations/messages | Real database counts |
| Unique visitors | Actually session count, not a deduplicated visitor identity |
| Resolution rate | Derived from manually set session status; defaults to 100% when there are zero conversations |
| RAG/knowledge hit rate | Based on trace.used_retrieval/had_knowledge_hit, which can be true for empty or failed retrieval |
| User activity score | Heuristic formula, not a measured product event |
| Top questions | Recent distinct questions via set, not frequency-ranked questions |
| Knowledge gaps | Generated from fallback recency with generic templated language; “no gaps” is also hardcoded text |
| Suggested improvements | Generic static suggestions, not evidence-ranked recommendations |
| Top documents | Reflects corpus/chunk volume rather than customer engagement or citation usage |
| Token/provider cost | Schema permits token_usage, but main flows do not reliably record provider token/cost data |
| Dashboard playground activity | Not persisted through the same public analytics path |
| BotAnalyticsDaily | Model exists but has no active reads/writes |
| Operational activity feed | Dashboard repackages recent questions/gaps as events; it is not AuditLog activity |

Evidence: backend/routes/analytics_routes.py:46, 95-107, 121, 187-211; backend/database/models.py:377-399.

The analytics UI is not wholly fake, but labels need to distinguish measured counts from heuristics and proxies. Today, several cards look more authoritative than their source data warrants.

## 10. Billing / Usage Gaps

| Capability | Status | Evidence-based assessment |
|---|---|---|
| Plan catalog | COMPLETE | Free/Pro/Business defaults with limits and prices are created |
| Subscription model | PARTIAL | One subscription per organization; new orgs default to free |
| Bot limit | PARTIAL | Enforced for organization-scoped creates; bypassed by null-org create and check/record races |
| Document limit | PARTIAL | Checked at upload/crawl start; one deep crawl can create many documents after one check |
| Storage limit | PARTIAL | Uploaded file bytes tracked; remote website corpus is not meaningfully counted |
| Monthly message limit | PARTIAL | Public chat checks/records; concurrency can overshoot and dashboard chat is broken/not recorded |
| Team-member limit | PARTIAL | Service enforcement exists |
| Crawl limit | PARTIAL | Rate limiting and document quota are proxies; no distinct monthly crawl/page budget |
| API usage limit | MISSING | No commercial API-call/token quota model |
| Embedding/LLM token usage | MISSING | Not reliably metered into billing usage |
| Usage dashboard | PARTIAL | Shows counts, but “Documents” is an event counter and can diverge from current resources |
| Payment provider/Stripe | INTENTIONALLY DEFERRED | No SDK/config/client found; BillingProvider is explicitly not_configured |
| Checkout | INTENTIONALLY DEFERRED | create_checkout_session returns status not_configured and has no active route/UI |
| Billing portal | INTENTIONALLY DEFERRED | No implementation found |
| Webhook handling | BROKEN | Public unsigned endpoint echoes payload and reports handled=False |
| Upgrade/downgrade/cancel | MISSING | No customer action or lifecycle |
| Invoice/payment history | MISSING | No implementation |

Evidence: backend/services/billing_service.py:8-112; backend/routes/billing_routes.py:16-47; backend/services/usage_service.py; frontend/components/platform/platform-client.tsx.

The repository has a useful entitlement skeleton but no revenue collection loop. Calling it “billing” in the current dashboard is acceptable only if clearly labeled as plan/usage preview; it is not a functioning paid subscription system.

## 11. Security / Reliability Gaps

### CRITICAL

1. Cross-tenant/unauthenticated access to null-organization bots and knowledge.

### HIGH

2. Stored HTML/script execution through PDF transcript export, amplified by localStorage tokens.
3. Plaintext provider API keys.
4. Unsigned public billing webhook.
5. Public access ignores bot status and allowed origins.
6. In-process long-running ingestion has no durable queue guarantee. API restart loses active BackgroundTasks.
7. Working knowledge is deleted before replacement succeeds.

### MEDIUM

8. Known development JWT default if environment classification is wrong.
9. Refresh-token rotation race and incomplete session revocation.
10. Client-selected public session IDs can merge transcripts.
11. File-type validation lacks signature checks.
12. SSRF defenses resolve and reject private IPs at validation time, but the repository does not prove redirect/DNS-rebinding enforcement across the external Firecrawl fetch chain. Firecrawl is external, which reduces direct server fetch exposure, but the trust boundary should be documented. Evidence: backend/services/firecrawl_service.py:167-201.
13. CORS wildcard applies to the whole API, not only public widget routes.
14. Public usage checks are non-atomic; streaming has inconsistent limiter behavior.
15. Deterministic embedding fallback fails open and can silently damage knowledge quality.
16. Semantic cache omits history/configuration.
17. In-memory cache and circuit state diverge across multiple API workers; Redis support is optional and Compose omits Redis.
18. /health produces false-positive readiness.
19. Startup migration catches errors and continues, allowing the app to serve against a partially migrated schema.
20. Fixed IVFFlat lists=100 is created at startup without corpus-size tuning/analyze workflow. It may be poor for small or large deployments. Evidence: backend/database/connection.py:436-445.
21. No documented backup/restore/deployment migration process. A standalone backup_db.py writes a local JSON backup and is not a production recovery system.

### Reliability positives

- DB pool pre-ping, bounded size/overflow, and status metrics exist.
- LLM synchronous generation has error classification, retries, a circuit breaker, and distributed concurrency guard.
- Redis rate-limit code has in-memory fallback and dedicated tests.
- Job state transitions, heartbeat/recovery concepts, and tenant checks exist in worker code.
- URL validation rejects private, loopback, link-local, multicast, and reserved addresses.

These controls should be connected and made consistent rather than replaced.

## 12. UX Problems

### “What can a paying customer click that does not work?”

1. Save advanced assistant configuration: success can be shown while most fields are discarded.
2. Save widget customization: success toast, no persisted widget configuration.
3. Test bot in builder/knowledge playground: backend runtime 500.
4. Copy iframe embed: points to a nonexistent page.
5. Copy cURL command: points to the frontend origin rather than API.
6. Copy public bot share link: points to the same nonexistent page.
7. Open a shared conversation: frontend dynamic route is malformed.
8. Switch BYOK to platform AI: old key remains.
9. Select Claude/Grok and accept default model: likely backend validation failure.
10. Upload CSV/XLSX/Markdown: frontend accepts, backend rejects.
11. Search from top navbar: decorative.
12. Open notifications: bell has no action or notification system.
13. Upgrade/manage subscription: no checkout or portal action.
14. View usage vs subscription vs billing: three navigation destinations show the same screen.
15. Cancel a crawl or view failed pages: backend capability is not surfaced.

### Confusing or unfinished experiences

- Bot creation can race organization selection and create an invisible bot.
- “Setup Complete” is shown before ingestion completion and despite individual upload rejection.
- “Web Search” sounds like live search but merely relaxes grounding.
- Bot “Draft” sounds private but remains public.
- Widget displays raw Markdown/URLs as text, undermining the promise of CTA grounding.
- Knowledge UI says “page” while backend may crawl a website; users cannot see exact scope.
- Dashboard surfaces a backend target URL and developer-oriented status copy.
- CSV is repeatedly advertised despite lack of support.
- Analytics terms such as unique visitors, resolution, top questions, and activity score overstate what is measured.
- Organization controls are not consistently role-gated in the UI, so lower-role users encounter backend denials.
- Brand identity changes between Chatbot SaaS, Antigravity AI, and generic AI.
- Empty/error/loading states exist in many major pages, but PlatformClient’s broad Promise.all makes unrelated failures blank entire views.
- Long bot clone and conversation duplicate actions have no progress model.
- No onboarding check verifies: organization selected → bot active → knowledge ready → test passed → widget installed on an allowed domain.

## 13. Dead / Disconnected Features

### Backend exists but is unavailable or materially hidden in frontend

| Backend capability | Disconnection |
|---|---|
| Job status and cancel endpoints | Knowledge UI polls documents only |
| Website/Crawl version and coverage metadata | Flat document UI; audit report discarded |
| Claude and Grok model support | Frontend core types normalize providers to Gemini/OpenAI behavior |
| Bot description/category/avatar/tone/status/capabilities/widget_config | Advanced UI exists but API client drops fields |
| Public non-stream sources/retrieved chunks | Widget uses stream and renders text only |
| Conversation share backend | Frontend route folder malformed |
| Platform-key allocation/admin | UI exists but operational path is fragile and errors are swallowed |
| AuditLog model | No customer-facing operational activity; dashboard fabricates activity-like rows from analytics |
| Usage job progress data | No stage/progress UI |
| Profile notification preferences | No email/in-app notification delivery |

### Frontend exists without a working backend/product path

| Frontend feature | Disconnection |
|---|---|
| Web Search toggle | No web-search provider; disables strict grounding |
| CSV/XLSX/Markdown upload | Backend rejects formats |
| Hosted iframe/public bot chat | No Next.js page route |
| Billing upgrade experience | BillingProvider is placeholder |
| Search and notification controls | No handlers/services |
| Suggested questions customization expectation | Widget starters are hardcoded |
| Advanced bot fields | Not transmitted |

### Dead or legacy code

- backend/services/crawl4ai_service.py is used by tests/demos, not the active knowledge processor, which imports Firecrawl. Several test names and comments therefore describe a superseded path.
- backend/static/widget.js is not mounted by backend/main.py; frontend/public/widget.js is the active widget.
- backend/routes/chat.py, customer.py, knowledge.py, and upload.py are not mounted; similarly named *_routes.py files are active.
- backend/services/scraper_service.py remains active only through the legacy /ingest/website path, separate from the modern knowledge/Firecrawl/job flow.
- backend/services/ai_service.py and portions of the legacy database/model stack appear superseded by provider routing and database/models.py.
- BotAnalyticsDaily is defined but unused.
- generate_proactive_followups is implemented/imported but not called.
- frontend/components/settings/settings-client.tsx is not routed; Settings uses PlatformClient.
- frontend/components/bots/bot-form.tsx and EmbedSnippetCard are superseded by AdvancedBotBuilder.
- The first retrieve_relevant_chunks_cached definition is overwritten by a second definition.
- dispatched_to_redis is assigned but never used.
- README claims Slack, Teams, WhatsApp, GraphQL, docs, screenshots, and LICENSE assets that are absent from the active repository.

Dead-code labels are based on repository references and active entry points, not file names alone.

## 14. Test Coverage Gaps

### What the repository does test

| Test class | Examples | Assessment |
|---|---|---|
| Unit/algorithm tests | test_rag_pipeline.py, intent/retrieval/chunking assertions | Valuable for retrieval behavior |
| Mocked service tests | Firecrawl acceptance, ARQ/job, production platform, resilience suites | Broad, but mocks do not prove live wiring |
| Database integration-style tests | tenant cache, job state, security suites | Valuable if run against compatible PostgreSQL/pgvector |
| Live API scripts | verify_saas.py, verify_phase5e_acceptance.py, test_phase5c.py, test_phase5d.py | Require a running backend and seeded/environment-specific state |
| Live external crawl tests | IKEA, Crawl4AI real site, Firecrawl tests | Environment/network/provider dependent |
| Load/concurrency tests | production_load, production_concurrency, real_world_stress | Useful harnesses; not evidence they pass in the audited deployment |
| Security tests | phase11 security, prompt-injection and tenant suites | Strong themes, but do not cover null-organization authorization |
| RAG quality benchmarks | 50-query/customer readiness, Phase 9, CTA, follow-up suites | Substantial coverage of the strongest subsystem |

### Why current tests did not prevent the top failures

- No route smoke test imports/calls every mounted FastAPI endpoint. Such a test would catch the undefined ensure_can_send_message name.
- No frontend/backend bot contract test verifies every editable field round-trips through create/get/update.
- No UI/E2E framework exists. There are no Playwright/Cypress/Vitest/Jest dependencies or test scripts in frontend/package.json.
- Several “ARQ” tests call worker/state functions directly and therefore do not prove queue dispatch or a running Redis worker.
- Crawl4AI-focused tests exercise a service that is not the active Firecrawl ingestion path.
- Mocked Firecrawl tests prove parser/processor behavior under fixtures, not credentials, asynchronous API polling, quotas, redirect behavior, or live page variability.
- Live scripts are standalone and environment-dependent rather than a deterministic CI acceptance gate.

### Missing high-value tests

1. Unauthenticated and cross-tenant access to null-organization bot/knowledge IDs.
2. Attempt to create a bot without selected organization.
3. Mounted API route smoke test for all four /chat endpoints.
4. Draft/deactivated bot cannot fetch widget config or chat.
5. Full bot rich-field create/get/update round trip, including explicit BYOK clear.
6. Widget settings persistence round trip.
7. Supported/unsupported upload format contract shared by frontend/backend.
8. End-to-end signup → org → bot → upload/crawl → job ready → chat → widget.
9. Real ARQ enqueue → Redis → separate worker → completion, plus API restart durability.
10. Atomic recrawl: old corpus remains active until complete new promotion.
11. Failed partial crawl does not expose mixed versions.
12. Semantic cache isolation for identical follow-up text with different histories.
13. Streaming parity for grounding, rate limiting, resilience, and source events.
14. Public origin allowlist and client session collision behavior.
15. Billing webhook signature rejection/replay/idempotency.
16. Concurrent quota enforcement at the exact plan boundary.
17. Transcript PDF export escaping/XSS.
18. Public share page browser navigation.
19. Generated iframe/cURL/embed snippets against actual routes.
20. Conversation list/export pagination and transcript inclusion.
21. Migration from each supported prior schema using an actual migration history.
22. Health/readiness failure when PostgreSQL/Redis/worker is unavailable.
23. Scanned PDF and DOCX table extraction expectations.
24. Frontend role-aware control visibility for viewer/member/editor/admin/owner.
25. Accessibility keyboard/screen-reader test for widget and primary dashboard flows.

## 15. Top 25 Remaining Issues

Ratings: C = customer impact, S = security impact, R = revenue impact, P = production risk. H/M/L are relative. Complexity is estimated implementation complexity, not elapsed calendar time.

| Rank | Issue | Severity | C | S | R | P | Complexity |
|---:|---|---|---|---|---|---|---|
| 1 | Eliminate null-organization bot/knowledge authorization bypass and migrate legacy rows | CRITICAL | H | H | H | H | M |
| 2 | Fix all authenticated/playground chat routes and add route smoke coverage | CRITICAL | H | M | H | H | S |
| 3 | Repair rich bot create/update/read contracts, including widget settings and explicit key clearing | CRITICAL | H | M | H | H | M |
| 4 | Enforce bot active/status and tenant-configured origins on public widget/chat | HIGH | H | H | H | H | M |
| 5 | Make generated iframe, cURL, and public bot links point to real supported routes | HIGH | H | L | H | M | S/M |
| 6 | Fix the public conversation share dynamic route | HIGH | H | L | M | M | S |
| 7 | Replace unsafe transcript PDF HTML construction with escaped rendering | HIGH | M | H | M | H | S |
| 8 | Connect durable Redis/ARQ dispatch, worker deployment, retries, and shutdown semantics | HIGH | H | M | H | H | L |
| 9 | Implement atomic knowledge version promotion and preserve old corpus on failure | HIGH | H | M | H | H | L |
| 10 | Remove conversation-history collisions from semantic cache and include relevant bot config | HIGH | H | M | M | H | M |
| 11 | Bring streaming through equivalent resilience, quota, grounding, and source-event behavior | HIGH | H | M | H | H | L |
| 12 | Encrypt BYOK provider keys and define rotation/redaction handling | HIGH | M | H | H | H | M/L |
| 13 | Make billing webhook private, signed, replay-safe, idempotent—or remove it until provider work begins | HIGH | L | H | H | H | M |
| 14 | Align upload formats; stop advertising unsupported CSV/XLSX/MD until implemented | HIGH | H | L | M | M | S |
| 15 | Render safe Markdown plus verified clickable source/CTA cards in the widget | HIGH | H | M | H | M | M |
| 16 | Replace web_search toggle semantics with a real capability or truthful disabled state | HIGH | H | M | H | M | S/L |
| 17 | Make plan/quota enforcement atomic and count deep-crawl pages/storage accurately | HIGH | M | M | H | H | L |
| 18 | Surface real job progress, failed pages, coverage, cancel, and recrawl lifecycle in UI | MEDIUM | H | L | H | M | L |
| 19 | Stop silent deterministic production embeddings; fail/queue retry with truthful status | HIGH | H | M | H | H | M |
| 20 | Correct frontend membership roles and harden token/session storage/revocation | HIGH | M | H | M | H | L |
| 21 | Replace startup schema mutation with versioned migrations and true readiness checks | HIGH | M | M | H | H | L |
| 22 | Make analytics labels and calculations reflect measured data | MEDIUM | M | L | H | M | M |
| 23 | Add deterministic CI E2E acceptance for the paying-customer golden path | HIGH | H | M | H | H | L |
| 24 | Paginate conversations and export actual transcripts safely | MEDIUM | M | M | M | M | M |
| 25 | Remove/segregate dead legacy paths and correct deployment/README truth | LOW | M | L | M | M | M |

## 16. Recommended Next Phases

No implementation is included in this audit. The smallest sensible sequence is:

### Phase 1 — Security and primary-flow stop-ship repair

- Make organization ownership mandatory for all new bots and knowledge.
- Define a migration/quarantine policy for existing null-organization rows.
- Make every bot/document/job access check fail closed.
- Import/wire usage enforcement correctly in authenticated chat routes.
- Enforce public bot active status.
- Escape transcript export content.
- Disable or protect the unsigned billing webhook.
- Add focused regression tests for each item.

Exit criterion: no known cross-tenant/null-tenant access path; authenticated playground chat works; inactive bots cannot be used publicly.

### Phase 2 — Frontend/backend contract closure

- Establish one typed bot contract and round-trip all supported fields.
- Persist widget config, tone, status, capabilities, avatar/category/description.
- Implement explicit provider-key clear semantics.
- Correct provider/model types and defaults.
- Make organization selection a prerequisite to bot creation.
- Align upload formats and setup completion states.
- Fix conversation-share and generated deployment links.

Exit criterion: every editable control is either persisted and verified after reload or removed/disabled with truthful copy.

### Phase 3 — Durable ingestion and knowledge lifecycle

- Deploy Redis and a separate ARQ worker; connect the actual enqueue call.
- Add durable retries, cancellation semantics, heartbeat/stale recovery, and API restart tests.
- Implement staging plus atomic active-version promotion.
- Persist crawl coverage/failures and retire stale pages deliberately.
- Make embedding failure truthful; record actual provider/model/version.
- Clean up physical uploaded files safely.

Exit criterion: old knowledge remains available through failed ingestion; job progress survives API restarts; customers can understand exactly what was indexed.

### Phase 4 — Widget and chat production parity

- Add per-bot approved origins and a documented public authentication/session strategy.
- Unify stream/non-stream rate limits, resilience, trace semantics, and source delivery.
- Make semantic caching history/config safe.
- Render sanitized Markdown and verified clickable source/CTA cards.
- Add retry UX, configurable suggested questions, and accessibility coverage.
- Clarify or implement web search.

Exit criterion: the same grounded answer quality and safeguards apply in the real embedded widget as in internal non-stream evaluation.

### Phase 5 — Commercial controls and trustworthy analytics

- Make quota counters atomic and complete for messages, crawl pages, storage, embeddings, and provider usage.
- Rename or rebuild heuristic analytics so every metric has a documented event/query definition.
- Decide whether to implement a payment provider; if yes, add signed/idempotent webhooks, checkout, portal, lifecycle, and invoices. If not, label billing as deferred.
- Add audit/customer activity where the UI claims operational events.

Exit criterion: plan enforcement is reliable under concurrency, dashboard metrics can be reconciled to source events, and the paid-plan lifecycle is either functional or explicitly absent.

### Phase 6 — Production gate and repository consolidation

- Add deterministic browser E2E for signup through external widget embed.
- Add mounted-route, migration, readiness, security, load, and failure-injection CI gates.
- Separate mocked, integration, live-provider, and load suites with explicit prerequisites.
- Remove or archive superseded Crawl4AI, legacy routes/services/widget, duplicate components, and overwritten functions after usage proof.
- Replace startup mutations with versioned migrations.
- Update README, deployment topology, ports, supported formats/providers, and operational runbooks.

Exit criterion: a clean environment can be deployed from documented steps, passes the golden path and failure gates, and contains one clearly active implementation for each subsystem.

## Final verdict

The repository’s RAG core is the product’s strongest asset and should be retained. The current risk is not lack of sophisticated retrieval; it is lack of trustworthy end-to-end closure. Tenant fail-closed behavior, bot setting persistence, playground/runtime wiring, public status/origin enforcement, durable jobs, atomic knowledge promotion, safe widget rendering, and real acceptance tests are prerequisites to calling the application production-ready.

Until Phases 1-3 are complete, the product should be treated as an advanced development/pre-production system, not a generally available multi-tenant SaaS.
