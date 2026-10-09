"""Prebuild the selected bots' immutable retrieval indexes before accepting chat."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='Warm all active bots')
    group.add_argument('--bot-id', type=int, action='append')
    args = parser.parse_args()
    from database.connection import SessionLocal
    from database.models import Bot
    from services.knowledge_runtime import engine_name, warm
    if engine_name() != 'llamaindex':
        parser.error('This command requires KNOWLEDGE_ENGINE=llamaindex')
    failures = 0
    with SessionLocal() as db:
        query = db.query(Bot.id).filter(Bot.status == 'active')
        if args.bot_id:
            query = query.filter(Bot.id.in_(args.bot_id))
        ids = [row[0] for row in query.order_by(Bot.id).all()]
        if args.bot_id and set(ids) != set(args.bot_id):
            parser.error('A requested bot does not exist or is inactive')
        for bot_id in ids:
            try:
                warm(db, db.get(Bot, bot_id))
                print(f'Bot {bot_id}: ready', flush=True)
            except Exception as error:
                db.rollback()
                print(f'Bot {bot_id}: failed ({type(error).__name__})', flush=True)
                failures += 1
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
