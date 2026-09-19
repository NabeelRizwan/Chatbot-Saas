"""New explicit post-diagnosis authorization; frozen retrieval, bounded retries."""
from contextlib import contextmanager
from hashlib import sha256
from time import time, perf_counter

from services.canary_contracts import Lane
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from database import canary_schema as s
from scripts.canary_bounded_output import emit
from scripts.canary_evaluation_resume import require, read_bounded
from scripts.canary_evaluation_transport import safe_error
from scripts.canary_final_evaluation import FinalEvaluation, AUTHORIZATION as PRIOR_AUTHORIZATION
from scripts.canary_split_evidence import SplitEvidenceRepository, split_atom_row

AUTHORIZATION = 'CASE75_STRUCTURAL_POST_ATOM_DIAGNOSIS_20260919'


def completion_hashes(root):
    return {name: sha256((root/'backend/scripts'/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name in ('canary_post_atom_completion.py', 'canary_exact_atom_diagnostic.py', 'canary_split_evidence.py')}


class PostAtomCompletion(FinalEvaluation):
    def __init__(self, *args, final_authorization, diagnosis_artifact, **kwargs):
        require(final_authorization == AUTHORIZATION, 'POST_ATOM_AUTHORIZATION_REQUIRED')
        super().__init__(*args, final_authorization=PRIOR_AUTHORIZATION, **kwargs)
        require('/' not in diagnosis_artifact and '\\' not in diagnosis_artifact,
                'DIAGNOSIS_ARTIFACT_NAME_REQUIRED')
        self.diagnosis_path = self.folder/diagnosis_artifact
        self.split_expected = {}
        self.split_transport_proof = None
        self.result.update(final_authorization=AUTHORIZATION, transport_repair='EXACT_SPLIT_ROW_V1')

    def admit_execution(self, admission):
        # Inherited admission retains every original frozen semantic identity.
        super().admit_execution(admission)
        proof = read_bounded(self.diagnosis_path)
        require(proof['identity_hash'] == self.identity_hash and proof['case'] == 75
                and proof['lane'] == Lane.STRUCTURAL_CANARY.value and proof['provider_calls'] == 0
                and proof['diagnosis_complete'] is True and proof['transport_repair'] == 'EXACT_SPLIT_ROW_V1'
                and proof['root_cause'] in ('EXACT_ATOM_QUERY_SERVER_EXECUTION_STALL', 'LOCK_WAIT',
                    'LARGE_TOAST_OR_PAYLOAD_READ_PATH', 'CLIENT_TRANSPORT_RESPONSE_STALL',
                    'QUERY_PLAN_SCOPE_INEFFICIENCY', 'CONNECTION_FAILURE', 'ROOT_CAUSE_UNKNOWN'),
                'POST_ATOM_DIAGNOSIS_REQUIRED')
        for name, expected in proof['diagnostic_artifact_hashes'].items():
            require('/' not in name and '\\' not in name, 'DIAGNOSTIC_ARTIFACT_NAME_REQUIRED')
            require(sha256((self.folder/name).read_bytes()).hexdigest() == expected,
                    'DIAGNOSTIC_EVIDENCE_CHANGED')
        require(len(proof['diagnostic_artifact_hashes']) >= 7, 'INCOMPLETE_ATOM_DIAGNOSTIC')
        require(len(proof['equivalence_scopes']) == 5
                and len({digest(v) for v in proof['equivalence_scopes']}) == 5
                and proof['equivalence_scopes'][0] == proof['source_scope'], 'TARGET_AND_FOUR_PEER_PROOFS_REQUIRED')
        self.diagnosis = proof
        self.diagnosis_sha = sha256(self.diagnosis_path.read_bytes()).hexdigest()
        self.completion_code = completion_hashes(self.root)
        self.save('post-atom-admission-'+digest(self.completion_code), dict(
            authorization=AUTHORIZATION, wrappers=self.completion_code,
            diagnosis_sha256=self.diagnosis_sha,
            identity_hash=self.identity_hash, transport_repair='EXACT_SPLIT_ROW_V1'), immutable=True)

    def validated_document(self, mf, pin, proof):
        data, checksum = super().validated_document(mf, pin, proof)
        if mf.lane == Lane.STRUCTURAL_CANARY:
            # These are the unchanged, fully validated OLD full-row reads.
            # Every measured split read must equal its corresponding row exactly.
            for row in data[s.atoms.name]:
                scope = {k: row[k] for k in (*s.DOC, 'atom_id')}
                self.split_expected[digest(scope)] = digest(row)
        return data, checksum

    @contextmanager
    def repository(self, *, inspection=False, writable=False):
        with super().repository(inspection=inspection, writable=writable) as original:
            yield SplitEvidenceRepository(original.conn, self.approval, authorization=self.authorization,
                lease_until=self.retained_until, identities=[mf.canonical_hash() for mf in self.manifests],
                inspection=inspection, observer=getattr(self, 'telemetry', None),
                expected_rows=self.split_expected)

    def setup(self):
        super().setup()
        mf = next(m for m in self.manifests if m.lane == Lane.STRUCTURAL_CANARY)
        _, hard = next(v for v in self.common if v[0]['id'] == 75)
        require(len(self.split_expected) == sum(len(pin.atoms)
                for mf in self.manifests if mf.lane == Lane.STRUCTURAL_CANARY for pin in mf.documents),
                'FULL_OLD_ATOM_ROW_INVENTORY_REQUIRED')
        outcomes = []
        for scope in self.diagnosis['equivalence_scopes']:
            started = perf_counter()
            with self.exclusive():
                self.identity_gate()
                with self.repository() as repo:
                    repo.read_gate(mf, hard, now=int(time()))
                    require(scope['manifest_hash'] == mf.canonical_hash()
                            and scope['document_id'] in mf.effective(hard), 'SPLIT_PROBE_SCOPE_REFUSED')
                    expected = self.split_expected.get(digest(scope))
                    require(expected is not None, 'VALIDATED_ATOM_ROW_REQUIRED')
                    row = split_atom_row(repo.conn, scope, expected_hash=expected)
                    outcomes.append(dict(scope_digest=digest(scope), canonical_row_hash=digest(row),
                        payload_hash=row['payload_hash'], result='EXACT_EQUAL', elapsed_ms=(perf_counter()-started)*1000))
            self.save(f'post-atom-split-proof-{self.session}-{len(outcomes)}', outcomes[-1], immutable=True)
        require(len(outcomes) == 5, 'TARGET_AND_FOUR_PEER_PROOFS_REQUIRED')
        self.split_transport_proof = dict(result='PASS', rows=outcomes, old_rows_validated=len(self.split_expected),
            session=self.session, provider_calls=0, transport='EXACT_SPLIT_ROW_V1')
        self.save('post-atom-split-proof-'+self.session, self.split_transport_proof, immutable=True)
        emit(dict(stage='EXACT_SPLIT_ROW_EQUIVALENCE_PASS', rows=len(outcomes),
                  old_rows_validated=len(self.split_expected), provider_calls=0))

    def attempt_name(self, case, lane, attempt):
        return f'{AUTHORIZATION}-{case:02d}-{lane}-attempt-{attempt+1}'

    def proof_name(self, case, lane):
        return f'{AUTHORIZATION}-{case:02d}-{lane}-fresh-scope-proof'

    def before_lane_attempt(self, snapshot, hard, mf, attempt):
        require(type(attempt) is int and attempt in (0, 1), 'MEASURED_ATTEMPT_BOUND')
        from scripts.canary_final_evaluation import wrapper_hashes
        require(wrapper_hashes(self.root) == self.wrapper_code
                and completion_hashes(self.root) == self.completion_code, 'FROZEN_EXECUTION_WRAPPER_CHANGED')
        require(sha256(self.diagnosis_path.read_bytes()).hexdigest() == self.diagnosis_sha,
                'DIAGNOSTIC_EVIDENCE_CHANGED')
        case, lane = snapshot['id'], mf.lane.value
        require(self.split_transport_proof and self.split_transport_proof['result'] == 'PASS',
                'REAL_SPLIT_ROW_EQUIVALENCE_REQUIRED')
        require(75 <= case <= 90, 'HISTORICAL_LANE_REEXECUTION_REFUSED')
        require(not (self.folder/(self.case_name(case, mf)+'.json')).exists(), 'SAVED_LANE_REEXECUTION_REFUSED')
        if case == 75:
            require(mf.lane == Lane.STRUCTURAL_CANARY, 'CASE75_LEGACY_REEXECUTION_REFUSED')
            legacy = next(m for m in self.manifests if m.lane == Lane.LEGACY_CONTROL)
            self.validate(read_bounded(self.folder/(self.case_name(case, legacy)+'.json')), snapshot, hard, legacy)
        if attempt:
            proof = read_bounded(self.folder/(self.proof_name(case, lane)+'.json'))
            require(proof['identity_hash'] == self.identity_hash and proof['session'] == self.session
                    and proof['case'] == case and proof['lane'] == lane
                    and proof['manifest'] == mf.canonical_hash() and proof['result'] == 'EXACT_FRESH_SCOPE_PASS',
                    'EXACT_FRESH_SCOPE_RETRY_PROOF_REQUIRED')
        name = self.attempt_name(case, lane, attempt)
        require(not (self.folder/(name+'.json')).exists(), 'MEASURED_ATTEMPT_ALREADY_CONSUMED')
        self.save(name, dict(authorization=AUTHORIZATION, session=self.session, identity_hash=self.identity_hash,
            case=case, lane=lane, attempt_ordinal=attempt+1, manifest=mf.canonical_hash(), generation=mf.generation,
            snapshot_hash=snapshot['snapshot_hash'], hard_scope=hard.identity(),
            query_vector_hash=self.queries[exact_input_hash(snapshot['query'])].vector_hash,
            timestamp=int(time()), provider_calls=0, transport_repair='EXACT_SPLIT_ROW_V1'), immutable=True)
        self.telemetry.set_context(case, lane, mf.canonical_hash(), mf.generation, attempt)

    def authorize_lane_retry(self, snapshot, hard, mf, exc, retry_path):
        summary = dict(self.telemetry.summary(), status='FAILED', failure=safe_error(exc))
        self.save(f"measured-summary-{self.session}-{snapshot['id']:02d}-{mf.lane.value}-failed", summary, immutable=True)
        failed = self.telemetry.failed
        require(bool(failed and failed['record']['statement_started']
                     and failed['record']['result_category'] in ('DATABASE_TIMEOUT', 'TRANSPORT_FAILURE')),
                'EXACT_FAILED_SCOPE_TELEMETRY_REQUIRED')
        if snapshot['id'] == 75:
            require(failed['record']['source_scope'] != self.diagnosis['source_scope'],
                    'CASE75_SAME_ATOM_FAILED_AGAIN_STOP')
        proof_name = self.proof_name(snapshot['id'], mf.lane.value)
        require(not (self.folder/(proof_name+'.json')).exists(), 'EXACT_SCOPE_RETRY_ALREADY_CONSUMED')
        self.telemetry.context['purpose'] = 'EXACT_SCOPE_PROBE'
        with self.exclusive():
            self.identity_gate()
            with self.repository() as repo:
                repo.evidence(mf, hard, failed['route'], failed['key'], now=int(time()))
            latest = self.telemetry.latest
            expected_hash = 'PASS' if mf.lane == Lane.STRUCTURAL_CANARY else 'NOT_PERFORMED_BY_LEGACY_METHOD'
            require(latest['source_scope'] == failed['record']['source_scope']
                    and latest['result_category'] == 'SUCCESS'
                    and latest['payload_hash_validation'] == expected_hash,
                    'EXACT_FRESH_SCOPE_PROOF_FAILED')
            self.identity_gate()
        proof = dict(identity_hash=self.identity_hash, session=self.session, case=snapshot['id'],
            lane=mf.lane.value, manifest=mf.canonical_hash(), source_scope=latest['source_scope'],
            result='EXACT_FRESH_SCOPE_PASS', timestamp=int(time()), provider_calls=0)
        self.save(proof_name, proof, immutable=True)
        self.transport_retries += 1
        emit(dict(stage='POST_ATOM_TRANSPORT_RETRY_AUTHORIZED', **proof))
        return True
