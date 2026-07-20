import sys
from sqlalchemy import text
from database.connection import SessionLocal

def audit():
    db = SessionLocal()
    try:
        print("=== DATABASE AUDIT: USER AND ORGANIZATION ===")
        # Look for target user
        user = db.execute(text("SELECT id, email, name FROM users WHERE email = 'testbotid2@gmail.com'")).first()
        if not user:
            print("Target user 'testbotid2@gmail.com' NOT found in users table.")
            user_id = None
            org_id = None
        else:
            user_id = user[0]
            print(f"Target User found: ID={user[0]}, Name={user[2]}, Email={user[1]}")
            
            # Find organizations for this user
            org_memberships = db.execute(text(
                "SELECT o.id, o.name, o.slug, om.role FROM organizations o "
                "JOIN organization_memberships om ON o.id = om.organization_id "
                "WHERE om.user_id = :user_id"
            ), {"user_id": user_id}).all()
            
            if org_memberships:
                print("Organizations associated with target user:")
                for o in org_memberships:
                    print(f" - ID={o[0]}, Name='{o[1]}', Slug='{o[2]}', Role={o[3]}")
                org_id = org_memberships[0][0]
            else:
                print("Target user has NO organizations in organization_memberships.")
                org_id = None

        print("\n=== DATABASE AUDIT: ORPHANED & LEGACY DATA ===")
        
        # Bots
        total_bots = db.execute(text("SELECT COUNT(*) FROM bots")).scalar()
        legacy_bots = db.execute(text("SELECT COUNT(*) FROM bots WHERE organization_id IS NULL")).scalar()
        print(f"Bots: Total={total_bots}, Legacy/Orphaned (organization_id IS NULL)={legacy_bots}")
        
        # Documents
        total_docs = db.execute(text("SELECT COUNT(*) FROM documents")).scalar()
        legacy_docs = db.execute(text("SELECT COUNT(*) FROM documents WHERE organization_id IS NULL")).scalar()
        print(f"Documents: Total={total_docs}, Legacy/Orphaned (organization_id IS NULL)={legacy_docs}")
        
        # Chunks
        total_chunks = db.execute(text("SELECT COUNT(*) FROM chunks")).scalar()
        legacy_chunks = db.execute(text("SELECT COUNT(*) FROM chunks WHERE organization_id IS NULL")).scalar()
        print(f"Chunks: Total={total_chunks}, Legacy/Orphaned (organization_id IS NULL)={legacy_chunks}")

        # Conversation Sessions
        total_sessions = db.execute(text("SELECT COUNT(*) FROM conversation_sessions")).scalar()
        legacy_sessions = db.execute(text("SELECT COUNT(*) FROM conversation_sessions WHERE organization_id IS NULL")).scalar()
        print(f"Conversation Sessions: Total={total_sessions}, Legacy/Orphaned (organization_id IS NULL)={legacy_sessions}")

        # Conversation Messages
        total_messages = db.execute(text("SELECT COUNT(*) FROM conversation_messages")).scalar()
        legacy_messages = db.execute(text("SELECT COUNT(*) FROM conversation_messages WHERE organization_id IS NULL")).scalar()
        print(f"Conversation Messages: Total={total_messages}, Legacy/Orphaned (organization_id IS NULL)={legacy_messages}")

        # Bot Analytics Daily
        total_analytics = db.execute(text("SELECT COUNT(*) FROM bot_analytics_daily")).scalar()
        legacy_analytics = db.execute(text("SELECT COUNT(*) FROM bot_analytics_daily WHERE organization_id IS NULL")).scalar()
        print(f"Bot Analytics Daily: Total={total_analytics}, Legacy/Orphaned (organization_id IS NULL)={legacy_analytics}")
        
        # Usage Daily & Monthly
        total_usage_daily = db.execute(text("SELECT COUNT(*) FROM usage_daily")).scalar()
        total_usage_monthly = db.execute(text("SELECT COUNT(*) FROM usage_monthly")).scalar()
        print(f"Usage Records: Daily Total={total_usage_daily}, Monthly Total={total_usage_monthly}")

    finally:
        db.close()

if __name__ == "__main__":
    audit()
