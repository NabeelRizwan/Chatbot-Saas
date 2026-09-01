"""Apply all database migrations and exit non-zero on failure."""

import os
import sys


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.migration_service import upgrade_to_head  # noqa: E402


if __name__ == "__main__":
    upgrade_to_head()
