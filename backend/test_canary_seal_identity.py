"""Exact manifest/generation/epoch repository regressions; no network."""
import unittest
from sqlalchemy import select, update, delete
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects import postgresql
from database import canary_schema as s
from scripts.canary_stage_a import fixture_batch, make_manifest, hard_scope, offline_repository, NOW
from scripts.canary_seal_gold import cases, exercise
from services.canary_contracts import CanaryError, State
from services.canary_repository import CanaryRepository


class SealIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = fixture_batch('# Synthetic guide\n\nA source-backed statement.', document_id=601)

    def setUp(self):
        self.ctx = offline_repository()
        self.repo = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        pin = self.repo.register_fixture_source(self.batch, source_id=601)
        self.repo.conn.execute(update(s.lifecycle).values(epoch=10))
        self.manifest = make_manifest((pin,), run='seal-gold')
        self.repo.create(self.manifest, now=NOW)
        self.repo.stage(self.manifest, self.batch, now=NOW)

    def test_explicit_seal_required(self):
        with self.assertRaisesRegex(CanaryError, 'EXPLICIT_SEAL_IDENTITY_REQUIRED'):
            self.repo.transition(self.manifest, State.INDEX_READY, now=NOW)

    def test_snapshot_survives_repository_reopen(self):
        first = self.repo.build_identity(self.manifest)
        other = CanaryRepository(self.repo.conn, self.repo.approval, clock=lambda: NOW)
        self.assertEqual(first, other.build_identity(self.manifest))
        self.assertEqual(other._manifest(self.manifest)['build_snapshot'][0]['epoch'], 10)
        other.conn.execute(update(s.lifecycle).values(epoch=11))
        with self.assertRaisesRegex(CanaryError, 'STALE_SOURCE_EPOCH'):
            other.seal_generation(self.manifest, expected_build_identity=first, now=NOW)

    def test_epoch_cannot_reset(self):
        self.repo.conn.execute(update(s.lifecycle).values(epoch=11))
        for value in (10, 11, 0):
            with self.assertRaises(DBAPIError), self.repo.conn.begin_nested():
                self.repo.conn.execute(update(s.lifecycle).values(epoch=value))

    def test_epoch_cannot_delete_reinsert(self):
        with self.assertRaises(DBAPIError), self.repo.conn.begin_nested():
            self.repo.conn.execute(delete(s.lifecycle))

    def test_snapshot_tamper_refused(self):
        self.repo.conn.execute(update(s.manifests).values(build_snapshot=[]))
        with self.assertRaisesRegex(CanaryError, 'BUILD_IDENTITY_MISMATCH'):
            self.repo.build_identity(self.manifest)

    def test_wrong_explicit_identity_refused(self):
        with self.assertRaisesRegex(CanaryError, 'BUILD_IDENTITY_MISMATCH'):
            self.repo.seal_generation(self.manifest, expected_build_identity='f'*64, now=NOW)

    def test_read_epoch_aba_invalidates_release(self):
        token = self.repo.build_identity(self.manifest)
        self.repo.seal_generation(self.manifest, expected_build_identity=token, now=NOW)
        self.repo.transition(self.manifest, State.CANARY_READ, now=NOW)
        lease = self.repo.read_gate(self.manifest, hard_scope(self.manifest), now=NOW)
        self.repo.conn.execute(update(s.lifecycle).values(status='processing', epoch=11))
        self.repo.conn.execute(update(s.lifecycle).values(status='ready', epoch=12))
        with self.assertRaisesRegex(CanaryError, 'STALE_SOURCE_EPOCH'):
            self.repo.read_gate(self.manifest, hard_scope(self.manifest), now=NOW, expected_epoch=lease)

    def test_source_lock_sql(self):
        from unittest.mock import patch
        original = self.repo.conn.execute
        statements = []
        def capture(stmt, *args, **kwargs):
            statements.append(str(stmt.compile(dialect=postgresql.dialect())))
            return original(stmt, *args, **kwargs)
        with patch.object(self.repo.conn, 'execute', capture):
            self.repo.seal_generation(self.manifest, expected_build_identity=self.repo.build_identity(self.manifest), now=NOW)
        source = [q for q in statements if 'FROM canary_source_lifecycle' in q]
        self.assertEqual(len(source), 2)
        self.assertTrue(all('FOR SHARE' in q and 'ORDER BY' in q for q in source))

    def test_failed_publication_rolls_back_seal(self):
        from unittest.mock import patch
        original = self.repo._publish
        def failure(*args):
            original(*args)
            raise CanaryError('INJECTED_PUBLICATION_FAILURE')
        with patch.object(self.repo, '_publish', failure):
            with self.assertRaisesRegex(CanaryError, 'INJECTED_PUBLICATION_FAILURE'):
                self.repo.seal_generation(self.manifest, expected_build_identity=self.repo.build_identity(self.manifest), now=NOW)
        self.assertEqual(self.repo._manifest(self.manifest)['state'], 'EMBEDDING_STAGING')
        self.assertEqual(self.repo._run(self.manifest)['state'], 'EMBEDDING_STAGING')


for name, expected in cases():
    def test(self, name=name, expected=expected):
        result = exercise(self.repo, self.manifest, self.batch, name, expected, NOW)
        self.assertEqual(result['result'], 'REFUSED' if expected.startswith('REFUSE') else expected)
    setattr(SealIdentity, 'test_gold_' + name, test)


if __name__ == '__main__':
    unittest.main()
