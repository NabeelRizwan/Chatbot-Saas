# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import logging
import re
from enum import Enum
from .runtime import num_tokens_from_string
from .delim import DEFAULT_DELIMITER, normalize_text_newlines, parse_delimiter_field, has_wrapped_delimiter, compile_delimiter_pattern
from .image_utils import concat_img

def _compute_overlap_prefix(prev_text, overlapped_percent):
    """Return (overlap_text, overlap_token_count) carved from the tail of ``prev_text``.

    ``prev_text`` is treated as if HTML/PDF markup has been stripped, so the carve
    index is computed against the visible characters, matching the existing
    behaviour of ``RAGFlowPdfParser.remove_tag`` callers above.
    """
    visible = re.sub(r"@@[\t0-9.-]+?##", "", prev_text or "")
    if not visible:
        return "", 0
    overlap_start = int(len(visible) * (100 - overlapped_percent) / 100.0)
    overlap_text = visible[overlap_start:]
    return overlap_text, num_tokens_from_string(overlap_text)


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


def _reconstruct_text_chunk(paragraphs, group):
    """Rebuild a chunk string from a ``merge_paragraphs`` group, re-attaching
    ``pos`` (PDF coordinate tag) per the historical caller convention: append
    ``pos`` to a paragraph when it is not already present in the running text.
    """
    text = ""
    for idx in group:
        ptext, ppos = paragraphs[idx]
        new_text = text + ptext
        if ppos and ptext.find(ppos) < 0 and new_text.find(ppos) < 0:
            new_text += ppos
        text = new_text
    return text


def _reconstruct_image_chunk(paragraphs, group):
    """Like ``_reconstruct_text_chunk`` but also concatenates the image of every
    merged paragraph (mirrors the previous ``concat_img`` dedupe behaviour).
    """
    text = ""
    image = None
    for idx in group:
        ptext, ppos, pimg = paragraphs[idx]
        new_text = text + ptext
        if ppos and ptext.find(ppos) < 0 and new_text.find(ppos) < 0:
            new_text += ppos
        text = new_text
        if pimg is not None:
            image = pimg if image is None else concat_img(image, pimg)
    return text, image


def _apply_overlap_unconditional(chunks, overlapped_percent):
    """Prepend an overlap prefix from the previous chunk at each new-chunk
    boundary, UNCONDITIONALLY when ``overlapped_percent > 0`` (unified JSON
    strategy). The prefix is never dropped for not fitting the budget, so
    context is continuous across every chunk boundary; a chunk may therefore
    exceed ``chunk_token_num`` by up to the overlap amount.
    """
    if overlapped_percent <= 0:
        return chunks
    out = []
    for i, c in enumerate(chunks):
        if i == 0:
            out.append(c)
            continue
        overlap_text, _ = _compute_overlap_prefix(out[-1], overlapped_percent)
        if overlap_text:
            out.append(overlap_text + c)
        else:
            out.append(c)
    return out


def naive_merge(sections: str | list, chunk_token_num=128, delimiter=DEFAULT_DELIMITER, overlapped_percent=0, strategy=MergeStrategy.OVER_CAP):
    """Split sections into chunks. Chunking contract: see ``merge_paragraphs`` (refs #17799)."""
    if not sections:
        return []
    if isinstance(sections, str):
        sections = [sections]
    if isinstance(sections[0], str):
        sections = [(s, "") for s in sections]
    # Normalize line endings so delimiter ``\n`` matches ``\r\n`` and standalone ``\r``.
    sections = [(normalize_text_newlines(s), pos) for s, pos in sections]

    # Parse the delimiter field once, via the canonical helper (#17383).
    # `has_custom` means the field contains a backtick-wrapped token — the
    # historical signal that chunk_token_num should be bypassed: each segment is
    # its own chunk.
    parsed_dels = parse_delimiter_field(delimiter)
    has_custom = has_wrapped_delimiter(delimiter)
    if has_custom:
        # Custom delimiters ignore chunk_token_num: each segment is its own chunk.
        custom_pattern = compile_delimiter_pattern(parsed_dels)
        cks = []
        for sec, pos in sections:
            split_sec = re.split(r"(%s)" % custom_pattern, sec, flags=re.DOTALL) if custom_pattern else [sec]
            for sub_sec in split_sec:
                if not sub_sec:
                    continue
                if custom_pattern and re.fullmatch(custom_pattern, sub_sec):
                    continue
                text = "\n" + sub_sec
                local_pos = pos
                if num_tokens_from_string(text) < 8:
                    local_pos = ""
                if local_pos and text.find(local_pos) < 0:
                    text += local_pos
                cks.append(text)
        return cks

    # Default path: split every section on the delimiter into paragraphs (no
    # delimiter text), then group paragraphs with the chosen merge strategy.
    # No atom-split is performed: a paragraph larger than ``chunk_token_num``
    # becomes its own chunk; the model layer truncates oversize units.
    #
    # A section is split on the delimiter whenever one is present -- even when
    # the whole section already fits ``chunk_token_num``. The delimiter is a
    # chunk boundary and its text must never leak into a chunk; only the
    # empty-delimiter (size-only) mode below skips splitting.
    dels = compile_delimiter_pattern(parsed_dels)
    paragraphs = []  # list of (text, pos)
    for sec, pos in sections:
        if not dels:
            paragraphs.append(("\n" + sec, pos))
            continue
        for sub_sec in re.split(r"(%s)" % dels, sec, flags=re.DOTALL):
            if not sub_sec or re.fullmatch(dels, sub_sec):
                continue
            paragraphs.append(("\n" + sub_sec, pos))

    groups = _merge_paragraph_groups([p[0] for p in paragraphs], chunk_token_num, strategy, num_tokens_from_string, overlapped_percent)
    cks = [_reconstruct_text_chunk(paragraphs, g) for g in groups]
    logging.debug("naive_merge: %d sections -> %d chunks (delimiter=%r)", len(sections), len(cks), delimiter)
    return _apply_overlap_unconditional(cks, overlapped_percent)


def naive_merge_with_images(texts, images, chunk_token_num=128, delimiter=DEFAULT_DELIMITER, overlapped_percent=0, strategy=MergeStrategy.OVER_CAP):
    """Split texts (with images) into chunks. Chunking contract: see ``merge_paragraphs`` (refs #17799)."""
    if not texts or len(texts) != len(images):
        return [], []

    # Parse the delimiter field once, via the canonical helper (#17383).
    # See ``naive_merge`` for the ``has_custom`` rationale.
    parsed_dels = parse_delimiter_field(delimiter)
    has_custom = has_wrapped_delimiter(delimiter)
    if has_custom:
        # Custom delimiters ignore chunk_token_num: each segment is its own chunk.
        custom_pattern = compile_delimiter_pattern(parsed_dels)
        cks, result_images = [], []
        for text, image in zip(texts, images):
            text_str = text[0] if isinstance(text, tuple) else text
            if text_str is None:
                text_str = ""
            text_str = normalize_text_newlines(text_str)
            text_pos = text[1] if isinstance(text, tuple) and len(text) > 1 else ""
            split_sec = re.split(r"(%s)" % custom_pattern, text_str) if custom_pattern else [text_str]
            for sub_sec in split_sec:
                if not sub_sec:
                    continue
                if custom_pattern and re.fullmatch(custom_pattern, sub_sec):
                    continue
                text_seg = "\n" + sub_sec
                local_pos = text_pos
                if num_tokens_from_string(text_seg) < 8:
                    local_pos = ""
                if local_pos and text_seg.find(local_pos) < 0:
                    text_seg += local_pos
                cks.append(text_seg)
                result_images.append(image)
        return cks, result_images

    # Default path: split every text on the delimiter into paragraphs (no
    # delimiter text) carrying its image, then group with the merge strategy.
    # Images of merged paragraphs are concatenated; no atom-split is performed.
    # As in ``naive_merge``, a small text is still split on the delimiter so
    # the boundary text never leaks into a chunk; only empty-delimiter skips.
    dels = compile_delimiter_pattern(parsed_dels)
    paragraphs = []  # list of (text, pos, image)
    for text, image in zip(texts, images):
        # if text is tuple, unpack it
        if isinstance(text, tuple):
            text_str = text[0] if text[0] is not None else ""
            text_pos = text[1] if len(text) > 1 else ""
        else:
            text_str = text or ""
            text_pos = ""
        text_str = normalize_text_newlines(text_str)
        if not dels:
            paragraphs.append(("\n" + text_str, text_pos, image))
            continue
        for sub_sec in re.split(r"(%s)" % dels, text_str, flags=re.DOTALL):
            if not sub_sec or re.fullmatch(dels, sub_sec):
                continue
            paragraphs.append(("\n" + sub_sec, text_pos, image))

    groups = _merge_paragraph_groups([p[0] for p in paragraphs], chunk_token_num, strategy, num_tokens_from_string, overlapped_percent)
    cks, result_images = [], []
    for g in groups:
        text, image = _reconstruct_image_chunk(paragraphs, g)
        cks.append(text)
        result_images.append(image)
    logging.debug("naive_merge_with_images: %d texts -> %d chunks (delimiter=%r)", len(texts), len(cks), delimiter)
    return _apply_overlap_unconditional(cks, overlapped_percent), result_images


def _build_cks(sections, delimiter):
    cks = []
    tables = []
    images = []

    # Parse the delimiter field once, via the canonical helper (#17383).
    # Split on every parsed delimiter (bare and wrapped). `has_custom`
    # only controls whether _merge_cks bypasses chunk_token_num (wrapped
    # token present in the original field).
    parsed_dels = parse_delimiter_field(delimiter)
    has_custom = has_wrapped_delimiter(delimiter)
    split_pattern = compile_delimiter_pattern(parsed_dels)
    pattern = r"(%s)" % split_pattern if split_pattern else ""

    seg = ""
    for text, image, table in sections:
        # normalize text: ensure string and prepend newline for continuity
        if not text:
            text = ""
        else:
            text = "\n" + normalize_text_newlines(str(text))

        if table:
            # table chunk
            ck_text = text + str(table)
            idx = len(cks)
            cks.append(
                {
                    "text": ck_text,
                    "image": image,
                    "ck_type": "table",
                    "tk_nums": num_tokens_from_string(ck_text),
                }
            )
            tables.append(idx)
            continue

        if image:
            # image chunk (text kept as-is for context)
            idx = len(cks)
            cks.append(
                {
                    "text": text,
                    "image": image,
                    "ck_type": "image",
                    "tk_nums": num_tokens_from_string(text),
                }
            )
            images.append(idx)
            continue

        # pure text chunk(s) — split on every parsed delimiter when present
        if split_pattern:
            split_sec = re.split(pattern, text)
            for sub_sec in split_sec:
                if not sub_sec:
                    continue

                # ① matched delimiter (exact capture; do not strip — wrapped
                # whitespace delimiters such as `` ` ` `` or `\n` must match here)
                if re.fullmatch(split_pattern, sub_sec):
                    if seg and seg.strip():
                        s = seg.strip()
                        cks.append(
                            {
                                "text": s,
                                "image": None,
                                "ck_type": "text",
                                "tk_nums": num_tokens_from_string(s),
                            }
                        )
                    seg = ""
                    continue

                # ② empty or whitespace-only ordinary segment → flush current buffer
                if not sub_sec.strip():
                    if seg and seg.strip():
                        s = seg.strip()
                        cks.append(
                            {
                                "text": s,
                                "image": None,
                                "ck_type": "text",
                                "tk_nums": num_tokens_from_string(s),
                            }
                        )
                    seg = ""
                    continue

                # ③ normal text content → accumulate
                seg += sub_sec
        else:
            if text and text.strip():
                t = text.strip()
                cks.append(
                    {
                        "text": t,
                        "image": None,
                        "ck_type": "text",
                        "tk_nums": num_tokens_from_string(t),
                    }
                )

    # final flush after loop (only when delimiters were used for splitting)
    if split_pattern and seg and seg.strip():
        s = seg.strip()
        cks.append(
            {
                "text": s,
                "image": None,
                "ck_type": "text",
                "tk_nums": num_tokens_from_string(s),
            }
        )

    return cks, tables, images, has_custom


def _add_context(cks, idx, context_size):
    if cks[idx]["ck_type"] not in ("image", "table"):
        return

    prev = idx - 1
    after = idx + 1
    remain_above = context_size
    remain_below = context_size

    cks[idx]["context_above"] = ""
    cks[idx]["context_below"] = ""

    split_pat = r"([。!?？；！\n]|\. )"

    picked_above = []
    picked_below = []

    def take_sentences_from_end(cnt, need_tokens):
        txts = re.split(split_pat, cnt, flags=re.DOTALL)
        sents = []
        for j in range(0, len(txts), 2):
            sents.append(txts[j] + (txts[j + 1] if j + 1 < len(txts) else ""))
        acc = ""
        for s in reversed(sents):
            acc = s + acc
            if num_tokens_from_string(acc) >= need_tokens:
                break
        return acc

    def take_sentences_from_start(cnt, need_tokens):
        txts = re.split(split_pat, cnt, flags=re.DOTALL)
        acc = ""
        for j in range(0, len(txts), 2):
            acc += txts[j] + (txts[j + 1] if j + 1 < len(txts) else "")
            if num_tokens_from_string(acc) >= need_tokens:
                break
        return acc

    # above
    parts_above = []
    while prev >= 0 and remain_above > 0:
        if cks[prev]["ck_type"] == "text":
            tk = cks[prev]["tk_nums"]
            if tk >= remain_above:
                piece = take_sentences_from_end(cks[prev]["text"], remain_above)
                parts_above.insert(0, piece)
                picked_above.append((prev, "tail", remain_above, tk, piece[:80]))
                remain_above = 0
                break
            else:
                parts_above.insert(0, cks[prev]["text"])
                picked_above.append((prev, "full", remain_above, tk, (cks[prev]["text"] or "")[:80]))
                remain_above -= tk
        prev -= 1

    # below
    parts_below = []
    while after < len(cks) and remain_below > 0:
        if cks[after]["ck_type"] == "text":
            tk = cks[after]["tk_nums"]
            if tk >= remain_below:
                piece = take_sentences_from_start(cks[after]["text"], remain_below)
                parts_below.append(piece)
                picked_below.append((after, "head", remain_below, tk, piece[:80]))
                remain_below = 0
                break
            else:
                parts_below.append(cks[after]["text"])
                picked_below.append((after, "full", remain_below, tk, (cks[after]["text"] or "")[:80]))
                remain_below -= tk
        after += 1

    cks[idx]["context_above"] = "".join(parts_above) if parts_above else ""
    cks[idx]["context_below"] = "".join(parts_below) if parts_below else ""


def _merge_cks(cks, chunk_token_num, has_custom):
    merged = []
    image_idxs = []
    prev_text_ck = -1

    for i in range(len(cks)):
        ck_type = cks[i]["ck_type"]

        if ck_type != "text":
            merged.append(cks[i])
            if ck_type == "image":
                image_idxs.append(len(merged) - 1)
            continue

        if prev_text_ck < 0 or merged[prev_text_ck]["tk_nums"] >= chunk_token_num or has_custom:
            merged.append(cks[i])
            prev_text_ck = len(merged) - 1
            continue

        merged[prev_text_ck]["text"] = (merged[prev_text_ck].get("text") or "") + (cks[i].get("text") or "")
        merged[prev_text_ck]["tk_nums"] = merged[prev_text_ck].get("tk_nums", 0) + cks[i].get("tk_nums", 0)

    return merged, image_idxs


def naive_merge_docx(
    sections,
    chunk_token_num=128,
    delimiter=DEFAULT_DELIMITER,
    table_context_size=0,
    image_context_size=0,
):
    if not sections:
        return [], []

    cks, tables, images, has_custom = _build_cks(sections, delimiter)

    if table_context_size > 0:
        for i in tables:
            _add_context(cks, i, table_context_size)

    if image_context_size > 0:
        for i in images:
            _add_context(cks, i, image_context_size)

    merged_cks, merged_image_idx = _merge_cks(cks, chunk_token_num, has_custom)

    return merged_cks, merged_image_idx

