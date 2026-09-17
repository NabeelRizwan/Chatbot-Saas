"""Frozen binary32 identity GOLD and runtime staging/seal tests; no network."""
import hashlib
import json
import locale
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from database import canary_schema as s
from services.canary_contracts import (
    CanaryError, Manifest, Profile, SYNTHETIC_PROFILE, VECTOR_ATTESTATION, State, Lane,
    canonicalize_vector_f32, canonical_vector_bytes, canonical_vector_digest, synthetic_vector,
)
from services.canary_repository import document_values, where
from services.structural_chunking import digest
from scripts.canary_stage_a import fixture_batch, offline_repository, make_manifest, NOW


GOLD_PATH = Path(__file__).parent / 'fixtures/canary_vector_f32_v1/gold.json'
GOLD = json.loads(GOLD_PATH.read_text(encoding='utf-8'))
GOLD_SHA = '59072664a720322ab1ffefc0a2891de458a2625bfadc3f83936d2dbad105e877'


class Binary32(unittest.TestCase):
    def test_gold_frozen(self):
        self.assertEqual(hashlib.sha256(GOLD_PATH.read_bytes().replace(b'\r\n', b'\n')).hexdigest(), GOLD_SHA)
        self.assertEqual(len(GOLD['required_cases']), 25)

    def test_repeated_coordinates(self):
        self.assertEqual(canonical_vector_bytes([0.1] * 768), bytes.fromhex('3dcccccd') * 768)

    def test_valid_768(self):
        self.assertEqual(len(canonicalize_vector_f32([0.1] * 768)), 768)
        self.assertEqual(len(canonical_vector_bytes([0.1] * 768)), 3072)

    def test_json_roundtrip(self):
        a = [0.6854400634765625] * 768
        b = json.loads('[' + ','.join(['0.68544006'] * 768) + ']')
        self.assertNotEqual(a, b)
        self.assertEqual(canonical_vector_bytes(a), canonical_vector_bytes(b))

    def test_f32_python_f32_stability(self):
        vector = canonicalize_vector_f32([x['value'] for x in GOLD['coordinates']] * 85 + [0.1] * 3)
        self.assertEqual(canonicalize_vector_f32(vector), vector)

    def test_digest_repeatability(self):
        for _ in range(3):
            self.assertEqual(canonical_vector_digest([0.1] * 768), GOLD['repeat']['sha256'])

    def test_one_coordinate_change(self):
        a = [0.1] * 768
        b = a.copy()
        b[767] = struct.unpack('!f', bytes.fromhex('3dccccce'))[0]
        self.assertNotEqual(canonical_vector_digest(a), canonical_vector_digest(b))

    def test_signed_zero(self):
        a = [0.0] * 767 + [1.0]
        b = [-0.0] * 767 + [1.0]
        self.assertEqual(canonical_vector_bytes(a), canonical_vector_bytes(b))
        self.assertEqual(canonical_vector_bytes(b)[:4], b'\0' * 4)

    def test_locale_independent(self):
        with patch.object(locale, 'localeconv', return_value={'decimal_point': ','}), \
             patch.object(locale, 'format_string', side_effect=AssertionError('no decimal formatting')):
            self.assertEqual(canonical_vector_digest([0.1] * 768), GOLD['repeat']['sha256'])

    def test_serialization_independent(self):
        vector = [0.1] * 768
        for encoded in (json.dumps(vector), json.dumps(vector, indent=2).replace('\n', '\r\n')):
            self.assertEqual(canonical_vector_digest(json.loads(encoded)), GOLD['repeat']['sha256'])

    def test_synthetic_repeatability(self):
        a = synthetic_vector('Provider-free UTF-8: café')
        self.assertEqual(a, synthetic_vector('Provider-free UTF-8: café'))
        self.assertEqual(a, canonicalize_vector_f32(a))
        self.assertEqual(canonical_vector_digest(a), canonical_vector_digest(list(a)))

    def test_provider_shaped_mock(self):
        mock_response = {'embedding': {'values': [0.1, -2.75, 1e-40] * 256}}
        values = mock_response['embedding']['values']
        self.assertEqual(canonical_vector_bytes(values), bytes.fromhex('3dcccccdc0300000000116c2') * 256)

    def test_old_profile_requires_explicit_new_version(self):
        old = SYNTHETIC_PROFILE.model_dump()
        old.pop('vector_attestation')
        with self.assertRaises(ValidationError):
            Profile.model_validate(old)

    def test_unknown_digest_version_refused(self):
        with self.assertRaises(ValidationError):
            Profile.model_validate(SYNTHETIC_PROFILE.model_dump() | {'vector_attestation': 'json-v0'})

    def test_version_bound_into_manifest_and_route_profile(self):
        self.assertEqual(SYNTHETIC_PROFILE.vector_attestation, VECTOR_ATTESTATION)
        self.assertNotEqual(SYNTHETIC_PROFILE.configuration_hash, hashlib.sha256(b'canary-synthetic-vector-v1').hexdigest())
        from services.canary_representation import source_pin
        manifest = make_manifest((source_pin(fixture_batch(), source_id=1),))
        old = manifest.model_dump(mode='json')
        old['profile'].pop('vector_attestation')
        self.assertNotEqual(digest(old), manifest.canonical_hash())
        with self.assertRaises(ValidationError):
            Manifest.model_validate(old)


for case in GOLD['coordinates']:
    def test(self, case=case):
        self.assertEqual(canonical_vector_bytes([case['value']] * 768), bytes.fromhex(case['hex']) * 768)
    setattr(Binary32, 'test_' + case['name'], test)

for name, values in (
    ('nan_rejected', [float('nan')] + [1.] * 767),
    ('positive_inf_rejected', [float('inf')] + [1.] * 767),
    ('negative_inf_rejected', [-float('inf')] + [1.] * 767),
    ('all_zero_rejected', [-0.] * 768),
    ('767_rejected', [1.] * 767), ('769_rejected', [1.] * 769),
    ('bool_rejected', [True] + [1.] * 767), ('string_rejected', ['1'] + [1.] * 767),
    ('overflow_rejected', [1e40] + [1.] * 767),
    ('underflow_zero_rejected', [1e-50] * 768),
):
    def test(self, values=values):
        with self.assertRaises(CanaryError):
            canonicalize_vector_f32(values)
    setattr(Binary32, 'test_' + name, test)


class Attestation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = fixture_batch()

    def setUp(self):
        self.ctx = offline_repository()
        self.repo = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.pin = self.repo.register_fixture_source(self.batch, source_id=1)
        self.manifest = make_manifest((self.pin,))
        self.repo.create(self.manifest, now=NOW)
        self.repo.stage(self.manifest, self.batch, now=NOW)

    def test_staged_digest_is_binary_not_old_json(self):
        row = self.repo.conn.execute(select(s.vectors).limit(1)).mappings().one()
        self.assertEqual(row['vector_hash'], canonical_vector_digest(row['embedding']))
        self.assertNotEqual(row['vector_hash'], digest(tuple(row['embedding'])))
        self.assertEqual(row['vector_attestation'], VECTOR_ATTESTATION)

    def test_postgres_decimal_readback_seals_exactly(self):
        # Model the observed JSON/pgvector text decoder, not a tolerance oracle.
        import numpy as np
        for row in self.repo.conn.execute(select(s.vectors)).mappings().all():
            short = [float(str(np.float32(x))) for x in row['embedding']]
            self.assertEqual(canonical_vector_bytes(short), canonical_vector_bytes(row['embedding']))
            self.repo.conn.execute(update(s.vectors).where(s.vectors.c.entry_id == row['entry_id']).values(embedding=short))
        self.repo.transition(self.manifest, State.INDEX_READY, now=NOW)

    def test_old_json_digest_refused_at_seal(self):
        row = self.repo.conn.execute(select(s.vectors).limit(1)).mappings().one()
        self.repo.conn.execute(update(s.vectors).where(s.vectors.c.entry_id == row['entry_id']).values(vector_hash=digest(tuple(row['embedding']))))
        with self.assertRaisesRegex(CanaryError, 'ENTRY_VECTOR_CORRUPTION'):
            self.repo.transition(self.manifest, State.INDEX_READY, now=NOW)

    def test_new_digest_does_not_authorize_changed_coordinate(self):
        row = self.repo.conn.execute(select(s.vectors).limit(1)).mappings().one()
        changed = list(row['embedding'])
        changed[0] = 0.25
        self.repo.conn.execute(update(s.vectors).where(s.vectors.c.entry_id == row['entry_id']).values(embedding=changed, vector_hash=canonical_vector_digest(changed)))
        with self.assertRaisesRegex(CanaryError, 'ENTRY_VECTOR_CORRUPTION'):
            self.repo.transition(self.manifest, State.INDEX_READY, now=NOW)

    def test_row_version_database_check(self):
        with self.assertRaises(IntegrityError), self.repo.conn.begin_nested():
            self.repo.conn.execute(update(s.vectors).values(vector_attestation='json-v0'))

    def test_manifest_roundtrip_preserves_attestation(self):
        restored = Manifest.model_validate_json(self.manifest.canonical_json())
        self.assertEqual(restored.profile.vector_attestation, VECTOR_ATTESTATION)
        self.assertEqual(restored.canonical_hash(), self.manifest.canonical_hash())

    def test_legacy_readback_uses_same_binary_attestation(self):
        import numpy as np
        chunks = [{'id': 1, 'text': 'A synthetic legacy source.'}]
        pin = self.pin.model_copy(update={'entries': (), 'legacy_members': (1,), 'batch_hash': digest(chunks)})
        legacy = make_manifest((pin,), lane=Lane.LEGACY_CONTROL)
        self.repo.create(legacy, now=NOW)
        self.repo.stage_legacy(legacy, pin, chunks, now=NOW)
        row = self.repo.conn.execute(select(s.legacy)).mappings().one()
        self.assertEqual(row['vector_hash'], canonical_vector_digest(row['embedding']))
        self.repo.conn.execute(update(s.legacy).values(embedding=[float(str(np.float32(x))) for x in row['embedding']]))
        self.repo.transition(self.manifest, State.INDEX_READY, now=NOW)

    def test_legacy_old_json_hash_rejected(self):
        chunks = [{'id': 1, 'text': 'A synthetic legacy source.'}]
        pin = self.pin.model_copy(update={'entries': (), 'legacy_members': (1,), 'batch_hash': digest(chunks)})
        legacy = make_manifest((pin,), lane=Lane.LEGACY_CONTROL)
        self.repo.create(legacy, now=NOW)
        self.repo.stage_legacy(legacy, pin, chunks, now=NOW)
        row = self.repo.conn.execute(select(s.legacy)).mappings().one()
        self.repo.conn.execute(update(s.legacy).values(vector_hash=digest(tuple(row['embedding']))))
        with self.assertRaisesRegex(CanaryError, 'INVALID_LEGACY_VECTOR'):
            self.repo.transition(self.manifest, State.INDEX_READY, now=NOW)


if __name__ == '__main__':
    unittest.main()
