# Private BGE service

This is a deployable boundary around the same official CrossEncoder path used
in the combination tests. It imports no validation runners and makes no Gemini
or other generation calls. The application's embedding provider remains separate.

`POST /rerank` requires `Authorization: Bearer <COMBINED_RERANKER_TOKEN>` and JSON
`{"query":"question","documents":["Title: ...\nContent:\n..."]}`. Documents are
scored in their supplied order. The response contains `model`, `revision`,
`scores` and `token_counts`. Scores are raw classification logits, not native
similarity scores or probabilities. The caller retains document IDs and sorts
stably by scores.

At most 32 documents and 1 MiB of JSON are accepted. Every complete query/document
pair is preflighted with the model's actual processor. Any pair above 8,192 tokens
rejects the entire request with HTTP 422 before inference. No passage is truncated.
Inference uses float32, SDPA, Identity activation and batch size 1. One request can
score at a time, with at most two others waiting for up to 60 seconds; excess or
expired requests receive HTTP 503. The server accepts at most eight connections,
leaving connection capacity for health and authorization while scoring is queued,
closes each after its reply,
and bounds request-body reads to ten seconds. Input failures return 400/411/413/415;
busy, unloaded or failed inference returns 503 with a safe category. Queries,
passages, credentials and exception details are not logged.

`GET /health` exposes only readiness, pinned model/revision, device, dtype and
batch size. `GET /ready` exposes the same fields but requires the scoring bearer
token, allowing the backend to check credentials without inference. Model identity
and every required artifact SHA-256 are checked at
startup. Missing/changed weights or runtime package versions fail startup. All
model loading is local-only; downloads happen only in `service.prefetch` during
the image build. `COMBINED_RERANKER_TOKEN` is mandatory and must be supplied by the
deployment secret store; do not publish this service on a public domain.

Build from the `deploy/bge-reranker` directory:

```sh
docker build -t combined-bge-reranker .
```

The image explicitly uses CPU. Its dependency versions come from the tested
Python 3.12 environment. The Linux image has been built and deployed in the
destination Chatbot-SaaS Railway project; its isolated contract suite passed
14 tests with one skipped on 2026-09-30. Verify startup and measure peak memory,
full-length latency and concurrent capacity on each deployment's hardware.
The weights alone occupy 2.27 GB and float32 inference needs additional memory.
Do not assume the small existing TEI allocation can serve this model. Long
passages near 8,192 tokens can cost substantially more memory/time than the
tested short passages.

For an explicitly configured local GPU runtime use `BGE_DEVICE=cuda` with the
tested `torch==2.10.0+cu126`, the same other requirements, and an existing verified
snapshot directory in `BGE_MODEL_DIR`. CPU uses `torch==2.10.0+cpu`. CUDA availability
and compiled device architecture are checked; there is no silent CPU fallback.
`BGE_THREADS` accepts 1–8 (default 2). `PORT` defaults to 8080.
`BGE_QUEUE_WAIT_SECONDS` defaults to 60 and must be positive and at most 90.
The app client's 120-second request timeout includes both queueing and scoring.
CPU capacity and worst-case passage latency must therefore be measured with this
combined budget; the bounded queue does not make an undersized CPU fast enough.

A local CPU smoke test with two threads took 47.89 seconds to score 32 recorded
pairs (maximum 675 tokens each), after a 24.99-second model load. Its full ordering
matched the saved GPU run; the largest logit difference was 0.0000098. This is
one local measurement, not Railway throughput or worst-case latency validation.

The 2026-09-30 deployed CPU comparison used four threads and scored 512 pairs
across 16 requests. All ten cases matched the saved full order and merged context
using frozen retrieval and query plans. Eight had complete expected evidence;
the two known IKEA misses remained. Lanes took 47.8–61.2 seconds in that run;
a later repeat of one 32-pair lane took 30.2 seconds at four threads. These are
variable sequential observations, not a capacity guarantee. More threads did
not consistently improve latency. Complete destination widget validation and
concurrent-load measurements remain separate release checks.

Tests use a local ephemeral HTTP listener and mocked scoring, with no model or
provider downloads:

```sh
python -m unittest service.test_service
```

## Provenance

- [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3/tree/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e),
  revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, Apache-2.0.
- [Sentence Transformers 6.1.0](https://github.com/huggingface/sentence-transformers/tree/b0bf39968ba461c34b29372144794eff1be06f6d),
  Apache-2.0: unmodified `CrossEncoder.preprocess` and `CrossEncoder.predict`
  provide all tokenization and relevance computation.
- Transformers 5.17.0, Hugging Face Hub 1.7.2, PyTorch 2.10.0. Apache-2.0 text is
  retained in `LICENSE`; installed distributions retain their own license files.
- `model-artifacts.json` contains byte lengths and SHA-256 values from the frozen
  tested model snapshot. The new adapter adds only service, lifecycle and input
  validation; it does not add learned scoring or query-specific rules.
