"""Network-free provider-to-repository handoff and bounded output regressions."""
from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from sqlalchemy import select,update
from database import canary_schema as s
from scripts.canary_stage_a import offline_repository,approval,fixture_batch,make_manifest,hard_scope,NOW
from scripts.canary_gemini_embeddings import GeminiCanary,configuration,real_profile
from scripts.canary_real_repository import RealAuthorization,RealCanaryRepository
from scripts.canary_bounded_output import bounded_json,emit,vector_summary
from services.canary_contracts import CanaryError,Manifest,State,Lane,canonical_vector_bytes
from services.structural_chunking import digest


class Handoff(unittest.TestCase):
    def setUp(self):
        self.approval=approval().model_copy(update={'environment':'disposable_test'})
        self.auth=RealAuthorization.from_environment({'CANARY_REAL_EMBEDDING_AUTHORIZED':'true',
            'CANARY_APPROVAL_REFERENCE':self.approval.operator_reference},self.approval)
        self.context=offline_repository(self.approval)
        base=self.context.__enter__();self.addCleanup(self.context.__exit__,None,None,None)
        self.repo=RealCanaryRepository(base.conn,self.approval,authorization=self.auth,clock=lambda:NOW)
        self.batch=fixture_batch('# Guide\n\nAn ordinary source-backed statement.')
        self.pin=self.repo.register_fixture_source(self.batch,source_id=1)
        self.manifest=Manifest(**(make_manifest((self.pin,),approved=self.approval).model_dump()|
            {'profile':real_profile(),'embedding_configuration':configuration()}))
        self.repo.create(self.manifest,now=NOW)
        self.repo.stage_structure(self.manifest,self.batch,now=NOW)
        factory=Mock();self.client=factory.return_value
        self.client.models.embed_content.side_effect=lambda **kw:NS(embeddings=[NS(
            values=[0.123456789123456+i/10000 for i in range(768)],statistics=None) for _ in kw['contents']])
        self.provider=GeminiCanary('offline-fake',organization_id=self.approval.organization_id,
            bot_id=self.approval.bot_id,approved=True,client_factory=factory)
        self.addCleanup(self.provider.close)

    def items(self):return [(self.pin,e.entry_key,e) for e in self.batch.entries]

    def persist(self,items=None):
        items=items or self.items()
        self.repo.begin_attempt(self.manifest,items,now=NOW)
        receipts=self.provider.embed([e.text for _,_,e in items],purpose='evidence')
        self.repo.persist(self.manifest,items,receipts,now=NOW)
        return receipts

    def test_real_roundtrip_seal_and_query(self):
        receipts=self.persist()
        self.repo.seal_generation(self.manifest,expected_build_identity=self.repo.build_identity(self.manifest),now=NOW)
        self.repo.transition(self.manifest,State.CANARY_READ,now=NOW)
        hits=self.repo.dense(self.manifest,hard_scope(self.manifest),receipts[0].vector,now=NOW)
        self.assertEqual(len(hits),len(receipts))
        for pin,key,e in self.items():
            loaded=self.repo.persisted_receipt(self.manifest,pin,key,e.text)
            self.assertEqual(canonical_vector_bytes(loaded.vector),canonical_vector_bytes(self.provider.receipt(e.text).vector))

    def test_no_partial_seal(self):
        with self.assertRaisesRegex(CanaryError,'INCOMPLETE'):
            self.repo.seal_generation(self.manifest,expected_build_identity=self.repo.build_identity(self.manifest),now=NOW)

    def test_default_repository_refuses_real(self):
        from services.canary_repository import CanaryRepository
        ordinary=CanaryRepository(self.repo.conn,self.approval,clock=lambda:NOW)
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):
            ordinary.build_identity(self.manifest)

    def test_no_synthetic_staging_under_real_manifest(self):
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):
            self.repo.stage(self.manifest,self.batch,now=NOW)

    def test_real_adapter_refuses_synthetic(self):
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):
            self.repo.create(make_manifest((self.pin,),run='synthetic',approved=self.approval),now=NOW)

    def test_missing_authorization(self):
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):
            RealAuthorization.from_environment({},self.approval)

    def test_wrong_authorization_reference(self):
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'):
            RealAuthorization.from_environment({'CANARY_REAL_EMBEDDING_AUTHORIZED':'true',
                'CANARY_APPROVAL_REFERENCE':'wrong'},self.approval)

    def test_changed_profile(self):
        altered=self.manifest.model_copy(update={'profile':self.manifest.profile.model_copy(update={'model':'other'})})
        with self.assertRaises(CanaryError):self.repo.build_identity(altered)

    def test_proof_tamper_rejected(self):
        self.persist()
        self.repo.conn.execute(update(s.vectors).values(provider_receipt={}))
        with self.assertRaisesRegex(CanaryError,'CORRUPTION'):
            self.repo.seal_generation(self.manifest,expected_build_identity=self.repo.build_identity(self.manifest),now=NOW)

    def test_unknown_consumption_does_not_retry(self):
        self.repo.begin_attempt(self.manifest,self.items(),now=NOW)
        pin,key,e=self.items()[0]
        with self.assertRaisesRegex(CanaryError,'UNKNOWN_PROVIDER_CONSUMPTION'):
            self.repo.persisted_receipt(self.manifest,pin,key,e.text)
        self.client.models.embed_content.assert_not_called()

    def test_reopen_completed_work_no_provider_repeat(self):
        self.persist();calls=self.client.models.embed_content.call_count
        other=RealCanaryRepository(self.repo.conn,self.approval,authorization=self.auth,clock=lambda:NOW)
        for pin,key,e in self.items():self.assertIsNotNone(other.persisted_receipt(self.manifest,pin,key,e.text))
        self.assertEqual(calls,self.client.models.embed_content.call_count)

    def test_epoch_change_blocks_real_seal(self):
        self.persist();self.repo.conn.execute(update(s.lifecycle).values(epoch=1))
        with self.assertRaisesRegex(CanaryError,'STALE_SOURCE_EPOCH'):
            self.repo.seal_generation(self.manifest,expected_build_identity=self.repo.build_identity(self.manifest),now=NOW)

    def test_wrong_receipt_input_no_vector_insert(self):
        self.repo.begin_attempt(self.manifest,self.items(),now=NOW)
        receipts=self.provider.embed(['different'],purpose='evidence')
        with self.assertRaises(CanaryError):self.repo.persist(self.manifest,self.items(),receipts,now=NOW)
        self.assertEqual(self.repo.conn.execute(select(s.vectors)).all(),[])

    def test_explicit_partial_vector_manifest(self):
        b=fixture_batch('# A\n\n'+('A standalone passage. '*500),document_id=2)
        p=self.repo.register_fixture_source(b,source_id=2)
        self.assertGreater(len(b.entries),1)
        mf=self.manifest.model_copy(update={'run_id':'subset','documents':(p,),
            'vector_entry_selection':(b.entries[0].entry_key,)})
        self.repo.create(mf,now=NOW);self.repo.stage_structure(mf,b,now=NOW)
        e=b.entries[0];items=[(p,e.entry_key,e)]
        self.repo.begin_attempt(mf,items,now=NOW)
        self.repo.persist(mf,items,self.provider.embed([e.text],purpose='evidence'),now=NOW)
        self.repo.seal_generation(mf,expected_build_identity=self.repo.build_identity(mf),now=NOW)
        self.repo.transition(mf,State.CANARY_READ,now=NOW)
        hits=self.repo.dense(mf,hard_scope(mf),self.provider.receipt(e.text).vector,now=NOW)
        self.assertEqual([h.route.key for h in hits],[e.entry_key])

    def test_legacy_real_work_and_seal(self):
        chunks=[{'id':1,'text':'An exact legacy input.'}]
        pin=self.pin.model_copy(update={'entries':(),'legacy_members':(1,),'batch_hash':digest(chunks)})
        mf=self.manifest.model_copy(update={'lane':Lane.LEGACY_CONTROL,'documents':(pin,)})
        self.repo.create(mf,now=NOW);self.repo.stage_legacy_work(mf,pin,chunks,now=NOW)
        items=[(pin,1,chunks[0])];self.repo.begin_attempt(mf,items,now=NOW)
        receipts=self.provider.embed([chunks[0]['text']],purpose='evidence')
        self.repo.persist(mf,items,receipts,now=NOW)
        self.repo.seal_generation(mf,expected_build_identity=self.repo.build_identity(mf),now=NOW)

    def test_actual_runner_eight_query_and_multiple_batches_preserve_bytes(self):
        from scripts.canary_real_embedding_retrieval import handoff
        chunks=[{'id':i,'text':f'Independent frozen evidence number {i}.'} for i in range(1,33)]
        pin=self.pin.model_copy(update={'entries':(),'legacy_members':tuple(c['id'] for c in chunks),
            'batch_hash':digest(chunks)})
        mf=self.manifest.model_copy(update={'lane':Lane.LEGACY_CONTROL,'documents':(pin,)})
        self.repo.create(mf,now=NOW);self.repo.stage_legacy_work(mf,pin,chunks,now=NOW)
        output=StringIO()
        with redirect_stdout(output):
            for offset in range(0,32,8):
                items=[(pin,c['id'],c) for c in chunks[offset:offset+8]]
                self.repo.begin_attempt(mf,items,now=NOW)
                emit(handoff(self.provider,self.repo,mf,items,now=NOW))
                for _,key,c in items:
                    receipt=self.repo.persisted_receipt(mf,pin,key,c['text'])
                    self.assertEqual(canonical_vector_bytes(receipt.vector),
                                     canonical_vector_bytes(self.provider.receipt(c['text']).vector))
                if offset==0:
                    query=self.provider.embed(['An unrelated exact query?'],purpose='query')[0]
                    emit({'query':vector_summary(query)})
        self.assertLess(len(output.getvalue().encode()),16384)
        self.assertNotIn(str(query.vector[0]),output.getvalue())
        self.assertEqual(len(self.repo.conn.execute(select(s.legacy)).all()),32)
        self.repo.seal_generation(mf,expected_build_identity=self.repo.build_identity(mf),now=NOW)
        self.assertEqual(self.provider.client.models.embed_content.call_count,5)

    def test_handoff_persists_before_summary(self):
        from scripts.canary_real_embedding_retrieval import handoff
        from unittest.mock import patch
        self.repo.begin_attempt(self.manifest,self.items(),now=NOW)
        def inspect(receipt):
            self.assertEqual(len(self.repo.conn.execute(select(s.vectors)).all()),len(self.items()))
            return vector_summary(receipt)
        with patch('scripts.canary_real_embedding_retrieval.vector_summary',side_effect=inspect):
            result=handoff(self.provider,self.repo,self.manifest,self.items(),now=NOW)
        self.assertEqual(result['result'],'PERSISTED')

    def test_legacy_work_hash_tampering_refused(self):
        chunks=[{'id':1,'text':'Exact text.'}]
        pin=self.pin.model_copy(update={'entries':(),'legacy_members':(1,),'batch_hash':digest(chunks)})
        mf=self.manifest.model_copy(update={'lane':Lane.LEGACY_CONTROL,'documents':(pin,)})
        self.repo.create(mf,now=NOW);self.repo.stage_legacy_work(mf,pin,chunks,now=NOW)
        items=[(pin,1,chunks[0])];self.repo.begin_attempt(mf,items,now=NOW)
        self.repo.persist(mf,items,self.provider.embed(['Exact text.'],purpose='evidence'),now=NOW)
        self.repo.conn.execute(update(s.legacy_work).values(input_hash='f'*64))
        with self.assertRaisesRegex(CanaryError,'INCOMPLETE_LEGACY_WORK'):
            self.repo.seal_generation(mf,expected_build_identity=self.repo.build_identity(mf),now=NOW)


class RunnerGates(unittest.TestCase):
    def test_p1_failure_never_calls_p2_and_cleans(self):
        from scripts.canary_real_embedding_retrieval import Runner
        from pathlib import Path
        from unittest.mock import patch
        obj=Runner(Path(__file__).resolve().parents[1],{})
        db=Mock();db.cleanup.return_value={'schema_removed':True}
        def setup():obj.db=db
        with patch.object(obj,'setup',side_effect=setup),patch.object(obj,'p1',side_effect=CanaryError('P1_TEST_FAILURE')),\
                patch.object(obj,'p2') as p2,patch.object(obj,'save'),redirect_stdout(StringIO()):
            self.assertEqual(obj.run(),1)
        p2.assert_not_called();db.cleanup.assert_called_once();db.close.assert_called_once()

    def test_p1_pass_automatically_runs_p2(self):
        from scripts.canary_real_embedding_retrieval import Runner
        from pathlib import Path
        from unittest.mock import patch
        obj=Runner(Path(__file__).resolve().parents[1],{})
        def p2():obj.result['decision']='A'
        with patch.object(obj,'setup'),patch.object(obj,'p1'),patch.object(obj,'p2',side_effect=p2) as second,\
                patch.object(obj,'save'),redirect_stdout(StringIO()):
            self.assertEqual(obj.run(),0)
        second.assert_called_once()

    def test_stage_p_explicit_authorization_before_inventory(self):
        from scripts.canary_real_embedding_retrieval import Runner
        from pathlib import Path
        from unittest.mock import patch
        obj=Runner(Path(__file__).resolve().parents[1],{})
        with patch('scripts.canary_real_embedding_retrieval.freeze') as frozen:
            with self.assertRaisesRegex(CanaryError,'REAL_PROVIDER_NOT_AUTHORIZED'):obj.setup()
        frozen.assert_not_called()

    def test_frozen_selection_and_query_not_changed(self):
        from pathlib import Path
        from services.canary_representation import exact_input_hash
        plan=json.loads((Path(__file__).parent/'fixtures/canary_real_embedding_v1/plan.json').read_text())
        self.assertEqual(len(plan['p1_entries']),8)
        self.assertEqual(plan['p1_tokens'],3044)
        self.assertEqual(exact_input_hash(plan['p1_query']),plan['p1_query_hash'])

    def test_security_copy_is_not_valid_provider_receipt(self):
        self.assertIn('SECURITY_TEST_COPY_NOT_PROVIDER_ATTESTATION',
            __import__('pathlib').Path(__file__).with_name('scripts').joinpath('canary_real_security.py').read_text())

    def test_pg_work_updates_remain_narrow(self):
        sql=s.postgres_seal_guards()[0]
        self.assertIn("OLD.state='pending' AND NEW.state='unknown'",sql)
        self.assertIn("OLD.state='unknown' AND NEW.state IN ('succeeded','failed')",sql)
        self.assertIn("(to_jsonb(NEW)-'state'-'attempts') IS DISTINCT FROM",sql)
        self.assertIn("IF g IS DISTINCT FROM 'EMBEDDING_STAGING'",sql)


class Output(unittest.TestCase):
    def test_prior_large_result_shape_and_many_batches(self):
        from scripts.canary_gemini_embeddings import Attestation
        from services.canary_contracts import canonicalize_vector_f32,canonical_vector_digest
        # Distinct nontrivial values reproduce the prior large decimal payload.
        vector=canonicalize_vector_f32([0.123456789123456+i/10000 for i in range(768)])
        persisted=[];messages=[]
        for size in (8,1,8,8,8):
            internal=[Attestation(1,2,'a'*64,'b'*64,canonical_vector_digest(vector),vector,1) for _ in range(size)]
            # This fake persistence sink deliberately retains complete byte copies.
            persisted.extend(canonical_vector_bytes(v.vector) for v in internal)
            summary={'result':'PASS','items':[vector_summary(v) for v in internal]}
            out=StringIO()
            with redirect_stdout(out):emit(summary)
            encoded=out.getvalue();messages.append(encoded)
            self.assertLess(len(encoded.encode()),8192)
            self.assertNotIn(str(vector[0]),encoded)
            self.assertNotIn('coordinates',encoded)
            self.assertNotIn('"vector":',encoded)
        self.assertEqual(len(persisted),33)
        self.assertTrue(all(len(v)==3072 for v in persisted))

    def test_vector_coordinate_output_refused(self):
        with self.assertRaises(CanaryError):bounded_json({'vector':[.1]*768})

    def test_disguised_large_numeric_sequence_refused(self):
        with self.assertRaises(CanaryError):bounded_json({'distances':[.1]*768})

    def test_output_size_bound(self):
        with self.assertRaisesRegex(CanaryError,'SIZE_BOUND'):
            bounded_json({'items':[{'a':'x'*500} for _ in range(64)]},limit=1024)

    def test_raw_object_refused(self):
        with self.assertRaises(CanaryError):bounded_json({'response':object()})

    def test_secret_field_refused(self):
        with self.assertRaises(CanaryError):bounded_json({'api_key':'fake'})


if __name__=='__main__':unittest.main()
