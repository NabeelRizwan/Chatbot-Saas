"""Prepare trusted corpus snapshots before adding retrieval workers to traffic."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument('--bot-id', action='append', type=int)
    targets.add_argument('--all-active', action='store_true')
    args = parser.parse_args()
    from database.connection import SessionLocal
    from database.models import Bot
    from services.knowledge_runtime import engine_name, warm
    from services.llama_rag.client import close_retrieval_clients
    if engine_name() != 'llamaindex':
        parser.error('This command requires KNOWLEDGE_ENGINE=llamaindex')
    if args.bot_id and any(value < 1 for value in args.bot_id):
        parser.error('Bot IDs must be positive')
    try:
        with SessionLocal() as db:
            query = db.query(Bot).filter(Bot.status == 'active')
            if args.bot_id:
                query = query.filter(Bot.id.in_(args.bot_id))
            ids = [bot.id for bot in query.order_by(Bot.id).all()]
            if args.bot_id and set(ids) != set(args.bot_id):
                parser.error('One or more selected bots are missing or inactive')
        for bot_id in ids:
            with SessionLocal() as db:
                bot = db.get(Bot, bot_id)
                if not bot or bot.status != 'active':
                    raise RuntimeError('Bot access changed during warm-up')
                warm(db, bot)
            print(f'Bot {bot_id}: corpus ready on the configured retrieval workers', flush=True)
    finally:
        close_retrieval_clients()


if __name__ == '__main__':
    main()
