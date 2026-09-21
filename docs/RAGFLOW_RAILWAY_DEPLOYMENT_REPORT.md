# RAGFlow Railway deployment report

2026-09-21 UTC. **STATUS: PARTIAL — both native services RUNNING; runtime/security/lifecycle/persistence PASS; generic retrieval quality not fully accepted.**

## Source and isolation

Development branch `ragflow-derived-dev` was created from `06f2d5d4c78805f54e818cc3886cf2438e5990cf`. Validated runtime: `37fb06f4184a8d969accdf89a315da405ca6ebaf`; final report-only checkpoint does not change it. RAGFlow v0.27.2 upstream: `a024bea0cd93f39e6652a42bf84dd20c55bc560b`.

Local main remains `06f2d5d4c78805f54e818cc3886cf2438e5990cf`; remote main was observed at `7c8236001ccc552c89c860b2db6a4d4c369ee211`. Neither was changed/pushed by this task. No merge or force push. The 19 pre-existing untracked Q2/Q4/Q4B files remain untouched and excluded.

Forbidden production project `4ca162fa-755c-4c70-b3aa-7f4166a1fb36` was not mutated. No production variables, services, deployments, volumes, domains, existing databases or customer corpus used. Deployment used the authenticated Railway integration and authorized GitHub development branch; no Windows Railway CLI/WSL or policy bypass.

## Actual new deployment

| Item | Verified value |
| --- | --- |
| New project | `ragflow-derived-dev` / `068a5695-2cf6-4c7f-89fc-3d24a225e4a5` |
| Environment | `31650c5f-fc5f-4954-9094-6d06383b3d17`; default name `production`, inside ONLY this new development project |
| Backend | `ragflow-dev-backend` / `92349a32-e92d-4795-b86e-338929b03059` |
| Public API | https://ragflow-dev-backend-production.up.railway.app |
| Source | `NabeelRizwan/Chatbot-Saas`, branch `ragflow-derived-dev`, `Dockerfile.ragflow-dev` |
| Completed initial acceptance | `6d9f38c1-c574-43a8-9503-fe59cee8f51a`: terminal SUCCESS |
| New-secret activation | `65b01464-7f76-4dfc-a605-2f30d58df5f7`: terminal SUCCESS |
| Persistence / positive tenant check | `d8f25a74-54b1-4435-89e7-2a2d946725d6`: terminal SUCCESS |
| Hook removal / final runtime | `1823950a-8a09-419b-9f6b-137be395ced0`: terminal SUCCESS; no pre-deploy hook, same validated runtime |
| Elasticsearch | `d005597d-3e7b-4238-b2a7-e37cb534fb22`, `ragflow-dev-elasticsearch`, real 8.11.3 |
| Private ES address | `ragflow-dev-elasticsearch.railway.internal:9200`; no public domain or configured public TCP proxy |
| New persistent volume | `9f427118-1557-40b5-86c5-66451116d094`, 1 GiB, `/usr/share/elasticsearch/data` |
| ES restart | `ce995534-dafa-4400-a54f-c919c8ef5acc`: terminal SUCCESS, same volume |

One backend and one ES replica; no PostgreSQL, Redis, worker, GPU or separate model service. ES initializes ownership only on the new mount root, then runs the official entrypoint as non-root Elasticsearch user. Backend is non-root. Health: `/health` and `/ragflow-dev/health`.

## Real native validation

| Gate | Result |
| --- | --- |
| Tokenizer | REAL PASS: Infinity SDK 0.7.3 RagTokenizer, native Linux build/startup/query execution |
| Embedding | REAL PASS: `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU, 384 dimensions, Apache-2.0 |
| Reranker | REAL PASS: `cross-encoder/ms-marco-MiniLM-L6-v2`, revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`, CPU, Apache-2.0 |
| Ingest/index | PASS: 24 synthetic HTML/Markdown/text sources, 12 per tenant, 38 evidence chunks; sentinel adds one source/chunk |
| Lexical/vector/hybrid | PASS for real execution: native ES candidates and RAGFlow-derived hybrid expressions saved for all eight queries |
| Reranking | PASS for execution: real scores/input hashes and before/after order; quality limitations below |
| Context/citations | PASS for exact text hashes, source/version identity and limits; empty/incomplete packs are not quality passes |
| Lifecycle | PASS: old text revoked on update, stale version rejected, deletion excludes source, reingest v3 succeeds |
| Auth/scope | PASS: wrong org/bot/generation/document 403, stale version 409, no bearer 401, malformed input 422 |
| Tenant isolation | PASS: nonempty library evidence for A and B; 20 A / 19 B candidates individually validated against real authorized ES rows; zero cross-tenant candidate overlap |
| Failure handling | PASS: controlled storage/embedding/reranker faults return structured 503; no old-engine fallback |
| Restart persistence | PASS: identical sentinel context AND citations after ES restart |

Sentinel chunk `87eba153eea73c527626ba14ad58e5c4679e4c4e55bf3a111a0cc3fb96a3e183` was retained. The successful native path uses no test doubles. Explicit failure tests use request-local fault injection, not an actual induced infrastructure outage. No external model/provider or answer-generation call: this API returns retrieval evidence/context, not generated conversational answers.

## Generic retrieval quality: 4 complete / 1 partial / 3 empty

All eight requests returned HTTP 200 and valid response contracts. The loose harness `functional_hit` count is 5/8 because it counts the one-sided hours response. **Full requested evidence is supported in only 4/8.**

| Exact question | Actual final evidence | Quality |
| --- | --- | --- |
| How many days can members borrow printed library books? | Library: 21 days; conditional seven-day renewal | Complete |
| Where can I leave spent household power cells safely? | Empty | Fail |
| Cedar group study room capacity | Study: six people, up to three hours | Complete |
| What are the opening hours for the museum and parcel collection? | Parcel: 08:00–18:00 weekdays; museum missing | Partial |
| Which community services offer book borrowing, classes or shared tools? | Empty | Fail |
| Compare the Basic and Plus membership monthly fees and included services. | Table: Basic 12 credits, Plus 18 credits; included services | Complete |
| Can I rent a kayak during thunderstorms? | Rentals pause during thunderstorms or strong winds | Complete |
| How can I reserve a room or a woodworking workshop session? | Empty | Fail |

The no-reranker diagnostic has both museum and parcel evidence; only parcel survives the final reranked output. Workshop goes from one no-reranker unit to no final evidence. Paraphrase and discovery are empty even without reranking. These are observations, not an exhaustive root-cause diagnosis. No ranking/threshold/query/port algorithm tuning was performed.

## Execution history / secret handling

1. Actual Linux tokenizer and pinned CPU model build smoke passed. Weights are image assets, not Git files.
2. First acceptance attempt ingested v1 and ran all eight functional queries, then rapid negative checks encountered a proxy idle-connection ceiling 503. No full artifact survived.
3. Deployment-only fix: Uvicorn connection ceiling 64, two-second keepalive; model work remains serialized. Harness now retains partial results, classifies non-JSON errors and version-updates only its exact owned synthetic fixtures. No retrieval algorithm changed.
4. Complete second initial acceptance took `118.58198770321906` seconds; 24 sources became v2. Eight UNIQUE questions ran twice (16 requests); tenant/error/lifecycle probes are additional.
5. After ES restart the first persistence client saw HTTP 401: the user had replaced three secrets with redeploy skipped, while the running API still held prior values. No secrets were read/exported. A backend deployment synchronized the new values.
6. Only persistence and two positive tenant checks then reran and passed in `2.481580827385187` seconds. There was no third eight-question run.
7. One-shot pre-deploy hook is removed after validation; acceptance phase is `disabled` as a second guard against automatic reruns. User-set secrets remain only in the NEW Railway service and process memory, never printed, downloaded or committed.

## Resource observations

One-hour Railway samples at 30-second intervals include deployments/overlap, not a steady-state load benchmark:

| Service | Latest memory GB | Max memory GB | Max CPU vCPU |
| --- | ---: | ---: | ---: |
| Backend | 0.739033088 | 1.530175488 | 0.43516156666666667 |
| Elasticsearch | 1.726246912 | 2.009935872 | 1.1803582666666665 |

ES volume latest `0.03682304` GB, max `0.038035456` GB. Initial evidence-index primary bytes: `1,330,947` across two scoped indexes, excluding authority index. Railway ceilings are **8 vCPU / 8 GB per replica**, not the planned 2 vCPU/2 GiB: unsupported limit fields were discarded by the integration. No plan/billing upgrade. ES heap is 1 GiB; inference uses two intra-op/one inter-op threads. This is not production capacity acceptance.

24 initial ingest responses: `3234.029643237591`–`4996.709778904915` ms each. Eight traced requests: `353.70444506406784`–`572.2939670085907` ms internally, including extra diagnostic lanes, NOT ordinary single-lane or internet end-to-end latency. Reranker: `28.861403465270996`–`174.13560301065445` ms. No throughput claim.

## Offline verification / artifacts

- **147/147 focused tests PASS**: 110 existing port + 33 API/authority + four acceptance transport tests. Offline doubles are separate from native acceptance.
- Syntax/secret-pattern preflight and whitespace checks PASS; pre-existing fixture/example false positives reviewed without revealing values.
- Provenance PASS: 30 mapped files / 32 mappings / official upstream blobs.
- Original port, vendored upstream, production services/frontend/dependencies unchanged against baseline; additive dev/runtime/test files only.
- `RAGFLOW_NATIVE_ACCEPTANCE_RESULTS.json`: full eight-query traces, exact evidence, citations, initial lifecycle and inventory.
- `RAGFLOW_NATIVE_PERSISTENCE_RESULTS.json`: post-restart sentinel and both positive tenant traces.
- Original transport SHA256 verified before parsing: initial `b21e8e5f0551fb51054a57011df01c487574b970b48327f33d8f26058fe7ebd4`; persistence `e1638733c14973291d2aa001633ff2eeb99b1ba0ac5bbbf5aedf3601db1ceb15`. Pretty-printed repository JSON normalizes number formatting; those hashes refer to transport bytes, not formatted file bytes.

## Development branch commits

- `a3aceb53ab0c0d6571bd80c2744f54946ef2dd75` — isolated native runtime.
- `dd77e080a6371c5b484ddd5c355e2c3e418e6e8a` — healthcheck alias.
- `b94fa3042f08e2e9d640fe698a8edb53b69ceb56` — secret-safe acceptance job.
- `702c12bcef50127ae6854fcdf3c31dabc6035c2f` — transport safeguards.
- `16aea80011abea6443adc62170a962b06bfc98d1` — proxy connection bound / partial progress.
- `37fb06f4184a8d969accdf89a315da405ca6ebaf` — saved trace / stronger positive tenant checks.
- Final documentation checkpoint: `RAGFlow: document measured native deployment and persistence` (commit containing this report).

All pushes normal, ONLY `origin/ragflow-derived-dev`. No main push/merge, production switch, existing DB/customer data, old engine change, provider call or 90-case/GOLD benchmark.

## How to test now

1. Open https://ragflow-dev-backend-production.up.railway.app/health for status.
2. Open https://ragflow-dev-backend-production.up.railway.app/docs. Choose `POST /ragflow-dev/retrieve` or `/ragflow-dev/context`, then **Try it out**.
3. In the `authorization` header field, locally enter `Bearer ` followed by your NEW backend `RAGFLOW_DEV_TOKEN_A` (or B). Do not put values in chat, source, screenshots or reports. Admin token is only for the failure-check route.
4. Body: `{"query":"How many days can members borrow printed library books?","trace":true}`. Inspect evidence/context/citations/trace. This is an API explorer, not a customer chatbot widget or LLM generator.
5. `/sources` shows synthetic inventory; ingest/update/delete require expected-version checks. Do not rerun full initial acceptance against this finished corpus: its safety guard refuses the added lifecycle sentinel.

**Conclusion:** native deployment and real model execution, scoped authority, exact provenance, lifecycle and persistence verified. Retrieval sufficiency remains partial; separate diagnosis is required before full quality acceptance. No tuning/benchmark started.
