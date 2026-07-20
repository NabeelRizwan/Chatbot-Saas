import sys
import datetime
from sqlalchemy import text
from database.connection import SessionLocal

def migrate():
    db = SessionLocal()
    try:
        # Start transaction
        db.execute(text("BEGIN"))
        
        # 1. Update Bots
        res_bots = db.execute(text(
            "UPDATE bots SET organization_id = 4 WHERE organization_id IS NULL"
        ))
        print(f"Migrated {res_bots.rowcount} bots")
        
        # 2. Update Documents
        res_docs = db.execute(text(
            "UPDATE documents SET organization_id = 4 WHERE organization_id IS NULL"
        ))
        print(f"Migrated {res_docs.rowcount} documents")
        
        # 3. Update Chunks
        res_chunks = db.execute(text(
            "UPDATE chunks SET organization_id = 4 WHERE organization_id IS NULL"
        ))
        print(f"Migrated {res_chunks.rowcount} chunks")
        
        # 4. Update Conversation Sessions
        res_sessions = db.execute(text(
            "UPDATE conversation_sessions SET organization_id = 4 WHERE organization_id IS NULL"
        ))
        print(f"Migrated {res_sessions.rowcount} sessions")
        
        # 5. Update Conversation Messages
        res_messages = db.execute(text(
            "UPDATE conversation_messages SET organization_id = 4 WHERE organization_id IS NULL"
        ))
        print(f"Migrated {res_messages.rowcount} messages")
        
        # 6. Update Bot Analytics
        res_analytics = db.execute(text(
            "UPDATE bot_analytics_daily SET organization_id = 4 WHERE organization_id IS NULL"
        ))
        print(f"Migrated {res_analytics.rowcount} analytics records")

        # STEP 5 — Rebuild Usage Metrics
        # Count resources now associated with Organization 4
        active_bots = db.execute(text(
            "SELECT COUNT(*) FROM bots WHERE organization_id = 4"
        )).scalar() or 0
        
        document_uploads = db.execute(text(
            "SELECT COUNT(*) FROM documents WHERE organization_id = 4"
        )).scalar() or 0
        
        storage_bytes = db.execute(text(
            "SELECT COALESCE(SUM(file_size), 0) FROM documents WHERE organization_id = 4"
        )).scalar() or 0
        
        messages_sent = db.execute(text(
            "SELECT COUNT(*) FROM conversation_messages WHERE organization_id = 4"
        )).scalar() or 0

        print(f"Rebuilding usage metrics for Org 4: bots={active_bots}, docs={document_uploads}, storage={storage_bytes}, messages={messages_sent}")
        
        # Update usage_daily and usage_monthly
        today = datetime.date.today()
        daily_record = db.execute(text(
            "SELECT id FROM usage_daily WHERE organization_id = 4 AND date = :date"
        ), {"date": today}).first()
        
        if daily_record:
            db.execute(text(
                "UPDATE usage_daily SET "
                "messages_sent = :messages_sent, "
                "document_uploads = :document_uploads, "
                "storage_bytes = :storage_bytes, "
                "active_bots = :active_bots, "
                "updated_at = NOW() "
                "WHERE id = :id"
            ), {
                "messages_sent": messages_sent,
                "document_uploads": document_uploads,
                "storage_bytes": storage_bytes,
                "active_bots": active_bots,
                "id": daily_record[0]
            })
        else:
            db.execute(text(
                "INSERT INTO usage_daily (organization_id, date, messages_sent, document_uploads, storage_bytes, active_bots, created_at, updated_at) "
                "VALUES (4, :date, :messages_sent, :document_uploads, :storage_bytes, :active_bots, NOW(), NOW())"
            ), {
                "date": today,
                "messages_sent": messages_sent,
                "document_uploads": document_uploads,
                "storage_bytes": storage_bytes,
                "active_bots": active_bots
            })

        current_month = today.strftime("%Y-%m")
        monthly_record = db.execute(text(
            "SELECT id FROM usage_monthly WHERE organization_id = 4 AND month = :month"
        ), {"month": current_month}).first()
        
        if monthly_record:
            db.execute(text(
                "UPDATE usage_monthly SET "
                "messages_sent = :messages_sent, "
                "document_uploads = :document_uploads, "
                "storage_bytes = :storage_bytes, "
                "active_bots = :active_bots, "
                "updated_at = NOW() "
                "WHERE id = :id"
            ), {
                "messages_sent": messages_sent,
                "document_uploads": document_uploads,
                "storage_bytes": storage_bytes,
                "active_bots": active_bots,
                "id": monthly_record[0]
            })
        else:
            db.execute(text(
                "INSERT INTO usage_monthly (organization_id, month, messages_sent, document_uploads, storage_bytes, active_bots, created_at, updated_at) "
                "VALUES (4, :month, :messages_sent, :document_uploads, :storage_bytes, :active_bots, NOW(), NOW())"
            ), {
                "month": current_month,
                "messages_sent": messages_sent,
                "document_uploads": document_uploads,
                "storage_bytes": storage_bytes,
                "active_bots": active_bots
            })
            
        # Commit transaction
        db.execute(text("COMMIT"))
        print("Migration transaction committed successfully!")
    except Exception as e:
        db.execute(text("ROLLBACK"))
        print(f"Migration failed and transaction was rolled back: {e}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
