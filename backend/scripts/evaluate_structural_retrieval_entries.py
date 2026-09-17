"""Explicit offline file-only L evaluation. No DB, embeddings or retrieval calls."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import socket
import sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.structural_document import SourceIdentity, RevisionIdentity, StructuralDocument, make_node_key
from services.structural_chunking import SerializationBatch, count_tokens, digest, serialize_structural_document
from services.structural_retrieval_entries import build_retrieval_entries, RetrievalEntryScope


def namespace_evidence(batch,organization_id=None,bot_id=None,document_id=None,source_version=None,revision_name=None):
    """Synthetic identity generator only: no content/semantic change or authority grant."""
    old=batch.source_graph.revision.identity
    data=old.source.model_dump()
    data.update({k:v for k,v in dict(organization_id=organization_id,bot_id=bot_id,
        document_id=document_id,source_version=source_version).items() if v is not None})
    data['document_version_id']='L-namespace-'+digest(data)[:32]
    source=SourceIdentity.model_validate(data)
    revision=RevisionIdentity(source=source,structure_revision_id=revision_name or 'L-namespace-'+source.canonical_hash())
    nodes={n.identity.node_key:make_node_key(source,n.parser_path,n.occurrence,n.text) for n in batch.source_graph.nodes}
    keys={c.chunk_key:digest([revision.model_dump(),c.chunk_key]) for c in batch.chunks}
    keys.update({c.bundle_key:digest([revision.model_dump(),c.bundle_key]) for c in batch.chunks})
    def rewrite(value,key=None):
        if isinstance(value,dict):
            if value==old.source.model_dump(mode='json'): return source.model_dump(mode='json')
            if value==old.model_dump(mode='json'): return revision.model_dump(mode='json')
            return {k:rewrite(v,k) for k,v in value.items()}
        if isinstance(value,list): return [rewrite(v,key) for v in value]
        if key=='node_key': return nodes.get(value,value)
        if key in ('chunk_key','chunk_id','bundle_key'): return keys.get(value,value)
        return value
    payload=rewrite(batch.model_dump(mode='json'))
    graph=StructuralDocument.model_validate(payload['source_graph'])
    ih=graph.canonical_hash();payload['input_hash']=ih
    for c in payload['chunks']: c['input_hash']=ih
    return SerializationBatch.model_validate(payload).verify()


def distribution(values):
    if not values:return {'min':0,'p50':0,'p95':0,'max':0}
    x=sorted(values)
    return dict(min=x[0],p50=x[math.ceil(len(x)*.5)-1],p95=x[math.ceil(len(x)*.95)-1],max=x[-1])


def metrics(batch,source_tokens):
    e=batch.entries; ledger=batch.coverage
    counts=Counter(x.disposition for x in ledger.nodes)
    return dict(source_tokens=source_tokens,nodes=len(batch.evidence.source_graph.nodes),
        edges=len(batch.evidence.source_graph.edges),searchable_atoms=len(batch.atoms),entries=len(e),
        entry_tokens=sum(x.token_count for x in e),mapping_rows=sum(x.mapping_count for x in e),
        entry_tokens_distribution=distribution([x.token_count for x in e]),
        atom_fanout_distribution=distribution([x.logical_child_count for x in e]),
        heading_only=sum(x.kind=='heading' for x in e),small=sum(x.token_count<250 for x in e),
        continuations=sum(x.kind=='continuation' for x in e),
        lexical_only_atoms=sum(x.disposition=='LEXICAL_ONLY' for x in ledger.atoms),
        node_dispositions=dict(counts),excluded_reasons=dict(Counter(reason for r in ledger.nodes for reason in r.reasons)),
        max_mapping_count=max((x.mapping_count for x in e),default=0),
        mapped_node_bytes=sum(x.mapped_bytes for x in ledger.nodes),
        admitted_node_bytes=sum(x.source_bytes-x.excluded_bytes for x in ledger.nodes),
        excluded_node_bytes=sum(x.excluded_bytes for x in ledger.nodes),unaccounted_bytes=ledger.unaccounted_bytes,
        entries_per_1000_tokens=len(e)*1000/source_tokens,token_multiplier=sum(x.token_count for x in e)/source_tokens,
        mapping_rows_per_1000_tokens=sum(x.mapping_count for x in e)*1000/source_tokens,batch_hash=batch.canonical_hash())


def network_denied():
    def fail(*a,**kw):raise AssertionError('L evaluation network forbidden')
    socket.socket.connect=fail;socket.socket.connect_ex=fail
    socket.create_connection=fail;socket.getaddrinfo=fail


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--scale',type=int,choices=(1,10,100),default=1)
    parser.add_argument('--saved',action='store_true');parser.add_argument('--document-scale',action='store_true')
    args=parser.parse_args();network_denied()
    root=Path(__file__).resolve().parents[2];output=Path(args.output).resolve()
    allowed=(root/'.codex_structural_4_1l').resolve()
    if not output.is_relative_to(allowed):raise ValueError('output must stay in ignored L evaluation directory')
    start=perf_counter();out={};observed_peak=0
    try:
        import psutil
        process=psutil.Process()
    except ImportError:process=None
    if args.saved:
        from scripts.structural_descriptor_corpus import load_corpus
        prep=perf_counter();batches,pins,_,_=load_corpus(root)
        out['existing_parser_serializer_seconds']=perf_counter()-prep
        source=json.loads((root/'.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json').read_text(encoding='utf-8'))
        tokens={d['id']:count_tokens(d['raw_text']) for d in source['documents']}
        del source
        rows=[];totals=Counter();work_seconds=0.;namespace_seconds=0.;ids=set();hashes=[]
        token_histogram=Counter();fanout_histogram=Counter();max_maps=0
        for replica in range(args.scale):
            for did,original in batches.items():
                t=perf_counter()
                b=original if args.scale==1 else namespace_evidence(original,organization_id=800000+replica,bot_id=900000+replica)
                namespace_seconds+=perf_counter()-t
                pin=pins[did];scope=RetrievalEntryScope(revision=b.source_graph.revision.identity,
                    crawl_id=pin.crawl_id,crawl_version=pin.crawl_version)
                assert scope.canonical_hash() not in ids;ids.add(scope.canonical_hash())
                t=perf_counter();result=build_retrieval_entries(b,scope=scope);duration=perf_counter()-t;work_seconds+=duration
                m=metrics(result,tokens[did]);hashes.append(m['batch_hash'])
                token_histogram.update(x.token_count for x in result.entries)
                fanout_histogram.update(x.logical_child_count for x in result.entries)
                max_maps=max(max_maps,m['max_mapping_count'])
                for k in ('source_tokens','nodes','edges','searchable_atoms','entries','entry_tokens','mapping_rows','heading_only','small','continuations','lexical_only_atoms','mapped_node_bytes','admitted_node_bytes','unaccounted_bytes'):
                    totals[k]+=m[k]
                if args.scale==1:
                    repeated=build_retrieval_entries(b,scope=scope)
                    m['repeat_hash_equal']=repeated.canonical_hash()==m['batch_hash'];assert m['repeat_hash_equal']
                    m['seconds']=duration;m['document_id']=did;rows.append(m)
                if process:observed_peak=max(observed_peak,process.memory_info().rss)
                if args.scale>1 and did==next(reversed(batches)):
                    print(json.dumps({'replicas_complete':replica+1,'scale':args.scale}),flush=True)
        out.update(scale=args.scale,totals=dict(totals),documents=rows,distinct_scopes=len(ids),
            token_histogram=dict(token_histogram),fanout_histogram=dict(fanout_histogram),max_mapping_count=max_maps,
            construction_seconds=work_seconds,namespace_seconds=namespace_seconds,
            construction_seconds_per_1000_tokens=work_seconds*1000/totals['source_tokens'],
            sampled_process_peak_rss_bytes=observed_peak or None,identity_digest=sha256(''.join(hashes).encode()).hexdigest())
    if args.document_scale:
        from scripts.evaluate_structural_text_adapter import parse_source
        rows=[]
        for size in (10,100,500,1000):
            text='# Guide\n\n'+'\n\n'.join(f'## Section {i}\n\nAn ordinary passage remains exact.\n\n- First item\n- Second item' for i in range(size))
            t=perf_counter();d=parse_source(text);b=serialize_structural_document(d);prep=perf_counter()-t
            t=perf_counter();r=build_retrieval_entries(b,scope=RetrievalEntryScope(revision=d.revision.identity));dt=perf_counter()-t
            row=metrics(r,count_tokens(text));row.update(sections=size,seconds=dt,existing_parser_serializer_seconds=prep)
            rows.append(row)
        out['document_scale']=rows
    out['total_seconds']=perf_counter()-start
    # Windows exposes the kernel-recorded lifetime peak working set. Includes
    # fixture preparation and validation, not a claim about serving memory.
    out['os_peak_working_set_bytes']=getattr(process.memory_info(),'peak_wset',None) if process else None
    output.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k not in ('documents','document_scale')},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
