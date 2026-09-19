"""Separate case-82 authorization after diagnosis; existing split transport only."""
from hashlib import sha256
from time import perf_counter, time

from services.canary_contracts import Lane
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_bounded_output import emit
from scripts.canary_evaluation_resume import require, read_bounded
from scripts.canary_final_evaluation import FinalEvaluation, wrapper_hashes
from scripts.canary_post_atom_completion import PostAtomCompletion, completion_hashes, AUTHORIZATION as PRIOR_AUTHORIZATION
from scripts.canary_split_evidence import split_atom_row

AUTHORIZATION = 'CASE82_STRUCTURAL_POST_DIAGNOSIS_20260919'


def case82_hashes(root):
    return dict(completion_hashes(root), **{name: sha256((root/'backend/scripts'/name)
        .read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        for name in ('canary_case82_completion.py', 'canary_payload_diagnostic.py')})


class Case82Completion(PostAtomCompletion):
    def __init__(self, *args, final_authorization, **kwargs):
        require(final_authorization == AUTHORIZATION, 'CASE82_AUTHORIZATION_REQUIRED')
        super().__init__(*args, final_authorization=PRIOR_AUTHORIZATION, **kwargs)
        self.result.update(final_authorization=AUTHORIZATION, transport_changed=False)

    def admit_execution(self, admission):
        # Do not replace the old case-75 admission or exhausted case-82 ledger.
        FinalEvaluation.admit_execution(self, admission)
        proof = read_bounded(self.diagnosis_path)
        require(proof['identity_hash'] == self.identity_hash and proof['case'] == 82
                and proof['lane'] == Lane.STRUCTURAL_CANARY.value and proof['provider_calls'] == 0
                and proof['diagnosis_complete'] is True and proof['transport_changed'] is False
                and proof['transport_repair'] == 'EXACT_SPLIT_ROW_V1'
                and proof['root_cause'] == 'ROOT_CAUSE_UNKNOWN', 'CASE82_DIAGNOSIS_REQUIRED')
        for name, expected in proof['diagnostic_artifact_hashes'].items():
            require('/' not in name and '\\' not in name, 'DIAGNOSTIC_ARTIFACT_NAME_REQUIRED')
            require(sha256((self.folder/name).read_bytes()).hexdigest() == expected,
                    'DIAGNOSTIC_EVIDENCE_CHANGED')
        require(len(proof['diagnostic_artifact_hashes']) == 18, 'COMPLETE_PAYLOAD_DIAGNOSTIC_REQUIRED')
        require(len(proof['equivalence_scopes']) == 5
                and len({digest(v) for v in proof['equivalence_scopes']}) == 5
                and proof['equivalence_scopes'][0] == proof['source_scope'], 'TARGET_AND_FOUR_PEER_PROOFS_REQUIRED')
        self.diagnosis = proof
        self.diagnosis_sha = sha256(self.diagnosis_path.read_bytes()).hexdigest()
        self.completion_code = case82_hashes(self.root)
        self.save('case82-admission-'+digest(self.completion_code), dict(
            authorization=AUTHORIZATION, wrappers=self.completion_code, diagnosis_sha256=self.diagnosis_sha,
            identity_hash=self.identity_hash, transport_repair='EXACT_SPLIT_ROW_V1', transport_changed=False), immutable=True)

    def setup(self):
        # Parent supplies unchanged preflight full-row hashes and split repository.
        FinalEvaluation.setup(self)
        mf = next(m for m in self.manifests if m.lane == Lane.STRUCTURAL_CANARY)
        _, hard = next(v for v in self.common if v[0]['id'] == 82)
        require(len(self.split_expected) == sum(len(pin.atoms) for pin in mf.documents),
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
            self.save(f'case82-row-proof-{self.session}-{len(outcomes)}', outcomes[-1], immutable=True)
        require(len(outcomes) == 5, 'TARGET_AND_FOUR_PEER_PROOFS_REQUIRED')
        self.split_transport_proof = dict(result='PASS', rows=outcomes, old_rows_validated=len(self.split_expected),
            session=self.session, provider_calls=0, transport='EXACT_SPLIT_ROW_V1', transport_changed=False)
        self.save('case82-row-proof-'+self.session, self.split_transport_proof, immutable=True)
        emit(dict(stage='CASE82_FIVE_ROW_PROOF_PASS', rows=5, provider_calls=0, transport_changed=False))

    def attempt_name(self, case, lane, attempt):
        return f'{AUTHORIZATION}-{case:02d}-{lane}-attempt-{attempt+1}'

    def proof_name(self, case, lane):
        return f'{AUTHORIZATION}-{case:02d}-{lane}-fresh-scope-proof'

    def before_lane_attempt(self, snapshot, hard, mf, attempt):
        require(type(attempt) is int and attempt in (0, 1), 'MEASURED_ATTEMPT_BOUND')
        require(wrapper_hashes(self.root) == self.wrapper_code
                and case82_hashes(self.root) == self.completion_code, 'FROZEN_EXECUTION_WRAPPER_CHANGED')
        require(sha256(self.diagnosis_path.read_bytes()).hexdigest() == self.diagnosis_sha,
                'DIAGNOSTIC_EVIDENCE_CHANGED')
        case, lane = snapshot['id'], mf.lane.value
        require(self.split_transport_proof and self.split_transport_proof['result'] == 'PASS',
                'REAL_SPLIT_ROW_EQUIVALENCE_REQUIRED')
        require(82 <= case <= 90, 'HISTORICAL_LANE_REEXECUTION_REFUSED')
        require(not (self.folder/(self.case_name(case, mf)+'.json')).exists(), 'SAVED_LANE_REEXECUTION_REFUSED')
        if case == 82:
            require(mf.lane == Lane.STRUCTURAL_CANARY, 'CASE82_LEGACY_REEXECUTION_REFUSED')
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
        if snapshot['id'] == 82 and self.telemetry.failed:
            require(self.telemetry.failed['record']['source_scope'] != self.diagnosis['source_scope'],
                    'CASE82_SAME_ATOM_FAILED_AGAIN_STOP')
        return super().authorize_lane_retry(snapshot, hard, mf, exc, retry_path)
