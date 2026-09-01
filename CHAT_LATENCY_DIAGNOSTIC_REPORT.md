# Chat Latency Diagnostic Report

Date: 2026-09-01  
Bot: `674 — WOWMD Joint Supplements Assistant`  
Scope: measurement only; no optimization was implemented.

## Environment health

| Component | Result |
|---|---|
| Backend | Healthy; `/health` returned 200 |
| Frontend | Healthy; dashboard loaded on port 3000 |
| PostgreSQL | Healthy; `SELECT 1` succeeded; separate observed round trip 476.6 ms |
| Redis | **Unavailable**; no listener on `localhost:6379` |
| ARQ worker | Not running; not used by the synchronous dashboard chat path |
| Gemini answer provider | Healthy during both turns on `gemini-2.5-flash` |
| Gemini embedding provider | Unstable/rate-limited; the measured turns received four `ClientError` failures each and used the existing local fallback after retries. A follow-up probe confirmed error code `429`. |

The controlled corpus remained unchanged at **10 READY documents / 573 READY chunks**. The only database change was the separately authorized test-account password reset required to enter the real frontend; no bot or knowledge data changed.

## Request totals

| Measurement | Request 1 | Request 2 |
|---|---:|---:|
| Question | Ingredients + results timeframe | `how much is it?` |
| Dashboard-reported answer pipeline | 27,256 ms | 33,433 ms |
| Full backend HTTP wall time | **32,325 ms** | **38,420 ms** |
| Browser-visible wall time | **33,263 ms** | **38,659 ms** |
| Cache | Miss | Miss |
| Retrieval | 4 chunks / 1 document | 4 chunks / 1 document |
| Structured metadata candidates | 0 | 1 |
| Final context | 3,388 characters | 3,483 characters |
| Gemini/API calls in request | 5: 4 failed embeddings + 1 answer | 5: 4 failed embeddings + 1 answer |

Request 1's first CORS preflight paid the rate-limit Redis timeout before the instrumented POST began: 4,009.425 ms. Request 2 reused the preflight but paid the same Redis wait inside its POST. Both values are included in the full backend totals.

## Stage-by-stage wall-clock breakdown

Times are exclusive where possible. Document selection is shown exclusive of the separately listed nested field/metadata work. Sub-millisecond values are retained from the diagnostic clock.

| Stage | Request 1 | Request 2 | Finding |
|---|---:|---:|---|
| A. Request/auth/quota setup, excluding Redis | 555.669 ms | 505.914 ms | Includes auth, bot authorization, and quota DB work |
| B. Query contract + history/entity resolution | 243 ms | 232 ms | Heuristic/DB work, no LLM |
| C. Answer-cache lookup | 0 ms | 1 ms | Miss; Redis call returned immediately during cooldown |
| D. Redis unavailable waits | **16,087.838 ms** | **16,071.014 ms** | Rate limit + concurrency semaphore calls |
| E. Embedding attempts/backoff, excluding Redis | **9,395.636 ms** | **9,155.075 ms** | Four failed Gemini calls, 7.3 s backoff, then fallback |
| F. Vector search | 1,019 ms | 464 ms | PostgreSQL/pgvector |
| G. Lexical search | 867 ms | 732 ms | PostgreSQL lexical queries |
| H. Document selection, exclusive | 317.843 ms | 350.936 ms | Inclusive trace was 328/360 ms |
| I. Per-field evidence retrieval | 9.735 ms | 6.658 ms | R1: ingredients + timeframe; R2: price |
| J. Structured metadata extraction | 0.422 ms | 2.406 ms | R2 produced price evidence |
| K. RRF + final ranking | 1 ms | 2 ms | Negligible |
| L. Context expansion | 49 ms | 123 ms | Same-document expansion |
| M. Context compression/build | 2 ms | 2 ms | Heuristic, no LLM |
| N. Final prompt construction | <1 ms | <1 ms | Negligible |
| O. Main Gemini generation | **2,921.978 ms** | **9,992.885 ms** | One provider call per turn |
| P. Critique | 0.466 ms | 0.063 ms | Invoked; heuristic only |
| Q. Verification | Not invoked | Not invoked | Zero verification LLM calls |
| R. Polish | 0.386 ms | 0.084 ms | Invoked; heuristic no-op, no LLM call |
| S. Source formatting | 2 ms | 1 ms | Negligible |
| T. DB persistence + usage accounting | 511.126 ms | 443.972 ms | Conversation/usage commit |
| U. SSE/buffering/response assembly | 65.821 ms | 85.313 ms | Dashboard used buffered JSON, not SSE |
| V. Frontend/local delivery overhead | 937.619 ms | 239.279 ms | Backend-ready to rendered-result difference; R1 includes polling/scheduling jitter |
| Other control-flow/instrumentation resolution | ~275 ms | ~248 ms | Reconciles clocks/rounding |

The stage totals reconcile to within about 1% of the measured browser wall times.

## Gemini calls

| Request | Purpose | Model | Attempts | Durations | Result |
|---|---|---|---:|---|---|
| 1 | Embedding | `gemini-embedding-001` | 4 | 629.372, 451.028, 449.230, 465.129 ms | All failed; existing deterministic fallback used |
| 1 | Answer generation | `gemini-2.5-flash` | 1 | **2,921.978 ms** | Success |
| 1 | Verification/polish LLM | — | 0 | — | Not invoked |
| 2 | Embedding | `gemini-embedding-001` | 4 | 517.899, 433.881, 447.013, 448.511 ms | All failed; existing deterministic fallback used |
| 2 | Answer generation | `gemini-2.5-flash` | 1 | **9,992.885 ms** | Success |
| 2 | Verification/polish LLM | — | 0 | — | Not invoked |

Embedding retry backoff was approximately 1.1 s + 2.1 s + 4.1 s = **7.3 s per request**. No answer-generation retry, timeout, or provider error was observed. The configured Gemini generation timeout is 20 seconds; both generation calls completed within it.

Exact provider token usage is not returned/persisted by the current provider wrapper (`token_usage` was null), so the following are character-based estimates rather than claimed billing tokens:

- Request 1: prompt 6,907 chars + 2,088 system chars, ~2,249 input tokens; response 395 chars, ~99 output tokens.
- Request 2: prompt 7,384 chars + 2,088 system chars, ~2,368 input tokens; response 179 chars, ~45 output tokens.

## Redis delay

Configuration: `REDIS_SOCKET_TIMEOUT=2.0` seconds, connection cooldown 5 seconds.

Each turn made seven logical `get_redis()` calls in the POST path, plus Request 1's preflight call. Four calls per user turn incurred real connection waits:

| Purpose | Request 1 | Request 2 |
|---|---:|---:|
| Rate limiting | 4,009.425 ms | 4,015.404 ms |
| Embedding semaphore release | 4,023.364 ms | 4,018.925 ms |
| LLM semaphore acquire | 4,028.221 ms | 4,026.298 ms |
| LLM semaphore release | 4,026.828 ms | 4,010.387 ms |
| Answer cache calls | ~0.006 ms total | ~0.008 ms total |
| Queue/ARQ | 0 ms | 0 ms |
| **Total unavailable-Redis waste** | **16,087.838 ms** | **16,071.014 ms** |

One logical connection/ping action takes about four seconds even though the per-socket timeout is two seconds. The most likely explanation is sequential localhost address attempts (for example IPv6 then IPv4); the client does not expose the low-level address-attempt count in current logs, so that detail is an inference. The measured fact is four paid logical Redis connection attempts per turn, approximately four seconds each.

The 5-second cooldown prevents every cache/rate-limit call from blocking, but the long embedding retry and generation intervals allow the cooldown to expire repeatedly. Cache, rate limiting, and semaphore infrastructure therefore trigger separate connection opportunities. The queue does not participate.

## Major-component percentages

Percentages use browser-visible wall time.

| Component | Request 1 | Request 2 |
|---|---:|---:|
| Unavailable Redis | **16.088 s (48.4%)** | **16.071 s (41.6%)** |
| Failed embedding attempts + backoff | **9.396 s (28.2%)** | **9.155 s (23.7%)** |
| Main Gemini generation | 2.922 s (8.8%) | **9.993 s (25.8%)** |
| Vector/lexical/document/field/ranking/context retrieval | 2.266 s (6.8%) | 1.683 s (4.4%) |
| Request/auth/quota excluding Redis | 0.556 s (1.7%) | 0.506 s (1.3%) |
| DB persistence/usage | 0.511 s (1.5%) | 0.444 s (1.1%) |
| Delivery/frontend | 1.003 s (3.0%) | 0.325 s (0.8%) |

## Top three causes

1. **Unavailable Redis:** a nearly fixed ~16.1 seconds per turn, caused mainly by rate-limit and concurrency-semaphore connection attempts.
2. **Embedding 429 retry path:** ~9.2–9.4 seconds excluding Redis, despite each failed API call taking only ~0.4–0.6 seconds; most of this is the 7.3-second retry backoff.
3. **Main Gemini generation variability:** 2.9 seconds on Request 1 and 10.0 seconds on Request 2.

Normal retrieval logic is not the primary bottleneck: vector + lexical + document/field selection + RRF + expansion + compression took about **2.27 seconds** and **1.68 seconds**.

## Conclusion

**PRIMARY BOTTLENECK:** unavailable Redis, wasting approximately **16.1 seconds per chatbot request**.

**SECONDARY BOTTLENECK:** repeated Gemini embedding 429 failures and retry backoff, wasting approximately **9.2 seconds per request** before the existing fallback is used.

**WHAT SHOULD BE OPTIMIZED FIRST:** make the normal configured Redis dependency healthy or prevent repeated unavailable-Redis connection waits. After that, diagnose the embedding endpoint's 429/quota behavior and retry policy. Main answer-generation latency should be addressed third.

No optimization, RAG change, prompt change, model change, Redis redesign, frontend change, or corpus change was implemented during this diagnostic.
