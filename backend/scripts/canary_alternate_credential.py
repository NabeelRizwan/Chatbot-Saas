"""Explicit alternate-development credential continuation; no serving imports.

Additive wrapper: the retained run's identity-bound recovery implementation,
profile, SDK configuration, retrieval and publication gates are unchanged.
"""
import argparse
import logging
import os
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.canary_contracts import (canonicalize_vector_f32,
    canonical_vector_bytes, canonical_vector_digest)
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_gemini_embeddings import real_profile, bounded_batches
from scripts.canary_provider_recovery import RecoverableGemini
from scripts.canary_recovery_runner import RecoveryRunner
from scripts.canary_real_embedding_retrieval import item_text, require
from scripts.canary_bounded_output import emit
from scripts.canary_postgres_validation import safe_failure

LABEL = 'alternate-development-credential'
EXPECTED_COUNTS = {
    'canary_embedding_work': {'succeeded': 1030},
    'canary_legacy_embedding_work': {'succeeded': 48, 'unknown': 7, 'pending': 1037},
    'canary_query_work': {'pending': 90},
}


def compare_receipts(texts, old, new, *, scope, profile):
    """Exact equality only; return bounded digests, never coordinates/text."""
    require(3 <= len(texts) <= 8 and len(old) == len(new) == len(texts),
            'COMPATIBILITY_SAMPLE_CARDINALITY')
    require(len(set(map(exact_input_hash, texts))) == len(texts), 'DUPLICATE_COMPATIBILITY_INPUT')
    rows = []
    for value, before, after in zip(texts, old, new):
        ih = exact_input_hash(value)
        a = canonicalize_vector_f32(before.vector)
        b = canonicalize_vector_f32(after.vector)
        require((before.organization_id, before.bot_id) == scope
                and before.input_hash == ih and before.profile_hash == profile.canonical_hash()
                and before.vector_hash == canonical_vector_digest(a), 'INVALID_RETAINED_PROBE_RECEIPT')
        equal = ((after.organization_id, after.bot_id) == scope and after.input_hash == ih
                 and after.profile_hash == profile.canonical_hash()
                 and after.vector_hash == canonical_vector_digest(b) == before.vector_hash
                 and a == b and canonical_vector_bytes(a) == canonical_vector_bytes(b)
                 and len(canonical_vector_bytes(b)) == 3072)
        rows.append(dict(input_hash=ih, old_vector_hash=before.vector_hash,
            new_vector_hash=canonical_vector_digest(b), exact_match=equal))
    return dict(result='PASS' if all(r['exact_match'] for r in rows) else 'FAIL',
        credential_label=LABEL, profile_hash=profile.canonical_hash(),
        configuration_hash=profile.configuration_hash, dimensions=768,
        canonical_bytes=3072, probes=rows)


class AlternateCredentialRunner(RecoveryRunner):
    credential_label = LABEL
    expected_counts = EXPECTED_COUNTS
    expected_reuse = 1078
    expected_unknown = 7
    mismatch_code = 'ALTERNATE_GEMINI_CREDENTIAL_EMBEDDING_MISMATCH'

    def __init__(self, *args, **kwargs):
        require(kwargs.get('mode') == 'resume', 'ALTERNATE_KEY_REQUIRES_EXPLICIT_RETAINED_RUN')
        super().__init__(*args, **kwargs)
        require(len(self.approved_batches) == 1 and bool(self.spend_reference),
                'EXACT_UNKNOWN_BATCH_AUTHORIZATION_REQUIRED')
        self.requested_batches = frozenset(self.approved_batches)
        self.approved_batches.clear()  # Neither probe may spend unknown work.
        self.result['credential_label'] = self.credential_label

    def diagnostic(self, record):
        super().diagnostic(dict(record, credential_label=self.credential_label))

    def make_provider(self, key, **kwargs):
        return RecoverableGemini(key, **kwargs)

    def provider_client(self):
        # Base resume has already verified manifests, epochs, immutable identity
        # and all completed PostgreSQL receipts before invoking this override.
        require(self.control_ready and self.resume_reused == self.expected_reuse, 'RETAINED_REUSE_COUNT_MISMATCH')
        require(self.counts() == self.expected_counts, 'RETAINED_WORK_INVENTORY_MISMATCH')
        unknown = []
        mf = self.manifests[1]
        items = self.all_items(mf)
        with self.repository() as repo:
            require(repo._run(mf)['state'] == 'EMBEDDING_STAGING', 'RETAINED_RUN_STATE_MISMATCH')
            for lane in self.manifests:
                require(repo._manifest(lane)['state'] == 'EMBEDDING_STAGING', 'PARTIAL_PAIR_REFUSED')
            for start in range(0, len(items), 100):
                group = items[start:start+100]
                states = repo.states(mf, group)
                unknown.extend(v for v in group
                    if states[(v[0].scope.revision.source.document_id, v[1])]['state'] == 'unknown')
        grant = digest([dict(lane=mf.lane.value, document=p.scope.revision.source.document_id,
            key=k, input_hash=exact_input_hash(item_text((p, k, v)))) for p, k, v in unknown])
        require(len(unknown) == self.expected_unknown and {grant} == set(self.requested_batches), 'UNKNOWN_BATCH_IDENTITY_MISMATCH')
        self.authorized_unknown_items = tuple(unknown)
        self.result['alternate_preflight'] = dict(result='PASS', completed_revalidated=self.expected_reuse,
            counts=self.expected_counts, retry_grant=grant, state='EMBEDDING_STAGING')
        self.save('alternate-preflight-'+self.session_id, self.result['alternate_preflight'])
        key = self.env.pop('CANARY_GEMINI_API_KEY', None)
        try:
            self.provider = self.make_provider(key,
                organization_id=self.config.approval.organization_id,
                bot_id=self.config.approval.bot_id, approved=True, on_attempt=self.diagnostic,
                deadline_seconds=min(18000, self.deadline-perf_counter()))
        finally:
            key = None

    def compatibility_probe(self):
        self.progress('ALTERNATE_CREDENTIAL_COMPATIBILITY')
        mf = self.manifests[0]
        items = sorted(self.all_items(mf), key=lambda v: (v[0].scope.revision.source.document_id,
                                                         v[2].ordinal, v[1]))
        selected = []; seen = set()
        for item in items:
            ih = exact_input_hash(item_text(item))
            if ih not in seen:
                selected.append(item); seen.add(ih)
            if len(selected) == 3: break
        with self.repository() as repo:
            _, receipts = repo.completed(mf, selected)
        old = [receipts[(p.scope.revision.source.document_id, k)] for p, k, _ in selected]
        texts = [item_text(v) for v in selected]
        new = []
        with self.timing.stage('provider_wait'):
            for batch in bounded_batches(texts):
                new.extend(self.provider.embed(batch, purpose='evidence', retries=0))
        result = compare_receipts(texts, old, new, scope=self.provider.scope, profile=real_profile())
        result['credential_label'] = self.credential_label
        self.result['compatibility'] = result
        self.save('alternate-compatibility-'+self.session_id, result)
        # These are comparison receipts only; never replace retained vectors.
        self.provider.ledger.clear()
        require(result['result'] == 'PASS', self.mismatch_code)

    def quota_probe(self):
        self.progress('ALTERNATE_CREDENTIAL_QUOTA_PROBE')
        mf = self.manifests[1]; items = self.all_items(mf); selected = None
        with self.repository() as repo:
            for start in range(0, len(items), 100):
                group = items[start:start+100]; states = repo.states(mf, group)
                for item in group:
                    key = (item[0].scope.revision.source.document_id, item[1])
                    if states[key]['state'] == 'pending' and exact_input_hash(item_text(item)) not in self.receipt_index:
                        selected = item; break
                if selected is not None: break
        require(selected is not None, 'PENDING_UNEMBEDDED_QUOTA_PROBE_REQUIRED')
        before = len(self.provider.attempts)
        self.store_batch(mf, [selected], retries=0)
        require(len(self.provider.attempts)-before == 1, 'QUOTA_PROBE_MUST_BE_ONE_PROVIDER_CALL')
        with self.repository() as repo:
            receipt = repo.persisted_receipt(mf, selected[0], selected[1], item_text(selected))
        self.result['quota_probe'] = dict(result='PASS', input_hash=receipt.input_hash,
            vector_hash=receipt.vector_hash, persisted_without_repeat=True)
        self.save('alternate-quota-'+self.session_id, self.result['quota_probe'])

    def setup(self):
        super().setup()
        self.compatibility_probe()
        self.quota_probe()
        # Granted only after BOTH probes, for the exact authorized work inventory.
        self.approved_batches = set(self.requested_batches)
        self.result['retry_grant_enabled'] = True

    def run(self):
        try:
            return super().run()
        finally:
            self.env.pop('CANARY_GEMINI_API_KEY', None)


class SingleAttemptGemini(RecoverableGemini):
    """This continuation authorizes one spend, never an automatic retry."""
    def embed(self, texts, *, purpose, retries=0):
        return super().embed(texts, purpose=purpose, retries=0)


class RetainedDatabase:
    """Delegate the owned connection, but honor this run's explicit no-delete rule."""
    def __init__(self, database):
        self.database = database

    def __getattr__(self, name):
        return getattr(self.database, name)

    def cleanup(self):
        return dict(schema_removed=False, retained_by_operator_request=True)


class FinalCredentialRunner(AlternateCredentialRunner):
    """Exact 2,106-vector continuation; finish all queries before evaluation."""
    credential_label = 'new-development-credential'
    expected_reuse = 2106
    expected_unknown = 8
    expected_counts = {
        'canary_embedding_work': {'succeeded': 1030},
        'canary_legacy_embedding_work': {'succeeded': 1076, 'unknown': 8, 'pending': 8},
        'canary_query_work': {'pending': 90},
    }
    mismatch_code = 'EMBEDDING_CREDENTIAL_COMPATIBILITY_FAILURE'

    def make_provider(self, key, **kwargs):
        return SingleAttemptGemini(key, **kwargs)

    def setup(self):
        super().setup()
        self.db = RetainedDatabase(self.db)
        # Quota probe is durable before the one exact UNKNOWN grant is consumed.
        self.store_batch(self.manifests[1], self.authorized_unknown_items, retries=0)
        self.result['authorized_unknown_completed'] = self.expected_unknown

    def evaluate_paired(self, structural, legacy, started):
        # Existing paired seal stays atomic. No retrieval/security case runs
        # until all frozen query vectors have durable, readback-verified receipts.
        self.result['pre_query_seal_ms'] = self.seal(structural)
        require(len(self.common) == 90 and len(set(self.query_hashes())) == 90,
                'FROZEN_QUERY_INVENTORY_MISMATCH')
        for index, (snapshot, _) in enumerate(self.common, 1):
            self.progress('P2_DURABLE_QUERY_EMBEDDINGS', query=index, total=90)
            self.embed_query(snapshot['query'])
        require(self.counts()['canary_query_work'] == {'succeeded': 90},
                'ALL_QUERY_RECEIPTS_REQUIRED_BEFORE_EVALUATION')
        self.result['queries_durable_before_evaluation'] = 90
        # Parent uses the exact persisted vectors for both lanes and security.
        result = super().evaluate_paired(structural, legacy, started)
        self.result['retained'] = dict(namespace=self.config.namespace, run_id=self.run_id,
            identity_hash=self.identity_hash, retained_until=self.config.approval.expires_at,
            completed=True, automatic_resume=False)
        return result


def main():
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--identity-hash', required=True)
    parser.add_argument('--retry-batch', required=True)
    parser.add_argument('--spend-reference', required=True)
    parser.add_argument('--final-continuation', action='store_true')
    args = parser.parse_args()
    try:
        runner_type = FinalCredentialRunner if args.final_continuation else AlternateCredentialRunner
        return runner_type(Path(__file__).resolve().parents[2], os.environ,
            mode='resume', namespace=args.namespace, run_id=args.run_id, identity_hash=args.identity_hash,
            approved_batches=(args.retry_batch,), spend_reference=args.spend_reference).run()
    except Exception as exc:
        emit(dict(decision='C', failure=safe_failure(exc)))
        return 1
    finally:
        for key in ('CANARY_GEMINI_API_KEY','CANARY_DATABASE_URL','CANARY_REAL_EMBEDDING_AUTHORIZED',
                    'CANARY_RESUME_AUTHORIZED','CANARY_ENVIRONMENT','CANARY_TARGET_FINGERPRINT','CANARY_APPROVAL_REFERENCE'):
            os.environ.pop(key, None)


if __name__ == '__main__': raise SystemExit(main())
