"""Real PostgreSQL races in a private, randomly named, disposable schema."""
import concurrent.futures
import re
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from database.connection import Base, engine as configured_engine
from database.models import Bot, Customer, Organization, PlatformApiKey, User
from routes.admin_routes import ConfigSnapshot, ProviderConfigRequest, assign_platform_key, update_provider_config
from services import platform_key_service as keys


class PlatformAdminConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "admin_console_test_" + uuid.uuid4().hex
        with configured_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(configured_engine.url.set(query={"options": f"-c search_path={cls.schema},public,extensions"}), hide_parameters=True)
        cls.sessions = sessionmaker(bind=cls.engine, autoflush=False)
        try:
            with cls.engine.connect() as conn:
                assert conn.execute(text("SELECT current_schema()")).scalar() == cls.schema
                assert conn.execute(text("SHOW transaction_isolation")).scalar() == "read committed"
            # checkfirst=False is essential: public tables must never make the
            # isolated schema silently skip creating its own test tables.
            Base.metadata.create_all(cls.engine, checkfirst=False)
            assert set(Base.metadata.tables) <= set(inspect(cls.engine).get_table_names(schema=cls.schema))
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        assert re.fullmatch(r"admin_console_test_[0-9a-f]{32}", cls.schema)
        with configured_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))

    def setUp(self):
        with self.sessions() as db:
            # Earlier fixtures are private to this schema; remove their capacity
            # from automatic-selection candidates without touching their history.
            db.query(PlatformApiKey).update({"status": "disabled"})
            suffix = uuid.uuid4().hex
            user = User(name="Synthetic operator", email=f"{suffix}@example.test", password_hash="synthetic", is_admin=True)
            customer = Customer(name="Synthetic", api_key=suffix)
            org = Organization(name="Synthetic", slug=suffix)
            other_org = Organization(name="Synthetic other", slug=suffix + "-other")
            other_customer = Customer(name="Synthetic other", api_key=suffix + "-other")
            db.add_all([user, customer, org, other_org, other_customer]); db.flush()
            bots = [Bot(name=f"Synthetic {i}", customer_id=customer.id if i % 2 == 0 else other_customer.id,
                        organization_id=org.id if i % 2 == 0 else other_org.id) for i in range(6)]
            profiles = [PlatformApiKey(provider="gemini", encrypted_key=b"synthetic-not-used-for-generation", label=f"Profile {i}") for i in range(2)]
            db.add_all(bots + profiles); db.commit()
            self.bot_ids = [bot.id for bot in bots]; self.key_ids = [key.id for key in profiles]
            self.user = SimpleNamespace(id=user.id)

    def race(self, *operations):
        barrier = threading.Barrier(len(operations))
        def call(operation):
            with self.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    operation(db)
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(call, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    def test_assignment_and_disable_retains_existing_reference_but_blocks_key(self):
        key_id, bot_id = self.key_ids[0], self.bot_ids[0]
        results = self.race(lambda db: assign_platform_key(key_id, bot_id, self.user, db),
                            lambda db: keys.admin_disable_key(db, key_id, self.user.id))
        self.assertIn(results[0], (200, 409)); self.assertEqual(results[1], 200)
        with self.sessions() as db:
            self.assertEqual(db.get(PlatformApiKey, key_id).status, "disabled")
            self.assertEqual(db.get(Bot, bot_id).platform_credential_id, key_id if results[0] == 200 else None)
            self.assertIsNone(keys.get_decrypted_key_for_bot(db, bot_id))
            self.assertIsNone(db.get(PlatformApiKey, key_id).allocated_to_bot_id)

    def test_assignment_and_deletion_never_leave_dangling_reference(self):
        key_id, bot_id = self.key_ids[0], self.bot_ids[0]
        results = self.race(lambda db: assign_platform_key(key_id, bot_id, self.user, db),
                            lambda db: keys.admin_delete_key(db, key_id, self.user.id))
        self.assertIn(results, ([200, 409], [404, 200]))
        with self.sessions() as db:
            key, bot = db.get(PlatformApiKey, key_id), db.get(Bot, bot_id)
            self.assertEqual(bot.platform_credential_id, key_id if key else None)

    def test_four_bots_cannot_exceed_capacity_two(self):
        key_id = self.key_ids[0]
        results = self.race(*(lambda db, bot_id=bot_id: assign_platform_key(key_id, bot_id, self.user, db) for bot_id in self.bot_ids[:4]))
        self.assertEqual(sorted(results), [200, 200, 409, 409])
        with self.sessions() as db:
            self.assertEqual(db.query(Bot).filter(Bot.platform_credential_id == key_id).count(), 2)

    def test_four_automatic_allocations_fill_two_profiles(self):
        def allocate(db, bot_id):
            keys.lock_credential_lifecycle(db)
            bot = db.get(Bot, bot_id)
            self.assertTrue(keys.allocate_key_to_bot(db, bot))
            db.commit()
        results = self.race(*(lambda db, bot_id=bot_id: allocate(db, bot_id) for bot_id in self.bot_ids[:4]))
        self.assertEqual(results, [200] * 4)
        with self.sessions() as db:
            self.assertEqual([keys.assignment_count(db, key_id) for key_id in self.key_ids], [2, 2])

    def test_four_new_bots_automatically_share_only_two_slots(self):
        with self.sessions() as db:
            keys.admin_disable_key(db, self.key_ids[1])
            original = db.get(Bot, self.bot_ids[0])
            customer_id, organization_id = original.customer_id, original.organization_id
        batch = "Concurrent new " + uuid.uuid4().hex
        def create(db):
            bot = Bot(name=batch, customer_id=customer_id, organization_id=organization_id)
            db.add(bot); db.flush()
            keys.allocate_key_to_bot(db, bot)
            db.commit()
        self.assertEqual(self.race(create, create, create, create), [200] * 4)
        with self.sessions() as db:
            rows = db.query(Bot).filter(Bot.name == batch).all()
            self.assertEqual(len(rows), 4)
            self.assertEqual(sum(b.platform_credential_id is not None for b in rows), 2)
            self.assertEqual(keys.assignment_count(db, self.key_ids[0]), 2)

    def test_shared_profile_usage_increments_are_atomic(self):
        with self.sessions() as db:
            for bot_id in self.bot_ids[:2]:
                assign_platform_key(self.key_ids[0], bot_id, self.user, db)
        self.race(*(lambda db, bot_id=bot_id: keys.increment_usage(db, bot_id, 7)
                    for bot_id in self.bot_ids[:2] * 4))
        with self.sessions() as db:
            profile = db.get(PlatformApiKey, self.key_ids[0])
            self.assertEqual((profile.requests_count, profile.tokens_used), (8, 56))

    def test_capacity_reduction_and_assignment_serialize(self):
        key_id = self.key_ids[0]
        with self.sessions() as db:
            assign_platform_key(key_id, self.bot_ids[0], self.user, db)
        results = self.race(
            lambda db: assign_platform_key(key_id, self.bot_ids[1], self.user, db),
            lambda db: keys.admin_update_key(db, key_id, {"max_bot_assignments": 1, "expected_max_bot_assignments": 2}, self.user.id),
        )
        self.assertEqual(sorted(results), [200, 409])
        with self.sessions() as db:
            self.assertLessEqual(keys.assignment_count(db, key_id), db.get(PlatformApiKey, key_id).max_bot_assignments)
            self.assertEqual(db.get(Bot, self.bot_ids[0]).platform_credential_id, key_id)

    def test_two_capacity_edits_reject_stale_snapshot(self):
        results = self.race(*(lambda db, cap=cap: keys.admin_update_key(db, self.key_ids[0],
            {"max_bot_assignments": cap, "expected_max_bot_assignments": 2}, self.user.id) for cap in (3, 4)))
        self.assertEqual(sorted(results), [200, 409])

    def test_two_admin_updates_reject_stale_snapshot(self):
        def update(db, key_id):
            data = ProviderConfigRequest(provider="gemini", model_name="gemini-1.5-pro", credential_profile_id=key_id,
                                         expected=ConfigSnapshot(provider="gemini", model_name="gemini-2.5-flash", credential_profile_id=None))
            return update_provider_config(self.bot_ids[0], data, self.user, db)
        with patch("routes.admin_routes.invalidate_bot_cache"):
            results = self.race(lambda db: update(db, self.key_ids[0]), lambda db: update(db, self.key_ids[1]))
        self.assertEqual(sorted(results), [200, 409])


if __name__ == "__main__":
    unittest.main()
