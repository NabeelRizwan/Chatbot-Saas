"""API entrypoint with explicit production migration ownership."""

import os
import sys


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database.connection import engine  # noqa: E402
from services.migration_service import require_migrations_current, upgrade_to_head  # noqa: E402


def prepare_database_for_startup(environment=None) -> None:
    """Migrate for local convenience; production replicas only verify head."""
    env = environment if environment is not None else os.environ
    app_environment = (env.get("APP_ENV") or env.get("ENVIRONMENT") or "development").lower()
    if app_environment in {"production", "prod"}:
        with engine.connect() as connection:
            require_migrations_current(connection)
        return
    upgrade_to_head()


def main() -> None:
    prepare_database_for_startup()
    os.chdir(BACKEND_DIR)
    # Railway (and other PaaS targets) assign the listen port dynamically via
    # PORT. Local/Docker-compose usage without PORT set keeps the prior 8000 default.
    port = str(int(os.getenv("PORT", "8000")))
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ],
    )


if __name__ == "__main__":
    main()
