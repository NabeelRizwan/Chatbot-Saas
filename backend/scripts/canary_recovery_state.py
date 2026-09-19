"""Exact operator-owned resume identity and spend ledger, never serving state."""
from hashlib import sha256
from pathlib import Path
import re
from sqlalchemy import insert,select,update,text
from database import canary_schema as s
from services.canary_contracts import Approval,CanaryError,Manifest,State,Lane
from services.canary_repository import run_values,manifest_values,document_values,where
from services.canary_representation import exact_input_hash
from services.structural_chunking import digest
from scripts.canary_bounded_output import bounded_json
from scripts.canary_postgres_validation import NAMESPACE,catalog_snapshot

RETENTION_SECONDS=86400


def implementation_identity():
    names=('canary_provider_recovery.py','canary_recovery_state.py','canary_recovery_runner.py',
           'canary_real_repository.py','canary_real_embedding_retrieval.py','canary_recovery_repository.py')
    return digest({name:sha256(Path(__file__).with_name(name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                   for name in names})


def ownership(db):
    return dict(schema_identity=list(db.schema_identity),marker_identity=list(db.marker_identity),
        owned=[list(r) for r in db.owned],owned_catalog=[list(r) for r in db.owned_catalog],
        before=[list(r) for r in db.before])


def initialize(repo,manifests,*,frozen_identity,owned,query_hashes,now):
    first=manifests[0]; a=first.approval
    if a.expires_at-a.created_at>RETENTION_SECONDS or now>=a.expires_at:
        raise CanaryError('RETENTION_BOUND')
    manifest_records=[]
    for mf in manifests:
        repo._staging(mf,now)
        table=s.work if mf.lane==Lane.STRUCTURAL_CANARY else s.legacy_work
        col='entry_id' if mf.lane==Lane.STRUCTURAL_CANARY else 'chunk_id'
        rows=repo.conn.execute(select(table).where(where(table,manifest_values(mf)))
            .order_by(table.c.document_id,table.c[col])).mappings().all()
        inventory=[(r['document_id'],r[col],r['input_hash']) for r in rows]
        manifest_records.append(dict(manifest=mf.canonical_hash(),lane=mf.lane.value,
            build_identity=repo.build_identity(mf),inventory_hash=digest(inventory),work_count=len(rows)))
    identity=dict(contract='real-canary-recovery-v1',schema=a.ownership_marker,
        target=a.database_identity,run=run_values(first),approval=a.canonical_hash(),
        retained_until=a.expires_at,manifests=manifest_records,frozen=frozen_identity,
        query_inventory=digest(query_hashes),ownership_hash=digest(owned),
        recovery_implementation=implementation_identity())
    repo.conn.execute(insert(s.recovery).values(**run_values(first),identity_hash=digest(identity),
        identity=identity,ownership=owned,retained_until=a.expires_at,condition='BUILDING'))
    if query_hashes:
        repo.conn.execute(insert(s.query_work),[dict(**run_values(first),input_hash=h,
            state='pending',profile_hash=first.profile.canonical_hash()) for h in query_hashes])
    return identity


def validate(repo,manifests,*,expected_hash,frozen_identity,query_hashes,now):
    first=manifests[0]
    row=repo.conn.execute(select(s.recovery).where(where(s.recovery,run_values(first)))
        .with_for_update()).mappings().one()
    identity=row['identity']
    if (digest(identity)!=expected_hash or row['identity_hash']!=expected_hash
            or identity['frozen']!=frozen_identity or identity['run']!=run_values(first)
            or identity['approval']!=first.approval.canonical_hash()
            or identity['recovery_implementation']!=implementation_identity()
            or identity['query_inventory']!=digest(query_hashes)
            or identity['ownership_hash']!=digest(row['ownership'])):
        raise CanaryError('RESUME_IDENTITY_MISMATCH')
    if now>=row['retained_until'] or row['retained_until']!=first.approval.expires_at:
        raise CanaryError('RETAINED_RUN_EXPIRED')
    if row['condition'] not in ('BUILDING','PROVIDER_HOLD','PAUSED'):
        raise CanaryError('RETAINED_RUN_NOT_RESUMABLE')
    if [(m.lane.value,m.canonical_hash()) for m in manifests] != [
            (v['lane'],v['manifest']) for v in identity['manifests']]:
        raise CanaryError('RESUME_MANIFEST_MISMATCH')
    for mf,proof in zip(manifests,identity['manifests']):
        repo._active(repo._run(mf,lock=True))
        stored=repo._manifest(mf)
        repo._snapshot(mf,stored,now,lock=True)
        if repo.build_identity(mf)!=proof['build_identity']:
            raise CanaryError('RESUME_BUILD_IDENTITY_MISMATCH')
        table=s.work if mf.lane==Lane.STRUCTURAL_CANARY else s.legacy_work
        col='entry_id' if mf.lane==Lane.STRUCTURAL_CANARY else 'chunk_id'
        rows=repo.conn.execute(select(table).where(where(table,manifest_values(mf)))
            .order_by(table.c.document_id,table.c[col])).mappings().all()
        if digest([(r['document_id'],r[col],r['input_hash']) for r in rows])!=proof['inventory_hash']:
            raise CanaryError('RESUME_WORK_INVENTORY_MISMATCH')
    queries=repo.conn.execute(select(s.query_work.c.input_hash).where(where(s.query_work,run_values(first)))).scalars().all()
    if set(queries)!=set(query_hashes) or len(queries)!=len(query_hashes):
        raise CanaryError('RESUME_QUERY_INVENTORY_MISMATCH')
    return identity


def mark(repo,mf,condition):
    repo.conn.execute(update(s.recovery).where(where(s.recovery,run_values(mf))).values(condition=condition))


def record_attempt(repo,mf,session_id,record):
    bounded_json(record)
    key=dict(**run_values(mf),session_id=session_id,attempt=record['attempt'])
    old=repo.conn.execute(select(s.attempts.c.diagnostic).where(where(s.attempts,key))).scalar_one_or_none()
    if record['result']=='STARTED':
        if old is not None:raise CanaryError('DUPLICATE_PROVIDER_ATTEMPT')
        repo.conn.execute(insert(s.attempts).values(**key,diagnostic=record))
    else:
        if old is None or old['result']!='STARTED' or old['batch_hash']!=record['batch_hash']:
            raise CanaryError('ATTEMPT_LEDGER_CONFLICT')
        repo.conn.execute(update(s.attempts).where(where(s.attempts,key)).values(diagnostic=record))


def authorize_unknown(repo,mf,items,*,approved_batches,reference,session_id):
    """One explicit grant per exact work-batch; no unknown->pending reset.

    Existing unknown work may complete, but the spend grant is committed before
    HTTP and cannot be reused after a crash. Old successful work is immutable.
    """
    identity=digest([dict(lane=mf.lane.value,document=p.scope.revision.source.document_id,
        key=k,input_hash=exact_input_hash(v.text if hasattr(v,'text') else v['text'])) for p,k,v in items])
    if identity not in approved_batches or not re.fullmatch(r'[A-Za-z0-9_-]{4,128}',reference or ''):
        raise CanaryError('UNKNOWN_CONSUMPTION_EXPLICIT_BATCH_GRANT_REQUIRED')
    repo.conn.execute(insert(s.spend_grants).values(**run_values(mf),batch_hash=identity,
        approval_reference=reference,session_id=session_id))
    return identity


def open_retained(db,*,namespace,run_id,expected_hash,reference,now,cleanup_only=False):
    """Exact named attach only. Fresh open still refuses all other stale schemas.

    No ownership is acquired for cleanup until saved OIDs, marker, catalog and
    the independent operator identity hash are all verified.
    """
    if not NAMESPACE.fullmatch(namespace or '') or not namespace.startswith('canary_stagep_'):
        raise CanaryError('EXPLICIT_RESUME_NAMESPACE_REQUIRED')
    if not re.fullmatch(r'[a-f0-9]{64}',expected_hash or ''):
        raise CanaryError('EXPLICIT_RESUME_IDENTITY_REQUIRED')
    db.config.namespace=namespace
    db.open()
    with db.transaction() as conn:
        rows=conn.execute(select(s.runs).where(s.runs.c.run_id==run_id)).mappings().all()
        if len(rows)!=1:raise CanaryError('EXPLICIT_RESUME_RUN_REQUIRED')
        a=Approval.model_validate(rows[0]['approval'])
        if (a.ownership_marker!=namespace or a.database_identity!=db.config.approval.database_identity
                or a.operator_reference!=reference or a.environment!='disposable_test'
                or (not cleanup_only and (a.organization_id,a.bot_id)!=(db.config.approval.organization_id,db.config.approval.bot_id))):
            raise CanaryError('RESUME_APPROVAL_MISMATCH')
        key={k:rows[0][k] for k in s.RUN}
        control=conn.execute(select(s.recovery).where(where(s.recovery,key))).mappings().one()
        if control['identity_hash']!=expected_hash or digest(control['identity'])!=expected_hash:
            raise CanaryError('RESUME_IDENTITY_MISMATCH')
        saved=control['ownership']
        if digest(saved)!=control['identity']['ownership_hash']:
            raise CanaryError('RESUME_OWNERSHIP_MISMATCH')
        current=tuple(conn.execute(text('SELECT oid,nspowner FROM pg_namespace WHERE nspname=:name'),{'name':namespace}).one())
        if (list(current)!=saved['schema_identity'] or [list(r) for r in db.relations(conn)]!=saved['owned']
                or [list(r) for r in catalog_snapshot(conn,'') if r[1]==namespace]!=saved['owned_catalog']
                or [list(r) for r in db.before]!=saved['before']):
            raise CanaryError('RESUME_OWNERSHIP_MISMATCH')
        marker=conn.execute(select(s.marker)).mappings().all()
        if [dict(r) for r in marker]!=[dict(database_identity=a.database_identity,marker=namespace,environment=a.environment)]:
            raise CanaryError('CANARY_OWNERSHIP_REFUSED')
        if a.expires_at-a.created_at>RETENTION_SECONDS or control['retained_until']!=a.expires_at:
            raise CanaryError('RETENTION_BOUND')
        if not cleanup_only and now>=a.expires_at:raise CanaryError('RETAINED_RUN_EXPIRED')
        manifests=tuple(Manifest.model_validate(r) for r in conn.execute(select(s.manifests.c.payload)
            .where(where(s.manifests,key)).order_by(s.manifests.c.lane.desc())).scalars())
    db.config.approval=a
    db.schema_identity=current;db.marker_identity=tuple(saved['marker_identity'])
    db.owned=tuple(tuple(r) for r in saved['owned']);db.owned_catalog=tuple(tuple(r) for r in saved['owned_catalog'])
    db.created=True
    return manifests,control['identity']


class ExclusiveRun:
    """Session advisory lock survives transaction boundaries, releases on crash."""
    def __init__(self,db):self.db=db;self.conn=None
    def acquire(self):
        self.key=int(digest(self.db.config.namespace)[:15],16)
        self.conn=self.db.engine.connect()
        if not self.conn.execute(text('SELECT pg_try_advisory_lock(:key)'),{'key':self.key}).scalar_one():
            self.close();raise CanaryError('RETAINED_RUN_ALREADY_ACTIVE')
        self.conn.commit()
    def close(self):
        if self.conn is not None:
            try:self.conn.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':self.key});self.conn.commit()
            finally:self.conn.close();self.conn=None
