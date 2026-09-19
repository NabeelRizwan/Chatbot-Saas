"""Provider-free, exact sealed Phase-P evaluation continuation. Never a build.

The original approval/manifests remain immutable. An explicitly authorized
evaluation lease changes only the owned run/recovery expiry, with a durable
write-ahead audit. Retrieval/ranking/materialization functions are unchanged.
"""
import argparse
from contextlib import contextmanager, ExitStack
from hashlib import sha256
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import subprocess
from time import time, perf_counter
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, update, text
from database import canary_schema as s
from services.canary_contracts import Approval, Manifest, CanaryError, Lane, canonicalize_vector_f32, canonical_vector_digest
from services.canary_repository import run_values, manifest_values, source_values, where
from services.canary_representation import exact_input_hash
from services.canary_retrieval import run_query
from services.structural_chunking import digest
from services import structural_retrieval_entries_v2 as m
from scripts.canary_bounded_output import bounded_json, emit, vector_summary
from scripts.canary_gemini_embeddings import Attestation, real_profile, configuration, GeminiCanary
from scripts.canary_real_repository import RealAuthorization, receipt_payload
from scripts.canary_recovery_repository import RecoveryRepository
from scripts.canary_recovery_state import implementation_identity, RETENTION_SECONDS
from scripts.canary_evaluation_transport import ExclusiveRun, bounded_database_io, transient_transport, safe_error
from scripts.canary_evaluation_validation import fetch_document, validate_document
from scripts.canary_postgres_validation import DisposableCanary, settings, safe_failure, catalog_snapshot, NAMESPACE
from scripts.canary_real_evaluation import snapshots, score_case, safe_trace
from scripts.canary_real_summary import summarize

READABLE = {'CANARY_READ', 'COMPARATIVE_EVAL'}
REASON = 'ACTIVE_90_CASE_EVALUATION'


def require(ok, code):
    if not ok:
        raise CanaryError(code)


def deny_provider(*args, **kwargs):
    raise CanaryError('UNEXPECTED_PROVIDER_ACCESS')


@contextmanager
def provider_free():
    """No SDK client or Python HTTP/socket access; libpq uses its own transport."""
    with ExitStack() as stack:
        for target in ('httpx.Client.send', 'httpx.AsyncClient.send',
                       'requests.sessions.Session.request', 'socket.create_connection',
                       'socket.socket.connect', 'socket.socket.connect_ex'):
            stack.enter_context(patch(target, side_effect=deny_provider))
        for method in ('__init__', 'embed'):
            stack.enter_context(patch.object(GeminiCanary, method, side_effect=deny_provider))
        from scripts.canary_provider_recovery import RecoverableGemini
        stack.enter_context(patch.object(RecoverableGemini, 'embed', side_effect=deny_provider))
        yield


def read_bounded(path):
    require(path.stat().st_size <= 65536, 'INVALID_EVALUATION_ARTIFACT')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
        bounded_json(record)
        return record
    except (ValueError, UnicodeError):
        raise CanaryError('INVALID_EVALUATION_ARTIFACT') from None


def atomic_record(path, record, *, immutable=False):
    encoded = bounded_json(record) + '\n'
    if immutable and path.exists():
        require(read_bounded(path) == record, 'EVALUATION_ARTIFACT_CONFLICT')
        return
    temporary = path.with_name(path.name + '.pending')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def frozen_files(root):
    paths = list((root/'backend/services').glob('canary_*.py'))
    paths += [root/'backend/scripts'/name for name in (
        'canary_real_repository.py', 'canary_recovery_repository.py',
        'canary_real_evaluation.py', 'canary_real_summary.py',
        'canary_real_embedding_retrieval.py', 'canary_gemini_embeddings.py',
        'canary_recovery_state.py', 'canary_recovery_runner.py',
        'canary_postgres_validation.py', 'canary_evaluation_resume.py',
        'canary_evaluation_transport.py', 'canary_evaluation_validation.py')]
    paths += [root/'backend/database/canary_schema.py',
              root/'backend/fixtures/canary_real_embedding_v1/plan.json',
              root/'backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json']
    return {str(p.relative_to(root)).replace('\\', '/'): sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for p in sorted(set(paths))}


def validate_query(row, manifest, authorization, expected_input):
    vector = canonicalize_vector_f32(row['embedding'])
    receipt = Attestation(manifest.approval.organization_id, manifest.approval.bot_id,
        expected_input, manifest.profile.canonical_hash(), canonical_vector_digest(vector),
        vector, row['provider_receipt']['provider_attempt'])
    require(row['state'] == 'succeeded' and row['input_hash'] == expected_input
            and row['profile_hash'] == receipt.profile_hash and row['vector_hash'] == receipt.vector_hash
            and row['provider_receipt'] == receipt_payload(receipt, authorization)
            and type(receipt.provider_attempt) is int and receipt.provider_attempt > 0,
            'SAVED_QUERY_RECEIPT_CORRUPTION')
    return receipt


def validate_artifact(record, snapshot, hard, manifest, receipt, gold, entry_atoms):
    """Validate v1 results without rerunning retrieval or changing their bytes."""
    bounded_json(record)
    trace = record['trace']
    require(record['case'] == snapshot['id'] and record['lane'] == manifest.lane.value
            and record['snapshot_hash'] == snapshot['snapshot_hash']
            and record['query'] == vector_summary(receipt)
            and trace['query_hash'] == exact_input_hash(snapshot['query'])
            and trace['manifest'] == manifest.canonical_hash()
            and trace['hard_scope'] == hard.identity()
            and trace['effective_scope'] == list(manifest.effective(hard))
            and trace['mode'] == 'full_hybrid' and trace['source_revalidation'] == 'PASS',
            'EVALUATION_ARTIFACT_IDENTITY_MISMATCH')
    pins = {p.scope.revision.source.document_id: p for p in manifest.documents}
    def expand(value):
        pin = pins.get(value['document'])
        require(pin is not None and value['document'] in trace['effective_scope']
                and value['generation'] == manifest.generation, 'FOREIGN_EVALUATION_ROUTE')
        kind, key = value['kind'], value['key']
        valid = (kind == 'LEGACY_CHUNK' and manifest.lane == Lane.LEGACY_CONTROL
                 and key in {str(k) for k in pin.legacy_members}) or (
                 manifest.lane == Lane.STRUCTURAL_CANARY and
                 ((kind == 'ENTRY' and key in pin.entries) or (kind == 'ATOM_ONLY' and key in pin.atoms)))
        require(valid, 'UNDECLARED_EVALUATION_ROUTE')
        return dict(source=pin.scope.model_dump(mode='json'), kind=kind, key=key)
    reconstructed = {}
    for channel in ('dense', 'fts'):
        items = trace['raw_' + channel]
        require(len(items) <= manifest.policy.candidate_limit, 'EVALUATION_CANDIDATE_BOUND')
        reconstructed['raw_' + channel] = []
        for rank, row in enumerate(items, 1):
            require(row['rank'] == rank and math.isfinite(row['score']), 'INVALID_EVALUATION_RANK')
            expanded = expand(row['route'])
            key = row.get('atom')
            if channel == 'fts' and manifest.lane == Lane.STRUCTURAL_CANARY:
                require(key in pins[row['route']['document']].atoms, 'FOREIGN_EVALUATION_EVIDENCE')
            reconstructed['raw_' + channel].append(dict(route=expanded, evidence_key=key))
        require(trace['channels'][channel]['status'] == 'success'
                and math.isfinite(trace['channels'][channel]['ms'])
                and trace['channels'][channel]['ms'] >= 0, 'INVALID_EVALUATION_TIMING')
    require(len(trace['rrf']) <= manifest.policy.candidate_limit, 'EVALUATION_CANDIDATE_BOUND')
    reconstructed['rrf'] = []
    for rank, row in enumerate(trace['rrf'], 1):
        require(row['rank'] == rank and math.isfinite(row['total']), 'INVALID_EVALUATION_RANK')
        reconstructed['rrf'].append(dict(route=expand(row['route'])))
    units = []
    for row in trace['materialized']:
        pin = pins.get(row['route']['document'])
        expanded = expand(row['route'])
        require(row['key'] in (pin.atoms if manifest.lane == Lane.STRUCTURAL_CANARY
                              else tuple(map(str, pin.legacy_members))), 'FOREIGN_EVALUATION_EVIDENCE')
        units.append(dict(route=expanded, key=row['key']))
    require(len(units) <= manifest.policy.evidence_units and 0 <= trace['bytes'] <= manifest.policy.evidence_bytes
            and trace['status'] in ('COMPLETE', 'INCOMPLETE_BUDGET'), 'EVALUATION_BUDGET_MISMATCH')
    for key in ('rrf_ms', 'materialization_ms', 'total_ms'):
        require(math.isfinite(trace[key]) and trace[key] >= 0, 'INVALID_EVALUATION_TIMING')
    fts = trace['raw_fts']
    reconstructed.update(materialized=dict(units=units), final_status=trace['status'],
        route_collapse_ratio=1-len({digest(r['route']) for r in fts})/len(fts) if fts else 0)
    expected = score_case(reconstructed, gold, manifest.lane.value, manifest.effective(hard), entry_atoms)
    # v1 bounded traces retain only the first 48 fused routes. These two
    # diagnostics were computed over the full union (up to 96), unlike recall.
    # Preserve their original values; do not pretend the truncated trace can
    # reproduce unseen tail-route diagnostics exactly.
    for field, upper in (('candidate_diversity', len(manifest.effective(hard))),
                         ('atom_only', 2*manifest.policy.candidate_limit)):
        require(type(record['outcome'][field]) is int and
                expected[field] <= record['outcome'][field] <= upper, 'EVALUATION_SCORE_MISMATCH')
        expected[field] = record['outcome'][field]
    require(record['outcome'] == expected, 'EVALUATION_SCORE_MISMATCH')
    return dict(case=record['case'], lane=record['lane'], outcome=record['outcome'],
        dense_ms=trace['channels']['dense']['ms'], fts_ms=trace['channels']['fts']['ms'],
        rrf_ms=trace['rrf_ms'], materialization_ms=trace['materialization_ms'], total_ms=trace['total_ms'])


class EvaluationRepository(RecoveryRepository):
    """Same read gates/SQL; only explicitly renewed TTL differs from approval TTL."""
    def __init__(self, *args, lease_until, identities, inspection=False, **kwargs):
        self.lease_until, self.identities, self.inspection = lease_until, frozenset(identities), inspection
        super().__init__(*args, **kwargs)

    def _fresh(self, manifest, now, *, lock=False):
        require(manifest.canonical_hash() in self.identities, 'EVALUATION_MANIFEST_REFUSED')
        actual = max(now, int(self.clock()))
        # Inspection permits identity/source validation, never retrieval, before
        # an explicitly authorized renewal of an expired retained lease.
        expiry = max(self.lease_until, actual+1) if self.inspection else self.lease_until
        require(actual < expiry, 'EVALUATION_LEASE_EXPIRED')
        view = manifest.model_copy(update={'approval': manifest.approval.model_copy(update={'expires_at': expiry})})
        return super()._fresh(view, now, lock=lock)

    def read_gate(self, *args, **kwargs):
        require(not self.inspection, 'INSPECTION_CANNOT_RETRIEVE')
        return super().read_gate(*args, **kwargs)


def verify_ownership(db, conn, approval, control):
    saved = control['ownership']
    identity = control['identity']
    require(digest(saved) == identity['ownership_hash'], 'RESUME_OWNERSHIP_MISMATCH')
    current = tuple(conn.execute(text('SELECT oid,nspowner FROM pg_namespace WHERE nspname=:name'),
                                 {'name': db.config.namespace}).one())
    require(list(current) == saved['schema_identity']
            and [list(r) for r in db.relations(conn)] == saved['owned']
            and [list(r) for r in catalog_snapshot(conn, '') if r[1] == db.config.namespace] == saved['owned_catalog']
            and [list(r) for r in catalog_snapshot(conn, db.config.namespace)] == saved['before'],
            'RESUME_OWNERSHIP_MISMATCH')
    require([dict(r) for r in conn.execute(select(s.marker)).mappings()] == [dict(
        database_identity=approval.database_identity, marker=approval.ownership_marker,
        environment=approval.environment)], 'CANARY_OWNERSHIP_REFUSED')
    db.schema_identity = current


def verify_lease_chain(folder, identity_hash, original, retained):
    cursor = original
    for path in sorted(folder.glob('evaluation-lease-*.json')):
        event = read_bounded(path)
        require(event['identity_hash'] == identity_hash and event['reason'] == REASON
                and event['old_retained_until'] == cursor
                and event['new_retained_until'] == cursor + RETENTION_SECONDS,
                'EVALUATION_LEASE_AUDIT_MISMATCH')
        # A write-ahead event may survive a rolled-back DB transaction.
        if retained == cursor:
            require(path == sorted(folder.glob('evaluation-lease-*.json'))[-1], 'EVALUATION_LEASE_AUDIT_MISMATCH')
            return cursor
        cursor = event['new_retained_until']
    require(cursor == retained, 'EVALUATION_LEASE_AUDIT_MISMATCH')
    return retained


def renew_metadata(conn, manifest, identity_hash, old, new):
    require(new-old == RETENTION_SECONDS, 'EVALUATION_LEASE_INCREMENT_BOUND')
    key = run_values(manifest)
    row = conn.execute(select(s.recovery).where(where(s.recovery, key)).with_for_update()).mappings().one()
    run = conn.execute(select(s.runs).where(where(s.runs, key)).with_for_update()).mappings().one()
    require(row['identity_hash'] == identity_hash and row['retained_until'] == old
            and run['expires_at'] == old and run['state'] in READABLE
            and row['condition'] in ('PAUSED', 'PROVIDER_HOLD'), 'EVALUATION_LEASE_CONCURRENT_CHANGE')
    require(conn.execute(update(s.recovery).where(where(s.recovery, key), s.recovery.c.retained_until == old)
        .values(retained_until=new)).rowcount == 1, 'EVALUATION_LEASE_CONCURRENT_CHANGE')
    require(conn.execute(update(s.runs).where(where(s.runs, key), s.runs.c.expires_at == old)
        .values(expires_at=new)).rowcount == 1, 'EVALUATION_LEASE_CONCURRENT_CHANGE')


class EvaluationRunner:
    def __init__(self, root, env, *, namespace, run_id, identity_hash, renew_authorized=False,
                 execution_checkpoint=None):
        require(NAMESPACE.fullmatch(namespace or '') and namespace.startswith('canary_stagep_')
                and re.fullmatch('[a-f0-9]{64}', identity_hash or ''), 'EXACT_EVALUATION_IDENTITY_REQUIRED')
        require(env.get('CANARY_EVALUATION_ONLY_AUTHORIZED') == 'true', 'EVALUATION_NOT_AUTHORIZED')
        self.root, self.env, self.namespace, self.run_id, self.identity_hash = root, env, namespace, run_id, identity_hash
        self.renew_authorized = renew_authorized
        self.execution_checkpoint = execution_checkpoint
        self.folder = root/'.codex_phase4p'/namespace
        require(self.folder.is_dir(), 'RETAINED_ARTIFACTS_REQUIRED')
        self.session = uuid.uuid4().hex
        self.db = self.lock = None
        self.manifests = ()
        self.rows = {}
        self.reused = self.new_lanes = self.pairs_at_start = 0
        self.last_renew_progress = -1
        self.cleanup_errors = []
        self.transport_retries = 0
        self.current = self.last_completed = None
        self.result = dict(stage='EVALUATION_PREFLIGHT', provider_calls=0, session=self.session,
                           overall_deadline=None, decision='C')

    def save(self, name, value, **kwargs):
        atomic_record(self.folder/(name+'.json'), value, **kwargs)

    @contextmanager
    def repository(self, *, inspection=False, writable=False):
        @contextmanager
        def connection():
            if self.lock and self.lock.conn is not None:
                with self.lock.conn.begin():
                    self.db.configure(self.lock.conn)
                    yield self.lock.conn
            else:
                with self.db.transaction() as conn:
                    yield conn
        with connection() as conn:
            if not writable:
                conn.execute(text('SET TRANSACTION READ ONLY'))
            yield EvaluationRepository(conn, self.approval, authorization=self.authorization,
                lease_until=self.retained_until, identities=[mf.canonical_hash() for mf in self.manifests],
                inspection=inspection)

    @contextmanager
    def exclusive(self):
        require(self.lock is None, 'NESTED_EVALUATION_OWNERSHIP')
        self.lock = ExclusiveRun(self.db)
        primary = None
        try:
            self.lock.acquire()
            yield
        except BaseException as exc:
            primary = exc
            raise
        finally:
            errors = self.lock.close()
            self.result['connection_state'] = self.lock.connection_state
            self.cleanup_errors.extend(errors)
            self.lock = None
            if errors and primary is None:
                raise CanaryError('DATABASE_CLEANUP_FAILURE')

    def identity_gate(self):
        """Recheck ownership/run/seals/snapshots under each fresh lane lock."""
        with self.repository(inspection=True) as repo:
            control = repo.conn.execute(select(s.recovery).where(where(s.recovery, run_values(self.manifests[0])))).mappings().one()
            require(control['identity_hash'] == self.identity_hash == digest(control['identity'])
                    and control['identity'] == self.identity, 'RESUME_IDENTITY_MISMATCH')
            require(control['retained_until'] == self.retained_until, 'EVALUATION_LEASE_MISMATCH')
            verify_ownership(self.db, repo.conn, self.approval, control)
            for mf, proof in zip(self.manifests, self.identity['manifests']):
                run, stored = repo._run(mf), repo._manifest(mf)
                require(run['state'] in READABLE and run['expires_at'] == self.retained_until
                        and stored['state'] in READABLE and stored['build_identity'] == proof['build_identity'],
                        'EXACT_SEALED_GENERATION_REQUIRED')
                repo._snapshot(mf, stored, int(time()))

    def setup(self):
        self.plan = json.loads((self.root/'backend/fixtures/canary_real_embedding_v1/plan.json').read_text())
        self.common = snapshots(self.root, self.plan)
        self.snapshot_hash = digest([v[0]['snapshot_hash'] for v in self.common])
        first_scope = self.common[0][1]
        self.config = settings(self.env, stage='p', organization_id=first_scope.organization_id, bot_id=first_scope.bot_id)
        self.config.namespace = self.namespace
        self.db = DisposableCanary(self.config)
        self.result['postgres'] = self.db.open()
        with self.db.transaction() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            runs = conn.execute(select(s.runs).where(s.runs.c.run_id == self.run_id)).mappings().all()
            require(len(runs) == 1, 'EXPLICIT_RESUME_RUN_REQUIRED')
            run = runs[0]
            self.approval = Approval.model_validate(run['approval'])
            a = self.approval
            require(a.ownership_marker == self.namespace and a.database_identity == self.config.approval.database_identity
                    and a.operator_reference == self.env['CANARY_APPROVAL_REFERENCE']
                    and (a.organization_id, a.bot_id) == (first_scope.organization_id, first_scope.bot_id)
                    and a.environment == 'disposable_test' and run['state'] in READABLE
                    and run['approval_hash'] == a.canonical_hash(), 'RESUME_APPROVAL_MISMATCH')
            key = {k: run[k] for k in s.RUN}
            control = conn.execute(select(s.recovery).where(where(s.recovery, key))).mappings().one()
            self.identity = control['identity']
            require(control['identity_hash'] == self.identity_hash == digest(self.identity)
                    and self.identity['run'] == key and self.identity['schema'] == self.namespace
                    and self.identity['target'] == a.database_identity and self.identity['approval'] == a.canonical_hash()
                    and self.identity['recovery_implementation'] == implementation_identity()
                    and control['condition'] in ('PAUSED', 'PROVIDER_HOLD', 'COMPLETE'), 'RESUME_IDENTITY_MISMATCH')
            self.retained_until = control['retained_until']
            require(run['expires_at'] == self.retained_until, 'EVALUATION_LEASE_MISMATCH')
            verify_lease_chain(self.folder, self.identity_hash, a.expires_at, self.retained_until)
            verify_ownership(self.db, conn, a, control)
            self.manifests = tuple(Manifest.model_validate(v) for v in conn.execute(select(s.manifests.c.payload)
                .where(where(s.manifests, key)).order_by(s.manifests.c.lane.desc())).scalars())
        self.config.approval = self.approval
        self.authorization = RealAuthorization(a.operator_reference, a.organization_id, a.bot_id, real_profile().configuration_hash)
        require(len(self.manifests) == 2 and {mf.lane for mf in self.manifests} == set(Lane), 'SEALED_PAIR_REQUIRED')
        require([(mf.lane.value, mf.canonical_hash()) for mf in self.manifests] ==
                [(v['lane'], v['manifest']) for v in self.identity['manifests']], 'RESUME_MANIFEST_MISMATCH')
        self.sidecar = json.loads((self.root/'backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json').read_text())
        self.gold = {int(c['case_id']): c for c in self.sidecar['cases']}
        self.validate_sealed(full=True)
        self.code = frozen_files(self.root)
        baselines = []
        for path in self.folder.glob('result-*.json'):
            record = read_bounded(path)
            if (record.get('retained', {}).get('identity_hash') == self.identity_hash
                    and record.get('queries_durable_before_evaluation') == 90 and 'security' in record):
                baselines.append((path, record))
        require(len(baselines) == 1, 'EXACT_SECURITY_BASELINE_REQUIRED')
        baseline_path, baseline = baselines[0]
        security = baseline['security']
        require(set(security) == {'foreign_org', 'foreign_bot', 'stale_generation', 'stale_source', 'identical_text_other_scope'}
                and all(value[field] == 0 for value in security.values() for field in
                    ('dense_unauthorized', 'fts_unauthorized', 'routing_unauthorized', 'materialization_unauthorized')),
                'SECURITY_BASELINE_FAILURE')
        self.result['security'] = security
        self.load_cases()
        self.pairs_at_start = self.completed()
        admission = dict(identity_hash=self.identity_hash, frozen_files=self.code,
            query_inventory=digest(sorted((k, v.vector_hash) for k, v in self.queries.items())),
            manifests=[mf.canonical_hash() for mf in self.manifests],
            security_baseline_sha256=sha256(baseline_path.read_bytes()).hexdigest(),
            frozen=self.identity['frozen'])
        self.admit_execution(admission)
        self.result.update(stage='EVALUATION_READY', reused_lanes=self.reused, pairs_at_start=self.pairs_at_start,
                           retained_until=self.retained_until, identity_hash=self.identity_hash)
        self.save('evaluation-session-'+self.session, dict(self.result, status='RUNNING'))
        self.aggregate()
        emit(dict(stage='EVALUATION_READY', reused_lanes=self.reused, completed_pairs=self.completed(), provider_calls=0))

    def admit_execution(self, admission):
        """Keep the old admission immutable; explicitly audit execution-only changes."""
        previous = read_bounded(self.folder/'evaluation-admission.json')
        if admission == previous:
            return
        checkpoint = self.execution_checkpoint
        require(re.fullmatch('[a-f0-9]{40}', checkpoint or ''), 'EXECUTION_CHECKPOINT_REQUIRED')
        path = 'backend/scripts/canary_evaluation_resume.py'
        old_source = subprocess.check_output(['git', 'show', checkpoint+':'+path], cwd=self.root,
                                             stderr=subprocess.DEVNULL)
        require(sha256(old_source.replace(b'\r\n', b'\n')).hexdigest() == previous['frozen_files'][path],
                'EXECUTION_CHECKPOINT_MISMATCH')
        allowed_new = {'backend/scripts/canary_evaluation_transport.py', 'backend/scripts/canary_evaluation_validation.py'}
        require(set(admission['frozen_files']) == set(previous['frozen_files']) | allowed_new
                and all(admission['frozen_files'][p] == h for p, h in previous['frozen_files'].items() if p != path)
                and dict(admission, frozen_files=previous['frozen_files']) == previous,
                'NON_EXECUTION_IDENTITY_CHANGE_REFUSED')
        self.save('evaluation-execution-'+digest(self.code), dict(checkpoint=checkpoint,
            original_admission_hash=digest(previous), admission=admission,
            reason='DATABASE_TRANSPORT_TERMINAL_REPAIR'), immutable=True)

    def validated_document(self, mf, pin, proof):
        doc = pin.scope.revision.source.document_id
        for attempt in range(2):
            try:
                with self.exclusive():
                    if attempt:
                        self.identity_gate()
                    with self.repository(inspection=True) as repo:
                        run, stored = repo._run(mf), repo._manifest(mf)
                        require(run['state'] in READABLE and stored['state'] in READABLE
                                and stored['state_epoch'] >= 2 and stored['build_identity'] == proof['build_identity'],
                                'EXACT_SEALED_GENERATION_REQUIRED')
                        repo._snapshot(mf, stored, int(time()))
                        data = fetch_document(repo.conn, mf, pin)
                        checksum = validate_document(repo, mf, pin, data)
                        repo._snapshot(mf, repo._manifest(mf), int(time()))
                return data, checksum
            except Exception as exc:
                if attempt or not transient_transport(exc):
                    raise
                self.transport_retries += 1
                event = dict(stage='PREFLIGHT_TRANSPORT_RETRY', document=doc, lane=mf.lane.value,
                             TRANSPORT_RETRY=1, failure=safe_error(exc), timestamp=int(time()))
                self.save(f'evaluation-preflight-retry-{self.session}-{doc}-{mf.lane.value}', event, immutable=True)
                emit(event)

    def validate_sealed(self, *, full=False, writable=False):
        require(not writable, 'VALIDATION_IS_READ_ONLY')
        legacy, batch_hashes, document_proofs = {}, [], []
        self.entry_atoms = {}
        for mf, proof in zip(self.manifests, self.identity['manifests']):
            require(mf.implementation_hash == self.plan['m_implementation'] == m._implementation_hash()
                    and mf.query_contract_hash == self.snapshot_hash
                    and mf.evaluation_hash == self.plan['evaluation_sha256'], 'FROZEN_EVALUATION_CHANGED')
            inventory = []
            for pin in mf.documents:
                doc = pin.scope.revision.source.document_id
                data, checksum = self.validated_document(mf, pin, proof)
                table = s.legacy_work if mf.lane == Lane.LEGACY_CONTROL else s.work
                column = 'chunk_id' if mf.lane == Lane.LEGACY_CONTROL else 'entry_id'
                work = data[table.name]
                require(all(r['state'] == 'succeeded' for r in work), 'RESUME_WORK_INVENTORY_MISMATCH')
                inventory.extend((r['document_id'], r[column], r['input_hash']) for r in work)
                document_proofs.append(dict(document=doc, lane=mf.lane.value, checksum=checksum))
                if mf.lane == Lane.LEGACY_CONTROL:
                    legacy[doc] = [r['payload'] for r in sorted(data[s.legacy.name], key=lambda r:r['chunk_id'])]
                else:
                    raw = data[s.sources.name][0]['payload']
                    require(digest(raw) == pin.batch_hash == self.sidecar['representation_pins'][str(doc)]['batch_hash'],
                            'FROZEN_SOURCE_CHANGED')
                    batch_hashes.append(pin.batch_hash)
                    for entry in raw['entries']:
                        self.entry_atoms[(doc, entry['entry_key'])] = tuple({v['atom_key'] for v in entry['memberships']})
                emit(dict(stage='SEALED_DOCUMENT_VALIDATED', lane=mf.lane.value, document=doc))
            require(len(inventory) == proof['work_count'] and digest(sorted(inventory)) == proof['inventory_hash'],
                    'RESUME_WORK_INVENTORY_MISMATCH')
        hashes = [exact_input_hash(v[0]['query']) for v in self.common]
        frozen = dict(m_digest=sha256(''.join(batch_hashes).encode()).hexdigest(), snapshots=self.snapshot_hash,
                      profile=real_profile().canonical_hash(), configuration=real_profile().configuration_hash,
                      legacy=digest(legacy), plan=digest(self.plan))
        require(frozen == self.identity['frozen'] and len(hashes) == len(set(hashes)) == 90
                and digest(hashes) == self.identity['query_inventory'], 'FROZEN_CORPUS_QUERY_CHANGED')
        with self.exclusive():
            self.identity_gate()
            with self.repository(inspection=True) as repo:
                records = repo.conn.execute(select(s.query_work).where(where(s.query_work, run_values(self.manifests[0])))
                    .order_by(s.query_work.c.input_hash).limit(91)).mappings().all()
        require({r['input_hash'] for r in records} == set(hashes) and len(records) == 90, 'SAVED_QUERY_INVENTORY_MISMATCH')
        self.queries = {r['input_hash']:validate_query(r, self.manifests[0], self.authorization, r['input_hash']) for r in records}
        self.validation_proof = dict(documents=document_proofs, checksum=digest(document_proofs),
                                     query_inventory=digest(sorted((k,v.vector_hash) for k,v in self.queries.items())))
        self.save('evaluation-validation-'+self.validation_proof['checksum'], self.validation_proof, immutable=True)

    def load_cases(self, *, count_reuse=True):
        expected = {self.case_name(v[0]['id'], mf): (v, mf) for v in self.common for mf in self.manifests}
        require(all(p.stem in expected for p in self.folder.glob('case-*.json')), 'UNEXPECTED_CASE_ARTIFACT')
        for name, ((snapshot, hard), mf) in expected.items():
            path = self.folder/(name+'.json')
            if path.exists():
                record = read_bounded(path)
                self.rows[(snapshot['id'], mf.lane.value)] = self.validate(record, snapshot, hard, mf)
                if count_reuse:
                    self.reused += 1
        # Existing pair checksums protect artifact reuse against later tampering.
        for snapshot, _ in self.common:
            self.pair(snapshot['id'])

    @staticmethod
    def case_name(case, mf):
        return f'case-{case:02d}-{mf.lane.value}'

    def validate(self, record, snapshot, hard, mf):
        return validate_artifact(record, snapshot, hard, mf,
            self.queries[exact_input_hash(snapshot['query'])], self.gold[snapshot['id']], self.entry_atoms)

    def pair(self, case):
        if all((case, mf.lane.value) in self.rows for mf in self.manifests):
            self.save(f'evaluation-pair-{case:02d}', dict(case=case, identity_hash=self.identity_hash,
                status='COMPLETE', lanes=[dict(lane=mf.lane.value,
                    artifact_sha256=sha256((self.folder/(self.case_name(case, mf)+'.json')).read_bytes()).hexdigest())
                    for mf in self.manifests]), immutable=True)

    def completed(self):
        return sum(all((v[0]['id'], mf.lane.value) in self.rows for mf in self.manifests) for v in self.common)

    def aggregate(self):
        paired = [r for (case, _), r in sorted(self.rows.items())
                  if all((case, mf.lane.value) in self.rows for mf in self.manifests)]
        if not paired:
            return
        summary = summarize(paired)
        summary.update(completed_pairs=self.completed(), remaining_pairs=90-self.completed(),
                       status='COMPLETE' if self.completed() == 90 else 'PARTIAL', provider_calls=0,
                       identity_hash=self.identity_hash)
        if self.completed() != 90:
            summary['decision'] = 'PENDING_FULL_BASELINE'
        self.save('evaluation-incremental', summary)
        return summary

    def ensure_lease(self):
        if self.retained_until > int(time()) + 3600:
            return
        require(self.renew_authorized and len(self.rows) > self.last_renew_progress, 'EVALUATION_LEASE_RENEWAL_NOT_AUTHORIZED')
        old, new = self.retained_until, self.retained_until + RETENTION_SECONDS
        require(new > int(time()), 'EXPLICIT_EXPIRED_LEASE_REVIEW_REQUIRED')
        # No leased reads until the exact source/generation/vector/query proof passes.
        self.validate_sealed(full=True)
        event = dict(identity_hash=self.identity_hash, old_retained_until=old,
                     new_retained_until=new, reason=REASON, namespace=self.namespace, run=self.run_id,
                     manifests=[mf.canonical_hash() for mf in self.manifests],
                     source_snapshot_verification='PASS', validation_hash=self.validation_proof['checksum'],
                     operator_reference=self.approval.operator_reference)
        self.save(f'evaluation-lease-{new}', event, immutable=True)
        with self.exclusive(), self.repository(inspection=True, writable=True) as repo:
            control = repo.conn.execute(select(s.recovery).where(where(s.recovery, run_values(self.manifests[0])))).mappings().one()
            verify_ownership(self.db, repo.conn, self.approval, control)
            for mf in self.manifests:
                stored = repo._manifest(mf)
                require(stored['state'] in READABLE, 'EXACT_SEALED_GENERATION_REQUIRED')
                repo._snapshot(mf, stored, int(time()), lock=True)
            renew_metadata(repo.conn, self.manifests[0], self.identity_hash, old, new)
        self.retained_until = new
        self.last_renew_progress = len(self.rows)
        self.save(f'evaluation-renewed-{new}', event, immutable=True)
        emit(dict(stage='LEASE_RENEWED', **event))

    def next_lane(self):
        for snapshot, _ in getattr(self, 'common', ()):
            for mf in sorted(self.manifests, key=lambda v:v.lane.value):
                if (snapshot['id'], mf.lane.value) not in self.rows:
                    return dict(case=snapshot['id'], lane=mf.lane.value)
        return None

    def saved_progress(self):
        """Terminal-only checksum inventory, including a preflight that failed early.

        This is not corpus authorization and cannot permit retrieval. It prevents
        an early DB failure from falsely reporting that old saved cases vanished.
        """
        saved = set()
        for case in range(1, 91):
            pair = self.folder/f'evaluation-pair-{case:02d}.json'
            if not pair.exists():
                continue
            record = read_bounded(pair)
            require(record['identity_hash'] == self.identity_hash and record['case'] == case
                    and record['status'] == 'COMPLETE'
                    and {v['lane'] for v in record['lanes']} == {v.value for v in Lane},
                    'TERMINAL_CHECKSUM_IDENTITY_MISMATCH')
            for lane in record['lanes']:
                path = self.folder/f"case-{case:02d}-{lane['lane']}.json"
                require(sha256(path.read_bytes()).hexdigest() == lane['artifact_sha256'], 'TERMINAL_CHECKSUM_MISMATCH')
                saved.add((case, lane['lane']))
        saved.update(self.rows)
        lanes = tuple(v.value for v in Lane)
        pairs = [case for case in range(1,91) if all((case,lane) in saved for lane in lanes)]
        next_work = next((dict(case=case,lane=lane) for case in range(1,91)
                          for lane in sorted(lanes) if (case,lane) not in saved),None)
        last = max(saved, default=None)
        return dict(completed_pairs=len(pairs), last_completed_case=max(pairs,default=None), next_resumable_lane=next_work,
                    last_completed_lane=dict(case=last[0], lane=last[1]) if last else None)

    def evaluate_lane(self, snapshot, hard, mf):
        case = snapshot['id']
        self.current = dict(case=case, lane=mf.lane.value)
        retry_path = self.folder/(f'evaluation-retry-{case:02d}-{mf.lane.value}.json')
        for attempt in range(2):
            try:
                with self.exclusive():
                    self.identity_gate()
                    # Another authorized evaluator might have saved a lane between
                    # ownership sessions. Validate/reuse it; never repeat it.
                    path = self.folder/(self.case_name(case, mf)+'.json')
                    if path.exists():
                        self.rows[(case, mf.lane.value)] = self.validate(read_bounded(path), snapshot, hard, mf)
                        self.pair(case)
                        return
                    emit(dict(stage='EVALUATION_LANE', **self.current, completed_pairs=self.completed()))
                    qr = self.queries[exact_input_hash(snapshot['query'])]
                    with self.repository() as repo:
                        trace = run_query(repo, mf, hard, query=snapshot['query'], query_vector=qr.vector, now=int(time()))
                    require(trace['mode'] == 'full_hybrid', 'PAIRED_CHANNEL_FAILURE')
                    record = dict(case=case, lane=mf.lane.value, snapshot_hash=snapshot['snapshot_hash'], query=vector_summary(qr),
                        outcome=score_case(trace, self.gold[case], mf.lane.value, mf.effective(hard), self.entry_atoms), trace=safe_trace(trace))
                    row = self.validate(record, snapshot, hard, mf)
                    self.save(self.case_name(case, mf), record, immutable=True)
                    self.rows[(case, mf.lane.value)] = row
                    self.last_completed = dict(self.current)
                    self.new_lanes += 1
                    self.pair(case)
                    self.aggregate()
                    self.save('evaluation-session-'+self.session, dict(self.result, status='RUNNING',
                        new_lanes=self.new_lanes, completed_pairs=self.completed(), last_case=case, last_lane=mf.lane.value))
                return
            except Exception as exc:
                saved = (self.folder/(self.case_name(case, mf)+'.json')).exists()
                if saved or attempt or retry_path.exists() or not transient_transport(exc):
                    raise
                retry = dict(identity_hash=self.identity_hash, **self.current, session=self.session,
                    TRANSPORT_RETRY=1, failure=safe_error(exc), timestamp=int(time()), provider_calls=0)
                atomic_record(retry_path, retry, immutable=True)
                self.transport_retries += 1
                emit(dict(stage='TRANSPORT_RETRY', **retry))

    def evaluate(self):
        for snapshot, hard in self.common:
            case = snapshot['id']
            for mf in sorted(self.manifests, key=lambda v:v.lane.value):
                if (case, mf.lane.value) in self.rows:
                    continue
                require(frozen_files(self.root) == self.code, 'FROZEN_RETRIEVAL_IMPLEMENTATION_CHANGED')
                self.ensure_lease()
                self.evaluate_lane(snapshot, hard, mf)
        require(self.completed() == 90, 'FULL_PAIRED_EVALUATION_REQUIRED')
        self.load_cases(count_reuse=False)
        self.validate_sealed(full=True)
        with self.exclusive(), self.repository(writable=True) as repo:
            control = repo.conn.execute(select(s.recovery).where(where(s.recovery, run_values(self.manifests[0])))).mappings().one()
            verify_ownership(self.db, repo.conn, self.approval, control)
            repo.conn.execute(update(s.recovery).where(where(s.recovery, run_values(self.manifests[0]))).values(condition='COMPLETE'))
        self.result.update(self.aggregate())
        self.result.update(stage='FULL_EVALUATION_ONLY_COMPLETION', new_lanes=self.new_lanes,
                           retained_until=self.retained_until, unrelated_catalog_unchanged=True)

    def run(self):
        started = perf_counter()
        primary = None
        final_cleanup = []
        with bounded_database_io(), provider_free():
            try:
                self.setup()
                self.evaluate()
            except BaseException as exc:
                primary = safe_error(exc)
                self.result.update(decision='C', failure=primary)
            finally:
                # Cleanup exceptions cannot skip terminal persistence or replace
                # the primary failure. A failed terminal write has a separate
                # fallback artifact and safe stdout record.
                for obj in (self.lock, self.db):
                    if obj is not None:
                        try:
                            errors = obj.close()
                            if isinstance(errors, list):
                                final_cleanup.extend(errors)
                        except BaseException as exc:
                            final_cleanup.append(safe_error(exc))
                self.cleanup_errors.extend(final_cleanup)
                if primary is None and final_cleanup:
                    self.result.update(decision='C', failure=final_cleanup[0])
                completed = self.completed() if hasattr(self, 'common') and self.manifests else 0
                last_pair = max((v[0]['id'] for v in getattr(self, 'common', ())
                                if self.manifests and all((v[0]['id'], mf.lane.value) in self.rows for mf in self.manifests)),
                                default=None)
                terminal = dict(self.result, status='COMPLETE' if self.result['decision'] in ('A','B') else 'SAFE_STOP',
                    elapsed_ms=(perf_counter()-started)*1000, new_lanes=self.new_lanes,
                    primary_error=primary, cleanup_errors=self.cleanup_errors[-16:],
                    completed_pairs=completed, last_completed_case=last_pair,
                    last_completed_lane=self.last_completed, current_lane=self.current,
                    next_resumable_lane=self.next_lane(), transport_retry_count=self.transport_retries,
                    timestamp=int(time()), provider_calls=0)
                try:
                    terminal.update(self.saved_progress())
                except BaseException as exc:
                    terminal.update(status='SAFE_STOP', decision='C', progress_check_error=safe_error(exc))
                try:
                    self.save('evaluation-session-'+self.session, terminal)
                except BaseException as exc:
                    terminal.update(status='SAFE_STOP', decision='C', terminal_write_error=safe_error(exc))
                    try:
                        atomic_record(self.folder/('evaluation-terminal-'+self.session+'.json'), terminal)
                    except BaseException as fallback:
                        terminal['terminal_fallback_error'] = safe_error(fallback)
                finally:
                    for key in tuple(self.env):
                        if key.startswith('CANARY_'):
                            self.env.pop(key, None)
                self.result = terminal
                emit(terminal)
        return 0 if self.result['decision'] in ('A', 'B') else 1


def main():
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--identity-hash', required=True)
    parser.add_argument('--renew-lease', action='store_true')
    parser.add_argument('--execution-checkpoint', help='Explicit reviewed local checkpoint for execution-only repair')
    args = parser.parse_args()
    try:
        return EvaluationRunner(Path(__file__).resolve().parents[2], os.environ,
            namespace=args.namespace, run_id=args.run_id, identity_hash=args.identity_hash,
            renew_authorized=args.renew_lease, execution_checkpoint=args.execution_checkpoint).run()
    except Exception as exc:
        emit(dict(decision='C', failure=safe_failure(exc), provider_calls=0))
        return 1
    finally:
        for name in tuple(os.environ):
            if name.startswith('CANARY_'):
                os.environ.pop(name, None)


if __name__ == '__main__':
    raise SystemExit(main())
