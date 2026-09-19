"""Canary-only compact-evidence-pack-v1. No ranking, providers, or serving hook.

The sole model-facing representation is ``serialize_pack``. All its UTF-8 bytes
count, including the envelope, citation references, JSON syntax and separators.
Source parts and node text are deliberately both kept: neither is assumed to
subsume the other. Complete original atoms live in a request-local sidecar, not
in an unscoped cache. A reference is an identifier, never an authorization grant.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from time import perf_counter, process_time

from sqlalchemy import select

from database import canary_schema as schema
from services.canary_contracts import CanaryError, Lane, Route
from services.canary_repository import document_values, where
from services.canary_representation import evidence_view
from services.structural_chunking import digest


CONTRACT = 'compact-evidence-pack-v1'


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def require(condition, code):
    if not condition:
        raise CanaryError(code)


def serialize_pack(units):
    """The complete context payload, not an estimate of its text substring."""
    return encoded({'contract': CONTRACT, 'units': list(units)})


def read_original(repository, manifest, hard, route, key, *, now):
    """One whole atom read with the existing gate and every scoped predicate.

    No entry text, unbounded corpus read, or alternate database is permitted.
    This does not replace or change the Phase-P repository or SQL paths.
    """
    pin = repository._route_pin(manifest, hard, route, now)
    require(manifest.lane == Lane.STRUCTURAL_CANARY and route.kind != 'LEGACY_CHUNK',
            'COMPACT_STRUCTURAL_ONLY')
    require(key in pin.atoms, 'FOREIGN_ATOM')
    require((route.kind == 'ENTRY' and route.key in pin.entries) or
            (route.kind == 'ATOM_ONLY' and route.key == key), 'UNDECLARED_COMPACT_ROUTE')
    row = repository.conn.execute(select(schema.atoms).where(
        where(schema.atoms, document_values(manifest, pin)),
        schema.atoms.c.atom_id == key)).mappings().one()
    require(digest(row['payload']) == row['payload_hash'], 'EVIDENCE_PAYLOAD_CORRUPTION')
    payload = row['payload']
    require(payload['atom']['scope'] == route.source.model_dump(mode='json') and
            payload['atom']['atom_key'] == key, 'COMPACT_ATOM_IDENTITY_MISMATCH')
    return payload


def compact_unit(payload, reference):
    """Project bookkeeping out, never alter strings or reorder source material.

    Mapping coordinates, parser paths, provenance and repeated full identities
    are backend-only. Local node IDs/parents, heading/table associations, roles,
    continuation flags, quality and ALL typed semantic attributes stay visible.
    No semantic deduplication (including repeated text) is attempted.
    """
    view = evidence_view(payload)
    return dict(atom_id=view['atom']['atom_key'], provenance_ref=reference,
        citation={'document_id': view['atom']['scope']['revision']['source']['document_id']},
        kind=view['atom']['kind'],
        parts=[{k: p[k] for k in ('text', 'kind', 'part_index', 'part_count',
            'complete_unit', 'source_block_complete', 'list_item_indices',
            'heading_path', 'table_cells')} for p in view['source_parts']],
        nodes=[{k: n[k] for k in ('identity', 'parent', 'node_type', 'semantic_role',
            'text', 'attributes', 'quality')} for n in view['nodes']])


@dataclass(frozen=True)
class SidecarRecord:
    """Canonical immutable bytes, so callers cannot mutate trusted shared dicts."""
    reference: str
    data: bytes

    @classmethod
    def create(cls, manifest, hard, route, key, payload):
        require(payload['atom']['scope'] == route.source.model_dump(mode='json') and
                payload['atom']['atom_key'] == key, 'COMPACT_ATOM_IDENTITY_MISMATCH')
        data = encoded(dict(contract=CONTRACT, manifest=manifest.canonical_hash(),
            hard_scope=hard.identity(), route=route.model_dump(mode='json'), atom_id=key,
            original_payload=payload, original_payload_hash=digest(payload)))
        return cls(sha256(data).hexdigest(), data)


class ProvenanceSidecar:
    """Request-local storage. Every resolution freshly rechecks trusted state."""
    def __init__(self):
        self._records = {}

    def add(self, record):
        require(sha256(record.data).hexdigest() == record.reference, 'COMPACT_SIDECAR_CORRUPTION')
        existing = self._records.get(record.reference)
        require(existing is None or existing == record, 'COMPACT_REFERENCE_COLLISION')
        self._records[record.reference] = record

    def resolve(self, reference, repository, manifest, hard, *, now, expected_atom=None,
                reader=read_original):
        epoch = repository.read_gate(manifest, hard, now=now)
        record = self._records.get(reference)
        require(record is not None, 'COMPACT_REFERENCE_NOT_FOUND')
        require(sha256(record.data).hexdigest() == reference, 'COMPACT_SIDECAR_CORRUPTION')
        value = json.loads(record.data)
        require(value['contract'] == CONTRACT and value['manifest'] == manifest.canonical_hash()
                and value['hard_scope'] == hard.identity(), 'FOREIGN_COMPACT_REFERENCE')
        key = value['atom_id']
        require(expected_atom is None or key == expected_atom, 'WRONG_COMPACT_ATOM')
        route = Route.model_validate(value['route'])
        current = reader(repository, manifest, hard, route, key, now=now)
        require(encoded(current) == encoded(value['original_payload']) and
                digest(current) == value['original_payload_hash'], 'COMPACT_PAYLOAD_CHANGED')
        repository.read_gate(manifest, hard, now=now, expected_epoch=epoch)
        return value  # A new dict, not the stored record; contains full original spans.


def requested_atoms(fused, witnesses, repository, manifest, hard, now):
    """Exact Phase-P request construction, including sorted repository children."""
    requested = [(h.route, h.evidence_key, 'lexical_reservation') for h in witnesses]
    max_fanout = 0
    for row in fused[:manifest.policy.evidence_units]:
        route = row['route']
        keys = repository.children(manifest, hard, route, now=now)
        max_fanout = max(max_fanout, len(keys))
        require(len(keys) <= 32, 'MATERIALIZATION_FANOUT_BOUND')
        requested.extend((route, key, 'fused_route') for key in keys)
    return requested, max_fanout


def materialize_compact(fused, witnesses, repository, manifest, hard, now, *, reader=read_original):
    """Whole atoms, same order/48-unit cap; only representation size changes.

    The reader injection supports deterministic saved-file replay, not an HTTP
    or provider fallback. The default reads and validates the complete DB atom.
    Returned scorer units retain Phase-P route/key/reason identities. Only the
    separate ``model_bytes`` is ever designated as model-facing context.
    """
    start = perf_counter()
    epoch = repository.read_gate(manifest, hard, now=now)
    require(manifest.lane == Lane.STRUCTURAL_CANARY, 'COMPACT_STRUCTURAL_ONLY')
    requested, max_fanout = requested_atoms(fused, witnesses, repository, manifest, hard, now)
    units, model_units, excluded, seen = [], [], [], set()
    sidecar = ProvenanceSidecar()
    used = len(serialize_pack(()))
    require(used <= manifest.policy.evidence_bytes, 'COMPACT_ENVELOPE_OVER_BUDGET')
    reader_ms = serialization_ms = 0.0
    for route, key, reason in requested:
        identity = (route.source, key)
        if identity in seen:
            continue
        seen.add(identity)
        if len(units) >= manifest.policy.evidence_units:
            excluded.append(dict(key=key, status='INCOMPLETE_BUDGET', reason=reason, cap='UNITS'))
            continue
        t = perf_counter()
        payload = reader(repository, manifest, hard, route, key, now=now)
        reader_ms += (perf_counter() - t) * 1000
        t = process_time()
        record = SidecarRecord.create(manifest, hard, route, key, payload)
        compact = compact_unit(payload, record.reference)
        size = len(encoded(compact)) + bool(model_units)  # exact comma cost
        if used + size <= manifest.policy.evidence_bytes:
            sidecar.add(record)
            units.append(dict(route=route.model_dump(mode='json'), key=key, reason=reason,
                              payload=evidence_view(payload)))
            model_units.append(compact)
            used += size
        else:
            excluded.append(dict(key=key, status='INCOMPLETE_BUDGET', reason=reason, cap='BYTES'))
        serialization_ms += (process_time() - t) * 1000
    model_bytes = serialize_pack(model_units)
    require(len(model_bytes) == used, 'COMPACT_ACCOUNTING_MISMATCH')
    repository.read_gate(manifest, hard, now=now, expected_epoch=epoch)
    return dict(units=units, exclusions=excluded, bytes=used, model_bytes=model_bytes,
        sidecar=sidecar, max_fanout=max_fanout,
        requested_sequence_hash=digest([dict(route=r.model_dump(mode='json'),key=k,reason=why)
                                        for r,k,why in requested]),
        supplemental_seeds=[row['route'].model_dump(mode='json')
                            for row in fused[:manifest.policy.supplemental_seeds]],
        timings=dict(evidence_read_ms=reader_ms, serialization_cpu_ms=serialization_ms,
                     total_materialization_ms=(perf_counter() - start) * 1000))
