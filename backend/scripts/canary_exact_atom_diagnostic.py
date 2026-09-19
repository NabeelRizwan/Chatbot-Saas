"""Read-only, bounded diagnosis of a durably recorded failed evidence scope.

No measured lane execution, provider access, payload output or database changes.
The existing full resume preflight and repository read gate remain authoritative.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import Event
from time import monotonic, time
import uuid

from sqlalchemy import Text, cast, event, func, select, text

from database import canary_schema as s
from services.canary_contracts import Lane
from services.canary_repository import document_values, where
from services.structural_chunking import digest
from scripts.canary_bounded_output import emit
from scripts.canary_evaluation_resume import EvaluationRunner, require, read_bounded
from scripts.canary_evaluation_transport import safe_error


def utc():
    return datetime.now(timezone.utc).isoformat()


def atom_statement(scope, columns=None):
    require(set(scope) == set(s.DOC) | {'atom_id'}, 'EXACT_ATOM_SCOPE_REQUIRED')
    return select(*(columns or [s.atoms])).where(
        where(s.atoms, {k: scope[k] for k in s.DOC}), s.atoms.c.atom_id == scope['atom_id'])


def safe_plan(value):
    """Retain plan structure, never literal-bearing filter/index expressions."""
    allowed = {'Node Type', 'Parent Relationship', 'Join Type', 'Index Name',
               'Relation Name', 'Scan Direction', 'Startup Cost', 'Total Cost',
               'Plan Rows', 'Plan Width', 'Strategy', 'Partial Mode'}
    out = {k: v for k, v in value.items() if k in allowed}
    for key in ('Filter', 'Index Cond', 'Recheck Cond', 'Hash Cond', 'Join Filter'):
        if key in value:
            out[key + ' digest'] = sha256(value[key].encode()).hexdigest()
            out[key + ' scoped columns'] = [k for k in (*s.DOC, 'atom_id') if k in value[key]]
    if 'Plans' in value:
        out['Plans'] = [safe_plan(p) for p in value['Plans']]
    return out


def explain(conn, stmt):
    compiled = stmt.compile(dialect=conn.dialect)
    plan = conn.exec_driver_sql('EXPLAIN (FORMAT JSON) ' + str(compiled), compiled.params).scalar_one()
    return safe_plan(plan[0]['Plan'])


def row_facts(row):
    require(digest(row['payload']) == row['payload_hash'], 'EVIDENCE_PAYLOAD_CORRUPTION')
    return dict(row_count=1, canonical_row_hash=digest(dict(row)),
                payload_hash_validation='PASS', payload_hash=row['payload_hash'],
                payload_canonical_bytes=len(json.dumps(row['payload'], sort_keys=True,
                    separators=(',', ':'), ensure_ascii=False).encode()),
                canonical_text_bytes=len(row['canonical_text'].encode()))


def observer_sample(conn, pid):
    with conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        row = conn.execute(text('''SELECT pid,state,wait_event_type,wait_event,
            query_start,xact_start,backend_start,state_change,
            backend_xid IS NOT NULL AS xid_present,backend_xmin IS NOT NULL AS xmin_present,
            extract(epoch FROM clock_timestamp()-query_start)*1000 AS query_age_ms,
            pg_blocking_pids(pid) AS blockers
            FROM pg_stat_activity WHERE pid=:pid'''), {'pid': pid}).mappings().one_or_none()
        if row is None:
            return dict(timestamp=utc(), backend_visible=False)
        facts = {k: v.isoformat() if isinstance(v, datetime) else float(v) if k == 'query_age_ms'
                 and v is not None else v for k, v in row.items()}
        locks = conn.execute(text('''SELECT pid,locktype,mode,granted,relation
            FROM pg_locks WHERE pid=:pid OR pid=ANY(:blockers)
            ORDER BY pid,locktype,mode LIMIT 64'''), {'pid': pid, 'blockers': row['blockers']}).mappings().all()
        return dict(timestamp=utc(), backend_visible=True, activity=facts,
                    locks=[dict(v) for v in locks])


class ExactAtomDiagnostic(EvaluationRunner):
    def __init__(self, *args, failure_artifact, **kwargs):
        super().__init__(*args, **kwargs)
        require('/' not in failure_artifact and '\\' not in failure_artifact, 'FAILURE_ARTIFACT_NAME_REQUIRED')
        self.failed_record = read_bounded(self.folder/failure_artifact)
        self.scope = self.failed_record['source_scope']
        require(self.failed_record['phase'] == 'AFTER_CALL'
                and self.failed_record['case_id'] == 75
                and self.failed_record['lane'] == 'STRUCTURAL_CANARY'
                and self.failed_record['result_category'] == 'DATABASE_TIMEOUT'
                and self.failed_record['statement_started'], 'EXACT_FAILED_ATOM_REQUIRED')
        atom_statement(self.scope)
        self.diagnostics = []

    def authorize(self, repo):
        repo.read_gate(self.mf, self.hard, now=int(time()))
        pin = next((p for p in self.mf.documents
                    if document_values(self.mf, p) == {k: self.scope[k] for k in s.DOC}), None)
        require(pin is not None and self.scope['atom_id'] in pin.atoms
                and pin.scope.revision.source.document_id in self.mf.effective(self.hard),
                'EXACT_DIAGNOSTIC_SCOPE_REFUSED')

    def record(self, name, work):
        started = monotonic()
        result = dict(name=name, started=utc(), connection_token=uuid.uuid4().hex)
        try:
            with self.exclusive():
                self.identity_gate()
                with self.repository() as repo:
                    self.authorize(repo)
                    result.update(work(repo.conn))
            result['result'] = 'PASS'
        except Exception as exc:
            result.update(result='FAIL', failure=safe_error(exc))
        result['elapsed_ms'] = (monotonic()-started)*1000
        self.diagnostics.append(result)
        self.save(f'atom75-diagnostic-{self.session}-{name}', result, immutable=True)
        emit(dict(stage='EXACT_ATOM_DIAGNOSTIC', **result))
        return result

    def observed_exact(self, conn):
        stmt = atom_statement(self.scope)
        sql_hash = sha256(str(stmt.compile(dialect=conn.dialect)).encode()).hexdigest()
        require(sql_hash == self.failed_record['query_shape_sha256'], 'EXACT_QUERY_SHAPE_CHANGED')
        pid = conn.execute(text('SELECT pg_backend_pid()')).scalar_one()
        in_flight, finished = Event(), Event()
        result = dict(backend_pid=pid, query_shape_sha256=sql_hash, samples=[])
        def before(connection, cursor, statement, parameters, context, executemany):
            if connection is conn and sha256(statement.encode()).hexdigest() == sql_hash:
                result.update(query_client_start=utc(), query_monotonic_start=monotonic())
                in_flight.set()
        def fetch():
            started = monotonic()
            try:
                return dict(result='PASS', **row_facts(conn.execute(stmt).mappings().one()))
            except Exception as exc:
                return dict(result='FAIL', failure=safe_error(exc))
            finally:
                result.update(query_elapsed_ms=(monotonic()-started)*1000, query_client_end=utc())
                finished.set()
        event.listen(self.db.engine, 'before_cursor_execute', before)
        try:
            with self.db.engine.connect() as observer, ThreadPoolExecutor(max_workers=1) as pool:
                result['observer_pid'] = observer.execute(text('SELECT pg_backend_pid()')).scalar_one()
                observer.rollback()
                future = pool.submit(fetch)
                if in_flight.wait(35):
                    # The target has its existing 30s operation bound. Each
                    # observer SQL also has the existing server/client bounds.
                    for _ in range(20):
                        try:
                            result['samples'].append(observer_sample(observer, pid))
                        except Exception as exc:
                            result['observer_failure'] = safe_error(exc)
                            break
                        if finished.wait(1):
                            break
                result['exact_read'] = future.result(timeout=35)
                if not observer.invalidated and not observer.closed:
                    try:
                        result['samples'].append(observer_sample(observer, pid))
                    except Exception as exc:
                        result['observer_final_failure'] = safe_error(exc)
        finally:
            event.remove(self.db.engine, 'before_cursor_execute', before)
        return result

    def evaluate(self):
        self.mf = next(m for m in self.manifests if m.lane == Lane.STRUCTURAL_CANARY)
        snapshot, self.hard = next(v for v in self.common if v[0]['id'] == 75)
        require(self.failed_record['scope_digest'] == digest(dict(source=self.scope, hard=self.hard.identity())),
                'RECORDED_HARD_SCOPE_MISMATCH')
        require(int(time()) < self.retained_until, 'EVALUATION_LEASE_EXPIRED')
        self.record('A_EXACT_OBSERVED', self.observed_exact)
        metadata = [c for c in s.atoms.c if c.name not in ('canonical_text', 'payload')]
        self.record('B_METADATA', lambda c: dict(metadata=dict(c.execute(
            atom_statement(self.scope, metadata)).mappings().one())))
        sizes = [func.pg_column_size(s.atoms.c.canonical_text).label('text_stored_bytes'),
                 func.octet_length(s.atoms.c.canonical_text).label('text_utf8_bytes'),
                 func.pg_column_size(s.atoms.c.payload).label('payload_stored_bytes'),
                 func.octet_length(cast(s.atoms.c.payload, Text)).label('payload_json_bytes')]
        self.record('C_SIZES', lambda c: dict(sizes=dict(c.execute(atom_statement(self.scope, sizes)).mappings().one())))
        for field in ('canonical_text', 'payload'):
            def read_field(conn, field=field):
                started = monotonic()
                value = conn.execute(atom_statement(self.scope, [s.atoms.c[field]])).scalar_one()
                value_bytes = value.encode() if isinstance(value, str) else json.dumps(
                    value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
                return dict(field_category=field, bytes=len(value_bytes), sha256=sha256(value_bytes).hexdigest(),
                            field_read_ms=(monotonic()-started)*1000)
            self.record('D_'+field, read_field)
        self.record('PLAN_EXACT', lambda c: dict(plan=explain(c, atom_statement(self.scope))))
        def peers(conn):
            found = []
            scope = {k: self.scope[k] for k in s.DOC}
            for before in (True, False):
                predicate = s.atoms.c.atom_id < self.scope['atom_id'] if before else s.atoms.c.atom_id > self.scope['atom_id']
                order = s.atoms.c.atom_id.desc() if before else s.atoms.c.atom_id.asc()
                ids = conn.execute(select(s.atoms.c.atom_id).where(where(s.atoms, scope), predicate)
                                   .order_by(order).limit(2)).scalars().all()
                found.extend(ids)
            return dict(peer_atoms=found, peer_order='IMMUTABLE_ATOM_ID_LEXICOGRAPHIC')
        peers_result = self.record('E_PEER_IDS', peers)
        for index, key in enumerate(peers_result.get('peer_atoms', [])):
            def peer(conn, key=key):
                scope = dict(self.scope, atom_id=key)
                started = monotonic()
                row = conn.execute(atom_statement(scope)).mappings().one()
                facts = row_facts(row)
                facts.update(atom_id=key, read_ms=(monotonic()-started)*1000,
                             plan=explain(conn, atom_statement(scope)))
                return facts
            self.record('E_PEER_'+str(index), peer)
        with self.exclusive():
            self.identity_gate()
        self.result.update(stage='EXACT_ATOM_DIAGNOSIS_COMPLETE', decision='C',
            diagnostic_only=True, diagnosis_records=[r['name'] for r in self.diagnostics],
            unrelated_catalog_unchanged=True, measured_lanes_executed=0)
