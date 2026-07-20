import sys
import httpx
from sqlalchemy import text
from database.connection import SessionLocal

BASE_URL = "http://127.0.0.1:8000"

def clean_database():
    print("Cleaning up E2E test data from database...")
    db = SessionLocal()
    try:
        # Get user ids
        user_ids = db.execute(text(
            "SELECT id FROM users WHERE email IN ('usera@example.com', 'userb@example.com')"
        )).all()
        ids = [u[0] for u in user_ids]
        
        if ids:
            # Delete memberships
            db.execute(text("DELETE FROM organization_memberships WHERE user_id IN :ids"), {"ids": tuple(ids)})
            # Delete refresh sessions
            db.execute(text("DELETE FROM auth_refresh_sessions WHERE user_id IN :ids"), {"ids": tuple(ids)})
            # Delete invitations
            db.execute(text(
                "DELETE FROM organization_invitations WHERE invited_by_user_id IN :ids OR email IN ('usera@example.com', 'userb@example.com')"
            ), {"ids": tuple(ids)})
            
            # Find organizations owned by these users
            org_ids = db.execute(text(
                "SELECT id FROM organizations WHERE owner_user_id IN :ids"
            ), {"ids": tuple(ids)}).all()
            oids = [o[0] for o in org_ids]
            
            if oids:
                # Delete bots in these orgs
                db.execute(text("DELETE FROM bots WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                # Delete documents in these orgs
                db.execute(text("DELETE FROM documents WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                # Delete usage
                db.execute(text("DELETE FROM usage_daily WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM usage_monthly WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                # Delete subscriptions
                db.execute(text("DELETE FROM subscriptions WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                # Delete orgs
                db.execute(text("DELETE FROM organizations WHERE id IN :oids"), {"oids": tuple(oids)})

            # Delete users
            db.execute(text("DELETE FROM users WHERE id IN :ids"), {"ids": tuple(ids)})
            
        db.commit()
        print("Clean up completed successfully!\n")
    except Exception as e:
        db.rollback()
        print(f"Clean up failed: {e}")
    finally:
        db.close()

def log_test(step_name, success, info=""):
    status = "SUCCESS" if success else "FAILED"
    print(f"[{status}] {step_name} {f'({info})' if info else ''}")
    if not success:
        sys.exit(1)

def run_tests():
    clean_database()
    
    print("Starting E2E SaaS Platform Verification Tests...\n")
    client = httpx.Client(timeout=10.0)

    # ----------------------------------------------------
    # 1. SIGNUP & LOGIN FLOWS
    # ----------------------------------------------------
    # Register User A
    try:
        res = client.post(
            f"{BASE_URL}/auth/register",
            json={
                "name": "User A",
                "email": "usera@example.com",
                "password": "securepassword123",
                "organization_name": "Org A"
            }
        )
        log_test("User A Auth (Register)", res.status_code == 200, f"Status: {res.status_code}")
        
        user_a_session = res.json()
        token_a = user_a_session["access_token"]
        refresh_a = user_a_session["refresh_token"]
        user_a_id = user_a_session["user"]["id"]
    except Exception as e:
        log_test("User A Auth Initial Request", False, str(e))

    # Register User B
    try:
        res = client.post(
            f"{BASE_URL}/auth/register",
            json={
                "name": "User B",
                "email": "userb@example.com",
                "password": "securepassword456",
                "organization_name": "Org B"
            }
        )
        log_test("User B Auth (Register)", res.status_code == 200, f"Status: {res.status_code}")
        
        user_b_session = res.json()
        token_b = user_b_session["access_token"]
        refresh_b = user_b_session["refresh_token"]
        user_b_id = user_b_session["user"]["id"]
    except Exception as e:
        log_test("User B Auth Initial Request", False, str(e))

    # ----------------------------------------------------
    # 2. PROFILE SETTINGS
    # ----------------------------------------------------
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res = client.get(f"{BASE_URL}/auth/profile", headers=headers_a)
    log_test("User A Profile (Get)", res.status_code == 200 and res.json()["email"] == "usera@example.com")

    res = client.patch(f"{BASE_URL}/auth/profile", json={"name": "User A Modified"}, headers=headers_a)
    log_test("User A Profile (Update)", res.status_code == 200 and res.json()["name"] == "User A Modified")

    # ----------------------------------------------------
    # 3. ORGANIZATION SYSTEM
    # ----------------------------------------------------
    res = client.get(f"{BASE_URL}/organizations/", headers=headers_a)
    log_test("User A Organizations (List)", res.status_code == 200 and len(res.json()) > 0)
    orgs_a = res.json()
    org_a_id = orgs_a[0]["id"]
    org_a_role = orgs_a[0]["role"]
    log_test("User A Organization Owner Check", org_a_role == "owner", f"Role is {org_a_role}")

    res = client.post(f"{BASE_URL}/organizations/", json={"name": "Org A Second"}, headers=headers_a)
    log_test("User A Organization (Create)", res.status_code == 200)
    org_a_second = res.json()
    org_a_second_id = org_a_second["id"]

    res = client.patch(f"{BASE_URL}/organizations/{org_a_id}", json={"name": "Org A Renamed"}, headers=headers_a)
    log_test("User A Organization (Rename)", res.status_code == 200 and res.json()["name"] == "Org A Renamed")

    # ----------------------------------------------------
    # 4. TEAM MANAGEMENT & INVITATIONS
    # ----------------------------------------------------
    headers_a_org = {"Authorization": f"Bearer {token_a}", "X-Organization-Id": str(org_a_id)}
    res = client.post(
        f"{BASE_URL}/organizations/{org_a_id}/invitations",
        json={"email": "userb@example.com", "role": "member"},
        headers=headers_a_org
    )
    log_test("Team Invitation (Create)", res.status_code == 200)
    invite = res.json()
    invite_token = invite.get("invite_token")
    log_test("Invite Token Exists", invite_token is not None)

    # User B accepts invitation
    headers_b = {"Authorization": f"Bearer {token_b}"}
    res_accept = client.post(
        f"{BASE_URL}/organizations/invitations/accept",
        json={"token": invite_token},
        headers=headers_b
    )
    log_test("Team Invitation (Accept)", res_accept.status_code == 200)

    # List members and update role
    res = client.get(f"{BASE_URL}/organizations/{org_a_id}/members", headers=headers_a_org)
    members = res.json()
    member_b = next((m for m in members if m["email"] == "userb@example.com"), None)
    log_test("Team Members list includes User B", member_b is not None)

    if member_b:
        membership_id = member_b["id"]
        res = client.patch(
            f"{BASE_URL}/organizations/{org_a_id}/members/{membership_id}",
            json={"role": "admin"},
            headers=headers_a_org
        )
        log_test("Team Member Role Update", res.status_code == 200 and res.json()["role"] == "admin")

    # ----------------------------------------------------
    # 5. BOT MANAGEMENT
    # ----------------------------------------------------
    res = client.post(f"{BASE_URL}/customer/create", json={"name": "Customer A"}, headers=headers_a)
    log_test("Create Customer API Key", res.status_code == 200)
    customer_key = res.json()["api_key"]

    res = client.post(
        f"{BASE_URL}/bot/create",
        json={
            "api_key": customer_key,
            "organization_id": org_a_id,
            "name": "E2E Bot A",
            "provider": "gemini",
            "model_name": "gemini-2.5-flash",
            "provider_api_key": "dummy-key",
            "system_prompt": "Test system prompt",
            "welcome_message": "Hello!"
        },
        headers=headers_a_org
    )
    log_test("Bot Creation", res.status_code == 200)
    bot = res.json()
    bot_id = bot["bot_id"]

    res = client.get(f"{BASE_URL}/bots", headers=headers_a_org)
    log_test("List Bots (Organization)", res.status_code == 200 and any(b["bot_id"] == bot_id for b in res.json()))

    res = client.put(
        f"{BASE_URL}/bot/{bot_id}",
        json={"name": "E2E Bot A Renamed", "provider_api_key": "dummy-key-updated"},
        headers=headers_a_org
    )
    log_test("Bot Update", res.status_code == 200 and res.json()["name"] == "E2E Bot A Renamed")

    # ----------------------------------------------------
    # 6. ANALYTICS & BILLING
    # ----------------------------------------------------
    res = client.get(f"{BASE_URL}/analytics/bot/{bot_id}/summary", headers=headers_a_org)
    log_test("Bot Analytics Load", res.status_code == 200)
    summary = res.json()
    log_test("Bot Analytics fields validation", "total_conversations" in summary and "total_messages" in summary)

    res = client.get(f"{BASE_URL}/billing/plans", headers=headers_a_org)
    log_test("Billing Plans List", res.status_code == 200 and len(res.json()) > 0)

    res = client.get(f"{BASE_URL}/billing/organizations/{org_a_id}/subscription", headers=headers_a_org)
    log_test("Billing Subscription Details", res.status_code == 200 and "plan" in res.json())

    res = client.get(f"{BASE_URL}/billing/organizations/{org_a_id}/usage", headers=headers_a_org)
    log_test("Billing Usage Details", res.status_code == 200 and "usage" in res.json() and "limits" in res.json())

    # ----------------------------------------------------
    # 7. TENANT ISOLATION AUDIT
    # ----------------------------------------------------
    headers_b_org_second = {"Authorization": f"Bearer {token_b}", "X-Organization-Id": str(org_a_second_id)}
    res = client.get(f"{BASE_URL}/bots", headers=headers_b_org_second)
    log_test("Tenant Isolation (Bot access denied)", res.status_code in (403, 404), f"Status: {res.status_code}")

    res = client.get(f"{BASE_URL}/billing/organizations/{org_a_second_id}/subscription", headers=headers_b_org_second)
    log_test("Tenant Isolation (Billing subscription denied)", res.status_code in (403, 404), f"Status: {res.status_code}")

    res = client.get(f"{BASE_URL}/billing/organizations/{org_a_second_id}/usage", headers=headers_b_org_second)
    log_test("Tenant Isolation (Billing usage denied)", res.status_code in (403, 404), f"Status: {res.status_code}")

    # ----------------------------------------------------
    # 8. REFRESH TOKEN & LOGOUT FLOW
    # ----------------------------------------------------
    res = client.post(f"{BASE_URL}/auth/refresh", json={"refresh_token": refresh_a})
    log_test("Auth Token Refresh", res.status_code == 200)
    refresh_session = res.json()
    new_token_a = refresh_session["access_token"]
    new_refresh_a = refresh_session["refresh_token"]

    headers_a_new = {"Authorization": f"Bearer {new_token_a}"}
    res = client.get(f"{BASE_URL}/auth/profile", headers=headers_a_new)
    log_test("User A Profile with Refreshed Token", res.status_code == 200)

    res = client.post(f"{BASE_URL}/auth/logout", json={"refresh_token": new_refresh_a})
    log_test("Auth Logout", res.status_code == 200)

    res = client.post(f"{BASE_URL}/auth/refresh", json={"refresh_token": new_refresh_a})
    log_test("Auth Refresh Token Revocation Validation", res.status_code in (401, 404), f"Status: {res.status_code}")

    print("\nAll E2E SaaS Platform Verification Tests Completed Successfully!")

if __name__ == "__main__":
    run_tests()
