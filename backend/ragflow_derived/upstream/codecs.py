# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import logging
import chardet

all_codecs = [
    "utf-8",
    "gb2312",
    "gbk",
    "utf_16",
    "ascii",
    "big5",
    "big5hkscs",
    "cp037",
    "cp273",
    "cp424",
    "cp437",
    "cp500",
    "cp720",
    "cp737",
    "cp775",
    "cp850",
    "cp852",
    "cp855",
    "cp856",
    "cp857",
    "cp858",
    "cp860",
    "cp861",
    "cp862",
    "cp863",
    "cp864",
    "cp865",
    "cp866",
    "cp869",
    "cp874",
    "cp875",
    "cp932",
    "cp949",
    "cp950",
    "cp1006",
    "cp1026",
    "cp1125",
    "cp1140",
    "cp1250",
    "cp1251",
    "cp1252",
    "cp1253",
    "cp1254",
    "cp1255",
    "cp1256",
    "cp1257",
    "cp1258",
    "euc_jp",
    "euc_jis_2004",
    "euc_jisx0213",
    "euc_kr",
    "gb18030",
    "hz",
    "iso2022_jp",
    "iso2022_jp_1",
    "iso2022_jp_2",
    "iso2022_jp_2004",
    "iso2022_jp_3",
    "iso2022_jp_ext",
    "iso2022_kr",
    "latin_1",
    "iso8859_2",
    "iso8859_3",
    "iso8859_4",
    "iso8859_5",
    "iso8859_6",
    "iso8859_7",
    "iso8859_8",
    "iso8859_9",
    "iso8859_10",
    "iso8859_11",
    "iso8859_13",
    "iso8859_14",
    "iso8859_15",
    "iso8859_16",
    "johab",
    "koi8_r",
    "koi8_t",
    "koi8_u",
    "kz1048",
    "mac_cyrillic",
    "mac_greek",
    "mac_iceland",
    "mac_latin2",
    "mac_roman",
    "mac_turkish",
    "ptcp154",
    "shift_jis",
    "shift_jis_2004",
    "shift_jisx0213",
    "utf_32",
    "utf_32_be",
    "utf_32_le",
    "utf_16_be",
    "utf_16_le",
    "utf_7",
    "windows-1250",
    "windows-1251",
    "windows-1252",
    "windows-1253",
    "windows-1254",
    "windows-1255",
    "windows-1256",
    "windows-1257",
    "windows-1258",
    "latin-2",
]


def find_codec(blob):
    sample = blob[:1024]

    # A blob that decodes as UTF-8 is UTF-8; nothing else needs to be guessed.
    # Check this first because chardet can report a confident single-byte guess
    # for short UTF-8 text, and callers decode with errors="ignore", so a wrong
    # codec is silently lossy instead of raising. The second decode covers a
    # multi-byte character that the 1024-byte sample cuts in half.
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        try:
            blob.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass

    detected = chardet.detect(sample)
    encoding = detected["encoding"]
    if encoding:
        # Honor the detection whenever it decodes the sample. The loop below
        # returns the first codec that does not raise, and legacy single-byte
        # codecs (cp037, utf_16) decode arbitrary bytes without error, so a
        # low-confidence detection still beats the loop's first non-raising hit.
        try:
            sample.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError) as e:
            logging.debug("find_codec: detection %r (%.2f) did not decode the sample: %s", encoding, detected["confidence"] or 0.0, e)

    for c in all_codecs:
        try:
            sample.decode(c)
            return c
        except Exception:
            pass
        try:
            blob.decode(c)
            return c
        except Exception:
            pass

    return "utf-8"


def decode_text(blob, document_type="text"):
    """Decode document bytes without silently accepting weak codec guesses."""
    bom_codecs = (
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\xfe\xff", "utf-16-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xef\xbb\xbf", "utf-8-sig"),
    )
    for bom, encoding in bom_codecs:
        if blob.startswith(bom):
            return blob.decode(encoding), encoding

    try:
        return blob.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    detected = chardet.detect(blob[:1024])
    encoding = detected.get("encoding")
    confidence = detected.get("confidence") or 0.0
    if encoding and encoding.lower().replace("-", "") in {"gb2312", "gbk"}:
        encoding = "gb18030"
    if not encoding or confidence < 0.8:
        raise UnicodeError(f"Unable to reliably detect {document_type} encoding (confidence={confidence:.2f})")
    try:
        return blob.decode(encoding), encoding
    except (LookupError, UnicodeDecodeError) as exc:
        raise UnicodeError(f"Unable to decode {document_type} as {encoding}") from exc
