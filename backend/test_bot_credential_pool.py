"""Deterministic bot-capacity contracts, using only isolated synthetic data."""
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from database.models import AuditLog, Bot, PlatformApiKey, UsageMonthly
from services.usage_service import record_usage
from services import platform_key_service as keys
from services.llm_router import LLMRouterError, _resolve_api_key
import test_platform_admin_console as console_fixture


class BotCredentialPoolTests(unittest.TestCase):
    # Reuse the existing isolated API fixture without inheriting/re-running its tests.
    add = console_fixture.PlatformAdminConsoleTests.add
    bot = console_fixture.PlatformAdminConsoleTests.bot
    configure = console_fixture.PlatformAdminConsoleTests.configure

    def setUp(self):
        console_fixture.PlatformAdminConsoleTests.setUp(self)
        self.patches = ExitStack()
        for name in ("ensure_can_create_bot", "refresh_resource_usage", "ensure_can_promote_knowledge", "invalidate_bot_cache"):
            self.patches.enter_context(patch("services.bot_service." + name))

    def tearDown(self):
        self.patches.close()
        console_fixture.PlatformAdminConsoleTests.tearDown(self)

    def create(self, **changes):
        data = {"name": "Synthetic new bot", "organization_id": 1, "provider": "gemini", "model_name": "gemini-2.5-flash", **changes}
        result = self.client.post("/bot/create", json=data, headers=self.headers[3])
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["id"]

    def capacity(self, key_id, capacity, expected=2):
        return self.client.put(f"/admin/platform-keys/{key_id}", headers=self.headers[1],
                               json={"max_bot_assignments": capacity, "expected_max_bot_assignments": expected})

    def test_default_two_and_exact_oldest_first_across_same_customer_bots(self):
        first, second = self.add(label="First"), self.add(label="Second")
        self.assertEqual((first["max_bot_assignments"], first["remaining_capacity"]), (2, 2))
        ids = [self.create() for _ in range(5)]
        with self.sessions() as db:
            bots = [db.get(Bot, bot_id) for bot_id in ids]
            self.assertEqual(len({b.customer_id for b in bots}), 1)
            self.assertEqual([b.platform_credential_id for b in bots], [first["id"], first["id"], second["id"], second["id"], None])
            self.assertTrue(all(k.allocated_to_bot_id is None for k in db.query(PlatformApiKey)))
            self.assertEqual(db.query(AuditLog).filter(AuditLog.action.like("platform.credential.auto_assigned:%")).count(), 4)

    def test_profile_shared_across_customers_and_organizations_with_separate_usage(self):
        key = self.add()
        for bot_id in (1, 2):
            self.assertEqual(self.configure("gemini", "gemini-2.5-flash", key["id"], bot_id=bot_id).status_code, 200)
        with self.sessions() as db:
            keys.increment_usage(db, 1, 7)
            keys.increment_usage(db, 2, 11)
            record_usage(db, 1, messages_sent=1, tokens_used=7)
            record_usage(db, 2, messages_sent=1, tokens_used=11)
            ledger = db.query(UsageMonthly).order_by(UsageMonthly.organization_id).all()
            self.assertEqual([(row.organization_id, row.messages_sent, row.tokens_used) for row in ledger], [(1, 1, 7), (2, 1, 11)])
            profile = db.get(PlatformApiKey, key["id"])
            self.assertEqual((profile.requests_count, profile.tokens_used), (2, 18))
            self.assertEqual((db.get(Bot, 1).organization_id, db.get(Bot, 2).organization_id), (1, 2))
            self.assertEqual(keys.assignment_count(db, key["id"]), 2)
        listing = self.client.get("/admin/platform-keys", headers=self.headers[1]).json()["items"][0]
        self.assertEqual({b["organization_id"] for b in listing["assigned_bots"]}, {1, 2})
        self.assertEqual({b["customer_name"] for b in listing["assigned_bots"]}, {"Customer Alpha", "Customer Beta"})

    def test_no_capacity_and_disabled_bots_never_use_environment_generation_key(self):
        bot_id = self.create()
        with self.sessions() as db, patch("database.connection.SessionLocal", self.sessions), patch.dict(os.environ, {"GEMINI_API_KEY": "synthetic-environment-must-not-be-used"}):
            with self.assertRaises(LLMRouterError) as failure:
                _resolve_api_key(db.get(Bot, bot_id))
            self.assertEqual(failure.exception.status_code, 503)
            self.assertNotIn("capacity", str(failure.exception))
        key = self.add()
        self.configure("gemini", "gemini-2.5-flash", key["id"], bot_id=bot_id)
        self.client.post(f'/admin/platform-keys/{key["id"]}/disable', headers=self.headers[1])
        with self.sessions() as db, patch("database.connection.SessionLocal", self.sessions):
            self.assertEqual(db.get(Bot, bot_id).platform_credential_id, key["id"])
            with self.assertRaises(LLMRouterError): _resolve_api_key(db.get(Bot, bot_id))

    def test_byok_create_clear_switch_and_delete_release_only_one_slot(self):
        key = self.add()
        first = self.create(provider_api_key="synthetic-byok-credential")
        with self.sessions() as db:
            self.assertIsNone(db.get(Bot, first).platform_credential_id)
            self.assertEqual(keys.assignment_count(db, key["id"]), 0)
            self.assertFalse(keys.allocate_key_to_bot(db, db.get(Bot, first)))
            with self.assertRaises(HTTPException): keys.assign_key_to_bot(db, key["id"], db.get(Bot, first))
        response = self.client.put(f"/bot/{first}", json={"provider_api_key": None}, headers=self.headers[3])
        self.assertEqual(response.status_code, 200, response.text)
        second = self.create()
        response = self.client.put(f"/bot/{first}", json={"provider_api_key": "synthetic-new-byok"}, headers=self.headers[3])
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertEqual(keys.assignment_count(db, key["id"]), 1)
            self.assertEqual(db.get(Bot, second).platform_credential_id, key["id"])
        self.assertEqual(self.client.delete(f"/bot/{second}", headers=self.headers[3]).status_code, 200)
        with self.sessions() as db: self.assertEqual(keys.assignment_count(db, key["id"]), 0)

    def test_manual_move_does_not_move_other_bot_and_full_target_is_atomic(self):
        first, target = self.add(), self.add(label="Target")
        for bot_id in (1, 2): self.configure("gemini", "gemini-2.5-flash", first["id"], bot_id=bot_id)
        self.assertEqual(self.capacity(target["id"], 1).status_code, 200)
        self.assertEqual(self.configure("gemini", "gemini-2.5-flash", target["id"]).status_code, 200)
        self.assertEqual(self.bot(2)["credential_profile_id"], first["id"])
        self.assertEqual(self.configure("gemini", "gemini-2.5-flash", target["id"], bot_id=2).status_code, 409)
        self.assertEqual(self.bot(2)["credential_profile_id"], first["id"])
        self.assertEqual(self.configure("gemini", "gemini-1.5-pro", target["id"]).status_code, 200)
        with self.sessions() as db:
            self.assertEqual([keys.assignment_count(db, k["id"]) for k in (first, target)], [1, 1])

    def test_provider_switch_auto_assigns_matching_profile_or_leaves_unassigned(self):
        gemini, openai = self.add(), self.add("openai")
        first, second = self.create(), self.create()
        response = self.client.put(f"/bot/{first}", json={"provider": "openai", "model_name": "gpt-4.1-mini"}, headers=self.headers[3])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.bot(first)["credential_profile_id"], openai["id"])
        self.assertEqual(self.bot(second)["credential_profile_id"], gemini["id"])
        self.assertEqual(self.configure("claude", "claude-3-5-sonnet", None, bot_id=first).status_code, 200)
        self.assertIsNone(self.bot(first)["credential_profile_id"])
        self.assertEqual(self.configure("openai", "gpt-4.1-mini", None, bot_id=first).status_code, 200)
        self.assertEqual(self.bot(first)["credential_profile_id"], openai["id"])

    def test_disable_keeps_all_references_reenable_resumes_without_redistribution(self):
        first, other = self.add(), self.add(label="Other")
        ids = [self.create(), self.create()]
        path = f'/admin/platform-keys/{first["id"]}'
        disabled = self.client.post(path + "/disable", headers=self.headers[1]).json()
        self.assertEqual((disabled["assigned_bot_count"], disabled["status"]), (2, "disabled"))
        with self.sessions() as db:
            for bot_id in ids:
                self.assertFalse(keys.allocate_key_to_bot(db, db.get(Bot, bot_id)))
                self.assertEqual(db.get(Bot, bot_id).platform_credential_id, first["id"])
                self.assertIsNone(keys.get_decrypted_key_for_bot(db, bot_id))
        self.assertEqual(self.client.delete(path, headers=self.headers[1]).status_code, 409)
        third = self.create()
        self.assertEqual(self.bot(third)["credential_profile_id"], other["id"])
        self.client.post(path + "/enable", headers=self.headers[1])
        with self.sessions() as db:
            for bot_id in ids: self.assertEqual(keys.get_decrypted_key_for_bot(db, bot_id), "synthetic-provider-secret")

    def test_capacity_validation_lowering_and_stale_updates(self):
        key = self.add()
        self.create(); self.create()
        self.assertIn("2 currently assigned", self.capacity(key["id"], 1).text)
        self.assertEqual(self.capacity(key["id"], 1).status_code, 409)
        for invalid in (0, -1, 1.5, True, "3", None, 2147483648):
            self.assertEqual(self.capacity(key["id"], invalid).status_code, 422)
        self.assertEqual(self.capacity(key["id"], 3).status_code, 200)
        self.assertEqual(self.capacity(key["id"], 4).status_code, 409)
        third = self.create()
        self.assertEqual(self.bot(third)["credential_profile_id"], key["id"])
        with self.sessions() as db:
            db.get(PlatformApiKey, key["id"]).max_bot_assignments = 0
            with self.assertRaises(IntegrityError): db.commit()

    def test_capacity_one_and_bounded_assignment_preview_filters(self):
        key = self.add()
        self.assertEqual(self.capacity(key["id"], 1).status_code, 200)
        first, second = self.create(), self.create()
        self.assertEqual(self.bot(first)["credential_profile_id"], key["id"])
        self.assertIsNone(self.bot(second)["credential_profile_id"])
        self.assertEqual(self.capacity(key["id"], 12, expected=1).status_code, 200)
        for _ in range(11): self.create()
        listing = self.client.get("/admin/platform-keys", headers=self.headers[1]).json()["items"][0]
        self.assertEqual((listing["assigned_bot_count"], len(listing["assigned_bots"]), listing["remaining_capacity"]), (12, 10, 0))
        assigned = self.client.get(f'/admin/bots?credential_profile_id={key["id"]}&limit=5', headers=self.headers[1]).json()
        self.assertEqual((assigned["total"], len(assigned["items"])), (12, 5))
        unassigned = self.client.get("/admin/bots?unassigned=true&provider=gemini", headers=self.headers[1]).json()
        self.assertIn(second, [b["id"] for b in unassigned["items"]])
        for bot_id, expected in ((first, 1), (second, 0)):
            choices = self.client.get(f"/admin/platform-keys?assignable_to_bot_id={bot_id}", headers=self.headers[1]).json()
            self.assertEqual(choices["total"], expected)

    def test_clone_allocates_a_separate_slot_and_customer_cannot_set_profile(self):
        key = self.add()
        first = self.create()
        response = self.client.post(f"/bot/{first}/clone", headers=self.headers[3])
        self.assertEqual(response.status_code, 200, response.text)
        clone = response.json()["id"]
        self.assertNotEqual(first, clone)
        self.assertEqual(self.bot(clone)["credential_profile_id"], key["id"])
        for data in ({"platform_credential_id": 999}, {"max_bot_assignments": 99}):
            result = self.client.put(f"/bot/{first}", json=data, headers=self.headers[3])
            self.assertIn(result.status_code, (200, 422))  # Unknown customer fields may be ignored.
            self.assertEqual(self.bot(first)["credential_profile_id"], key["id"])
        body = self.client.get(f"/bot/{first}", headers=self.headers[3]).json()
        for field in ("platform_credential_id", "credential_profile_id", "uses_platform_key", "assigned_bot_count", "max_bot_assignments", "remaining_capacity"):
            self.assertNotIn(field, body)

    def test_legacy_reverse_link_is_not_a_runtime_fallback(self):
        key = self.add()
        with self.sessions() as db:
            db.get(PlatformApiKey, key["id"]).allocated_to_bot_id = 1
            db.commit()
            self.assertIsNone(keys.get_decrypted_key_for_bot(db, 1))
            self.assertEqual(keys.assignment_count(db, key["id"]), 0)
            self.assertTrue(keys.allocate_key_to_bot(db, db.get(Bot, 2)))
            db.commit()
            self.assertIsNone(db.get(Bot, 1).platform_credential_id)
            self.assertEqual(db.get(Bot, 2).platform_credential_id, key["id"])

    def test_stale_request_cannot_send_new_providers_key_to_old_adapter(self):
        key = self.add("openai")
        self.assertEqual(self.configure("openai", "gpt-4.1-mini", key["id"]).status_code, 200)
        stale = Bot(id=1, name="Stale snapshot", provider="gemini", model_name="gemini-2.5-flash")
        with patch("database.connection.SessionLocal", self.sessions):
            with self.assertRaises(LLMRouterError): _resolve_api_key(stale)
        with self.sessions() as db:
            self.assertIsNone(keys.get_decrypted_key_for_bot(db, 1, expected_provider="gemini"))
            self.assertEqual(keys.get_decrypted_key_for_bot(db, 1, expected_provider="openai"), "synthetic-provider-secret")


if __name__ == "__main__":
    unittest.main()
