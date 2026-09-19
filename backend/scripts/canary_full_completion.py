"""Authorized final 17 lanes: frozen semantics, evaluation-only read recovery."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import json
from time import time, sleep

from sqlalchemy import select, text
from database import canary_schema as s
from services.canary_contracts import Lane
from services.canary_database_guard import DisposableTarget, validate_target
from services.canary_repository import run_values, where
from services.canary_representation import exact_input_hash
from services.canary_retrieval import run_query
from services.structural_chunking import digest
from scripts.canary_bounded_output import emit, vector_summary
from scripts.canary_evaluation_resume import (EvaluationRunner, EvaluationRepository, require,
    read_bounded, verify_ownership, READABLE, frozen_files)
from scripts.canary_evaluation_transport import ExclusiveRun, transient_transport, safe_error
from scripts.canary_final_evaluation import FinalEvaluation
from scripts.canary_case82_completion import Case82Completion, AUTHORIZATION as PREVIOUS_AUTHORIZATION
from scripts.canary_postgres_validation import catalog_snapshot, DisposableCanary
from scripts.canary_real_evaluation import score_case, safe_trace
from scripts.canary_split_evidence import SplitEvidenceRepository
from scripts.canary_read_recovery import (ReadTelemetry, ObservedConnection, RecoveringConnection,
                                         OwnershipTransportFailure)
from scripts.canary_exact_atom_diagnostic import safe_plan, observer_sample

AUTHORIZATION = 'CASE82_STRUCTURAL_FULL_COMPLETION_RECOVERY_20260919'
WRAPPERS = ('canary_full_completion.py', 'canary_read_recovery.py')
# Exact internal catalog SELECT literals only; arbitrary textual SQL is not eligible.
CATALOG_SQL = frozenset(value for fn in (verify_ownership, catalog_snapshot, DisposableCanary.relations)
                        for value in fn.__code__.co_consts
                        if isinstance(value, str) and value.lstrip().upper().startswith('SELECT'))


class ValidatedEvidenceRepository(SplitEvidenceRepository):
    """Record existing post-read hash validation without altering evidence."""
    def evidence(self, manifest, hard, route, key, *, now):
        telemetry = self.conn.telemetry
        try:
            evidence = super().evidence(manifest, hard, route, key, now=now)
        except Exception as exc:
            telemetry.writer(dict(telemetry.context, phase='EVIDENCE_VALIDATION_FAILURE',
                operation_ordinal=telemetry.ordinal, document=route.source.revision.source.document_id,
                evidence_key=key, failure=safe_error(exc)))
            raise
        telemetry.writer(dict(telemetry.context, phase='EVIDENCE_VALIDATED',
            operation_ordinal=telemetry.ordinal, document=route.source.revision.source.document_id,
            evidence_key=key, full_row_hash='PASS' if route.kind != 'LEGACY_CHUNK' else 'NOT_APPLICABLE',
            evidence_digest=digest(evidence)))
        return evidence


def recovery_hashes(root):
    return {name: sha256((root/'backend/scripts'/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name in WRAPPERS}


class FullCompletion(Case82Completion):
    def __init__(self, *args, final_authorization, **kwargs):
        require(final_authorization == AUTHORIZATION, 'FULL_COMPLETION_AUTHORIZATION_REQUIRED')
        super().__init__(*args, final_authorization=PREVIOUS_AUTHORIZATION, **kwargs)
        self.reads = ReadTelemetry(self.write_read)
        self.measured_scope = None
        self.epochs = {}
        self.result.update(final_authorization=AUTHORIZATION, transport='GENERIC_READ_RECOVERY_V1')

    def write_read(self, record):
        self.save(f"read-{self.session}-{record['operation_ordinal']:07d}-{record['phase']}", record, immutable=True)

    def admit_execution(self, admission):
        super().admit_execution(admission)
        self.recovery_code = recovery_hashes(self.root)
        self.save('full-completion-admission-'+digest(self.recovery_code), dict(
            authorization=AUTHORIZATION, checkpoint='9aa3be257e06aa75a9bd7935e85e6ec936099bb6',
            identity_hash=self.identity_hash, wrappers=self.recovery_code,
            saved_lane_hashes_digest=digest({p.name:sha256(p.read_bytes()).hexdigest()
                                            for p in sorted(self.folder.glob('case-*.json'))})), immutable=True)

    def setup(self):
        # Do not install old evidence-only event hooks: every read now has a boundary.
        EvaluationRunner.setup(self)
        require(self.reused >= 163 and self.completed() >= 81, 'FROZEN_STARTING_RESULTS_REQUIRED')
        require(len(self.split_expected) == sum(len(p.atoms) for mf in self.manifests
                if mf.lane == Lane.STRUCTURAL_CANARY for p in mf.documents), 'FULL_OLD_ATOM_ROW_INVENTORY_REQUIRED')
        self.result['read_recovery'] = 'READY'

    @contextmanager
    def exclusive(self):
        # Ownership lives on a separate connection; transport replacement cannot
        # silently release the lock. Healthy heartbeats occur on each read-session open.
        require(self.lock is None, 'NESTED_EVALUATION_OWNERSHIP')
        lock = self.lock = ExclusiveRun(self.db)
        try:
            lock.acquire()
            yield
        finally:
            errors = lock.close()
            self.cleanup_errors.extend(errors)
            self.lock = None
            # Invalid unlock is diagnostic, not a replacement for a successful lane.

    def fresh_raw(self):
        url = self.db.config.url
        validate_target(url.render_as_string(hide_password=False), DisposableTarget(
            host_database_fingerprint=self.approval.database_identity,
            ownership_marker=self.namespace, approval_reference=self.approval.operator_reference), self.approval)
        conn = self.db.engine.connect()
        try:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            self.db.configure(conn)
            return conn
        except BaseException:
            conn.invalidate()
            conn.close()
            raise

    def revalidate_read_connection(self, conn):
        if self.lock and self.lock.conn is not None:
            # A dead ownership socket aborts the UNSAVED lane, never authorizes
            # continued work under an unheld lock. No reconnect on this connection.
            if self.lock.conn.closed or self.lock.conn.invalidated:
                raise OwnershipTransportFailure('OWNERSHIP_CONNECTION_LOST')
            heartbeat = ObservedConnection(self.lock.conn, self.reads, allowed_text=('SELECT 1',),
                                          purpose='OWNERSHIP_HEARTBEAT')
            try:
                heartbeat.execute(text('SELECT 1')).scalar_one()
                self.lock.conn.commit()
            except Exception as exc:
                if not transient_transport(exc):
                    raise
                self.lock.conn.invalidate()
                raise OwnershipTransportFailure('OWNERSHIP_CONNECTION_LOST') from None
        control = conn.execute(select(s.recovery).where(where(s.recovery, run_values(self.manifests[0])))).mappings().one()
        require(control['identity_hash'] == self.identity_hash == digest(control['identity'])
                and control['identity'] == self.identity and control['retained_until'] == self.retained_until,
                'READ_RECOVERY_IDENTITY_MISMATCH')
        verify_ownership(self.db, conn, self.approval, control)
        repo = EvaluationRepository(conn, self.approval, authorization=self.authorization,
            lease_until=self.retained_until, identities=[m.canonical_hash() for m in self.manifests],
            inspection=self.measured_scope is None)
        for mf, proof in zip(self.manifests, self.identity['manifests']):
            run, stored = repo._run(mf), repo._manifest(mf)
            require(run['state'] in READABLE and run['expires_at'] == self.retained_until
                    and stored['state'] in READABLE and stored['build_identity'] == proof['build_identity'],
                    'READ_RECOVERY_SEALED_IDENTITY_MISMATCH')
            repo._snapshot(mf, stored, int(time()))
        if self.measured_scope:
            mf, hard = self.measured_scope
            token = repo.read_gate(mf, hard, now=int(time()), expected_epoch=self.epochs.get(mf.canonical_hash()))
            self.epochs.setdefault(mf.canonical_hash(), token)

    def diagnostic(self, statement, parameters, identity, cycle):
        """Three independent probes at most; successful data is not scored here."""
        ordinal = self.reads.ordinal
        for number in range(1, 4):
            conn = None
            record = dict(**identity, probe=number, cycle=cycle+1, provider_calls=0)
            try:
                conn = self.fresh_raw()
                observed = ObservedConnection(conn, self.reads, allowed_text=CATALOG_SQL,
                                               purpose='REVALIDATION')
                self.revalidate_read_connection(observed)
                pid = conn.execute(text('SELECT pg_backend_pid()')).scalar_one()
                record['backend_pid'] = pid
                def probe():
                    return ObservedConnection(conn, self.reads, allowed_text=CATALOG_SQL,
                        purpose='EXACT_PROBE').execute(statement, parameters).all()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(probe)
                    try:
                        with self.db.engine.connect() as observer:
                            record['observer'] = observer_sample(observer, pid)
                    except Exception as exc:
                        # The independent observer supplies diagnostics, not read
                        # authorization. Its failure cannot invalidate a good probe.
                        record['observer_failure'] = safe_error(exc)
                    rows = future.result(timeout=40)
                record.update(result='SUCCESS', row_count=len(rows))
                sizes = [[len(json.dumps(value, sort_keys=True, ensure_ascii=False,
                    default=str).encode()) for value in row] for row in rows]
                record['client_size_bytes'] = dict(total_fields=sum(sum(v) for v in sizes),
                    largest_field=max((n for v in sizes for n in v), default=0),
                    largest_row_fields=max(map(sum, sizes), default=0))
                compiled = statement.params(**(parameters or {})).compile(dialect=conn.dialect,
                    compile_kwargs={'render_postcompile': True})
                try:
                    plan = conn.exec_driver_sql('EXPLAIN (FORMAT JSON) '+str(compiled), compiled.params).scalar_one()
                    record['plan'] = safe_plan(plan[0]['Plan'])
                except Exception as exc:
                    if not transient_transport(exc):
                        raise
                    record['plan_transport_failure'] = safe_error(exc)
                return True
            except Exception as exc:
                record.update(result='FAILURE', failure=safe_error(exc))
                if not transient_transport(exc):
                    raise
            finally:
                if conn is not None:
                    if record.get('result') != 'SUCCESS' or record.get('plan_transport_failure'):
                        conn.invalidate()
                    conn.close()
                self.save(f'read-probe-{self.session}-{ordinal}-{cycle}-{number}', record, immutable=True)
        return False

    @contextmanager
    def repository(self, *, inspection=False, writable=False):
        if writable or not hasattr(self, 'identity') or not self.manifests:
            with super().repository(inspection=inspection, writable=writable) as repo:
                yield repo
            return
        conn = RecoveringConnection(self.fresh_raw, self.revalidate_read_connection, self.reads,
            self.diagnostic, dialect=self.db.engine.dialect, allowed_text=CATALOG_SQL)
        try:
            yield ValidatedEvidenceRepository(conn, self.approval, authorization=self.authorization,
                lease_until=self.retained_until, identities=[m.canonical_hash() for m in self.manifests],
                inspection=inspection, observer=None, expected_rows=self.split_expected)
        finally:
            conn.close()

    def ensure_lease(self):
        # Original full source/vector/query validation, ownership and CAS; no old
        # one-renewal-only wrapper. User authorized active-run 24h increments.
        if self.retained_until <= int(time())+3600:
            self.load_cases(count_reuse=False)
        EvaluationRunner.ensure_lease(self)

    def before_lane_attempt(self, snapshot, hard, mf, attempt):
        case, lane = snapshot['id'], mf.lane.value
        require(82 <= case <= 90 and not (case == 82 and mf.lane == Lane.LEGACY_CONTROL),
                'SAVED_HISTORICAL_LANE_REEXECUTION_REFUSED')
        require(attempt in (0, 1, 2), 'THREE_LANE_EXECUTIONS_ONLY')
        require(recovery_hashes(self.root) == self.recovery_code and frozen_files(self.root) == self.code,
                'FROZEN_IMPLEMENTATION_CHANGED')
        require(not (self.folder/(self.case_name(case, mf)+'.json')).exists(), 'SAVED_LANE_REEXECUTION_REFUSED')
        name = f'{AUTHORIZATION}-{case:02d}-{lane}-attempt-{attempt+1}'
        require(not (self.folder/(name+'.json')).exists(), 'LANE_ATTEMPT_ALREADY_CONSUMED')
        self.save(name, dict(authorization=AUTHORIZATION, session=self.session, case=case, lane=lane,
            attempt_ordinal=attempt+1, identity_hash=self.identity_hash, manifest=mf.canonical_hash(),
            generation=mf.generation, snapshot_hash=snapshot['snapshot_hash'], hard_scope=hard.identity(),
            query_vector_hash=self.queries[exact_input_hash(snapshot['query'])].vector_hash,
            timestamp=int(time()), provider_calls=0), immutable=True)
        self.reads.context = dict(case=case, lane=lane, lane_attempt=attempt+1, manifest=mf.canonical_hash(),
            generation=mf.generation, organization_id=hard.organization_id, bot_id=hard.bot_id,
            hard_scope_digest=digest(hard.identity()))

    def next_unused_attempt(self, snapshot, hard, mf):
        """Interrupted processes consume attempts; immutable history is never reset."""
        case, lane = snapshot['id'], mf.lane.value
        prefix = f'{AUTHORIZATION}-{case:02d}-{lane}-attempt-'
        paths = sorted(self.folder.glob(prefix+'*.json'))
        require(len(paths) <= 3, 'THREE_LANE_EXECUTIONS_ONLY')
        for ordinal, path in enumerate(paths, 1):
            require(path.name == prefix+str(ordinal)+'.json', 'LANE_ATTEMPT_LEDGER_GAP')
            prior = read_bounded(path)
            expected = dict(authorization=AUTHORIZATION, case=case, lane=lane,
                attempt_ordinal=ordinal, identity_hash=self.identity_hash,
                manifest=mf.canonical_hash(), generation=mf.generation,
                snapshot_hash=snapshot['snapshot_hash'], hard_scope=hard.identity(),
                query_vector_hash=self.queries[exact_input_hash(snapshot['query'])].vector_hash,
                provider_calls=0)
            require(all(prior.get(k) == v for k,v in expected.items()), 'LANE_ATTEMPT_IDENTITY_MISMATCH')
            session = prior.get('session')
            require(isinstance(session, str) and len(session) == 32
                    and all(c in '0123456789abcdef' for c in session), 'LANE_ATTEMPT_SESSION_MISMATCH')
            failure = self.folder/f'lane-failure-{session}-{case:02d}-{lane}-{ordinal}.json'
            if failure.exists():
                value = read_bounded(failure)
                require(value.get('case') == case and value.get('lane') == lane
                        and value.get('attempt') == ordinal and value.get('saved') is False,
                        'LANE_FAILURE_LEDGER_MISMATCH')
                require(value.get('failure', {}).get('category') == 'DATABASE_TRANSPORT_FAILURE',
                        'NON_TRANSPORT_LANE_RESUME_REFUSED')
        require(len(paths) < 3, 'THREE_LANE_EXECUTIONS_ONLY')
        return len(paths)

    def evaluate_lane(self, snapshot, hard, mf):
        case = snapshot['id']
        self.current = dict(case=case, lane=mf.lane.value)
        saved_path = self.folder/(self.case_name(case, mf)+'.json')
        first_attempt = 0 if saved_path.exists() else self.next_unused_attempt(snapshot, hard, mf)
        for attempt in range(first_attempt, 3):
            self.measured_scope = None
            try:
                with self.exclusive():
                    self.identity_gate()
                    path = self.folder/(self.case_name(case, mf)+'.json')
                    if path.exists():
                        self.rows[(case, mf.lane.value)] = self.validate(read_bounded(path), snapshot, hard, mf)
                        self.pair(case)
                        return
                    self.before_lane_attempt(snapshot, hard, mf, attempt)
                    self.measured_scope = (mf, hard)
                    before = self.reads.summary()
                    emit(dict(stage='RECOVERABLE_EVALUATION_LANE', **self.current, attempt=attempt+1,
                              completed_pairs=self.completed()))
                    qr = self.queries[exact_input_hash(snapshot['query'])]
                    with self.repository() as repo:
                        trace = run_query(repo, mf, hard, query=snapshot['query'], query_vector=qr.vector, now=int(time()))
                    require(trace['mode'] == 'full_hybrid', 'PAIRED_CHANNEL_FAILURE')
                    record = dict(case=case, lane=mf.lane.value, snapshot_hash=snapshot['snapshot_hash'], query=vector_summary(qr),
                        outcome=score_case(trace, self.gold[case], mf.lane.value, mf.effective(hard), self.entry_atoms), trace=safe_trace(trace))
                    row = self.validate(record, snapshot, hard, mf)
                    delta = {k:v-before[k] for k,v in self.reads.summary().items()}
                    self.save(f'read-summary-{self.session}-{case:02d}-{mf.lane.value}', dict(
                        **self.current, lane_attempt=attempt+1, **delta, provider_calls=0,
                        hash_validation='PASS', transport='GENERIC_READ_RECOVERY_V1'), immutable=True)
                    self.save(self.case_name(case, mf), record, immutable=True)
                    self.rows[(case, mf.lane.value)] = row
                    self.last_completed = dict(self.current)
                    self.new_lanes += 1
                    self.pair(case)
                    self.aggregate()
                    self.save('evaluation-session-'+self.session, dict(self.result, status='RUNNING',
                        new_lanes=self.new_lanes, completed_pairs=self.completed(), next_resumable_lane=self.next_lane(),
                        recovery=self.reads.summary()))
                    emit(dict(stage='LANE_SAVED', **self.current, completed_pairs=self.completed(),
                              saved_lanes=len(self.rows), recovery=delta))
                return
            except Exception as exc:
                saved = (self.folder/(self.case_name(case, mf)+'.json')).exists()
                self.save(f'lane-failure-{self.session}-{case:02d}-{mf.lane.value}-{attempt+1}',
                    dict(**self.current, attempt=attempt+1, failure=safe_error(exc), saved=saved), immutable=True)
                if saved or not transient_transport(exc) or attempt == 2:
                    raise
                self.transport_retries += 1
                sleep((1, 2)[attempt])
            finally:
                self.measured_scope = None
