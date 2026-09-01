"""Cross-platform ARQ worker entrypoint with a stable backend import path."""

import os
import sys


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from arq.worker import create_worker  # noqa: E402
from workers.worker import WorkerSettings  # noqa: E402


if __name__ == "__main__":
    create_worker(WorkerSettings).run()
