from sqlalchemy import text
from database.connection import SessionLocal

def audit_users_orgs():
    db = SessionLocal()
    try:
        print("=== USERS IN DATABASE ===")
        users = db.execute(text("SELECT id, email, name FROM users")).all()
        for u in users:
            print(f"User ID={u[0]}, Email='{u[1]}', Name='{u[2]}'")

        print("\n=== ORGANIZATIONS IN DATABASE ===")
        orgs = db.execute(text("SELECT id, name, slug, owner_user_id FROM organizations")).all()
        for o in orgs:
            print(f"Org ID={o[0]}, Name='{o[1]}', Slug='{o[2]}', OwnerUserID={o[3]}")

        print("\n=== MEMBERSHIPS IN DATABASE ===")
        members = db.execute(text("SELECT id, organization_id, user_id, role FROM organization_memberships")).all()
        for m in members:
            print(f"Membership ID={m[0]}, OrgID={m[1]}, UserID={m[2]}, Role='{m[3]}'")

    finally:
        db.close()

if __name__ == "__main__":
    audit_users_orgs()
