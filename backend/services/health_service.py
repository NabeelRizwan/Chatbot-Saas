import os
from typing import Any

from sqlalchemy import text

from database.connection import engine
from services.queue_service import get_queue_mode
from utils.redis_client import get_redis
from workers.worker import WORKER_HEARTBEAT_KEY
from services.migration_service import migration_state


def liveness_status() -> dict[str, str]:
    """Liveness intentionally proves only that the API process can answer."""
    return {"status": "alive"}


def readiness_status() -> tuple[bool, dict[str, Any]]:
    dependencies: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current_revision, head_revision = migration_state(connection)
        dependencies["database"] = "ready"
        dependencies["migrations"] = (
            "ready" if current_revision == head_revision else "outdated"
        )
    except Exception:
        dependencies["database"] = "unavailable"
        dependencies["migrations"] = "unknown"

    production = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").lower() in {
        "production", "prod"
    }
    queue_mode = get_queue_mode()
    queue_required = production
    if queue_required:
        if queue_mode != "arq":
            dependencies["queue"] = "misconfigured"
            ready = False
            return ready, {"status": "not_ready", "dependencies": dependencies}
        redis = get_redis()
        if redis is None:
            dependencies["redis"] = "unavailable"
            dependencies["worker"] = "unknown"
        else:
            try:
                redis.ping()
                dependencies["redis"] = "ready"
                dependencies["worker"] = "ready" if redis.get(WORKER_HEARTBEAT_KEY) else "unavailable"
            except Exception:
                dependencies["redis"] = "unavailable"
                dependencies["worker"] = "unknown"
    else:
        dependencies["queue"] = "not-required"

    ready = (
        dependencies.get("database") == "ready"
        and dependencies.get("migrations") == "ready"
        and (
        not queue_required
        or dependencies.get("redis") == "ready" and dependencies.get("worker") == "ready"
        )
    )
    return ready, {"status": "ready" if ready else "not_ready", "dependencies": dependencies}
