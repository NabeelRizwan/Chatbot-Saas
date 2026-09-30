from dataclasses import replace
from .config import NativeConfig
from .client import NativeClient


def readiness():
    try:
        config = replace(NativeConfig.from_env(), timeout=3)
        return "ready" if NativeClient(config).health() else "unavailable"
    except Exception:
        return "unavailable"
