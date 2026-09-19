"""Q1 wrapper tests without network or Phase-P artifact mutation."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
from time import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from services.canary_contracts import CanaryError, Lane
from services.canary_retrieval import run_query, materialize
from services.compact_evidence_pack import materialize_compact, encoded
from scripts.canary_stage_a import (fixture_batch, offline_repository, make_manifest,
    hard_scope, NOW, lexical_rank_fixture, State, synthetic_vector)
from scripts.run_compact_evidence_canary import CompactCanary, query_with_materializer, split_original
from scripts.canary_real_evaluation import safe_trace


class BindingEquivalence(unittest.TestCase):
    def test_same_bytecode_no_shared_global_mutation(self):
        alternate=Mock()
        bound=query_with_materializer(alternate)
        self.assertIs(bound.__code__,run_query.__code__)
        self.assertIsNot(bound.__globals__,run_query.__globals__)
        self.assertIs(bound.__globals__['materialize'],alternate)
        self.assertIs(run_query.__globals__['materialize'],materialize)
        self.assertEqual({k:v for k,v in bound.__globals__.items() if k!='materialize'},
                         {k:v for k,v in run_query.__globals__.items() if k!='materialize'})

    def test_actual_pipeline_upstream_identity_equivalence(self):
        batch=fixture_batch()
        with offline_repository() as repo:
            pin=repo.register_fixture_source(batch,source_id=1);mf=make_manifest((pin,));hard=hard_scope(mf)
            repo.create(mf,now=NOW);repo.stage(mf,batch,now=NOW)
            repo.seal_generation(mf,expected_build_identity=repo.build_identity(mf),now=NOW)
            repo.transition(mf,State.CANARY_READ,now=NOW)
            args=dict(query='Offline exact binding test',query_vector=synthetic_vector('q'),now=NOW,
                      fts_call=lambda:lexical_rank_fixture(batch,mf))
            old=run_query(repo,mf,hard,**args)
            new=query_with_materializer(materialize_compact)(repo,mf,hard,**args)
            for field in ('raw_dense','raw_fts','rrf','dense_routes','lexical_routes',
                          'lexical_reservations','manifest','effective_scope','hard_scope','query'):
                self.assertEqual(old[field],new[field])
            self.assertEqual([u['key'] for u in old['materialized']['units']],
                             [u['key'] for u in new['materialized']['units']])
            self.assertEqual(new['materialized']['bytes'],len(new['materialized']['model_bytes']))

    def test_control_binding_is_original_algorithm(self):
        fn=query_with_materializer(materialize)
        self.assertIs(fn.__globals__['materialize'],materialize)


class ResultFamily(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.runner=object.__new__(CompactCanary)
        self.runner.folder=root/'phase-p';self.runner.folder.mkdir()
        self.runner.output=root/'phase-q';self.runner.output.mkdir()

    def test_save_cannot_overwrite_phase_p(self):
        p=self.runner.folder/'case.json';p.write_bytes(b'original')
        self.runner.save('case',{'new':True},immutable=True)
        self.assertEqual(p.read_bytes(),b'original')
        self.assertTrue((self.runner.output/'case.json').exists())
        with self.assertRaises(CanaryError):self.runner.save('../phase-p/case',{})

    def test_new_family_success_is_immutable(self):
        self.runner.save('case',{'n':1},immutable=True)
        with self.assertRaises(CanaryError):self.runner.save('case',{'n':2},immutable=True)

    def test_no_lease_renewal_after_phase_p_closed(self):
        self.runner.retained_until=int(time())-1
        with self.assertRaisesRegex(CanaryError,'LEASE_EXPIRED'):self.runner.ensure_lease()

    def test_writable_repository_rejected_before_open(self):
        with self.assertRaisesRegex(CanaryError,'WRITES_FORBIDDEN'):
            with self.runner.repository(writable=True):pass

    def test_split_reader_requires_attested_complete_row(self):
        from scripts.canary_stage_a import fixture_batch, make_manifest, hard_scope
        from services.canary_representation import source_pin
        from services.canary_contracts import route
        batch=fixture_batch('Exact source.');pin=source_pin(batch,source_id=1)
        mf=make_manifest((pin,));key=pin.atoms[0];r=route(mf,pin,'ATOM_ONLY',key)
        repo=SimpleNamespace(_route_pin=lambda *args:pin,expected_rows={},conn=object())
        with patch('scripts.run_compact_evidence_canary.split_atom_row') as fetch:
            with self.assertRaisesRegex(CanaryError,'VALIDATED_ATOM_ROW_REQUIRED'):
                split_original(repo,mf,hard_scope(mf),r,key,now=NOW)
            fetch.assert_not_called()


if __name__=='__main__':unittest.main()
