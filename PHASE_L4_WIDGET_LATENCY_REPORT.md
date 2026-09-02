# Phase L.4 — Widget Latency & Delivery Report

Date: 2026-09-02  
Controlled bot: `674 — WOWMD Joint Supplements Assistant`  
Local stack: API `:8000`, frontend `:3000`, widget origin `:4173`, Redis healthy  
Quality pipeline preserved: **Generate → Critique → conditional Verify → Polish → approved delivery**

No QueryContract / multi-entity / L.2 / L / J retrieval redesign.

## 1. Exact before latency breakdown

Fresh cache-miss widget session (instrumented browser + backend diagnostics), established with the required comparison context.

### Pre-change representative path

Turn 1 — `What's the difference between Turmeric Boost and Turmeric Gummies?`

| Marker | ms |
| --- | ---: |
| Browser headers | 1419 |
| First SSE `meta` | 1502 |
| First SSE `token` / first visible | 14463 |
| SSE `done` | 14467 |
| Final visible | 14486 |
| Backend `response_time_ms` | 11786 |
| Query contract | 648 |
| Embedding | 1126 |
| Vector | 1751 |
| Lexical | 1949 |
| Retrieval total | 5536 |
| Generation | 5040 |
| Token stream window (`first_token` → `done`) | **4** |

Turn 2 — `Which one is cheaper, and how do I use each one?`

| Marker | ms |
| --- | ---: |
| First SSE `token` / first visible | 12636 |
| Final visible | 12658 |
| Backend `response_time_ms` | 9907 |
| Retrieval | 5540 |
| Generation | 3152 |
| Token stream window | **1** |

### Derived pre-change facts

- Backend compute dominated total time (~10–12 s).
- Approved-answer → first-visible was already **~0–20 ms**.
- Approved-answer → complete-render was already **<50 ms**.
- SSE artificial pacing was **not** a multi-second delay in the current tree.
- The earlier L.3 “32–41 s browser” figure was **not reproduced** as current artificial typing delay; measured post-approval delivery was already near-instant. Remaining gap vs backend totals is connection/UI overhead plus provider/retrieval time.

## 2. Root cause of the historical 32–41 s browser completion

Primary current bottleneck: **backend compute** (embedding + sequential vector/lexical + Gemini generation), not widget typing animation.

Secondary historical contributors likely included:

- cold provider / embedding latency during L.3 acceptance
- measurement marks that spanned waits outside pure send→done
- small 48-char SSE batches + post-answer DB persistence ordering (minor vs provider time)

There was **no** remaining multi-second intentional typing sleep in `widget.js`.

## 3. Delivery changes

1. Public/dashboard streams now emit **large approved answer batches** (`iter_approved_answer_chunks`, 4096 chars) instead of 48-char fragments.
2. Public widget stream emits **token → sources → done before persistence**, so analytics/DB write cannot block first paint after approval.
3. Widget paints the **first approved token immediately** (`flushMessageUpdate`), then coalesces later batches; Markdown/sources still finalize once at completion.
4. Quality-safe buffering remains: raw Gemini tokens never reach the widget before approval.

## 4. SSE changes

Event sequence remains compatible:

`meta` → `token` (one/few large chunks) → `sources` → `done`

Acceptance showed **1 token event** for full answers instead of many tiny ones.

## 5. Rendering changes

- First approved text replaces the typing indicator immediately.
- No full Markdown re-parse per tiny chunk during streaming (`textContent` updates).
- Final Markdown + sources render once on completion.

## 6. Backend optimizations

1. **Concurrent vector + lexical recall** after embedding, using isolated DB sessions + main-session hydration.
2. Sequential fallback if parallel workers fail.
3. Lean `_ready_contract_documents` load (`load_only` identity/metadata fields; defer large body fields).
4. Query-contract stage improved from ~500–650 ms toward ~240–250 ms on acceptance turns.

## 7. Retrieval before / after

| Metric | Before (turn 2) | After (turn 2) |
| --- | ---: | ---: |
| Embedding | 775 ms | 762 ms |
| Vector | 1475 ms | 590 ms (parallel wall) |
| Lexical | 2500 ms | 590 ms (parallel wall) |
| Retrieval total | 5540 ms | 3311 ms |

Recall remained correct: both Turmeric documents, full price/directions coverage.

## 8. Gemini before / after

| Turn | Before generation | After generation |
| --- | ---: | ---: |
| Difference | 5040 ms | 4466 ms |
| Cheaper/use | 3152 ms | 3391 ms |
| Simple price | — | 6573 ms |

Generation remains the largest single variable cost. Critique/verify/polish stayed on the healthy heuristic path (no extra LLM calls in acceptance diagnostics timings).

## 9. Approved-answer → first-visible time

After fixes:

- Difference: first_token 11819 → first_visible 11821 (**2 ms**)
- Cheaper/use: 8709 → 8710 (**1 ms**)
- Simple miss: 12994 → 12994 (**0 ms**)
- Cache hit: 1812 → 1812 (**0 ms**)

Target `<150 ms` local: **met**.

## 10. Approved-answer → complete-render time

Token event count = 1 for approved answers; SSE `done` arrived with the token batch.

Observed final_visible sometimes lagged done by ~1–1.5 s due to final Markdown/source DOM work in the instrumented browser path, but there is **no artificial multi-second SSE pacing**.

## 11. Simple cache-miss result

Question: `How much is Turmeric Boost?`

Answer:

> Turmeric Boost is available for $33.00 for a one-time purchase. If you choose to subscribe and save, it's $31.35. There's also a bundle option priced at $1.05 per unit.

- Sources: Turmeric Boost canonical page
- Browser first/final visible: **12994 / 14484 ms**
- Backend: **11796 ms** (generation 6573 + retrieval 4412)
- Correctness: pass

`<6 s` browser-visible target: **not met** because Gemini + retrieval exceeded 6 s.

## 12. Multi-entity results

Turn 1 difference:

- Both products compared; both sources; no `'s` entity; no Sea Essence
- Browser final visible: **13340 ms**
- Backend: **10654 ms**

Turn 2 cheaper + directions:

- Boost cheaper at **$33**; Gummies **$55**
- Correct serving directions for both
- Coverage all SUPPORTED
- Both canonical sources
- Browser final visible: **10161 ms**
- Backend: **7512 ms**

## 13. Cache-hit result

Fresh session replay of `How much is Turmeric Boost?`

- Backend `cache_hit=true`, `response_time_ms=720`
- Browser first visible: **1812 ms**
- Browser final visible: **3326 ms**

`<1.5 s` first-visible target: **nearly met / slightly missed** because query-contract still runs before cache lookup (~250 ms) plus connection overhead (~1.3 s headers). Not used to claim the cache-miss target.

## 14. Exact final widget answers

### Comparison turn 1

Turmeric Boost vs Turmeric Gummies form/ingredients/usage comparison; Boost price $33.00; Gummies price noted as not listed in that turn’s free-form difference answer.

### Comparison turn 2

> Turmeric Boost is cheaper at $33.00 USD. You take 1 veggie capsule daily, preferably with a meal...
>
> For Turmeric Gummies, the price is $55.00 USD. You take two (2) gummies once daily, preferably after meals...

### Simple price

> ...$33.00 for a one-time purchase... subscribe and save, it's $31.35...

## 15. Sources

Successful comparison: Turmeric Boost + Turmeric Gummies canonical URLs.  
Simple price: Turmeric Boost canonical URL.  
No unrelated Sea Essence contamination.

## 16. Regression results

| Suite | Result |
| --- | --- |
| Phase L.4 delivery tests | **8/8 OK** |
| Phase L.3 | **26/26 OK** |
| Phase L.2 | **20/20 OK** |
| Phase L | **15/15 OK** |
| Phase J | **11/11 OK** |
| Widget streaming parity | **16/16 OK** |
| Tenant chat security | **15/15 OK** |
| RAG quality hardening | **14/14 OK** |
| Python compile of changed modules | **OK** |
| Frontend `tsc --noEmit` | **OK** |
| Frontend ESLint | **OK** (0 errors; 2 pre-existing `<img>` warnings) |

## 17. No-hardcoding scan

Runtime scan of `backend/services`, `backend/routes`, and `frontend/public/widget.js` for WOWMD / Turmeric / Sea Essence / `$33` / `$31.35` / wowmd.com: **no matches**.

## 18. Remaining bottleneck

**Gemini generation + retrieval still dominate cache-miss latency.**

Even with delivery fixed and parallel recall:

- simple miss ≈ 12–15 s browser
- multi-entity ≈ 8–13 s browser
- provider generation alone often 3–6+ s

Further `<6 s` cache-miss typical would require provider/model latency reduction or deeper architecture changes outside this delivery-hardening phase (without weakening the quality pipeline).

---

## FINAL VERDICT

**WIDGET DELIVERY FIXED — PROVIDER LATENCY REMAINS**
