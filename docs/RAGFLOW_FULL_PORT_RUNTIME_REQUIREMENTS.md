# Full development runtime requirements

Only project `068a5695-2cf6-4c7f-89fc-3d24a225e4a5` (`ragflow-derived-dev`), backend `92349a32-e92d-4795-b86e-338929b03059`. Its environment happens to be named `production`; it is not Chatbot-SaaS-Production. Forbidden project `4ca162fa-755c-4c70-b3aa-7f4166a1fb36` remains untouched.

## Existing services, no new infrastructure

Elasticsearch 8.11.3 can store source chunks, parent/TOC rows, compiled document graphs, KG rows and RAPTOR vectors. No Neo4j, Redis cluster, GPU service or extra replica is required for the delivered modes. Existing ES volume is 1,024 MB; synthetic validation is deliberately small. No paid upgrade or volume resize is authorized or performed by this workstream.

Backend: Python 3.12, one Uvicorn worker, serialized native operations; existing CPU MiniLM embedding and cross-encoder weights/revisions unchanged. Additional graph/parser packages are in `backend/requirements-ragflow-full.txt`; isolated offline runner extras are in `backend/requirements-ragflow-test.txt`. CPU/RAM expectations are workload-dependent: model baseline dominates, with additional graph/vector/ZIP allocations. Compilation is bounded at 10,000 leaves/rows, API sources at 30 and request bodies at 1.1 MB; this is not a large-corpus capacity certification. ZIP expanded-byte bounds are 20 times the parser input bound. Production scaling is out of scope.

## Configuration and API

Existing bearer tokens remain organization/bot authority. API callers never supply a wider tenant. `POST /ragflow-dev/ingest` accepts text/base64 rich formats, existing child/TOC/keyword options and document metadata/tags. `retrieve/context` keeps ordinary mode and optional actual upstream query helpers. `POST /ragflow-dev/compile` accepts explicit `raptor`, `structure`, `graph`, exact expected source versions/generation and optional `artifact_sources` subset. `POST /ragflow-dev/advanced` selects `navigation`, `raptor`, `graph`, or `agentic` plus actual thinking mode.

Artifact subset is explicit configuration, not inferred from an evaluation answer. Requests must name the same sealed source inventory used at compilation. Changes/deletion/version/generation invalidate old artifacts. No silent mode substitution is offered. Publication is CREATE-only; replacing a published collection requires a new source version/inventory, not an overwrite endpoint.

Gemini remains `gemini-3.5-flash-lite`, using only the key already inside this development service. `RAGFLOW_DEV_MAX_CHAT_CALLS` defaults to 20 and has a hard ceiling of 200 per process. Frozen validation uses a bounded 160-call ceiling, not unbounded calls or model retries. Actual upstream KG per-document retry policy remains pinned; the validation job itself cannot be retried because of a durable CREATE-only run marker. A 900-second operation timeout fails explicitly. No key is read back or copied locally.

Normal threshold .2, .7/.3 term/neural blend, embedding/reranker, top-k and context limits are unchanged. Agentic BM25/vector tools keep their upstream route semantics and do not secretly borrow normal cross-encoder behavior. No provider call occurs at startup/import/health. Health reports software readiness and artifact requirements separately; live acceptance must test each mode.

LangSmith/LangChain tracing and HuggingFace telemetry are disabled in the image. No hosted tracing service, provider discovery, application DATABASE_URL, dotenv or production credentials are used.

## Exact deferred requirements

- DeepDoc OCR/layout/table recognition: pinned ONNX OCR/layout/TSR model assets, CPU/native runtime and measured RAM; alternative parser services need their own model/server/credentials. No fake OCR fallback.
- Vision/audio: explicit licensed VLM/ASR callback plus media storage/lineage. Current API does not claim image/audio interpretation.
- KG community reports: exact upstream graspologic fork and audited native numerical closure. NER: spaCy plus one or more mapped language pipelines (e.g. en_core_web_sm). These modes refuse before calls.
- Full arbitrary compiled templates/wiki: product template/task/revision services, owned versioned FileCommitService, checkpoint/resume. Source helpers exist; these operational workflows are not enabled.
- SQL: scoped structured-data backend and SQL authorization adapter. Customer/application SQL is not used as a shortcut.
- Durable/distributed task/agent state: upstream task lifecycle and scoped Redis/queue storage. Current operation-local state intentionally does not promise cross-request resume.
