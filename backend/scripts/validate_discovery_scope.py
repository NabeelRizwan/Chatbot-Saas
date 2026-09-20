"""Q3 targeted read-only canary. Frozen vectors/SQL/RRF/Q1 packing; scope only.

Fresh output only. No lease extension, corpus writes, provider calls, or 90-case
retrieval. Full retained identity validation is inherited, not bypassed.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import time, perf_counter
from types import FunctionType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.canary_contracts import Lane
from services.canary_representation import exact_input_hash
from services.compact_evidence_pack import materialize_compact
from services.discovery_scope import preserve_discovery_scope
from scripts.canary_bounded_output import emit, vector_summary
from scripts.canary_evaluation_resume import (EvaluationRunner, require, read_bounded, provider_free, frozen_files)
from scripts.canary_evaluation_transport import bounded_database_io, safe_error
from scripts.canary_read_recovery import ReadTelemetry
from scripts.canary_real_evaluation import score_case, safe_trace
from scripts.replay_discovery_scope import load_contract
from scripts.run_compact_evidence_canary import CompactCanary, query_with_materializer, split_original
from scripts.run_compact_evidence_overnight import OvernightCanary


class ScopeCanary(CompactCanary):
    def __init__(self, root, env, *, accepted, scope_replay):
        require(env.get('CANARY_Q3_SCOPE_AUTHORIZED') == 'true', 'Q3_AUTHORIZATION_REQUIRED')
        self.accepted = accepted.resolve(); self.scope_replay = scope_replay.resolve()
        for folder in (self.accepted, self.scope_replay):
            require(folder.parent == root / '.codex_phase4q' and folder.is_dir(), 'Q3_LOCAL_INPUT_REQUIRED')
        lease = read_bounded(self.accepted / 'overnight-lease-committed.json')
        EvaluationRunner.__init__(self, root, env, namespace=lease['namespace'], run_id=lease['run'],
                                 identity_hash=lease['identity_hash'])
        self.offline = read_bounded(self.scope_replay / 'scope-replay.json')
        require(self.offline['status'] == 'PASS' and self.offline['cases'] == 90
                and self.offline['old_support_made_inaccessible'] == 0
                and self.offline['old_required_docs_made_inaccessible'] == 0, 'Q3_OFFLINE_GATE_REQUIRED')
        self.targets = tuple(self.offline['changed_scope_cases'])
        require(0 < len(self.targets) < 90 and len(set(self.targets)) == len(self.targets), 'Q3_TARGETED_ONLY')
        for path in self.scope_replay.glob('protected-*.json'):
            for name, expected in read_bounded(path).items():
                require(sha256((root / name).read_bytes()).hexdigest() == expected, 'Q3_SAVED_INPUT_CHANGED')
        self.output = self.scope_replay / ('live-' + self.session)
        self.output.mkdir(exist_ok=False)
        self.reads = ReadTelemetry(self.write_read)
        self.measured_scope = None; self.epochs = {}; self.split_expected = {}
        self.telemetry = None; self.preflight = True
        self.target_rows = []

    def aggregate(self):
        # Original full-suite results are inspected, never reaggregated/overwritten.
        return None

    def lease_chain(self, folder, identity_hash, original, retained):
        proxy = SimpleNamespace(folder=self.folder, identity_hash=self.identity_hash,
            namespace=self.namespace, run_id=self.run_id, output=self.accepted)
        OvernightCanary.combined_lease_chain(proxy, folder, identity_hash, original, retained)
        require(int(time()) < retained, 'Q3_RETAINED_READ_LEASE_EXPIRED')

    def admit_execution(self, admission):
        accepted = read_bounded(self.accepted / 'admission.json')
        require(admission == accepted['admission'], 'Q3_RETAINED_IDENTITY_CHANGED')
        self.q1_code = accepted['q1_code']
        require(all(sha256((self.root / p).read_bytes()).hexdigest() == h for p, h in self.q1_code.items()),
                'Q1_IMPLEMENTATION_CHANGED')
        self.q3_code = {p: sha256((self.root / p).read_bytes()).hexdigest() for p in (
            'backend/services/discovery_scope.py', 'backend/services/rag_planning.py',
            'backend/scripts/replay_discovery_scope.py', 'backend/scripts/validate_discovery_scope.py')}
        self.save('admission', dict(admission=admission, q1_code=self.q1_code, q3_code=self.q3_code,
            offline_sha256=sha256((self.scope_replay / 'scope-replay.json').read_bytes()).hexdigest(),
            targeted_cases=self.targets, provider_calls=0), immutable=True)

    def setup(self):
        original = EvaluationRunner.setup
        fn = FunctionType(original.__code__, dict(original.__globals__, verify_lease_chain=self.lease_chain),
                          original.__name__, original.__defaults__, original.__closure__)
        fn(self)
        require(self.reused == 180 and self.completed() == 90, 'COMPLETE_PHASE_P_REQUIRED')
        require(len(self.split_expected) == sum(len(p.atoms) for m in self.manifests
                if m.lane == Lane.STRUCTURAL_CANARY for p in m.documents), 'FULL_ATOM_VALIDATION_REQUIRED')
        committed = read_bounded(self.accepted / 'overnight-lease-committed.json')
        require(committed['validation_hash'] == self.validation_proof['checksum']
                and committed['query_inventory'] == self.validation_proof['query_inventory'],
                'Q3_FROZEN_SOURCE_VECTOR_CHANGED')
        emit(dict(stage='Q3_PREFLIGHT_PASS', targeted_cases=self.targets, provider_calls=0))

    def evaluate_target(self, snapshot, mf):
        self.ensure_lease()
        require(frozen_files(self.root) == self.code and all(sha256((self.root / p).read_bytes()).hexdigest() == h
                for p, h in {**self.q1_code, **self.q3_code}.items()), 'Q3_IMPLEMENTATION_CHANGED')
        case = snapshot['id']
        require(case in self.targets, 'UNCHANGED_CASE_RETRIEVAL_REFUSED')
        offline = read_bounded(self.scope_replay / f'case-{case:02d}.json')
        c = load_contract(snapshot['contract']); preserve_discovery_scope(c, snapshot['history'])
        hard = c.execution.hard_scope
        after = hard.intersect(c.execution.scope_decision.effective_document_ids)
        require(list(after) == offline['after'] and offline['contained'] and
                c.execution.retrieval_query == snapshot['query'], 'Q3_OFFLINE_LIVE_SCOPE_MISMATCH')
        # Preserve hard versions/source/profile/corpus exactly. Only the historical
        # semantic document intersection is removed by the proven runtime decision.
        require(list(mf.effective(hard)) == offline['after'], 'Q3_MANIFEST_SCOPE_MISMATCH')
        old = read_bounded(self.accepted / (self.case_name(case, mf) + '.json'))
        require(old['query'] == vector_summary(self.queries[exact_input_hash(snapshot['query'])]), 'Q3_QUERY_VECTOR_CHANGED')
        require(not (self.output / (self.case_name(case, mf) + '.json')).exists(), 'Q3_TARGET_ALREADY_SAVED')
        self.current = dict(case=case, lane=mf.lane.value)
        self.measured_scope = None
        with self.exclusive():
            self.identity_gate()
            self.measured_scope = (mf, hard)
            self.reads.context = dict(case=case, lane=mf.lane.value, manifest=mf.canonical_hash(),
                generation=mf.generation, organization_id=hard.organization_id, bot_id=hard.bot_id)
            self.save(f'attempt-{case:02d}', dict(**self.current, provider_calls=0, timestamp=int(time())), immutable=True)
            emit(dict(stage='Q3_TARGET_START', **self.current, before=offline['before'], after=after))
            measured = {}
            def selected(fused, witnesses, repo, manifest, scope, now):
                value = materialize_compact(fused, witnesses, repo, manifest, scope, now, reader=split_original)
                measured.update(bytes=value['bytes'], units=len(value['units']),
                    model_bytes_sha256=sha256(value['model_bytes']).hexdigest(),
                    byte_exclusions=sum(v['cap'] == 'BYTES' for v in value['exclusions']),
                    unit_exclusions=sum(v['cap'] == 'UNITS' for v in value['exclusions']))
                return value
            with self.repository() as repo:
                trace = query_with_materializer(selected)(repo, mf, hard, query=snapshot['query'],
                    query_vector=self.queries[exact_input_hash(snapshot['query'])].vector, now=int(time()))
            record = dict(case=case, lane=mf.lane.value, snapshot_hash=snapshot['snapshot_hash'],
                query=vector_summary(self.queries[exact_input_hash(snapshot['query'])]), trace=safe_trace(trace),
                outcome=score_case(trace, self.gold[case], mf.lane.value, mf.effective(hard), self.entry_atoms))
            self.validate(record, snapshot, hard, mf)
            self.save(self.case_name(case, mf), record, immutable=True)
            self.save(f'packing-{case:02d}', measured, immutable=True)
            self.target_rows.append(dict(case=case, before=offline['before'], after=after,
                before_metrics=old['outcome']['metrics'], after_metrics=record['outcome']['metrics'], packing=measured))
            emit(dict(stage='Q3_TARGET_COMPLETE', case=case, metrics=record['outcome']['metrics'], packing=measured))

    def run(self):
        started = perf_counter(); failure = None
        with bounded_database_io(), provider_free():
            try:
                self.setup()
                manifest = next(m for m in self.manifests if m.lane == Lane.STRUCTURAL_CANARY)
                for snapshot, _ in self.common:
                    if snapshot['id'] in self.targets:
                        self.evaluate_target(snapshot, manifest)
                self.measured_scope = None
                with self.exclusive(): self.identity_gate()
            except BaseException as exc:
                failure = safe_error(exc)
            finally:
                for obj in (self.lock, self.db):
                    if obj is not None:
                        try: obj.close()
                        except BaseException as exc: self.cleanup_errors.append(safe_error(exc))
                for key in ('CANARY_DATABASE_URL', 'CANARY_Q3_SCOPE_AUTHORIZED', 'CANARY_EVALUATION_ONLY_AUTHORIZED'):
                    self.env.pop(key, None)
                result = dict(status='COMPLETE' if failure is None and len(self.target_rows) == len(self.targets)
                    and not self.cleanup_errors else 'BLOCKED', failure=failure, cleanup_errors=self.cleanup_errors,
                    targeted_cases=self.targets, completed_cases=[r['case'] for r in self.target_rows],
                    provider_calls=0, database_writes=0, lease_renewals=0, elapsed_seconds=perf_counter()-started)
                self.save('terminal', result, immutable=True); emit(result)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accepted', type=Path, required=True)
    parser.add_argument('--scope-replay', type=Path, required=True)
    args = parser.parse_args()
    runner = ScopeCanary(Path(__file__).resolve().parents[2], os.environ,
                         accepted=args.accepted, scope_replay=args.scope_replay)
    raise SystemExit(0 if runner.run()['status'] == 'COMPLETE' else 1)
