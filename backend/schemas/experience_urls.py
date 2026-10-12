import re
from urllib.parse import urlsplit


def public_https_parts(value: str):
    """Validate browser links without fetching them or restricting product queries."""
    if len(value) > 2048 or any(ord(char) < 32 or ord(char) == 127 or char.isspace() for char in value) or "\\" in value:
        raise ValueError("Use a complete public HTTPS website address")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (ValueError, UnicodeError):
        raise ValueError("Use a valid HTTPS website address") from None
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("Use a public HTTPS address without embedded credentials")
    if "." not in host or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
        raise ValueError("Use a public website name")
    labels = host.split(".")
    if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("Use a valid public website name")
    # A numeric final label can be interpreted as a shortened/octal/hex IPv4 host.
    if not (re.fullmatch(r"[a-z]{2,63}", labels[-1]) or labels[-1].startswith("xn--")):
        raise ValueError("Use a public website name, not an IP address")
    return parsed, host
