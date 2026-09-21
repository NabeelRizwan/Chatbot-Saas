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
# Modified for Chatbot-SaaS: scoped storage/model callback and namespace adaptations; see manifest.
import copy
import re
import logging
import hashlib
import json
from .runtime import native_tokenizer
from .prompts.generator import run_toc_from_text

def tokenize(d, txt, eng, language="English", tokenizer=None):
    rag_tokenizer = tokenizer or native_tokenizer
    if tokenizer is None:
        rag_tokenizer.set_language(language)
    d["content_with_weight"] = txt
    t = re.sub(r"</?(table|td|caption|tr|th)( [^<>]{0,12})?>", " ", txt)
    d["content_ltks"] = rag_tokenizer.tokenize(t)
    d["content_sm_ltks"] = rag_tokenizer.fine_grained_tokenize(d["content_ltks"])


def split_with_pattern(d, pattern: str, content: str, eng, language="English", tokenizer=None) -> list:
    docs = []

    # Validate and compile regex pattern before use
    try:
        compiled_pattern = re.compile(r"(%s)" % pattern, flags=re.DOTALL)
    except re.error as e:
        logging.warning(f"Invalid delimiter regex pattern '{pattern}': {e}. Falling back to no split.")
        # Fallback: return content as single chunk
        dd = copy.deepcopy(d)
        tokenize(dd, content, eng, language=language, tokenizer=tokenizer)
        return [dd]

    txts = [txt for txt in compiled_pattern.split(content)]
    for j in range(0, len(txts), 2):
        txt = txts[j]
        if not txt:
            continue
        if j + 1 < len(txts):
            txt += txts[j + 1]
        dd = copy.deepcopy(d)
        tokenize(dd, txt, eng, language=language, tokenizer=tokenizer)
        docs.append(dd)
    return docs



async def build_toc(docs, chat_mdl):
    docs = sorted(
        docs,
        key=lambda d: (
            d.get("page_num_int", 0)[0] if isinstance(d.get("page_num_int", 0), list) else d.get("page_num_int", 0),
            d.get("top_int", 0)[0] if isinstance(d.get("top_int", 0), list) else d.get("top_int", 0),
        ),
    )
    toc: list[dict] = await run_toc_from_text([d["content_with_weight"] for d in docs], chat_mdl)
    logging.debug("TOC_ITEMS count=%s", len(toc))
    for ii, item in enumerate(toc):
        try:
            chunk_val = item.pop("chunk_id", None)
            if chunk_val is None or str(chunk_val).strip() == "":
                logging.warning(f"Index {ii}: chunk_id is missing or empty. Skipping.")
                continue
            curr_idx = int(chunk_val)
            if curr_idx >= len(docs):
                logging.error(f"Index {ii}: chunk_id {curr_idx} exceeds docs length {len(docs)}.")
                continue
            item["ids"] = [docs[curr_idx]["id"]]
            if ii + 1 < len(toc):
                next_chunk_val = toc[ii + 1].get("chunk_id", "")
                if str(next_chunk_val).strip() != "":
                    next_idx = int(next_chunk_val)
                    for jj in range(curr_idx + 1, min(next_idx + 1, len(docs))):
                        item["ids"].append(docs[jj]["id"])
                else:
                    logging.warning(f"Index {ii + 1}: next chunk_id is empty, range fill skipped.")
        except (ValueError, TypeError) as e:
            logging.error("TOC_INDEX_CONVERSION_FAILED")
        except Exception as e:
            logging.error("TOC_INDEX_MAPPING_FAILED")

    if toc:
        d = copy.deepcopy(docs[-1])
        d["content_with_weight"] = json.dumps(toc, ensure_ascii=False)
        d["toc_kwd"] = "toc"
        d["available_int"] = 0
        d["page_num_int"] = [100000000]
        d["id"] = hashlib.sha256((d["content_with_weight"] + str(d["doc_id"])).encode("utf-8", "surrogatepass")).hexdigest()
        return d
    return None
