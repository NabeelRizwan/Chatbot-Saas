"""File-only provenance verification; no DB/provider/config imports."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def verify(upstream_root=None):
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "third_party/ragflow_port_manifest.json").read_text(encoding="utf-8"))
    checked = set()
    for item in manifest["files"]:
        target = (root / item["destination_path"]).resolve()
        if not target.is_relative_to(root):
            raise AssertionError("Manifest path escapes repository")
        content = target.read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["destination_sha256"], item["destination_path"]
        if item["port_action"] in {"COPY", "ADAPT"} and target.suffix == ".py":
            assert b"InfiniFlow Authors" in content and b"Apache License" in content
            if item["port_action"] == "ADAPT":
                assert b"Modified for Chatbot-SaaS" in content
        if upstream_root:
            blob = subprocess.run(["git", "-C", str(upstream_root), "show",
                item["upstream_commit"] + ":" + item["upstream_path"]], check=True, capture_output=True).stdout
            assert hashlib.sha256(blob).hexdigest() == item["upstream_sha256"], item["upstream_path"]
        checked.add(item["destination_path"])
    print(json.dumps({"provenance": "PASS", "mapped_files": len(checked), "mappings": len(manifest["files"]),
                      "official_blobs_verified": bool(upstream_root)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", type=Path)
    args = parser.parse_args()
    verify(args.upstream_root)
