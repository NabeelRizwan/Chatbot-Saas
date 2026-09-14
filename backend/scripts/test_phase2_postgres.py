"""Run only against owned Docker/explicit disposable remote objects; exit 2 is BLOCKED.

No application database fallback. No providers or embeddings called.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase2_disposable_postgres import DisposableUnavailable, disposable_postgres, create_schema, seed_acceptance, migrate
from scripts.phase2_disposable_postgres import application_import_boundary, acceptance_test_result


def main():
    try:
        with disposable_postgres() as engine, application_import_boundary(engine):
            from database import connection
            import test_phase2_postgres_integration as tests
            with patch.object(connection.engine, 'connect', side_effect=AssertionError('Configured database forbidden')), \
                 patch('httpx.Client.send', side_effect=AssertionError('Live HTTP forbidden')), \
                 patch('httpx.AsyncClient.send', side_effect=AssertionError('Live HTTP forbidden')):
                create_schema(engine)
                seed_acceptance(engine)  # Existing rows precede migration.
                migrate(engine)
                tests.ENGINE = engine
                # Pure RRF/config and application boundary cases are run too;
                # they remain explicitly separate from real PostgreSQL tests.
                names = ['test_phase2_postgres_integration', 'test_phase2_hybrid_retrieval']
                result = unittest.TextTestRunner(verbosity=2, resultclass=acceptance_test_result()).run(
                    unittest.defaultTestLoader.loadTestsFromNames(names))
                return 0 if result.wasSuccessful() else 1
    except DisposableUnavailable as exc:
        print('PostgreSQL integration BLOCKED: ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
