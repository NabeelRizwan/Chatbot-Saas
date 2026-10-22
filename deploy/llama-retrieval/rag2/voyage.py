"""Bounded live Voyage rerank-3 scoring; original text and input order persist.

Shared Redis admission coordinates both service lanes by provider account.
No response or source text is persisted by this adapter.
"""
from collections import defaultdict
import asyncio
from contextlib import suppress
from email.utils import parsedate_to_datetime
import math
import os
from pathlib import Path
import time

import httpx
from redis import Redis
from contextlib import nullcontext
from copy import copy
from .redis_quota import QuotaLedger
from .request_budget import RequestBudget, VoyageError


def retry_after_seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError, AttributeError):
            return 0.0
    return max(0.0, seconds) if math.isfinite(seconds) else 0.0


class VoyagePredictor:
    def __init__(self, key, tokenizer, ledger, *, transport=None, max_attempts=4,
                 budget=None, remote_context=nullcontext):
        if not isinstance(key, str) or not key.strip():
            raise VoyageError('voyage_credentials_missing')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 4:
            raise ValueError('Voyage retries must be bounded to one through four attempts.')
        self.key, self.tokenizer, self.ledger = key, tokenizer, ledger
        self.transport, self.max_attempts = transport, max_attempts
        self.budget = budget or RequestBudget()
        self.remote_context = remote_context

    @classmethod
    def from_environment(cls, model_root, *, budget=None, remote_context=nullcontext):
        from tokenizers import Tokenizer
        path = Path(model_root) / 'voyage-tokenizer' / 'tokenizer.json'
        try:
            tokenizer = Tokenizer.from_file(str(path))
        except Exception:
            raise VoyageError('voyage_tokenizer_unavailable') from None
        tokenizer.no_truncation()
        tokenizer.no_padding()
        key = os.getenv('VOYAGE_API_KEY', '').strip()
        if not key:
            raise VoyageError('voyage_credentials_missing')
        url = os.getenv('VOYAGE_REDIS_URL') or os.getenv('REDIS_URL')
        if not url:
            raise VoyageError('voyage_quota_store_not_configured')
        try:
            rpm, tpm = int(os.getenv('VOYAGE_RPM', '3')), int(os.getenv('VOYAGE_TPM', '10000'))
            if (rpm, tpm) != (3, 10000) and os.getenv('VOYAGE_QUOTA_LIMITS_VERIFIED', '').lower() != 'true':
                raise ValueError('quota override not verified')
            client = Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
        except (ValueError, TypeError):
            raise VoyageError('voyage_quota_configuration_invalid') from None
        ledger = QuotaLedger(client, os.getenv('VOYAGE_QUOTA_ACCOUNT_ID') or key, rpm=rpm, tpm=tpm)
        return cls(key, tokenizer, ledger, budget=budget, remote_context=remote_context)

    def count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    async def _post_async(self, payload):
        """A whole HTTP attempt has a wall-clock cap and observes disconnects."""
        seconds = min(60, self.budget.remaining())
        async with httpx.AsyncClient(transport=self.transport, trust_env=False,
                follow_redirects=False, timeout=seconds) as client:
            task = asyncio.create_task(client.post('https://api.voyageai.com/v1/rerank',
                json=payload, headers={'Authorization': 'Bearer ' + self.key}))
            end = time.monotonic() + seconds
            try:
                while not task.done():
                    self.budget.remaining()
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        raise httpx.TimeoutException('Voyage attempt deadline exceeded')
                    await asyncio.wait({task}, timeout=min(.1, remaining))
                self.budget.remaining()
                return await task
            finally:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def request(self, query, documents):
        estimated = self.count(query) * len(documents) + sum(self.count(text) for text in documents)
        if not documents or len(documents) > 1000 or estimated > 3500:
            raise VoyageError('voyage_batch_token_limit')
        payload = {'model': 'rerank-3', 'query': query, 'documents': documents,
                   'truncation': False, 'return_documents': False}
        reservation = math.ceil(estimated * 1.02) + 32
        for attempt in range(self.max_attempts):
            key = self.ledger.reserve(reservation, self.budget)
            remaining = self.budget.remaining()
            if remaining <= 0:
                raise VoyageError('voyage_request_deadline_exceeded')
            retry_after = 0.0
            try:
                response = asyncio.run(self._post_async(payload))
            except (httpx.TimeoutException, httpx.TransportError):
                retryable = True
            else:
                retry_after = retry_after_seconds(response.headers.get('retry-after', '0'))
                cooldown = max(retry_after, 62.0 if response.status_code == 429 else 0.0)
                if cooldown:
                    self.ledger.defer(cooldown)
                if response.status_code == 200:
                    try:
                        body = response.json()
                        data = body['data']
                        if body['model'] != 'rerank-3' or len(data) != len(documents):
                            raise ValueError('invalid model or response length')
                        indices = [row['index'] for row in data]
                        if any(type(i) is not int for i in indices) or set(indices) != set(range(len(documents))):
                            raise ValueError('invalid indices')
                        scores = [None] * len(documents)
                        for row in data:
                            score = float(row['relevance_score'])
                            if not math.isfinite(score):
                                raise ValueError('invalid score')
                            scores[row['index']] = score
                        usage = body['usage']['total_tokens']
                        if type(usage) is not int or usage < 0:
                            raise ValueError('invalid usage')
                    except (KeyError, ValueError, TypeError, OverflowError):
                        raise VoyageError('voyage_response_invalid') from None
                    self.ledger.reconcile(key, usage)
                    self.budget.remaining()
                    return scores
                retryable = response.status_code in {429, 500, 502, 503, 504}
                if not retryable:
                    raise VoyageError('voyage_provider_rejected_request')
            if not retryable or attempt + 1 == self.max_attempts:
                raise VoyageError('voyage_provider_unavailable')
            wait = max(retry_after, min(248, 62 * 2 ** attempt))
            self.ledger.defer(wait)
            self.budget.pause(wait)
        raise VoyageError('voyage_provider_unavailable')

    def predict(self, pairs):
        with self.remote_context():
            return self._predict(pairs)

    def _predict(self, pairs):
        self.budget.remaining()
        grouped = defaultdict(list)
        for index, (query, text) in enumerate(pairs):
            grouped[query].append((index, text))
        result = [None] * len(pairs)
        for query, items in grouped.items():
            query_tokens = self.count(query)
            batch, tokens = [], 0
            def score_batch(rows):
                scores = self.request(query, [text for _, text in rows])
                for (index, _), score in zip(rows, scores):
                    result[index] = score
            for item in items:
                required = query_tokens + self.count(item[1])
                if required > 3500:
                    raise VoyageError('voyage_pair_token_limit')
                if batch and tokens + required > 3500:
                    score_batch(batch)
                    batch, tokens = [], 0
                batch.append(item)
                tokens += required
            if batch:
                score_batch(batch)
        return result


class PassageRanker:
    """Retain MiniLM discovery; replace only primary passage scoring."""
    def __init__(self, original, predictor):
        self.original = original
        self.remote = copy(original)
        self.remote._model = predictor

    def postprocess_nodes(self, nodes, query_bundle=None, **kwargs):
        if nodes and all(node.node.metadata.get('discovery_only') for node in nodes):
            return self.original.postprocess_nodes(nodes, query_bundle=query_bundle, **kwargs)
        return self.remote.postprocess_nodes(nodes, query_bundle=query_bundle, **kwargs)
