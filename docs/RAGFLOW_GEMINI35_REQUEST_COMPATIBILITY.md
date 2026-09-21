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

Current task live calls: **1 / 3**. Adapter smoke and upstream helper pending. SDK unchanged.
