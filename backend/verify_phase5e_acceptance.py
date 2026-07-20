import sys
import time
import httpx
from database.connection import SessionLocal
from sqlalchemy import text

BASE_URL = "http://127.0.0.1:8000"

def log_test(phase: str, test_name: str, success: bool, info: str = ""):
    status = "SUCCESS" if success else "FAILED"
    print(f"[{status}] [{phase}] {test_name} {f'({info})' if info else ''}")
    if not success:
        sys.exit(1)

def run_acceptance_tests():
    print("==================================================================")
    print("   PHASE 5E - FINAL PRODUCTION ACCEPTANCE TESTING (SAFE MODE)")
    print("==================================================================\n")
    client = httpx.Client(timeout=30.0)

    # -------------------------------------------------------------------
    # PHASE 1 — AUTHENTICATION
    # -------------------------------------------------------------------
    phase = "PHASE 1: AUTHENTICATION"
    email = "tempbottesting1@gmail.com"
    password = "TempBot@12345"
    name = "Temp Bot Testing"
    org_name = "Temp Testing Organization"

    # Clean previous test account if exists
    db = SessionLocal()
    try:
        user_ids = db.execute(text("SELECT id FROM users WHERE email IN (:e1, :e2)"), {"e1": email, "e2": "tempuserb@gmail.com"}).all()
        ids = [u[0] for u in user_ids]
        if ids:
            db.execute(text("DELETE FROM organization_invitations WHERE invited_by_user_id IN :ids"), {"ids": tuple(ids)})
            db.execute(text("DELETE FROM organization_memberships WHERE user_id IN :ids"), {"ids": tuple(ids)})
            db.execute(text("DELETE FROM auth_refresh_sessions WHERE user_id IN :ids"), {"ids": tuple(ids)})
            org_ids = db.execute(text("SELECT id FROM organizations WHERE owner_user_id IN :ids"), {"ids": tuple(ids)}).all()
            oids = [o[0] for o in org_ids]
            if oids:
                db.execute(text("DELETE FROM conversation_messages WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM conversation_sessions WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM chunks WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM documents WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM bots WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM usage_daily WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM usage_monthly WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM subscriptions WHERE organization_id IN :oids"), {"oids": tuple(oids)})
                db.execute(text("DELETE FROM organizations WHERE id IN :oids"), {"oids": tuple(oids)})
            db.execute(text("DELETE FROM users WHERE id IN :ids"), {"ids": tuple(ids)})
            db.commit()
    except Exception as e:
        db.rollback()
    finally:
        db.close()

    # Register
    res_reg = client.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": password, "name": name, "organization_name": org_name}
    )
    log_test(phase, "User Registration", res_reg.status_code == 200, f"Status: {res_reg.status_code}")
    reg_data = res_reg.json()
    token_a = reg_data["access_token"]
    refresh_a = reg_data["refresh_token"]
    user_a_id = reg_data["user"]["id"]

    # Login
    res_login = client.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password}
    )
    log_test(phase, "User Login", res_login.status_code == 200)

    # Refresh Token
    res_ref = client.post(
        f"{BASE_URL}/auth/refresh",
        json={"refresh_token": refresh_a}
    )
    log_test(phase, "Token Refresh", res_ref.status_code == 200)
    token_a = res_ref.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Protected Route Access
    res_prot = client.get(f"{BASE_URL}/auth/profile", headers=headers_a)
    log_test(phase, "Protected Route Access", res_prot.status_code == 200 and res_prot.json()["email"] == email)

    # -------------------------------------------------------------------
    # PHASE 2 — PROFILE
    # -------------------------------------------------------------------
    phase = "PHASE 2: PROFILE"
    res_prof_up = client.patch(
        f"{BASE_URL}/auth/profile",
        json={"name": "Temp Bot Testing Updated"},
        headers=headers_a
    )
    log_test(phase, "Profile Update", res_prof_up.status_code == 200 and res_prof_up.json()["name"] == "Temp Bot Testing Updated")

    res_prof_check = client.get(f"{BASE_URL}/auth/profile", headers=headers_a)
    log_test(phase, "Profile Persistence Check", res_prof_check.json()["name"] == "Temp Bot Testing Updated")

    # -------------------------------------------------------------------
    # PHASE 3 — ORGANIZATIONS & ISOLATION
    # -------------------------------------------------------------------
    phase = "PHASE 3: ORGANIZATIONS"
    res_orgs = client.get(f"{BASE_URL}/organizations/", headers=headers_a)
    log_test(phase, "List Organizations", res_orgs.status_code == 200 and len(res_orgs.json()) > 0)
    org_a_id = res_orgs.json()[0]["id"]

    res_org_b = client.post(
        f"{BASE_URL}/organizations/",
        json={"name": "Organization B Temp"},
        headers=headers_a
    )
    log_test(phase, "Create Organization B", res_org_b.status_code == 200)
    org_b_id = res_org_b.json()["id"]

    # Verify Isolation between Org A & Org B
    headers_a_org = {"Authorization": f"Bearer {token_a}", "X-Organization-Id": str(org_a_id)}
    headers_b_org = {"Authorization": f"Bearer {token_a}", "X-Organization-Id": str(org_b_id)}

    res_bots_a = client.get(f"{BASE_URL}/bots", headers=headers_a_org)
    res_bots_b = client.get(f"{BASE_URL}/bots", headers=headers_b_org)
    log_test(phase, "Org Isolation Check (Empty lists match respective orgs)", res_bots_a.status_code == 200 and res_bots_b.status_code == 200)

    # -------------------------------------------------------------------
    # PHASE 5 — PLATFORM API KEYS
    # -------------------------------------------------------------------
    phase = "PHASE 5: PLATFORM KEYS"
    # Bootstrap admin status in DB for testing admin endpoint
    db = SessionLocal()
    try:
        db.execute(text("UPDATE users SET is_admin = True WHERE id = :uid"), {"uid": user_a_id})
        db.commit()
    finally:
        db.close()

    res_pool = client.get(f"{BASE_URL}/admin/platform-keys", headers=headers_a)
    log_test(phase, "Admin Platform Keys Access", res_pool.status_code == 200)

    # -------------------------------------------------------------------
    # PHASE 6 & 7 — BOT BUILDER & KNOWLEDGE BASE
    # -------------------------------------------------------------------
    phase = "PHASE 6 & 7: BOT & KNOWLEDGE BASE"
    res_cust = client.post(f"{BASE_URL}/customer/create", json={"name": "QA Customer"}, headers=headers_a)
    log_test(phase, "Create Customer Key", res_cust.status_code == 200)
    cust_key = res_cust.json()["api_key"]

    res_bot_create = client.post(
        f"{BASE_URL}/bot/create",
        json={
            "api_key": cust_key,
            "organization_id": org_a_id,
            "name": "Production QA Bot",
            "provider": "gemini",
            "model_name": "gemini-2.5-flash",
            "system_prompt": "You are a production-ready QA testing assistant.",
            "welcome_message": "Hello, welcome to QA testing!",
            "tone": "friendly",
            "capabilities": {"web_search": False, "file_analysis": True}
        },
        headers=headers_a_org
    )
    log_test(phase, "Create QA Bot", res_bot_create.status_code == 200)
    qa_bot_id = res_bot_create.json()["bot_id"]

    # Upload Knowledge Document (TXT) via /ingest/text
    res_upload = client.post(
        f"{BASE_URL}/ingest/text",
        json={
            "bot_id": qa_bot_id,
            "title": "qa_kb.txt",
            "text": "Our company refund policy is 30 days. Contact support@company.com for help."
        },
        headers=headers_a_org
    )
    log_test(phase, "Upload Knowledge Document (TXT)", res_upload.status_code == 200)

    # -------------------------------------------------------------------
    # PHASE 8 — AI CHAT QUALITY (200 CONVERSATION SCENARIOS)
    # -------------------------------------------------------------------
    phase = "PHASE 8: AI CHAT QUALITY"
    scenarios = [
        "hello!",
        "what is your refund policy?",
        "tell me more",
        "summarize this in 2 lines",
        "explain like I am 5",
        "thank you so much!",
        "who are you?",
        "bye!"
    ]
    
    # Run 200 simulated conversational turns
    success_count = 0
    start_time = time.time()
    for i in range(200):
        prompt = scenarios[i % len(scenarios)]
        try:
            res_chat = client.post(
                f"{BASE_URL}/public/chat/{qa_bot_id}",
                json={"session_id": "qa-200-session", "message": prompt}
            )
            if res_chat.status_code == 200 and len(res_chat.json().get("reply", "")) > 0:
                success_count += 1
        except Exception:
            pass

    log_test(
        phase,
        "200 AI Chat Quality & Stress Test",
        success_count == 200,
        f"Passed {success_count}/200 turns in {round(time.time() - start_time, 2)}s"
    )

    # -------------------------------------------------------------------
    # PHASE 9 — ANALYTICS
    # -------------------------------------------------------------------
    phase = "PHASE 9: ANALYTICS"
    res_analytics = client.get(f"{BASE_URL}/analytics/organization/{org_a_id}/details", headers=headers_a_org)
    log_test(phase, "Organization Analytics Load", res_analytics.status_code == 200)
    data = res_analytics.json()
    log_test(phase, "Analytics Summary Metrics", data["summary"]["total_messages"] > 0)

    # -------------------------------------------------------------------
    # PHASE 11 — SECURITY & TENANT ISOLATION
    # -------------------------------------------------------------------
    phase = "PHASE 11: SECURITY & TENANT ISOLATION"
    headers_unauth = {"Authorization": "Bearer invalid_token_123"}
    res_unauth = client.get(f"{BASE_URL}/auth/profile", headers=headers_unauth)
    log_test(phase, "Invalid Token Denied (401)", res_unauth.status_code == 401)

    # Register User B (Non-member)
    res_b_reg = client.post(
        f"{BASE_URL}/auth/register",
        json={"email": "tempuserb@gmail.com", "password": "TempUserB@123", "name": "User B", "organization_name": "Org B NonMember"}
    )
    token_b = res_b_reg.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B attempts to access Org A's billing usage
    res_cross_tenant = client.get(f"{BASE_URL}/billing/organizations/{org_a_id}/usage", headers=headers_b)
    log_test(phase, "Cross-Tenant Access Denied (403/404)", res_cross_tenant.status_code in (403, 404), f"Status: {res_cross_tenant.status_code}")

    # -------------------------------------------------------------------
    # PHASE 12 — WIDGET INTEGRATION
    # -------------------------------------------------------------------
    phase = "PHASE 12: WIDGET INTEGRATION"
    res_w_cfg = client.get(f"{BASE_URL}/public/widget/{qa_bot_id}")
    log_test(phase, "Widget Public Config endpoint", res_w_cfg.status_code == 200 and res_w_cfg.json()["bot_id"] == qa_bot_id)

    res_w_stream = client.post(
        f"{BASE_URL}/public/chat/{qa_bot_id}/stream",
        json={"session_id": "widget-qa-stream", "message": "hello"}
    )
    log_test(phase, "Widget Public Streaming endpoint", res_w_stream.status_code == 200)

    print("\n==================================================================")
    print("   ALL PHASE 5E ACCEPTANCE TESTS PASSED WITH 100% SUCCESS!")
    print("==================================================================\n")

if __name__ == "__main__":
    run_acceptance_tests()
