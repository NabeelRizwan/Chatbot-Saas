"""Focused Stage A tests. PostgreSQL execution is intentionally a separate HOLD."""
from dataclasses import replace
from hashlib import sha256
import ast
import json
import math
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex

from database import canary_schema as s
from services.canary_contracts import *
from services.canary_representation import prepare_batch, source_pin, primary_routes, atomic_projection
from services.canary_repository import CanaryRepository, document_values, source_values, where
from services.canary_retrieval import Hit, normalize, typed_rrf, reserve_witnesses, run_query
from services.structural_chunking import digest
from services import structural_retrieval_entries_v2 as m
from services.hybrid_retrieval import weighted_rrf, ChannelCandidate, HybridConfig
from scripts.canary_stage_a import (fixture_batch, make_manifest, offline_repository, hard_scope,
    approval, lexical_rank_fixture, compare_mechanical_lanes, NOW, GOLD)

ROOT=Path(__file__).resolve().parents[1]


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch=fixture_batch(); cls.pin=source_pin(cls.batch,source_id=1); cls.manifest=make_manifest((cls.pin,))

    def test_frozen_nested(self):
        for obj,field,value in ((self.manifest,'generation','x'),(self.manifest.policy,'rrf_k',2),
                                (self.pin,'source_id',2)):
            with self.assertRaises(ValidationError): setattr(obj,field,value)
    def test_canonical_roundtrip(self):
        self.assertEqual(Manifest.model_validate_json(self.manifest.canonical_json()),self.manifest)
    def test_identity_changes(self):
        for field,value in (('run_id','other'),('generation','other'),('query_contract_hash',digest('other')),
                             ('evaluation_hash',digest('other')),('policy',Policy(rrf_k=61))):
            self.assertNotEqual(self.manifest.canonical_hash(),self.manifest.model_copy(update={field:value}).canonical_hash())
    def test_profile_real_refused(self):
        p=Profile(source='REAL_PROVIDER',provider='gemini',model='gemini-embedding-001',configuration_hash=digest('real'),vector_attestation=VECTOR_ATTESTATION)
        with self.assertRaisesRegex(CanaryError,'NOT_AUTHORIZED'): p.require_stage_a()
        self.assertNotEqual(p.canonical_hash(),SYNTHETIC_PROFILE.canonical_hash())
    def test_no_fake_gemini(self):
        with self.assertRaises(ValidationError): Profile(source='SYNTHETIC_TEST',provider='gemini',model='gemini-embedding-001',configuration_hash=digest('real'),vector_attestation=VECTOR_ATTESTATION)
    def test_vectors_repeat(self): self.assertEqual(synthetic_vector('é'),synthetic_vector('é'))
    def test_vectors_distinct(self): self.assertNotEqual(synthetic_vector('a'),synthetic_vector('b'))
    def test_vectors_dimension(self): self.assertEqual(len(synthetic_vector('a')),768)
    def test_vectors_finite(self): self.assertTrue(all(math.isfinite(v) for v in synthetic_vector('a')))
    def test_vectors_nonzero(self): self.assertGreater(sum(v*v for v in synthetic_vector('a')),0)
    def test_pgvector_float32_decoding(self):
        import numpy as np
        self.assertEqual(validate_vector(np.asarray(synthetic_vector('a'),dtype=np.float32)),synthetic_vector('a'))
    def test_operator_expiry(self):
        with self.assertRaises(ValidationError): Approval(**(approval().model_dump()|{'expires_at':NOW-2}))
    def test_production_refusal(self):
        with self.assertRaises(ValidationError): Approval(**(approval().model_dump()|{'environment':'production'}))
    def test_no_zero_rrf_weights(self):
        with self.assertRaises(ValidationError): Policy(dense_weight=0,fts_weight=0)
    def test_hard_none_bounded(self): self.assertEqual(self.manifest.effective(hard_scope(self.manifest)),(1,))
    def test_hard_empty_empty(self): self.assertEqual(self.manifest.effective(hard_scope(self.manifest,())),())
    def test_source_id_intersection(self):
        h=replace(hard_scope(self.manifest),authorized_source_ids=(999,))
        self.assertEqual(self.manifest.effective(h),())
    def test_version_intersection(self):
        h=replace(hard_scope(self.manifest),active_document_versions=((1,2,None),))
        self.assertEqual(self.manifest.effective(h),())
    def test_typed_key_inequality(self):
        r=route(self.manifest,self.pin,'ENTRY','same')
        self.assertNotEqual(r,r.model_copy(update={'kind':'ATOM_ONLY'}))
    def test_scope_identity_inequality(self):
        r=route(self.manifest,self.pin,'ENTRY','same')
        for field,value in (('run_id','x'),('generation','x'),('manifest',digest('x')),('profile',digest('x'))):
            self.assertNotEqual(r,r.model_copy(update={field:value}))


for name,vector in [('dimension', (1.,)*767),('nan',(float('nan'),)+(1.,)*767),
                    ('inf',(float('inf'),)+(1.,)*767),('zero',(0.,)*768),('bool',(True,)+(1.,)*767)]:
    def test(self,v=vector):
        with self.assertRaises(CanaryError): validate_vector(v)
    setattr(Contracts,'test_invalid_vector_'+name,test)
for name,changes in [('org',{'organization_id':2}),('bot',{'bot_id':2}),('profile',{'embedding_profile':None})]:
    def test(self,changes=changes):
        with self.assertRaises(CanaryError): self.manifest.effective(replace(hard_scope(self.manifest),**changes))
    setattr(Contracts,'test_wrong_hard_'+name,test)


class Repository(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.batch=fixture_batch()
    def setUp(self):
        self.ctx=offline_repository(); self.repo=self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__,None,None,None)
        self.pin=self.repo.register_fixture_source(self.batch,source_id=1)
        self.manifest=make_manifest((self.pin,)); self.hard=hard_scope(self.manifest)
        self.repo.create(self.manifest,now=NOW)
    def stage(self): self.repo.stage(self.manifest,self.batch,now=NOW)
    def ready(self):
        self.stage(); self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
        self.repo.transition(self.manifest,State.CANARY_READ,now=NOW)
    def test_partial_unreadable(self):
        with self.assertRaisesRegex(CanaryError,'NO_READ_LEASE'): self.repo.read_gate(self.manifest,self.hard,now=NOW)
    def test_partial_unsealable(self):
        with self.assertRaisesRegex(CanaryError,'INCOMPLETE'): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_ready_without_read_lease(self):
        self.stage(); self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
        with self.assertRaisesRegex(CanaryError,'NO_READ_LEASE'): self.repo.read_gate(self.manifest,self.hard,now=NOW)
    def test_invalid_transition(self):
        with self.assertRaises(CanaryError): self.repo.transition(self.manifest,State.CANARY_READ,now=NOW)
    def test_stage_after_cancel(self):
        self.repo.transition(self.manifest,State.CANCELLED,now=NOW)
        with self.assertRaises(CanaryError): self.stage()
    def test_cancel_before_seal(self):
        self.stage(); self.repo.transition(self.manifest,State.CANCELLED,now=NOW)
        with self.assertRaises(CanaryError): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_expiry(self):
        self.ready()
        with self.assertRaisesRegex(CanaryError,'EXPIRED'): self.repo.read_gate(self.manifest,self.hard,now=NOW+4000)
    def test_expiry_uses_fresh_clock(self):
        self.ready(); self.repo.clock=lambda:NOW+4000
        with self.assertRaisesRegex(CanaryError,'EXPIRED'): self.repo.read_gate(self.manifest,self.hard,now=NOW)
    def test_source_epoch_release(self):
        self.ready(); token=self.repo.read_gate(self.manifest,self.hard,now=NOW)
        self.repo.conn.execute(update(s.lifecycle).values(epoch=1))
        with self.assertRaisesRegex(CanaryError,'LEASE_CHANGED'): self.repo.read_gate(self.manifest,self.hard,now=NOW,expected_epoch=token)
    def test_off_blocks_result(self):
        self.ready(); self.repo.transition(self.manifest,State.OFF,now=NOW)
        with self.assertRaises(CanaryError): self.repo.dense(self.manifest,self.hard,synthetic_vector('q'),now=NOW)
    def test_complete_inventory(self):
        self.ready(); counts=self.repo.counts(self.manifest)
        self.assertEqual(counts['canary_entry_vectors'],len(self.batch.entries))
        self.assertEqual(counts['canary_atoms'],len(self.batch.atoms))
        self.assertEqual(counts['canary_entry_atom_spans'],sum(len(e.mappings) for e in self.batch.entries))
    def test_missing_vector(self):
        self.stage(); self.repo.conn.execute(delete(s.vectors))
        with self.assertRaises(CanaryError): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_missing_fts_atom(self):
        self.stage(); self.repo.conn.execute(delete(s.atoms))
        with self.assertRaises(CanaryError): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_corrupt_mapping(self):
        self.stage(); self.repo.conn.execute(update(s.spans).values(node_start=s.spans.c.node_start+1,node_end=s.spans.c.node_end+1))
        with self.assertRaisesRegex(CanaryError,'SPAN'): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_foreign_node_database_rejected(self):
        self.stage()
        with self.assertRaises(IntegrityError):
            with self.repo.conn.begin_nested(): self.repo.conn.execute(update(s.spans).values(node_key='f'*64))
    def test_corrupt_projection(self):
        self.stage(); self.repo.conn.execute(update(s.atoms).values(canonical_text='changed'))
        with self.assertRaisesRegex(CanaryError,'PROJECTION'): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_missing_vector_input(self):
        with self.assertRaises(CanaryError): self.repo.stage(self.manifest,self.batch,now=NOW,supplied_vectors={})
    def test_extra_vector_input(self):
        values={e.entry_key:synthetic_vector(e.text) for e in self.batch.entries}; values['unknown']=synthetic_vector('x')
        with self.assertRaises(CanaryError): self.repo.stage(self.manifest,self.batch,now=NOW,supplied_vectors=values)
    def test_swapped_vector_input(self):
        values={e.entry_key:synthetic_vector('foreign') for e in self.batch.entries}
        with self.assertRaises(CanaryError): self.repo.stage(self.manifest,self.batch,now=NOW,supplied_vectors=values)
    def test_source_changed_before_seal(self):
        self.stage(); self.repo.conn.execute(update(s.lifecycle).values(source_fingerprint='f'*64))
        with self.assertRaises(CanaryError): self.repo.transition(self.manifest,State.INDEX_READY,now=NOW)
    def test_cleanup_owned_only(self):
        other=make_manifest((self.pin,),run='other')
        self.repo.create(other,now=NOW); self.repo.stage(other,self.batch,now=NOW)
        self.ready(); self.repo.transition(self.manifest,State.OFF,now=NOW)
        self.repo.delete_run(self.manifest)
        self.assertFalse(any(self.repo.counts(self.manifest).values()))
        self.assertEqual(self.repo.counts(other)['canary_entries'],len(self.batch.entries))
        self.assertEqual(self.repo.conn.execute(select(func.count()).select_from(s.sources)).scalar_one(),1)
        self.assertEqual(self.repo.conn.execute(select(s.sources.c.payload_hash)).scalar_one(),self.batch.canonical_hash())
    def test_cleanup_readable_refused(self):
        self.ready()
        with self.assertRaises(CanaryError): self.repo.delete_run(self.manifest)
    def test_cleanup_failure_not_success(self):
        self.stage(); self.repo.transition(self.manifest,State.OFF,now=NOW)
        with patch.object(self.repo.conn,'execute',side_effect=RuntimeError('injected cleanup failure')):
            with self.assertRaises(RuntimeError): self.repo.delete_run(self.manifest)
        self.assertEqual(self.repo.counts(self.manifest)['canary_runs'],1)
    def test_manifest_digest_mismatch(self):
        self.ready(); bad=self.manifest.model_copy(update={'generation':'foreign'})
        with self.assertRaises(CanaryError): self.repo.read_gate(bad,self.hard,now=NOW)
    def test_database_marker_refused(self):
        bad=self.repo.approval.model_copy(update={'ownership_marker':'unknown'})
        with self.assertRaises(CanaryError): CanaryRepository(self.repo.conn,bad)
    def test_dense_empty(self):
        self.ready(); self.assertEqual(self.repo.dense(self.manifest,hard_scope(self.manifest,()),synthetic_vector('q'),now=NOW),())
    def test_dense_scope_before_limit(self):
        self.ready(); other_batch=fixture_batch('Foreign exact query',document_id=2)
        pin=self.repo.register_fixture_source(other_batch,source_id=2)
        other=make_manifest((pin,),run='other')
        self.repo.create(other,now=NOW); self.repo.stage(other,other_batch,now=NOW)
        self.repo.transition(other,State.INDEX_READY,now=NOW); self.repo.transition(other,State.CANARY_READ,now=NOW)
        vector=synthetic_vector(other_batch.entries[0].text)
        hits=self.repo.dense(self.manifest,self.hard,vector,now=NOW)
        self.assertTrue(hits); self.assertTrue(all(h.route.source.revision.source.document_id==1 for h in hits))
    def test_fts_not_faked_on_sqlite(self):
        self.ready()
        with self.assertRaisesRegex(RuntimeError,'HOLD'): self.repo.fts(self.manifest,self.hard,'word',now=NOW)
    def test_pg_dense_materialized_scope_sql(self):
        sql=str(self.repo.dense_statement(self.manifest,self.hard).compile(dialect=postgresql.dialect()))
        for fragment in ('eligible_sources AS MATERIALIZED','eligible_vectors AS MATERIALIZED','<=>','vector(768)',
                         'source_fingerprint','profile_hash','revision','crawl_id','expires_at','ORDER BY','LIMIT'):
            self.assertIn(fragment,sql)
        self.assertLess(sql.index('source_fingerprint'),sql.index('ORDER BY'))
    def test_pg_fts_scope_and_parameterization(self):
        sql=str(self.repo.fts_statement(self.manifest,self.hard).compile(dialect=postgresql.dialect()))
        for fragment in ('websearch_to_tsquery','ts_rank_cd','@@','querytree','numnode','query_text','eligible_sources AS MATERIALIZED'):
            self.assertIn(fragment,sql)
        self.assertNotIn('ILIKE',sql); self.assertNotIn('SELECT * FROM chunks',sql)
        self.assertLess(sql.index('source_fingerprint'),sql.index('ORDER BY'))
        self.assertIn('LEFT OUTER JOIN',sql); self.assertIn('query_nodes',sql)
    def test_reverse_forward_exact(self):
        self.ready()
        for e in self.batch.entries:
            r=route(self.manifest,self.pin,'ENTRY',e.entry_key)
            self.assertEqual(set(self.repo.children(self.manifest,self.hard,r,now=NOW)),set(e.evidence_atoms))
    def test_pipeline_trace_and_budget(self):
        self.ready(); result=run_query(self.repo,self.manifest,self.hard,query='fixture',query_vector=synthetic_vector('q'),now=NOW,
                                       fts_call=lambda:lexical_rank_fixture(self.batch,self.manifest))
        self.assertEqual(result['mode'],'full_hybrid'); self.assertEqual(result['source_revalidation'],'PASS')
        self.assertLessEqual(result['materialized']['bytes'],131072); self.assertLessEqual(len(result['materialized']['units']),48)
        self.assertEqual(len(result['lexical_ledger']),len(self.batch.atoms)); self.assertEqual(result['cache'],'DISABLED')
    def test_budget_incomplete(self):
        other=make_manifest((self.pin,),run='tiny',policy=Policy(evidence_bytes=1))
        self.repo.create(other,now=NOW); self.repo.stage(other,self.batch,now=NOW)
        self.repo.transition(other,State.INDEX_READY,now=NOW); self.repo.transition(other,State.CANARY_READ,now=NOW)
        result=run_query(self.repo,other,hard_scope(other),query='q',query_vector=synthetic_vector('q'),now=NOW,fts_call=lambda:())
        self.assertEqual(result['final_status'],'INCOMPLETE_BUDGET'); self.assertEqual(result['materialized']['units'],[])
    def test_both_channels_failure(self):
        self.ready()
        def fail(): raise TimeoutError('sensitive data not to be returned')
        with self.assertRaisesRegex(CanaryError,'BOTH_CHANNELS_FAILED'):
            run_query(self.repo,self.manifest,self.hard,query='q',query_vector=synthetic_vector('q'),now=NOW,dense_call=fail,fts_call=fail)
    def test_authorization_not_degradation(self):
        self.ready()
        def fail(): raise CanaryError('FOREIGN_HARD_SCOPE')
        with self.assertRaisesRegex(CanaryError,'FOREIGN_HARD_SCOPE'):
            run_query(self.repo,self.manifest,self.hard,query='q',query_vector=synthetic_vector('q'),now=NOW,dense_call=fail,fts_call=lambda:())


for field,value in [('status','processing'),('status','deleted'),('status','failed'),('status','superseded'),
                    ('processing','pending'),('crawl_status','failed'),('active_crawl_id',999),('revision_state','active')]:
    def test(self,f=field,v=value):
        self.ready(); self.repo.conn.execute(update(s.lifecycle).values(**{f:v}))
        with self.assertRaisesRegex(CanaryError,'STALE'): self.repo.read_gate(self.manifest,self.hard,now=NOW)
    setattr(Repository,'test_lifecycle_'+field+'_'+str(value),test)
for field,value in [('organization_id',2),('bot_id',2),('generation','other'),('manifest_hash','f'*64),
                    ('document_id',2),('document_version_id','other'),('source_version',2),('source_hash','f'*64),
                    ('revision','other'),('profile_hash','f'*64),('crawl_id',2),('policy_hash','f'*64)]:
    def test(self,f=field,v=value):
        self.stage(); row=dict(self.repo.conn.execute(select(s.vectors)).mappings().first()); row[f]=v
        with self.assertRaises(IntegrityError):
            with self.repo.conn.begin_nested(): self.repo.conn.execute(insert(s.vectors).values(**row))
    setattr(Repository,'test_database_foreign_vector_'+field,test)
for failed in ('dense','fts'):
    def test(self,failed=failed):
        self.ready()
        def fail(): raise TimeoutError('secret must not appear')
        args={'dense_call':fail,'fts_call':lambda:()} if failed=='dense' else {'fts_call':fail}
        result=run_query(self.repo,self.manifest,self.hard,query='q',query_vector=synthetic_vector('q'),now=NOW,**args)
        self.assertEqual(result['mode'],'fts_only' if failed=='dense' else 'dense_only')
        self.assertNotIn('secret must',json.dumps(result))
    setattr(Repository,'test_degradation_'+failed,test)


class Routing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch=fixture_batch(); cls.pin=source_pin(cls.batch,source_id=1); cls.manifest=make_manifest((cls.pin,))
    def test_m_exact_import(self):
        original=self.batch.canonical_hash(); b,atoms,routes,maps=prepare_batch(self.batch)
        self.assertEqual(b.canonical_hash(),original); self.assertEqual(len(atoms),len(b.atoms))
        self.assertEqual(len(routes),len(b.atoms)); self.assertEqual(b.coverage.unaccounted_bytes,0)
    def test_projection_repeat(self):
        for a in self.batch.atoms: self.assertEqual(atomic_projection(self.batch,a),atomic_projection(self.batch,a))
    def test_projection_utf8_provenance(self):
        b=fixture_batch('# Café\n\nRésumé: naïve.'); nodes={n.identity.node_key:n for n in b.evidence.source_graph.nodes}
        for a in b.atoms:
            p=atomic_projection(b,a); raw=p['canonical_text'].encode()
            for v in p['projection_maps']:
                x,y=v['node_slice']; start,end=v['projection_slice']
                self.assertEqual(nodes[v['node']['node_key']].text.encode()[x:y],raw[start:end])
    def test_equal_occurrences_not_text_dedup(self):
        b=fixture_batch('# Repeated\n\nSame statement.\n\nSame statement.')
        projections=[atomic_projection(b,a) for a in b.atoms]
        self.assertGreaterEqual(sum(p['canonical_text'].count('Same statement.') for p in projections),2)
    def test_primary_heading_exact(self):
        routes=primary_routes(self.batch)
        for a in self.batch.heading_allocations:
            if a.witness_entry: self.assertEqual(routes[a.atom_key],('ENTRY',a.witness_entry))
    def test_primary_body_minimum(self):
        routes=primary_routes(self.batch)
        for a in self.batch.atoms:
            choices=[(v.part_index,e.ordinal,e.entry_key) for e in self.batch.entries for v in e.memberships
                     if v.atom_key==a.atom_key and v.usage=='body']
            if choices: self.assertEqual(routes[a.atom_key],('ENTRY',min(choices)[2]))
    def test_atom_only(self):
        from scripts.structural_retrieval_heading_gold import cases,base
        old=base(next(x for x in cases() if x['name']=='lexical_descendant'))
        b=m.revise_heading_allocation(old,scope=old.scope)
        self.assertTrue(any(kind=='ATOM_ONLY' for kind,key in primary_routes(b).values()))
    def test_continuation_whole(self):
        b=fixture_batch('# Long\n\n'+'A continuing statement with exact quantities. '*700)
        split=[a for a in b.atoms if len(a.source_parts)>1]; self.assertTrue(split)
        for a in split:
            p=atomic_projection(b,a)
            self.assertEqual(len(p['source_parts']),len(a.source_parts))
            self.assertEqual([x['part_index'] for x in p['source_parts']],list(range(len(a.source_parts))))
    def test_rrf_missing_one_based(self):
        r=route(self.manifest,self.pin,'ENTRY',self.pin.entries[0])
        result=typed_rrf(((r,1),),(),Policy())
        self.assertEqual(result[0]['total'],1/61); self.assertEqual(result[0]['fts_contribution'],0)
    def test_collapse_40_no_multiplier(self):
        r=route(self.manifest,self.pin,'ENTRY',self.pin.entries[0])
        hits=tuple(Hit(r,str(i),i,100-i) for i in range(1,41))
        normalized=normalize(hits,self.manifest,(1,))
        self.assertEqual(normalized,((r,1),)); self.assertEqual(typed_rrf((),normalized,Policy())[0]['total'],1/61)
    def test_witness_8_and_two_first(self):
        routes=[route(self.manifest,self.pin,'ENTRY',self.pin.entries[i]) for i in range(4)]
        hits=tuple(Hit(routes[(i-1)//10],str(i),i,1) for i in range(1,41))
        reserved=reserve_witnesses(hits,Policy())
        self.assertEqual([h.rank for h in reserved],[1,2,11,12,21,22,31,32])
    def test_witness_fills_unused(self):
        r=route(self.manifest,self.pin,'ENTRY',self.pin.entries[0])
        self.assertEqual(len(reserve_witnesses(tuple(Hit(r,str(i),i,1) for i in range(1,41)),Policy())),8)
    def test_witness_inside_unit_cap(self):
        r=route(self.manifest,self.pin,'ENTRY',self.pin.entries[0])
        self.assertEqual(len(reserve_witnesses(tuple(Hit(r,str(i),i,1) for i in range(1,41)),Policy(evidence_units=3))),3)
    def test_rrf_equivalence(self):
        pin=self.pin.model_copy(update={'entries':(),'legacy_members':(2,10,30)})
        mf=make_manifest((pin,),lane=Lane.LEGACY_CONTROL)
        routes={i:route(mf,pin,'LEGACY_CHUNK',i) for i in (2,10,30)}
        for dense,lex in [((2,10),(10,30)),((2,),(10,)),((),(30,10,2)),((2,10,30),())]:
            old=weighted_rrf([ChannelCandidate(i,1,99,r,'dense') for r,i in enumerate(dense,1)],
                [ChannelCandidate(i,1,.01,r,'fts') for r,i in enumerate(lex,1)],HybridConfig())
            new=typed_rrf(tuple((routes[i],r) for r,i in enumerate(dense,1)),tuple((routes[i],r) for r,i in enumerate(lex,1)),Policy())
            self.assertEqual([(x.chunk_id,x.score,x.rank) for x in old],[(int(x['route'].key),x['total'],x['rank']) for x in new])
    def test_scope_failure_before_fusion(self):
        hit=lexical_rank_fixture(self.batch,self.manifest)[0]
        bad=replace(hit,route=hit.route.model_copy(update={'generation':'other'}))
        with self.assertRaises(CanaryError): normalize((bad,),self.manifest,(1,))


class Boundaries(unittest.TestCase):
    def test_target_explicit_allowlist(self):
        from services.canary_database_guard import DisposableTarget,validate_target
        fp=digest({'host':'example.invalid','port':5432,'database':'disposable'})
        approved=approval().model_copy(update={'environment':'disposable_test','database_identity':fp})
        target=DisposableTarget(host_database_fingerprint=fp,ownership_marker=approved.ownership_marker,
                                approval_reference=approved.operator_reference)
        self.assertEqual(validate_target('postgresql://example.invalid:5432/disposable',target,approved),fp)
        for url in ('postgresql://another.invalid:5432/disposable','postgresql://example.invalid:5432/other','sqlite:///file'):
            with self.assertRaisesRegex(CanaryError,'REFUSED'): validate_target(url,target,approved)
        with self.assertRaises(CanaryError): validate_target('postgresql://example.invalid:5432/disposable',target,approval())
    def test_pg_schema_compile(self):
        dialect=postgresql.dialect()
        ddl='\n'.join(str(CreateTable(t).compile(dialect=dialect)) for t in s.metadata.sorted_tables)
        self.assertIn('VECTOR(768)',ddl); self.assertIn('FOREIGN KEY',ddl); self.assertIn('SYNTHETIC_TEST',ddl)
        self.assertNotIn('REFERENCES chunks',ddl); self.assertNotIn('REFERENCES documents',ddl)
    def test_gin_expression(self):
        index=next(i for i in s.atoms.indexes if i.name=='ix_canary_atoms_content_fts_en_v1')
        ddl=str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        self.assertIn('USING gin',ddl); self.assertIn("to_tsvector('english'::regconfig, coalesce(canonical_text, ''))",ddl)
    def test_pg_guard_locks(self):
        ddl='\n'.join(s.postgres_seal_guards())
        self.assertIn('FOR UPDATE',ddl); self.assertIn('CANARY_IMMUTABLE',ddl)
    def test_no_serving_imports(self):
        forbidden={'embedding_service','rag_service','rag_planning','tenant_cache_service','connection','models','fastapi'}
        for path in (ROOT/'backend/services').glob('canary_*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(set((x or '').split('.'))&forbidden for x in imports),str(path))
    def test_network_forbidden(self):
        with (patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')),
              patch.object(socket,'getaddrinfo',side_effect=AssertionError('network forbidden'))):
            r=compare_mechanical_lanes()
        self.assertEqual(r['measurement'],'SYNTHETIC_OFFLINE_MECHANICS_ONLY')
        self.assertFalse(any(r['remaining_run_rows'].values()))
    def test_no_provider_or_env_url_lookup(self):
        for path in [*(ROOT/'backend/services').glob('canary_*.py'),ROOT/'backend/scripts/canary_stage_a.py']:
            source=path.read_text(encoding='utf-8')
            self.assertNotIn('os.getenv',source); self.assertNotIn('os.environ',source)
            self.assertNotIn('generate_embeddings',source); self.assertNotIn('generate_auxiliary',source)
    def test_gold_categories_frozen(self):
        gold=json.loads(GOLD.read_text(encoding='utf-8'))
        self.assertEqual(len(gold['obligations']),28); self.assertEqual(gold['expected']['foreign_hits'],0)
        self.assertEqual(sha256(GOLD.read_bytes()).hexdigest(),'e37ea082044798ffdbda8345183ec7b101023cfc8201c58bd72c85f11a5043e7')
    def test_real_gold_frozen(self):
        p=GOLD.parent/'real_corpus_retrieval_gold.json'
        side=json.loads(p.read_text(encoding='utf-8')); claimed=side.pop('sidecar_digest')
        self.assertEqual(digest(side),claimed)
        self.assertEqual(claimed,'11932248a247a41bdc7a227503468274ba0498b6367932e440d60a91265cfeb5')
        self.assertEqual(len(side['cases']),90)
        self.assertFalse(side['semantic_evaluation_authorized'])
        self.assertTrue(all(c['review_status'] for c in side['cases']))
    def test_original_gold_unchanged(self):
        self.assertEqual(sha256((ROOT/'.codex_real_corpus_v1/REAL_CORPUS_V1_EVAL_V1.json').read_bytes()).hexdigest(),
                         'e7d0314bd79bd6279f5b404ee28a9c2211e2d0ddf0313d938e10370b3f19f5b1')


if __name__=='__main__': unittest.main()
