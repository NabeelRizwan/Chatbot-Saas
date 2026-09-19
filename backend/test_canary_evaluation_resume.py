"""Offline sealed evaluation continuation: no provider or application DB."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import select, update, insert
from database import canary_schema as s
from services.canary_contracts import CanaryError, State, Lane, route
from services.canary_retrieval import run_query
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_bounded_output import vector_summary
from scripts.canary_evaluation_resume import (provider_free, read_bounded, atomic_record, validate_artifact,
    validate_query, EvaluationRepository, EvaluationRunner, verify_lease_chain, renew_metadata, RETENTION_SECONDS, REASON)
from scripts.canary_gemini_embeddings import Attestation, GeminiCanary
from scripts.canary_real_evaluation import score_case, safe_trace
from scripts.canary_real_repository import receipt_payload
from scripts.canary_stage_a import NOW, hard_scope, lexical_rank_fixture
from services.canary_repository import run_values
import test_canary_real_handoff as fixture_module


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.base = fixture_module.Handoff('test_real_roundtrip_seal_and_query')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        b = self.base
        receipt = b.persist()[0]
        b.repo.seal_generation(b.manifest, expected_build_identity=b.repo.build_identity(b.manifest), now=NOW)
        b.repo.transition(b.manifest, State.CANARY_READ, now=NOW)
        self.mf = b.manifest
        self.hard = hard_scope(self.mf)
        query = 'An ordinary source-backed statement?'
        self.qr = Attestation(b.approval.organization_id, b.approval.bot_id, exact_input_hash(query),
                             receipt.profile_hash, receipt.vector_hash, receipt.vector, 1)
        self.snapshot = dict(id=1, snapshot_hash=digest('saved snapshot'), query=query)
        trace = run_query(b.repo, self.mf, self.hard, query=query, query_vector=self.qr.vector, now=NOW,
            fts_call=lambda:lexical_rank_fixture(b.batch, self.mf))
        self.atoms = {(1, e.entry_key):tuple({v.atom_key for v in e.memberships}) for e in b.batch.entries}
        self.gold = dict(support=[dict(span_mapping='EXACT_UNIQUE_OCCURRENCE',
            candidate_atoms=[dict(atom=b.batch.atoms[0].atom_key, route=['ENTRY', b.batch.entries[0].entry_key])],
            legacy_exact=True, legacy_chunk_id=1, development_document_id=1)])
        self.record = dict(case=1, lane=self.mf.lane.value, snapshot_hash=self.snapshot['snapshot_hash'],
            query=vector_summary(self.qr), trace=safe_trace(trace),
            outcome=score_case(trace, self.gold, self.mf.lane.value, self.mf.effective(self.hard), self.atoms))

    def validate(self, record=None, mf=None):
        return validate_artifact(record or self.record, self.snapshot, self.hard,
                                 mf or self.mf, self.qr, self.gold, self.atoms)

    def test_runtime_trace_reused_without_retrieval(self):
        with patch('scripts.canary_evaluation_resume.run_query', side_effect=AssertionError('rerun')):
            self.assertEqual(self.validate()['case'], 1)

    def test_changed_case_lane_snapshot_query_and_manifest_refused(self):
        for path, value in [(('case',), 2), (('lane',), 'LEGACY_CONTROL'),
                            (('snapshot_hash',), 'a'*64), (('query','vector_hash'), 'a'*64),
                            (('trace','manifest'), 'a'*64), (('trace','hard_scope'), 'a'*64),
                            (('trace','query_hash'), 'a'*64), (('trace','effective_scope'), [])]:
            with self.subTest(path=path):
                r = copy.deepcopy(self.record)
                if len(path) == 1:r[path[0]] = value
                else:r[path[0]][path[1]] = value
                with self.assertRaises(CanaryError):self.validate(r)

    def test_foreign_stale_and_unknown_routes_refused(self):
        for key, value in [('document', 999), ('generation', 'stale'), ('key', 'a'*64), ('kind', 'LEGACY_CHUNK')]:
            r = copy.deepcopy(self.record);r['trace']['raw_dense'][0]['route'][key] = value
            with self.assertRaises(CanaryError):self.validate(r)

    def test_changed_policy_is_not_same_artifact_identity(self):
        mf = self.mf.model_copy(update={'policy':self.mf.policy.model_copy(update={'rrf_k':61})})
        with self.assertRaises(CanaryError):self.validate(mf=mf)

    def test_score_tamper_refused(self):
        r = copy.deepcopy(self.record);r['outcome']['metrics']['materialized_span_hit_recall'][0] = 42
        with self.assertRaisesRegex(CanaryError, 'SCORE'):self.validate(r)

    def test_budget_failure_is_preserved_not_fixed(self):
        r = copy.deepcopy(self.record)
        r['trace']['materialized'] = [];r['trace']['bytes'] = 0;r['trace']['status'] = 'INCOMPLETE_BUDGET'
        for name in ('materialized_span_hit_recall', 'required_document_recall'):
            r['outcome']['metrics'][name][0] = 0
        r['outcome']['metrics']['duplicate_evidence_rate'] = [0,0]
        r['outcome']['metrics']['source_noise_relative_to_mapped_support'] = [0,0]
        r['outcome']['incomplete_budget'] = True
        self.assertTrue(self.validate(r)['outcome']['incomplete_budget'])

    def test_saved_query_requires_success_exact_coordinates_digest_and_provenance(self):
        row = dict(input_hash=self.qr.input_hash, state='succeeded', embedding=self.qr.vector,
                   vector_hash=self.qr.vector_hash, profile_hash=self.qr.profile_hash,
                   provider_receipt=receipt_payload(self.qr, self.base.auth))
        self.assertEqual(validate_query(row,self.mf,self.base.auth,self.qr.input_hash),self.qr)
        for key,value in [('state','pending'),('vector_hash','f'*64),('profile_hash','f'*64),('provider_receipt',{})]:
            with self.subTest(key=key), self.assertRaises((CanaryError,KeyError)):
                validate_query(row|{key:value},self.mf,self.base.auth,self.qr.input_hash)

    def test_read_lease_extension_keeps_manifest_identity_and_scope(self):
        b=self.base
        repo=EvaluationRepository(b.repo.conn,b.approval,authorization=b.auth,
            lease_until=b.approval.expires_at+86400,identities=[self.mf.canonical_hash()],
            clock=lambda:b.approval.expires_at+10)
        before=self.mf.canonical_hash()
        self.assertTrue(repo.read_gate(self.mf,self.hard,now=b.approval.expires_at+10))
        self.assertEqual(before,self.mf.canonical_hash())
        other=self.mf.model_copy(update={'generation':'other'})
        with self.assertRaises(CanaryError):repo.read_gate(other,self.hard,now=NOW)

    def test_expired_lease_is_fail_closed_and_inspection_cannot_retrieve(self):
        b=self.base
        args=dict(authorization=b.auth,lease_until=NOW,identities=[self.mf.canonical_hash()],clock=lambda:NOW+1)
        repo=EvaluationRepository(b.repo.conn,b.approval,**args)
        with self.assertRaisesRegex(CanaryError,'LEASE_EXPIRED'):repo.read_gate(self.mf,self.hard,now=NOW)
        inspector=EvaluationRepository(b.repo.conn,b.approval,inspection=True,**args)
        self.assertTrue(inspector._snapshot(self.mf,inspector._manifest(self.mf),NOW))
        with self.assertRaisesRegex(CanaryError,'INSPECTION'):inspector.read_gate(self.mf,self.hard,now=NOW)

    def test_renewal_updates_only_mutable_expiry_not_manifest_or_approval(self):
        b=self.base;key=run_values(self.mf);old=b.approval.expires_at;new=old+RETENTION_SECONDS
        b.repo.conn.execute(insert(s.recovery).values(**key,identity_hash='a'*64,identity={},ownership={},
                                                     retained_until=old,condition='PAUSED'))
        before=dict(b.repo.conn.execute(select(s.runs)).mappings().one())
        payload=b.repo.conn.execute(select(s.manifests.c.payload)).scalar_one()
        renew_metadata(b.repo.conn,self.mf,'a'*64,old,new)
        after=dict(b.repo.conn.execute(select(s.runs)).mappings().one())
        self.assertEqual(after,before|{'expires_at':new})
        self.assertEqual(b.repo.conn.execute(select(s.manifests.c.payload)).scalar_one(),payload)
        with self.assertRaisesRegex(CanaryError,'CONCURRENT'):
            renew_metadata(b.repo.conn,self.mf,'a'*64,old,new)
        with self.assertRaisesRegex(CanaryError,'INCREMENT'):
            renew_metadata(b.repo.conn,self.mf,'a'*64,new,new+2*RETENTION_SECONDS)


class DurableFiles(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def test_atomic_write_and_immutable_reuse(self):
        p=self.folder/'case.json';atomic_record(p,{'case':1},immutable=True)
        before=p.read_bytes();atomic_record(p,{'case':1},immutable=True)
        self.assertEqual(before,p.read_bytes())
        with self.assertRaisesRegex(CanaryError,'CONFLICT'):atomic_record(p,{'case':2},immutable=True)
        self.assertFalse(p.with_name('case.json.pending').exists())

    def test_interrupted_pending_file_does_not_replace_completed_result(self):
        p=self.folder/'case.json';atomic_record(p,{'case':1})
        p.with_name('case.json.pending').write_text('partial',encoding='utf-8')
        self.assertEqual(read_bounded(p),{'case':1})

    def test_unsafe_vector_or_secret_payload_refused(self):
        for record in ({'embedding':[1]*768},{'api_key':'not-a-real-key'}):
            with self.assertRaises(CanaryError):atomic_record(self.folder/'bad.json',record)

    def test_bounded_lease_chain_and_write_ahead_recovery(self):
        old=100;new=old+RETENTION_SECONDS
        record=dict(identity_hash='a'*64,old_retained_until=old,new_retained_until=new,reason=REASON)
        atomic_record(self.folder/f'evaluation-lease-{new}.json',record)
        self.assertEqual(verify_lease_chain(self.folder,'a'*64,old,old),old)
        self.assertEqual(verify_lease_chain(self.folder,'a'*64,old,new),new)
        for identity,retained in [('b'*64,new),('a'*64,new+1)]:
            with self.assertRaises(CanaryError):verify_lease_chain(self.folder,identity,old,retained)

    def test_bad_lease_increment_and_reason_refused(self):
        for field,value in [('new_retained_until',999999),('reason','other')]:
            r=dict(identity_hash='a'*64,old_retained_until=100,new_retained_until=100+RETENTION_SECONDS,reason=REASON)
            r[field]=value
            atomic_record(self.folder/'evaluation-lease-1.json',r)
            with self.assertRaises(CanaryError):verify_lease_chain(self.folder,'a'*64,100,100)

    def test_provider_paths_hard_fail_without_key(self):
        import httpx
        with provider_free():
            for call in (lambda:GeminiCanary(None,organization_id=1,bot_id=2),
                         lambda:httpx.get('https://example.invalid'),
                         lambda:socket.create_connection(('example.invalid',443))):
                with self.assertRaisesRegex(CanaryError,'UNEXPECTED_PROVIDER_ACCESS'):call()

    def test_resume_dispatch_skips_completed_lane_and_has_no_deadline(self):
        class Finished(Exception):pass
        r=object.__new__(EvaluationRunner)
        r.common=[(dict(id=1,query='saved'),None)]
        legacy=SimpleNamespace(lane=Lane.LEGACY_CONTROL)
        structural=SimpleNamespace(lane=Lane.STRUCTURAL_CANARY)
        r.manifests=(structural,legacy);r.rows={(1,'LEGACY_CONTROL'):dict()}
        r.root=self.folder;r.code={};r.ensure_lease=Mock();r.completed=lambda:0
        r.queries={exact_input_hash('saved'):SimpleNamespace(vector=(.1,)*768)}
        @contextmanager
        def repository():yield object()
        r.repository=repository
        with patch('scripts.canary_evaluation_resume.frozen_files',return_value={}), \
             patch('scripts.canary_evaluation_resume.run_query',side_effect=Finished) as execute:
            with self.assertRaises(Finished):r.evaluate()
        self.assertIs(execute.call_args.args[1],structural)
        self.assertFalse(hasattr(r,'deadline'))

    def test_renewal_requires_progress_and_explicit_authority(self):
        r=object.__new__(EvaluationRunner);r.retained_until=0;r.renew_authorized=False
        r.rows={};r.last_renew_progress=-1
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):r.ensure_lease()
        r.renew_authorized=True;r.last_renew_progress=0
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):r.ensure_lease()


if __name__=='__main__':unittest.main()
