"""Execution-only same-family Q1 continuation. Packing/retrieval stay frozen.

Successful lanes are never rerun. Execution failures remain unscored; integrity
guards fail closed. The only permitted writes to PostgreSQL are one explicitly
authorized, compare-and-swap retention extension (two expiry columns).
"""
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter, time
from types import FunctionType

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from database import canary_schema as s
from services.canary_contracts import CanaryError
from services.canary_repository import run_values, where
from services.structural_chunking import digest
from scripts.canary_bounded_output import emit
from scripts.canary_evaluation_resume import (EvaluationRunner, EvaluationRepository,
    atomic_record, provider_free, read_bounded, require, verify_lease_chain,
    verify_ownership, READABLE)
from scripts.canary_evaluation_transport import (bounded_database_io, safe_error,
    transient_transport, ChannelTransportFailure)
from scripts.canary_read_recovery import ReadTelemetry
from scripts.replay_compact_evidence_pack import hashes
from scripts.run_compact_evidence_canary import CompactCanary

REASON = 'ACTIVE_PHASE_4_1Q1_90_CASE_EVALUATION'
OLD_EXPIRY = 1789895058
NEW_EXPIRY = OLD_EXPIRY + 86400
EXECUTION_GUARDS = frozenset((
    'REPRODUCIBLE_DATABASE_READ_FAILURE', 'READ_RECOVERY_CYCLES_EXHAUSTED',
    'DATABASE_OPERATION_RESPONSE_TIMEOUT', 'DATABASE_POLL_STATE_FAILURE',
    'DATABASE_TRANSPORT_FAILURE', 'OWNERSHIP_CONNECTION_LOST',
    'PAIRED_CHANNEL_FAILURE', 'DATABASE_CLEANUP_FAILURE',
))


def execution_only(exc):
    """Unknown guard/validation errors are never downgraded to execution noise."""
    if isinstance(exc, CanaryError):
        return str(exc) in EXECUTION_GUARDS or isinstance(exc, ChannelTransportFailure)
    if transient_transport(exc) or isinstance(exc, TimeoutError):
        return True
    # Permission, integrity and unclassified database faults are not transport.
    code = str(getattr(getattr(exc, 'orig', None), 'pgcode', '') or '')
    return isinstance(exc, DBAPIError) and (code.startswith(('08', '40', '53', '58'))
        or code in ('57014', '57P01', '57P02', '57P03'))


def renewal_update(conn, manifest, identity_hash, old, new):
    require((old, new) == (OLD_EXPIRY, NEW_EXPIRY), 'Q1_LEASE_INCREMENT_REFUSED')
    key = run_values(manifest)
    control = conn.execute(select(s.recovery).where(where(s.recovery, key))
                           .with_for_update()).mappings().one()
    run = conn.execute(select(s.runs).where(where(s.runs, key))
                       .with_for_update()).mappings().one()
    require(control['identity_hash'] == identity_hash and control['retained_until'] == old
            and run['expires_at'] == old and run['state'] in READABLE
            and control['condition'] in ('PAUSED', 'PROVIDER_HOLD', 'COMPLETE'),
            'Q1_LEASE_CONCURRENT_CHANGE')
    require(conn.execute(update(s.recovery).where(where(s.recovery, key),
        s.recovery.c.retained_until == old).values(retained_until=new)).rowcount == 1,
        'Q1_LEASE_CONCURRENT_CHANGE')
    require(conn.execute(update(s.runs).where(where(s.runs, key),
        s.runs.c.expires_at == old).values(expires_at=new)).rowcount == 1,
        'Q1_LEASE_CONCURRENT_CHANGE')


class OvernightCanary(CompactCanary):
    def __init__(self, root, env, *, namespace, run_id, identity_hash,
                 replay_folder, existing_folder, renew_on_resume=False):
        EvaluationRunner.__init__(self, root, env, namespace=namespace,
                                 run_id=run_id, identity_hash=identity_hash)
        require(env.get('CANARY_COMPACT_Q1_AUTHORIZED') == 'true'
                and env.get('CANARY_Q1_OVERNIGHT_AUTHORIZED') == 'true',
                'Q1_OVERNIGHT_AUTHORIZATION_REQUIRED')
        self.output = existing_folder.resolve()
        require(self.output.parent == root / '.codex_phase4q' and self.output.is_dir()
                and self.output.name.startswith('REAL_CORPUS_V1_EVAL_V1_PHASE4Q1-'),
                'EXISTING_Q1_FAMILY_REQUIRED')
        self.replay_folder = replay_folder.resolve()
        require(self.replay_folder.parent == root / '.codex_phase4q', 'Q1_REPLAY_FOLDER_REQUIRED')
        self.replay = json.loads((self.replay_folder / 'summary.json').read_text())
        require(self.replay['real_rerun_gate'] == 'PASS'
                and self.replay['old_pack_exact_reproduction'] == 90
                and not self.replay['lost_previous_support'], 'Q1_REPLAY_GATE_FAILED')
        self.verify_phase_p()
        self.reads = ReadTelemetry(self.write_read)
        self.measured_scope = None
        self.epochs = {}; self.split_expected = {}; self.baseline_records = {}
        self.telemetry = None; self.preflight = True
        self.renew_on_resume = renew_on_resume
        self.deferred = {}
        self.wrapper_hash = sha256(Path(__file__).read_bytes()).hexdigest()
        self.result.update(family=self.output.name, provider_calls=0,
                           overnight=True, phase_p_folder_read_only=True)
        self.events = []
        for p in sorted(self.output.glob('overnight-deferred-*.json')):
            if p.name == 'overnight-deferred-lanes.json':
                continue
            event = read_bounded(p)
            require(event['identity_hash'] == self.identity_hash
                    and event['status'] == 'DEFERRED_EXECUTION_FAILURE'
                    and event['scored'] is False, 'DEFERRED_LEDGER_CORRUPTION')
            self.deferred[event['case'], event['lane']] = event

    def verify_phase_p(self):
        require(hashes(self.folder) == json.loads((
            self.replay_folder / 'phase-p-artifact-hashes.json').read_text()), 'PHASE_P_BASELINE_CHANGED')
        pins = json.loads((self.root / '.codex_structural_4_1m/preservation_before.json').read_text())
        require(len(pins) == 740 and all((self.root / p).is_file()
            and sha256((self.root / p).read_bytes()).hexdigest() == h for p, h in pins.items()),
            'PROTECTED_HASH_CORRUPTION')

    def save(self, name, value, **kwargs):
        require('/' not in name and '\\' not in name, 'Q1_ARTIFACT_NAME_REQUIRED')
        if name.startswith('attempt-'):
            value = dict(value, attempt=self.attempt_ordinal, execution_session=self.session)
            name = f'overnight-{name}-{self.session}-{self.attempt_ordinal}'
        path = self.output / (name + '.json')
        if path.exists() and kwargs.get('immutable') and name.startswith('evaluation-validation-'):
            require(read_bounded(path) == value, 'Q1_SEALED_VALIDATION_CHANGED')
            return
        atomic_record(path, value, **kwargs)

    def event(self, kind, **values):
        record = dict(kind=kind, timestamp=int(time()), session=self.session,
                      identity_hash=self.identity_hash, provider_calls=0, **values)
        self.save(f'overnight-event-{self.session}-{len(self.events):04d}', record, immutable=True)
        self.events.append(record)
        emit(record)
        # Generated execution log only; never source/evidence/Phase-P history.
        report = self.root / 'docs/PHASE_4_1Q_COMPACT_EVIDENCE_PACK_REPORT.md'
        with report.open('a', encoding='utf-8') as stream:
            stream.write('\n- OVERNIGHT Q1 EXECUTION LOG: `' + json.dumps(record, sort_keys=True) + '`\n')
            stream.flush()

    def admit_execution(self, admission):
        saved = read_bounded(self.output / 'admission.json')
        require(admission == saved['admission']
                and sha256((self.replay_folder / 'summary.json').read_bytes()).hexdigest()
                    == saved['replay_sha256'], 'Q1_ADMISSION_CHANGED')
        self.q1_code = saved['q1_code']
        require(all(sha256((self.root / p).read_bytes()).hexdigest() == h
                    for p, h in self.q1_code.items()), 'Q1_IMPLEMENTATION_CHANGED')
        self.save('overnight-admission-' + self.session,
            dict(original_admission_sha256=sha256((self.output / 'admission.json').read_bytes()).hexdigest(),
                 wrapper_sha256=self.wrapper_hash, identity_hash=self.identity_hash), immutable=True)

    def combined_lease_chain(self, folder, identity_hash, original, retained):
        require(folder == self.folder and identity_hash == self.identity_hash,
                'Q1_LEASE_AUDIT_IDENTITY_MISMATCH')
        verify_lease_chain(folder, identity_hash, original, OLD_EXPIRY)
        require(retained in (OLD_EXPIRY, NEW_EXPIRY), 'Q1_LEASE_UNAUTHORIZED_EXPIRY')
        if retained == NEW_EXPIRY:
            event = read_bounded(self.output / 'overnight-lease-prepared.json')
            require(event['identity_hash'] == identity_hash and event['namespace'] == self.namespace
                    and event['run'] == self.run_id and event['reason'] == REASON
                    and (event['old_retained_until'], event['new_retained_until'])
                        == (OLD_EXPIRY, NEW_EXPIRY)
                    and event['q1_family'] == self.output.name,
                    'Q1_LEASE_AUDIT_MISMATCH')

    def setup(self):
        # Same preflight bytecode; only extend audit-chain lookup to this Q1
        # folder. Historical Phase-P lease records are never altered.
        original = EvaluationRunner.setup
        fn = FunctionType(original.__code__, dict(original.__globals__,
            verify_lease_chain=self.combined_lease_chain), original.__name__,
            original.__defaults__, original.__closure__)
        fn(self)
        require(self.reused == 180 and self.completed() == 90, 'COMPLETE_PHASE_P_REQUIRED')
        self.baseline_records = {(snapshot['id'], mf.lane.value): read_bounded(
            self.folder / (self.case_name(snapshot['id'], mf) + '.json'))
            for snapshot, _ in self.common for mf in self.manifests}
        require(len(self.split_expected) == sum(len(p.atoms) for mf in self.manifests
            if mf.lane.value == 'STRUCTURAL_CANARY' for p in mf.documents),
            'FULL_OLD_ATOM_ROW_INVENTORY_REQUIRED')
        self.rows = {}; self.reused = 0; self.preflight = False
        self.load_q1()
        if self.retained_until == NEW_EXPIRY:
            prepared = read_bounded(self.output / 'overnight-lease-prepared.json')
            require(prepared['manifests'] == [m.canonical_hash() for m in self.manifests]
                    and prepared['validation_hash'] == self.validation_proof['checksum']
                    and prepared['query_inventory'] == self.validation_proof['query_inventory'],
                    'Q1_RENEWED_SEALED_IDENTITY_MISMATCH')
            if not (self.output / 'overnight-lease-committed.json').exists():
                self.save('overnight-lease-committed', dict(prepared,
                    recovered_after_interruption=True, confirmed_at=int(time())), immutable=True)
        self.event('OVERNIGHT_RESUMED', successful_pairs=self.completed(),
                   successful_lanes=len(self.rows), deferred_lanes=len(self.deferred),
                   next_lane=self.next_unsaved())
        if self.renew_on_resume and self.retained_until == OLD_EXPIRY:
            self.renew_once(preflight_fresh=True)

    def validate_q1_record(self, case, mf, record, packing, snapshot, hard):
        row = self.validate(record, snapshot, hard, mf)
        old = self.baseline_records[case, mf.lane.value]
        require(packing['case'] == case and packing['lane'] == mf.lane.value
                and packing['upstream_identity'] == 'EXACT_EQUAL', 'Q1_PACKING_RECORD_MISMATCH')
        for field in ('raw_dense', 'raw_fts', 'rrf', 'manifest', 'effective_scope', 'hard_scope', 'query_hash'):
            require(record['trace'][field] == old['trace'][field], 'Q1_UPSTREAM_IDENTITY_CHANGED')
        if mf.lane.value == 'LEGACY_CONTROL':
            require(all(record['trace'][k] == old['trace'][k] for k in ('materialized', 'bytes', 'status')),
                    'Q1_LEGACY_CHANGED')
        else:
            replay = json.loads((self.replay_folder / f'case-{case:02d}.json').read_text())
            require(packing['model_bytes_sha256'] == replay['model_bytes_sha256']
                    and record['trace']['bytes'] == replay['new_bytes']
                    and len(record['trace']['materialized']) == replay['new_units']
                    and record['trace']['materialized'] == replay['materialized'],
                    'Q1_REAL_REPLAY_PACK_MISMATCH')
        return row

    def attest_saved_lane(self, case, mf):
        proof = dict(case=case, lane=mf.lane.value, identity_hash=self.identity_hash,
            case_sha256=sha256((self.output / (self.case_name(case, mf) + '.json')).read_bytes()).hexdigest(),
            packing_sha256=sha256((self.output / f'packing-{case:02d}-{mf.lane.value}.json').read_bytes()).hexdigest())
        self.save(f'overnight-saved-checksum-{case:02d}-{mf.lane.value}', proof, immutable=True)

    def load_q1(self):
        self.reused = 0
        for snapshot, hard in self.common:
            case = snapshot['id']
            for mf in self.manifests:
                key = case, mf.lane.value
                path = self.output / (self.case_name(case, mf) + '.json')
                pp = self.output / f'packing-{case:02d}-{mf.lane.value}.json'
                require(path.exists() == pp.exists(), 'Q1_PARTIAL_SAVED_ARTIFACT_REQUIRES_REVIEW')
                if path.exists():
                    self.rows[key] = self.validate_q1_record(case, mf, read_bounded(path),
                        read_bounded(pp), snapshot, hard)
                    self.attest_saved_lane(case, mf)
                    self.reused += 1
            self.pair(case)
        require(not (set(self.rows) & set(self.deferred)), 'Q1_SUCCESS_DEFERRED_CONFLICT')
        self.aggregate()

    def pair(self, case):
        if self.preflight:
            return CompactCanary.pair(self, case)
        path = self.output / f'evaluation-pair-{case:02d}.json'
        complete = all((case, mf.lane.value) in self.rows for mf in self.manifests)
        if path.exists():
            value = read_bounded(path)
            require(complete and value['case'] == case and value['identity_hash'] == self.identity_hash
                    and value['status'] == 'COMPLETE'
                    and {v['lane'] for v in value['lanes']} == {mf.lane.value for mf in self.manifests},
                    'Q1_SAVED_PAIR_IDENTITY_MISMATCH')
            require(all(sha256((self.output / f"case-{case:02d}-{v['lane']}.json").read_bytes()).hexdigest()
                        == v['artifact_sha256'] for v in value['lanes']), 'Q1_SAVED_PAIR_CHECKSUM_MISMATCH')
        elif complete:
            CompactCanary.pair(self, case)

    def next_unsaved(self):
        return next((dict(case=snapshot['id'], lane=mf.lane.value)
            for snapshot, _ in self.common for mf in self.manifests
            if (snapshot['id'], mf.lane.value) not in self.rows
            and (snapshot['id'], mf.lane.value) not in self.deferred), None)

    def aggregate(self):
        if self.preflight:
            return
        EvaluationRunner.aggregate(self)
        self.save('overnight-resume-state', dict(identity_hash=self.identity_hash,
            successful_pairs=self.completed(), successful_lanes=len(self.rows),
            deferred_lanes=len(self.deferred), next_independent_lane=self.next_unsaved(),
            deferred=self.deferred_index(), provider_calls=0))

    def deferred_index(self):
        return {str(case): [lane for c, lane in sorted(self.deferred) if c == case]
                for case in sorted({c for c, _ in self.deferred})}

    def renew_once(self, *, preflight_fresh=False):
        require(self.env.get('CANARY_Q1_ONE_DAY_RENEWAL_AUTHORIZED') == 'true'
                and self.retained_until == OLD_EXPIRY and int(time()) < OLD_EXPIRY,
                'Q1_ONE_DAY_RENEWAL_NOT_AUTHORIZED')
        require(sha256(Path(__file__).read_bytes()).hexdigest() == self.wrapper_hash,
                'Q1_EXECUTION_CONTROLLER_CHANGED')
        if not preflight_fresh:
            self.validate_sealed(full=True)
        self.verify_phase_p()
        self.load_q1()
        event = dict(identity_hash=self.identity_hash, namespace=self.namespace, run=self.run_id,
            q1_family=self.output.name, reason=REASON, old_retained_until=OLD_EXPIRY,
            new_retained_until=NEW_EXPIRY, manifests=[m.canonical_hash() for m in self.manifests],
            validation_hash=self.validation_proof['checksum'],
            query_inventory=self.validation_proof['query_inventory'],
            successful_lane_count=len(self.rows), provider_calls=0)
        prepared = self.output / 'overnight-lease-prepared.json'
        if prepared.exists():
            require(read_bounded(prepared) == event, 'Q1_LEASE_PREPARATION_MISMATCH')
        else:
            self.save('overnight-lease-prepared', event, immutable=True)
        with self.exclusive():
            self.identity_gate()
            # Deliberate narrow exception to read-only execution: only these
            # two CAS expiry updates are permitted by the overnight instruction.
            with self.db.engine.begin() as conn:
                self.db.configure(conn)
                control = conn.execute(select(s.recovery).where(where(s.recovery,
                    run_values(self.manifests[0]))).with_for_update()).mappings().one()
                verify_ownership(self.db, conn, self.approval, control)
                repo = EvaluationRepository(conn, self.approval, authorization=self.authorization,
                    lease_until=self.retained_until, identities=[m.canonical_hash() for m in self.manifests],
                    inspection=True)
                for mf in self.manifests:
                    stored = repo._manifest(mf)
                    require(stored['state'] in READABLE, 'EXACT_SEALED_GENERATION_REQUIRED')
                    repo._snapshot(mf, stored, int(time()), lock=True)
                renewal_update(conn, self.manifests[0], self.identity_hash, OLD_EXPIRY, NEW_EXPIRY)
        self.retained_until = NEW_EXPIRY
        self.save('overnight-lease-committed', dict(event, confirmed_at=int(time())), immutable=True)
        self.event('LEASE_EXTENDED', old_retained_until=OLD_EXPIRY, new_retained_until=NEW_EXPIRY,
                   reason=REASON)

    def ensure_lease(self):
        if self.retained_until == OLD_EXPIRY and self.retained_until - int(time()) <= 7200:
            self.renew_once()
        CompactCanary.ensure_lease(self)

    def record_failure(self, snapshot, hard, mf, exc, before, elapsed):
        latest = self.reads.latest or {}
        safe = safe_error(exc)
        event = dict(case=snapshot['id'], lane=mf.lane.value, attempt=self.attempt_ordinal,
            timestamp=int(time()), identity_hash=self.identity_hash,
            status='DEFERRED_EXECUTION_FAILURE', scored=False, failure=safe,
            stage=latest.get('retrieval_stage', 'ADMISSION_OR_EXECUTION'),
            repository_method=latest.get('repository_method'), scope_digest=digest(hard.identity()),
            query_shape_digest=latest.get('query_shape_digest'), elapsed_seconds=elapsed,
            retries=self.reads.retries-before['retries'], recoveries=self.reads.recoveries-before['recoveries'],
            connection_state=latest.get('connection_state', 'UNKNOWN'),
            corpus_identity='NO_IDENTITY_MISMATCH_OBSERVED; NEXT_LANE_REQUIRES_FRESH_GATE',
            upstream_parity_had_passed='NOT_DURABLY_ATTESTED', partial_materialization='UNKNOWN_UNSCORED',
            exact_probe_succeeded='SEE_IMMUTABLE_READ_PROBE_RECORDS',
            artifact_saved=False, provider_calls=0, next_action='DEFERRED_FOR_REVIEW',
            recommendation='Diagnose recorded execution failure; rerun only this unsaved lane after separate authorization.')
        self.save(f'overnight-deferred-{snapshot["id"]:02d}-{mf.lane.value}-{self.session}', event, immutable=True)
        self.deferred[snapshot['id'], mf.lane.value] = event
        self.save('overnight-deferred-lanes', dict(identity_hash=self.identity_hash,
            lanes=self.deferred_index(), provider_calls=0))
        self.event('LANE_DEFERRED', case=snapshot['id'], lane=mf.lane.value, failure=safe)
        self.aggregate()

    def run(self):
        started = perf_counter(); failure = None
        with bounded_database_io(), provider_free():
            try:
                self.setup()
                for snapshot, hard in self.common:
                    for mf in self.manifests:
                        key = snapshot['id'], mf.lane.value
                        if key in self.rows or key in self.deferred:
                            continue
                        require(sha256(Path(__file__).read_bytes()).hexdigest() == self.wrapper_hash,
                                'Q1_EXECUTION_CONTROLLER_CHANGED')
                        self.attempt_ordinal = 1 + sum(1 for p in self.output.glob('*attempt-*.json')
                            if (lambda v: (v.get('case'), v.get('lane')) == key)(read_bounded(p)))
                        before = self.reads.summary(); lane_start = perf_counter()
                        try:
                            # Inherited original Q1 lane body, including all
                            # replay, original-control, upstream and scope gates.
                            self.evaluate_lane(snapshot, hard, mf)
                        except Exception as exc:
                            if not execution_only(exc):
                                raise
                            p = self.output / (self.case_name(snapshot['id'], mf) + '.json')
                            pp = self.output / f'packing-{snapshot["id"]:02d}-{mf.lane.value}.json'
                            if p.exists() and pp.exists():
                                self.rows[key] = self.validate_q1_record(snapshot['id'], mf,
                                    read_bounded(p), read_bounded(pp), snapshot, hard)
                                self.pair(snapshot['id'])
                                self.event('SAVED_LANE_EXECUTION_CLEANUP_WARNING', case=key[0], lane=key[1],
                                           failure=safe_error(exc))
                            elif p.exists() or pp.exists():
                                raise CanaryError('Q1_PARTIAL_SAVED_ARTIFACT_REQUIRES_REVIEW') from None
                            else:
                                self.record_failure(snapshot, hard, mf, exc, before, perf_counter()-lane_start)
                        finally:
                            after = self.reads.summary()
                            self.save(f'overnight-read-summary-{snapshot["id"]:02d}-{mf.lane.value}-{self.session}',
                                dict(case=key[0], lane=key[1],
                                     counters={k:after[k]-before[k] for k in before},
                                     successful=key in self.rows, provider_calls=0), immutable=True)
                        self.aggregate()
                        if key in self.rows:
                            self.attest_saved_lane(snapshot['id'], mf)
                            self.event('LANE_COMPLETE', case=key[0], lane=key[1],
                                       successful_pairs=self.completed(), successful_lanes=len(self.rows))
                self.verify_phase_p()
                self.load_q1()
            except BaseException as exc:
                failure = safe_error(exc)
                self.event('OVERNIGHT_HARD_STOP', failure=failure)
            finally:
                for obj in (self.lock, self.db):
                    if obj is not None:
                        try:
                            obj.close()
                        except BaseException as exc:
                            self.cleanup_errors.append(safe_error(exc))
                for key in tuple(self.env):
                    if key.startswith('CANARY_'):
                        self.env.pop(key, None)
                outcome = dict(self.result, failure=failure, cleanup_errors=self.cleanup_errors,
                    successful_lanes=len(self.rows) if not self.preflight else 0,
                    successful_pairs=self.completed() if not self.preflight else 0,
                    deferred_lanes=len(self.deferred), provider_calls=0,
                    elapsed_seconds=perf_counter()-started,
                    status='HARD_STOP' if failure else 'PARTIAL_DEFERRED' if self.deferred else 'COMPLETE')
                self.save('overnight-terminal-' + self.session, outcome, immutable=True)
                emit(outcome)
        return outcome
