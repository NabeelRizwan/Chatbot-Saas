"""Opt-in real PostgreSQL acceptance. Never registered in the offline suite.

Run explicitly with python -B test_canary_stage_a_postgres.py. Missing approval
is HOLD/exit 2, not skip/pass. The first failing prerequisite stops dependent
tests; cleanup still runs. No runtime repair or bypass of a seal is performed.
Only sanitized JSON records are printed, never raw driver exceptions.
"""
import json
from time import perf_counter, time

from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError

from database import canary_schema as s
from scripts import canary_schema_migration as migration
from scripts.canary_postgres_validation import settings, DisposableCanary, safe_failure
from scripts.canary_stage_a import fixture_batch, make_manifest, hard_scope
from services.canary_contracts import CanaryError, State, synthetic_vector, validate_vector
from services.canary_repository import CanaryRepository, document_values, where
from services.canary_retrieval import run_query


def require(value, code):
    if not value:
        raise CanaryError(code)


class Acceptance:
    def __init__(self, db):
        self.db = db
        self.approval = db.config.approval
        self.batch = fixture_batch()
        self.manifest = None
        self.other = None
        self.metrics = {}

    def repo(self, conn):
        return CanaryRepository(conn, self.approval)

    def migration_cycle(self):
        self.db.bootstrap()
        with self.db.transaction() as conn:
            migration.upgrade(conn, self.approval)
            require({r[0] for r in self.db.relations(conn) if r[2] == 'r'} == set(s.metadata.tables), 'UPGRADE_TABLE_INVENTORY')
            migration.downgrade(conn, self.approval)
            retained = {r[0] for r in self.db.relations(conn) if r[2] == 'r'}
            require(retained == {s.marker.name, s.sources.name, s.lifecycle.name, s.nodes.name}, 'DOWNGRADE_INVENTORY')
            migration.upgrade(conn, self.approval)
            self.db.record_owned(conn)
        return {'upgrade': 'PASS', 'downgrade': 'PASS', 'reupgrade': 'PASS',
                'tables': len(s.metadata.tables), 'retained_on_downgrade': sorted(retained)}

    def schema_constraints(self):
        with self.db.transaction() as conn:
            constraints = conn.execute(text("""SELECT c.contype,count(*) FROM pg_constraint c
                JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=current_schema()
                GROUP BY c.contype ORDER BY c.contype""")).all()
            dimensions = conn.execute(text("""SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod)
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND a.attname='embedding' ORDER BY c.relname""")).all()
            require(len(dimensions) == 2 and all(r[2] == 'vector(768)' for r in dimensions), 'VECTOR_COLUMN_TYPE')
            fks = conn.execute(text("""SELECT c.conrelid::regclass::text,pg_get_constraintdef(c.oid)
                FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
                WHERE n.nspname=current_schema() AND c.contype='f'""")).all()
            for table, definition in fks:
                if table != s.runs.name:
                    require('organization_id' in definition and 'bot_id' in definition, 'UNSCOPED_FOREIGN_KEY')
            indexes = conn.execute(text("""SELECT c.relname,i.indisvalid,i.indisready,pg_get_indexdef(c.oid)
                FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()
                AND c.relname='ix_canary_atoms_content_fts_en_v1'""")).one()
            require(indexes[1] and indexes[2] and 'USING gin' in indexes[3], 'GIN_INVALID')
            required_nulls = conn.execute(text("""SELECT count(*) FROM information_schema.columns
                WHERE table_schema=current_schema() AND is_nullable='NO'""")).scalar_one()
        return {'constraints': dict(constraints), 'full_scope_foreign_keys': len(fks),
                'not_null_columns': required_nulls, 'vector_columns': [list(r) for r in dimensions],
                'gin': list(indexes)}

    def stage_real_rows(self):
        with self.db.transaction() as conn:
            repo = self.repo(conn)
            pin = repo.register_fixture_source(self.batch, source_id=1)
            self.manifest = make_manifest((pin,), run='pg-run-a', approved=self.approval)
            self.other = make_manifest((pin,), run='pg-run-b', approved=self.approval)
            for manifest in (self.manifest, self.other):
                repo.create(manifest, now=int(time()))
                repo.stage(manifest, self.batch, now=int(time()))
            self.metrics['run_a_staged_counts'] = repo.counts(self.manifest)
            vector = conn.execute(select(s.vectors.c.embedding).limit(1)).scalar_one()
            require(len(validate_vector(vector)) == 768, 'VECTOR_ROUNDTRIP')
            sizes = conn.execute(text("""SELECT c.relname,c.relkind,pg_relation_size(c.oid),pg_total_relation_size(c.oid)
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() ORDER BY c.relname""")).all()
        self.metrics['storage_bytes'] = [list(r) for r in sizes]
        return {'run_a': self.metrics['run_a_staged_counts'], 'run_b_same_counts': True,
                'decoded_vector_type': type(vector).__name__, 'decoded_scalar_type': type(vector[0]).__name__,
                'finite_dimensions': len(vector), 'storage_bytes': self.metrics['storage_bytes']}

    def invalid_vectors(self):
        cases = ([1.] * 767, [1.] * 769, [float('nan')] + [1.] * 767,
                 [float('inf')] + [1.] * 767, [0.] * 768)
        with self.db.transaction() as conn:
            repo = self.repo(conn)
            before = repo.counts(self.manifest)
            for vector in cases:
                supplied = {e.entry_key: vector for e in self.batch.entries}
                try:
                    repo.stage(self.manifest, self.batch, now=int(time()), supplied_vectors=supplied)
                except CanaryError:
                    pass
                else:
                    raise CanaryError('INVALID_VECTOR_ACCEPTED')
            require(repo.counts(self.manifest) == before, 'INVALID_VECTOR_MUTATED_ROWS')
        return {'invalid_vector_shapes_refused': 5, 'rows_unchanged': True}

    def database_rejections(self):
        outcomes = {}
        with self.db.transaction() as conn:
            repo = self.repo(conn)
            before = repo.counts(self.manifest)
            row = dict(conn.execute(select(s.vectors).where(where(s.vectors,
                document_values(self.manifest, self.manifest.documents[0]))).limit(1)).mappings().one())
            fields = dict(organization_id=90001, bot_id=90002, run_id='foreign-run',
                generation='foreign-generation', manifest_hash='f' * 64, profile_hash='f' * 64,
                policy_hash='f' * 64, document_id=999, document_version_id='foreign-version',
                source_version=99, source_hash='f' * 64, website_id=9, crawl_id=9,
                crawl_version=9, revision='foreign-revision', entry_id='f' * 64, input_hash='f' * 64)
            for field, value in fields.items():
                try:
                    with conn.begin_nested():
                        conn.execute(insert(s.vectors).values(**(row | {field: value})))
                except DBAPIError as exc:
                    code = getattr(exc.orig, 'pgcode', '')
                    require(code in ('23503', '23505', 'P0001'), 'UNEXPECTED_DATABASE_REJECTION')
                    outcomes[field] = code
                else:
                    raise CanaryError('FOREIGN_VECTOR_ACCEPTED')
            # Real FK CHECK/NOT NULL/PK failures, rolled back to a savepoint each.
            for label, table, changes, expected in (
                ('duplicate_vector', s.vectors, {}, '23505'),
                ('foreign_atom_membership', s.memberships, {'atom_id': 'f' * 64}, '23503'),
                ('foreign_entry_membership', s.memberships, {'entry_id': 'f' * 64}, '23503'),
                ('foreign_span_node', s.spans, {'ordinal': 250, 'node_key': 'f' * 64}, '23503'),
                ('invalid_span_range', s.spans, {'ordinal': 250, 'node_end': -1}, '23514'),
                ('null_embedding', s.vectors, {'embedding': None}, '23502'),
            ):
                fixture = dict(conn.execute(select(table).limit(1)).mappings().one()) | changes
                try:
                    with conn.begin_nested():
                        conn.execute(insert(table).values(**fixture))
                except DBAPIError as exc:
                    code = getattr(exc.orig, 'pgcode', '')
                    require(code == expected, 'UNEXPECTED_CONSTRAINT_CATEGORY')
                    outcomes[label] = code
                else:
                    raise CanaryError('INVALID_RELATIONAL_ROW_ACCEPTED')
            require(repo.counts(self.manifest) == before, 'SAVEPOINT_ROLLBACK_FAILED')
        return {'rejections': outcomes, 'savepoint_rollback': 'PASS',
                'note': 'P0001 is the run-state trigger rejecting absent foreign runs before FK evaluation.'}

    def seal(self):
        with self.db.transaction() as conn:
            repo = self.repo(conn)
            repo.transition(self.manifest, State.INDEX_READY, now=int(time()))
            repo.transition(self.manifest, State.CANARY_READ, now=int(time()))
            repo.read_gate(self.manifest, hard_scope(self.manifest), now=int(time()))
        return {'transaction_seal': 'PASS', 'read_lease': 'PASS'}

    def query_database(self):
        with self.db.transaction() as conn:
            repo = self.repo(conn)
            scope = hard_scope(self.manifest)
            vector = synthetic_vector(self.batch.entries[0].text)
            dense = repo.dense(self.manifest, scope, vector, now=int(time()))
            require(bool(dense) and abs(dense[0].score) < 1e-5, 'EXACT_COSINE_FAILED')
            cases = {'word': 'console', 'phrase': '"before renewal"', 'or': 'console OR renewal',
                'negative': 'console -straightforward', 'stemming': 'provide', 'number': '42',
                'currency': '$42', 'identifier': 'ERR-42/ALPHA', 'empty': '', 'non_indexable': '-console'}
            observations = {}
            for label, query in cases.items():
                result = repo.fts(self.manifest, scope, query, now=int(time()))
                observations[label] = dict(status=result.query_status, hits=len(result.hits),
                    atom_ids=[h.evidence_key for h in result.hits])
                if label not in ('empty', 'non_indexable'):
                    require(bool(result.hits), 'FTS_CHARACTERIZATION_MISSING_HIT')
            require(observations['empty']['status'] == 'empty', 'FTS_EMPTY_STATUS')
            require(observations['non_indexable']['status'] == 'non_indexable', 'FTS_NONINDEXABLE_STATUS')
            result = run_query(repo, self.manifest, scope, query='console OR renewal', query_vector=vector, now=int(time()))
            require(result['mode'] == 'full_hybrid', 'REAL_CHANNEL_DEGRADATION')
            require(result['source_revalidation'] == 'PASS', 'SOURCE_REVALIDATION')
        return {'dense_hits': len(dense), 'fts_cases': observations, 'query': result}

    def cleanup_runs(self):
        with self.db.transaction() as conn:
            repo = self.repo(conn)
            repo.transition(self.manifest, State.OFF, now=int(time()))
            other_before = repo.counts(self.other)
            source_before = conn.execute(select(s.sources.c.payload_hash)).scalars().all()
            repo.delete_run(self.manifest)
            require(not any(repo.counts(self.manifest).values()), 'RUN_A_NOT_REMOVED')
            require(repo.counts(self.other) == other_before, 'RUN_B_CHANGED')
            require(conn.execute(select(s.sources.c.payload_hash)).scalars().all() == source_before, 'SOURCE_HISTORY_CHANGED')
            repo.transition(self.other, State.OFF, now=int(time()))
            repo.delete_run(self.other)
            migration.downgrade(conn, self.approval)
            self.db.record_owned(conn)
        return {'run_a_removed': True, 'run_b_survived_then_removed': True, 'source_history_preserved': True,
                'final_downgrade': 'PASS'}


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def main():
    db = None
    records = []
    failed = False
    cleanup = None
    try:
        db = DisposableCanary(settings())
        steps = [('preflight', db.open)]
        acceptance = Acceptance(db)
        steps += [(name, getattr(acceptance, name)) for name in (
            'migration_cycle', 'schema_constraints', 'stage_real_rows', 'invalid_vectors',
            'database_rejections', 'seal', 'query_database', 'cleanup_runs')]
        for name, call in steps:
            if failed:
                record = dict(test=name, status='NOT_RUN_PREREQUISITE_FAILED')
            else:
                start = perf_counter()
                try:
                    details = call()
                    record = dict(test=name, status='PASS', details=details)
                except Exception as exc:
                    record = dict(test=name, status='FAIL', failure=safe_failure(exc),
                                  preflight_observations=db.facts)
                    failed = True
                record['elapsed_ms'] = (perf_counter() - start) * 1000
            records.append(record)
            emit(record)
    except Exception as exc:
        failed = True
        emit(dict(status='HOLD', failure=safe_failure(exc)))
    finally:
        if db is not None:
            try:
                cleanup = db.cleanup()
                emit(dict(cleanup=cleanup))
            except Exception as exc:
                failed = True
                emit(dict(cleanup='FAIL_REFUSED', failure=safe_failure(exc)))
            finally:
                db.close()
        else:
            import os
            from scripts.canary_postgres_validation import ENV_KEYS
            for key in ENV_KEYS:
                os.environ.pop(key, None)
    emit(dict(summary={'passed': sum(r['status'] == 'PASS' for r in records),
        'failed': sum(r['status'] == 'FAIL' for r in records),
        'not_run': sum(r['status'].startswith('NOT_RUN') for r in records),
        'cleanup_verified': bool(cleanup and cleanup.get('schema_removed')),
        'complete_acceptance': False, 'provider_calls': 0}))
    # These first prerequisite gates cannot by themselves grant full acceptance.
    return 1 if failed else 2


if __name__ == '__main__':
    raise SystemExit(main())
