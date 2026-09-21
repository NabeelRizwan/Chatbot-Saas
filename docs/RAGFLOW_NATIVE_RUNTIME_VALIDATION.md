# RAGFlow native runtime validation

2026-09-21 UTC. **Native runtime/security/lifecycle/persistence: PASS. Generic retrieval quality: PARTIAL (4 complete, 1 partial, 3 empty / 8).**

Runtime commit `37fb06f4184a8d969accdf89a315da405ca6ebaf` on `ragflow-derived-dev`; baseline `06f2d5d4c78805f54e818cc3886cf2438e5990cf`; upstream v0.27.2 `a024bea0cd93f39e6652a42bf84dd20c55bc560b`. No retrieval algorithm changes for deployment.

## Evidence anchors

- New project `068a5695-2cf6-4c7f-89fc-3d24a225e4a5`, environment `31650c5f-fc5f-4954-9094-6d06383b3d17`.
- Initial completed acceptance: `6d9f38c1-c574-43a8-9503-fe59cee8f51a`, terminal SUCCESS.
- ES restart: `ce995534-dafa-4400-a54f-c919c8ef5acc`, terminal SUCCESS, same volume `9f427118-1557-40b5-86c5-66451116d094`.
- Post-restart persistence and positive tenant checks: `d8f25a74-54b1-4435-89e7-2a2d946725d6`, terminal SUCCESS.
- Full non-secret records: `RAGFLOW_NATIVE_ACCEPTANCE_RESULTS.json` and `RAGFLOW_NATIVE_PERSISTENCE_RESULTS.json`. Transport checksums/history are in `RAGFLOW_RAILWAY_DEPLOYMENT_REPORT.md`.

## Native gates

| Gate | Result |
| --- | --- |
| Linux tokenizer | REAL PASS: Infinity SDK 0.7.3 RagTokenizer startup and native query execution |
| Elasticsearch | REAL PASS: 8.11.3 private single node, new volume, real index/search |
| Embedding/index/search | REAL PASS: pinned CPU MiniLM, 384-dimensional vectors, real ES vector candidates |
| Lexical/hybrid | REAL PASS: native RAGFlow-derived MatchTextExpr, MatchDenseExpr, FusionExpr trace |
| Reranking | REAL PASS for execution; actual model scores/hashes, quality losses retained below |
| Context/citations | PASS: exact text SHA256/version/chunk identity; distinct IDs; <=131072 bytes, <=8192 tokens, <=48 units |
| Lifecycle | PASS: v1 -> v2 old text invalidation, deletion, reingest v3, stale exclusion |
| Auth/scope | PASS: missing bearer 401, malformed input 422, wrong org/bot/generation/document 403, stale version 409 |
| Positive tenant isolation | PASS: nonempty A/B library results; real ES mget and scoped-row validation on 20 A / 19 B candidates; zero overlap |
| Negative tenant probes | PASS: foreign markers absent; responses empty, so insufficient alone as isolation proof |
| Failure contract | PASS: explicitly injected storage/embedding/reranker failures return structured 503; no old fallback |
| Persistence | PASS: exact sentinel context AND citations unchanged after ES restart |

Sentinel chunk `87eba153eea73c527626ba14ad58e5c4679e4c4e55bf3a111a0cc3fb96a3e183`; an initial repeated read also matched. Post-restart acceptance elapsed `2.481580827385187` seconds.

## Models

- Embedding: `sentence-transformers/all-MiniLM-L6-v2`, `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache-2.0, CPU, 384 dimensions.
- Reranker: `cross-encoder/ms-marco-MiniLM-L6-v2`, `233902d25c440f23af6f7d6e94d2946bac0bee0a`, Apache-2.0, CPU.
- Pinned safetensors downloaded during Linux image build; real smoke then local-only runtime loading. No weights in Git or external provider calls.

## Eight generic questions / measured trace

24 generic synthetic sources (12 per tenant), 38 evidence chunks; sentinel brings final total to 25 sources / 39 chunks. Saved records contain lexical/vector/hybrid candidates, no-reranker diagnostic output, pre/post rerank order, real scores/input hashes and exact final evidence/citations.

| Category | Lexical / vector candidates | Final sources | Internal traced request ms | Reranker ms | Full requested support |
| --- | ---: | --- | ---: | ---: | --- |
| exact_fact | 11 / 19 | library | 572.2939670085907 | 174.13560301065445 | PASS |
| semantic_paraphrase | 3 / 19 | none | 374.20205026865005 | 45.0148731470108 | FAIL |
| lexical | 2 / 19 | study | 353.70444506406784 | 28.861403465270996 | PASS |
| multi_document | 6 / 19 | delivery | 445.6065818667412 | 100.96397250890732 | PARTIAL |
| discovery | 10 / 19 | none | 513.129711151123 | 129.85770404338837 | FAIL |
| comparison | 5 / 19 | membership | 414.78095203638077 | 63.77220153808594 | PASS |
| qualified_policy | 5 / 19 | kayak | 535.9790623188019 | 79.16447520256042 | PASS |
| rerank_candidates | 6 / 19 | none | 478.93939912319183 | 106.42705857753754 | FAIL |

The loose harness `functional_hit` count 5/8 credits a nonempty but one-sided museum/parcel response; honest full-support count is **4/8**. Empty packs passed structural validation but failed sufficiency. API returns context, not generated chatbot answers.

Museum + parcel has two units in no-reranker diagnostic output and only delivery after reranking. Workshop has one unit before reranking and none finally. Paraphrase/discovery are empty in both outputs. These observations are not a complete root-cause diagnosis; no tuning was performed.

First initial run stopped after eight functional requests during a proxy-connection-limit 503 in negative tests. A deployment-only transport repair preceded the complete retry: eight unique questions were executed twice. Following user secret rotation, one persistence call received 401; backend redeploy synchronized credentials, then only persistence and two positive tenant checks reran. No third eight-question run.

## Offline checks / limitations

- 147/147 focused tests PASS: 110 existing port + 33 native API/authority + four acceptance transport tests. Offline doubles are not native evidence.
- Syntax/secret-pattern preflight and whitespace PASS. Provenance PASS: 30 mapped files / 32 mappings, official blobs.
- Original application DB/customer corpus/old engine/production untouched. No provider/model API calls, main push/merge, 90-case/GOLD benchmark or quality optimization.
- Final success-path test doubles: NO. Controlled faults use explicit request-local injection, not actual outages.
- No throughput, production latency, OCR, distributed-load or complete customer-chat acceptance claim. Native execution does not guarantee sufficient retrieval for arbitrary queries.

See deployment report for exact question wording, resources and authenticated API instructions. One-shot acceptance pre-deploy hook is removed after validation; phase `disabled` prevents accidental reruns.
