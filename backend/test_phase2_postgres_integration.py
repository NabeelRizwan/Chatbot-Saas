"""Real PostgreSQL cases: only invoked by the owned-container runner."""
from types import SimpleNamespace
import unittest

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from services.postgres_fts import fts_candidates
from scripts.phase2_disposable_postgres import deterministic_vector, migrate, migration_module

ENGINE = None  # Deliberately no environment/DSN fallback.


class PostgreSQLAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ENGINE is None:
            raise RuntimeError('Use scripts/test_phase2_postgres.py; an owned disposable DB is required')
        cls.sessions = sessionmaker(bind=ENGINE)
        cls.profile = SimpleNamespace(provider='fixture', model='fixture', version=1)

    def recall(self, query, ids=None, bot=1, org=1, limit=48):
        return fts_candidates(self.sessions, query, bot, org, ids, self.profile, limit)

    def ids(self, query, **kwargs):
        return [c.chunk_id for c in self.recall(query, **kwargs).candidates]

    def test_01_expression_and_index_are_valid(self):
        with ENGINE.connect() as conn:
            index = conn.execute(text("SELECT i.indisvalid, pg_get_indexdef(i.indexrelid) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname=:name"),
                                 dict(name=migration_module().INDEX_NAME)).one()
        self.assertTrue(index[0])
        self.assertIn('USING gin', index[1])
        self.assertIn('to_tsvector', index[1])

    def test_02_existing_rows_searchable(self):
        self.assertIn(1, self.ids('silver package'))

    def test_03_insert_is_searchable(self):
        with ENGINE.begin() as conn:
            conn.execute(text("INSERT INTO chunks (id,document_id,bot_id,organization_id,content,embedding) VALUES (800,1,1,1,'insertbeacon',CAST(:vec AS vector))"), dict(vec=deterministic_vector()))
        self.assertEqual(self.ids('insertbeacon'), [800])

    def test_04_update_is_searchable(self):
        with ENGINE.begin() as conn:
            conn.execute(text("INSERT INTO chunks (id,document_id,bot_id,organization_id,content,embedding) VALUES (801,1,1,1,'oldbeacon',CAST(:vec AS vector))"), dict(vec=deterministic_vector()))
            conn.exec_driver_sql("UPDATE chunks SET content='updatedbeacon' WHERE id=801")
        self.assertEqual(self.ids('updatedbeacon'), [801])
        self.assertEqual(self.ids('oldbeacon'), [])

    def test_05_downgrade_preserves_rows_and_reupgrade(self):
        with ENGINE.connect() as conn:
            before = conn.exec_driver_sql("SELECT id,content,embedding::text FROM chunks ORDER BY id").all()
        migrate(ENGINE, 'downgrade')
        with ENGINE.connect() as conn:
            self.assertIsNone(conn.execute(text('SELECT to_regclass(:name)'), dict(name=migration_module().INDEX_NAME)).scalar())
            self.assertEqual(before, conn.exec_driver_sql("SELECT id,content,embedding::text FROM chunks ORDER BY id").all())
        migrate(ENGINE)
        self.assertIn(1, self.ids('silver'))

    def test_06_names_do_not_collide(self):
        self.assertLessEqual(len(migration_module().INDEX_NAME), 63)
        with ENGINE.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM pg_class WHERE relname=:name'), dict(name=migration_module().INDEX_NAME)).scalar(), 1)

    def test_07_morphology(self):
        self.assertIn(1, self.ids('price', ids=[1]))
        self.assertIn(1, self.ids('prices', ids=[1]))

    def test_08_phrase(self):
        self.assertIn(1, self.ids('"Silver Package"'))
        self.assertNotIn(1, self.ids('"Package Silver"'))

    def test_09_or(self):
        self.assertIn(1, self.ids('silver OR nonexistentlexeme'))

    def test_10_negation(self):
        self.assertEqual(self.ids('silver -phone'), [])
        self.assertIn(1, self.ids('silver -gummy'))

    def test_11_empty_stopwords_and_negative_only(self):
        for query in ('', 'the and of', '-phone'):
            result = self.recall(query)
            self.assertEqual(result.candidates, ())
            self.assertIn(result.query_status, {'empty', 'non_indexable'})

    def test_12_commercial_numeric_tokens(self):
        for query in ('33', 'COA', 'EPA', 'SKU-123', '60-day'):
            with self.subTest(query=query):
                self.assertIn(1, self.ids(query))

    def test_13_injection_does_not_execute(self):
        self.recall("silver'); DROP TABLE chunks; --")
        with ENGINE.connect() as conn:
            self.assertGreater(conn.exec_driver_sql('SELECT count(*) FROM chunks').scalar(), 150)

    def test_14_sql_ranks_late_row_before_limit(self):
        self.assertEqual(self.ids('pricing target', ids=[1], limit=1), [500])

    def test_15_title_not_broadcast_to_every_chunk(self):
        self.assertEqual(self.ids('brochure'), [])

    def test_16_foreign_org(self):
        self.assertNotIn(3, self.ids('needle'))

    def test_17_foreign_bot(self):
        self.assertNotIn(4, self.ids('needle'))

    def test_18_processing_document_and_chunk(self):
        self.assertTrue({5, 11}.isdisjoint(self.ids('needle')))

    def test_19_crawl_version_and_active(self):
        ids = self.ids('needle')
        self.assertIn(7, ids)
        self.assertTrue({8, 9}.isdisjoint(ids))

    def test_20_deleted_error(self):
        self.assertTrue({6, 10}.isdisjoint(self.ids('needle')))

    def test_21_document_scope(self):
        self.assertEqual(self.ids('needle', ids=[2]), [2])
        self.assertEqual(self.ids('needle', ids=[]), [])

    def test_22_profile(self):
        self.assertNotIn(12, self.ids('needle'))

    def test_23_null_org(self):
        self.assertEqual(self.ids('needle', org=None), [])

    def test_24_no_score_gate_and_stable_ranks(self):
        a, b = self.recall('needle'), self.recall('needle')
        self.assertEqual(a, b)
        self.assertEqual([c.rank for c in a.candidates], list(range(1, len(a.candidates)+1)))
        self.assertTrue(all(c.raw_score >= 0 for c in a.candidates))
