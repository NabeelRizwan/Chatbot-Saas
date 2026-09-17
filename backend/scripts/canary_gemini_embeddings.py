"""Explicit development-only Phase P embedding boundary; never serving code.

No dotenv, application database, provider fallback, disk writes or chat API.
The caller owns the secret and the lifetime of this in-memory attestation ledger.
"""
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from time import monotonic, sleep

from services.canary_contracts import (CanaryError, Profile, VECTOR_ATTESTATION,
    canonicalize_vector_f32, canonical_vector_bytes, canonical_vector_digest)
from services.canary_representation import exact_input_hash
from services.structural_chunking import count_tokens, digest

MODEL = 'gemini-embedding-001'
SERIALIZATION = 'exact-utf8-no-prefix-no-title-no-task-type-no-normalization-v1'


def configuration():
    return dict(provider='gemini', model=MODEL, profile_version=1, dimensions=768,
        sdk='google-genai', sdk_version=version('google-genai'),
        request={'output_dimensionality': 768}, serialization=SERIALIZATION,
        vector_attestation=VECTOR_ATTESTATION,
        transport={'vertexai': False, 'timeout_ms': 45000, 'sdk_attempts': 1},
        implementation_sha256=sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest())


def real_profile():
    return Profile(source='REAL_PROVIDER', provider='gemini', model=MODEL,
        version=1, dimensions=768, configuration_hash=digest(configuration()),
        vector_attestation=VECTOR_ATTESTATION)


def bounded_batches(texts):
    batch, tokens = [], 0
    for value in texts:
        if not isinstance(value, str) or not value.strip():
            raise CanaryError('EMPTY_EMBEDDING_INPUT')
        size = count_tokens(value)
        if size > 4000:
            raise CanaryError('EMBEDDING_BATCH_BUDGET_HOLD')
        if batch and (len(batch) == 8 or tokens + size > 4000):
            yield tuple(batch)
            batch, tokens = [], 0
        batch.append(value)
        tokens += size
    if batch:
        yield tuple(batch)


@dataclass(frozen=True)
class Attestation:
    organization_id: int
    bot_id: int
    input_hash: str
    profile_hash: str
    vector_hash: str
    vector: tuple
    provider_attempt: int


class GeminiCanary:
    """One explicit client, serial calls, exact input/profile/tenant-bound reuse.

    Failed calls never enter the ledger. Errors expose only fixed categories and
    numeric HTTP status. The SDK owns no retry; this wrapper is the sole owner.
    """
    def __init__(self, key, *, organization_id, bot_id, approved=False,
                 client_factory=None, clock=monotonic, pause=sleep):
        if approved is not True or organization_id <= 0 or bot_id <= 0:
            raise CanaryError('GEMINI_CANARY_AUTHORIZATION_REQUIRED')
        if not isinstance(key, str) or not key.strip():
            raise CanaryError('GEMINI_CANARY_CREDENTIAL_REQUIRED')
        from google import genai
        from google.genai import types
        self.profile = real_profile()
        self.scope = (organization_id, bot_id)
        self.clock, self.pause, self.started = clock, pause, clock()
        self.lock, self.ledger, self.attempts = Lock(), {}, []
        self.closed = False
        self.metrics = dict(new_vectors=0, query_embeddings=0, reused=0,
            succeeded=0, failed=0, retried=0, local_input_tokens=0,
            query_local_tokens=0, provider_tokens=0, unknown_usage_attempts=0)
        factory = client_factory or genai.Client
        self.client = factory(api_key=key, vertexai=False, http_options=types.HttpOptions(
            base_url='https://generativelanguage.googleapis.com', timeout=45000,
            retry_options=types.HttpRetryOptions(attempts=1)))

    def close(self):
        try:
            self.client.close()
        finally:
            self.ledger.clear()
            self.closed = True

    def embed(self, texts, *, purpose, retries=0):
        if self.closed or purpose not in ('evidence', 'query') or retries not in (0, 1, 2):
            raise CanaryError('INVALID_EMBEDDING_REQUEST')
        if not self.lock.acquire(blocking=False):
            raise CanaryError('PARALLEL_EMBEDDING_BATCH_REFUSED')
        try:
            return self._embed(tuple(texts), purpose, retries)
        finally:
            self.lock.release()

    def _embed(self, texts, purpose, retries):
        from google.genai import types
        if not texts or len(texts) > 8:
            raise CanaryError('EMBEDDING_BATCH_BUDGET_HOLD')
        planned = list(bounded_batches(texts))
        if len(planned) != 1 or sum(map(count_tokens, texts)) > 4000:
            raise CanaryError('EMBEDDING_BATCH_BUDGET_HOLD')
        if self.clock() - self.started >= 10800:
            raise CanaryError('EMBEDDING_WALL_DEADLINE')
        keys = [(*self.scope, exact_input_hash(t), self.profile.canonical_hash()) for t in texts]
        if len(keys) != len(set(keys)):
            raise CanaryError('DUPLICATE_BATCH_INPUT')
        needed = [(key, text) for key, text in zip(keys, texts) if key not in self.ledger]
        self.metrics['reused'] += len(texts) - len(needed)
        if not needed:
            return tuple(self.ledger[k] for k in keys)
        tokens = sum(count_tokens(t) for _, t in needed)
        if purpose == 'evidence' and (self.metrics['new_vectors'] + len(needed) > 2500
                or self.metrics['local_input_tokens'] + tokens > 500000):
            raise CanaryError('PAIRED_BUILD_BUDGET_HOLD')
        for retry in range(retries + 1):
            if self.clock() - self.started >= 10800:
                raise CanaryError('EMBEDDING_WALL_DEADLINE')
            started = self.clock()
            record = dict(attempt=len(self.attempts) + 1, purpose=purpose, inputs=len(needed),
                input_hashes=[k[2] for k, _ in needed], local_tokens=tokens,
                elapsed_start_seconds=started - self.started, retry=retry)
            self.attempts.append(record)
            if retry:
                self.metrics['retried'] += 1
            try:
                response = self.client.models.embed_content(model=MODEL,
                    contents=[t for _, t in needed],
                    config=types.EmbedContentConfig(output_dimensionality=768))
            except Exception as exc:
                status = getattr(exc, 'code', None)
                status = status if type(status) is int and 100 <= status <= 599 else None
                record.update(result='FAILED', http_status=status,
                    duration_ms=(self.clock() - started) * 1000, usage='UNKNOWN')
                self.metrics['failed'] += 1
                self.metrics['unknown_usage_attempts'] += 1
                if retry < retries and status in (429, 500, 502, 503, 504):
                    self.pause(min(30, 2 ** (retry + 1)))
                    continue
                raise CanaryError('GEMINI_EMBEDDING_PROVIDER_FAILURE') from None
            record['duration_ms'] = (self.clock() - started) * 1000
            try:
                embeddings = response.embeddings
                if embeddings is None or len(embeddings) != len(needed):
                    raise CanaryError('PROVIDER_CARDINALITY_MISMATCH')
                values = []
                usage = []
                for embedding in embeddings:
                    vector = canonicalize_vector_f32(embedding.values)
                    if len(canonical_vector_bytes(vector)) != 3072:
                        raise CanaryError('VECTOR_BYTE_LENGTH_MISMATCH')
                    stats = getattr(embedding, 'statistics', None)
                    if stats is not None and getattr(stats, 'truncated', False):
                        raise CanaryError('PROVIDER_TRUNCATED_INPUT')
                    count = getattr(stats, 'token_count', None)
                    usage.append(count if type(count) in (int, float) and count >= 0 else None)
                    values.append(vector)
            except Exception as exc:
                record.update(result='REFUSED', usage='UNKNOWN')
                self.metrics['failed'] += 1
                self.metrics['unknown_usage_attempts'] += 1
                code = str(exc) if isinstance(exc, CanaryError) else 'PROVIDER_RESPONSE_INVALID'
                raise CanaryError(code) from None
            record.update(result='SUCCEEDED', provider_tokens=usage,
                vector_hashes=[canonical_vector_digest(v) for v in values])
            self.metrics['succeeded'] += 1
            self.metrics['provider_tokens'] += sum(n for n in usage if n is not None)
            self.metrics['unknown_usage_attempts'] += int(any(n is None for n in usage))
            self.metrics['new_vectors' if purpose == 'evidence' else 'query_embeddings'] += len(needed)
            self.metrics['local_input_tokens' if purpose == 'evidence' else 'query_local_tokens'] += tokens
            for (key, _), vector in zip(needed, values):
                self.ledger[key] = Attestation(*key[:2], key[2], key[3],
                    canonical_vector_digest(vector), vector, record['attempt'])
            return tuple(self.ledger[k] for k in keys)

    def receipt(self, text):
        key = (*self.scope, exact_input_hash(text), self.profile.canonical_hash())
        if key not in self.ledger:
            raise CanaryError('REAL_PROVIDER_ATTESTATION_REQUIRED')
        return self.ledger[key]
