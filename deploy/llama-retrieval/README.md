# LlamaIndex knowledge service

The widget and SaaS API keep their existing authentication, quotas, conversations,
bot settings, Gemini/OpenAI selection, citations, PostgreSQL, Redis and ingestion
workers. `KNOWLEDGE_ENGINE=llamaindex` selects this service for evidence. RAGFlow
and the separate BGE reranker are not required for this mode.
An unset `KNOWLEDGE_ENGINE` preserves the existing `ragflow` deployment. The API
and worker must both be explicitly configured with `llamaindex` during rollout.

Question → scoped conversation → bot-provider follow-up resolution when needed
→ LlamaIndex dense + BM25 search → reciprocal-rank fusion → MiniLM reranking
→ bounded source evidence → existing bot-provider answer → existing widget.

Direct questions need no planning call. Ambiguous follow-ups ask for clarification.
Static pages do not supply private order lookups or live inventory verification.
Conversation history is bounded at 120 messages / 100,000 characters; oversize
histories ask the user to start a new conversation rather than silently cutting it.

## Retrieval configuration

- BGE-small-en-v1.5 ONNX embeddings; full-precision MiniLM-L6 cross-encoder on CPU.
- 280-token chunks, 40-token overlap, 64 passage pairs; named comparisons can
  use 96 pairs. Broad discovery can also rank up to 20 document summaries.
- 12 evidence cores, adaptive maximum 16; 4,000-token context with bounded
  adjacent passages, table headers and source attribution.
- Product exclusions and alternatives resolve against corpus titles, including
  unambiguous shortened titles. No website names or expected answers are encoded.
- 96 model-token query limit. Oversize questions ask for shorter questions.
- Model revisions and checksums are in `model-artifacts.json`; public artifacts
  download during image build. Inference uses local files without a generative API.

The production package includes neither the manual planning/answer bridge nor
benchmark corpora, transcripts, reports or saved expected answers. Model code and
adaptations retain their upstream licenses and attribution.

## Answer generation

A normal successful answer uses one final call to the bot's selected provider;
existing bounded transport retries still apply. The model receives the verified
retrieved context and the existing business instructions with a general evidence
policy. It returns a natural customer answer. There is no answer JSON protocol,
block-label layer, forced source rendering, second AI judge or repair call.
Auxiliary conversation planning retains its existing JSON behavior.

Source authority, document versions, context integrity and answer links are
checked by the application. The model still decides how facts support the user's
request and how to phrase the answer. The evidence policy asks it to preserve
qualifiers, distinguish unknown information from contradictions, and avoid
transferring another item's properties. These instructions do not guarantee
semantic correctness. Provider/model answer-quality limitations remain separate
from retrieval correctness.

Provider failures and empty responses produce the existing safe retryable widget
error and release the message reservation. Warnings log only the failure stage
and category, without prompts, source text, credentials or raw provider errors.

## Deployment

No deployment is performed by these files. For the next approved release:

Stage these changes as a coordinated release. Keep the API and worker on their
current engine until the private retrieval service is healthy and reachable;
do not set the new engine on only one of them. Keep existing services available
until the new widget path is validated.

1. Add one private service in **Chatbot-SaaS-Production**, with repository root
   `/deploy/llama-retrieval` and its `Dockerfile`. Set the service and its volume
   to the same Southeast Asia region as the API and worker. Do not expose a
   public domain. Attach a volume at `/data/retrieval`.
2. Generate a random secret of at least 32 printable ASCII characters. Set the
   same `LLAMA_RETRIEVAL_TOKEN` on retrieval, API and worker. Set
   `LLAMA_RETRIEVAL_URL=http://<private-service-host>:8000` on API and worker;
   keep their current engine selected until step 5. If the platform overrides
   `PORT`, use that internal port in the URL. The retrieval image honors `PORT`.
   Its listener accepts IPv4 and IPv6, including older environments with IPv6-only
   private DNS ([Railway private domains](https://docs.railway.com/networking/domains/working-with-domains)).
3. Retain all existing database, Redis, storage, crawler, encryption and bot AI
   credentials. No database migration, account reset or source deletion is needed.
4. Build the images and confirm the private retrieval service is ready. Run
   existing database migrations as usual, then run
   `python scripts/warm_knowledge.py --all` in a one-off API/worker process with
   `KNOWLEDGE_ENGINE=llamaindex` set for that process only.
   It reads authorized ready source text and builds new caches; it does not rewrite
   the original documents or their previous RAGFlow bindings.
5. Set `KNOWLEDGE_ENGINE=llamaindex` on both API and worker in the coordinated
   rollout. Verify API `/health/ready` and a real widget session. Test the actual selected
   Gemini/OpenAI provider before release. A provider-stub test validates wiring and
   evidence delivery, not the quality or latency of an external model's answers.

The main Compose file includes this private service. Supply
`LLAMA_RETRIEVAL_TOKEN` through the Compose environment; do not commit a secret.
The retrieval build context excludes tests, models, caches, local settings and data.

## Generation timeouts

`LLM_TIMEOUT` on the API/worker is the shared retry/transport budget for each
generation call (default 30 seconds). Each retry receives only the remaining
budget, with the existing 20-second Gemini/OpenAI/xAI attempt cap and 30-second
Anthropic cap. A retry is skipped when its required wait and minimum transport
deadline cannot fit. Gemini requires a minimum 10-second server deadline.
Keep `LLM_TIMEOUT` above 10 seconds for Gemini so setup leaves a usable attempt;
the default 30 seconds is unchanged.
Auxiliary planning retains its existing separate caller deadline and bounded
executor. Successful requests add no calls or waiting, and the selected bot model
and provider never change as a timeout fallback.

This is not a whole-chat wall-clock guarantee: retrieval, credential lookup,
database work and SDK network phases are separate. The widget reports a temporary
service failure when generation exhausts its retry budget; it never substitutes
an unsupported answer. Raising `LLM_TIMEOUT` also requires reviewing worker,
proxy and concurrency-permit lease limits. Keep this setting unchanged when
rolling the knowledge engine back; it governs provider calls in both engines.

## Source lifecycle and capacity

Only database-owned bot/org documents in the active completed crawl are searchable.
An immutable corpus fingerprint includes text, title, URL, version and crawl.
Every returned span and table header is checked against that snapshot, and the
database is checked again before generation and delivery. Source revocation or a
service failure uses the existing retry/quota-release path; there is no fallback
to another bot, stale knowledge or the legacy engine.

Ingestion validates parsing and builds the complete proposed corpus before atomic
source promotion. The proposed snapshot is inaccessible to chat until the database
activates that version. The worker rechecks the resulting corpus after commit;
concurrent source changes can require a new snapshot. Failed staging retains the
previous source version. Ingestion statistics do not claim per-page parsing alone
created vectors; the shared index tracks its actual vector count.
Existing ready datasets are usable from their stored text without recrawling.

This service deliberately uses one worker, four model threads and one loaded corpus
at a time. Excess work waits at most five seconds for admission, then receives a
retryable 503. This is not a demonstrated multi-tenant concurrency capacity claim.
Switching bots may reload an index/model; cold index build time is separate from
warm retrieval time. Add separately measured replicas when higher capacity is needed.

Disk caches default to 2 GiB, 32 snapshots and 24 hours of inactivity. Periodic
cleanup releases expired engines and removes expired caches; active source data
in PostgreSQL is never deleted. Configure `LLAMA_CACHE_MAX_BYTES`,
`LLAMA_CACHE_MAX_ENTRIES`, `LLAMA_CACHE_TTL_SECONDS` and `LLAMA_DATA_DIR` on retrieval
only. Capacity failures are explicit 507 errors rather than unbounded storage growth.

Legacy RAGFlow modules and bindings are retained for an explicit rollback. Selecting
`KNOWLEDGE_ENGINE=ragflow` also requires its former services/settings and valid native
bindings. Sources changed after switching must be reindexed into RAGFlow before
rollback; switching an environment variable alone cannot recreate those bindings.

## Local checks

Run `python -m pytest tests -q` from this directory in the pinned retrieval runtime
(pytest is a test-only dependency). Run
`python -m unittest test_llama_rag test_provider_time_budget test_gemini_error_mapping test_llm_retry_wait_budget -v` in
`backend` for isolated database/provider-boundary checks. These do not call an AI
provider. Keep real dataset acceptance results outside the repository.
