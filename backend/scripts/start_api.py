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
            "8000",
        ],
    )


if __name__ == "__main__":
    main()
