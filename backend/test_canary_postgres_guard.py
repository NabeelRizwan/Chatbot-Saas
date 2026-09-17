"""Offline authorization/redaction tests; never opens a PostgreSQL connection."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

from scripts.canary_postgres_validation import settings, safe_failure, DisposableCanary, NAMESPACE
from services.canary_contracts import CanaryError
from services.structural_chunking import digest


def approved_env():
    return dict(CANARY_DATABASE_URL='postgresql://fixture:fixture@example.invalid:5432/disposable',
        CANARY_TARGET_FINGERPRINT=digest({'host': 'example.invalid', 'port': 5432, 'database': 'disposable'}),
        CANARY_ENVIRONMENT='disposable_test', CANARY_APPROVAL_REFERENCE='offline-guard-test')


class Guard(unittest.TestCase):
    def test_explicit_authorization(self):
        with patch('scripts.canary_postgres_validation.create_engine', side_effect=AssertionError('no connection')):
            value = settings(approved_env())
        self.assertTrue(NAMESPACE.fullmatch(value.namespace))
        self.assertEqual(value.approval.ownership_marker, value.namespace)
        self.assertEqual(value.approval.environment, 'disposable_test')

    def test_namespace_unique(self):
        self.assertNotEqual(settings(approved_env()).namespace, settings(approved_env()).namespace)

    def test_default_database_never_used(self):
        with self.assertRaisesRegex(CanaryError, 'HOLD_EXPLICIT_CANARY_TARGET_REQUIRED'):
            settings({'DATABASE_URL': approved_env()['CANARY_DATABASE_URL']})

    def test_missing_target_hold_not_skip(self):
        with self.assertRaisesRegex(CanaryError, '^HOLD_'):
            settings({})

    def test_no_credential_repr(self):
        self.assertNotIn('fixture', repr(settings(approved_env())))

    def test_raw_exception_suppressed(self):
        error = RuntimeError('sensitive URL and password that must not be emitted')
        self.assertNotIn('sensitive', str(safe_failure(error)))

    def test_only_fixed_guard_emitted(self):
        self.assertEqual(safe_failure(CanaryError('CANARY_OWNERSHIP_REFUSED'))['guard'], 'CANARY_OWNERSHIP_REFUSED')
        self.assertNotIn('guard', safe_failure(CanaryError('unsafe host:password')))

    def test_secret_clear(self):
        env = approved_env()
        with patch.dict('os.environ', env):
            c = DisposableCanary(settings(env))
            c.close()
            import os
            self.assertNotIn('CANARY_DATABASE_URL', os.environ)
            self.assertIsNone(c.config.url)

    def test_guard_no_application_imports(self):
        source = Path('scripts/canary_postgres_validation.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        forbidden = {'connection', 'models', 'dotenv', 'embedding_service', 'rag_service'}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(set((node.module or '').split('.')) & forbidden)
        self.assertNotIn('load_dotenv', source)

    def test_missing_vector_stops_without_mutation(self):
        engine = MagicMock()
        conn = engine.begin.return_value.__enter__.return_value
        version = MagicMock()
        version.one.return_value = ('PostgreSQL 18.6 fixture', '180006', 'UTF8', 'UTC', 'public', 'public')
        extension = MagicMock()
        extension.one_or_none.return_value = None
        available = MagicMock()
        available.scalar_one_or_none.return_value = '0.8.6'
        conn.execute.side_effect = [MagicMock(), version, extension, available]
        db = DisposableCanary(settings(approved_env()))
        with patch('scripts.canary_postgres_validation.create_engine', return_value=engine):
            with self.assertRaisesRegex(CanaryError, '^PGVECTOR_EXTENSION_REQUIRED$'):
                db.open()
        statements = [str(call.args[0]) for call in conn.execute.call_args_list]
        self.assertTrue(all(q.lstrip().startswith(('SELECT', 'SET TRANSACTION READ ONLY')) for q in statements))
        self.assertFalse(db.created)
        self.assertEqual(db.cleanup(), {'owned_schema_created': False})
        self.assertFalse(db.facts['vector_installed'])
        self.assertEqual(db.facts['server_version_num'], 180006)
        db.close()

    def test_schema_name_validation_before_sql(self):
        db = DisposableCanary(settings(approved_env()))
        db.config.namespace = 'public'
        db.engine = MagicMock()
        with self.assertRaisesRegex(CanaryError, 'CANARY_NAMESPACE_REFUSED'):
            db.bootstrap()
        db.engine.begin.assert_not_called()

    def test_hold_is_not_integration_pass(self):
        import contextlib
        import io
        import json
        from test_canary_stage_a_postgres import main
        output = io.StringIO()
        with patch.dict('os.environ', {}, clear=True), contextlib.redirect_stdout(output):
            self.assertNotEqual(main(), 0)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(records[0]['status'], 'HOLD')
        self.assertFalse(records[-1]['summary']['complete_acceptance'])


def refusal(field, value):
    def test(self):
        env = approved_env()
        if value is None:
            env.pop(field)
        else:
            env[field] = value
        with self.assertRaises(CanaryError):
            settings(env)
    return test


for name, field, value in (
    ('missing_allowlist', 'CANARY_TARGET_FINGERPRINT', None),
    ('wrong_allowlist', 'CANARY_TARGET_FINGERPRINT', '0' * 64),
    ('missing_approval', 'CANARY_APPROVAL_REFERENCE', None),
    ('blank_approval', 'CANARY_APPROVAL_REFERENCE', ''),
    ('missing_environment', 'CANARY_ENVIRONMENT', None),
    ('prod', 'CANARY_ENVIRONMENT', 'prod'),
    ('production', 'CANARY_ENVIRONMENT', 'production'),
    ('unknown', 'CANARY_ENVIRONMENT', 'unknown'),
    ('sqlite', 'CANARY_DATABASE_URL', 'sqlite:///:memory:'),
    ('wrong_host', 'CANARY_DATABASE_URL', 'postgresql://fixture:fixture@other.invalid:5432/disposable'),
    ('wrong_database', 'CANARY_DATABASE_URL', 'postgresql://fixture:fixture@example.invalid:5432/production'),
    ('no_port', 'CANARY_DATABASE_URL', 'postgresql://fixture:fixture@example.invalid/disposable'),
    ('dsn_override', 'CANARY_DATABASE_URL', 'postgresql://fixture:fixture@example.invalid:5432/disposable?host=other.invalid'),
    ('service_override', 'CANARY_DATABASE_URL', 'postgresql://fixture:fixture@example.invalid:5432/disposable?service=production'),
    ('options_override', 'CANARY_DATABASE_URL', 'postgresql://fixture:fixture@example.invalid:5432/disposable?options=anything'),
):
    setattr(Guard, 'test_refuse_' + name, refusal(field, value))


if __name__ == '__main__':
    unittest.main()
