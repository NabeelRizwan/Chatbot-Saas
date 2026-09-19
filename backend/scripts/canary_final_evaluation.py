"""Explicit final measured continuation; no overall timer or retrieval changes."""
import argparse
from hashlib import sha256
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from time import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.canary_contracts import CanaryError, Lane
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_evaluation_resume import EvaluationRunner, require, read_bounded
from scripts.canary_evaluation_transport import safe_error, CleanupOnlyFailure
from scripts.canary_measured_telemetry import MeasuredEvidenceTelemetry
from scripts.canary_bounded_output import emit

AUTHORIZATION = 'CASE72_STRUCTURAL_FINAL_MEASURED_RETRY_20260919'
WRAPPERS = ('canary_final_evaluation.py', 'canary_measured_telemetry.py', 'canary_session_diagnostics.py')


def wrapper_hashes(root):
    return {name: sha256((root/'backend/scripts'/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name in WRAPPERS}


class FinalEvaluation(EvaluationRunner):
    def __init__(self, *args, final_authorization, diagnostic_checkpoint, resume_paused_session=None, **kwargs):
        require(final_authorization == AUTHORIZATION, 'FINAL_MEASURED_AUTHORIZATION_REQUIRED')
        require(bool(re.fullmatch('[a-f0-9]{40}', diagnostic_checkpoint or '')), 'DIAGNOSTIC_CHECKPOINT_REQUIRED')
        super().__init__(*args, **kwargs)
        self.diagnostic_checkpoint = diagnostic_checkpoint
        require(resume_paused_session is None or bool(re.fullmatch('[a-f0-9]{32}', resume_paused_session)),
                'INVALID_PAUSED_SESSION_REFERENCE')
        self.resume_paused_session = resume_paused_session
        self.telemetry = None
        self.result.update(final_authorization=AUTHORIZATION, diagnostic_checkpoint=diagnostic_checkpoint)

    def admit_execution(self, admission):
        # The original immutable admission still pins every retrieval/config/GOLD
        # file. Additionally pin the audited validation helper to its checkpoint.
        path = 'backend/scripts/canary_evaluation_validation.py'
        original = subprocess.check_output(['git', 'show', self.diagnostic_checkpoint+':'+path],
            cwd=self.root, stderr=subprocess.DEVNULL)
        require(sha256(original.replace(b'\r\n', b'\n')).hexdigest() == admission['frozen_files'][path],
                'AUDITED_VALIDATION_IMPLEMENTATION_CHANGED')
        super().admit_execution(admission)
        self.wrapper_code = wrapper_hashes(self.root)
        self.save('evaluation-final-admission-'+digest(dict(code=self.code, wrappers=self.wrapper_code)),
            dict(authorization=AUTHORIZATION, diagnostic_checkpoint=self.diagnostic_checkpoint,
                 admission=admission, wrappers=self.wrapper_code), immutable=True)

    def setup(self):
        super().setup()
        self.telemetry = MeasuredEvidenceTelemetry(self.db.engine, self.write_operation, session=self.session)

    def write_operation(self, record):
        self.save(f"measured-{self.session}-{record['operation_ordinal']:05d}-{record['phase']}",
                  record, immutable=True)

    def ensure_lease(self):
        if self.retained_until > int(time()) + 3600:
            return
        prior = [read_bounded(p) for p in self.folder.glob('evaluation-final-lease-*.json')]
        require(not prior, 'FINAL_AUTHORIZED_LEASE_ALREADY_CONSUMED')
        old = self.retained_until
        # Parent performs complete source/vector/query/ownership checks, CAS and
        # its original write-ahead audit. This adds the explicit user reference.
        self.save(f'evaluation-final-lease-{old}', dict(old_retained_until=old,
            new_retained_until=old+86400, namespace=self.namespace, run=self.run_id,
            resume_identity=self.identity_hash, manifests=[m.canonical_hash() for m in self.manifests],
            source_snapshot_digest=self.validation_proof['checksum'],
            authorization_reference=AUTHORIZATION, timestamp=int(time()),
            reason='ACTIVE_90_CASE_EVALUATION'), immutable=True)
        super().ensure_lease()

    def attempt_name(self, case, lane, attempt):
        return f'{AUTHORIZATION}-{case:02d}-{lane}-attempt-{attempt+1}'

    def paused_attempt_name(self, original_name, snapshot, hard, mf, attempt):
        """One explicit user-resume of an interrupted, unsaved initial attempt.

        This never changes old ledgers or authorizes replay of a transport failure.
        The normal one-transport-retry policy still applies to the resumed lane.
        """
        if self.resume_paused_session is None:
            return original_name
        pause_path = self.folder/f'evaluation-session-{self.resume_paused_session}.json'
        pause = read_bounded(pause_path)
        lane = dict(case=snapshot['id'], lane=mf.lane.value)
        if pause.get('current_lane') != lane:
            return original_name
        require(snapshot['id'] >= 73 and pause.get('status') == 'PAUSED_BY_USER'
                and pause.get('pause_reason') == 'USER_REQUESTED_PC_RESTART'
                and pause.get('process_stopped') is True and pause.get('primary_error') is None
                and pause.get('session') == self.resume_paused_session
                and pause.get('identity_hash') == self.identity_hash
                and pause.get('next_resumable_lane') == lane and pause.get('provider_calls') == 0,
                'USER_PAUSED_RESUME_REFUSED')
        old_path = self.folder/(self.attempt_name(snapshot['id'], mf.lane.value, 0)+'.json')
        old = read_bounded(old_path)
        require(old['session'] == self.resume_paused_session and old['attempt_ordinal'] == 1
                and old['identity_hash'] == self.identity_hash and old['case'] == snapshot['id']
                and old['lane'] == mf.lane.value and old['manifest'] == mf.canonical_hash()
                and old['generation'] == mf.generation and old['snapshot_hash'] == snapshot['snapshot_hash']
                and old['hard_scope'] == hard.identity()
                and old['query_vector_hash'] == self.queries[exact_input_hash(snapshot['query'])].vector_hash
                and not (self.folder/(self.case_name(snapshot['id'], mf)+'.json')).exists(),
                'USER_PAUSED_ATTEMPT_IDENTITY_MISMATCH')
        if attempt == 0:
            require(not (self.folder/f"evaluation-retry-{snapshot['id']:02d}-{mf.lane.value}.json").exists(),
                    'TRANSPORT_RETRY_CANNOT_RESET_ON_USER_RESUME')
        audit = dict(paused_session=self.resume_paused_session, pause_sha256=sha256(pause_path.read_bytes()).hexdigest(),
            original_attempt_sha256=sha256(old_path.read_bytes()).hexdigest(), identity_hash=self.identity_hash,
            case=snapshot['id'], lane=mf.lane.value, authorization='USER_CONTINUE_AFTER_PC_RESTART',
            session=self.session)
        self.save('evaluation-user-resume-'+self.resume_paused_session, audit, immutable=True)
        return original_name+'-resume-'+self.resume_paused_session

    def before_lane_attempt(self, snapshot, hard, mf, attempt):
        require(type(attempt) is int and attempt in (0, 1), 'MEASURED_ATTEMPT_BOUND')
        require(wrapper_hashes(self.root) == self.wrapper_code, 'FROZEN_EXECUTION_WRAPPER_CHANGED')
        case, lane = snapshot['id'], mf.lane.value
        require(case >= 72, 'HISTORICAL_LANE_REEXECUTION_REFUSED')
        if case == 72:
            require(mf.lane == Lane.STRUCTURAL_CANARY, 'CASE72_LEGACY_REEXECUTION_REFUSED')
            legacy = next(m for m in self.manifests if m.lane == Lane.LEGACY_CONTROL)
            self.validate(read_bounded(self.folder/(self.case_name(case, legacy)+'.json')), snapshot, hard, legacy)
            if attempt:
                proof = read_bounded(self.folder/(AUTHORIZATION+'-fresh-atom-proof.json'))
                require(proof['identity_hash'] == self.identity_hash and proof['manifest'] == mf.canonical_hash()
                        and proof['session'] == self.session and proof['payload_hash_validation'] == 'PASS'
                        and proof['result'] == 'MEASURED_LANE_TRANSPORT_FAILURE_NOT_REPRODUCED_ON_FRESH_ATOM',
                        'EXACT_ATOM_RETRY_PROOF_REQUIRED')
        name = self.attempt_name(case, lane, attempt)
        name = self.paused_attempt_name(name, snapshot, hard, mf, attempt)
        require(not (self.folder/(name+'.json')).exists(), 'MEASURED_ATTEMPT_ALREADY_CONSUMED')
        self.save(name, dict(authorization=AUTHORIZATION, session=self.session, identity_hash=self.identity_hash,
            case=case, lane=lane, attempt_ordinal=attempt+1, manifest=mf.canonical_hash(), generation=mf.generation,
            snapshot_hash=snapshot['snapshot_hash'], hard_scope=hard.identity(),
            query_vector_hash=self.queries[exact_input_hash(snapshot['query'])].vector_hash,
            timestamp=int(time()), provider_calls=0), immutable=True)
        self.telemetry.set_context(case, lane, mf.canonical_hash(), mf.generation, attempt)

    def lane_telemetry_complete(self, trace):
        summary = self.telemetry.summary()
        summary.update(status='COMPLETE', evidence_units=len(trace['materialized']['units']),
            evidence_bytes=trace['materialized']['bytes'], max_fanout=trace['materialized']['max_fanout'],
            exclusions=len(trace['materialized']['exclusions']), budget_status=trace['final_status'])
        require(not summary['persistence_errors'], 'TELEMETRY_PERSISTENCE_FAILURE')
        self.save(f"measured-summary-{self.session}-{summary['case_id']:02d}-{summary['lane']}-{summary['retry_ordinal']}",
                  summary, immutable=True)

    def authorize_lane_retry(self, snapshot, hard, mf, exc, retry_path):
        summary = dict(self.telemetry.summary(), status='FAILED', failure=safe_error(exc))
        self.save(f"measured-summary-{self.session}-{snapshot['id']:02d}-{mf.lane.value}-failed", summary, immutable=True)
        if snapshot['id'] != 72 or mf.lane != Lane.STRUCTURAL_CANARY:
            return super().authorize_lane_retry(snapshot, hard, mf, exc, retry_path)
        failed = self.telemetry.failed
        require(bool(failed and failed['record']['statement_started']
                     and failed['record']['result_category'] in ('DATABASE_TIMEOUT', 'TRANSPORT_FAILURE')),
                'EXACT_FAILED_ATOM_TELEMETRY_REQUIRED')
        self.save(AUTHORIZATION+'-failure', failed['record'], immutable=True)
        self.telemetry.context['purpose'] = 'EXACT_ATOM_PROBE'
        read_started = False
        try:
            with self.exclusive():
                self.identity_gate()
                with self.repository() as repo:
                    read_started = True
                    repo.evidence(mf, hard, failed['route'], failed['key'], now=int(time()))
            require(self.telemetry.latest['payload_hash_validation'] == 'PASS'
                    and self.telemetry.latest['source_scope'] == failed['record']['source_scope'],
                    'EXACT_ATOM_HASH_REQUIRED')
        except CleanupOnlyFailure:
            raise
        except Exception as probe_error:
            category = ('EXACT_ATOM_READ_REPRODUCIBLE_FAILURE' if read_started
                        else 'EXACT_ATOM_PROBE_PREFLIGHT_FAILURE')
            self.save(AUTHORIZATION+'-fresh-atom-proof', dict(identity_hash=self.identity_hash,
                result=category, failure=safe_error(probe_error)), immutable=True)
            raise CanaryError(category) from None
        proof = dict(identity_hash=self.identity_hash, manifest=mf.canonical_hash(), session=self.session,
            source_scope=failed['record']['source_scope'], payload_hash_validation='PASS',
            result='MEASURED_LANE_TRANSPORT_FAILURE_NOT_REPRODUCED_ON_FRESH_ATOM', timestamp=int(time()))
        self.save(AUTHORIZATION+'-fresh-atom-proof', proof, immutable=True)
        # Never modify the exhausted historical ledger.
        self.transport_retries += 1
        emit(dict(stage='FINAL_CASE72_TRANSPORT_RETRY_AUTHORIZED', **proof))
        return True


def main():
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('namespace', 'run-id', 'identity-hash', 'execution-checkpoint',
                 'diagnostic-checkpoint', 'final-authorization'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--resume-paused-session')
    args = parser.parse_args()
    try:
        return FinalEvaluation(Path(__file__).resolve().parents[2], os.environ,
            namespace=args.namespace, run_id=args.run_id, identity_hash=args.identity_hash,
            execution_checkpoint=args.execution_checkpoint, diagnostic_checkpoint=args.diagnostic_checkpoint,
            final_authorization=args.final_authorization, resume_paused_session=args.resume_paused_session,
            renew_authorized=True).run()
    except Exception as exc:
        emit(dict(decision='C', failure=safe_error(exc), provider_calls=0))
        return 1
    finally:
        for name in tuple(os.environ):
            if name.startswith('CANARY_'):
                os.environ.pop(name, None)


if __name__ == '__main__':
    raise SystemExit(main())
