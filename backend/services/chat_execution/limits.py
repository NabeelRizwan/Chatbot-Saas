"""Profile budgets: persisted on acceptance; OG keeps its original deadline."""
import os


def og_execution_timeout():
    return _seconds("CHAT_EXECUTION_TIMEOUT_SECONDS", 180, 420)


def rag2_execution_timeout():
    return _seconds("RAG2_CHAT_EXECUTION_TIMEOUT_SECONDS", 1800, 1800)


def maximum_execution_timeout():
    return max(og_execution_timeout(), rag2_execution_timeout())


def _seconds(name, default, maximum):
    value = int(os.getenv(name, str(default)))
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value
