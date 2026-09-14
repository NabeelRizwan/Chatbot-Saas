"""One Unicode-preserving discovery key; display strings stay untouched."""
import unicodedata

MAX_TERM_CHARS = 512


def normalize_resource_text(value):
    if not isinstance(value, str):
        raise ValueError("Resource reference must be text")
    if len(value) > MAX_TERM_CHARS:
        raise ValueError("Resource reference exceeds bounded length")
    text = unicodedata.normalize("NFKC", value).casefold()
    # Keep letters, combining marks and numbers, including non-Latin scripts.
    normalized = " ".join("".join(c if unicodedata.category(c)[0] in "LNM" else " " for c in text).split())
    # Compatibility ligatures/casefolding can expand beyond the input length.
    # Bound persisted/indexed keys too; never truncate them into another name.
    if len(normalized) > MAX_TERM_CHARS:
        raise ValueError("Normalized resource reference exceeds bounded length")
    return normalized
