"""Image-build-only download. Runtime never invokes this entry point."""
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download
from .scorer import MODEL, REVISION, verify_artifacts


def main():
    import json
    manifest = json.loads(Path(__file__).with_name("model-artifacts.json").read_text())
    names = [row["path"] for row in manifest]
    snapshot = Path(snapshot_download(repo_id=MODEL, revision=REVISION, token=False,
                                     cache_dir="/tmp/bge-build-cache", allow_patterns=names))
    root = Path("/model")
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(snapshot / name, root / name)
    verify_artifacts(root)
    # Only the fixed build cache under /tmp belongs to this image-build step.
    shutil.rmtree("/tmp/bge-build-cache")


if __name__ == "__main__":
    main()
