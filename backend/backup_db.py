import json
from datetime import datetime, date
from sqlalchemy import text
from database.connection import SessionLocal

TABLES = [
    "bots",
    "documents",
    "chunks",
    "conversation_sessions",
    "conversation_messages",
    "bot_analytics_daily",
    "usage_daily",
    "usage_monthly"
]

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="ignore")
        return super().default(obj)

def backup():
    db = SessionLocal()
    backup_data = {}
    try:
        print("Starting database backup for legacy migration...")
        for table in TABLES:
            rows = db.execute(text(f"SELECT * FROM {table}")).all()
            # Get column names
            columns_res = db.execute(text(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{table}' ORDER BY ordinal_position"
            )).all()
            colnames = [r[0] for r in columns_res]
            
            table_rows = []
            for row in rows:
                row_dict = {}
                for idx, val in enumerate(row):
                    col = colnames[idx] if idx < len(colnames) else f"col_{idx}"
                    # convert memoryviews/vector types if necessary
                    if hasattr(val, "tolist"):
                        val = val.tolist()
                    elif type(val).__name__ == "memoryview":
                        val = bytes(val).decode("utf-8", errors="ignore")
                    row_dict[col] = val
                table_rows.append(row_dict)
                
            backup_data[table] = table_rows
            print(f"Backed up {len(table_rows)} records from table '{table}'")
            
        with open("backup_before_migration.json", "w") as f:
            json.dump(backup_data, f, cls=CustomEncoder, indent=2)
            
        print("Backup completed successfully! Saved to backup_before_migration.json")
    except Exception as e:
        print(f"Backup failed: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    backup()
