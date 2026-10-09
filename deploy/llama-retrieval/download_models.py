"""Build-time download of pinned public models; runtime never downloads weights."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['TIKTOKEN_CACHE_DIR'] = str(ROOT / 'models/tiktoken')


def main():
    from huggingface_hub import snapshot_download
    import nltk
    import tiktoken
    expected = json.loads((ROOT / 'model-artifacts.json').read_text(encoding='utf-8'))
    for model in expected['models']:
        destination = ROOT / 'models' / model['role']
        snapshot_download(repo_id=model['repository'], revision=model['revision'],
            local_dir=str(destination), allow_patterns=[row['path'] for row in model['files']],
            token=False, max_workers=2)
        for row in model['files']:
            with (destination / row['path']).open('rb') as handle:
                actual = hashlib.file_digest(handle, 'sha256').hexdigest()
            if actual != row['sha256']:
                raise RuntimeError('Model artifact checksum mismatch: ' + row['path'])
    tiktoken.get_encoding('cl100k_base')
    for row in expected['tokenizer']['files']:
        if hashlib.sha256((ROOT / 'models/tiktoken' / row['path']).read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('Context tokenizer checksum mismatch')
    for resource in ('stopwords', 'punkt_tab'):
        if not nltk.download(resource, download_dir=str(ROOT / 'models/nltk_data'), quiet=True, raise_on_error=True):
            raise RuntimeError('NLTK resource download failed')
    for row in expected['nltk']:
        if hashlib.sha256((ROOT / 'models/nltk_data' / row['path']).read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('NLTK resource checksum mismatch: ' + row['path'])


if __name__ == '__main__':
    main()
