"""Frozen-file Phase J source-native reconstruction. No database/catalog writes."""
from hashlib import sha256
import json
from pathlib import Path

from services.structural_document import SourceIdentity, RevisionIdentity
from services.structural_text_adapter import parse_structural_text
from services.structural_chunking import serialize_structural_document
from scripts.structural_resource_descriptors import SourcePin, ResourceTarget, Refusal


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def file_hash(path): return sha256(path.read_bytes()).hexdigest()


def native_batch(text, *, org, bot, document, version):
    data=text.encode('utf-8'); h=sha256(data).hexdigest()
    s=SourceIdentity(organization_id=org,bot_id=bot,document_id=document,source_version=version,
        document_version_id=f'phase-j-native-v{version}-{h}',source_sha256=h)
    r=RevisionIdentity(source=s,structure_revision_id='phase-j-native-'+s.canonical_hash())
    graph=parse_structural_text(data,identity=r,source_format='markdown',fidelity='extracted_markdown')
    return serialize_structural_document(graph)


def load_corpus(root):
    folder=root/'.codex_real_corpus_v1'
    source=read(folder/'SOURCE_PRODUCTION_SNAPSHOT.json')
    projection=read(folder/'PHASE37_PROJECTION.json')
    mapping=read(folder/'SOURCE_TO_DEVELOPMENT_ID_MAPPING.json')
    fp=read(folder/'REAL_CORPUS_V1_FINGERPRINT.json')
    if not projection['source_corpus_unchanged'] or projection['source_corpus_fingerprint']!=fp['fingerprint']:
        raise Refusal('frozen_projection_mismatch')
    org,bot=fp['development_organization_id'],fp['development_bot_id']
    source_scope=(fp['source_organization_id'],fp['source_bot_id'])
    assert mapping['organization'][str(source_scope[0])]==org
    assert mapping['bot'][str(source_scope[1])]==bot
    catalog=projection['catalog']
    assert all((r['organization_id'],r['bot_id'])==(org,bot) for rows in catalog.values() for r in rows)
    crawls={r['id']:r for r in source['website_crawls']}
    websites={r['id']:r for r in source['websites']}
    batches={};pins={};resources=[];reconciliation=[]
    for d in source['documents']:
        assert (d['organization_id'],d['bot_id'])==source_scope
        assert d['status']=='ready' and d['processing_status']=='completed'
        mapped=mapping['corpus']['documents'][str(d['id'])]
        b=native_batch(d['raw_text'],org=org,bot=bot,document=mapped,version=d['version'])
        crawl=crawls.get(d['crawl_id']);website=websites.get(d['website_id'])
        if website: assert website['active_crawl_id']==d['crawl_id']
        if crawl: assert crawl['status']=='ready' and (crawl['organization_id'],crawl['bot_id'])==source_scope
        mapped_crawl=mapping['corpus']['website_crawls'].get(str(d['crawl_id'])) if crawl else None
        p=SourcePin(revision=b.source_graph.revision.identity,source_document_id=d['id'],
            source_organization_id=source_scope[0],source_bot_id=source_scope[1],
            crawl_id=mapped_crawl,crawl_version=crawl['version'] if crawl else None,canonical_url=d['canonical_url'] or '')
        links=[r for r in catalog['knowledge_resource_documents'] if r['document_id']==mapped]
        assert len(links)==1
        link=links[0]
        assert link['relation_type']=='primary' and link['document_version']==d['version'] and link['document_crawl_id']==mapped_crawl
        r=next(r for r in catalog['knowledge_resources'] if r['id']==link['resource_id'])
        assert r['status']=='ready' and r['resource_type']=='document'
        assert r['source_key']==f'document:{mapped}' and r['metadata_json']=={'primary_document_id':mapped}
        assert r['url']==p.canonical_url
        resources.append(ResourceTarget(key='catalog:'+str(r['id']),pin=p,root=b.source_graph.nodes[0].identity,canonical_url=r['url']))
        batches[d['id']]=b;pins[d['id']]=p
        metadata=d.get('metadata_json') or d.get('metadata') or {}
        # Report capture availability only; never copy arbitrary saved metadata.
        reconciliation.append({'document_id':d['id'],'development_document_id':mapped,'source_version':d['version'],
            'source_hash':p.revision.source.source_sha256,'crawl_id':mapped_crawl,'crawl_version':p.crawl_version,
            'graph_hash':b.source_graph.canonical_hash(),'pin':p.model_dump(mode='json'),
            'saved_raw_html':bool(d.get('raw_html') or metadata.get('rawHtml') or metadata.get('raw_html') or metadata.get('html')),
            'saved_anchor_registry':bool(metadata.get('anchor_map') or metadata.get('anchors') or metadata.get('fragment_targets')),
            'saved_dom_boundaries':bool(metadata.get('dom_blocks') or metadata.get('resource_boundaries')),
            'saved_json_ld_identity':bool(metadata.get('json_ld') or metadata.get('jsonld') or metadata.get('structuredData'))})
    assert len(batches)==23 and len(resources)==23
    return batches,pins,tuple(resources),reconciliation
