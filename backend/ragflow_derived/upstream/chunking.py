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
from enum import Enum
from .runtime import num_tokens_from_string

class MergeStrategy(Enum):
    """How ``merge_paragraphs`` groups delimiter-split paragraphs into chunks.

    ``OVER_CAP`` (default) greedily accumulates adjacent paragraphs while the
    projected total stays within ``token_size``; when the next paragraph would
    exceed ``token_size``, it is still merged (one boundary overflow is allowed),
    then the chunk is closed. ``UNDER_CAP`` only merges when the projected total
    still fits the soft ``token_size`` target and never overflows. Switching
    strategy is a single enum value — no logic change elsewhere.
    """

    UNDER_CAP = "under_cap"
    OVER_CAP = "over_cap"


def _merge_paragraph_groups(paragraphs, token_size, strategy, size, overlapped_percent=0):
    """Return index groups of ``paragraphs`` per ``strategy``.

    ``paragraphs`` are already split on the delimiter and contain no delimiter
    text. No atom-split is ever performed: a paragraph larger than ``token_size``
    becomes its own chunk. ``size(paragraph)`` returns the token count.

    The OVER_CAP merge decision uses the overlap-scaled threshold
    ``token_size * (100 - overlapped_percent) / 100`` so the grouping reserves
    room for the unconditional overlap prefix (unified JSON strategy). At
    ``overlapped_percent == 0`` the threshold equals ``token_size``, so grouping
    is identical to the prior ``prev_t + cur_t <= token_size`` rule — including
    the one-boundary-overflow close — keeping ``merge_paragraphs``/``txt_parser``
    output unchanged.
    """
    cap = token_size
    threshold = token_size * (100 - overlapped_percent) / 100.0
    n = len(paragraphs)
    groups = []

    if strategy == MergeStrategy.UNDER_CAP:
        cur = []
        cur_tokens = 0
        for i in range(n):
            p = paragraphs[i]
            if not cur:
                cur = [i]
                cur_tokens = size(p)
                if cur_tokens > cap:
                    groups.append(cur)
                    cur = []
                    cur_tokens = 0
                continue
            if cur_tokens + size(p) <= cap:
                cur.append(i)
                cur_tokens += size(p)
            else:
                groups.append(cur)
                cur = [i]
                cur_tokens = size(p)
                if cur_tokens > cap:
                    groups.append(cur)
                    cur = []
                    cur_tokens = 0
        if cur:
            groups.append(cur)
        return groups

    # OVER_CAP (default): a new chunk starts when the current chunk's running
    # token sum exceeds the (overlap-scaled) ``threshold``; an over-budget unit
    # always stands alone (#17799). The scaled threshold reserves room for the
    # unconditional overlap prefix (unified JSON strategy). At overlap=0 the
    # threshold equals ``token_size``, so grouping is identical to the prior
    # ``prev_t + cur_t <= token_size`` rule (incl. the one-boundary-overflow
    # close).
    cur, cur_t = [], 0
    for i in range(n):
        pt = size(paragraphs[i])
        if pt > cap:
            if cur:
                groups.append(cur)
            groups.append([i])
            cur, cur_t = [], 0
            continue
        if not cur:
            cur, cur_t = [i], pt
            continue
        if cur_t > threshold:
            groups.append(cur)
            cur, cur_t = [i], pt
        else:
            cur.append(i)
            cur_t += pt
    if cur:
        groups.append(cur)
    return groups


def merge_paragraphs(paragraphs, token_size, strategy=MergeStrategy.OVER_CAP, size=None, overlapped_percent=0):
    """Group delimiter-split ``paragraphs`` into chunks using ``strategy``.

    Pure function: no pos / PDF coordinate handling, no atom-split. Returns a
    list of chunks, each a list of the original paragraph strings (order and
    identity preserved). ``token_size`` is a soft target; see ``MergeStrategy``.

    ``size`` defaults to ``num_tokens_from_string`` and is resolved at call
    time (not captured at definition) so tests can monkeypatch the tokenizer
    deterministically via ``rag.nlp.num_tokens_from_string``.

    Chunking contract (refs #17799)
    --------------------------------
    * **Delimiter is a chunk boundary.** The delimiter text specified by the
      user never enters a chunk. ``naive_merge`` / ``naive_merge_with_images``
      split every section on the delimiter (except the empty-delimiter
      size-only mode) so boundary text cannot leak into a chunk.
    * **``token_size`` is a soft target + merge strategy.** There is no
      atom-split: a paragraph larger than ``token_size`` stands alone as its own
      chunk and is truncated later by the model layer.
    * **Default strategy is ``OVER_CAP``.** A migration that needs the old
      strict behaviour can opt into ``UNDER_CAP``.
    * **``OVER_CAP`` has no hard cap** (the model layer truncates oversize
      units); **``UNDER_CAP`` enforces a strict cap** and never overflows
      ``token_size``.
    """
    if size is None:
        size = num_tokens_from_string
    groups = _merge_paragraph_groups(paragraphs, token_size, strategy, size, overlapped_percent)
    return [[paragraphs[i] for i in g] for g in groups]
