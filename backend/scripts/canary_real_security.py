"""Owned, rollback-only adversarial rows; never trusted provider attestations.

Copies an authorized real query vector under deliberately foreign fixture
identities. Direct test inserts do not disable guards or bless these records as
sealed/provider-attested builds. The production canary seal still rejects them.
"""
from dataclasses import replace
from time import time
from sqlalchemy import insert, select, update, Float
from database import canary_schema as s
from services.canary_contracts import CanaryError, canonical_vector_digest
from services.canary_repository import where, manifest_values, run_values, source_values
from services.canary_retrieval import normalize, typed_rrf
from services.structural_chunking import digest


def verify_security(runner, manifest, query_receipt=None):
    # Already-created query only. Never spends provider quota for attacks.
    receipt=query_receipt or runner.provider.receipt(runner.plan['p1_query'])
    params={'query_vector':'['+','.join(map(str,receipt.vector))+']'}
    outcomes={}
    hard=runner.hard(manifest)
    with runner.repository() as repo:
        conn=repo.conn; savepoint=conn.begin_nested()
        try:
            pin=manifest.documents[0];src=source_values(pin)
            source=dict(conn.execute(select(s.sources).where(where(s.sources,src))).mappings().one())
            life=dict(conn.execute(select(s.lifecycle).where(s.lifecycle.c.document_id==src['document_id'],
                s.lifecycle.c.organization_id==src['organization_id'],s.lifecycle.c.bot_id==src['bot_id'])).mappings().one())
            document=dict(conn.execute(select(s.documents).where(where(s.documents,manifest_values(manifest)),
                s.documents.c.document_id==src['document_id'])).mappings().one())
            entry=dict(conn.execute(select(s.entries).where(where(s.entries,manifest_values(manifest)),
                s.entries.c.document_id==src['document_id']).limit(1)).mappings().one())
            atom=dict(conn.execute(select(s.atoms).where(where(s.atoms,manifest_values(manifest)),
                s.atoms.c.document_id==src['document_id']).limit(1)).mappings().one())
            vector=dict(conn.execute(select(s.vectors).where(where(s.vectors,manifest_values(manifest))).limit(1)).mappings().one())
            run=dict(conn.execute(select(s.runs).where(where(s.runs,run_values(manifest)))).mappings().one())
            build=dict(conn.execute(select(s.manifests).where(where(s.manifests,manifest_values(manifest)))).mappings().one())
            for i,label in enumerate(('foreign_org','foreign_bot','stale_generation','stale_source','identical_text_other_scope'),1):
                org=src['organization_id']+(1 if label in ('foreign_org','identical_text_other_scope') else 0)
                bot=src['bot_id']+(1 if label=='foreign_bot' else 0)
                changed=dict(organization_id=org,bot_id=bot,document_id=900000+i,
                    run_id=manifest.run_id if label=='stale_generation' else 'attack-'+label,
                    generation='attack-generation',manifest_hash=digest(label))
                def clone(row):return {k:changed.get(k,v) for k,v in row.items()}
                a_source=clone(source); a_src={k:a_source[k] for k in s.SRC}
                conn.execute(insert(s.sources),a_source)
                conn.execute(insert(s.lifecycle),clone(life)|dict(source_fingerprint=digest(a_src)))
                a_run=clone(run)|dict(state='EMBEDDING_STAGING',epoch=0)
                if label!='stale_generation':conn.execute(insert(s.runs),a_run)
                a_build=clone(build)|dict(state='EMBEDDING_STAGING',state_epoch=0)
                conn.execute(insert(s.manifests),a_build)
                a_doc=clone(document)|dict(source_fingerprint=digest(a_src))
                conn.execute(insert(s.documents),a_doc)
                a_entry=clone(entry);conn.execute(insert(s.entries),a_entry)
                # Copy real query vector to make a measured zero-distance attack.
                # This explicit TEST_COPY proof cannot pass RealCanaryRepository.seal.
                a_vector=clone(vector)|{k:a_doc[k] for k in s.DOC}|dict(entry_id=a_entry['entry_id'],
                    input_hash=a_entry['input_hash'],embedding=list(receipt.vector),
                    vector_hash=canonical_vector_digest(receipt.vector),
                    provider_receipt={'provenance':'SECURITY_TEST_COPY_NOT_PROVIDER_ATTESTATION'})
                conn.execute(insert(s.vectors),a_vector)
                a_atom=clone(atom)|dict(route_kind='ENTRY',route_entry=a_entry['entry_id'])
                conn.execute(insert(s.atoms),a_atom)
                # Malicious fixture state, not a seal API success; all immutable
                # identity and source-epoch DB triggers remain active.
                man={k:a_build[k] for k in s.MAN};run_key={k:a_run[k] for k in s.RUN}
                conn.execute(update(s.manifests).where(where(s.manifests,man)).values(state='INDEX_READY',state_epoch=1))
                conn.execute(update(s.manifests).where(where(s.manifests,man)).values(state='CANARY_READ',state_epoch=2))
                if label!='stale_generation':
                    conn.execute(update(s.runs).where(where(s.runs,run_key)).values(state='CANARY_READ',epoch=2))
                distance=conn.execute(select(s.vectors.c.embedding.op('<=>',return_type=Float)(text_vector())).where(
                    where(s.vectors,{k:a_vector[k] for k in s.DOC}),s.vectors.c.entry_id==a_vector['entry_id']),params).scalar_one()
                if abs(float(distance))>0.000001:raise CanaryError('ATTACK_VECTOR_STRENGTH_UNPROVEN')
                if label=='stale_source':
                    conn.execute(update(s.lifecycle).where(s.lifecycle.c.organization_id==org,
                        s.lifecycle.c.bot_id==bot,s.lifecycle.c.document_id==changed['document_id'])
                        .values(status='deleted',epoch=1))
                dense=repo.dense(manifest,hard,receipt.vector,now=int(time()))
                lexical=repo.fts(manifest,hard,runner.plan['p1_query'],now=int(time())).hits
                if any(h.route.manifest!=manifest.canonical_hash() or h.route.source.revision.source.document_id==changed['document_id']
                       for h in (*dense,*lexical)):raise CanaryError('REAL_SECURITY_CANDIDATE_LEAK')
                nd=normalize(dense,manifest,manifest.effective(hard));nf=normalize(lexical,manifest,manifest.effective(hard))
                fused=typed_rrf(nd,nf,manifest.policy)
                if any(r['route'].source.revision.source.document_id==changed['document_id'] for r in fused):
                    raise CanaryError('REAL_SECURITY_ROUTING_LEAK')
                # Forged foreign route cannot fetch any evidence payload.
                route=dense[0].route.model_copy(update={'manifest':changed['manifest_hash'],
                    'run_id':changed['run_id'],'generation':changed['generation']})
                try:repo.evidence(manifest,hard,route,a_atom['atom_id'],now=int(time()))
                except CanaryError as exc:
                    if str(exc)!='FOREIGN_MATERIALIZATION':raise
                else:raise CanaryError('REAL_SECURITY_MATERIALIZATION_LEAK')
                outcomes[label]=dict(raw_attack_distance=float(distance),
                    strictly_stronger=bool(dense and float(distance)<dense[0].score),
                    dense_unauthorized=0,fts_unauthorized=0,routing_unauthorized=0,materialization_unauthorized=0)
        finally:savepoint.rollback()
    return outcomes


def text_vector():
    from sqlalchemy import text, Float, type_coerce
    return type_coerce(text('CAST(:query_vector AS vector(768))'),Float)
