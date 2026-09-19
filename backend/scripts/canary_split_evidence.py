"""Exact evaluation-only row transport; no retrieval or materialization policy."""
from hashlib import sha256

from sqlalchemy import select
from database import canary_schema as s
from services.canary_contracts import CanaryError
from services.canary_repository import CanaryRepository, document_values, where
from services.canary_representation import evidence_view
from services.structural_chunking import digest
from scripts.canary_evaluation_resume import EvaluationRepository, require


def split_atom_row(conn, scope, before=None, *, expected_hash=None):
    """Reconstruct the entire original row, not an approximate payload projection.

    Both reads retain every hard predicate. The second additionally compares ALL
    metadata from the first, so a concurrent metadata change fails closed instead
    of mixing two row versions. Payload content must match that exact row's hash.
    """
    require(set(scope) == set(s.DOC) | {'atom_id'}, 'EXACT_ATOM_SCOPE_REQUIRED')
    metadata_columns = [c for c in s.atoms.c if c.name != 'payload']
    def scoped(columns):
        return select(*columns).where(where(s.atoms, {k: scope[k] for k in s.DOC}),
                                      s.atoms.c.atom_id == scope['atom_id'])
    metadata_stmt = scoped(metadata_columns)
    if before:
        before(conn, metadata_stmt, scope, 1)
    row = dict(conn.execute(metadata_stmt).mappings().one())
    guards = {k: v for k, v in row.items() if k not in scope}
    payload_stmt = scoped([s.atoms.c.payload]).where(where(s.atoms, guards))
    if before:
        before(conn, payload_stmt, scope, 2)
    row['payload'] = conn.execute(payload_stmt).scalar_one()
    if digest(row['payload']) != row['payload_hash']:
        raise CanaryError('EVIDENCE_PAYLOAD_CORRUPTION')
    if expected_hash is not None:
        require(digest(row) == expected_hash, 'SPLIT_EVIDENCE_ROW_EQUIVALENCE_FAILED')
    return row


class SplitEvidenceRepository(EvaluationRepository):
    def __init__(self, *args, expected_rows=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_rows = expected_rows

    def _before_part(self, conn, stmt, scope, part):
        observer = self.observer
        if observer is None:
            return
        require(observer.pending is not None
                and observer.pending['record']['source_scope'] == scope,
                'MEASURED_EVIDENCE_SCOPE_MISMATCH')
        record = dict(observer.pending['record'], phase='BEFORE_SQL_PART'+str(part),
            statement_started=True, transport='EXACT_SPLIT_ROW_V1', transport_part=part,
            query_shape_sha256=sha256(str(stmt.compile(dialect=conn.dialect)).encode()).hexdigest())
        observer.pending['record'] = record
        observer.writer(record)  # Durable immediately before this exact execute.

    def _split_evidence(self, manifest, hard, route, key, *, now):
        if route.kind == 'LEGACY_CHUNK':
            # Avoid recursively entering the observation wrapper.
            return CanaryRepository.evidence(self, manifest, hard, route, key, now=now)
        pin = self._route_pin(manifest, hard, route, now)
        if key not in pin.atoms:
            raise CanaryError('FOREIGN_ATOM')
        scope = dict(document_values(manifest, pin), atom_id=key)
        expected_hash = None
        if self.expected_rows is not None:
            expected_hash = self.expected_rows.get(digest(scope))
            require(expected_hash is not None, 'VALIDATED_ATOM_ROW_REQUIRED')
        row = split_atom_row(self.conn, scope, self._before_part, expected_hash=expected_hash)
        return evidence_view(row['payload'])

    def evidence(self, manifest, hard, route, key, *, now):
        if self.observer is None:
            return self._split_evidence(manifest, hard, route, key, now=now)
        return self.observer.observe(self._split_evidence, self.conn, manifest, hard, route, key, now=now)
