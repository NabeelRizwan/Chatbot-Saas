from sqlalchemy import text
from database.connection import SessionLocal

def audit_details():
    db = SessionLocal()
    try:
        print("=== BOTS IN DATABASE ===")
        bots = db.execute(text("SELECT id, name, customer_id, organization_id, created_at FROM bots")).all()
        for b in bots:
            print(f"Bot ID={b[0]}, Name='{b[1]}', CustomerID={b[2]}, OrgID={b[3]}, Created={b[4]}")

        print("\n=== DOCUMENTS IN DATABASE ===")
        docs = db.execute(text("SELECT id, bot_id, filename, organization_id, file_size, processing_status FROM documents")).all()
        for d in docs:
            print(f"Doc ID={d[0]}, BotID={d[1]}, Filename='{d[2]}', OrgID={d[3]}, Size={d[4]}, Status='{d[5]}'")

        print("\n=== CONVERSATION SESSIONS IN DATABASE ===")
        sessions = db.execute(text("SELECT id, bot_id, session_id, organization_id, channel FROM conversation_sessions")).all()
        for s in sessions:
            print(f"Session ID={s[0]}, BotID={s[1]}, SessionID='{s[2]}', OrgID={s[3]}, Channel='{s[4]}'")

        print("\n=== CONVERSATION MESSAGES IN DATABASE ===")
        messages = db.execute(text("SELECT id, conversation_session_id, bot_id, organization_id, session_id, user_message, assistant_response FROM conversation_messages")).all()
        for m in messages:
            print(f"Msg ID={m[0]}, SessionID={m[1]}, BotID={m[2]}, OrgID={m[3]}, SessionUID='{m[4]}', UserMsg='{m[5][:20]}...', AsstResp='{m[6][:20] if m[6] else None}...'")

    finally:
        db.close()

if __name__ == "__main__":
    audit_details()
