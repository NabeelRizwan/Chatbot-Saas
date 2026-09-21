"""Build-time only: download pinned public weights and tokenizer assets."""
from pathlib import Path
import nltk
import tiktoken
from huggingface_hub import snapshot_download
from ragflow_dev.config import EMBED_MODEL, EMBED_REVISION, RERANK_MODEL, RERANK_REVISION


def main():
    for package in ("wordnet", "omw-1.4", "punkt", "punkt_tab", "averaged_perceptron_tagger_eng"):
        if not nltk.download(package, download_dir="/opt/nltk_data", quiet=True, raise_on_error=True):
            raise RuntimeError("NLTK_ASSET_MISSING")
    tiktoken.get_encoding("cl100k_base")
    patterns = ["*.json", "*.txt", "model.safetensors", "README.md", "LICENSE*"]
    for role, model, revision in (("embedding", EMBED_MODEL, EMBED_REVISION),
                                   ("reranker", RERANK_MODEL, RERANK_REVISION)):
        snapshot_download(model, revision=revision, local_dir=str(Path("/opt/models") / role),
                          allow_patterns=patterns)
    from ragflow_derived.upstream.runtime import native_tokenizer, NativeSynonyms
    assert native_tokenizer.tokenize("Library services include books.")
    NativeSynonyms().lookup("library")
    from ragflow_dev.models import CpuModels
    CpuModels()
    print("Native tokenizer and pinned CPU model build smoke: PASS")


if __name__ == "__main__":
    main()
