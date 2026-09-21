"""Explicit one-call job; no retrieval, storage, corpus or credential export."""
import argparse
import asyncio
import importlib.metadata
import json
import os
import time

from ragflow_dev.chat import from_env, PROJECT
from ragflow_derived.contracts import EngineError


async def run(phase):
    if (os.environ.get("RAILWAY_PROJECT_ID") != PROJECT or
            os.environ.get("RAGFLOW_DEV_PROJECT_ID") != PROJECT or
            os.environ.get("RAGFLOW_DEV_PROVIDER_DIAGNOSTIC") != phase.upper() + "_ONCE"):
        raise RuntimeError("EXPLICIT_ISOLATED_DIAGNOSTIC_REQUIRED")
    model = from_env(PROJECT)
    if model is None:
        raise RuntimeError("EXPLICIT_TEST_CALLBACK_REQUIRED")
    model.max_calls = 1
    report = {"phase": phase, "model": model.llm_name,
        "sdk": importlib.metadata.version("google-genai"), "success": False}
    started = time.perf_counter()
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
        # SDK success does not expose a response status via the upstream callback.
        report["http_status"] = None
    except EngineError:
        report["diagnostic"] = model.last_diagnostic
    finally:
        report.update(latency_ms=round((time.perf_counter() - started) * 1000, 3),
            callback_attempts=model.calls, recorded_tokens=model.tokens, failures=model.failures)
    print("RAGFLOW_PROVIDER_DIAGNOSTIC " + json.dumps(report, sort_keys=True), flush=True)
    return report["success"]


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--phase", choices=("smoke", "keyword"), required=True)
        args = parser.parse_args()
        raise SystemExit(0 if asyncio.run(run(args.phase)) else 1)
    finally:
        for name in ("RAGFLOW_DEV_GEMINI_API_KEY", "RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN"):
            os.environ.pop(name, None)
