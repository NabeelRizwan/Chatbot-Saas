"""Actual repository/SQL equivalence plus deterministic transport fault injection."""
import copy
from contextlib import nullcontext
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, select, update, text, func, literal_column
from sqlalchemy.dialects.postgresql import psycopg2
from sqlalchemy.exc import OperationalError

from database import canary_schema as s
from services.canary_contracts import CanaryError
from services.canary_repository import document_values, where
from services.structural_chunking import digest
from scripts.canary_stage_a import NOW
from scripts.canary_evaluation_transport import DatabaseTransportTimeout
from scripts.canary_read_recovery import (ObservedConnection, RecoveringConnection,
    ReadTelemetry, ReproducibleReadFailure, ReadRecoveryExhausted, OwnershipTransportFailure,
    operation_identity, readonly, BACKOFF)
from scripts.canary_split_evidence import SplitEvidenceRepository, split_atom_row
from scripts.canary_full_completion import ValidatedEvidenceRepository, FullCompletion
import test_canary_split_evidence as fixtures


class FaultConnection:
    """Only transport is doubled. Successful executions use real SQLAlchemy rows."""
    def __init__(self, raw, fail=False, fetch_fail=False):
        self.real, self.fail, self.fetch_fail = raw, fail, fetch_fail
        self.dialect, self.info = raw.dialect, {}
        self.closed = self.invalidated = False
        self.calls = []

    def execute(self, stmt, params):
        assert not self.closed and not self.invalidated
        self.calls.append(operation_identity(stmt, params, self.dialect))
        if self.fail:
            raise DatabaseTransportTimeout()
        result = self.real.execute(stmt, params)
        if self.fetch_fail:
            return NS(freeze=Mock(side_effect=DatabaseTransportTimeout()))
        return result

    def invalidate(self):
        self.invalidated = True

    def close(self):
        self.closed = True


class GenericReads(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.SplitEvidenceTests('test_missing_atom_fails')
        # Diagnostic probes run on a worker, just like psycopg2. Only this local
        # SQLite fixture disables its thread-affinity check; SQL still executes.
        with patch('scripts.canary_stage_a.create_engine', side_effect=lambda *a,**k:
                create_engine(*a,connect_args={'check_same_thread':False},**k)):
            self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.conn = self.f.conn
        self.records = []
        self.telemetry = ReadTelemetry(lambda r:self.records.append(copy.deepcopy(r)),
            dict(case=82, lane='STRUCTURAL_CANARY', manifest=self.f.mf.canonical_hash(),
                 generation=self.f.mf.generation))
        self.statement = select(s.memberships.c.atom_id).where(
            where(s.memberships, document_values(self.f.mf, self.f.pin)),
            s.memberships.c.entry_id == self.f.pin.entries[0]).order_by(s.memberships.c.atom_id).limit(33)

    def proxy(self, failures=(), *, validate=None, diagnostic=None, **kwargs):
        self.connections, self.delays = [], []
        states = iter(failures)
        def factory():
            state = next(states, False)
            conn = FaultConnection(self.conn, fail=state is True, fetch_fail=state == 'fetch')
            self.connections.append(conn)
            return conn
        proxy = RecoveringConnection(factory, validate or (lambda c:None), self.telemetry,
            diagnostic or (lambda *args:False), dialect=self.conn.dialect,
            sleeper=self.delays.append, **kwargs)
        self.addCleanup(proxy.close)
        return proxy

    def test_membership_scope_and_durable_before_actual_sql(self):
        checks=[]
        def before(conn,cursor,stmt,params,*unused):
            checks.append(self.records[-1])
            self.assertEqual(self.records[-1]['phase'],'BEFORE_SQL')
        event.listen(self.conn.engine,'before_cursor_execute',before)
        try:
            actual=ObservedConnection(self.conn,self.telemetry).execute(self.statement).scalars().all()
        finally:
            event.remove(self.conn.engine,'before_cursor_execute',before)
        self.assertEqual(actual,self.conn.execute(self.statement).scalars().all())
        scope=checks[0]['source_scope']
        self.assertEqual(scope['entry_id'],self.f.pin.entries[0])
        self.assertEqual(scope['document_id'],self.f.scope['document_id'])
        self.assertEqual(scope['manifest_hash'],self.f.mf.canonical_hash())

    def test_timeout_recovers_same_statement_binds_order_and_lane(self):
        proxy=self.proxy([True,False])
        expected=self.conn.execute(self.statement).all()
        self.assertEqual(proxy.execute(self.statement).all(),expected)
        self.assertEqual(self.connections[0].calls,self.connections[1].calls)
        self.assertTrue(self.connections[0].closed and self.connections[0].invalidated)
        self.assertEqual(self.delays,[1])
        self.assertEqual(self.telemetry.recoveries,1)
        self.assertEqual(self.records[-1]['phase'],'TRANSPORT_RECOVERY_SUCCESS')

    def test_fetch_time_failure_recovered_before_rows_escape(self):
        proxy=self.proxy(['fetch',False])
        self.assertEqual(proxy.execute(self.statement).all(),self.conn.execute(self.statement).all())
        self.assertTrue(self.connections[0].invalidated)

    def test_all_five_retries_then_three_probe_failure_is_terminal(self):
        probe=Mock(return_value=False)
        proxy=self.proxy([True]*6,diagnostic=probe)
        with self.assertRaisesRegex(ReproducibleReadFailure,'REPRODUCIBLE_DATABASE_READ_FAILURE'):
            proxy.execute(self.statement)
        self.assertEqual(len(self.connections),6)
        self.assertEqual(self.delays,list(BACKOFF))
        probe.assert_called_once()

    def test_successful_independent_probe_allows_second_cycle(self):
        probe=Mock(return_value=True)
        proxy=self.proxy([True]*6+[False],diagnostic=probe)
        self.assertEqual(proxy.execute(self.statement).all(),self.conn.execute(self.statement).all())
        self.assertEqual(self.delays,[*BACKOFF,1])
        self.assertEqual(len(self.connections),7)
        probe.assert_called_once()

    def test_second_cycle_bounded_to_five(self):
        proxy=self.proxy([True]*11,diagnostic=lambda *args:True)
        with self.assertRaisesRegex(ReadRecoveryExhausted,'CYCLES_EXHAUSTED'):
            proxy.execute(self.statement)
        self.assertEqual(len(self.connections),11)
        self.assertEqual(self.delays,list(BACKOFF)*2)

    def test_exhausted_cycles_escape_as_transport_not_unreadable_data(self):
        from scripts.canary_evaluation_transport import transient_transport
        self.assertTrue(transient_transport(ReadRecoveryExhausted('READ_RECOVERY_CYCLES_EXHAUSTED')))
        self.assertFalse(transient_transport(ReproducibleReadFailure('REPRODUCIBLE_DATABASE_READ_FAILURE')))

    def test_identity_auth_epoch_or_hash_failure_never_retried(self):
        for reason in ('IDENTITY','AUTHORIZATION','SOURCE_EPOCH','HASH'):
            def guard(conn): raise CanaryError(reason)
            proxy=self.proxy(validate=guard)
            with self.assertRaisesRegex(CanaryError,reason):proxy.execute(self.statement)
            self.assertEqual(len(self.connections),1)
            self.assertEqual(self.connections[0].calls,[])

    def test_revalidates_every_new_connection_and_never_uses_broken_one(self):
        guard=Mock()
        proxy=self.proxy([True,True,False],validate=guard)
        proxy.execute(self.statement)
        self.assertEqual(guard.call_count,3)
        self.assertEqual([len(c.calls) for c in self.connections],[1,1,1])

    def test_lost_ownership_escapes_to_fresh_unsaved_lane_not_false_read_failure(self):
        proxy=self.proxy(validate=Mock(side_effect=OwnershipTransportFailure('OWNERSHIP_CONNECTION_LOST')))
        with self.assertRaises(OwnershipTransportFailure):proxy.execute(self.statement)
        self.assertEqual(self.delays,[])
        self.assertEqual(len(self.connections),1)
        self.assertTrue(self.connections[0].invalidated)

    def test_read_bound_uses_new_connections(self):
        proxy=self.proxy(max_reads=1)
        for _ in range(3):proxy.execute(self.statement).all()
        self.assertEqual(len(self.connections),3)
        self.assertTrue(all(c.closed for c in self.connections[:2]))

    def test_write_lock_and_unapproved_text_never_executed(self):
        proxy=self.proxy()
        for stmt in (update(s.atoms).values(payload_hash='f'*64),select(s.atoms).with_for_update(),
                     text('DELETE FROM x'),text("SELECT nextval('x')"),text('SELECT pg_advisory_lock(1)')):
            with self.assertRaisesRegex(CanaryError,'SELECT_ONLY'):proxy.execute(stmt)
        self.assertEqual(self.connections,[])

    def test_mutating_cte_refused(self):
        stmt=select(update(s.atoms).values(payload_hash='f'*64).returning(s.atoms.c.atom_id).cte())
        self.assertFalse(readonly(stmt))

    def test_stateful_select_functions_and_nested_sql_never_retried(self):
        proxy=self.proxy()
        for stmt in (select(func.nextval('x')),select(func.setval('x',1)),
                     select(func.pg_advisory_lock(1)),select(func.customer_mutation()),
                     select(func.untrusted.count()),select(text("nextval('x')")),
                     select(literal_column("nextval('x')"))):
            with self.assertRaisesRegex(CanaryError,'SELECT_ONLY'):proxy.execute(stmt)
        self.assertEqual(self.connections,[])

    def test_artifact_write_failure_prevents_sql_and_retry(self):
        proxy=self.proxy()
        self.telemetry.writer=Mock(side_effect=OSError())
        with self.assertRaises(OSError):proxy.execute(self.statement)
        self.assertEqual(self.connections[0].calls,[])
        self.assertEqual(self.delays,[])

    def test_postgresql_compiled_membership_identity_exact_and_secret_free(self):
        value=operation_identity(self.statement,None,psycopg2.dialect())
        encoded=json.dumps(value)
        self.assertNotIn('SELECT',encoded)
        self.assertNotIn('params',encoded)
        self.assertEqual(len(value['bind_digest']),64)

    def test_payload_hash_corruption_is_not_transport_recovery(self):
        self.conn.execute(update(s.atoms).values(payload_hash='f'*64))
        proxy=self.proxy()
        with self.assertRaisesRegex(CanaryError,'HASH_MISMATCH'):
            proxy.execute(select(s.atoms).where(where(s.atoms,self.f.scope)))
        self.assertEqual(self.telemetry.retries,0)
        self.assertEqual(self.records[-1]['result'],'VALIDATION_FAILURE')

    def test_complete_retrieval_on_off_identical_sql_binds_routes_evidence_and_budgets(self):
        b=self.f.b
        b.repo=self.f.new
        statements=[]
        def record(conn,cursor,stmt,params,*unused):statements.append((stmt,copy.deepcopy(params)))
        event.listen(self.conn.engine,'before_cursor_execute',record)
        try:
            off=b.query(); old_sql=statements[:]; statements.clear()
            # Constructor's ownership check is unchanged but outside run_query.
            proxy=self.proxy()
            b.repo=ValidatedEvidenceRepository(proxy,b.base.approval,authorization=b.base.auth,
                lease_until=b.base.approval.expires_at,identities=[b.mf.canonical_hash()],clock=lambda:NOW)
            statements.clear()
            on=b.query()
            self.assertEqual(old_sql,statements)
            self.assertEqual(b.logical(off),b.logical(on))
        finally:event.remove(self.conn.engine,'before_cursor_execute',record)
        self.assertTrue(any(r['source_scope'].get('entry_id') for r in self.records))
        self.assertTrue(any(r['source_scope'].get('atom_id') for r in self.records))
        self.assertTrue(any(r.get('repository_method')=='children' for r in self.records))

    def test_split_payload_retry_exact_full_row(self):
        # First metadata succeeds; rotate before payload so it fails on a new connection.
        proxy=self.proxy([False,True,False],max_reads=1)
        old=split_atom_row(self.conn,self.f.scope)
        self.assertEqual(split_atom_row(proxy,self.f.scope,expected_hash=digest(old)),old)
        self.assertEqual(self.telemetry.recoveries,1)

    def test_sqlstate_connection_class_and_invalidation_are_retryable(self):
        from scripts.canary_evaluation_transport import transient_transport
        for state,invalid in (('08006',False),(None,True)):
            exc=OperationalError(None,None,NS(pgcode=state),connection_invalidated=invalid)
            self.assertTrue(transient_transport(exc))
        self.assertFalse(transient_transport(OperationalError(None,None,NS(pgcode='42501'))))

    def diagnostic_fixture(self, failures):
        connections=[];records=[];plans=[];states=iter(failures)
        raw=self.conn
        class ProbeConnection(FaultConnection):
            def execute(self, stmt, params=None):
                if str(stmt)=='SELECT pg_backend_pid()':return NS(scalar_one=lambda:42)
                return super().execute(stmt,params or {})
            def exec_driver_sql(self, stmt, params):
                plans.append(stmt)
                return NS(scalar_one=lambda:[{'Plan':{'Node Type':'Index Scan'}}])
        def factory():
            conn=ProbeConnection(raw,fail=next(states));connections.append(conn);return conn
        runner=NS(reads=self.telemetry,fresh_raw=factory,revalidate_read_connection=Mock(),
            session='a'*32,db=NS(engine=NS(connect=lambda:nullcontext(object()))),
            save=lambda name,record,**kw:records.append(record))
        return runner,connections,records,plans

    def test_actual_diagnostic_requires_three_independent_failed_probes(self):
        r,conns,records,plans=self.diagnostic_fixture([True]*3)
        with patch('scripts.canary_full_completion.observer_sample',return_value={'visible':True}):
            self.assertFalse(FullCompletion.diagnostic(r,self.statement,None,{},0))
        self.assertEqual(len(conns),3);self.assertEqual(r.revalidate_read_connection.call_count,3)
        self.assertTrue(all(c.closed and c.invalidated for c in conns))
        self.assertTrue(all(v['result']=='FAILURE' for v in records));self.assertFalse(plans)

    def test_observer_failure_does_not_override_successful_exact_probe(self):
        r,conns,records,plans=self.diagnostic_fixture([False])
        with patch('scripts.canary_full_completion.observer_sample',side_effect=DatabaseTransportTimeout()):
            self.assertTrue(FullCompletion.diagnostic(r,self.statement,None,{},0))
        self.assertEqual(len(conns),1);self.assertTrue(conns[0].closed)
        self.assertEqual(records[0]['result'],'SUCCESS');self.assertIn('observer_failure',records[0])
        self.assertGreater(records[0]['client_size_bytes']['total_fields'],0)
        self.assertEqual(len(plans),1);self.assertTrue(plans[0].startswith('EXPLAIN (FORMAT JSON)'))
        self.assertNotIn('ANALYZE',plans[0])

    def test_diagnostic_identity_failure_stops_before_exact_query(self):
        r,conns,records,plans=self.diagnostic_fixture([False]*3)
        r.revalidate_read_connection.side_effect=CanaryError('IDENTITY_CHANGED')
        with self.assertRaisesRegex(CanaryError,'IDENTITY_CHANGED'):
            FullCompletion.diagnostic(r,self.statement,None,{},0)
        self.assertEqual(len(conns),1);self.assertEqual(conns[0].calls,[])
        self.assertTrue(conns[0].closed and conns[0].invalidated);self.assertFalse(plans)


if __name__=='__main__': unittest.main()
