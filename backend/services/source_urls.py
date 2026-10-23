"""Validate source navigation destinations without resolving or inventing links."""

from urllib.parse import urlsplit


def safe_source_url(value):
    """Return the exact safe HTTP(S) URL, or None; never repair an unsafe URL.

    Check raw text before parsing: URL parsers can silently discard control
    characters, and browsers interpret backslashes differently from urlsplit.
    A source is navigation metadata, so user-info and invalid ports are rejected.
    Ordinary query strings and fragments keep their original meaning.
    """
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159
                   for char in value)
            or "\\" in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname or parsed.username is not None
                or parsed.password is not None):
            return None
        # Access validates malformed / out-of-range port values.
        parsed.port
    except ValueError:
        return None
    return value
