"""Deliberately promote one existing account; no passwords or HTTP bootstrap."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database.connection import SessionLocal  # noqa: E402
from database.models import User  # noqa: E402
from services.platform_key_service import record_admin_action  # noqa: E402


def find_account(db, *, email: str | None = None, user_id: int | None = None):
    if (email is None) == (user_id is None):
        raise ValueError("Specify exactly one existing account with --email or --user-id.")
    query = db.query(User)
    query = query.filter(User.email == email.strip().lower()) if email is not None else query.filter(User.id == user_id)
    user = query.populate_existing().with_for_update().first()
    if user is None:
        raise ValueError("Existing account not found; register through normal authentication first.")
    if user.disabled:
        raise ValueError("Disabled accounts cannot be promoted.")
    return user


def promote_account(db, *, email: str | None = None, user_id: int | None = None) -> tuple[int, bool]:
    user = find_account(db, email=email, user_id=user_id)
    changed = not user.is_admin
    if changed:
        user.is_admin = True
        # CLI actor is the infrastructure operator, not an impersonated user.
        record_admin_action(db, None, "admin.promoted_cli", "user", user.id)
    db.commit()
    return user.id, changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--email", help="Exact existing account email")
    target.add_argument("--user-id", type=int, help="Exact existing user ID")
    parser.add_argument("--yes", action="store_true", help="Confirm promotion for a noninteractive one-off command")
    args = parser.parse_args(argv)
    try:
        with SessionLocal() as db:
            user = find_account(db, email=args.email, user_id=args.user_id)
            target_id = user.id
            db.rollback()  # Do not hold a row lock while waiting for an operator.
            if not args.yes and input(f"Promote existing user ID {target_id} to platform admin? Type PROMOTE: ") != "PROMOTE":
                print("Cancelled. No account changed.")
                return 1
            user_id, changed = promote_account(db, user_id=target_id)
        print(f"User ID {user_id}: " + ("platform admin granted." if changed else "already a platform admin; unchanged."))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print("Cancelled. No account changed.", file=sys.stderr)
    except Exception:
        # Never print SQL parameters, passwords, database URLs, or secrets.
        print("Promotion failed. Check database connectivity/schema and retry.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
