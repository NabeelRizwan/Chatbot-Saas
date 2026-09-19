"""Bounded, read-only case-72 diagnosis; never reset or consume a retry ledger.

This is not a measured lane replay. It reconstructs the frozen request ordering
and probes those atom reads on fresh connections. Historical missing binds are
not fabricated from a successful diagnostic.
"""
import json
from pathlib import Path
from time import monotonic, time

from sqlalchemy import event
from sqlalchemy.engine import Engine

from services.canary_contracts import CanaryError, Lane
from services.canary_retrieval import normalize, typed_rrf, reserve_witnesses
from services.canary_representation import exact_input_hash
from scripts.canary_bounded_output import emit
from scripts.canary_evaluation_resume import EvaluationRunner, require, frozen_files
from scripts.canary_evaluation_transport import safe_error, transient_transport
from scripts.canary_session_diagnostics import SessionWindow, EvidenceTelemetry


class Case72Diagnostic(EvaluationRunner):
    def __init__(self, *args, session_start, **kwargs):
        super().__init__(*args, **kwargs)
        self.window = SessionWindow(session_start)
        self.telemetry = None
        self.diagnostic_failure = None
        self.probes = 0
        self.result.update(session_start_monotonic=session_start,
                           case72_new_execution_authorized=False,
                           case72_new_execution_used=False, diagnostic_only=True)

    def checkpoint(self):
        # Stop starting SQL at shutdown preparation, earlier than the hard 24m
        # bound. The current operation still has its unchanged 30s watchdog.
        if self.window.shutdown_ready:
            raise CanaryError('SESSION_USAGE_WINDOW_ENDED')
        self.window.require_database()

    def before_sql(self, *args):
        # Session teardown may release a healthy owned advisory lock after the
        # work boundary. No other SQL gets this exemption.
        if len(args) > 2 and str(args[2]).startswith('SELECT pg_advisory_unlock('):
            return
        self.checkpoint()

    def setup(self):
        event.listen(Engine, 'before_cursor_execute', self.before_sql)
        try:
            super().setup()
        except BaseException:
            self.detach()
            raise

    def write_operation(self, record):
        self.save('case72-operation-'+self.session, record)
        if record.get('result_category') == 'DATABASE_ERROR':
            self.save('case72-operation-failure-'+self.session, record)

    def detach(self):
        # Diagnostic cleanup never replaces an in-flight primary error.
        try:
            if self.telemetry is not None:
                self.telemetry.close()
                self.telemetry = None
        except BaseException as exc:
            self.cleanup_errors.append(safe_error(exc))
        try:
            if event.contains(Engine, 'before_cursor_execute', self.before_sql):
                event.remove(Engine, 'before_cursor_execute', self.before_sql)
        except BaseException as exc:
            self.cleanup_errors.append(safe_error(exc))

    def observed_atom_failure(self, route, atom):
        last = self.telemetry.latest or {}
        scope = last.get('source_scope', {})
        return (last.get('result_category') == 'DATABASE_ERROR'
                and scope.get('document_id') == route.source.revision.source.document_id
                and scope.get('atom_id') == atom)

    def authorized_execution(self, snapshot, hard, mf):
        self.checkpoint()
        require(bool(self.diagnostic_failure and self.diagnostic_failure.get('fresh_read_succeeded')
                     and self.diagnostic_failure.get('atom')
                     and self.diagnostic_failure.get('manifest') == mf.canonical_hash()
                     and self.diagnostic_failure.get('generation') == mf.generation),
                'CASE72_FRESH_ATOM_PROOF_REQUIRED')
        require(frozen_files(self.root) == self.code, 'FROZEN_RETRIEVAL_IMPLEMENTATION_CHANGED')
        with self.exclusive():
            self.identity_gate()
        name = 'CASE72_TRANSPORT_DIAGNOSTIC_RETRY_AUTH_20260919'
        require(not (self.folder/(name+'.json')).exists(), 'CASE72_NEW_ATTEMPT_ALREADY_CONSUMED')
        self.save(name, dict(authorization=name, session=self.session,
            identity_hash=self.identity_hash, manifest=mf.canonical_hash(), generation=mf.generation,
            snapshot_hash=snapshot['snapshot_hash'], hard_scope=hard.identity(),
            query_receipt_hash=self.queries[exact_input_hash(snapshot['query'])].vector_hash,
            diagnostic_failure=self.diagnostic_failure, attempt_consumed=True,
            historical_retry_ledger_unchanged=True, provider_calls=0), immutable=True)
        self.result.update(case72_new_execution_used=True, case72_new_execution_authorized=True)
        self.telemetry.set_context(72, mf.lane.value, mf.canonical_hash(), mf.generation, 1)
        # Historical retry file remains present, so the parent cannot retry this
        # new attempt if it fails. A successful result uses normal persistence.
        self.evaluate_lane(snapshot, hard, mf)
        for following, scope in self.common:
            if following['id'] <= 72:
                continue
            # Conservatively reserve the measured slow paired-lane time and a
            # shutdown minute; never start a pair that cannot reasonably fit.
            if self.window.elapsed + 660 >= 23 * 60:
                raise CanaryError('SESSION_USAGE_WINDOW_ENDED')
            for lane_manifest in sorted(self.manifests, key=lambda v:v.lane.value):
                self.checkpoint()
                self.telemetry.set_context(following['id'], lane_manifest.lane.value,
                    lane_manifest.canonical_hash(), lane_manifest.generation)
                self.evaluate_lane(following, scope, lane_manifest)

    def probe(self, mf, hard, route, atom):
        self.checkpoint()
        self.telemetry.latest = None
        # Each probe owns a brand-new NullPool connection; repository.evidence
        # still checks the exact route, source lease, atom and payload digest.
        with self.exclusive():
            self.identity_gate()
            with self.repository() as repo:
                return repo.evidence(mf, hard, route, atom, now=int(time()))

    def evaluate(self):
        snapshot, hard = next(v for v in self.common if v[0]['id'] == 72)
        mf = next(v for v in self.manifests if v.lane == Lane.STRUCTURAL_CANARY)
        require((72, Lane.LEGACY_CONTROL.value) in self.rows and
                (72, mf.lane.value) not in self.rows, 'CASE72_RESUME_MISMATCH')
        self.current = dict(case=72, lane=mf.lane.value)
        self.telemetry = EvidenceTelemetry(self.db.engine, self.write_operation, window=self.window)
        self.telemetry.set_context(case_id=72, lane=mf.lane.value,
                                   manifest_hash=mf.canonical_hash(), generation=mf.generation)
        try:
            with self.exclusive():
                self.identity_gate()
                with self.repository() as repo:
                    qr = self.queries[exact_input_hash(snapshot['query'])]
                    dense = repo.dense(mf, hard, qr.vector, now=int(time()))
                    lexical = repo.fts(mf, hard, snapshot['query'], now=int(time())).hits
                    fused = typed_rrf(normalize(dense, mf, mf.effective(hard)),
                                      normalize(lexical, mf, mf.effective(hard)), mf.policy)
                    witnesses = reserve_witnesses(lexical, mf.policy)
                    requests = [(h.route, h.evidence_key) for h in witnesses]
                    for row in fused[:mf.policy.evidence_units]:
                        self.checkpoint()
                        ids = repo.children(mf, hard, row['route'], now=int(time()))
                        require(len(ids) <= 32, 'MATERIALIZATION_FANOUT_BOUND')
                        requests.extend((row['route'], key) for key in ids)
            emit(dict(stage='DIAGNOSTIC_ATOM_REQUESTS_READY', case=72,
                      request_count=len(requests), provider_calls=0))
            seen, used, units = set(), 0, 0
            for route, atom in requests:
                key = (route.source, atom)
                if key in seen:
                    continue
                seen.add(key)
                if units >= mf.policy.evidence_units:
                    continue
                try:
                    value = self.probe(mf, hard, route, atom)
                except Exception as exc:
                    if not self.observed_atom_failure(route, atom):
                        raise
                    self.diagnostic_failure = dict(document=route.source.revision.source.document_id,
                        atom=atom, manifest=mf.canonical_hash(), generation=mf.generation,
                        failure=safe_error(exc), historically_captured=False)
                    self.save('case72-diagnostic-failure-'+self.session, self.diagnostic_failure)
                    if transient_transport(exc):
                        # One exact fresh read is diagnosis, not a new measured
                        # retrieval execution and never changes the old ledger.
                        try:
                            self.probe(mf, hard, route, atom)
                        except Exception as second:
                            self.diagnostic_failure['fresh_read_failure'] = safe_error(second)
                        else:
                            self.diagnostic_failure['fresh_read_succeeded'] = True
                        self.save('case72-diagnostic-failure-'+self.session, self.diagnostic_failure)
                        if self.diagnostic_failure.get('fresh_read_succeeded'):
                            self.authorized_execution(snapshot, hard, mf)
                            return
                    raise
                self.probes += 1
                size = len(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode())
                if used + size <= mf.policy.evidence_bytes:
                    used += size
                    units += 1
                self.save('case72-diagnostic-progress-'+self.session,
                          dict(case=72, fresh_atom_reads=self.probes, accepted_units=units,
                               used_bytes=used, historical_atom_identified=False, provider_calls=0))
            self.result.update(diagnostic_result='FROZEN_REQUEST_READS_PASS_HISTORICAL_ATOM_UNKNOWN',
                               fresh_atom_reads=self.probes)
            # Successful probes cannot manufacture the historical missing bind.
            raise CanaryError('HISTORICAL_FAILED_ATOM_NOT_RECOVERABLE')
        finally:
            self.detach()

    def run(self):
        code = super().run()
        self.detach()
        try:
            self.result.update(session_elapsed_seconds=self.window.elapsed,
                fresh_atom_reads=self.probes, session_start_monotonic=self.window.started_monotonic,
                saved_lane_count=len(list(self.folder.glob('case-*.json'))))
            if (self.result.get('primary_error') or {}).get('guard') == 'SESSION_USAGE_WINDOW_ENDED':
                self.result.update(status='SESSION_USAGE_WINDOW_ENDED', phase_decision='DEFERRED')
            self.save('case72-bounded-session-'+self.session, self.result)
            emit(self.result)
        except BaseException as exc:
            self.cleanup_errors.append(safe_error(exc))
            emit(dict(session=self.session, terminal_supplement_failure=safe_error(exc), provider_calls=0))
        return code
