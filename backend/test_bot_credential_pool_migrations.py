"""Actual Alembic/PostgreSQL upgrades in guarded disposable schemas only."""
import re
import unittest
import uuid
from unittest.mock import patch

from alembic import command
from sqlalchemy import create_engine, inspect, text

from database.connection import Base, engine as configured_engine
from services.migration_service import alembic_config, migration_state, upgrade_to_head


class BotCredentialPoolMigrationTests(unittest.TestCase):
    def setUp(self):
        self.schema = "credential_migration_test_" + uuid.uuid4().hex
        with configured_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.url = configured_engine.url.set(query={"options": f"-c search_path={self.schema},public,extensions"}).render_as_string(hide_password=False)
        self.engine = create_engine(self.url, hide_parameters=True)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT current_schema()")).scalar(), self.schema)

    def tearDown(self):
        self.engine.dispose()
        assert re.fullmatch(r"credential_migration_test_[0-9a-f]{32}", self.schema)
        with configured_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    def upgrade(self):
        upgrade_to_head(self.url, self.schema)

    def old_schema(self, with_capacity=False):
        # Minimal pre-release tables let us test the real additive migration,
        # not simulate it by creating current model metadata with a capacity.
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE platform_api_keys (id INTEGER PRIMARY KEY, provider VARCHAR NOT NULL, "
                              "encrypted_key BYTEA NOT NULL, status VARCHAR NOT NULL, allocated_to_bot_id INTEGER UNIQUE)"))
            conn.execute(text("CREATE TABLE bots (id INTEGER PRIMARY KEY, provider VARCHAR NOT NULL, provider_api_key TEXT, "
                              "platform_credential_id INTEGER REFERENCES platform_api_keys(id))"))
            conn.execute(text("ALTER TABLE platform_api_keys ADD FOREIGN KEY (allocated_to_bot_id) REFERENCES bots(id)"))
            if with_capacity:
                conn.execute(text("ALTER TABLE platform_api_keys ADD COLUMN max_bot_assignments INTEGER NOT NULL DEFAULT 2"))
        command.stamp(alembic_config(self.url, self.schema), "20260902_02")

    def state(self):
        with self.engine.connect() as conn:
            return migration_state(conn, self.schema)

    def snapshot(self):
        with self.engine.connect() as conn:
            return (conn.execute(text("SELECT id,provider,encrypted_key,status,allocated_to_bot_id FROM platform_api_keys ORDER BY id")).all(),
                    conn.execute(text("SELECT * FROM bots ORDER BY id")).all())

    def test_fresh_full_schema_and_idempotent_upgrade(self):
        original_create = Base.metadata.create_all

        def isolated_create(bind):
            self.assertEqual(bind.execute(text("SELECT current_schema()")).scalar(), self.schema)
            # Public tables must not satisfy baseline checkfirst and cause raw
            # migration SQL to resolve to the customer schema. Fresh DB equivalent.
            original_create(bind, checkfirst=False)

        with patch.object(Base.metadata, "create_all", side_effect=isolated_create):
            self.upgrade()
        self.assertTrue(set(Base.metadata.tables) <= set(inspect(self.engine).get_table_names(schema=self.schema)))
        self.assertIn("max_bot_assignments", {c["name"] for c in inspect(self.engine).get_columns("platform_api_keys", schema=self.schema)})
        self.assertEqual(self.state(), ("20260903_01", "20260903_01"))
        self.upgrade()
        self.assertEqual(self.state(), ("20260903_01", "20260903_01"))

    def test_existing_multi_provider_legacy_assignments_and_ciphertext_preserved(self):
        self.old_schema()
        with self.engine.begin() as conn:
            for i, provider in enumerate(("gemini", "openai", "claude", "grok"), 1):
                conn.execute(text("INSERT INTO platform_api_keys VALUES (:id,:provider,:secret,'assigned',NULL)"),
                             {"id": i, "provider": provider, "secret": b"synthetic-encrypted-bytes-unchanged"})
                conn.execute(text("INSERT INTO bots VALUES (:id,:provider,NULL,NULL)"), {"id": i, "provider": provider})
                conn.execute(text("UPDATE platform_api_keys SET allocated_to_bot_id=:id WHERE id=:id"), {"id": i})
        before = self.snapshot()
        self.upgrade()
        after = self.snapshot()
        self.assertEqual(before[0], after[0])  # Includes encrypted bytes and historical reverse links.
        self.assertEqual([row.platform_credential_id for row in after[1]], [1, 2, 3, 4])
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT max_bot_assignments FROM platform_api_keys ORDER BY id")).scalars().all(), [2, 2, 2, 2])
        self.upgrade()
        self.assertEqual(after, self.snapshot())

    def test_existing_many_references_capacity_and_disabled_state_preserved(self):
        self.old_schema(with_capacity=True)
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO platform_api_keys VALUES (1,'gemini',:secret,'disabled',NULL,2), (2,'openai',:secret,'available',NULL,9)"), {"secret": b"synthetic-ciphertext"})
            conn.execute(text("INSERT INTO bots VALUES (1,'gemini',NULL,1),(2,'gemini',NULL,1),(3,'gemini',NULL,1)"))
        before = self.snapshot()
        self.upgrade()
        self.assertEqual(before, self.snapshot())
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT max_bot_assignments FROM platform_api_keys ORDER BY id")).scalars().all(), [3, 9])
        self.upgrade()
        self.assertEqual(before, self.snapshot())

    def test_legacy_invalid_candidates_not_assigned_and_canonical_wins(self):
        self.old_schema()
        with self.engine.begin() as conn:
            for i in range(1, 5):
                conn.execute(text("INSERT INTO platform_api_keys VALUES (:id,'gemini',:secret,'available',NULL)"), {"id": i, "secret": b"synthetic-ciphertext"})
            conn.execute(text("INSERT INTO bots VALUES (1,'gemini','synthetic-BYOK',NULL),(2,'openai',NULL,NULL),(3,'gemini',NULL,4)"))
            conn.execute(text("UPDATE platform_api_keys SET allocated_to_bot_id=id WHERE id<=3"))
        self.upgrade()
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT platform_credential_id FROM bots ORDER BY id")).scalars().all(), [None, None, 4])
            self.assertEqual(conn.execute(text("SELECT provider_api_key FROM bots WHERE id=1")).scalar(), "synthetic-BYOK")

    def test_invalid_canonical_assignment_fails_atomically_without_data_loss(self):
        self.old_schema()
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO platform_api_keys VALUES (1,'gemini',:secret,'assigned',NULL)"), {"secret": b"synthetic-encrypted-bytes"})
            conn.execute(text("INSERT INTO bots VALUES (1,'openai',NULL,1)"))
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, "administrator review"):
            self.upgrade()
        self.assertEqual(self.state()[0], "20260902_02")
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("max_bot_assignments", {c["name"] for c in inspect(self.engine).get_columns("platform_api_keys", schema=self.schema)})


if __name__ == "__main__":
    unittest.main()
