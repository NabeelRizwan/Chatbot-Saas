"""Bounded, read-only payload-sequence diagnosis; never executes a measured lane."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import statistics
from threading import Event
from time import monotonic, time
import uuid

from sqlalchemy import Text, cast, func, select, text

from database import canary_schema as s
from services.canary_contracts import Lane
from services.canary_repository import document_values, where
from services.structural_chunking import digest
from scripts.canary_bounded_output import emit
from scripts.canary_evaluation_resume import EvaluationRunner, EvaluationRepository, require, read_bounded
from scripts.canary_evaluation_transport import safe_error
from scripts.canary_exact_atom_diagnostic import atom_statement, explain, observer_sample, row_facts, utc


def metadata_statement(scope):
    return atom_statement(scope, [c for c in s.atoms.c if c.name != 'payload'])


def payload_statement(scope, metadata):
    require(set(metadata) == {c.name for c in s.atoms.c if c.name != 'payload'},
            'COMPLETE_ATOM_METADATA_REQUIRED')
    require(all(metadata[k] == v for k, v in scope.items()), 'METADATA_SCOPE_MISMATCH')
    return atom_statement(scope, [s.atoms.c.payload]).where(
        where(s.atoms, {k: v for k, v in metadata.items() if k not in scope}))


def reconstruct(metadata, value, expected_hash):
    row = dict(metadata, payload=value)
    facts = row_facts(row)
    require(expected_hash is not None and facts['canonical_row_hash'] == expected_hash,
            'EXACT_PREFLIGHT_ROW_MISMATCH')
    return facts


def connection_facts(conn):
    row = conn.execute(text('''SELECT pid,backend_start,xact_start,
        extract(epoch FROM clock_timestamp()-backend_start)*1000 AS connection_age_ms,
        extract(epoch FROM clock_timestamp()-xact_start)*1000 AS transaction_age_ms
        FROM pg_stat_activity WHERE pid=pg_backend_pid()''')).mappings().one()
    return {k: v.isoformat() if isinstance(v, datetime) else float(v) if k.endswith('_ms')
            and v is not None else v for k, v in row.items()}


class PayloadSequenceDiagnostic(EvaluationRunner):
    def __init__(self, *args, failure_artifact, repetitions=3, **kwargs):
        super().__init__(*args, **kwargs)
        require(type(repetitions) is int and 3 <= repetitions <= 5, 'DIAGNOSTIC_REPETITION_BOUND')
        require('/' not in failure_artifact and '\\' not in failure_artifact, 'FAILURE_ARTIFACT_NAME_REQUIRED')
        self.failed_record = read_bounded(self.folder/failure_artifact)
        r = self.failed_record
        require(r['phase'] == 'AFTER_CALL' and r['lane'] == 'STRUCTURAL_CANARY'
                and r['result_category'] == 'DATABASE_TIMEOUT' and r['statement_started']
                and r['transport_part'] == 2 and 1 <= r['case_id'] <= 90,
                'EXACT_FAILED_PAYLOAD_REQUIRED')
        self.scope, self.case = r['source_scope'], r['case_id']
        atom_statement(self.scope)
        self.repetitions = repetitions
        self.expected_rows, self.target_metadata, self.diagnostics = {}, None, []

    def validated_document(self, mf, pin, proof):
        data, checksum = super().validated_document(mf, pin, proof)
        if mf.lane == Lane.STRUCTURAL_CANARY:
            for row in data[s.atoms.name]:
                scope = {k: row[k] for k in (*s.DOC, 'atom_id')}
                self.expected_rows[digest(scope)] = digest(row)
                if scope == self.scope:
                    self.target_metadata = {k: v for k, v in row.items() if k != 'payload'}
        return data, checksum

    def authorize(self, repo, scope):
        repo.read_gate(self.mf, self.hard, now=int(time()))
        pin = next((p for p in self.mf.documents
                    if document_values(self.mf, p) == {k: scope[k] for k in s.DOC}), None)
        require(pin is not None and scope['atom_id'] in pin.atoms
                and scope['document_id'] in self.mf.effective(self.hard), 'EXACT_DIAGNOSTIC_SCOPE_REFUSED')

    @contextmanager
    def fresh_repository(self, scope):
        # NullPool ensures a new physical connection; never the ownership connection.
        with self.db.transaction() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            repo = EvaluationRepository(conn, self.approval, authorization=self.authorization,
                lease_until=self.retained_until, identities=[m.canonical_hash() for m in self.manifests])
            self.authorize(repo, scope)
            yield repo

    def record(self, name, work):
        result = dict(name=name, started=utc(), source_scope=self.scope,
                      scope_digest=self.failed_record['scope_digest'])
        started = monotonic()
        try:
            with self.exclusive():
                self.identity_gate()
                work(result)
            result['result'] = result.get('part2', {}).get('result', 'PASS')
        except Exception as exc:
            result.update(result='FAIL', failure=safe_error(exc))
        result.update(elapsed_ms=(monotonic()-started)*1000, ended=utc(), provider_calls=0)
        self.diagnostics.append(result)
        self.save(f'payload-diagnostic-{self.session}-{name}', result, immutable=True)
        emit(dict(stage='PAYLOAD_DIAGNOSTIC', **result))
        return result

    def metadata(self, conn, result, scope):
        part = result['part1'] = dict(connection_token=conn.info.setdefault('payload_diagnostic_token', uuid.uuid4().hex),
                                     **connection_facts(conn))
        started = monotonic()
        try:
            metadata = dict(conn.execute(metadata_statement(scope)).mappings().one())
            part.update(result='PASS', metadata_hash=digest(metadata))
            return metadata
        except Exception as exc:
            part.update(result='FAIL', failure=safe_error(exc))
            raise
        finally:
            part['elapsed_ms'] = (monotonic()-started)*1000

    def payload(self, conn, metadata, result, scope, *, observe=False):
        stmt = payload_statement(scope, metadata)
        shape = sha256(str(stmt.compile(dialect=conn.dialect)).encode()).hexdigest()
        require(shape == self.failed_record['query_shape_sha256'], 'EXACT_PAYLOAD_SHAPE_CHANGED')
        part = result['part2'] = dict(connection_token=conn.info.setdefault('payload_diagnostic_token', uuid.uuid4().hex),
            query_shape_sha256=shape, **connection_facts(conn))
        finished, started_event = Event(), Event()
        def fetch():
            started = monotonic()
            part['client_start'] = utc()
            started_event.set()
            try:
                value = conn.execute(stmt).scalar_one()
                part.update(result='PASS', **reconstruct(metadata, value, self.expected_rows.get(digest(scope))))
            except Exception as exc:
                part.update(result='FAIL', failure=safe_error(exc))
            finally:
                part.update(elapsed_ms=(monotonic()-started)*1000, client_end=utc())
                finished.set()
        if not observe:
            fetch()
            return
        result['observer_samples'] = []
        with self.db.engine.connect() as observer, ThreadPoolExecutor(max_workers=1) as pool:
            result['observer_pid'] = observer.execute(text('SELECT pg_backend_pid()')).scalar_one()
            observer.rollback()
            future = pool.submit(fetch)
            if started_event.wait(35):
                for _ in range(20):
                    try:
                        result['observer_samples'].append(observer_sample(observer, part['pid']))
                    except Exception as exc:
                        result['observer_error'] = safe_error(exc)
                        break
                    if finished.wait(1):
                        break
            future.result(timeout=35)

    def sequence(self, pattern, result, *, observe=False):
        require(pattern in ('A', 'B', 'C'), 'UNKNOWN_DIAGNOSTIC_PATTERN')
        result['pattern'] = pattern
        if pattern == 'A':
            with self.fresh_repository(self.scope) as repo:
                metadata = self.metadata(repo.conn, result, self.scope)
                self.payload(repo.conn, metadata, result, self.scope, observe=observe)
        elif pattern == 'B':
            with self.fresh_repository(self.scope) as repo:
                metadata = self.metadata(repo.conn, result, self.scope)
            with self.fresh_repository(self.scope) as repo:
                self.payload(repo.conn, metadata, result, self.scope)
                require(result['part1']['pid'] != result['part2']['pid'], 'FRESH_PAYLOAD_CONNECTION_REQUIRED')
        else:
            require(self.target_metadata is not None, 'PREFLIGHT_METADATA_REQUIRED')
            with self.fresh_repository(self.scope) as repo:
                self.payload(repo.conn, self.target_metadata, result, self.scope)

    def evaluate(self):
        self.mf = next(m for m in self.manifests if m.lane == Lane.STRUCTURAL_CANARY)
        _, self.hard = next(v for v in self.common if v[0]['id'] == self.case)
        require(self.failed_record['scope_digest'] == digest(dict(source=self.scope, hard=self.hard.identity()))
                and self.target_metadata is not None and int(time()) < self.retained_until,
                'EXACT_DIAGNOSTIC_IDENTITY_REQUIRED')
        self.record('B1_SPLIT_OBSERVED', lambda r: self.sequence('A', r, observe=True))
        self.record('B2_PAYLOAD_FRESH', lambda r: self.sequence('C', r))
        for pattern in ('A', 'B', 'C'):
            for index in range(self.repetitions):
                self.record(f'B3_{pattern}_{index+1}', lambda r, p=pattern: self.sequence(p, r))
        def plan(result):
            with self.fresh_repository(self.scope) as repo:
                result['plan'] = explain(repo.conn, payload_statement(self.scope, self.target_metadata))
        self.record('B5_PLAN', plan)
        peers = []
        def peer_ids(result):
            with self.fresh_repository(self.scope) as repo:
                for before in (True, False):
                    predicate = s.atoms.c.atom_id < self.scope['atom_id'] if before else s.atoms.c.atom_id > self.scope['atom_id']
                    order = s.atoms.c.atom_id.desc() if before else s.atoms.c.atom_id.asc()
                    peers.extend(repo.conn.execute(select(s.atoms.c.atom_id).where(
                        where(s.atoms, {k:self.scope[k] for k in s.DOC}), predicate).order_by(order).limit(2)).scalars())
                result.update(peer_atoms=peers, peer_order='IMMUTABLE_ATOM_ID_LEXICOGRAPHIC')
        self.record('B6_PEER_IDS', peer_ids)
        for index, key in enumerate([self.scope['atom_id'], *peers]):
            def sizes(result, key=key):
                scope = dict(self.scope, atom_id=key)
                with self.fresh_repository(scope) as repo:
                    cols = [func.pg_column_size(s.atoms.c.payload).label('payload_stored_bytes'),
                        func.octet_length(cast(s.atoms.c.payload, Text)).label('payload_json_bytes'),
                        func.octet_length(s.atoms.c.canonical_text).label('text_utf8_bytes')]
                    result.update(atom_id=key, sizes=dict(repo.conn.execute(atom_statement(scope, cols)).mappings().one()))
                    started = monotonic()
                    row = repo.conn.execute(atom_statement(scope)).mappings().one()
                    require(digest(dict(row)) == self.expected_rows[digest(scope)], 'PEER_ROW_IDENTITY_CHANGED')
                    result.update(read_ms=(monotonic()-started)*1000, **row_facts(row))
            self.record(f'B6_SIZE_ROW_{index}', sizes)
        summary = {}
        for pattern in ('A', 'B', 'C'):
            records = [r for r in self.diagnostics if r['name'].startswith('B3_'+pattern)]
            times = [r['part2']['elapsed_ms'] for r in records if 'part2' in r]
            summary[pattern] = dict(attempts=len(records), successes=sum(r['result']=='PASS' for r in records),
                failures=sum(r['result']!='PASS' for r in records), payload_p50_ms=statistics.median(times) if times else None)
        with self.exclusive():
            self.identity_gate()
        self.result.update(stage='PAYLOAD_DIAGNOSIS_COMPLETE', decision='C', diagnostic_only=True,
            measured_lanes_executed=0, diagnostic_summary=summary, unrelated_catalog_unchanged=True,
            diagnostic_records=[r['name'] for r in self.diagnostics])
