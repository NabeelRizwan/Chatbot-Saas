# RAGFlow local/development runtime

No remote service was provisioned. No production settings, current dependency file or current venv was changed.

## Services and sizing

Required for native retrieval: Python 3.12, optional dependency environment, Infinity SDK tokenizer/assets, NLTK WordNet resources, cl100k_base token data, and Elasticsearch 8.11.3. Infinity *server* is not needed: its SDK supplies the release tokenizer. No additional PostgreSQL, Redis, MinIO, queue or RAGFlow server is needed for this local synchronous interface.

Planning estimate, not measured benchmark: 2-4 CPU cores, ES 1 GiB heap / 2 GiB container memory plus roughly 1-2 GiB Python/model headroom. Reserve several GiB for image/packages plus corpus/vector-dependent index disk. Embedding/reranker model RAM, disk and accelerator requirements depend on operator selection; none selected/downloaded in this task.

dev/ragflow/docker-compose.yml exposes ONLY 127.0.0.1:19200 (container 9200), pinned ES image, isolated named volume. Security is disabled only for this loopback development service. Never use this configuration in production. Future production requires licensed service review, authentication/TLS, operator network controls, snapshots, lifecycle/concurrency validation and capacity planning.

## Reproducible setup (operator action; not executed here)

Use a separate Python 3.12 virtual environment, preferably Linux where native datrie can build, and install backend/requirements-ragflow.txt. Do not install into the accepted backend environment. When mounting the optional router, also provide the platform's existing declared dependencies in that development runtime.

From repository root:

```powershell
python -m venv .venv-ragflow
.\.venv-ragflow\Scripts\python.exe -m pip install -r backend/requirements-ragflow.txt
docker compose -f dev/ragflow/docker-compose.yml up -d
```

On Linux use bin/python instead of Scripts/python.exe. Provision approved tokenizer resources/WordNet and tiktoken cache ahead of runtime; tokenizer/model licenses are separate from RAGFlow's license. Runtime code does not download WordNet/OCR/model weights. tiktoken may fetch its encoding asset if its cache is missing, so pre-populate the cache for network-isolated execution.

No database/provider URL is read by the standalone engine. No new production environment variable is introduced. All connections/models/selection are explicit objects. Never use an application database URL to configure Elasticsearch.

## Minimal trusted SDK usage

Run from backend after setup, with operator-supplied local or separately authorized model callbacks:

```python
import asyncio
from ragflow_derived.contracts import AuthorizedScope, SourceRef
from ragflow_derived.engine import RagFlowDerivedEngine
from ragflow_derived.models import CallableEmbeddingAdapter, CallableRerankerAdapter
from ragflow_derived.storage import ElasticsearchBackend

# Created by trusted test setup or platform authorization, NEVER from user/model JSON.
scope = AuthorizedScope("test-org", "test-bot", "gen-1", "approved-model-v1", 384,
                        (SourceRef("manual", "manual-doc", "1"),))
# These callables are supplied by the operator; no default provider exists.
embedding = CallableEmbeddingAdapter("approved-model-v1", 384,
                                     encode_documents, encode_query)
reranker = CallableRerankerAdapter(score_documents)
engine = RagFlowDerivedEngine(ElasticsearchBackend.local(), embedding,
                             still_authorized=validate_current_authority,
                             reranker=reranker)
try:
    engine.ingest(scope, "manual", "# Service\nEmail support.", kind="md",
                  title="Service", url="https://example.test/service")
    evidence = asyncio.run(engine.retrieve(scope, "How can I contact support?"))
    pack = engine.build_context(scope, evidence)
    # pack["context"], pack["sources"] are neutral generation inputs.
finally:
    engine.close()
```

The undefined callbacks in this example are deliberate configuration points, not built-in implementations. For synthetic provider-free runnable examples use scripts/ragflow_local_smoke.py. Do not substitute a permanently-true authority callback for platform use.

For new version ingestion construct a fresh authorized SourceRef version; update_source delegates to immutable-version ingestion. delete_source removes only that exact source version. No index-wide or database-wide destructive helper is provided.

For HTTP use a separate DEVELOPMENT app and include create_router(EngineSelection("ragflow","development",True), trusted_adapter_factory). Its factory returns RagFlowDerivedEngineAdapter with READY authorization and fresh-session checks. Normal public/widget routes remain current. This endpoint invokes existing generation only when the operator explicitly calls it; it was tested with a mock, not a provider.

## What actually ran here

A separate ignored .codex_ragflow_venv was created; smaller Python parser/search/test dependencies were installed there. Tests reused existing platform libraries read-only. Infinity SDK 0.7.3 installation was attempted but its datrie 0.8.3 build needs Microsoft Visual C++ 14+ on this Windows host. No compiler/global system change was made. Docker is unavailable. Thus neither the native tokenizer nor Elasticsearch server smoke ran.

The optional manifest pins NumPy 1.26.4 / SciPy 1.17.1. The test environment inherited NumPy 2.3.5 and installed SciPy 1.18.1; record this deviation rather than claiming the full optional lock was installed/tested. A clean Linux install of the declared optional requirements is the next runtime gate.

Provider-free commands from backend:

```powershell
..\.codex_ragflow_venv\Scripts\python.exe -B -m pytest tests_ragflow -q --tb=short -p no:cacheprovider
..\.codex_ragflow_venv\Scripts\python.exe -B scripts/ragflow_local_smoke.py
.\.venv\Scripts\python.exe -B scripts/verify_ragflow_port.py --upstream-root ../.codex_ragflow_upstream
```

The fixture smoke uses deterministic vectors/tokenizer and an explicitly test-only memory backend. It proves orchestration, not native ranking quality or production latency.
