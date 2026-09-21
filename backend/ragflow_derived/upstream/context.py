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
# Modified for Chatbot-SaaS; see third_party/ragflow_port_manifest.json.
import logging
import re
from .runtime import num_tokens_from_string

def get_value(item, first, second):
    return item.get(first) or item.get(second) or ''

def kb_prompt(kbinfos, max_tokens, hash_id=False):
    chunks = kbinfos["chunks"]
    knowledges = [get_value(ck, "content", "content_with_weight") for ck in chunks]
    kwlg_len = len(knowledges)
    used_token_count = 0
    selected_chunks = []
    for ck, c in zip(chunks, knowledges):
        if not c:
            continue
        chunk_tokens = num_tokens_from_string(c)
        if max_tokens * 0.97 < used_token_count + chunk_tokens:
            logging.warning(f"Not all the retrieval into prompt: {len(selected_chunks)}/{kwlg_len}")
            break
        used_token_count += chunk_tokens
        selected_chunks.append(ck)

    def draw_node(k, line):
        if line is not None and not isinstance(line, str):
            line = str(line)
        if not line:
            return ""
        return f"\n├── {k}: " + re.sub(r"\n+", " ", line, flags=re.DOTALL)

    knowledges = []
    for i, ck in enumerate(selected_chunks):
        cnt = "\nID: {}".format(i if not hash_id else get_value(ck, "id", "chunk_id"))
        cnt += draw_node("Title", get_value(ck, "docnm_kwd", "document_name"))
        cnt += draw_node("URL", ck.get("url", ""))
        meta = ck.get("document_metadata") or {}
        for k, v in meta.items():
            cnt += draw_node(k, v)
        cnt += "\n└── Content:\n"
        cnt += get_value(ck, "content", "content_with_weight")
        knowledges.append(cnt)

    return knowledges
