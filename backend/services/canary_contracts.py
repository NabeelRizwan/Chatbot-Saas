"""Internal Phase O values. No environment, DB, HTTP, cache or provider imports."""
from enum import Enum
import hashlib
import math
import struct
from numbers import Real
from typing import Literal

from pydantic import Field, model_validator
from services.structural_document import Value, Digest, Name, Positive, NonNegative
from services.structural_retrieval_entries import RetrievalEntryScope
from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity


class CanaryError(ValueError):
    """Fixed diagnostic codes only; never include connection/provider details."""


class Lane(str, Enum):
    LEGACY_CONTROL = 'LEGACY_CONTROL'
    STRUCTURAL_CANARY = 'STRUCTURAL_CANARY'


class State(str, Enum):
    OFF = 'OFF'
    EMBEDDING_STAGING = 'EMBEDDING_STAGING'
    INDEX_READY = 'INDEX_READY'
    CANARY_READ = 'CANARY_READ'
    COMPARATIVE_EVAL = 'COMPARATIVE_EVAL'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'
    EXPIRED = 'EXPIRED'
    STALE = 'STALE'


TERMINAL = {State.FAILED, State.CANCELLED, State.EXPIRED, State.STALE}
TRANSITIONS = {
    State.OFF: {State.EMBEDDING_STAGING},
    State.EMBEDDING_STAGING: {State.INDEX_READY, *TERMINAL, State.OFF},
    State.INDEX_READY: {State.CANARY_READ, State.COMPARATIVE_EVAL, *TERMINAL, State.OFF},
    State.CANARY_READ: {State.INDEX_READY, *TERMINAL, State.OFF},
    State.COMPARATIVE_EVAL: {State.INDEX_READY, *TERMINAL, State.OFF},
}


class Approval(Value):
    environment: Literal['offline_test', 'disposable_test']
    database_identity: Digest
    ownership_marker: Name
    operator_reference: Name
    organization_id: Positive
    bot_id: Positive
    created_at: Positive
    expires_at: Positive

    @model_validator(mode='after')
    def valid(self):
        if self.expires_at <= self.created_at:
            raise CanaryError('INVALID_APPROVAL_EXPIRY')
        return self


VECTOR_ATTESTATION = 'vector-attestation-f32-v1'


class Profile(Value):
    source: Literal['SYNTHETIC_TEST', 'REAL_PROVIDER']
    provider: Name
    model: Name
    version: Positive = 1
    dimensions: Literal[768] = 768
    configuration_hash: Digest
    # Required, not defaulted: an old JSON-vector digest must never acquire new meaning.
    vector_attestation: Literal['vector-attestation-f32-v1']

    @model_validator(mode='after')
    def provenance(self):
        synthetic = self.provider == 'canary-local-fixture' and self.model == 'sha256-v1'
        if (self.source == 'SYNTHETIC_TEST') != synthetic:
            raise CanaryError('PROFILE_PROVENANCE_MISMATCH')
        return self

    def require_stage_a(self):
        if self.source != 'SYNTHETIC_TEST':
            raise CanaryError('REAL_PROVIDER_NOT_AUTHORIZED')

    def hard_identity(self):
        return ProfileIdentity(self.provider, self.model, self.version, self.dimensions)


SYNTHETIC_PROFILE = Profile(source='SYNTHETIC_TEST', provider='canary-local-fixture',
    model='sha256-v1', vector_attestation=VECTOR_ATTESTATION,
    configuration_hash=hashlib.sha256(b'canary-synthetic-vector-v1\0' + VECTOR_ATTESTATION.encode('ascii')).hexdigest())


class Policy(Value):
    version: Literal['canary-mechanics-v1'] = 'canary-mechanics-v1'
    atomic_projection: Literal['atomic-fts-v1'] = 'atomic-fts-v1'
    fts: Literal['english/websearch_to_tsquery/ts_rank_cd'] = 'english/websearch_to_tsquery/ts_rank_cd'
    tie: Literal['score/best-rank/document/typed-key'] = 'score/best-rank/document/typed-key'
    candidate_limit: Positive = Field(default=48, le=500)
    evidence_units: Positive = Field(default=48, le=48)
    evidence_bytes: Positive = Field(default=131072, le=131072)
    supplemental_seeds: Positive = Field(default=20, le=20)
    witness_limit: NonNegative = Field(default=8, le=8)
    dense_weight: float = Field(default=1, ge=0, allow_inf_nan=False)
    fts_weight: float = Field(default=1, ge=0, allow_inf_nan=False)
    rrf_k: float = Field(default=60, gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def nonzero(self):
        if self.dense_weight + self.fts_weight <= 0:
            raise CanaryError('ZERO_CHANNEL_WEIGHTS')
        return self


class SourcePin(Value):
    scope: RetrievalEntryScope
    source_id: Positive
    website_id: Positive | None = None
    batch_hash: Digest
    entries: tuple[Digest, ...]
    atoms: tuple[Digest, ...]
    mapping_hash: Digest
    projection_hash: Digest
    quality_hash: Digest
    legacy_members: tuple[Positive, ...] = ()

    @model_validator(mode='after')
    def unique(self):
        if (self.website_id is None) != (self.scope.crawl_id is None):
            raise CanaryError('CRAWL_PIN_INCOMPLETE')
        for values in (self.entries, self.atoms, self.legacy_members):
            if len(values) != len(set(values)):
                raise CanaryError('DUPLICATE_INVENTORY')
        return self


class Manifest(Value):
    schema_version: Literal['canary-manifest-v1'] = 'canary-manifest-v1'
    run_id: Name
    lane: Lane
    generation: Name
    approval: Approval
    profile: Profile
    policy: Policy
    documents: tuple[SourcePin, ...] = Field(min_length=1, max_length=25)
    representation_policy: Literal['structural-retrieval-entry-v2'] = 'structural-retrieval-entry-v2'
    implementation_hash: Digest
    query_contract_hash: Digest
    evaluation_hash: Digest

    @model_validator(mode='after')
    def owned(self):
        ids = []
        for pin in self.documents:
            s = pin.scope.revision.source
            if (s.organization_id, s.bot_id) != (self.approval.organization_id, self.approval.bot_id):
                raise CanaryError('FOREIGN_MANIFEST_DOCUMENT')
            ids.append(s.document_id)
            if self.lane == Lane.STRUCTURAL_CANARY and pin.legacy_members:
                raise CanaryError('CROSS_LANE_INVENTORY')
            if self.lane == Lane.LEGACY_CONTROL and (pin.entries or not pin.legacy_members):
                raise CanaryError('CROSS_LANE_INVENTORY')
        if len(ids) != len(set(ids)) or ids != sorted(ids):
            raise CanaryError('DOCUMENT_ORDER_OR_DUPLICATE')
        if sum(len(p.atoms) for p in self.documents) > 5000 or sum(len(p.entries) for p in self.documents) > 1200:
            raise CanaryError('MANIFEST_CAPACITY')
        return self

    def effective(self, hard: HardKnowledgeScope):
        if (hard.organization_id, hard.bot_id) != (self.approval.organization_id, self.approval.bot_id):
            raise CanaryError('FOREIGN_HARD_SCOPE')
        if hard.embedding_profile != self.profile.hard_identity():
            raise CanaryError('HARD_PROFILE_MISMATCH')
        ids = hard.intersect(p.scope.revision.source.document_id for p in self.documents)
        permitted = set(ids or ())
        if hard.authorized_source_ids is not None:
            permitted.intersection_update(p.scope.revision.source.document_id for p in self.documents
                                          if p.source_id in hard.authorized_source_ids)
        if hard.active_document_versions:
            versions = set(hard.active_document_versions)
            permitted.intersection_update(p.scope.revision.source.document_id for p in self.documents
                if (p.scope.revision.source.document_id, p.scope.revision.source.source_version, p.scope.crawl_id) in versions)
        return tuple(sorted(permitted))


class Route(Value):
    manifest: Digest
    run_id: Name
    lane: Lane
    generation: Name
    profile: Digest
    source: RetrievalEntryScope
    kind: Literal['ENTRY', 'ATOM_ONLY', 'LEGACY_CHUNK']
    key: Name

    def sort_key(self):
        # Legacy integer ordering must equal serving chunk-id ordering, not "10" < "2".
        return (self.kind, int(self.key) if self.kind == 'LEGACY_CHUNK' else self.key)


def route(manifest, pin, kind, key):
    return Route(manifest=manifest.canonical_hash(), run_id=manifest.run_id, lane=manifest.lane,
        generation=manifest.generation, profile=manifest.profile.canonical_hash(), source=pin.scope, kind=kind, key=str(key))


def canonicalize_vector_f32(values):
    """Exact pgvector coordinate identity, independent of decimal serialization.

    IEEE-754 binary32, big-endian; signed zeros normalize to +0. No tolerance.
    Check finiteness and nonzero again after quantization (overflow/underflow).
    This contract is provider-neutral; it never authorizes a provider call.
    """
    try:
        result = tuple(values)
        if len(result) != 768 or any(isinstance(v, bool) or not isinstance(v, Real) for v in result):
            raise CanaryError('INVALID_VECTOR')
        result = tuple(float(v) for v in result)
        if not all(math.isfinite(v) for v in result):
            raise CanaryError('INVALID_VECTOR')
        result = struct.unpack('!768f', struct.pack('!768f', *result))
    except (TypeError, OverflowError, struct.error):
        raise CanaryError('INVALID_VECTOR') from None
    if not all(math.isfinite(v) for v in result):
        raise CanaryError('INVALID_VECTOR')
    if not any(v != 0 for v in result):
        raise CanaryError('INVALID_VECTOR_NORM')
    return tuple(0.0 if v == 0 else v for v in result)


def canonical_vector_bytes(values):
    return struct.pack('!768f', *canonicalize_vector_f32(values))


def canonical_vector_digest(values):
    return hashlib.sha256(canonical_vector_bytes(values)).hexdigest()


def validate_vector(values):
    return canonicalize_vector_f32(values)


def synthetic_vector(exact_input: str):
    """Dedicated synthetic fixture; no embedding-service import, network or semantic claim."""
    seed = b'CANARY_SYNTHETIC_TEST_V1\0' + exact_input.encode('utf-8')
    raw = b''.join(hashlib.sha256(seed + i.to_bytes(2, 'big')).digest() for i in range(48))
    return validate_vector(tuple((int.from_bytes(raw[i:i+2], 'big') - 32767.5) / 32768 for i in range(0, 1536, 2)))
