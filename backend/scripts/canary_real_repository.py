"""Explicit real-provider adapter for the owned development canary only.

Shares Phase O sealing, source epochs, SQL scope, ranking and read-release gates.
There are no application DB/provider imports and no caller-visible vector output.
"""
from collections import defaultdict
from dataclasses import dataclass
from sqlalchemy import insert, select, update

from database import canary_schema as s
from services.canary_contracts import CanaryError, Lane, canonicalize_vector_f32, canonical_vector_bytes, canonical_vector_digest
from services.canary_repository import CanaryRepository, document_values, manifest_values, where
from services.canary_representation import prepare_batch, source_pin, exact_input_hash
from services.structural_chunking import digest
from scripts.canary_gemini_embeddings import Attestation, configuration, real_profile


@dataclass(frozen=True)
class RealAuthorization:
    reference: str
    organization_id: int
    bot_id: int
    configuration_hash: str

    @classmethod
    def from_environment(cls, env, approval):
        if (env.get('CANARY_REAL_EMBEDDING_AUTHORIZED') != 'true'
                or not env.get('CANARY_APPROVAL_REFERENCE')
                or env['CANARY_APPROVAL_REFERENCE'] != approval.operator_reference
                or approval.environment != 'disposable_test'):
            raise CanaryError('REAL_PROVIDER_NOT_AUTHORIZED')
        return cls(approval.operator_reference, approval.organization_id, approval.bot_id,
                   real_profile().configuration_hash)

    def check(self, manifest):
        if ((manifest.approval.organization_id, manifest.approval.bot_id) != (self.organization_id,self.bot_id)
                or manifest.approval.operator_reference != self.reference
                or manifest.profile != real_profile()
                or manifest.embedding_configuration != configuration()
                or manifest.profile.configuration_hash != self.configuration_hash):
            raise CanaryError('REAL_PROVIDER_NOT_AUTHORIZED')


def receipt_payload(receipt, authorization):
    return dict(provenance='gemini-sdk-response-v1', organization_id=receipt.organization_id,
        bot_id=receipt.bot_id, input_hash=receipt.input_hash, profile_hash=receipt.profile_hash,
        vector_hash=receipt.vector_hash, provider_attempt=receipt.provider_attempt,
        operator_reference=authorization.reference, configuration=configuration())


def bulk(conn, table, rows):
    # Bounded INSERT-only transport; never alters representation or serving SQL.
    for i in range(0,len(rows),100):
        conn.execute(insert(table),rows[i:i+100])


class RealCanaryRepository(CanaryRepository):
    def __init__(self, connection, approval, *, authorization, **kwargs):
        self.authorization=authorization
        super().__init__(connection,approval,**kwargs)

    def _require_profile(self, manifest):
        self.authorization.check(manifest)

    def _validate_stored_vector(self, manifest, row, exact_text):
        self._require_profile(manifest)
        proof=row['provider_receipt']
        vector=canonicalize_vector_f32(row['embedding'])
        return (row['embedding_source']=='REAL_PROVIDER'
            and row['input_hash']==exact_input_hash(exact_text)
            and row['vector_hash']==canonical_vector_digest(vector)
            and row['vector_attestation']==manifest.profile.vector_attestation
            and proof==dict(provenance='gemini-sdk-response-v1',
                organization_id=manifest.approval.organization_id,bot_id=manifest.approval.bot_id,
                input_hash=row['input_hash'],profile_hash=manifest.profile.canonical_hash(),
                vector_hash=row['vector_hash'],provider_attempt=proof.get('provider_attempt'),
                operator_reference=self.authorization.reference,configuration=manifest.embedding_configuration)
            and type(proof.get('provider_attempt')) is int and proof['provider_attempt']>0)

    def stage_structure(self, manifest, batch, *, now):
        self._staging(manifest,now)
        if manifest.lane!=Lane.STRUCTURAL_CANARY:
            raise CanaryError('WRONG_LANE')
        batch,projections,routes,_=prepare_batch(batch)
        pin=next((p for p in manifest.documents if p.scope==batch.scope),None)
        if pin is None or pin!=source_pin(batch,source_id=pin.source_id,website_id=pin.website_id):
            raise CanaryError('BATCH_MANIFEST_MISMATCH')
        v=document_values(manifest,pin)
        with self.conn.begin_nested():
            bulk(self.conn,s.entries,[dict(**v,entry_id=e.entry_key,ordinal=e.ordinal,text=e.text,
                input_hash=exact_input_hash(e.text),payload=e.model_dump(mode='json')) for e in batch.entries])
            bulk(self.conn,s.work,[dict(**v,entry_id=e.entry_key,input_hash=exact_input_hash(e.text),
                state='pending',attempts=0) for e in batch.entries if e.entry_key in manifest.vector_entries(pin)])
            atom_rows=[]
            for payload in projections:
                a=payload['atom']; kind,key=routes[a['atom_key']]
                atom_rows.append(dict(**v,atom_id=a['atom_key'],bundle_id=a['bundle_key'],kind=a['kind'],
                    canonical_text=payload['canonical_text'],payload=payload,payload_hash=digest(payload),
                    route_kind=kind,route_entry=key if kind=='ENTRY' else None))
            bulk(self.conn,s.atoms,atom_rows)
            members=[]; spans=[]
            for e in batch.entries:
                grouped=defaultdict(list)
                for member in e.memberships:
                    grouped[member.atom_key].append(member.model_dump(mode='json'))
                members.extend(dict(**v,entry_id=e.entry_key,atom_id=k,payload=p) for k,p in grouped.items())
                for i,m in enumerate(e.mappings):
                    spans.append(dict(**v,entry_id=e.entry_key,atom_id=m.atom_key,ordinal=i,node_key=m.node.node_key,
                        node_start=m.node_slice.start,node_end=m.node_slice.end,entry_start=m.entry_slice.start,
                        entry_end=m.entry_slice.end,usage=m.usage,origin=m.origin_usage))
            bulk(self.conn,s.memberships,members); bulk(self.conn,s.spans,spans)
            self._staging(manifest,now)

    def stage_legacy_work(self,manifest,pin,chunks,*,now):
        self._staging(manifest,now)
        if (manifest.lane!=Lane.LEGACY_CONTROL or pin not in manifest.documents
                or tuple(c['id'] for c in chunks)!=pin.legacy_members or digest(chunks)!=pin.batch_hash):
            raise CanaryError('LEGACY_INVENTORY_MISMATCH')
        bulk(self.conn,s.legacy_work,[dict(**document_values(manifest,pin),chunk_id=c['id'],
            input_hash=exact_input_hash(c['text']),state='pending',attempts=0) for c in chunks])

    def work_state(self,manifest,pin,key):
        table,column=(s.work,'entry_id') if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy_work,'chunk_id')
        return self.conn.execute(select(table).where(where(table,document_values(manifest,pin)),
            table.c[column]==key)).mappings().one()

    def begin_attempt(self,manifest,items,*,now):
        self._staging(manifest,now)
        table,column=(s.work,'entry_id') if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy_work,'chunk_id')
        for pin,key,_ in items:
            state=self.work_state(manifest,pin,key)
            if state['state']!='pending':
                raise CanaryError('UNKNOWN_OR_ALREADY_CONSUMED_WORK')
            self.conn.execute(update(table).where(where(table,document_values(manifest,pin)),table.c[column]==key)
                .values(state='unknown',attempts=1))

    def persist(self,manifest,items,receipts,*,now,attempts=1):
        """Provider receipts stay in-process through INSERT and exact readback."""
        self._staging(manifest,now)
        if len(items)!=len(receipts) or not 1<=attempts<=3:
            raise CanaryError('REAL_BATCH_CARDINALITY')
        table,column,work=(s.vectors,'entry_id',s.work) if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy,'chunk_id',s.legacy_work)
        rows=[]
        for (pin,key,item),receipt in zip(items,receipts):
            text=item.text if manifest.lane==Lane.STRUCTURAL_CANARY else item['text']
            if (self.work_state(manifest,pin,key)['state']!='unknown'
                    or (receipt.organization_id,receipt.bot_id)!=(self.approval.organization_id,self.approval.bot_id)
                    or receipt.input_hash!=exact_input_hash(text) or receipt.profile_hash!=manifest.profile.canonical_hash()
                    or canonical_vector_digest(receipt.vector)!=receipt.vector_hash):
                raise CanaryError('REAL_RECEIPT_IDENTITY_MISMATCH')
            row=dict(**document_values(manifest,pin),**{column:key},input_hash=receipt.input_hash,
                embedding=list(receipt.vector),vector_hash=receipt.vector_hash,
                vector_attestation=manifest.profile.vector_attestation,embedding_source='REAL_PROVIDER',
                provider_receipt=receipt_payload(receipt,self.authorization))
            if manifest.lane==Lane.LEGACY_CONTROL:
                row.update(text=text,payload=item)
            rows.append(row)
        with self.conn.begin_nested():
            bulk(self.conn,table,rows)
            for (pin,key,item),receipt in zip(items,receipts):
                row=self.conn.execute(select(table).where(where(table,document_values(manifest,pin)),table.c[column]==key)).mappings().one()
                text=item.text if manifest.lane==Lane.STRUCTURAL_CANARY else item['text']
                if (not self._validate_stored_vector(manifest,row,text)
                        or canonicalize_vector_f32(row['embedding'])!=receipt.vector
                        or canonical_vector_bytes(row['embedding'])!=canonical_vector_bytes(receipt.vector)):
                    raise CanaryError('REAL_PGVECTOR_ROUNDTRIP_MISMATCH')
                self.conn.execute(update(work).where(where(work,document_values(manifest,pin)),work.c[column]==key)
                    .values(state='succeeded',attempts=attempts))
            self._staging(manifest,now)

    def persisted_receipt(self,manifest,pin,key,text):
        """Resume only completed exact-input/profile/provenance work; unknown holds."""
        self._require_profile(manifest)
        state=self.work_state(manifest,pin,key)
        if state['state']=='pending':
            return None
        if state['state']!='succeeded':
            raise CanaryError('UNKNOWN_PROVIDER_CONSUMPTION_HOLD')
        table,column=(s.vectors,'entry_id') if manifest.lane==Lane.STRUCTURAL_CANARY else (s.legacy,'chunk_id')
        row=self.conn.execute(select(table).where(where(table,document_values(manifest,pin)),table.c[column]==key)).mappings().one()
        if not self._validate_stored_vector(manifest,row,text):
            raise CanaryError('PERSISTED_REAL_VECTOR_CORRUPTION')
        return Attestation(self.approval.organization_id,self.approval.bot_id,row['input_hash'],
            manifest.profile.canonical_hash(),row['vector_hash'],canonicalize_vector_f32(row['embedding']),
            row['provider_receipt']['provider_attempt'])

    def _validate_generation(self,manifest):
        super()._validate_generation(manifest)
        if manifest.lane==Lane.LEGACY_CONTROL:
            for pin in manifest.documents:
                work=self._rows(s.legacy_work,manifest,pin)
                rows={r['chunk_id']:r for r in self._rows(s.legacy,manifest,pin)}
                if ({r['chunk_id'] for r in work}!=set(pin.legacy_members)
                        or any(r['state']!='succeeded' or r['input_hash']!=rows[r['chunk_id']]['input_hash'] for r in work)):
                    raise CanaryError('INCOMPLETE_LEGACY_WORK')
