# Native RAGFlow + combined ranking integration

The SaaS answer path uses native RAGFlow search, the tested BGE combination method and whole source passages. The earlier PostgreSQL candidate adapter is replaced. The existing bot-selected provider implementation is unchanged. Gemini remains the intended production configuration; temporary Codex-assisted validation does not replace that implementation. Codex callbacks, saved answers and question-specific plans are outside the repository and are not deployment code.

## Operational status — 2026-09-30

The destination Chatbot-SaaS Railway project now runs the native RAGFlow service and its dependencies, the pinned BGE service, and the SaaS API/worker candidate. The existing WOWMD corpus was copied and adopted with verified source and manifest identities: 23 documents and 413 native chunks. The API readiness check reports ready and the worker is active.

The deployed eight-case widget validation completed: all eight authored answers were delivered and persisted, with one consumed quota reservation per turn. The original Gemini bot configuration is restored. Approved obsolete SaaS records were removed after a fresh verified backup; current knowledge, credentials and the latest eight conversations were preserved. A successful readiness response confirms dependency availability; it does not establish answer quality or concurrent capacity.

## Request flow

1. The existing widget authenticates its session; the existing SaaS routes load the bot/history and reserve the message quota.
2. PostgreSQL supplies the bot's authorized, current document versions. Every current ready document must have a matching native binding; a partial migration fails explicitly rather than silently omitting knowledge.
3. Follow-up rewriting and focused-query planning use the existing bot/provider router. Focus queries cannot supply document IDs or change ownership.
4. Native RAGFlow W128 search runs on the original question and focused queries: BGE-small embeddings, Elasticsearch, threshold 0.1, vector weight 0.3, KNN top_k 1024 / candidates 2048. Native parent expansion precedes BGE.
5. The pinned BGE v2-m3 cross-encoder scores the first 32 full title/content pairs per focused query. The pinned LangChain round-robin merger interleaves lanes, deduplicates source identities, then retains the original/focused native tails.
6. A prefix of complete passages fits within 4,000 actual cl100k source tokens and the 65,536-character application envelope. No passage is clipped, keyword-compressed or supplemented with an expected answer.
7. The existing bot-selected Gemini provider receives the question, conversation, complete evidence and existing business instructions. The answer path checks source authority again and validates links, then returns through the existing SSE, persistence and quota flow.

The retired answer function, old final evidence reviewer/compressor and PG candidate adapter are not called by this path. Older low-level helpers still used elsewhere in the repository remain. No automatic fallback can silently substitute the old retrieval policy. Existing-answer cache entries are not reused.

A planner failure can use the original query with BGE and is explicitly marked degraded. A native/BGE integrity or availability failure returns a technical failure. Supplying verified evidence is not a proof of semantic answer correctness; the trace does not assert that it is.

## Knowledge lifecycle

Four knowledge-only tables mirror native datasets, versioned document bindings, complete source chunks and a deletion outbox. Migration head is `20260928_01`. Accounts, bots, provider credentials, subscriptions, Redis and message quotas keep their existing roles.

The existing upload/crawl jobs call official native dataset/upload/parse APIs. Parsing uses the tested 512-token naive configuration, DeepDOC layout, no generated keywords/questions and no parent-child/RAPTOR/GraphRAG expansion at ingestion. New manifests remain staged until the complete document/crawl is ready. Promotion is atomic; parse failure keeps the preceding active version. Parse polling maintains the existing job heartbeat. Removed pages and retired versions enter durable cleanup.

A bot clone queues its own native ingestion. Website page copies are independent text snapshots with their original URLs; native permissions are never shared between bots. ORM document/bot/organization deletion writes remote cleanup work in the same transaction. Cleanup protects active bindings and retries known resource IDs, including a lost delete acknowledgement.

Ambiguous native create/upload outcomes are not blindly retried. If a connection fails after a remote write but before its ID is received, an operator may need to reconcile the remote orphan. This limitation is not described as solved storage management.

## Configuration and deployment preparation

See [native service setup](../deploy/native-ragflow/README.md) and [BGE setup](../deploy/bge-reranker/README.md) for image configuration and service contracts. The optional native Compose overlay supplements the existing SaaS services; this consolidation validates Railway services, not a local Compose startup.

API and ingestion worker require operator-owned values:

```text
RAGFLOW_URL=http://PRIVATE_NATIVE_HOST:9380
RAGFLOW_API_TOKEN=<native service tenant token>
RAGFLOW_TENANT_ID=<native tenant ID>
RAGFLOW_EMBEDDING_ID=<registered BGE-small UUID or BAAI/bge-small-en-v1.5@HuggingFace>
RAG_COMBINED_RERANKER_URL=http://PRIVATE_RANKER_HOST:8080/rerank
RAG_COMBINED_RERANKER_TOKEN=<shared private ranker secret>
```

The ranker receives that secret as `COMBINED_RERANKER_TOKEN`. Secrets never go to the browser. Production uses the existing bot/provider configuration; temporary validation overrides must be restored before release. Readiness requires native policy/tenant/source integrity, the authenticated pinned BGE service and the offline tokenizer, alongside the platform's existing checks.

For a new installation or corpus migration, run the normal migration and populate bindings for every current source before application cutover. Reindex through the existing Knowledge workflow, or adopt an existing parsed native corpus using `backend/scripts/bind_native_knowledge.py`. Adoption requires an explicit database identity and a mapping of document IDs plus source/manifest hashes. Its default is read-only validation; `--apply` atomically binds the complete current corpus. Never infer mappings from filenames alone. A newly crawled corpus can have different chunks; adopting the verified existing corpus is the route that preserves the tested index. The destination WOWMD adoption is complete.

## Pinned open-source components

- RAGFlow revision `a024bea0cd93f39e6652a42bf84dd20c55bc560b`, Apache-2.0. Native search code runs unchanged; an authenticated adapter exposes its full 128-candidate operation because the ordinary REST retrieval page is capped at 100.
- Official RAGFlow image digest `sha256:e6b3f1a185c0a70abb3a72e1092415df8c5c6a4fae0089545554f2936c4b27ab`. Six source hashes are verified at build and request boundaries.
- BGE v2-m3 revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, Apache-2.0; official Sentence Transformers 6.1.0 CrossEncoder.
- LangChain MergerRetriever commit `d7508191bcf2af823ad8a168a15772710de5592b`, MIT, adapted to stable source IDs.

Licenses, adaptation notes and artifact hashes accompany the code. There are no WOWMD/IKEA keywords or per-question answers in the runtime. Backend, frontend, native and BGE images use scoped build contexts. Tests, temporary harnesses, reports and local credentials are excluded; required runtime prompts and source attribution remain packaged. This integration guide is outside those build contexts.

## Verification and limits

See [the 2026-09-28 widget verification report](NATIVE_RAG_WIDGET_VERIFICATION_20260928.md) for the earlier local test's exact questions, answers and observed gaps. It is historical evidence; current raw captures and test reports are held privately outside the repository.

The frozen replay matches ranking and context-prefix selection in all 65 stored cases. Its existing evidence-coverage results remain 9/9 answerable cases in each WOWMD ten-case set and 43/45 IKEA cases; one unavailable-image case in each WOWMD set is excluded. The two IKEA misses remain failures. This is not a claim that all 90/100 answers were perfect or freshly rerun.

Linux image acceptance completed with 86 backend tests passed and one skipped, plus 14 BGE service tests passed and one skipped: 100 passed and two skipped in total. The acceptance runner verified 350 backend runtime source files and seven BGE runtime source files, blocked external network access, used isolated SQLite for backend tests, and made no provider calls. Coverage includes native ownership/content integrity, revocation, partial migration, ingestion/recrawl/promotion/failure, clone isolation, cleanup, SQLite migration execution, public SSE/history/quota/retry behavior, combination ranking, readiness and frozen replay. These checks do not establish a fresh live upload/recrawl/delete lifecycle against all deployed dependencies.

A controlled ten-case comparison exercised the deployed CPU BGE service with frozen retrieval candidates and query plans, then the production merge/context code. All ten cases exactly matched the saved full ranking order, context and evidence coverage. Eight cases had complete expected evidence; the two known IKEA misses (U22 and U34) remained misses. The run scored 512 pairs in 16 ranking requests and made no LLM calls. This validates BGE/merge/context parity for those inputs, not fresh retrieval, widget delivery or semantic answer correctness.

CPU scoring took 47.8–61.2 seconds per lane (median 51.9 seconds); one failed attempt was recorded. Multi-focus questions require multiple sequential lanes. Concurrent load and acceptable production latency remain unverified. The eight-case widget run used the deployed SaaS routes and destination PostgreSQL, Redis, native RAGFlow and BGE services, with temporary Codex-assisted planning/answers outside the shipped code. All eight returned exact authored answers with native and combined traces; successful retries took 29.4–64.4 seconds. Gemini counters and encrypted credentials were unchanged. Manual plans/answers do not prove Gemini will choose the same queries or wording.

The fresh widget test used different focused query wording from September 28 in seven cases. Its source contexts therefore cannot be treated as an identical-input parity test. Q59 still omitted the conflicting Turmeric Boost dose; Q65 selected Greens Blend and the digestion collection without the other previously suggested products; Q84 did not select the explicit no-cure disclaimer. Answers stayed within the selected evidence. These are remaining coverage limits, not perfect retrieval. The widget's bold-link and saved-history formatting fixes passed 53 browser checks, including verified-link preservation and unsafe-link rejection. Older saved replies without source metadata cannot regain verified links merely from their answer text.

A separate fresh replay then used the exact September 28 questions and focused queries against the destination native index and combined pipeline. All eight reproduced the earlier source-context strings, passage bodies and passage order exactly. This replay enforced read-only PostgreSQL access, blocked provider calls and used the deployed native and BGE services. Single-lane cases took 31–33 seconds and two-lane cases 61–64 seconds. It establishes parity for these identical inputs while retaining the earlier evidence gaps; it does not guarantee identical queries from a different answer provider.

## Preserved cleanup history

The earlier 2026-09-28 authorized cleanup affected `ragflow-stock-dev`: WOWMD (23 documents, 413 chunks, 370 source objects), one active assistant and owner settings were retained. IKEA, extra test assistants and chat history were backed up and removed. Provider quota/cooldown safeguards remain. The September 30 destination cleanup removed the approved 65 old messages, one session, 65 consumed reservations, four audit entries, 13 obsolete ingestion jobs, two failed crawls and 1,092 replaced PostgreSQL chunks. A fresh custom-format database backup was verified before the transaction. Protected-row hashes, source manifests and original provider settings were checked before commit; the admin, bot/settings, WOWMD dataset and latest eight validation conversations remain.

Earlier local reports and the stock validation tree remain recoverable in the private archive outside the project; all 76,519 relocated files passed SHA-256 checks. The current cleanup separately archived 65 approved obsolete report files (30 tracked and 35 ignored), verified their hashes, then removed the originals and repaired documentation references. Protected runtime assets, prompts, fixtures and licenses remain. Git history retains previously committed report versions; history has not been rewritten. Archives still occupy disk. Current test harnesses, backups and raw traces remain outside Git and deployment contexts.

For each release, verify the deployed commit, private service dependencies, worker heartbeat, provider configuration and regional placement. Keep temporary provider endpoints, test bridges and archive files out of deployed images and service settings.
