"""One-process authorized Phase P runner. Embeddings never cross stdout/files.

Uses only the supplied disposable target and frozen local source copies. It has
no application settings, serving DB, generation, crawler or answer-model path.
P2 is reached only after every P1 gate succeeds. An exception stops the run.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import sys
from time import perf_counter, time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func, text, update
from database import canary_schema as s
from services.canary_contracts import CanaryError, Manifest, Policy, Lane, State
from services.canary_repository import source_values, where, manifest_values
from services.canary_retrieval import run_query
from services.canary_representation import exact_input_hash
from services.retrieval_contracts import HardKnowledgeScope
from services.structural_chunking import count_tokens, digest
from scripts.canary_gemini_embeddings import GeminiCanary, bounded_batches, configuration, real_profile
from scripts.canary_real_repository import RealCanaryRepository, RealAuthorization
from scripts.canary_postgres_validation import DisposableCanary, settings, safe_failure
from scripts.canary_schema_migration import upgrade
from scripts.canary_semantic_inventory import freeze
from scripts.canary_real_evaluation import snapshots, score_case, safe_trace
from scripts.canary_bounded_output import bounded_json, emit, vector_summary


def require(value, code):
    if not value: raise CanaryError(code)


def item_text(item):
    value = item[2]
    return value.text if hasattr(value, 'text') else value['text']


def handoff(provider, repository, manifest, items, *, now, retries=0):
    """Testable process-internal response -> persistence -> bounded summary.

    Work must already be committed UNKNOWN before the provider request. No
    serialization of the receipts occurs at this or any outer call boundary.
    """
    before = len(provider.attempts)
    receipts = provider.embed([item_text(v) for v in items], purpose='evidence', retries=retries)
    repository.persist(manifest, items, receipts, now=now,
        attempts=max(1, len(provider.attempts)-before))
    return {'result':'PERSISTED', 'items':[vector_summary(r) for r in receipts]}


class Runner:
    def __init__(self, root, env):
        self.root, self.env = root, env
        self.plan = json.loads((root/'backend/fixtures/canary_real_embedding_v1/plan.json').read_text())
        self.db = self.provider = None
        self.result = {'decision':'C', 'stage':'OFFLINE_FREEZE', 'p1':'NOT_RUN', 'p2':'NOT_RUN'}
        self.receipt_index = {}  # input hash -> persisted scope/key/text locator, not coordinates
        self.reused_persisted = 0
        self.artifacts = None

    def save(self, name, record):
        encoded = bounded_json(record)
        if self.artifacts is not None:
            (self.artifacts/(name+'.json')).write_text(encoded+'\n', encoding='utf-8')
        return encoded

    def progress(self, stage, **values):
        self.result['stage'] = stage
        emit(dict(stage=stage, **values))

    @contextmanager
    def repository(self):
        with self.db.transaction() as conn:
            yield RealCanaryRepository(conn, self.config.approval, authorization=self.authorization)

    def manifest(self, pins, *, run, lane=Lane.STRUCTURAL_CANARY, selection=None):
        return Manifest(run_id=run, lane=lane, generation='real-baseline-v1',
            approval=self.config.approval, profile=real_profile(), policy=Policy(),
            documents=tuple(sorted(pins, key=lambda p:p.scope.revision.source.document_id)),
            implementation_hash=self.frozen['implementation_hash'],
            query_contract_hash=self.snapshot_hash, evaluation_hash=self.plan['evaluation_sha256'],
            embedding_configuration=configuration(), vector_entry_selection=selection)

    def hard(self, manifest):
        return HardKnowledgeScope(organization_id=self.config.approval.organization_id,
            bot_id=self.config.approval.bot_id, embedding_profile=manifest.profile.hard_identity(),
            authorized_document_ids=tuple(p.scope.revision.source.document_id for p in manifest.documents),
            active_document_versions=tuple((p.scope.revision.source.document_id,
                p.scope.revision.source.source_version,p.scope.crawl_id) for p in manifest.documents),
            corpus_fingerprint=self.frozen['ordered_batch_digest'])

    def freeze_inputs(self):
        require(self.env.get('CANARY_REAL_EMBEDDING_AUTHORIZED')=='true', 'REAL_PROVIDER_NOT_AUTHORIZED')
        self.batches, self.frozen = freeze(self.root)
        require(self.frozen['counts']==self.plan['counts'] and
            self.frozen['ordered_batch_digest']==self.plan['m_digest'], 'FROZEN_PLAN_MISMATCH')
        self.common = snapshots(self.root, self.plan)
        self.snapshot_hash = digest([v[0]['snapshot_hash'] for v in self.common])
        folder = self.root/'.codex_real_corpus_v1'
        source = json.loads((folder/'SOURCE_PRODUCTION_SNAPSHOT.json').read_text(encoding='utf-8'))
        mapping = json.loads((folder/'SOURCE_TO_DEVELOPMENT_ID_MAPPING.json').read_text(encoding='utf-8'))
        self.websites = {d['id']:mapping['corpus']['websites'].get(str(d['website_id']))
                         for d in source['documents']}
        # Old snapshot vectors lack request-config/input-byte/receipt attestation.
        # Rebuild only the frozen text into an isolated LEGACY_CONTROL generation.
        self.legacy_chunks = {doc:[] for doc in self.batches}
        for c in sorted(source['chunks'],key=lambda c:c['id']):
            require(c['status']=='ready' and c['document_id'] in self.batches, 'LEGACY_INVENTORY_MISMATCH')
            self.legacy_chunks[c['document_id']].append(dict(id=c['id'],text=c['content']))
        del source
        n=sum(map(len,self.legacy_chunks.values()))
        tokens=sum(count_tokens(c['text']) for rows in self.legacy_chunks.values() for c in rows)
        require(n==1092 and n+1030<=2500 and tokens+217263<=500000, 'PAIRED_BUILD_BUDGET_HOLD')
        # Preflight every batch BEFORE spending provider quota (including control).
        list(bounded_batches(c['text'] for rows in self.legacy_chunks.values() for c in rows))
        self.result['frozen'] = self.frozen['counts'] | dict(m_digest=self.plan['m_digest'],
            snapshots_digest=self.snapshot_hash, legacy_inputs=n, legacy_local_tokens=tokens,
            legacy_provenance='UNPROVEN_REQUEST_CONFIGURATION_PAIRED_REBUILD_AUTHORIZED')

    def setup(self):
        self.freeze_inputs()
        first=next(iter(self.batches.values())).scope.revision.source
        self.config=settings(self.env,stage='p',organization_id=first.organization_id,bot_id=first.bot_id)
        self.authorization=RealAuthorization.from_environment(self.env,self.config.approval)
        self.db=DisposableCanary(self.config)
        self.artifacts=self.root/'.codex_phase4p'/self.config.namespace
        self.artifacts.mkdir(parents=True,exist_ok=False)
        self.result['run_hash']=digest(self.config.namespace)
        self.progress('POSTGRES_PREFLIGHT')
        self.result['postgres']=self.db.open()
        self.db.bootstrap()
        with self.db.transaction() as conn:
            upgrade(conn,self.config.approval)
            self.db.record_owned(conn)
        # Read exactly one approved dev credential; never load application settings
        # or assign any DB env var from this file.
        from dotenv import dotenv_values
        local=dotenv_values(self.root/'backend/.env',interpolate=False)
        key=local.get('GEMINI_API_KEY');local.clear()
        self.provider=GeminiCanary(key,organization_id=first.organization_id,
            bot_id=first.bot_id,approved=True)
        key=None

    def store_batch(self, manifest, items, *, retries):
        with self.repository() as repo:
            pending=[]
            for pin,key,item in items:
                prior=repo.persisted_receipt(manifest,pin,key,item_text((pin,key,item)))
                if prior is not None:
                    self.reused_persisted+=1
                else: pending.append((pin,key,item))
        if not pending:return
        # UNKNOWN committed before HTTP: crash/restart never implies permission
        # to re-spend on an unconfirmed response. Failure leaves no readable pool.
        with self.repository() as repo:repo.begin_attempt(manifest,pending,now=int(time()))
        reusable=[]; fresh=[]
        with self.repository() as repo:
            for item in pending:
                ih=exact_input_hash(item_text(item))
                locator=self.receipt_index.get(ih)
                if locator is None:fresh.append(item)
                else:
                    old,pin,key,text_value=locator
                    receipt=repo.persisted_receipt(old,pin,key,text_value)
                    require(receipt is not None, 'PERSISTED_REUSE_MISSING')
                    reusable.append((item,receipt));self.reused_persisted+=1
            if reusable:
                repo.persist(manifest,[v[0] for v in reusable],[v[1] for v in reusable],now=int(time()))
        if fresh:
            with self.repository() as repo:
                summary=handoff(self.provider,repo,manifest,fresh,now=int(time()),retries=retries)
            self.save(f'batch-{len(self.provider.attempts):04d}',summary)
        for pin,key,item in pending:
            ih=exact_input_hash(item_text((pin,key,item)))
            self.receipt_index[ih]=(manifest,pin,key,item_text((pin,key,item)))
            self.provider.ledger.pop((*self.provider.scope,ih,self.provider.profile.canonical_hash()),None)

    def build(self, manifest, items):
        # Exact duplicate texts are reused only AFTER their first committed insert.
        batch=[];seen=set();tokens=0;done=0
        for item in items:
            value=item_text(item);ih=exact_input_hash(value);size=count_tokens(value)
            require(size<=4000,'INDIVIDUAL_ENTRY_BUDGET_HOLD')
            if batch and (len(batch)==8 or tokens+size>4000 or ih in seen):
                self.store_batch(manifest,batch,retries=2);done+=len(batch)
                if done%32<8:self.progress('P2_EMBEDDING_BUILD',lane=manifest.lane.value,persisted=done)
                batch=[];seen=set();tokens=0
            batch.append(item);seen.add(ih);tokens+=size
        if batch:self.store_batch(manifest,batch,retries=2)

    def seal(self, manifest):
        started=perf_counter()
        with self.repository() as repo:
            repo.seal_generation(manifest,expected_build_identity=repo.build_identity(manifest),now=int(time()))
            repo.transition(manifest,State.CANARY_READ,now=int(time()))
            repo.read_gate(manifest,self.hard(manifest),now=int(time()))
        return (perf_counter()-started)*1000

    def p1(self):
        self.progress('P1_STAGING')
        selected=[];pins={}
        with self.repository() as repo:
            for row in self.plan['p1_entries']:
                doc=row['source_document'];batch=self.batches[doc]
                if doc not in pins:
                    pins[doc]=repo.register_fixture_source(batch,
                        source_id=batch.scope.revision.source.document_id,website_id=self.websites[doc])
                entry=next(e for e in batch.entries if e.entry_key==row['entry'])
                require(exact_input_hash(entry.text)==row['input_hash'],'P1_EXACT_INPUT_MISMATCH')
                selected.append((pins[doc],entry.entry_key,entry))
            require(sum(e.token_count for _,_,e in selected)==self.plan['p1_tokens'],'P1_TOKEN_MISMATCH')
            mf=self.manifest(pins.values(),run='p1-handoff',selection=tuple(v[1] for v in selected))
            repo.create(mf,now=int(time()))
            for doc in pins:repo.stage_structure(mf,self.batches[doc],now=int(time()))
        self.progress('P1_PROVIDER_HANDOFF')
        self.store_batch(mf,selected,retries=0)
        self.progress('P1_QUERY_EMBEDDING')
        query=self.plan['p1_query']
        require(exact_input_hash(query)==self.plan['p1_query_hash'],'P1_QUERY_CHANGED')
        qr=self.provider.embed([query],purpose='query',retries=0)[0]
        self.progress('P1_SEAL')
        seal_ms=self.seal(mf)
        self.progress('P1_SCOPED_COSINE')
        hard=self.hard(mf)
        with self.repository() as repo:
            epoch=repo.read_gate(mf,hard,now=int(time()))
            hits=repo.dense(mf,hard,qr.vector,now=int(time()))
            require({h.route.key for h in hits}==set(mf.vector_entry_selection),'P1_DENSE_INVENTORY_MISMATCH')
            mapped={h.route.key:repo.children(mf,hard,h.route,now=int(time())) for h in hits}
            security={}
            for label,changed in [('foreign_org',replace(hard,organization_id=hard.organization_id+1)),
                                  ('foreign_bot',replace(hard,bot_id=hard.bot_id+1))]:
                try:repo.dense(mf,changed,qr.vector,now=int(time()))
                except CanaryError as exc:require(str(exc)=='FOREIGN_HARD_SCOPE','P1_SECURITY_WRONG_REFUSAL')
                else:raise CanaryError('P1_SCOPE_LEAK')
                security[label]='REFUSED'
            require(not repo.dense(mf,replace(hard,active_document_versions=((999999,1,None),)),qr.vector,now=int(time())),
                'P1_STALE_VERSION_LEAK')
            security['stale_version']='ZERO_CANDIDATES'
            repo.read_gate(mf,hard,now=int(time()),expected_epoch=epoch)
            for pin,key,entry in selected:require(repo.persisted_receipt(mf,pin,key,entry.text) is not None,'P1_READBACK_MISSING')
        from scripts.canary_real_security import verify_security
        attacks=verify_security(self,mf,qr)
        with self.repository() as repo:repo.read_gate(mf,hard,now=int(time()),expected_epoch=epoch)
        self.result['p1']=dict(result='PASS',exact_readback='PASS',seal='INDEX_READY_THEN_CANARY_READ',
            manifest=mf.canonical_hash(),document_inputs=8,local_tokens=3044,query=vector_summary(qr),
            security=security,attack_rows=attacks,source_epoch='UNCHANGED',seal_ms=seal_ms,
            candidates=[dict(entry=h.route.key,distance=h.score,
                source_id=next(p.source_id for p in mf.documents if p.scope==h.route.source),
                atoms=list(mapped[h.route.key])) for h in hits])
        # Validate the full public result before admitting P2. No vector dump.
        self.save('p1',self.result['p1']);emit({'stage':'P1_COMPLETE','result':'PASS','inputs':8})
        return mf

    def stage_paired(self):
        self.progress('P2_STAGING')
        pins={}
        with self.repository() as repo:
            for doc,batch in self.batches.items():
                pins[doc]=repo.register_fixture_source(batch,
                    source_id=batch.scope.revision.source.document_id,website_id=self.websites[doc])
            structural=self.manifest(pins.values(),run='paired-real')
            lp={doc:p.model_copy(update={'entries':(),'legacy_members':tuple(c['id'] for c in self.legacy_chunks[doc]),
                'batch_hash':digest(self.legacy_chunks[doc])}) for doc,p in pins.items()}
            legacy=self.manifest(lp.values(),run='paired-real',lane=Lane.LEGACY_CONTROL)
            repo.create(structural,now=int(time()));repo.create(legacy,now=int(time()))
        for doc,batch in self.batches.items():
            with self.repository() as repo:
                repo.stage_structure(structural,batch,now=int(time()))
                repo.stage_legacy_work(legacy,lp[doc],self.legacy_chunks[doc],now=int(time()))
            self.progress('P2_STAGING',documents_staged=list(self.batches).index(doc)+1)
        return structural,legacy,pins,lp

    def p2(self):
        started=perf_counter()
        structural,legacy,pins,lp=self.stage_paired()
        self.build(structural,[(pins[d],e.entry_key,e) for d,b in self.batches.items() for e in b.entries])
        self.build(legacy,[(lp[d],c['id'],c) for d,rows in self.legacy_chunks.items() for c in rows])
        self.evaluate_paired(structural,legacy,started)

    def embed_query(self,query):
        return self.provider.embed([query],purpose='query',retries=2)[0]

    def evaluate_paired(self,structural,legacy,started):
        self.progress('P2_SEAL')
        seals={m.lane.value:self.seal(m) for m in (structural,legacy)}
        with self.repository() as repo:
            counts=repo.counts(structural)
            sizes=[dict(r) for r in repo.conn.execute(text("""SELECT relname,
                pg_relation_size(c.oid) relation_bytes,pg_total_relation_size(c.oid) total_bytes
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND c.relkind='r' ORDER BY relname""")).mappings()]
        self.result['storage']=dict(counts=counts,sizes=sizes,raw_vector_bytes=(1030+1092)*3072,
            build_ms=(perf_counter()-started)*1000,seal_ms=seals)
        from scripts.canary_real_security import verify_security
        # First frozen evaluation query is shared with its later evaluation,
        # never an extra security embedding request.
        self.result['security']=verify_security(self,structural,self.embed_query(self.common[0][0]['query']))
        sidecar=json.loads((self.root/'backend/fixtures/canary_mechanics_v1/real_corpus_retrieval_gold.json').read_text())
        gold={int(c['case_id']):c for c in sidecar['cases']}
        entry_atoms={(b.scope.revision.source.document_id,e.entry_key):tuple({m.atom_key for m in e.memberships})
                     for b in self.batches.values() for e in b.entries}
        summaries=[]
        for snapshot,hard in self.common:
            case=snapshot['id'];query=snapshot['query']
            self.progress('P2_PAIRED_RETRIEVAL',case=case)
            require((hard.organization_id,hard.bot_id)==self.provider.scope,'COMMON_HARD_SCOPE_MISMATCH')
            qr=self.embed_query(query)
            for mf in (legacy,structural):
                with self.repository() as repo:
                    trace=run_query(repo,mf,hard,query=query,query_vector=qr.vector,now=int(time()))
                require(trace['mode']=='full_hybrid','PAIRED_CHANNEL_FAILURE')
                outcome=score_case(trace,gold[case],mf.lane.value,mf.effective(hard),entry_atoms)
                record=dict(case=case,lane=mf.lane.value,snapshot_hash=snapshot['snapshot_hash'],
                    query=vector_summary(qr),outcome=outcome,trace=safe_trace(trace))
                self.save(f'case-{case:02d}-{mf.lane.value}',record)
                summaries.append(dict(case=case,lane=mf.lane.value,outcome=outcome,
                    dense_ms=trace['channels']['dense']['ms'],fts_ms=trace['channels']['fts']['ms'],
                    rrf_ms=trace['rrf_ms'],materialization_ms=trace['materialization_ms'],total_ms=trace['total_ms']))
        self.result['p2']='COMPLETE'
        from scripts.canary_real_summary import summarize
        self.result.update(summarize(summaries))

    def run(self):
        start=perf_counter()
        try:
            self.setup();self.p1();self.p2()
        except Exception as exc:
            self.result.update(decision='C',failure=safe_failure(exc))
        finally:
            if self.provider is not None:
                self.result['provider']=dict(self.provider.metrics,requests=len(self.provider.attempts),
                    reused_persisted=self.reused_persisted,
                    elapsed_call_ms=sum(a.get('duration_ms',0) for a in self.provider.attempts),cost='UNKNOWN')
                self.provider.close()
            if self.db is not None:
                try:self.result['cleanup']=self.db.cleanup()
                except Exception as exc:self.result.update(decision='C',cleanup=safe_failure(exc))
                finally:self.db.close()
            for name in ('CANARY_DATABASE_URL','CANARY_REAL_EMBEDDING_AUTHORIZED','CANARY_APPROVAL_REFERENCE',
                         'CANARY_ENVIRONMENT','CANARY_TARGET_FINGERPRINT'):
                self.env.pop(name,None)
            self.result['elapsed_ms']=(perf_counter()-start)*1000
            self.save('result',self.result)
            emit(self.result)
        return 0 if self.result['decision'] in ('A','B') else 1


def main():
    # SDK/HTTP diagnostics must never emit DSNs, headers or response objects.
    logging.disable(logging.CRITICAL)
    runner=Runner(Path(__file__).resolve().parents[2],os.environ)
    return runner.run()


if __name__=='__main__':raise SystemExit(main())
