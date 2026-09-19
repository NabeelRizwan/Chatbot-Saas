"""Offline safety checks for the evaluation-only exact atom diagnostic."""
import unittest

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import psycopg2

from database import canary_schema as s
from services.canary_contracts import CanaryError
from services.canary_repository import where
from services.structural_chunking import digest
from scripts.canary_exact_atom_diagnostic import atom_statement, row_facts, safe_plan


class ExactAtomDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.scope = {k: 1 if k in s.INTS else 'safe-identity' for k in s.DOC}
        self.scope['atom_id'] = 'a'*64

    def test_exact_statement_matches_repository_shape_and_parameters(self):
        expected = select(s.atoms).where(where(s.atoms, {k: self.scope[k] for k in s.DOC}),
                                        s.atoms.c.atom_id == self.scope['atom_id'])
        dialect = psycopg2.dialect()
        old, new = expected.compile(dialect=dialect), atom_statement(self.scope).compile(dialect=dialect)
        self.assertEqual(str(old), str(new))
        self.assertEqual(old.params, new.params)
        self.assertEqual(len(new.params), len(s.DOC)+1)

    def test_missing_or_extra_scope_refused(self):
        for scope in ({k: v for k, v in self.scope.items() if k != 'bot_id'}, dict(self.scope, extra=1)):
            with self.assertRaises(CanaryError):
                atom_statement(scope)

    def test_metadata_projection_does_not_fetch_large_fields(self):
        fields = [c for c in s.atoms.c if c.name not in ('canonical_text', 'payload')]
        stmt = atom_statement(self.scope, fields)
        self.assertNotIn('payload', stmt.selected_columns.keys())
        self.assertNotIn('canonical_text', stmt.selected_columns.keys())
        self.assertIn('payload_hash', stmt.selected_columns.keys())

    def test_plan_never_retains_literal_filters(self):
        plan = safe_plan({'Node Type': 'Index Scan', 'Index Name': 'canary_atoms_pkey',
                          'Filter': "atom_id='private-content'", 'Plans': [
                              {'Node Type': 'Seq Scan', 'Index Cond': "document_id=99"}]})
        self.assertNotIn('private-content', str(plan))
        self.assertNotIn('document_id=99', str(plan))
        self.assertEqual(plan['Filter scoped columns'], ['atom_id'])
        self.assertEqual(plan['Plans'][0]['Node Type'], 'Seq Scan')

    def test_row_output_contains_only_hash_sizes_and_validation(self):
        row = dict(self.scope, payload={'secret-content': 'unprinted'}, canonical_text='unprinted',
                   payload_hash=digest({'secret-content': 'unprinted'}))
        facts = row_facts(row)
        self.assertEqual(facts['payload_hash_validation'], 'PASS')
        self.assertNotIn('unprinted', str(facts))
        self.assertNotIn('secret-content', str(facts))
        row['payload_hash'] = 'b'*64
        with self.assertRaises(CanaryError):
            row_facts(row)


if __name__ == '__main__':
    unittest.main()
