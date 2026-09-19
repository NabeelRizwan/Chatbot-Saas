"""Bounded batch transport only; same identity checks, transactions and f32 proof."""
from contextlib import nullcontext
from sqlalchemy import select,insert,update,tuple_
from database import canary_schema as s
from services.canary_contracts import CanaryError,Lane,canonicalize_vector_f32,canonical_vector_bytes,canonical_vector_digest
from services.canary_repository import document_values,manifest_values,source_values,where
from services.canary_representation import exact_input_hash,source_pin
from services.structural_chunking import digest
from scripts.canary_gemini_embeddings import Attestation
from scripts.canary_real_repository import RealCanaryRepository,receipt_payload


class RecoveryRepository(RealCanaryRepository):
    def __init__(self,*args,timing=None,**kwargs):
        self.timing=timing
        super().__init__(*args,**kwargs)

    def _bulk(self,conn,table,rows):
        category=('membership_span_staging' if table in (s.memberships,s.spans) else
                  'entry_atom_staging' if table in (s.entries,s.atoms,s.nodes) else
                  'work_ledger' if table in (s.work,s.legacy_work) else 'vector_persistence_readback')
        with self.timing.stage(category) if self.timing else nullcontext():
            for i in range(0,len(rows),100):
                # Explicit bounded multi-VALUES, not driver executemany per row.
                conn.execute(insert(table).values(rows[i:i+100]))

    def stage_structure(self,*args,**kwargs):
        with self.timing.stage('entry_atom_staging') if self.timing else nullcontext():
            return super().stage_structure(*args,**kwargs)

    def stage_legacy_work(self,*args,**kwargs):
        with self.timing.stage('work_ledger') if self.timing else nullcontext():
            return super().stage_legacy_work(*args,**kwargs)

    def register_fixture_source(self,batch,*,source_id,website_id=None):
        # Identical fixture identity/immutability checks to the base repository.
        pin=source_pin(batch,source_id=source_id,website_id=website_id);v=source_values(pin)
        if (v['organization_id'],v['bot_id'])!=(self.approval.organization_id,self.approval.bot_id):
            raise CanaryError('FOREIGN_FIXTURE_SOURCE')
        old=self.conn.execute(select(s.sources).where(where(s.sources,v))).mappings().one_or_none()
        if old is not None:
            if old['payload_hash']!=batch.canonical_hash():raise CanaryError('IMMUTABLE_SOURCE_CONFLICT')
            return pin
        self.conn.execute(insert(s.sources).values(**v,payload=batch.model_dump(mode='json'),payload_hash=batch.canonical_hash()))
        self._bulk(self.conn,s.nodes,[dict(**v,node_key=n.identity.node_key,payload=n.model_dump(mode='json'))
            for n in batch.evidence.source_graph.nodes])
        key={k:v[k] for k in ('organization_id','bot_id','document_id')}
        self.conn.execute(insert(s.lifecycle).values(**key,source_fingerprint=digest(v),status='ready',
            processing='completed',crawl_status='ready' if v['crawl_id'] else 'upload',
            active_crawl_id=v['crawl_id'],revision_state='validated',epoch=0))
        return pin

    def selection(self,table,manifest,items,column):
        return where(table,manifest_values(manifest)) & tuple_(table.c.document_id,table.c[column]).in_(
            [(p.scope.revision.source.document_id,k) for p,k,_ in items])

    def states(self,manifest,items):
        table,column=(s.work,'entry_id') if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy_work,'chunk_id')
        rows=self.conn.execute(select(table).where(self.selection(table,manifest,items,column))).mappings().all()
        states={(r['document_id'],r[column]):r for r in rows}
        if len(states)!=len(items):raise CanaryError('WORK_INVENTORY_MISMATCH')
        for pin,key,item in items:
            row=states[(pin.scope.revision.source.document_id,key)]
            if any(row[k]!=v for k,v in document_values(manifest,pin).items()):
                raise CanaryError('WORK_IDENTITY_MISMATCH')
            value=item.text if hasattr(item,'text') else item['text']
            if row['input_hash']!=exact_input_hash(value):raise CanaryError('WORK_INPUT_MISMATCH')
        return states

    def begin_attempt(self,manifest,items,*,now):
        self._staging(manifest,now)
        if any(r['state']!='pending' for r in self.states(manifest,items).values()):
            raise CanaryError('UNKNOWN_OR_ALREADY_CONSUMED_WORK')
        table,column=(s.work,'entry_id') if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy_work,'chunk_id')
        result=self.conn.execute(update(table).where(self.selection(table,manifest,items,column),table.c.state=='pending')
            .values(state='unknown',attempts=1))
        if result.rowcount!=len(items):raise CanaryError('WORK_CONCURRENT_CHANGE')

    def completed(self,manifest,items):
        self._require_profile(manifest)
        states=self.states(manifest,items)
        done=[v for v in items if states[(v[0].scope.revision.source.document_id,v[1])]['state']=='succeeded']
        if not done:return states,{}
        table,column=(s.vectors,'entry_id') if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy,'chunk_id')
        rows=self.conn.execute(select(table).where(self.selection(table,manifest,done,column))).mappings().all()
        stored={(r['document_id'],r[column]):r for r in rows};result={}
        for pin,key,item in done:
            ident=(pin.scope.revision.source.document_id,key);row=stored.get(ident)
            value=item.text if hasattr(item,'text') else item['text']
            if row is None or any(row[k]!=v for k,v in document_values(manifest,pin).items()) or not self._validate_stored_vector(manifest,row,value):
                raise CanaryError('PERSISTED_REAL_VECTOR_CORRUPTION')
            result[ident]=Attestation(self.approval.organization_id,self.approval.bot_id,row['input_hash'],
                manifest.profile.canonical_hash(),row['vector_hash'],canonicalize_vector_f32(row['embedding']),row['provider_receipt']['provider_attempt'])
        return states,result

    def persist(self,manifest,items,receipts,*,now,attempts=1):
        self._staging(manifest,now)
        if len(items)!=len(receipts) or not 1<=attempts<=3:raise CanaryError('REAL_BATCH_CARDINALITY')
        table,column,work=(s.vectors,'entry_id',s.work) if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy,'chunk_id',s.legacy_work)
        states=self.states(manifest,items);rows=[]
        for (pin,key,item),r in zip(items,receipts):
            value=item.text if hasattr(item,'text') else item['text']
            state=states[(pin.scope.revision.source.document_id,key)]
            if (state['state']!='unknown' or (r.organization_id,r.bot_id)!=(self.approval.organization_id,self.approval.bot_id)
                    or r.input_hash!=exact_input_hash(value) or r.profile_hash!=manifest.profile.canonical_hash()
                    or canonical_vector_digest(r.vector)!=r.vector_hash):raise CanaryError('REAL_RECEIPT_IDENTITY_MISMATCH')
            row=dict(**document_values(manifest,pin),**{column:key},input_hash=r.input_hash,
                embedding=list(r.vector),vector_hash=r.vector_hash,vector_attestation=manifest.profile.vector_attestation,
                embedding_source='REAL_PROVIDER',provider_receipt=receipt_payload(r,self.authorization))
            if manifest.lane==Lane.LEGACY_CONTROL:row.update(text=value,payload=item)
            rows.append(row)
        with self.conn.begin_nested():
            self._bulk(self.conn,table,rows)
            readback=self.conn.execute(select(table).where(self.selection(table,manifest,items,column))).mappings().all()
            stored={(r['document_id'],r[column]):r for r in readback}
            for (pin,key,item),r in zip(items,receipts):
                row=stored[(pin.scope.revision.source.document_id,key)]
                value=item.text if hasattr(item,'text') else item['text']
                if (not self._validate_stored_vector(manifest,row,value)
                        or canonicalize_vector_f32(row['embedding'])!=r.vector
                        or canonical_vector_bytes(row['embedding'])!=canonical_vector_bytes(r.vector)):
                    raise CanaryError('REAL_PGVECTOR_ROUNDTRIP_MISMATCH')
            count=self.conn.execute(update(work).where(self.selection(work,manifest,items,column),work.c.state=='unknown')
                .values(state='succeeded',attempts=max(attempts,max(r['attempts'] for r in states.values())))).rowcount
            if count!=len(items):raise CanaryError('WORK_CONCURRENT_CHANGE')
            self._staging(manifest,now)
