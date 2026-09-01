import re
from collections.abc import Iterable


_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:refresh|access|session)[_-]?token\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgAAAAA[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|xai|AIza)-[A-Za-z0-9_-]{8,}\b"),
)


def redact_secrets(value: object, known_secrets: Iterable[str | None] = ()) -> str:
    text = str(value)
    for secret in known_secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text
