# Gemini 3.5 Flash-Lite request compatibility

Date: 2026-09-21. Starting development HEAD: `c63abb6961c47d68d73bf3061f3b75774a7fa2dd`.
Scope: ONLY `ragflow-derived-dev` / backend `92349a32-e92d-4795-b86e-338929b03059`.
The existing Railway-only key is unchanged and its value is not inspected/exported. No retrieval tests or retrieval changes.

## Pre-call inventory (application unchanged)

The actual installed SDK 1.55.0 was exercised with an in-memory HTTP transport and an offline placeholder credential, not the real key. The request body below reproduces the prior failed smoke request through `GeminiProvider._async_chat`. No headers were captured or printed.

Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent`.

```json
{
  "contents": [{"role": "user", "parts": [{"text": "Return the single word OK."}]}],
  "generationConfig": {
    "temperature": 0.0,
    "maxOutputTokens": 16,
    "thinkingConfig": {"thinking_budget": 0}
  }
}
```

| Field | Current value/shape (prior smoke) | Source in our code | Supported by Gemini 3.5 Flash-Lite? | Required by RAGFlow? | Action |
| --- | --- | --- | --- | --- | --- |
| model | `gemini-3.5-flash-lite` in URL | `ragflow_dev/chat.py:MODEL`; SDK | Yes; already visible with generation support | A configured callback model | Keep |
| contents / roles | One final `user` turn | `upstream/gemini.py:_async_chat` | Yes | Message transport | Keep |
| parts | One `Part(text=...)`, nonempty text | Same function | Yes | Text transport | Keep exact text |
| assistant/model prefill | Absent | Smoke history; assistant maps to model for other calls | No prefill to validate here | No | Keep absent in smoke |
| empty turns | None | Smoke history | No empty final turn | No | Preserve nonempty final user turn |
| system_instruction | Absent (empty string not added) | `_async_chat` conditional | Text system instructions supported | Actual keyword helper supplies its prompt here | Omit in smoke; preserve helper prompt verbatim |
| thinking_config.thinking_budget | `0`; SDK serializes nested key as `thinking_budget` | `_async_chat` default; installed SDK `models.py` pass-through | Suspect: numeric budget is legacy; full thinking-off is not supported for Gemini 3 Flash/Flash-Lite | No; provider default, not prompt logic | Omit in minimal experiment; evaluate removal after result |
| thinking_level | Absent | No mapping | `minimal`, `low`, `medium`, `high`; Flash-Lite default minimal | No explicit level required | Prefer omission/default |
| candidate_count | Absent, not injected | `_clean_conf` allowlist | Gemini 3.x migration says unsupported | No | Never present; keep omitted |
| temperature | `0.0` (helper normally asks for 0.2) | Diagnostic smoke / upstream helper, forwarded by provider | Exposed but customization discouraged | Upstream requests it; transport compatibility may omit without changing prompt | Omit in minimal experiment |
| top_p | Absent | Allowed only if supplied | Customization discouraged | Not required for smoke/keyword | Omit |
| top_k | Absent | Not allowlisted | Customization discouraged | No | Omit |
| max_output_tokens | `16` | Diagnostic `max_tokens`, provider renames | Supported; includes thoughts; tiny cap risks truncation | Not required by SDK | Omit from minimal call; preserve application caller limits if adapter repaired |
| stop_sequences | Absent | Not allowlisted | Optional API field; unused | No for these calls | Omit |
| response_mime_type / response_schema | Absent | Not allowlisted | Supported capabilities, unused | Keyword helper consumes text, not JSON schema | Omit |
| tools / tool_config | Absent | Not constructed | Model supports tools, unused | No | Omit |
| custom safety settings | Absent | Not constructed | Optional, unused | No | Omit |
| conversation history | Only the one user turn | Diagnostic smoke | Legal single-turn text request | No earlier conversation required | Keep |

The legacy provider also maps assistant roles to `model`, extracts a leading system message into `systemInstruction`, and filters system-role turns from contents. The actual keyword helper uses its unchanged rendered upstream prompt as the system instruction and the nonempty user text `Output: `. Neither smoke nor helper has assistant prefill.

## Current official contract

Google's current migration guide discourages custom sampling values, says to use thinking levels instead of numeric budgets, and lists candidate count as unsupported for Gemini 3.x. It strongly recommends SDK 2.0.0+, with breaking-change discussion centered on Interactions. This is not proof that SDK 1.55.0 cannot issue this basic generateContent call. No upgrade is made before the minimal experiment. [Migration guide](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5).

Flash-Lite supports minimal/low/medium/high thinking and defaults to minimal. The thinking guide says full thinking-off is unsupported for Gemini 3 Flash/Flash-Lite, while also documenting general legacy-budget compatibility. Therefore `thinking_budget=0` is suspect, not a proven specific cause from the previous redacted 400 alone. A 16-token cap includes thought tokens and can truncate output. [Thinking contract](https://ai.google.dev/gemini-api/docs/generate-content/thinking).

The generateContent API permits a content-only body; generation config and system instruction are optional. Content roles are user/model with text parts. The installed SDK's locally serialized minimal body contains only `contents`. [API reference](https://ai.google.dev/api/generate-content). The exact model is stable. [Model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).

## Bounded execution plan / live ledger

1. Minimal call: same key/model/SDK/base URL and retry limit one. SDK invocation supplies only model and the exact smoke string; no config, including no output cap.
2. Only after minimal PASS: correct the generic development adapter compatibility and run one adapter smoke.
3. Only after adapter PASS: one actual upstream keyword helper call.

Maximum three generateContent attempts in this task, no retries. No per-field live experiment. A multi-field cleanup cannot by itself prove which individual field caused the prior 400; report causal uncertainty explicitly.

### Call 1: minimal request PASS

Deployment `4d08e056-2526-40de-9832-39119f238b18`, diagnostic commit `ffc3f7d11ab8b68a4afa50b0648413c3595321f3`. At 2026-09-21 15:26:45 UTC, the guarded `minimal35` job reported PASS: exact output `OK`, 1013.301 ms, 8 total tokens, one generateContent attempt, SDK 1.55.0. No optional request config. SDK success result does not expose an HTTP status; none fabricated. The one-shot hook/gate were then cleared without a redeploy.

This establishes credential/model/endpoint/basic SDK compatibility and rules out a required SDK upgrade for this minimal request. The former body differed in three optional settings; a unique offending field is **NOT PROVEN**. Local inspection identifies the legacy zero thinking budget (and its nested serialization) as the principal suspect; temperature customization is discouraged and the tiny output cap is unnecessary for this diagnostic. No one-call-per-field experiments.

### Intended development adapter after minimal PASS

`ragflow_dev/gemini35.py` preserves the upstream text/system/role and usage mapping, uses no thinking configuration (model default minimal), no custom sampling or candidate count, and retains any explicitly requested application output bound. It rejects invalid text roles/empty turns or non-user final turns before network access. Caller history/config are not mutated. The original upstream Gemini provider, prompts, keyword parsing and retrieval orchestration remain untouched; only the development provider factory selects this compatibility adapter.

The new direct adapter smoke uses the exact smoke prompt without the old test-only 16-token cap or temperature. The actual helper still supplies its unchanged system prompt and nonempty `Output: ` user turn; its inherited temperature preference is not sent to Gemini 3.5. SDK 1.55.0 serializes the text system instruction as `systemInstruction: {role: "user", parts: [{text: ...}]}` and an empty `generationConfig`; this matches its pre-existing system-instruction conversion. Focused offline transport tests verify these wire bodies and conditional no-retry call limits.

### Calls 2 and 3: application adapter and real helper PASS

Development adapter commit: `8136c0926da39e87adecda1bfe620f07a05b8c4c`.
Deployment: `ea22b4ac-ccee-4eb4-abca-add7593b7038`.
Railway deployment status: **SUCCESS**, 2026-09-21 15:32:58.517 UTC; corrected development revision promoted. No separate health/build-history audit was rerun.
Guarded command: `python -B dev/ragflow/provider_diagnostic.py --phase adapter35`.

At 2026-09-21 15:32:33 UTC the job recorded:

| Call | Result | Measured latency | Total tokens reported | Attempts |
| --- | --- | --- | --- | --- |
| 1: minimal SDK | PASS; exact `OK` | 1013.301 ms | 8 | 1 |
| 2: actual application adapter | PASS; exact `OK` | 20253.489 ms | 8 | 1 |
| 3: upstream RAGFlow keyword helper | PASS; upstream parsing/nonempty augmentation | 7559.652 ms | 118 | 1 |

The helper called `prepare_query(..., QueryOptions(keyword=True), model)` on the authorized generic community-facilities sentence. Its real `keyword_extraction` function rendered the unchanged upstream Jinja prompt, invoked the actual development Gemini callback, applied the existing parser, and returned a nonempty suffix appended to the original query. This was not a retrieval call or a substitute prompt. Offline tests compare the exact rendered system prompt and serialized user turn, and live validation confirms the resulting augmentation. No JSON schema was added.

**Total generateContent calls: 3 / 3.** No retries, extra metadata checks, field-by-field generation experiments, or SDK changes. Successful SDK results did not expose HTTP status; reports record `SUCCESS` rather than inventing status metadata. Reported usage totals 134 tokens across the three calls. Latencies are individual provider-callback observations, not retrieval or production benchmarks.

The temporary adapter hook and nonsecret diagnostic gate were cleared after the successful job, with deploys skipped. Readback verifies `preDeployCommand: []`. No secrets were read/exported and no additional deployment was triggered for cleanup or reporting.

## Causal conclusion

**ROOT INVALID_ARGUMENT CAUSE: NOT PROVEN at individual-field level.** Request-configuration compatibility is restored: same credential, model, endpoint and SDK work with minimal settings, both directly and through the actual upstream helper. The former zero thinking budget is the principal documented suspect; custom temperature and the tiny test-only output cap were also removed. Neither the previous safe error nor these bounded experiments isolates one of those fields, or conclusively establishes that snake_case nested serialization was rejected. Do not claim a proven serialization bug, a bad key, missing model, or required SDK upgrade.

## Final validation / preservation

- Focused tests: **32/32 PASS**, actual installed SDK with offline HTTP transport; no test provider quota. The first new exact-body expectations omitted the SDK-added system-instruction role; those test expectations were corrected to match observed serialization before the passing run. No runtime workaround was needed for that assertion mismatch.
- `git diff --check`: PASS.
- Application adapter changed: YES, development-only provider compatibility.
- Thinking configuration: omitted, documented Flash-Lite default minimal.
- Candidate count: never present; remains absent.
- Sampling: temperature/top_p/top_k omitted at the development provider boundary.
- SDK: `google-genai 1.55.0`, upgrade NO.
- Original upstream provider, RAGFlow prompts/query logic/TOC, retrieval services, dependencies and vendored upstream: unchanged against starting HEAD.
- Threshold 0.2, blend 0.7/0.3, candidate/top-k limits, embeddings/reranker, evidence/context limits: unchanged.
- Eight generic questions / GENERIC_HOLDOUT_B / old90 / GOLD / customer corpus: NOT RUN / NOT USED.
- Production project: NOT TOUCHED. No model/key change in this task.
- Main refs unchanged: local `06f2d5d4c78805f54e818cc3886cf2438e5990cf`, origin/main `7c8236001ccc552c89c860b2db6a4d4c369ee211`.
- Only development branch commits/pushes used to execute the authorized diagnostics. All pre-existing untracked work preserved. Final measured report update remains local to avoid a report-only deployment.

## Final decision

**REQUEST COMPATIBILITY VALIDATION PASS.** The previously frozen expanded RAGFlow validation is ready to resume as a separately authorized task. It was not started here. Exact optional-field attribution remains unresolved; no further calls are authorized in this task.
