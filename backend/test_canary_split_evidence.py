"""Exact full-row and materialization equivalence, including fail-closed scope."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from sqlalchemy import delete, event, insert, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound

from database import canary_schema as s
from services.canary_contracts import CanaryError, Route, route
from services.canary_repository import document_values, where
from services.canary_retrieval import materialize
from services.structural_chunking import digest
from scripts.canary_stage_a import NOW
from scripts.canary_real_evaluation import score_case
from scripts.canary_split_evidence import SplitEvidenceRepository, split_atom_row
import test_canary_final_evaluation as fixtures


class SplitEvidenceTests(unittest.TestCase):
    def setUp(self):
        b = self.b = fixtures.ActualMeasuredRetrieval('test_actual_materialization_on_off_identical_sql_parameters_order_budgets_rankings')
        b.setUp(); self.addCleanup(b.doCleanups)
        self.conn, self.mf, self.hard = b.repo.conn, b.mf, b.hard
        self.pin = self.mf.documents[0]
        self.key = self.pin.atoms[0]
        self.scope = dict(document_values(self.mf, self.pin), atom_id=self.key)
        self.new = SplitEvidenceRepository(self.conn, b.base.approval, authorization=b.base.auth,
            lease_until=b.base.approval.expires_at, identities=[self.mf.canonical_hash()], clock=lambda: NOW)
        self.route = route(self.mf, self.pin, 'ATOM_ONLY', self.key)

    def test_complete_row_exact_equivalence_for_every_fixture_atom(self):
        rows = self.conn.execute(select(s.atoms).where(where(s.atoms, document_values(self.mf, self.pin)))).mappings().all()
        self.assertTrue(rows)
        for row in rows:
            new = split_atom_row(self.conn, dict(self.scope, atom_id=row['atom_id']))
            self.assertEqual(dict(row), new)
            self.assertEqual(digest(dict(row)), digest(new))
        self.assertEqual(self.b.repo.evidence(self.mf, self.hard, self.route, self.key, now=NOW),
                         self.new.evidence(self.mf, self.hard, self.route, self.key, now=NOW))

    def test_all_scope_predicates_remain_required(self):
        for key in (*s.DOC, 'atom_id'):
            with self.subTest(scope=key):
                value = self.scope[key]
                bad = value+1 if isinstance(value, int) else value+'wrong'
                with self.assertRaises(NoResultFound): split_atom_row(self.conn, dict(self.scope, **{key: bad}))

    def test_missing_atom_fails(self):
        self.conn.execute(delete(s.atoms).where(where(s.atoms, self.scope)))
        with self.assertRaises(NoResultFound): split_atom_row(self.conn, self.scope)

    def test_duplicate_exact_row_is_prevented_by_schema(self):
        row = dict(self.conn.execute(select(s.atoms).where(where(s.atoms, self.scope))).mappings().one())
        with self.assertRaises(IntegrityError): self.conn.execute(insert(s.atoms).values(**row))

    def test_payload_hash_corruption_fails(self):
        self.conn.execute(update(s.atoms).where(where(s.atoms, self.scope)).values(payload_hash='f'*64))
        with self.assertRaisesRegex(CanaryError, 'EVIDENCE_PAYLOAD_CORRUPTION'):
            split_atom_row(self.conn, self.scope)

    def test_validated_full_row_hash_is_required_when_supplied(self):
        with self.assertRaisesRegex(CanaryError, 'SPLIT_EVIDENCE_ROW_EQUIVALENCE_FAILED'):
            split_atom_row(self.conn, self.scope, expected_hash='f'*64)
        self.new.expected_rows = {}
        with self.assertRaisesRegex(CanaryError, 'VALIDATED_ATOM_ROW_REQUIRED'):
            self.new.evidence(self.mf, self.hard, self.route, self.key, now=NOW)

    def test_metadata_change_between_parts_fails_closed(self):
        def before(conn, stmt, scope, part):
            if part == 2:
                conn.execute(update(s.atoms).where(where(s.atoms, scope)).values(canonical_text='changed'))
        with self.assertRaises(NoResultFound): split_atom_row(self.conn, self.scope, before)

    def test_payload_change_between_parts_fails_closed(self):
        def before(conn, stmt, scope, part):
            if part == 2:
                conn.execute(update(s.atoms).where(where(s.atoms, scope)).values(payload={'changed': True}))
        with self.assertRaisesRegex(CanaryError, 'EVIDENCE_PAYLOAD_CORRUPTION'):
            split_atom_row(self.conn, self.scope, before)

    def test_wrong_org_bot_manifest_generation_document_source_and_atom_rejected_by_gate(self):
        for field in ('organization_id', 'bot_id'):
            hard = replace(self.hard, **{field: 999999})
            with self.subTest(field=field), self.assertRaises(CanaryError):
                self.new.evidence(self.mf, hard, self.route, self.key, now=NOW)
        for field, value in (('generation', 'wrong'), ('query_contract_hash', 'f'*64)):
            with self.subTest(field=field), self.assertRaises(CanaryError):
                self.new.evidence(self.mf.model_copy(update={field: value}), self.hard, self.route, self.key, now=NOW)
        for field, value in (('document_id', 999999), ('source_version', 999), ('source_sha256', 'f'*64)):
            source = self.pin.scope.revision.source.model_copy(update={field: value})
            revision = self.pin.scope.revision.model_copy(update={'source': source})
            scope = self.pin.scope.model_copy(update={'revision': revision})
            with self.subTest(field=field), self.assertRaises(CanaryError):
                self.new.evidence(self.mf, self.hard, self.route.model_copy(update={'source': scope}), self.key, now=NOW)
        with self.assertRaisesRegex(CanaryError, 'FOREIGN_ATOM'):
            self.new.evidence(self.mf, self.hard, self.route, 'f'*64, now=NOW)

    def test_stale_lifecycle_rejected(self):
        self.conn.execute(update(s.lifecycle).values(status='error', epoch=s.lifecycle.c.epoch+1))
        with self.assertRaises(CanaryError): self.new.evidence(self.mf, self.hard, self.route, self.key, now=NOW)

    def test_full_materialization_requests_order_units_budgets_status_and_scoring_identical(self):
        old = self.b.query()
        self.b.repo = self.new
        new = self.b.query()
        self.assertEqual(self.b.logical(old), self.b.logical(new))
        unit = old['materialized']['units'][0]
        gold = {'support': [dict(span_mapping='EXACT_UNIQUE_OCCURRENCE', legacy_exact=True,
            development_document_id=self.pin.scope.revision.source.document_id, legacy_chunk_id=1,
            candidate_atoms=[dict(atom=unit['key'], route=(unit['route']['kind'], unit['route']['key']))])]}
        self.assertEqual(score_case(old, gold, self.mf.lane.value, self.mf.effective(self.hard)),
                         score_case(new, gold, self.mf.lane.value, self.mf.effective(self.hard)))

    def test_each_split_sql_has_prior_durable_telemetry_and_success_hash(self):
        self.new.observer = self.b.telemetry
        checks = []
        def check(conn, cursor, sql, params, context, *args):
            pending = self.b.telemetry.pending
            if pending and pending['record'].get('transport') == 'EXACT_SPLIT_ROW_V1':
                record = pending['record']
                if record['phase'].startswith('BEFORE_SQL_PART'):
                    self.assertTrue((self.b.folder/f"{record['operation_ordinal']}-{record['phase']}.json").exists())
                    checks.append(record['transport_part'])
        event.listen(self.conn.engine, 'before_cursor_execute', check)
        self.addCleanup(event.remove, self.conn.engine, 'before_cursor_execute', check)
        self.new.evidence(self.mf, self.hard, self.route, self.key, now=NOW)
        self.assertEqual(checks, [1, 2])
        self.assertEqual(self.b.telemetry.latest['payload_hash_validation'], 'PASS')

    def test_actual_full_materialization_byte_and_unit_exclusions_are_identical(self):
        trace = self.b.query()
        fused = [dict(row, route=Route.model_validate(row['route'])) for row in trace['rrf']]
        for policy in (self.mf.policy.model_copy(update={'evidence_bytes': 1}),
                       self.mf.policy.model_copy(update={'evidence_units': 1})):
            outputs, requests = [], []
            for repo in (self.b.repo, self.new):
                calls = []
                # Only the fixture's budget differs; every actual repository
                # read still passes the real sealed manifest and authorization.
                def evidence(unused, hard, route, key, *, now):
                    calls.append((route, key))
                    return repo.evidence(self.mf, hard, route, key, now=now)
                adapter = SimpleNamespace(evidence=evidence, children=lambda unused, hard, route, now:
                    repo.children(self.mf, hard, route, now=now))
                outputs.append(materialize(fused, (), adapter, SimpleNamespace(policy=policy), self.hard, NOW))
                requests.append(calls)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(requests[0], requests[1])
            self.assertTrue(outputs[0]['exclusions'])


if __name__ == '__main__':
    unittest.main()
