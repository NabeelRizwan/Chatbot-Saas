"""Isolated relational canary repository. Caller owns transaction/connection.

Never imports application connection/models or reads DSNs/environment variables.
SQLite validates repository/constraints only, not PostgreSQL FTS/pgvector behavior.
"""
from collections import defaultdict
import math
from time import time

from sqlalchemy import select, and_, insert, update, delete, func, text, bindparam, Float, literal_column, true
from services.canary_contracts import (Approval, Manifest, CanaryError, State, TRANSITIONS,
    Lane, route, validate_vector, synthetic_vector)
from services.canary_representation import prepare_batch, source_pin, exact_input_hash, evidence_view
from services.structural_chunking import digest
from services import structural_retrieval_entries_v2 as m
from services.canary_retrieval import Hit, LexicalResult
from database import canary_schema as s


def source_values(pin):
    v = pin.scope.revision.source
    return dict(organization_id=v.organization_id, bot_id=v.bot_id, document_id=v.document_id,
        document_version_id=v.document_version_id, source_version=v.source_version,
        source_hash=v.source_sha256, website_id=pin.website_id or 0, crawl_id=pin.scope.crawl_id or 0,
        crawl_version=pin.scope.crawl_version or 0, revision=pin.scope.revision.structure_revision_id)


def run_values(manifest):
    a = manifest.approval
    return dict(organization_id=a.organization_id, bot_id=a.bot_id, run_id=manifest.run_id)


def manifest_values(manifest):
    return dict(**run_values(manifest), lane=manifest.lane.value, generation=manifest.generation,
        manifest_hash=manifest.canonical_hash(), profile_hash=manifest.profile.canonical_hash(),
        policy_hash=manifest.policy.canonical_hash())


def document_values(manifest, pin):
    return manifest_values(manifest) | source_values(pin)


def where(table, values):
    return and_(*(table.c[k] == v for k, v in values.items()))


def join_keys(left, right, keys):
    return and_(*(left.c[k] == right.c[k] for k in keys))


class CanaryRepository:
    def __init__(self, connection, approval: Approval, *, clock=time):
        self.conn, self.approval, self.clock = connection, approval, clock
        if connection.dialect.name not in ('sqlite', 'postgresql'):
            raise CanaryError('UNSUPPORTED_DISPOSABLE_DIALECT')
        row = connection.execute(select(s.marker).where(s.marker.c.database_identity == approval.database_identity)).mappings().one_or_none()
        if row is None or row['marker'] != approval.ownership_marker or row['environment'] != approval.environment:
            raise CanaryError('DATABASE_OWNERSHIP_REFUSED')

    def _run(self, manifest, *, lock=False):
        manifest = Manifest.model_validate_json(manifest.canonical_json())
        manifest.profile.require_stage_a()
        if manifest.approval != self.approval:
            raise CanaryError('OPERATOR_APPROVAL_MISMATCH')
        statement = select(s.runs).where(where(s.runs, run_values(manifest)))
        if lock:
            statement = statement.with_for_update()
        row = self.conn.execute(statement).mappings().one_or_none()
        if row is None or row['approval_hash'] != self.approval.canonical_hash():
            raise CanaryError('UNKNOWN_RUN')
        return row

    def _fresh(self, manifest, now):
        if max(now, int(self.clock())) >= manifest.approval.expires_at:
            raise CanaryError('RUN_EXPIRED')
        epochs = []
        current = {r['document_id']:r for r in self.conn.execute(select(s.lifecycle).where(
            s.lifecycle.c.organization_id==manifest.approval.organization_id,
            s.lifecycle.c.bot_id==manifest.approval.bot_id,
            s.lifecycle.c.document_id.in_([p.scope.revision.source.document_id for p in manifest.documents]))).mappings()}
        for pin in manifest.documents:
            values = source_values(pin)
            row = current.get(values['document_id'])
            if (row is None or row['source_fingerprint'] != digest(values) or
                row['status'] != 'ready' or row['processing'] != 'completed' or
                row['revision_state'] != 'validated' or row['active_crawl_id'] != values['crawl_id'] or
                row['crawl_status'] != ('ready' if values['crawl_id'] else 'upload')):
                raise CanaryError('STALE_OR_INELIGIBLE_SOURCE')
            epochs.append((values['document_id'], row['epoch'], row['source_fingerprint']))
        return tuple(epochs)

    def register_fixture_source(self, batch, *, source_id, website_id=None):
        """Owned immutable snapshot import; never writes shared documents/revisions."""
        pin = source_pin(batch, source_id=source_id, website_id=website_id)
        v = source_values(pin)
        if (v['organization_id'], v['bot_id']) != (self.approval.organization_id, self.approval.bot_id):
            raise CanaryError('FOREIGN_FIXTURE_SOURCE')
        old = self.conn.execute(select(s.sources).where(where(s.sources, v))).mappings().one_or_none()
        if old is not None:
            if old['payload_hash'] != batch.canonical_hash():
                raise CanaryError('IMMUTABLE_SOURCE_CONFLICT')
            return pin
        self.conn.execute(insert(s.sources).values(**v, payload=batch.model_dump(mode='json'), payload_hash=batch.canonical_hash()))
        self.conn.execute(insert(s.nodes),[dict(**v,node_key=n.identity.node_key,payload=n.model_dump(mode='json'))
                                          for n in batch.evidence.source_graph.nodes])
        key = {k: v[k] for k in ('organization_id','bot_id','document_id')}
        self.conn.execute(insert(s.lifecycle).values(**key, source_fingerprint=digest(v), status='ready',
            processing='completed', crawl_status='ready' if v['crawl_id'] else 'upload',
            active_crawl_id=v['crawl_id'], revision_state='validated', epoch=0))
        return pin

    def create(self, manifest, *, now):
        manifest = Manifest.model_validate_json(manifest.canonical_json())
        manifest.profile.require_stage_a()
        if manifest.approval != self.approval or manifest.implementation_hash != m._implementation_hash():
            raise CanaryError('MANIFEST_APPROVAL_OR_IMPLEMENTATION_MISMATCH')
        self._fresh(manifest, now)
        old = self.conn.execute(select(s.runs).where(where(s.runs, run_values(manifest))).with_for_update()).mappings().one_or_none()
        if old is None:
            self.conn.execute(insert(s.runs).values(**run_values(manifest), approval=self.approval.model_dump(mode='json'),
                approval_hash=self.approval.canonical_hash(), database_identity=self.approval.database_identity,
                state=State.OFF.value, epoch=0, expires_at=self.approval.expires_at))
            self.transition(manifest, State.EMBEDDING_STAGING, now=now)
        elif old['state'] != State.EMBEDDING_STAGING.value or old['approval_hash'] != self.approval.canonical_hash():
            raise CanaryError('RUN_NOT_STAGING')
        self.conn.execute(insert(s.manifests).values(**manifest_values(manifest), payload=manifest.model_dump(mode='json')))
        for pin in manifest.documents:
            self.conn.execute(insert(s.documents).values(**document_values(manifest,pin), pin_hash=pin.canonical_hash(),
                source_fingerprint=digest(source_values(pin)), source_id=pin.source_id, payload=pin.model_dump(mode='json')))

    def transition(self, manifest, target: State, *, now):
        row = self._run(manifest, lock=True)
        current = State(row['state'])
        if target not in TRANSITIONS.get(current, ()):
            raise CanaryError('INVALID_TRANSITION')
        if target in (State.EMBEDDING_STAGING, State.INDEX_READY, State.CANARY_READ, State.COMPARATIVE_EVAL):
            self._fresh(manifest, now)
        if target == State.INDEX_READY and current == State.EMBEDDING_STAGING:
            self._validate_run(manifest)
        result = self.conn.execute(update(s.runs).where(where(s.runs, run_values(manifest)),
            s.runs.c.epoch == row['epoch']).values(state=target.value, epoch=row['epoch']+1))
        if result.rowcount != 1:
            raise CanaryError('RUN_CONCURRENT_CHANGE')

    def _staging(self, manifest, now):
        if self._run(manifest, lock=True)['state'] != State.EMBEDDING_STAGING.value:
            raise CanaryError('RUN_NOT_STAGING')
        self._fresh(manifest, now)

    def stage(self, manifest, batch, *, now, supplied_vectors=None):
        self._staging(manifest, now)
        if manifest.lane != Lane.STRUCTURAL_CANARY:
            raise CanaryError('WRONG_LANE')
        batch, projections, routes, maps = prepare_batch(batch)
        pin = next((p for p in manifest.documents if p.scope == batch.scope), None)
        if pin is None or pin != source_pin(batch, source_id=pin.source_id, website_id=pin.website_id):
            raise CanaryError('BATCH_MANIFEST_MISMATCH')
        vectors = supplied_vectors if supplied_vectors is not None else {e.entry_key:synthetic_vector(e.text) for e in batch.entries}
        if set(vectors) != set(pin.entries):
            raise CanaryError('VECTOR_IDENTITY_SET_MISMATCH')
        vectors = {key:validate_vector(value) for key,value in vectors.items()}
        # Input attestation prevents vectors for another entry from being relabeled.
        if any(vectors[e.entry_key] != synthetic_vector(e.text) for e in batch.entries):
            raise CanaryError('VECTOR_INPUT_PROVENANCE_MISMATCH')
        v = document_values(manifest, pin)
        with self.conn.begin_nested():
            for e in batch.entries:
                ih = exact_input_hash(e.text)
                self.conn.execute(insert(s.entries).values(**v, entry_id=e.entry_key, ordinal=e.ordinal,
                    text=e.text, input_hash=ih, payload=e.model_dump(mode='json')))
                self.conn.execute(insert(s.vectors).values(**v, entry_id=e.entry_key, input_hash=ih,
                    embedding=list(vectors[e.entry_key]), vector_hash=digest(vectors[e.entry_key]), embedding_source='SYNTHETIC_TEST'))
                self.conn.execute(insert(s.work).values(**v, entry_id=e.entry_key, input_hash=ih, state='succeeded', attempts=1))
            for payload in projections:
                a = payload['atom']; kind,key = routes[a['atom_key']]
                self.conn.execute(insert(s.atoms).values(**v, atom_id=a['atom_key'], bundle_id=a['bundle_key'],
                    kind=a['kind'], canonical_text=payload['canonical_text'], payload=payload, payload_hash=digest(payload),
                    route_kind=kind, route_entry=key if kind=='ENTRY' else None))
            for e in batch.entries:
                grouped = defaultdict(list)
                for member in e.memberships:
                    grouped[member.atom_key].append(member.model_dump(mode='json'))
                for key,payload in grouped.items():
                    self.conn.execute(insert(s.memberships).values(**v, entry_id=e.entry_key, atom_id=key, payload=payload))
                for i,span in enumerate(e.mappings):
                    self.conn.execute(insert(s.spans).values(**v, entry_id=e.entry_key, atom_id=span.atom_key,
                        ordinal=i, node_key=span.node.node_key, node_start=span.node_slice.start,node_end=span.node_slice.end,
                        entry_start=span.entry_slice.start,entry_end=span.entry_slice.end,usage=span.usage,origin=span.origin_usage))
            self._staging(manifest, now)  # cancellation/expiry wins publication

    def stage_legacy(self, manifest, pin, chunks, *, now):
        self._staging(manifest, now)
        if manifest.lane != Lane.LEGACY_CONTROL or pin not in manifest.documents or tuple(c['id'] for c in chunks) != pin.legacy_members:
            raise CanaryError('LEGACY_INVENTORY_MISMATCH')
        if digest(chunks) != pin.batch_hash:
            raise CanaryError('LEGACY_PAYLOAD_MISMATCH')
        with self.conn.begin_nested():
            for c in chunks:
                vector = synthetic_vector(c['text'])
                self.conn.execute(insert(s.legacy).values(**document_values(manifest,pin), chunk_id=c['id'],text=c['text'],
                    input_hash=exact_input_hash(c['text']),payload=c, embedding=list(vector),vector_hash=digest(vector),
                    embedding_source='SYNTHETIC_TEST'))

    def _rows(self, table, manifest, pin):
        return list(self.conn.execute(select(table).where(where(table,document_values(manifest,pin)))).mappings())

    def _validate_run(self, manifest):
        manifests = self.conn.execute(select(s.manifests.c.payload).where(where(s.manifests,run_values(manifest)))).scalars().all()
        if not manifests:
            raise CanaryError('EMPTY_RUN')
        for raw in manifests:
            mft = Manifest.model_validate(raw)
            for pin in mft.documents:
                if mft.lane == Lane.LEGACY_CONTROL:
                    rows = sorted(self._rows(s.legacy,mft,pin),key=lambda r:r['chunk_id'])
                    if tuple(r['chunk_id'] for r in rows) != pin.legacy_members or digest([r['payload'] for r in rows]) != pin.batch_hash:
                        raise CanaryError('INCOMPLETE_LEGACY_BUILD')
                    for r in rows:
                        if tuple(r['embedding']) != synthetic_vector(r['text']) or r['input_hash'] != exact_input_hash(r['text']):
                            raise CanaryError('INVALID_LEGACY_VECTOR')
                    continue
                original = self.conn.execute(select(s.sources.c.payload).where(where(s.sources,source_values(pin)))).scalar_one()
                batch = m.RetrievalEntryBatch.model_validate(original)
                batch, projections, routes, maps = prepare_batch(batch)
                if source_pin(batch,source_id=pin.source_id,website_id=pin.website_id) != pin:
                    raise CanaryError('PIN_INTEGRITY_FAILURE')
                es = {r['entry_id']:r for r in self._rows(s.entries,mft,pin)}
                vs = {r['entry_id']:r for r in self._rows(s.vectors,mft,pin)}
                ats = {r['atom_id']:r for r in self._rows(s.atoms,mft,pin)}
                ws = {r['entry_id']:r for r in self._rows(s.work,mft,pin)}
                if set(es)!=set(pin.entries) or set(vs)!=set(pin.entries) or set(ats)!=set(pin.atoms) or set(ws)!=set(pin.entries):
                    raise CanaryError('INCOMPLETE_BUILD')
                for e in batch.entries:
                    r,v=es[e.entry_key],vs[e.entry_key]
                    if (r['payload']!=e.model_dump(mode='json') or r['text']!=e.text or
                        r['input_hash']!=exact_input_hash(e.text) or tuple(validate_vector(v['embedding']))!=synthetic_vector(e.text) or
                        v['vector_hash']!=digest(tuple(v['embedding'])) or ws[e.entry_key]['state']!='succeeded'):
                        raise CanaryError('ENTRY_VECTOR_CORRUPTION')
                for payload in projections:
                    key=payload['atom']['atom_key']; r=ats[key]; kind,target=routes[key]
                    if (r['payload']!=payload or r['payload_hash']!=digest(payload) or r['canonical_text']!=payload['canonical_text'] or
                        r['route_kind']!=kind or r['route_entry']!=(target if kind=='ENTRY' else None)):
                        raise CanaryError('ATOM_PROJECTION_CORRUPTION')
                actual_members = self._rows(s.memberships,mft,pin)
                expected_members = defaultdict(list)
                for e in batch.entries:
                    for member in e.memberships:
                        expected_members[(e.entry_key,member.atom_key)].append(member.model_dump(mode='json'))
                if {(r['entry_id'],r['atom_id']):r['payload'] for r in actual_members}!=dict(expected_members):
                    raise CanaryError('MEMBERSHIP_CORRUPTION')
                expected_spans=[]
                for e in batch.entries:
                    for i,v in enumerate(e.mappings):
                        expected_spans.append((e.entry_key,v.atom_key,i,v.node.node_key,v.node_slice.start,v.node_slice.end,
                                               v.entry_slice.start,v.entry_slice.end,v.usage,v.origin_usage))
                columns=('entry_id','atom_id','ordinal','node_key','node_start','node_end','entry_start','entry_end','usage','origin')
                if sorted(tuple(r[k] for k in columns) for r in self._rows(s.spans,mft,pin))!=sorted(expected_spans):
                    raise CanaryError('SPAN_CORRUPTION')

    def read_gate(self, manifest, hard, *, now, expected_epoch=None):
        row = self._run(manifest)
        if row['state'] not in (State.CANARY_READ.value,State.COMPARATIVE_EVAL.value):
            raise CanaryError('NO_READ_LEASE')
        epochs = self._fresh(manifest,now)
        token = digest((row['epoch'], epochs))
        if expected_epoch is not None and token != expected_epoch:
            raise CanaryError('READ_LEASE_CHANGED')
        manifest.effective(hard)
        raw=self.conn.execute(select(s.manifests.c.payload).where(where(s.manifests,manifest_values(manifest)))).scalar_one_or_none()
        if raw != manifest.model_dump(mode='json'):
            raise CanaryError('MANIFEST_INTEGRITY_FAILURE')
        return token

    def eligible_sql(self, manifest, hard):
        ids=manifest.effective(hard)
        d,l=s.documents,s.lifecycle
        stmt=select(*d.c).select_from(d.join(l,join_keys(d,l,('organization_id','bot_id','document_id')))
            .join(s.runs,join_keys(d,s.runs,s.RUN))).where(
            where(d,manifest_values(manifest)),d.c.document_id.in_(ids),d.c.source_fingerprint==l.c.source_fingerprint,
            s.runs.c.state.in_(('CANARY_READ','COMPARATIVE_EVAL')),
            s.runs.c.expires_at > int(self.clock()),s.runs.c.approval_hash==manifest.approval.canonical_hash(),
            s.runs.c.database_identity==self.approval.database_identity,
            l.c.status=='ready',l.c.processing=='completed',l.c.revision_state=='validated',
            l.c.active_crawl_id==d.c.crawl_id,
            ((d.c.crawl_id==0)&(l.c.crawl_status=='upload'))|((d.c.crawl_id>0)&(l.c.crawl_status=='ready')))
        return stmt.cte('eligible_sources').prefix_with('MATERIALIZED',dialect='postgresql')

    def dense_statement(self,manifest,hard):
        eligible=self.eligible_sql(manifest,hard)
        table=s.vectors if manifest.lane==Lane.STRUCTURAL_CANARY else s.legacy
        key='entry_id' if manifest.lane==Lane.STRUCTURAL_CANARY else 'chunk_id'
        candidates=select(*table.c).select_from(table.join(eligible,join_keys(table,eligible,s.DOC))).cte('eligible_vectors').prefix_with('MATERIALIZED',dialect='postgresql')
        distance=candidates.c.embedding.op('<=>',return_type=Float)(text('CAST(:query_vector AS vector(768))'))
        return select(candidates,distance.label('distance')).order_by(distance,candidates.c.document_id,candidates.c[key]).limit(manifest.policy.candidate_limit)

    def fts_statement(self,manifest,hard):
        eligible=self.eligible_sql(manifest,hard)
        table=s.atoms if manifest.lane==Lane.STRUCTURAL_CANARY else s.legacy
        key='atom_id' if manifest.lane==Lane.STRUCTURAL_CANARY else 'chunk_id'
        field='canonical_text' if manifest.lane==Lane.STRUCTURAL_CANARY else 'text'
        q=select(func.websearch_to_tsquery(text("'english'::regconfig"),bindparam('query_text')).label('value')).cte('q').prefix_with('MATERIALIZED',dialect='postgresql')
        vector=func.to_tsvector(text("'english'::regconfig"),func.coalesce(table.c[field],literal_column("''")))
        score=func.ts_rank_cd(vector,q.c.value)
        candidates=select(table,score.label('score')).select_from(table.join(eligible,join_keys(table,eligible,s.DOC))).select_from(q).where(
            func.numnode(q.c.value)>0,func.querytree(q.c.value).not_in(('', 'T')),vector.op('@@')(q.c.value)
            ).order_by(score.desc(),table.c.document_id,table.c[key]).limit(manifest.policy.candidate_limit).cte('fts_candidates')
        return select(candidates,func.numnode(q.c.value).label('query_nodes'),func.querytree(q.c.value).label('indexable_tree'))\
            .select_from(q.outerjoin(candidates,true())).order_by(candidates.c.score.desc(),candidates.c.document_id,candidates.c[key])

    def _pin(self,manifest,row):
        return next(p for p in manifest.documents if source_values(p)=={k:row[k] for k in s.SRC})

    def dense(self,manifest,hard,values,*,now):
        self.read_gate(manifest,hard,now=now)
        vector=validate_vector(values)
        if self.conn.dialect.name=='postgresql':
            rows=self.conn.execute(self.dense_statement(manifest,hard),{'query_vector':'['+','.join(map(str,vector))+']'}).mappings().all()
        else:
            # Explicit SQLite mechanical emulator; not a pgvector acceptance result.
            table=s.vectors if manifest.lane==Lane.STRUCTURAL_CANARY else s.legacy
            eligible=self.eligible_sql(manifest,hard)
            rows=[dict(r) for r in self.conn.execute(select(table).select_from(table.join(eligible,join_keys(table,eligible,s.DOC)))).mappings()]
            for row in rows:
                v=validate_vector(row['embedding'])
                row['distance']=1-sum(a*b for a,b in zip(vector,v))/(math.sqrt(sum(a*a for a in vector))*math.sqrt(sum(a*a for a in v)))
            key='entry_id' if manifest.lane==Lane.STRUCTURAL_CANARY else 'chunk_id'
            rows=sorted(rows,key=lambda r:(r['distance'],r['document_id'],r[key]))[:manifest.policy.candidate_limit]
        kind='ENTRY' if manifest.lane==Lane.STRUCTURAL_CANARY else 'LEGACY_CHUNK'
        key='entry_id' if kind=='ENTRY' else 'chunk_id'
        return tuple(Hit(route(manifest,self._pin(manifest,r),kind,r[key]),str(r[key]),i,r['distance']) for i,r in enumerate(rows,1))

    def fts(self,manifest,hard,query,*,now):
        self.read_gate(manifest,hard,now=now)
        if len(query)>8192:
            raise CanaryError('QUERY_BOUND')
        if self.conn.dialect.name!='postgresql':
            raise RuntimeError('POSTGRESQL_FTS_VALIDATION_HOLD')
        rows=self.conn.execute(self.fts_statement(manifest,hard),{'query_text':query}).mappings().all()
        if not rows or not rows[0]['query_nodes']:
            return LexicalResult((),'empty')
        if rows[0]['indexable_tree'] in ('','T'):
            return LexicalResult((),'non_indexable')
        hits=[]
        for i,row in enumerate((r for r in rows if r['document_id'] is not None),1):
            pin=self._pin(manifest,row)
            if manifest.lane==Lane.LEGACY_CONTROL:
                kind,key,atom='LEGACY_CHUNK',row['chunk_id'],str(row['chunk_id'])
            else:
                kind=row['route_kind']; key=row['route_entry'] or row['atom_id']; atom=row['atom_id']
            hits.append(Hit(route(manifest,pin,kind,key),atom,i,row['score']))
        return LexicalResult(tuple(hits),'indexable')

    def _route_pin(self,manifest,hard,r,now):
        self.read_gate(manifest,hard,now=now)
        pin=next((p for p in manifest.documents if p.scope==r.source),None)
        if pin is None or r!=route(manifest,pin,r.kind,r.key) or pin.scope.revision.source.document_id not in manifest.effective(hard):
            raise CanaryError('FOREIGN_MATERIALIZATION')
        return pin

    def children(self,manifest,hard,r,*,now):
        pin=self._route_pin(manifest,hard,r,now)
        if r.kind=='LEGACY_CHUNK':
            if int(r.key) not in pin.legacy_members: raise CanaryError('FOREIGN_LEGACY_MEMBER')
            return (r.key,)
        if r.kind=='ATOM_ONLY':
            if r.key not in pin.atoms: raise CanaryError('FOREIGN_ATOM')
            return (r.key,)
        if r.key not in pin.entries: raise CanaryError('FOREIGN_ENTRY')
        rows=self.conn.execute(select(s.memberships.c.atom_id).where(where(s.memberships,document_values(manifest,pin)),
            s.memberships.c.entry_id==r.key).order_by(s.memberships.c.atom_id).limit(33)).scalars().all()
        if not rows or len(rows)>32: raise CanaryError('CORRUPT_ENTRY_FANOUT')
        return tuple(rows)

    def evidence(self,manifest,hard,r,key,*,now):
        pin=self._route_pin(manifest,hard,r,now)
        if r.kind=='LEGACY_CHUNK':
            if str(key)!=r.key or int(key) not in pin.legacy_members: raise CanaryError('FOREIGN_LEGACY_MEMBER')
            return self.conn.execute(select(s.legacy.c.payload).where(where(s.legacy,document_values(manifest,pin)),s.legacy.c.chunk_id==int(key))).scalar_one()
        if key not in pin.atoms: raise CanaryError('FOREIGN_ATOM')
        row=self.conn.execute(select(s.atoms).where(where(s.atoms,document_values(manifest,pin)),s.atoms.c.atom_id==key)).mappings().one()
        if digest(row['payload'])!=row['payload_hash']: raise CanaryError('EVIDENCE_PAYLOAD_CORRUPTION')
        return evidence_view(row['payload'])

    def counts(self,manifest):
        return {t.name:self.conn.execute(select(func.count()).select_from(t).where(where(t,run_values(manifest)))).scalar_one() for t in s.RUN_TABLES}

    def delete_run(self,manifest):
        row=self._run(manifest,lock=True)
        if row['state'] not in ('OFF','FAILED','CANCELLED','EXPIRED','STALE'):
            raise CanaryError('DELETE_READABLE_RUN_REFUSED')
        before=self.counts(manifest)
        self.conn.execute(delete(s.runs).where(where(s.runs,run_values(manifest))))
        if any(self.counts(manifest).values()): raise CanaryError('CLEANUP_INCOMPLETE')
        return before
