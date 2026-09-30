# Private BGE ranking service

This required internal service supplies ranking scores to the SaaS
backend. PostgreSQL, Redis, ingestion, accounts, bots and answer providers remain
owned by the existing platform. It neither generates answers nor stores queries.

Build from this directory with `docker build -t chatbot-bge .`. The image fetches
the exact tested model revision and verifies its artifact hashes at build time.
Startup loads local weights only. See `service/README.md` for the complete
scoring contract, provenance and dependency pins.

Required service secret: `COMBINED_RERANKER_TOKEN`. Put the same value in the
backend's `RAG_COMBINED_RERANKER_TOKEN`. Use a private network endpoint ending in
`/rerank` for `RAG_COMBINED_RERANKER_URL`; never put this secret in the widget.
The embedding service and Gemini credentials do not change.

The image uses CPU float32. The model weights alone occupy about 2.27 GB.
At most three ranking
requests are admitted, one scores at a time, and queue waiting is bounded.
An overloaded or unavailable service returns a typed error; it does not silently
substitute a different model or incomplete input.

As of 2026-09-30, the Linux image is deployed in the destination Chatbot-SaaS
project. Its isolated service suite passed 14 tests with one skipped. A controlled
ten-case run through the deployed scorer exactly reproduced saved ranking orders
and merged contexts for frozen retrieval candidates and query plans; the two
known IKEA evidence gaps remained. This does not establish full live retrieval,
answer quality or concurrent throughput.

The destination uses `BGE_THREADS=4`; the code default remains two threads.
Initial deployed scoring took 47.8–61.2 seconds per 32-pair lane, while a later
repeat of one lane took 30.2 seconds. CPU response times vary with workload and
available resources. Measure full-length inputs and concurrent traffic against
the client's timeout; increasing threads is not a guaranteed speed improvement.

The backend checks the authenticated `/ready` endpoint before declaring itself
ready. `/health` remains a lightweight service liveness/model check. Neither
probe performs inference.

Before each release, verify the private service and a complete widget flow
through the destination SaaS backend. The September 30 eight-case widget run
completed with exact authored answer delivery and one quota charge per turn;
scorer parity alone does not establish evidence completeness or answer quality.
There is no switch back to the old ranking path; rollback uses the previous
application release.
