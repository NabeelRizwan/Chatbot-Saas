#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
# Modified for Chatbot-SaaS: lazy injected dependencies; see port manifest.
"""Explicit, lazy dependencies for the port; never reads application settings."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

PAGERANK_FLD = "pagerank_fea"
TAG_FLD = "tag_fea"
ES_SETTINGS = SimpleNamespace(DOC_ENGINE_INFINITY=False, DOC_ENGINE_OCEANBASE=False,
                              DOC_ENGINE_SERENEDB=False, DOC_ENGINE_GAUSSDB=False)


async def thread_pool_exec(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


class NativeTokenizer:
    """The release's Infinity tokenizer, lazy to avoid import-time asset/network work."""
    def __init__(self):
        self._instance = None

    def __getattr__(self, name):
        if self._instance is None:
            try:
                from infinity.rag_tokenizer import RagTokenizer
                self._instance = RagTokenizer()
            except (ImportError, OSError, SystemExit):
                from ..contracts import EngineError
                raise EngineError("TOKENIZER_UNAVAILABLE", "native tokenizer/assets") from None
        aliases = {"tradi2simp": "_tradi2simp", "strQ2B": "_strQ2B"}
        return getattr(self._instance, aliases.get(name, name))


native_tokenizer = NativeTokenizer()


class NativeSynonyms:
    """Pinned dictionary + installed WordNet. No Redis/downloads or silent fallback."""
    def __init__(self):
        self.dictionary = json.loads(Path(__file__).with_name("res").joinpath("synonym.json").read_text(encoding="utf-8"))

    def lookup(self, token, topn=8):
        import re
        result = self.dictionary.get(token.strip().lower(), [])
        if result:
            return ([result] if isinstance(result, str) else result)[:topn]
        if re.fullmatch("[a-z]+", token):
            from nltk.corpus import wordnet
            return sorted({syn.name().split(".")[0].replace("_", " ") for syn in wordnet.synsets(token)} - {token})[:topn]
        return []


def num_tokens_from_string(text):
    import tiktoken
    return len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))


def truncate(text, length):
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return enc.decode(enc.encode(text, disallowed_special=())[:max(0, length)])


def decode_text(blob, document_type="text"):
    if isinstance(blob, str):
        return blob, "unicode"
    # No replacement characters that could silently change evidence.
    for codec in ("utf-8-sig", "utf-16"):
        try:
            return blob.decode(codec), codec
        except UnicodeError:
            continue
    raise ValueError("PARSER_FAILED: unsupported text encoding")


def get_text(filename, binary=None):
    if binary is None:
        binary = Path(filename).read_bytes()
    return decode_text(binary)[0]
