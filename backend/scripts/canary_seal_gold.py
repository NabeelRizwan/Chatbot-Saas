"""Frozen seal cases shared by offline and real owned-PostgreSQL acceptance.

Caller supplies a staged, unsealed synthetic generation and a rollback savepoint.
No connection creation, provider, environment, or serving code.
"""
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, update
from services.canary_contracts import CanaryError, Lane, Policy, State
from services.canary_repository import manifest_values, source_values, where
from services.structural_chunking import digest
from scripts.canary_stage_a import hard_scope, make_manifest
from database import canary_schema as s

GOLD = Path(__file__).resolve().parents[1] / 'fixtures/canary_seal_identity_v1/gold.json'
GOLD_SHA = 'f4d40d45ca59b487b27feb40a61ca10681f2256d3abba0a4a4591ce2f3a0a2d5'


def cases():
    raw = GOLD.read_bytes()
    if hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != GOLD_SHA:
        raise CanaryError('SEAL_GOLD_CHANGED')
    return json.loads(raw)['cases']


def exercise(repo, base, batch, name, expected, now):
    token = repo.build_identity(base)
    attempted, seal_time = base, now
    key = {k: source_values(base.documents[0])[k] for k in ('organization_id', 'bot_id', 'document_id')}

    def mutate(**values):
        repo.conn.execute(update(s.lifecycle).where(where(s.lifecycle, key))
                          .values(**(values | {'epoch': s.lifecycle.c.epoch + 1})))

    def seal(value=base, identity=token):
        repo.seal_generation(value, expected_build_identity=identity, now=seal_time)

    if name in ('wrong_manifest_hash', 'unknown_manifest', 'stale_manifest'):
        field = {'wrong_manifest_hash': 'evaluation_hash', 'unknown_manifest': 'query_contract_hash',
                 'stale_manifest': 'implementation_hash'}[name]
        attempted = base.model_copy(update={field: digest(name)})
    elif name in ('wrong_generation', 'unstaged_generation'):
        attempted = base.model_copy(update={'generation': 'not-staged'})
    elif name == 'other_run':
        attempted = make_manifest(base.documents, run='other-valid-run', approved=repo.approval)
        repo.create(attempted, now=now)
        repo.stage(attempted, batch, now=now)
    elif name == 'other_lane':
        chunks = [{'id': 1, 'text': 'Synthetic legacy text.'}]
        pin = base.documents[0].model_copy(update={'entries': (), 'legacy_members': (1,), 'batch_hash': digest(chunks)})
        attempted = make_manifest((pin,), run=base.run_id, lane=Lane.LEGACY_CONTROL, approved=repo.approval)
        repo.create(attempted, now=now)
        repo.stage_legacy(attempted, pin, chunks, now=now)
    elif name in ('incomplete_generation', 'older_complete_newer_incomplete'):
        if name == 'older_complete_newer_incomplete':
            seal()
        attempted = make_manifest(base.documents, run=base.run_id, generation='generation-2', approved=repo.approval)
        repo.create(attempted, now=now)
        token = repo.build_identity(attempted)
    elif name == 'profile_mismatch':
        attempted = base.model_copy(update={'profile': base.profile.model_copy(update={'configuration_hash': digest('other-config')})})
    elif name == 'policy_mismatch':
        attempted = base.model_copy(update={'policy': Policy(rrf_k=61)})
    elif name in ('source_hash', 'source_version', 'structural_revision', 'crawl_version'):
        values = source_values(base.documents[0])
        field = {'source_hash': 'source_hash', 'source_version': 'source_version',
                 'structural_revision': 'revision', 'crawl_version': 'crawl_version'}[name]
        values[field] = digest('changed') if field in ('source_hash','revision') else values[field] + 1
        mutate(source_fingerprint=digest(values))
    elif name == 'processing':
        mutate(status='processing', processing='pending')
    elif name == 'epoch_only':
        mutate()
    elif name in ('state_aba', 'content_aba'):
        original = dict(repo.conn.execute(select(s.lifecycle).where(where(s.lifecycle, key))).mappings().one())
        field, value = ('status', 'processing') if name == 'state_aba' else ('source_fingerprint', digest('changed'))
        mutate(**{field: value})
        mutate(**{field: original[field]})
    elif name in ('cancelled', 'off'):
        repo.transition(base, State.CANCELLED if name == 'cancelled' else State.OFF, now=now)
    elif name == 'expired':
        seal_time = repo.approval.expires_at
    elif name in ('foreign_org', 'foreign_bot'):
        field = 'organization_id' if name == 'foreign_org' else 'bot_id'
        attempted = base.model_copy(update={'approval': base.approval.model_copy(update={field: getattr(base.approval, field)+1})})
    elif name in ('duplicate_seal', 'read_exact', 'read_wrong_generation', 'comparative_mixed_generation'):
        seal()
        if name != 'duplicate_seal':
            repo.transition(base, State.COMPARATIVE_EVAL, now=now)
        if name == 'read_wrong_generation':
            attempted = base.model_copy(update={'generation': 'not-staged'})
        if name == 'comparative_mixed_generation':
            attempted = make_manifest(base.documents, run=base.run_id, generation='generation-2', approved=repo.approval)
            repo.create(attempted, now=now)
            repo.stage(attempted, batch, now=now)
            repo.seal_generation(attempted, expected_build_identity=repo.build_identity(attempted), now=now)

    try:
        if name in ('read_exact', 'read_wrong_generation'):
            repo.read_gate(attempted, hard_scope(attempted), now=now)
        elif name == 'comparative_mixed_generation':
            repo.transition(attempted, State.COMPARATIVE_EVAL, now=now)
        else:
            repo.seal_generation(attempted, expected_build_identity=token, now=seal_time)
    except (CanaryError, ValueError) as exc:
        if not expected.startswith('REFUSE'):
            raise
        # Pydantic renders input details; return only a fixed category.
        code = str(exc) if isinstance(exc, CanaryError) else 'INVALID_MANIFEST_SCOPE'
        if name == 'duplicate_seal' and code != 'INVALID_TRANSITION':
            raise CanaryError('DUPLICATE_SEAL_SEMANTICS')
        if name in ('epoch_only', 'state_aba', 'content_aba') and code != 'STALE_SOURCE_EPOCH':
            raise CanaryError('EPOCH_WITNESS_NOT_CHECKED')
        if name in ('incomplete_generation', 'older_complete_newer_incomplete') and code != 'INCOMPLETE_BUILD':
            raise CanaryError('WRONG_INCOMPLETE_GENERATION_GUARD')
        return {'result': 'REFUSED', 'guard': code}
    if expected.startswith('REFUSE'):
        raise CanaryError('SEAL_GOLD_BAD_STATE_ACCEPTED')
    stored = repo._manifest(base)
    if stored['state'] not in ('INDEX_READY', 'COMPARATIVE_EVAL'):
        raise CanaryError('EXACT_SEAL_NOT_PUBLISHED')
    return {'result': expected, 'exact_build': stored['build_identity']}
