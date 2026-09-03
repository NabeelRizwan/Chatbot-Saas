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
        cls.sessions = sessionmaker(bind=cls.engine)
        try:
            with cls.engine.connect() as conn:
                assert conn.execute(text("SELECT current_schema()")).scalar() == cls.schema
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
            suffix = uuid.uuid4().hex
            user = User(name="Synthetic operator", email=f"{suffix}@example.test", password_hash="synthetic", is_admin=True)
            customer = Customer(name="Synthetic", api_key=suffix)
            org = Organization(name="Synthetic", slug=suffix)
            db.add_all([user, customer, org]); db.flush()
            bots = [Bot(name=f"Synthetic {i}", customer_id=customer.id, organization_id=org.id) for i in range(2)]
            profiles = [PlatformApiKey(provider="gemini", encrypted_key=b"synthetic-not-used-for-generation", label=f"Profile {i}") for i in range(2)]
            db.add_all(bots + profiles); db.commit()
            self.bot_ids = [bot.id for bot in bots]; self.key_ids = [key.id for key in profiles]
            self.user = SimpleNamespace(id=user.id)

    def race(self, first, second):
        barrier = threading.Barrier(2)
        def call(operation):
            with self.sessions() as db:
                barrier.wait(timeout=10)
                try:
                    operation(db)
                    return 200
                except HTTPException as exc:
                    db.rollback()
                    return exc.status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(call, operation) for operation in (first, second)]
            return [future.result(timeout=30) for future in futures]

    def test_assignment_and_disable_cannot_leave_disabled_profile_attached(self):
        key_id, bot_id = self.key_ids[0], self.bot_ids[0]
        results = self.race(lambda db: assign_platform_key(key_id, bot_id, self.user, db),
                            lambda db: keys.admin_disable_key(db, key_id, self.user.id))
        self.assertIn(results[0], (200, 400)); self.assertEqual(results[1], 200)
        with self.sessions() as db:
            self.assertEqual(db.get(PlatformApiKey, key_id).status, "disabled")
            self.assertIsNone(db.get(Bot, bot_id).platform_credential_id)
            self.assertIsNone(db.get(PlatformApiKey, key_id).allocated_to_bot_id)

    def test_assignment_and_deletion_never_leave_dangling_reference(self):
        key_id, bot_id = self.key_ids[0], self.bot_ids[0]
        results = self.race(lambda db: assign_platform_key(key_id, bot_id, self.user, db),
                            lambda db: keys.admin_delete_key(db, key_id, self.user.id))
        self.assertIn(results, ([200, 400], [404, 200]))
        with self.sessions() as db:
            key, bot = db.get(PlatformApiKey, key_id), db.get(Bot, bot_id)
            self.assertEqual(bot.platform_credential_id, key_id if key else None)

    def test_two_bots_cannot_claim_one_profile(self):
        key_id = self.key_ids[0]
        results = self.race(lambda db: assign_platform_key(key_id, self.bot_ids[0], self.user, db),
                            lambda db: assign_platform_key(key_id, self.bot_ids[1], self.user, db))
        self.assertEqual(sorted(results), [200, 409])
        with self.sessions() as db:
            self.assertEqual(db.query(Bot).filter(Bot.platform_credential_id == key_id).count(), 1)

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
