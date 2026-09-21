"""Explicit one-call job; no retrieval, storage, corpus or credential export."""
import argparse
import asyncio
import importlib.metadata
import json
import os
import time

from ragflow_dev.chat import from_env, PROJECT
from ragflow_dev.provider_diagnostics import safe_diagnostic
from ragflow_derived.contracts import EngineError


async def availability(model):
    """Bounded official models/list, same client factory; no model generation."""
    result = {"visible": False, "supports_generate_content": False, "pages": 0, "complete": False}
    provider = None
    try:
        provider = model.provider_factory()
        pager = await provider.client.aio.models.list(config={"page_size": 100, "query_base": True})
        for page_index in range(10):
            result["pages"] += 1
            for item in pager.page:
                if item.name in (model.llm_name, "models/" + model.llm_name):
                    result.update(visible=True, supports_generate_content="generateContent" in (item.supported_actions or []), complete=True)
                    return result
            if not pager.config.get("page_token"):
                result["complete"] = True
                return result
            if page_index < 9:
                await pager.next_page()
        return result  # Incomplete catalog fails closed; never guesses a model.
    except Exception as exc:
        result["diagnostic"] = safe_diagnostic(exc, model.llm_name, "request")
        return result
    finally:
        if provider is not None:
            await provider.client.aio.aclose()
            provider.client.close()


async def check(model, phase):
    report = {"phase": phase, "model": model.llm_name,
        "sdk": importlib.metadata.version("google-genai"), "success": False}
    started = time.perf_counter()
    before_calls, before_tokens = model.calls, model.tokens
    try:
        if phase == "smoke":
            answer = await model.async_chat("", [{"role": "user", "content": "Return the single word OK."}],
                {"temperature": 0, "max_tokens": 16})
            report["success"] = isinstance(answer, str) and answer.strip() == "OK"
        else:
            from ragflow_derived.orchestration import prepare_query, QueryOptions
            query = "Compare opening hours and membership options for two community facilities."
            result = await prepare_query(query, [], QueryOptions(keyword=True), model)
            report["upstream_callback_parse"] = isinstance(result, str) and result.startswith(query + ",") and bool(result[len(query) + 1:].strip())
            report["success"] = report["upstream_callback_parse"]
        report["category"] = "SUCCESS" if report["success"] else "RESPONSE_PARSE"
        report["http_status"] = None  # Not exposed by upstream success return.
    except EngineError:
        report["diagnostic"] = model.last_diagnostic
    finally:
        report.update(latency_ms=round((time.perf_counter() - started) * 1000, 3),
            callback_attempts=model.calls - before_calls, recorded_tokens=model.tokens - before_tokens,
            failures=model.failures)
    return report


async def minimal_check(model):
    """One SDK request with no optional config; never runs the application adapter."""
    report = {"phase": "minimal35", "model": model.llm_name,
        "sdk": importlib.metadata.version("google-genai"), "success": False,
        "callback_attempts": 0, "recorded_tokens": None}
    started, provider = time.perf_counter(), None
    try:
        provider = model.provider_factory()
        report["callback_attempts"] = 1
        response = await provider.client.aio.models.generate_content(
            model=model.llm_name, contents="Return the single word OK.")
        report["success"] = isinstance(response.text, str) and response.text.strip() == "OK"
        report["category"] = "SUCCESS" if report["success"] else "RESPONSE_PARSE"
        report["http_status"] = None  # SDK success return does not expose status.
        if response.usage_metadata is not None:
            report["recorded_tokens"] = response.usage_metadata.total_token_count
    except Exception as exc:
        report["diagnostic"] = safe_diagnostic(exc, model.llm_name, "request")
    finally:
        if provider is not None:
            await provider.client.aio.aclose()
            provider.client.close()
        report["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return report


async def run(phase):
    if (os.environ.get("RAILWAY_PROJECT_ID") != PROJECT or
            os.environ.get("RAGFLOW_DEV_PROJECT_ID") != PROJECT or
            os.environ.get("RAGFLOW_DEV_PROVIDER_DIAGNOSTIC") != phase.upper() + "_ONCE"):
        raise RuntimeError("EXPLICIT_ISOLATED_DIAGNOSTIC_REQUIRED")
    model = from_env(PROJECT)
    if model is None:
        raise RuntimeError("EXPLICIT_TEST_CALLBACK_REQUIRED")
    model.max_calls = 2 if phase == "model35" else 1
    if phase == "minimal35":
        report = await minimal_check(model)
    elif phase == "model35":
        catalog = await availability(model)
        report = {"phase": phase, "model": model.llm_name,
            "sdk": importlib.metadata.version("google-genai"), "availability": catalog,
            "checks": [], "success": False}
        print("RAGFLOW_MODEL_AVAILABILITY " + json.dumps(report, sort_keys=True), flush=True)
        if catalog["visible"] and catalog["supports_generate_content"]:
            smoke = await check(model, "smoke")
            report["checks"].append(smoke)
            if smoke["success"]:
                report["checks"].append(await check(model, "keyword"))
                report["success"] = report["checks"][-1]["success"]
        report["callback_attempts"] = model.calls
    else:
        report = await check(model, phase)
    print("RAGFLOW_PROVIDER_DIAGNOSTIC " + json.dumps(report, sort_keys=True), flush=True)
    return report["success"]


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--phase", choices=("smoke", "keyword", "model35", "minimal35"), required=True)
        args = parser.parse_args()
        raise SystemExit(0 if asyncio.run(run(args.phase)) else 1)
    finally:
        for name in ("RAGFLOW_DEV_GEMINI_API_KEY", "RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN"):
            os.environ.pop(name, None)
