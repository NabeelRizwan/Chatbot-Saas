# Gemini provider-boundary diagnostic

Date: 2026-09-21 UTC. Only new project `ragflow-derived-dev` (`068a5695-2cf6-4c7f-89fc-3d24a225e4a5`), backend `ragflow-dev-backend`, development branch. Starting commit `0c7bbc41326801eaa6cb8796b374ad2300972ca7`; diagnostic implementation `bab18ef5daf0f84525201b382505df2521792162`.

## Result

**GEMINI CALLBACK FAIL — HTTP 404 / NOT_FOUND / MODEL_NOT_FOUND.**

Exactly ONE direct smoke callback was attempted, with `Return the single word OK.`; zero retrieval, eight-question, holdout or upstream-component requests. The API returned a real SDK `ClientError` during the request phase, not factory construction, response parsing or cleanup. No automatic retry. No second call was justified because no incorrect model identifier or generic adapter defect was established.

Deployment/job: `bda505a0-9f40-4db6-bfe3-98d7ba2b790b`. Result timestamp: **2026-09-21T14:56:09.104311071Z**. Latency: **199.562 ms**. SDK reported **1.55.0**. Model: **gemini-2.5-flash-lite**. Recorded successful tokens: **0** (no usage supplied by the failed response; not a billing assertion). Retryable: **false**.

Safe diagnostic:

```json
{"provider":"gemini","model":"gemini-2.5-flash-lite","exception_class":"ClientError","http_status":404,"provider_code":"NOT_FOUND","provider_reason":null,"category":"MODEL_NOT_FOUND","phase":"request","retryable":false}
```

This establishes rejection at the configured Gemini Developer API model endpoint. It does NOT establish whether model availability, access for this credential, or another provider-side availability condition caused that rejection. No raw provider message or headers were captured. The earlier 503 was the application wrapper; this diagnostic reproduced the callback failure and exposed its underlying 404 safely. The old attempt did not retain its provider status, so equality of every underlying detail cannot be proven retroactively.

## Adapter audit before edits

- Installed SDK inspected directly: `google-genai==1.55.0`; native image declares the same pin. `Client(api_key=..., vertexai=False, http_options=...)`, `aio.models.generate_content`, `Content`, `Part`, `GenerateContentConfig`, `ThinkingConfig`, `aio.aclose()` and `close()` exist as used.
- Endpoint construction was exercised through the REAL installed SDK with an in-memory `httpx.MockTransport`: `/v1beta/models/gemini-2.5-flash-lite:generateContent`. No network or real key in offline tests.
- SDK `HttpOptions.timeout` is milliseconds: 60000 -> 60 seconds. `HttpRetryOptions.attempts=1` explicitly includes the original attempt and disables retries. Neither changed.
- System text maps to `system_instruction`; assistant role maps to `model`; user role remains `user`. `max_tokens` maps to `max_output_tokens`. Responses consume `response.text` and usage total. Client pools are closed in the same async loop. No structured-output/schema option is sent by this callback path.
- The pinned upstream keyword helper renders its real Jinja prompt, calls `async_chat`, accepts string/tuple, removes a think-prefix, checks its error marker, and returns keyword text; query preparation appends that text. It is not a JSON-schema parser. No upstream prompt/parser/orchestration changed.
- Google's [model reference](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite) lists the configured stable model code, and its [thinking reference](https://ai.google.dev/gemini-api/docs/generate-content/thinking) documents budget 0 for Flash-Lite. This validates the published identifier/configuration, NOT availability for this particular key/endpoint. Actual smoke failed despite those documented contracts; no model name was guessed or substituted.

## Changes and tests

Only provider-boundary diagnostics were added: fixed enum/class/status/reason allowlists, bounded phase labels, boolean retryability and last safe diagnostic. No exception string, request/response headers, provider message, environment value or arbitrary metadata is serialized. Unknown strings are discarded. API behavior, request configuration, model and error propagation remain unchanged.

Files changed for implementation:

- `backend/ragflow_dev/chat.py`
- `backend/ragflow_dev/provider_diagnostics.py`
- `backend/tests_ragflow/test_provider_diagnostics.py`
- `dev/ragflow/provider_diagnostic.py`
- `Dockerfile.ragflow-dev` (copy the standalone diagnostic job only)

Focused tests: **18/18 PASS** (4 existing boundary tests + 14 new diagnostics/actual-SDK transport cases). Syntax PASS. Diff whitespace check PASS. Tests cover authentication/permission/quota/model-not-found/invalid-request/network/timeout/SDK/parse categorization, secret-shaped/error-message suppression, unknown-field rejection, actual request/response mapping, resource closure and exactly one HTTP attempt. An initial test assertion assumed camelCase for a nested SDK field; inspection showed SDK 1.55.0 serializes `thinking_budget`, and only that test assertion was corrected. No runtime workaround was introduced.

## Cleanup and restrictions

The failed job stopped. Process credential names are cleared by its finally block. The one-shot pre-deploy command is removed and its nonsecret gate cleared; no automatic replay is enabled. The key was used only by the service-side SDK and never exported, printed, downloaded, changed or saved outside Railway. The pre-existing healthy API remains available. A subsequent report-only deployment can install the diagnostics normally without calling Gemini.

No retrieval implementation, 0.2 cutoff, lexical/vector weighting, top-k, upstream prompts, keyword/rewrite/TOC logic, embedding/reranker models or evidence caps changed. The established four-query cutoff finding is unchanged. No corpus writes, production access, old90, holdout, main push/merge or force push. Pre-existing unrelated untracked work remains intact. Provider call count this task: **1 / 3 maximum**; upstream callback parse: **NOT RUN**.

## Next action

Confirm which Gemini Developer API model is actually available to the dedicated test credential/project. The configured identifier is published, but this API request rejects it with 404. Do not replace the key or guess a new model on this evidence alone. Any model-list/access diagnostic or replacement configuration needs a separately scoped continuation. The frozen expanded validation remains blocked and must not resume automatically.
