"""Offline proof that diagnostics mirror the exact guarded payload SELECT."""
import unittest
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import psycopg2
from services.canary_contracts import CanaryError
from services.structural_chunking import digest
from scripts.canary_payload_diagnostic import metadata_statement, payload_statement, reconstruct
from scripts.canary_split_evidence import split_atom_row
import test_canary_split_evidence as fixtures


class PayloadDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SplitEvidenceTests('test_missing_atom_fails')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.conn, self.scope = self.fixture.conn, self.fixture.scope
        self.full = split_atom_row(self.conn, self.scope)
        self.meta = {k:v for k,v in self.full.items() if k!='payload'}

    def test_exact_same_compiled_sql_and_parameters_as_split_transport(self):
        recorded=[]
        def before(conn, stmt, scope, part):recorded.append(stmt)
        split_atom_row(self.conn,self.scope,before)
        for actual,expected in zip((metadata_statement(self.scope),payload_statement(self.scope,self.meta)),recorded):
            a,b=actual.compile(dialect=psycopg2.dialect()),expected.compile(dialect=psycopg2.dialect())
            self.assertEqual(str(a),str(b));self.assertEqual(a.params,b.params)

    def test_incomplete_metadata_and_wrong_scope_refused(self):
        for meta in ({},dict(self.meta,bot_id=999999)):
            with self.assertRaises(CanaryError):payload_statement(self.scope,meta)

    def test_full_row_equality_required_and_safe_output(self):
        facts=reconstruct(self.meta,self.full['payload'],digest(self.full))
        self.assertEqual(facts['canonical_row_hash'],digest(self.full))
        self.assertNotIn('payload',facts);self.assertNotIn('canonical_text',facts)
        with self.assertRaises(CanaryError):reconstruct(self.meta,self.full['payload'],'f'*64)

    def test_corruption_refused(self):
        with self.assertRaises(CanaryError):reconstruct(self.meta,{'wrong':True},digest(self.full))

    def test_actual_diagnostic_reads_are_select_only(self):
        statements=[]
        def before(conn,cursor,stmt,*unused):statements.append(stmt)
        event.listen(self.conn.engine,'before_cursor_execute',before)
        try:
            metadata=dict(self.conn.execute(metadata_statement(self.scope)).mappings().one())
            value=self.conn.execute(payload_statement(self.scope,metadata)).scalar_one()
            reconstruct(metadata,value,digest(self.full))
        finally:event.remove(self.conn.engine,'before_cursor_execute',before)
        self.assertEqual(len(statements),2)
        self.assertTrue(all(sql.lstrip().upper().startswith('SELECT') for sql in statements))


if __name__=='__main__':unittest.main()
