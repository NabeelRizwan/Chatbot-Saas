"""Bounded readiness probes; never run ranking or any answer provider."""
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.structural_chunking import count_tokens
from .config import Config, MODEL, REVISION
from .errors import CombinedRetrievalError


def readiness(*, transport=None):
    try:
        config = Config.from_env()
    except CombinedRetrievalError:
        return "misconfigured"
    try:
        if count_tokens("readiness") < 1:
            return "tokenizer_unavailable"
    except Exception:
        return "tokenizer_unavailable"
    address = urlsplit(config.url)
    url = urlunsplit((address.scheme, address.netloc, "/ready", "", ""))
    try:
        with httpx.Client(timeout=3, trust_env=False, follow_redirects=False,
                          transport=transport) as client:
            response = client.get(url, headers={"Authorization": "Bearer " + config.token})
        if response.status_code != 200 or len(response.content) > 4096:
            return "unavailable"
        value = response.json()
        if (not isinstance(value, dict) or value.get("ok") is not True or
                value.get("loaded") is not True or value.get("model") != MODEL or
                value.get("revision") != REVISION or value.get("dtype") != "float32" or
                type(value.get("batch_size")) is not int or value["batch_size"] != 1):
            return "identity_mismatch"
    except (httpx.HTTPError, ValueError):
        return "unavailable"
    return "ready"
