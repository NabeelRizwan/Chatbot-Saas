# RAGFlow integration report

Date: 2026-09-21. **PORT STATUS: PARTIAL.**

A real, isolated RAGFlow-derived engine is present and executes ingest → chunk/index → retrieve/hybrid/rerank → bounded exact context → citations. It is not a wrapper pointing to an absent RAGFlow server and does not reuse our old RRF/Q1 implementation. The local end-to-end run used deterministic model/tokenizer fixtures and a test-only memory store. Native Elasticsearch, native tokenizer and real-model acceptance remain pending; this is not production-ready or full RAGFlow parity.

## Source and release gate

- Official source: https://github.com/infiniflow/ragflow
- Release: v0.27.2; published 2026-09-10T11:11:35Z.
- Full pin: a024bea0cd93f39e6652a42bf84dd20c55bc560b.
- Observed official main: 83c47d02518265f8bdec9ec226a2531f4a59f340; pin ancestry verified.
- Relevant post-release security/retrieval/rerank/parser/storage changes reviewed in RAGFLOW_PORT_REFERENCE.md. No post-release patch incorporated.
- Root LICENSE: Apache-2.0. No upstream root NOTICE; exact LICENSE plus explicitly authored attribution NOTICE supplied.
- Core copied-code attribution gate PASS. Optional ES service licensing, LGPL redistribution obligations and native/model asset licensing are documented separately; no blanket production licensing approval.

## Preservation / checkpoints

Starting branch main; starting HEAD 1b8be711d7f59cafdf9c6552778f396731c0a76d. Starting tracked changes: none. Nineteen existing untracked Q2/Q4 diagnostic/experiment files remain untouched and uncommitted.

All **579/579** files in the initial preservation inventory match their pre-task hashes. No accepted Q1/Q3, production route, provider, prompt, schema, credential, corpus, frontend or current dependency file changed.

Local implementation checkpoint: **cd7ac160772612b7db2f5d9317dc290079da175b**, `RAGFlow: vendor pinned core and integrate isolated development engine`.

The documentation/validation checkpoint containing this report is `RAGFlow: document provenance runtime limits and validation`; its exact SHA is available from `git log -1` and the task's final response. Only new workstream files are included in these local checkpoints. No push, deploy, remote migration or production switch.

## Layer classification

| Layer | Classification | Actual coverage / limitation |
| --- | --- | --- |
| Parsing | ADAPTED / WRAPPED | Actual Markdown/HTML/text parser code; basic pypdf/DOCX wrappers. DeepDoc OCR/layout deferred. |
| Chunking | ADAPTED | Actual upstream delimiter/paragraph merge plus protected block dispatch; not every upstream strategy. |
| Metadata | ADAPTED | Exact text/hash, title, source/doc/version, generation/profile, order/headings/type/URL; layout graphs deferred. |
| Embedding abstraction | ADAPTED / WRAPPED | Actual EmbeddingUtils text prep/title blend/vector attachment; explicit configurable callbacks. No provider calls. |
| Indexing | ADAPTED | Pinned ES mapping, scoped client, atomic source-version manifests/READY activation; native server not exercised. |
| Lexical retrieval | ADAPTED | Actual FulltextQueryer, term weighting, synonyms and ES query_string DSL; native tokenizer validation deferred. |
| Vector retrieval | ADAPTED | Actual Dealer KNN + second cosine-scoring request; no pgvector substitute. |
| Hybrid retrieval | ADAPTED | Pinned weighted ES retrieval and token/cosine scoring; no old RRF or Q1 reuse. |
| Query processing | ADAPTED | Deterministic upstream normalization/token/phrase/synonym processing. Optional model-backed multi-turn rewrite/expansion deferred. |
| Reranking | ADAPTED | Actual weighted and model rerank code; configured callback/failure handling; learned model quality unvalidated. |
| Context assembly | ADAPTED | Actual kb_prompt plus whole-block byte/token/unit cap including framing; no old packer. |
| Citations/provenance | ADAPTED | Exact indexed text/hash and full source-version/chunk IDs; short-ID collision risk removed. Generated answer citation placement not live-tested. |
| Orchestration | ADAPTED | Local ingest/update/delete/retrieve/context plus existing generation bridge; distributed product tasks/advanced agentic retrieval not ported. |

Product-only frontend/accounts/admin/billing/workflow marketplace/connectors/demos are omitted. Optional advanced graph/RAPTOR/TOC/tree/agentic retrieval is **deferred**, not misleadingly labeled product-only.

## Counts and file scope

- 31 distinct upstream paths used/referenced by source provenance, including interface references, four test modules, shared fixture, resources and license.
- 32 source-to-destination mapping records; 30 unique mapped destinations.
- Unique mapped destination classification: **10 COPY, 16 ADAPT, 1 WRAP, 3 REIMPLEMENT**. A multi-source adapter is counted once using ADAPT > WRAP > REIMPLEMENT > COPY precedence. This prevents double-counting runtime.py and models.py.
- **58 new project files**: 50 code/test/config/provenance/attribution files in the implementation checkpoint and 8 architecture/reference/runtime/test/benchmark/report documents.
- No existing project file replaced. Three new subtree .gitattributes files retain LF for byte-hashed provenance across checkouts.
- Machine manifest verification: **PASS**, 30 files / 32 mappings, canonical pinned git blobs verified.
- Source hashes cover exact upstream blob bytes; destination hashes cover exact local bytes. Namespace/algorithm changes are classified explicitly. The mapping JSON differs only by newline normalization and is correctly ADAPT rather than byte-identical COPY.

Required artifacts:

- CURRENT_RAG_ARCHITECTURE_MAP.md
- RAGFLOW_PORT_REFERENCE.md
- RAGFLOW_PORT_ARCHITECTURE.md
- RAGFLOW_DEPENDENCY_AND_LICENSE_MATRIX.md
- RAGFLOW_UPSTREAM_TEST_MAPPING.md
- RAGFLOW_RUNTIME_REQUIREMENTS.md
- RAGFLOW_BENCHMARK_PLAN.md
- RAGFLOW_INTEGRATION_REPORT.md
- ../third_party/ragflow_port_manifest.json and ../third_party/ragflow/{LICENSE,NOTICE}

## Adapter / security findings

Current engine default remains **current**. RAGFlow selection requires explicit development opt-in; production selection is rejected. Main/public/widget routes are unchanged. A separate factory supplies a development-only endpoint using existing login, bot membership and message quota. No client/model-controlled tenant/index/scope selector exists.

Authoritative READY/active-crawl scope translation uses existing ready_documents. Every search/fallback/second-KNN is constrained before ranking to the authorized scope/index, bot and ready source versions. Returned rows and context are revalidated. The authority callback must re-read lifecycle/generation/profile with fresh DB sessions, not cache permissions or share sessions across threads.

Synthetic stronger-foreign-match, forged-row, wrong-version/profile/generation, revocation, malformed identity and source-narrowing checks PASS. Empty/partial source activation fails closed. Incomplete native delete responses (timeout, failures, conflicts) raise INDEX_FAILED rather than falsely report success. No native multi-process race/stress certification is claimed.

Neutral context is passed to the unchanged prompt/system builders and llm_router.generate with the same bot/provider. This invocation is tested with a mock. Existing Gemini implementation/settings are not modified. Prompt-injection fixture text stays data and cannot change routing/system instructions; no claim of universal model-level injection resistance.

## Validation results

| Check | Result |
| --- | --- |
| New focused tests | **63/63 PASS** |
| Ported upstream tests | **47/47 PASS** |
| Combined new/ported suite | **110/110 PASS**, 2.40 seconds; one Starlette deprecation warning |
| Generic local functional smoke | **PASS**: ingest/retrieve/context, 3 citations, 0 provider calls; explicit fixture mode |
| Old/new imports, default/current adapter, FastAPI import with DB init stubbed | **PASS** |
| Actual dev HTTP auth/tenant rejection/response shape | **PASS** |
| AST syntax | **PASS**, 38 Python files |
| Source provenance/license header verifier | **PASS**, official pinned blob verification |
| Secret/customer URL/known-domain scan of new work | No matches |
| Staged whitespace check | **PASS** |
| Initial-file preservation | **579/579 unchanged** |
| Safe existing canonical suite | **3945/3948 PASS; 3 pre-existing stale-hash failures** |
| Native ES/tokenizer/model integration | **NOT RUN / prerequisites unresolved** |
| Existing 90-case comparison | **NOT RUN** |
| HOLDOUT_B | **NOT RUN / not fabricated** |

Canonical suite was run once (459.886 seconds), not repeatedly tuned. The three failures are listed exactly in RAGFLOW_UPSTREAM_TEST_MAPPING.md. They assert old rag_planning.py hash b90cab62a66f27c05f1576810c3ebe79e94d1c6a6d92d037bccc0780186c4f90 while the unchanged initial/current file hash is c643ccdcad43b573768d4500e7fd56f633dc861efee93337c8bcb304190f03e6. No code or frozen hash was changed to hide them.

## Runtime/dependency outcome

Optional local ES 8.11.3 configuration is supplied, loopback 19200, isolated volume, 1 GiB heap / 2 GiB memory planning budget. Docker is absent on this host; no service started or cloud provisioned.

Infinity SDK 0.7.3's datrie native build requires unavailable MSVC 14+ here. Smaller parser/search/test dependencies were installed only in the new ignored .codex_ragflow_venv; current backend/system Python remains untouched. The native optional requirements set was not fully installed, and test NumPy/SciPy versions differ from that declared native environment. See runtime/license docs rather than treating fixture success as native readiness.

New optional direct dependency declarations: infinity-sdk, elasticsearch, elasticsearch-dsl, elastic-transport, Markdown, beautifulsoup4, chardet, numpy, scipy, scikit-learn, nltk, tiktoken, python-docx, pypdf, pytest. Transitive/native/data/model license and resource implications are recorded. No credentials, provider models, OCR assets or customer embeddings were used.

## Remaining gates / next test

1. Clean native Linux development environment with declared requirements, licensed tokenizer data and loopback Elasticsearch.
2. Generic real-ES ingest/retrieve/update/delete and scope/READY/filter validation before any benchmark; configure licensed local or separately authorized embedding/reranking callbacks.
3. Explicit authorization for current-vs-derived corpus comparison; collect independent channel/rerank traces and metrics. The neutral paired harness interface is ready, but full stage metrics/native setup are not prevalidated.
4. Later unseen HOLDOUT_B independently authored/evaluated. Do not tune against old GOLD.
5. Separate approval for optional query rewrite, advanced retrieval, production licensing/service hardening and eventual production activation.

There is a working provider-free local execution path and the native adapters exist as source. Native operational/quality acceptance is withheld. No quality gains, production latency, full upstream parity or production readiness are claimed.

## Prohibited actions confirmation

No production/customer database or corpus access; no Railway action; no deployment; no provider/model calls; no crawl; no paid/local corpus re-embedding; no 90-case/holdout run; no rejected Q2/Q4 algorithm adoption; no secret persistence; no push. Only the authorized local commits were created.
