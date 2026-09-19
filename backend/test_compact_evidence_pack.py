"""Additive Q1 tests: actual scoped repository, source bytes, and packing policy."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import event, update

from database import canary_schema as s
from services.canary_contracts import CanaryError, Policy, State, route
from services.canary_representation import atomic_projection, evidence_view
from services.canary_retrieval import Hit, materialize
from services.compact_evidence_pack import (CONTRACT, SidecarRecord, ProvenanceSidecar,
    compact_unit, encoded, materialize_compact, read_original, requested_atoms, serialize_pack)
from services.structural_chunking import digest
from scripts.canary_stage_a import fixture_batch, offline_repository, make_manifest, hard_scope, NOW
from scripts.canary_real_evaluation import score_case


class ExactPacking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = fixture_batch()

    def setUp(self):
        ctx = offline_repository()
        self.repo = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.pin = self.repo.register_fixture_source(self.batch, source_id=1)
        self.mf = make_manifest((self.pin,))
        self.hard = hard_scope(self.mf)
        self.repo.create(self.mf, now=NOW)
        self.repo.stage(self.mf, self.batch, now=NOW)
        self.repo.seal_generation(self.mf, expected_build_identity=self.repo.build_identity(self.mf), now=NOW)
        self.repo.transition(self.mf, State.CANARY_READ, now=NOW)
        self.fused = [dict(route=route(self.mf, self.pin, 'ENTRY', e.entry_key)) for e in self.batch.entries]
        self.key = self.pin.atoms[0]
        self.route = route(self.mf, self.pin, 'ATOM_ONLY', self.key)

    def pack(self, fused=None, witnesses=(), reader=read_original):
        return materialize_compact(self.fused if fused is None else fused, witnesses,
            self.repo, self.mf, self.hard, NOW, reader=reader)

    def record(self):
        payload = read_original(self.repo, self.mf, self.hard, self.route, self.key, now=NOW)
        record = SidecarRecord.create(self.mf, self.hard, self.route, self.key, payload)
        sidecar = ProvenanceSidecar(); sidecar.add(record)
        return sidecar, record, payload

    def resolve(self, sidecar, record, **kwargs):
        return sidecar.resolve(record.reference, self.repo, self.mf, self.hard, now=NOW, **kwargs)

    def test_entire_original_payload_byte_recovery_and_scoped_spans(self):
        pack = self.pack()
        for model, unit in zip(json.loads(pack['model_bytes'])['units'], pack['units']):
            recovered = pack['sidecar'].resolve(model['provenance_ref'], self.repo,
                self.mf, self.hard, now=NOW, expected_atom=unit['key'])
            original = atomic_projection(self.batch, next(a for a in self.batch.atoms if a.atom_key == unit['key']))
            self.assertEqual(encoded(original), encoded(recovered['original_payload']))
            self.assertEqual(evidence_view(original), unit['payload'])
            self.assertEqual(recovered['route'], unit['route'])
            self.assertEqual(recovered['hard_scope'], self.hard.identity())
            self.assertEqual(model['citation']['document_id'], 1)

    def test_exact_text_attributes_roles_order_and_context_are_visible(self):
        pack = self.pack()
        for model, unit in zip(json.loads(pack['model_bytes'])['units'], pack['units']):
            old = unit['payload']
            for before, after in zip(old['source_parts'], model['parts']):
                for key in after: self.assertEqual(before[key], after[key])
            for before, after in zip(old['nodes'], model['nodes']):
                for key in after: self.assertEqual(before[key], after[key])
            self.assertEqual(len(model['parts']), len(old['source_parts']))
            self.assertEqual(len(model['nodes']), len(old['nodes']))

    def test_actual_utf8_envelope_comma_citation_accounting(self):
        pack = self.pack()
        model = json.loads(pack['model_bytes'])
        expected = len(serialize_pack(())) + sum(len(encoded(u)) for u in model['units']) + max(0,len(model['units'])-1)
        self.assertEqual(expected, pack['bytes'])
        self.assertEqual(pack['bytes'], len(serialize_pack(model['units'])))
        self.assertEqual(model['contract'], CONTRACT)
        self.assertLessEqual(pack['bytes'], 131072)

    def test_metadata_is_sidecar_only_not_a_hidden_second_context(self):
        pack = self.pack()
        model = json.loads(pack['model_bytes'])
        for item in model['units']:
            self.assertNotIn('route', item)
            self.assertNotIn('manifest', item)
            self.assertNotIn('mappings', item['parts'][0])
            self.assertNotIn('provenance', item['nodes'][0])
        self.assertTrue(all(isinstance(r.data, bytes) for r in pack['sidecar']._records.values()))

    def test_same_requested_order_and_duplicates_match_old_materializer(self):
        witness = Hit(self.route, self.key, 1, 1)
        requested, _ = requested_atoms(self.fused, (witness,witness), self.repo, self.mf,self.hard,NOW)
        calls=[]
        old_reader=self.repo.evidence
        with patch.object(self.repo,'evidence',side_effect=lambda m,h,r,k,now:(calls.append((r,k)) or old_reader(m,h,r,k,now=now))):
            old=materialize(self.fused,(witness,witness),self.repo,self.mf,self.hard,NOW)
        expected=[];seen=set()
        for r,k,_ in requested:
            if (r.source,k) not in seen:expected.append((r,k));seen.add((r.source,k))
        self.assertEqual(calls,expected)
        new=self.pack(witnesses=(witness,witness))
        self.assertEqual([(u['route'],u['key'],u['reason']) for u in old['units']],
                         [(u['route'],u['key'],u['reason']) for u in new['units']])
        self.assertEqual(len(new['units']),len({u['key'] for u in new['units']}))

    def test_same_support_scorer_and_original_payload_input(self):
        old=materialize(self.fused,(),self.repo,self.mf,self.hard,NOW); new=self.pack()
        gold={'support':[dict(span_mapping='EXACT_UNIQUE_OCCURRENCE',legacy_exact=True,
            development_document_id=1,legacy_chunk_id=1,candidate_atoms=[{'atom':u['key']}]) for u in old['units']]}
        trace=dict(raw_dense=[],raw_fts=[],rrf=[],route_collapse_ratio=0,final_status='COMPLETE')
        self.assertEqual(score_case(dict(trace,materialized=old),gold,self.mf.lane.value,(1,)),
                         score_case(dict(trace,materialized=new),gold,self.mf.lane.value,(1,)))

    def test_current_version_checked_again_after_atom_fetch(self):
        def raced(*args,**kwargs):
            payload=read_original(*args,**kwargs)
            self.repo.conn.execute(update(s.lifecycle).values(epoch=s.lifecycle.c.epoch+1))
            return payload
        with self.assertRaises(CanaryError): self.pack(reader=raced)

    def test_sidecar_lookup_concurrent_version_change_fails(self):
        sidecar,record,_=self.record()
        def raced(*args,**kwargs):
            payload=read_original(*args,**kwargs)
            self.repo.conn.execute(update(s.lifecycle).values(source_fingerprint='e'*64,epoch=s.lifecycle.c.epoch+1))
            return payload
        with self.assertRaises(CanaryError): self.resolve(sidecar,record,reader=raced)

    def test_stale_lifecycle_sidecar_and_packing_fail_closed(self):
        sidecar,record,_=self.record()
        self.repo.conn.execute(update(s.lifecycle).values(status='error',epoch=s.lifecycle.c.epoch+1))
        with self.assertRaises(CanaryError):self.resolve(sidecar,record)
        with self.assertRaises(CanaryError):self.pack()

    def test_missing_reference_rejected(self):
        sidecar,_,_=self.record()
        with self.assertRaisesRegex(CanaryError,'REFERENCE_NOT_FOUND'):
            sidecar.resolve('f'*64,self.repo,self.mf,self.hard,now=NOW)

    def test_wrong_atom_rejected(self):
        sidecar,record,_=self.record()
        with self.assertRaisesRegex(CanaryError,'WRONG_COMPACT_ATOM'):self.resolve(sidecar,record,expected_atom='f'*64)
        with self.assertRaises(CanaryError):read_original(self.repo,self.mf,self.hard,self.route,'f'*64,now=NOW)

    def test_corrupt_db_payload_rejected(self):
        sidecar,record,_=self.record()
        self.repo.conn.execute(update(s.atoms).where(s.atoms.c.atom_id==self.key).values(payload={'corrupt':True}))
        with self.assertRaisesRegex(CanaryError,'CORRUPTION'):self.resolve(sidecar,record)

    def test_self_consistent_but_changed_db_payload_rejected(self):
        sidecar,record,payload=self.record()
        payload['canonical_text']+=' changed'
        self.repo.conn.execute(update(s.atoms).where(s.atoms.c.atom_id==self.key).values(payload=payload,payload_hash=digest(payload)))
        with self.assertRaisesRegex(CanaryError,'PAYLOAD_CHANGED'):self.resolve(sidecar,record)

    def test_sidecar_corruption_rejected(self):
        sidecar,record,_=self.record()
        sidecar._records[record.reference]=SidecarRecord(record.reference,record.data+b' ')
        with self.assertRaisesRegex(CanaryError,'SIDECAR_CORRUPTION'):self.resolve(sidecar,record)

    def test_sidecar_is_immutable_and_recovery_does_not_mutate_it(self):
        sidecar,record,_=self.record()
        with self.assertRaises(FrozenInstanceError):record.data=b'other'
        a=self.resolve(sidecar,record);a['original_payload']['canonical_text']='changed'
        self.assertNotEqual(a,self.resolve(sidecar,record))

    def test_sql_atom_read_has_every_scope_predicate_and_no_substring_scan(self):
        statements=[]
        def capture(conn,cursor,sql,params,context,many):
            if 'canary_atoms' in sql:statements.append(sql)
        event.listen(self.repo.conn,'before_cursor_execute',capture)
        read_original(self.repo,self.mf,self.hard,self.route,self.key,now=NOW)
        self.assertEqual(len(statements),1)
        for column in (*s.DOC,'atom_id'): self.assertIn('canary_atoms.'+column,statements[0])
        self.assertNotIn('LIKE',statements[0])

    def test_atom_only_route_cannot_select_another_declared_atom(self):
        other=next(k for k in self.pin.atoms if k!=self.key)
        with self.assertRaisesRegex(CanaryError,'UNDECLARED_COMPACT_ROUTE'):
            read_original(self.repo,self.mf,self.hard,self.route,other,now=NOW)

    def test_undeclared_entry_fails_even_with_valid_atom(self):
        bad=route(self.mf,self.pin,'ENTRY','f'*64)
        with self.assertRaisesRegex(CanaryError,'UNDECLARED_COMPACT_ROUTE'):
            read_original(self.repo,self.mf,self.hard,bad,self.key,now=NOW)

    def test_stale_source_route_fails_without_returning_payload(self):
        src=self.route.source.revision.source.model_copy(update={'source_version':2})
        revision=self.route.source.revision.model_copy(update={'source':src})
        r=self.route.model_copy(update={'source':self.route.source.model_copy(update={'revision':revision})})
        with self.assertRaises(CanaryError):read_original(self.repo,self.mf,self.hard,r,self.key,now=NOW)

    def test_same_text_in_foreign_bot_has_no_sidecar_access(self):
        from scripts.canary_stage_a import approval
        from services.structural_document import RevisionIdentity
        from services.structural_text_adapter import parse_structural_text
        from services.structural_chunking import serialize_structural_document
        from services.structural_retrieval_entries import RetrievalEntryScope
        from services import structural_retrieval_entries_v2 as m
        graph=self.batch.evidence.source_graph
        src=graph.revision.identity.source.model_copy(update={'bot_id':70003})
        revision=RevisionIdentity(source=src,structure_revision_id='adapter-evaluation-v1')
        # The fixture's exact input, not an entity name or benchmark question.
        from scripts.canary_stage_a import GOLD
        original=json.loads(GOLD.read_text(encoding='utf-8'))['source']
        foreign=serialize_structural_document(parse_structural_text(original,identity=revision,
            source_format='markdown',fidelity='extracted_markdown'))
        batch=m.build_retrieval_entries(foreign,scope=RetrievalEntryScope(revision=revision))
        with offline_repository(approval(bot=70003)) as repo:
            pin=repo.register_fixture_source(batch,source_id=1)
            mf=make_manifest((pin,),approved=approval(bot=70003));hard=hard_scope(mf)
            repo.create(mf,now=NOW);repo.stage(mf,batch,now=NOW)
            repo.seal_generation(mf,expected_build_identity=repo.build_identity(mf),now=NOW)
            repo.transition(mf,State.CANARY_READ,now=NOW)
            sidecar,record,_=self.record()
            with self.assertRaisesRegex(CanaryError,'FOREIGN_COMPACT_REFERENCE'):
                sidecar.resolve(record.reference,repo,mf,hard,now=NOW)


class BudgetBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch=fixture_batch('\n\n'.join('# Section '+str(i)+'\n\nIndependent paragraph number '+str(i)+'.' for i in range(65)))

    def run_pack(self,policy):
        with offline_repository() as repo:
            pin=repo.register_fixture_source(self.batch,source_id=1)
            mf=make_manifest((pin,),policy=policy);hard=hard_scope(mf)
            repo.create(mf,now=NOW);repo.stage(mf,self.batch,now=NOW)
            repo.seal_generation(mf,expected_build_identity=repo.build_identity(mf),now=NOW)
            repo.transition(mf,State.CANARY_READ,now=NOW)
            fused=[dict(route=route(mf,pin,'ENTRY',e.entry_key)) for e in self.batch.entries]
            calls=[]
            def reader(*args,**kwargs):
                calls.append(args[4]);return read_original(*args,**kwargs)
            result=materialize_compact(fused,(),repo,mf,hard,NOW,reader=reader)
            return result,calls

    def test_48_units_still_cap_without_fetching_later_payloads(self):
        result,calls=self.run_pack(Policy())
        self.assertEqual(len(result['units']),48)
        self.assertEqual(len(calls),48)
        self.assertTrue(result['exclusions'])
        self.assertTrue(all(e['cap']=='UNITS' for e in result['exclusions']))

    def test_envelope_and_whole_unit_boundary_no_truncation(self):
        small=fixture_batch('Unicode 🧪 café exact.')
        prior=self.batch
        self.batch=small
        try:
            result,_=self.run_pack(Policy())
            exact=result['bytes']
            fits,_=self.run_pack(Policy(evidence_bytes=exact))
            self.assertEqual(fits['bytes'],exact)
            missed,_=self.run_pack(Policy(evidence_bytes=exact-1))
            self.assertEqual(missed['units'],[])
            self.assertEqual(missed['bytes'],len(serialize_pack(())))
            self.assertEqual(missed['exclusions'][0]['cap'],'BYTES')
        finally:self.batch=prior

    def test_budget_smaller_than_envelope_fails_explicitly(self):
        with self.assertRaisesRegex(CanaryError,'ENVELOPE_OVER_BUDGET'):
            self.run_pack(Policy(evidence_bytes=1))


for name,change in [('organization',{'organization_id':8}),('bot',{'bot_id':8}),
                     ('hard_documents',{'authorized_document_ids':()}),
                     ('hard_versions',{'active_document_versions':((1,9,None),)})]:
    def test(self,change=change):
        sidecar,record,_=self.record()
        with self.assertRaises(CanaryError):
            sidecar.resolve(record.reference,self.repo,self.mf,replace(self.hard,**change),now=NOW)
    setattr(ExactPacking,'test_scope_'+name,test)

for name,change in [('generation',{'generation':'wrong'}),('manifest',{'query_contract_hash':'a'*64})]:
    def test(self,change=change):
        sidecar,record,_=self.record()
        with self.assertRaises(CanaryError):
            sidecar.resolve(record.reference,self.repo,self.mf.model_copy(update=change),self.hard,now=NOW)
    setattr(ExactPacking,'test_scope_'+name,test)


class SerializationOnly(unittest.TestCase):
    def test_unicode_large_and_small_atoms_are_exact_and_never_truncated(self):
        for text in ('Plain text.', '# Café 🧪\n\nनमस्ते — 4–8 weeks; not guaranteed.\n\n- €12.40\n- Keep refrigerated.',
                     '# Large\n\n'+('Exact wording λ. '*1400)):
            batch=fixture_batch(text)
            for atom in batch.atoms:
                payload=atomic_projection(batch,atom); before=encoded(payload)
                unit=compact_unit(payload,'a'*64)
                self.assertEqual([p['text'] for p in payload['source_parts']],[p['text'] for p in unit['parts']])
                self.assertEqual([n['text'] for n in payload['nodes']],[n['text'] for n in unit['nodes']])
                self.assertEqual(before,encoded(payload))
                self.assertEqual(serialize_pack([unit]).decode('utf-8'),json.dumps(
                    {'contract':CONTRACT,'units':[unit]},sort_keys=True,ensure_ascii=False,separators=(',',':')))

    def test_same_text_different_sources_never_collapses_provenance(self):
        records=[]
        for doc in (1,2):
            batch=fixture_batch('Identical source text.',document_id=doc)
            from services.canary_representation import source_pin
            pin=source_pin(batch,source_id=doc);mf=make_manifest((pin,));a=batch.atoms[0]
            records.append(SidecarRecord.create(mf,hard_scope(mf),route(mf,pin,'ATOM_ONLY',a.atom_key),
                a.atom_key,atomic_projection(batch,a)))
        self.assertNotEqual(records[0].reference,records[1].reference)

    def test_no_benchmark_specialization_or_ranker_in_new_implementation(self):
        source=(Path(__file__).parent/'services/compact_evidence_pack.py').read_text()
        lowered=source.lower()
        for value in ('wowmd','turmeric','collagen','candidate_atoms','development_document_id',
                      'gold','case_id','support_id','typed_rrf','dense_statement','fts_statement'):
            self.assertNotIn(value,lowered)
        tree=ast.parse(source)
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                             and n.func.id in ('sorted','eval','exec') for n in ast.walk(tree)))


if __name__=='__main__':unittest.main()
