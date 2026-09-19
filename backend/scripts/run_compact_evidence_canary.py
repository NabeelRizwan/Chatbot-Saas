"""Q1 paired, provider-free, read-only rerun in a NEW result family.

Reuse the frozen Phase-P preflight/transport/SQL/ranker bytecode. The only
function binding replaced in the structural lane is materialization. The
binding is function-local: no monkeypatch of shared globals or serving code.
No Phase-P file, DB row, vector, TTL, schema or corpus is changed.
"""
import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import time, perf_counter
from types import FunctionType

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from database import canary_schema as s
from services.canary_contracts import Lane
from services.canary_repository import document_values
from services.canary_representation import exact_input_hash
from services.canary_retrieval import run_query, materialize
from services.compact_evidence_pack import materialize_compact
from services.structural_chunking import digest
from scripts.canary_bounded_output import emit, vector_summary
from scripts.canary_evaluation_resume import (EvaluationRunner, require, read_bounded,
    atomic_record, provider_free, frozen_files)
from scripts.canary_evaluation_transport import bounded_database_io, safe_error
from scripts.canary_full_completion import FullCompletion
from scripts.canary_read_recovery import ReadTelemetry
from scripts.canary_real_evaluation import score_case, safe_trace
from scripts.canary_split_evidence import split_atom_row
from scripts.replay_compact_evidence_pack import hashes


def query_with_materializer(callback):
    """Original bytecode/defaults, private namespace, no process-global patch."""
    fn=FunctionType(run_query.__code__,dict(run_query.__globals__,materialize=callback),
                    run_query.__name__,run_query.__defaults__,run_query.__closure__)
    fn.__kwdefaults__=run_query.__kwdefaults__
    return fn


def split_original(repo,mf,hard,r,key,*,now):
    pin=repo._route_pin(mf,hard,r,now)
    require(mf.lane==Lane.STRUCTURAL_CANARY and key in pin.atoms,'FOREIGN_ATOM')
    require((r.kind=='ENTRY' and r.key in pin.entries) or
            (r.kind=='ATOM_ONLY' and r.key==key),'UNDECLARED_COMPACT_ROUTE')
    scope=dict(document_values(mf,pin),atom_id=key)
    expected=repo.expected_rows.get(digest(scope))
    require(expected is not None,'VALIDATED_ATOM_ROW_REQUIRED')
    # Identical split transport and complete row hash used in final Phase P.
    return split_atom_row(repo.conn,scope,expected_hash=expected)['payload']


def short_route(r):
    return dict(document=r.source.revision.source.document_id,kind=r.kind,key=r.key,generation=r.generation)


def fused_identity(fused):
    return [dict(route=short_route(v['route']),rank=v['rank'],total=v['total'],
        dense_rank=v['dense_rank'],fts_rank=v['fts_rank']) for v in fused[:48]]


class CompactCanary(FullCompletion):
    def __init__(self,root,env,*,namespace,run_id,identity_hash,replay_folder):
        # Deliberately do not invoke historical, case-specific authorizations.
        EvaluationRunner.__init__(self,root,env,namespace=namespace,run_id=run_id,identity_hash=identity_hash)
        require(env.get('CANARY_COMPACT_Q1_AUTHORIZED')=='true','Q1_AUTHORIZATION_REQUIRED')
        self.replay_folder=replay_folder.resolve()
        require(self.replay_folder.parent==root/'.codex_phase4q','Q1_REPLAY_FOLDER_REQUIRED')
        self.replay=json.loads((self.replay_folder/'summary.json').read_text())
        require(self.replay['real_rerun_gate']=='PASS' and self.replay['old_pack_exact_reproduction']==90
                and not self.replay['lost_previous_support'],'Q1_REPLAY_GATE_FAILED')
        require(hashes(self.folder)==json.loads((self.replay_folder/'phase-p-artifact-hashes.json').read_text()),
                'PHASE_P_BASELINE_CHANGED')
        self.output=root/'.codex_phase4q'/('REAL_CORPUS_V1_EVAL_V1_PHASE4Q1-'+self.session)
        self.output.mkdir(parents=True,exist_ok=False)
        self.reads=ReadTelemetry(self.write_read)
        self.measured_scope=None;self.epochs={};self.split_expected={}
        self.telemetry=None;self.preflight=True;self.baseline_records={}
        self.result.update(family='REAL_CORPUS_V1_EVAL_V1_PHASE4Q1',provider_calls=0,decision='PENDING',
                           phase_p_folder_read_only=True,replay_gate='PASS')

    def save(self,name,value,**kwargs):
        require('/' not in name and '\\' not in name,'Q1_ARTIFACT_NAME_REQUIRED')
        atomic_record(self.output/(name+'.json'),value,**kwargs)

    @contextmanager
    def repository(self,*,inspection=False,writable=False):
        require(not writable,'Q1_DATABASE_WRITES_FORBIDDEN')
        with super().repository(inspection=inspection,writable=False) as repo:yield repo

    def admit_execution(self,admission):
        previous=read_bounded(self.folder/'evaluation-admission.json')
        require(dict(admission,frozen_files=previous['frozen_files'])==previous,'Q1_FROZEN_IDENTITY_CHANGED')
        checkpoint=self.replay['baseline_checkpoint']
        for path,expected in admission['frozen_files'].items():
            old=subprocess.check_output(['git','show',checkpoint+':'+path],cwd=self.root,stderr=subprocess.DEVNULL)
            require(sha256(old.replace(b'\r\n',b'\n')).hexdigest()==expected,'Q1_PROTECTED_SOURCE_CHANGED')
        self.q1_code={name:sha256((self.root/name).read_bytes()).hexdigest() for name in (
            'backend/services/compact_evidence_pack.py','backend/scripts/run_compact_evidence_canary.py')}
        self.save('admission',dict(admission=admission,q1_code=self.q1_code,
            replay_sha256=sha256((self.replay_folder/'summary.json').read_bytes()).hexdigest()),immutable=True)

    def pair(self,case):
        if self.preflight:
            if all((case,mf.lane.value) in self.rows for mf in self.manifests):
                record=read_bounded(self.folder/f'evaluation-pair-{case:02d}.json')
                require(record['identity_hash']==self.identity_hash and record['status']=='COMPLETE'
                    and all(sha256((self.folder/(f'case-{case:02d}-'+v['lane']+'.json')).read_bytes()).hexdigest()
                            ==v['artifact_sha256'] for v in record['lanes']),'PHASE_P_PAIR_CHANGED')
            return
        if all((case,mf.lane.value) in self.rows for mf in self.manifests):
            self.save(f'evaluation-pair-{case:02d}',dict(case=case,identity_hash=self.identity_hash,status='COMPLETE',
                lanes=[dict(lane=mf.lane.value,artifact_sha256=sha256((self.output/(self.case_name(case,mf)+'.json')).read_bytes()).hexdigest())
                    for mf in self.manifests]),immutable=True)

    def aggregate(self):
        if not self.preflight:EvaluationRunner.aggregate(self)

    def setup(self):
        EvaluationRunner.setup(self)
        require(self.reused==180 and self.completed()==90,'COMPLETE_PHASE_P_REQUIRED')
        require(len(self.split_expected)==sum(len(p.atoms) for mf in self.manifests
                if mf.lane==Lane.STRUCTURAL_CANARY for p in mf.documents),'FULL_OLD_ATOM_ROW_INVENTORY_REQUIRED')
        self.baseline_records={(snapshot['id'],mf.lane.value):read_bounded(
            self.folder/(self.case_name(snapshot['id'],mf)+'.json')) for snapshot,_ in self.common for mf in self.manifests}
        self.rows={};self.reused=0;self.pairs_at_start=0;self.preflight=False
        emit(dict(stage='Q1_PREFLIGHT_PASS',saved_vectors=90,owned_schema_unchanged=True,provider_calls=0))

    def ensure_lease(self):
        # No reuse of Phase-P renewal authority after Phase P closed.
        require(int(time())<self.retained_until,'Q1_RETAINED_READ_LEASE_EXPIRED')

    def evaluate_lane(self,snapshot,hard,mf):
        self.ensure_lease()
        require(frozen_files(self.root)==self.code and all(sha256((self.root/p).read_bytes()).hexdigest()==h
                for p,h in self.q1_code.items()),'Q1_IMPLEMENTATION_CHANGED')
        case=snapshot['id'];lane=mf.lane.value
        self.current=dict(case=case,lane=lane)
        old=self.baseline_records[case,lane]
        require(not (self.output/(self.case_name(case,mf)+'.json')).exists(),'Q1_LANE_ALREADY_COMPLETE')
        self.measured_scope=None
        with self.exclusive():
            self.identity_gate()
            self.measured_scope=(mf,hard)
            self.reads.context=dict(case=case,lane=lane,manifest=mf.canonical_hash(),generation=mf.generation,
                organization_id=hard.organization_id,bot_id=hard.bot_id,hard_scope_digest=digest(hard.identity()))
            self.save(f'attempt-{case:02d}-{lane}',dict(**self.current,provider_calls=0,
                snapshot_hash=snapshot['snapshot_hash'],query_vector_hash=self.queries[exact_input_hash(snapshot['query'])].vector_hash,
                timestamp=int(time())),immutable=True)
            emit(dict(stage='Q1_LANE',**self.current,completed_pairs=self.completed()))
            measured={}
            def selected(fused,witnesses,repo,manifest,scope,now):
                require(fused_identity(fused)==old['trace']['rrf'],'Q1_UPSTREAM_RRF_CHANGED')
                before=self.reads.summary()
                if manifest.lane==Lane.LEGACY_CONTROL:
                    return materialize(fused,witnesses,repo,manifest,scope,now)
                replay=json.loads((self.replay_folder/f'case-{case:02d}.json').read_text())
                value=materialize_compact(fused,witnesses,repo,manifest,scope,now,reader=split_original)
                require(value['requested_sequence_hash']==replay['requested_sequence_hash'],'Q1_REQUEST_ORDER_CHANGED')
                require(value['bytes']==replay['new_bytes'] and len(value['units'])==replay['new_units']
                    and sha256(value['model_bytes']).hexdigest()==replay['model_bytes_sha256'],
                    'Q1_REAL_REPLAY_PACK_MISMATCH')
                after=self.reads.summary()
                measured.update(value['timings'],database_sql_ms=after['successful_read_ms']-before['successful_read_ms']
                    +after['failed_read_ms']-before['failed_read_ms'],model_bytes_sha256=sha256(value['model_bytes']).hexdigest(),
                    byte_exclusions=sum(v['cap']=='BYTES' for v in value['exclusions']),
                    unit_exclusions=sum(v['cap']=='UNITS' for v in value['exclusions']))
                return value
            with self.repository() as repo:
                trace=query_with_materializer(selected)(repo,mf,hard,query=snapshot['query'],
                    query_vector=self.queries[exact_input_hash(snapshot['query'])].vector,now=int(time()))
            safe=safe_trace(trace)
            for field in ('raw_dense','raw_fts','rrf','manifest','effective_scope','hard_scope','query_hash'):
                require(safe[field]==old['trace'][field],'Q1_UPSTREAM_IDENTITY_CHANGED')
            if mf.lane==Lane.LEGACY_CONTROL:
                require(all(safe[k]==old['trace'][k] for k in ('materialized','bytes','status')),'Q1_LEGACY_CHANGED')
            record=dict(case=case,lane=lane,snapshot_hash=snapshot['snapshot_hash'],
                query=vector_summary(self.queries[exact_input_hash(snapshot['query'])]),
                outcome=score_case(trace,self.gold[case],lane,mf.effective(hard),self.entry_atoms),trace=safe)
            row=self.validate(record,snapshot,hard,mf)
            self.save(self.case_name(case,mf),record,immutable=True)
            self.save(f'packing-{case:02d}-{lane}',dict(**self.current,**measured,upstream_identity='EXACT_EQUAL',
                legacy_unchanged=mf.lane==Lane.LEGACY_CONTROL,provider_calls=0),immutable=True)
            self.rows[case,lane]=row;self.new_lanes+=1;self.last_completed=dict(self.current)
            self.pair(case);self.aggregate()

    def run(self):
        started=perf_counter();failure=None
        with bounded_database_io(),provider_free():
            try:
                self.setup()
                for snapshot,hard in self.common:
                    for mf in self.manifests:self.evaluate_lane(snapshot,hard,mf)
                self.measured_scope=None
                with self.exclusive():self.identity_gate()
                require(hashes(self.folder)==json.loads((self.replay_folder/'phase-p-artifact-hashes.json').read_text()),
                        'IMMUTABLE_PHASE_P_CHANGED')
            except BaseException as exc:
                failure=safe_error(exc)
            finally:
                for obj in (self.lock,self.db):
                    if obj is not None:
                        try:obj.close()
                        except BaseException as exc:self.cleanup_errors.append(safe_error(exc))
                for key in ('CANARY_DATABASE_URL','CANARY_COMPACT_Q1_AUTHORIZED','CANARY_EVALUATION_ONLY_AUTHORIZED'):
                    self.env.pop(key,None)
                complete_pairs=self.completed() if hasattr(self,'common') else 0
                result=dict(self.result,status='COMPLETE' if failure is None and complete_pairs==90 else 'BLOCKED',
                    failure=failure,cleanup_errors=self.cleanup_errors,completed_pairs=complete_pairs,
                    completed_lanes=len(self.rows),elapsed_seconds=perf_counter()-started,provider_calls=0,
                    database_writes=0,phase_p_files_changed=0,
                    output_folder=str(self.output.relative_to(self.root)))
                self.save('terminal',result,immutable=True);emit(result)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--identity-hash',required=True);parser.add_argument('--replay-folder',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    runner=CompactCanary(root,os.environ,namespace=args.namespace,run_id=args.run_id,identity_hash=args.identity_hash,
        replay_folder=Path(args.replay_folder))
    outcome=runner.run()
    raise SystemExit(0 if outcome['status']=='COMPLETE' and not outcome['cleanup_errors'] else 1)
