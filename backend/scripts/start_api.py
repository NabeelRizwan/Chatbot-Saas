"""Production API entrypoint: migrate successfully, then start Uvicorn."""

import os
import sys


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.migration_service import upgrade_to_head  # noqa: E402


def main() -> None:
    upgrade_to_head()
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
