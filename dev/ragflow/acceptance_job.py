"""Explicit one-shot Railway pre-deploy test client; never part of API startup.

Uses injected service credentials without exporting them through operator tools.
Only synthetic non-secret results are emitted in bounded log records.
"""
import base64
import hashlib
import json
import os
import time

from native_acceptance import Client, initial, verify_pack


def main():
    from ragflow_dev.config import Settings
    Settings.from_env()  # Exact isolated project/private dependency guard.
    mode = os.environ.get("RAGFLOW_DEV_ACCEPTANCE_PHASE", "")
    if mode not in ("initial", "persistence"):
        raise RuntimeError("EXPLICIT_ACCEPTANCE_PHASE_REQUIRED")
    started = time.perf_counter()
    client = Client(os.environ["RAGFLOW_DEV_ACCEPTANCE_URL"])
    if mode == "initial":
        report = initial(client)
    else:
        before = json.loads(os.environ["RAGFLOW_DEV_SENTINEL_EXPECTED"])
        result = client.call("POST", "/ragflow-dev/context", {
            "query": "Persistence sentinel code", "document_ids": ["doc-sentinel"]})
        verify_pack(result, "a")
        assert result["context"] == before["context"]
        assert result["citations"] == before["citations"]
        report = {"restart_persistence": "PASS", "sentinel_after_restart": result}
    report["phase"] = mode
    report["elapsed_seconds"] = time.perf_counter() - started
    raw = json.dumps(report, separators=(",", ":")).encode()
    # Defensive assertion before publishing results; never log credential values.
    for key in ("RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN"):
        assert os.environ[key].encode() not in raw
    encoded = base64.b64encode(raw).decode()
    pieces = [encoded[i:i + 1400] for i in range(0, len(encoded), 1400)]
    print("NATIVE_ACCEPTANCE_BEGIN " + json.dumps({"phase": mode, "pieces": len(pieces),
          "sha256": hashlib.sha256(raw).hexdigest()}), flush=True)
    for index, piece in enumerate(pieces):
        print(f"NATIVE_ACCEPTANCE_DATA {mode} {index} {piece}", flush=True)
    print("NATIVE_ACCEPTANCE_END " + mode, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exception text is deliberately suppressed; line/type is enough to locate
        # an assertion without risking URL/header/credential-bearing tracebacks.
        import traceback
        frames = traceback.extract_tb(exc.__traceback__)
        print("NATIVE_ACCEPTANCE_FAILED " + json.dumps({"type": type(exc).__name__,
              "frames": [{"file": os.path.basename(f.filename), "line": f.lineno}
                         for f in frames]}), flush=True)
        raise SystemExit(1) from None
    finally:
        for key in ("RAGFLOW_DEV_TOKEN_A", "RAGFLOW_DEV_TOKEN_B", "RAGFLOW_DEV_ADMIN_TOKEN"):
            os.environ.pop(key, None)
