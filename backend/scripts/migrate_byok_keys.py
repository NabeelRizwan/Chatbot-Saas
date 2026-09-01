"""One-time controlled migration for legacy plaintext Bot.provider_api_key rows."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal
from services.bot_secret_service import migrate_legacy_bot_keys


def main() -> None:
    if not os.getenv("PLATFORM_KEY_ENCRYPTION_KEY"):
        raise SystemExit("PLATFORM_KEY_ENCRYPTION_KEY must be configured before migration.")
    with SessionLocal() as db:
        result = migrate_legacy_bot_keys(db)
    print(
        f"BYOK migration complete: migrated={result['migrated']}, "
        f"already_encrypted={result['already_encrypted']}"
    )


if __name__ == "__main__":
    main()
