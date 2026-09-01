# Chat Latency Fix Report

Scope: Redis health and Gemini embedding retry behavior only. Bot 674; corpus unchanged at 10 READY documents / 573 READY chunks.

## 1. Redis root cause

No Redis-compatible server was running on `localhost:6379`. Each chat therefore crossed repeated 2-second socket/connect failures from cache, rate-limit, and concurrency paths; the prior diagnostic measured about 16.1 seconds of Redis-related wait per request. On this Windows host, `localhost` also attempted IPv6 before the IPv4-only temporary server, adding one 2.0-second timeout on the first connection.

## 2. Redis fix

The repository's intended runtime remains Redis 7 from `docker-compose.yml`; no Redis architecture changed. Docker/WSL were unavailable on this host, so the live validation used an official Memurai 4.1.2 Redis-compatible binary extracted to a temporary directory, not installed as a Windows service. Local configuration now uses `redis://127.0.0.1:6379/0`; the Docker services continue to use `redis://redis:6379/0` unchanged.

Live checks passed: PING, cache set/get, tenant cache, atomic sliding-window rate limit, distributed semaphore acquire/release, and ARQ pool PING. Representative timings were 0.38–0.92 ms per cache/rate/semaphore operation and 3.71 ms to create, ping, and close an ARQ pool.

## 3. Redis before/after latency

- Before: approximately 16,100 ms per chatbot request.
- Final chat POST: 2.264 ms across measured Redis commands.
- Including the cold CORS preflight and first connection: 19.653 ms.
- No Redis timeout or retry occurred during the final chat.

## 4. Exact embedding 429 cause

The live provider response was HTTP 429 / `RESOURCE_EXHAUSTED` for:

`aiplatform.googleapis.com/global_embed_content_requests_per_minute_per_base_model`

Base model: `gemini-embedding`. This is a requests-per-minute base-model quota, not a token or daily quota. The response contained no `Retry-After` header and no structured `RetryInfo` delay.

The credential is `GEMINI_API_KEY` loaded from `backend/.env`; no `GOOGLE_CLOUD_PROJECT` or `GCP_PROJECT` is configured. The provider response did not expose the owning project identifier, so it was not printed or inferred from the secret.

## 5. Retry-policy change

Embedding failures are now classified by status and provider payload:

- Temporary per-minute/per-second 429: honor provider delay when present; otherwise allow one short bounded retry (default 1.1 seconds).
- Daily, zero-value, billing-disabled, or project-restriction quota: no retry sleep; use the existing allowed fallback/error policy immediately.
- Retryable 408/5xx/timeouts: retain the existing bounded resilience policy.
- Other 4xx/provider-unavailable failures: fail fast.
- Provider delays above the 30-second safety bound are not slept through in a user request.

Retries were not removed globally.

## 6. Embedding before/after latency

- Before on repeated 429: approximately 9,200 ms including four failed calls and 1.1 + 2.1 + 4.1 seconds of sleeps.
- Final live chat: 741 ms embedding stage; one successful provider call was 639.756 ms; zero retries.
- A no-delay RPM failure is now bounded to two total attempts and one 1.1-second sleep instead of four attempts and 7.3 seconds of sleeps.

Stored compatibility was preserved: all 573 READY chunks use `gemini-embedding-001`, version 1, at 768 dimensions. Query embeddings remain `gemini-embedding-001`; no provider/model switch or re-embedding occurred.

## 7. Fallback safety

Deterministic embeddings remain a development/test aid. `APP_ENV=production` or `prod` unconditionally disables them even if `ALLOW_DETERMINISTIC_EMBEDDING_FALLBACK=true`. Production Compose also explicitly sets the flag false. No production-reachable fake-vector fallback was found.

## 8. Final Gemini generation latency

Main Gemini `gemini-2.5-flash` answer generation: 3,203 ms. It was one generation call with no retry. Total provider calls were two: one embedding and one answer generation.

## 9. Final retrieval latency

- Retrieval pipeline: 2,679 ms, including the 741 ms embedding stage.
- Non-embedding retrieval work: approximately 1,938 ms.
- Result: 4 chunks from 1 document, resolved to `Turmeric Boost`; cache miss; context length 3,388 characters.

## 10. Final backend/browser latency

- Dashboard response latency displayed by the frontend: 6,317 ms.
- Full `ChatTrace`, including post-answer work: 6,709 ms.
- Request edge to traced completion, including cold preflight/setup: 7,352 ms; the answer rendered immediately afterward (approximately 7.4 seconds browser-visible).

Major shares of traced backend time: generation 47.7%; retrieval including embedding 39.9%; everything else 12.3%. Redis was 0.034% of the traced POST time.

## 11. Answer/source correctness

Exact dashboard question asked once:

> What are the ingredients of Turmeric Boost and how soon willl i see results?

Answer returned:

> Turmeric Boost contains Organic Turmeric (Curcuma Longa) Root, Turmeric 95% Curcuminoids (Curcuma Longa) Root, Organic Ginger Extract (Zingiber officinale) Root, and BioPerine® (Black Pepper Extract). Regarding results, individual experiences vary; some users might notice support for joint comfort or digestive balance within 4–8 weeks of consistent daily use, while others may need more time.

Correctness: correct and field-complete for the indexed page. Source: `Turmeric Boost`, canonical URL `https://www.wowmd.com/products/turmeric-boost`. No RAG, prompt, corpus, or frontend change was made.

## 12. Tests

- New focused retry tests: 4 passed in 8.721 seconds (RPM bounded retry, non-recoverable quota fail-fast, structured RetryInfo, production fallback prohibition).
- Requested scoped regression run: 100 passed in 62.672 seconds. It covered Phase L.2, Phase L, cache/DB, Redis/rate-limit/concurrency, Phase E streaming/widget parity, embedding resilience, and RAG retrieval hardening.
- Python syntax validation: passed.
- Live Redis protocol checks: passed, including ARQ pool PING.
- Corpus after tests: 10 READY documents / 573 READY chunks.

## 13. Remaining bottleneck

The largest normal component is now Gemini answer generation (3.203 seconds in this run), followed by retrieval (2.679 seconds). The Google project still has a low per-minute embedding quota: a request can succeed and an immediate subsequent request can receive the measured RPM 429. The new policy removes repeated waste but cannot increase provider quota; Google Cloud quota/project configuration must be raised for concurrent pilot traffic.

## Verdict

CHAT LATENCY IMPROVED — PROVIDER LIMITATION REMAINS
