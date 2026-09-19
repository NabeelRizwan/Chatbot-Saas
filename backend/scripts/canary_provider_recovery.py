"""Canary-only recovery transport. The frozen request/profile module is unchanged.

The installed genai APIError supplies code/status/response/details; never use
message, str(error), response bodies, or arbitrary error class names in output.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import time
import httpx
from google.genai import errors, types

from scripts.canary_gemini_embeddings import GeminiCanary, Attestation, MODEL, bounded_batches
from services.canary_contracts import CanaryError, canonicalize_vector_f32, canonical_vector_digest
from services.canary_representation import exact_input_hash
from services.structural_chunking import count_tokens, digest

STATUSES = frozenset(('INVALID_ARGUMENT', 'UNAUTHENTICATED', 'PERMISSION_DENIED',
    'RESOURCE_EXHAUSTED', 'INTERNAL', 'UNAVAILABLE', 'DEADLINE_EXCEEDED',
    'NOT_FOUND', 'FAILED_PRECONDITION', 'OUT_OF_RANGE', 'UNKNOWN'))


class ProviderHold(CanaryError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('PROVIDER_HOLD')


def classify(exc, *, wall=time):
    status = exc.code if isinstance(exc, errors.APIError) else None
    status = status if type(status) is int and 100 <= status <= 599 else None
    enum = exc.status if isinstance(exc, errors.APIError) else None
    enum = enum if isinstance(enum, str) and enum in STATUSES else None
    timeout = isinstance(exc, (httpx.TimeoutException, TimeoutError))
    transport = isinstance(exc, (httpx.TransportError, ConnectionError))
    category = ({400:'INVALID_INPUT', 401:'AUTH', 403:'PERMISSION', 429:'RATE_LIMIT',
        500:'SERVER_500', 502:'SERVER_502', 503:'SERVER_503', 504:'SERVER_504'}.get(status)
        or ('TIMEOUT' if timeout else 'TRANSPORT' if transport else 'UNKNOWN_PROVIDER_FAILURE'))
    delay = None
    if isinstance(exc, errors.APIError):
        details = exc.details if isinstance(exc.details, dict) else {}
        error = details.get('error', details)
        metadata = error.get('details', []) if isinstance(error, dict) else []
        # QuotaFailure is structured proof; RESOURCE_EXHAUSTED alone is not.
        if status == 429 and isinstance(metadata, list) and any(isinstance(d, dict)
                and d.get('@type') == 'type.googleapis.com/google.rpc.QuotaFailure'
                and isinstance(d.get('violations'), list) and d['violations'] for d in metadata[:32]):
            category = 'QUOTA_EXHAUSTED'
        response = exc.response
        headers = getattr(response, 'headers', None)
        raw = headers.get('Retry-After') if headers is not None else None
        if isinstance(raw, str) and len(raw) <= 64:
            try:
                delay = float(raw) if raw.isdecimal() else (
                    parsedate_to_datetime(raw).astimezone(timezone.utc).timestamp() - wall())
                if not 0 <= delay <= 18000:
                    delay = None
            except (ValueError, TypeError, OverflowError):
                delay = None
    kind = ('server' if status and status >= 500 else 'client' if status and status >= 400
            else 'transport' if timeout or transport else 'unknown')
    cls = ('ClientError' if isinstance(exc, errors.ClientError) else
           'ServerError' if isinstance(exc, errors.ServerError) else
           'APIError' if isinstance(exc, errors.APIError) else
           'TimeoutException' if timeout else 'TransportError' if transport else 'OtherException')
    return dict(category=category, error_class=cls, http_status=status, provider_status=enum,
        retryable=status in (429,500,502,503,504) or timeout or transport,
        retry_after_seconds=delay, timeout=timeout, classification=kind,
        consumption='KNOWN_FAILURE' if status and 400 <= status < 500 else 'UNKNOWN')


class RecoverableGemini(GeminiCanary):
    """Identical SDK construction and exact f32 receipt validation; one retry owner.

    on_attempt is durable and called BEFORE HTTP and after its outcome. An error
    in that sink prevents further spend. Started attempts mean unknown external
    consumption, even if a process dies before receiving a response.
    """
    def __init__(self, *args, deadline_seconds=18000, on_attempt=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not 1 <= deadline_seconds <= 18000:
            raise CanaryError('INVALID_EXECUTION_DEADLINE')
        self.deadline = self.started + deadline_seconds
        self.on_attempt = on_attempt or (lambda record: None)

    def _embed(self, texts, purpose, retries):
        if not texts or len(texts)>8 or len(list(bounded_batches(texts))) != 1:
            raise CanaryError('EMBEDDING_BATCH_BUDGET_HOLD')
        keys = [(*self.scope, exact_input_hash(t), self.profile.canonical_hash()) for t in texts]
        if len(keys) != len(set(keys)):
            raise CanaryError('DUPLICATE_BATCH_INPUT')
        needed = [(key,t) for key,t in zip(keys,texts) if key not in self.ledger]
        self.metrics['reused'] += len(texts)-len(needed)
        if not needed:
            return tuple(self.ledger[k] for k in keys)
        tokens = sum(count_tokens(t) for _,t in needed)
        if purpose == 'evidence' and (self.metrics['new_vectors']+len(needed)>2500
                or self.metrics['local_input_tokens']+tokens>500000):
            raise CanaryError('PAIRED_BUILD_BUDGET_HOLD')
        hashes = [k[2] for k,_ in needed]
        for retry in range(retries+1):
            if self.clock()+45 > self.deadline:
                raise CanaryError('EMBEDDING_WALL_DEADLINE')
            record = dict(provider='gemini', model=MODEL, attempt=len(self.attempts)+1,
                batch_hash=digest(hashes), input_hashes=hashes, inputs=len(needed),
                local_tokens=tokens, purpose=purpose, retry=retry, result='STARTED',
                consumption='UNKNOWN', started_at=datetime.now(timezone.utc).isoformat())
            self.attempts.append(record)
            self.on_attempt(dict(record))
            if retry:self.metrics['retried']+=1
            start=self.clock()
            try:
                response=self.client.models.embed_content(model=MODEL, contents=[t for _,t in needed],
                    config=types.EmbedContentConfig(output_dimensionality=768))
            except Exception as exc:
                record.update(classify(exc), result='FAILED', duration_ms=(self.clock()-start)*1000)
                self.metrics['failed']+=1;self.metrics['unknown_usage_attempts']+=1
                self.on_attempt(dict(record))
                delay=record['retry_after_seconds']
                if delay is None:delay=min(30,2**(retry+1))
                if retry<retries and record['retryable'] and self.clock()+delay+45<self.deadline:
                    self.pause(delay)
                    continue
                raise ProviderHold(dict(record)) from None
            record['duration_ms']=(self.clock()-start)*1000
            try:
                if response.embeddings is None or len(response.embeddings)!=len(needed):
                    raise CanaryError('PROVIDER_CARDINALITY_MISMATCH')
                values=[];usage=[]
                for embedding in response.embeddings:
                    values.append(canonicalize_vector_f32(embedding.values))
                    stats=getattr(embedding,'statistics',None)
                    if stats is not None and getattr(stats,'truncated',False):
                        raise CanaryError('PROVIDER_TRUNCATED_INPUT')
                    count=getattr(stats,'token_count',None)
                    usage.append(count if type(count) in (int,float) and count>=0 else None)
            except Exception:
                record.update(result='REFUSED',category='INVALID_RESPONSE',error_class='ValidationError',
                    consumption='UNKNOWN',retryable=False)
                self.metrics['failed']+=1;self.metrics['unknown_usage_attempts']+=1
                self.on_attempt(dict(record))
                raise ProviderHold(dict(record)) from None
            record.update(result='SUCCEEDED', consumption='KNOWN_SUCCESS', category='SUCCESS',
                http_status=200, provider_status=None, retryable=False, timeout=False,
                classification='success', provider_tokens=usage,
                vector_hashes=[canonical_vector_digest(v) for v in values])
            self.on_attempt(dict(record))
            self.metrics['succeeded']+=1
            self.metrics['provider_tokens']+=sum(n for n in usage if n is not None)
            self.metrics['unknown_usage_attempts']+=int(any(n is None for n in usage))
            self.metrics['new_vectors' if purpose=='evidence' else 'query_embeddings']+=len(needed)
            self.metrics['local_input_tokens' if purpose=='evidence' else 'query_local_tokens']+=tokens
            for (key,_),vector in zip(needed,values):
                self.ledger[key]=Attestation(*key[:2],key[2],key[3],canonical_vector_digest(vector),vector,record['attempt'])
            return tuple(self.ledger[k] for k in keys)
