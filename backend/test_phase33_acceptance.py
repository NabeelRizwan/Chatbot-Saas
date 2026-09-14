"""Offline orchestration guards plus actual frozen natural contract replay."""
from contextlib import ExitStack
from unittest.mock import patch
import unittest

from scripts import phase33_acceptance as run
from scripts import phase31_fixture as data
from test_resource_discovery import ResourceFixture


class Phase33HarnessTests(unittest.TestCase):
    def test_bulk_augmentation_preserves_original_and_scale(self):
        original=data.documents();augmented=run.augmented_documents()
        self.assertEqual(len(augmented),6000)
        self.assertEqual(len({r['id'] for r in augmented}),6000)
        by_id={r['id']:r for r in augmented}
        for row in original[:-72]: self.assertEqual(row,by_id[row['id']])
        self.assertTrue(all(r['organization_id']==29 and r['bot_id']==30 for r in augmented[-72:]))

    def test_natural_failure_prevents_expensive_benchmark(self):
        result={};calls=[]
        def setup(conn,result): result['migration_upgrade']=True
        def sql(engine,result): result['sql_security_checks']={str(i):True for i in range(68)}
        with patch.object(run.prior,'setup',side_effect=setup),patch.object(run.prior,'sql_and_security',side_effect=sql), \
             patch.object(run,'natural_gates',side_effect=run.GateFailure('former_four')), \
             patch.object(run,'handoffs') as handoff,patch.object(run.prior,'benchmarks') as benchmark:
            with self.assertRaises(run.GateFailure): run.run(None,None,result)
            handoff.assert_not_called();benchmark.assert_not_called()

    def test_sql_fail_closed_even_when_mapping_empty(self):
        def setup(conn,result): result['migration_upgrade']=True
        with patch.object(run.prior,'setup',side_effect=setup),patch.object(run.prior,'sql_and_security'),patch.object(run,'natural_gates') as gate:
            with self.assertRaises(run.GateFailure): run.run(None,None,{})
            gate.assert_not_called()

    def test_run_order_all_existing_expensive_checks_retained(self):
        order=[];result={}
        def setup(conn,result): order.append('setup');result['migration_upgrade']=True
        def sql(engine,result): order.append('sql');result['sql_security_checks']={str(i):True for i in range(68)}
        def bench(engine,result): order.append('612');result['benchmark']={s:{'gates':{'ok':True}} for s in ('development','heldout')}
        def concurrent(engine,conn,result):
            order.append('concurrency');result.update(concurrency={'stable':True,'leaks':0},concurrent_revision={'pass':True})
        def history(engine,result): order.append('historical');result['historical']={'pass':True}
        def cycle(conn,result):
            order.append('cycle');result.update(migration_downgrade=True,migration_reupgrade=True,fixture_preserved_after_downgrade=True)
        with ExitStack() as stack:
            for name,callback in (('setup',setup),('sql_and_security',sql),('benchmarks',bench),('concurrency_and_plans',concurrent),('historical',history),('cycle',cycle)):
                stack.enter_context(patch.object(run.prior,name,side_effect=callback))
            for name in ('natural_gates','handoffs','performance'):
                stack.enter_context(patch.object(run,name,side_effect=lambda *_,n=name:order.append(n)))
            stack.enter_context(patch.object(run.prior,'emit'))
            run.run(None,None,result)
        self.assertEqual(order,['setup','sql','natural_gates','handoffs','612','concurrency','performance','historical','cycle'])


class FrozenHistoryTests(ResourceFixture):
    def test_original_fifty_and_reviewed_fifty(self):
        for number,name,kind,aliases in data.NATURAL: self.add(number,name,kind=kind,aliases=aliases)
        self.project(*[r[0] for r in data.NATURAL])
        rows=[run.golden_record(self,i) for i in range(1,51)]
        self.assertEqual(sum(r['original_ok'] for r in rows),47)
        self.assertEqual(sum(r['reviewed_ok'] for r in rows),50,[r['id'] for r in rows if not r['reviewed_ok']])
        self.assertTrue(all(r['frozen_match'] for r in rows))
        self.assertEqual(sum(r['leaks'] for r in rows),0)


if __name__=='__main__': unittest.main()
