"""
Comprehensive Platform API Key Pool Tests
==========================================
Tests:
  1. Encryption / decryption round-trip
  2. Key allocation to bot
  3. Key release from bot
  4. Provider switching (release old, allocate new)
  5. No available keys leaves unassigned
  6. BYOK does not allocate platform key
  7. Duplicate allocation is idempotent
  8. Admin enable / disable
  9. Disable assigned key retains bot reference
  10. Usage metrics increment
  11. Delete assigned key raises error
  12. Can delete after release

Run:
  cd backend && python scripts/test_admin_regressions.py
  Never run this legacy fixture script directly against a customer database.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# Load .env so PLATFORM_KEY_ENCRYPTION_KEY is available BEFORE any imports
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

if not os.getenv("PLATFORM_KEY_ENCRYPTION_KEY"):
    from cryptography.fernet import Fernet
    os.environ["PLATFORM_KEY_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    print("[setup] Generated temporary encryption key for this test run.")
else:
    print(f"[setup] Using PLATFORM_KEY_ENCRYPTION_KEY from .env")

# Import after env var is set
from database.connection import SessionLocal, init_db
from database.models import Bot, Customer, PlatformApiKey
from services import platform_key_service
from utils.encryption import decrypt_key, encrypt_key, mask_key, _get_fernet

# Clear cache so Fernet picks up the key we just set
_get_fernet.cache_clear()
from fastapi import HTTPException

PASS = "[PASS]"
FAIL = "[FAIL]"

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    status = PASS if condition else FAIL
    print(f"  {status}  {name}" + (f"  [{detail}]" if detail else ""))


def fresh_db():
    """Return a new session. Caller must commit/close."""
    return SessionLocal()


def make_key(provider="gemini", raw_key="AIza-test-key-123456") -> dict:
    """Create a platform key in its own committed session. Returns {id, provider}."""
    with fresh_db() as db:
        k = platform_key_service.admin_add_key(db, provider=provider, plaintext_api_key=raw_key, label=f"Test-{provider}")
        return {"id": k.id, "provider": k.provider}


def make_bot(name="TestBot", provider="gemini", has_custom_key=False) -> dict:
    """Create a customer+bot in its own committed session. Returns {id}."""
    import secrets
    with fresh_db() as db:
        customer = Customer(name=f"C-{name}", api_key=secrets.token_hex(8))
        db.add(customer)
        db.flush()
        bot = Bot(
            name=name,
            customer_id=customer.id,
            provider=provider,
            model_name="gemini-2.5-flash" if provider == "gemini" else "gpt-4.1-mini",
            provider_api_key="sk-custom-byok-key" if has_custom_key else None,
        )
        db.add(bot)
        db.commit()
        db.refresh(bot)
        return {"id": bot.id}


def cleanup_key(key_id: int):
    with fresh_db() as db:
        k = db.query(PlatformApiKey).filter(PlatformApiKey.id == key_id).first()
        if k:
            db.delete(k)
            db.commit()


def cleanup_bot(bot_id: int):
    with fresh_db() as db:
        b = db.query(Bot).filter(Bot.id == bot_id).first()
        if b:
            db.delete(b)
            db.commit()


# ─────────────────────────────────────────────────────────────────────────────
print("\n[1/12] Initializing database schema...")
try:
    init_db()
    print(f"  {PASS}  Database schema initialized")
except Exception as e:
    print(f"  {FAIL}  Database init failed: {e}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
print("\n[2/12] Test: Encryption round-trip")
raw = "AIza-my-super-secret-provider-key-xyz"
encrypted = encrypt_key(raw)
decrypted = decrypt_key(encrypted)
check("encrypt_key returns bytes", isinstance(encrypted, bytes))
check("decrypt_key returns original plaintext", decrypted == raw)
masked = mask_key(raw)
check("mask_key hides middle", "****" in str(masked))
check("mask_key never returns full value", masked != raw)


# ─────────────────────────────────────────────────────────────────────────────
print("\n[3/12] Test: Key allocation to bot")
k1 = make_key(provider="gemini", raw_key="AIza-allocation-test-key")
b1 = make_bot(name="AllocationBot", provider="gemini")
try:
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k1["id"]).first()
        bot = db.query(Bot).filter(Bot.id == b1["id"]).first()
        check("key status is available before allocation", pk.status == "available")
        check("key allocated_to_bot_id is None before allocation", pk.allocated_to_bot_id is None)
        
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
        db.refresh(pk)
        
        check("key status is assigned after allocation", pk.status == "assigned")
        check("bot references key", db.get(Bot, b1["id"]).platform_credential_id == pk.id)
        
        retrieved = platform_key_service.get_decrypted_key_for_bot(db, b1["id"])
        check("get_decrypted_key_for_bot returns plaintext", retrieved == "AIza-allocation-test-key")
finally:
    cleanup_key(k1["id"])
    cleanup_bot(b1["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[4/12] Test: Key release from bot")
k2 = make_key(provider="gemini", raw_key="AIza-release-test-key-12345")
b2 = make_bot(name="ReleaseBot", provider="gemini")
try:
    # Allocate
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b2["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    # Verify assigned
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k2["id"]).first()
        check("key assigned before release", pk.status == "assigned")
    
    # Release
    with fresh_db() as db:
        platform_key_service.release_key_from_bot(db, b2["id"])
        db.commit()
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k2["id"]).first()
        check("key status is available after release", pk.status == "available")
        check("key allocated_to_bot_id is None after release", pk.allocated_to_bot_id is None)
        retrieved = platform_key_service.get_decrypted_key_for_bot(db, b2["id"])
        check("get_decrypted_key_for_bot returns None after release", retrieved is None)
finally:
    cleanup_key(k2["id"])
    cleanup_bot(b2["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[5/12] Test: Provider switching")
k_gemini = make_key(provider="gemini", raw_key="AIza-switch-gemini-key")
k_openai = make_key(provider="openai", raw_key="sk-switch-openai-key-12345")
b3 = make_bot(name="SwitchBot", provider="gemini")
try:
    # Allocate gemini
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b3["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k_gemini["id"]).first()
        check("gemini key assigned before switch", pk.status == "assigned")
    
    # Switch provider to openai
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b3["id"]).first()
        bot.provider = "openai"
        bot.model_name = "gpt-4.1-mini"
        db.flush()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    with fresh_db() as db:
        gk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k_gemini["id"]).first()
        ok = db.query(PlatformApiKey).filter(PlatformApiKey.id == k_openai["id"]).first()
        check("old gemini key released after provider switch", gk.status == "available")
        check("new openai key assigned after provider switch", ok.status == "assigned")
        check("bot references new openai key", db.get(Bot, b3["id"]).platform_credential_id == ok.id)
finally:
    cleanup_key(k_gemini["id"])
    cleanup_key(k_openai["id"])
    cleanup_bot(b3["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[6/12] Test: No available keys error")
b4 = make_bot(name="NoKeyBot", provider="claude")
try:
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b4["id"]).first()
        allocated = platform_key_service.allocate_key_to_bot(db, bot)
        check("No capacity returns unassigned", allocated is False)
        check("No profile reference created", bot.platform_credential_id is None)
finally:
    cleanup_bot(b4["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[7/12] Test: Idempotent allocation (same provider)")
k5 = make_key(provider="gemini", raw_key="AIza-idempotent-key-12345")
b5 = make_bot(name="IdempotentBot", provider="gemini")
try:
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b5["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    # Second allocation call should be no-op
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b5["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k5["id"]).first()
        check("key still assigned after double allocation call", pk.status == "assigned")
        check("key still allocated to same bot", db.get(Bot, b5["id"]).platform_credential_id == pk.id)
finally:
    cleanup_key(k5["id"])
    cleanup_bot(b5["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[8/12] Test: BYOK bot does not consume platform key")
k6 = make_key(provider="gemini", raw_key="AIza-byok-available-key-1234")
b6 = make_bot(name="BYOKBot", provider="gemini", has_custom_key=True)
try:
    with fresh_db() as db:
        retrieved = platform_key_service.get_decrypted_key_for_bot(db, b6["id"])
        check("BYOK bot has no platform key allocated", retrieved is None)
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k6["id"]).first()
        check("Platform key remains available (not consumed)", pk.status == "available")
finally:
    cleanup_key(k6["id"])
    cleanup_bot(b6["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[9/12] Test: Admin enable / disable")
k7 = make_key(provider="openai", raw_key="sk-admin-toggle-test-12345678")
try:
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k7["id"]).first()
        check("key status is available after creation", pk.status == "available")
    
    with fresh_db() as db:
        disabled = platform_key_service.admin_disable_key(db, k7["id"])
        check("key status is disabled after admin_disable_key", disabled.status == "disabled")
    
    with fresh_db() as db:
        enabled = platform_key_service.admin_enable_key(db, k7["id"])
        check("key status is available after admin_enable_key", enabled.status == "available")
finally:
    cleanup_key(k7["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[10/12] Test: Disable assigned key retains bot reference")
k8 = make_key(provider="gemini", raw_key="AIza-disable-assigned-key-1234")
b7 = make_bot(name="DisableBot", provider="gemini")
try:
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b7["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k8["id"]).first()
        check("key assigned before disable", pk.status == "assigned")
    
    with fresh_db() as db:
        platform_key_service.admin_disable_key(db, k8["id"])
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k8["id"]).first()
        check("key status is disabled", pk.status == "disabled")
        check("bot reference retained after disable", db.get(Bot, b7["id"]).platform_credential_id == pk.id)
finally:
    cleanup_key(k8["id"])
    cleanup_bot(b7["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[11/12] Test: Usage metrics increment")
k9 = make_key(provider="gemini", raw_key="AIza-metrics-test-key-123456")
b8 = make_bot(name="MetricsBot", provider="gemini")
try:
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b8["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k9["id"]).first()
        check("requests_count starts at 0", pk.requests_count == 0)
        check("tokens_used starts at 0", pk.tokens_used == 0)
        check("last_used_at is None before use", pk.last_used_at is None)
    
    platform_key_service.increment_usage(None, b8["id"], tokens=150)  # opens own session
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k9["id"]).first()
        check("requests_count is 1 after increment", pk.requests_count == 1)
        check("tokens_used is 150 after increment", pk.tokens_used == 150)
        check("last_used_at is set after increment", pk.last_used_at is not None)
    
    platform_key_service.increment_usage(None, b8["id"], tokens=300)
    
    with fresh_db() as db:
        pk = db.query(PlatformApiKey).filter(PlatformApiKey.id == k9["id"]).first()
        check("requests_count is 2 after second increment", pk.requests_count == 2)
        check("tokens_used is 450 after second increment", pk.tokens_used == 450)
finally:
    cleanup_key(k9["id"])
    cleanup_bot(b8["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[12/12] Test: Delete assigned key raises 409 / can delete after release")
k10 = make_key(provider="gemini", raw_key="AIza-delete-assigned-test-1234")
b9 = make_bot(name="DeleteBot", provider="gemini")
try:
    with fresh_db() as db:
        bot = db.query(Bot).filter(Bot.id == b9["id"]).first()
        platform_key_service.allocate_key_to_bot(db, bot)
        db.commit()
    
    delete_error = False
    with fresh_db() as db:
        try:
            platform_key_service.admin_delete_key(db, k10["id"])
        except HTTPException as exc:
            delete_error = exc.status_code == 409
    check("HTTP 409 raised when deleting assigned key", delete_error)
    
    # Release then delete
    with fresh_db() as db:
        platform_key_service.release_key_from_bot(db, b9["id"])
        db.commit()
    
    try:
        with fresh_db() as db:
            platform_key_service.admin_delete_key(db, k10["id"])
        check("Can delete key after release", True)
        k10["id"] = None  # already deleted
    except Exception as e:
        check("Can delete key after release", False, str(e))
finally:
    if k10.get("id"):
        cleanup_key(k10["id"])
    cleanup_bot(b9["id"])


# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
total = len(results)
print(f"\nResults: {passed}/{total} tests passed")
if failed > 0:
    print(f"\n{FAIL} FAILED TESTS:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}" + (f"  [{detail}]" if detail else ""))
    sys.exit(1)
else:
    print(f"\n{PASS} All platform API key tests passed!")
    sys.exit(0)
