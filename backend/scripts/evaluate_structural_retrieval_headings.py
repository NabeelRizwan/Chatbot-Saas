"""M offline measurement: frozen source files only; bounded local worker pool.

No DB/provider/embedding calls. 1x compares frozen v1 and v2 side-by-side and
repeats hashes; 10x/100x actually construct every independently scoped source.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_structural_retrieval_entries import namespace_evidence, metrics, network_denied
from scripts.structural_retrieval_heading_gold import assert_reachability
from services import structural_retrieval_entries as v1
from services import structural_retrieval_entries_v2 as v2
from services.structural_chunking import count_tokens, serialize_structural_document

ROOT = Path(__file__).resolve().parents[2]
STATE = {}
ADDITIVE = ('source_tokens','nodes','edges','searchable_atoms','entries','entry_tokens','mapping_rows',
            'heading_only','small','continuations','lexical_only_atoms','mapped_node_bytes','admitted_node_bytes','unaccounted_bytes')


def init_worker():
    network_denied()
    from scripts.structural_descriptor_corpus import load_corpus
    start = perf_counter()
    batches, pins, _, _ = load_corpus(ROOT)
    raw = json.loads((ROOT/'.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json').read_text(encoding='utf-8'))
    tokens = {d['id']: count_tokens(d['raw_text']) for d in raw['documents']}
    del raw
    STATE.update(batches=batches, pins=pins, tokens=tokens, prep_seconds=perf_counter()-start)


def one(task):
    replica, did, scale = task
    import os
    import psutil
    start = perf_counter()
    original = STATE['batches'][did]
    b = original if scale == 1 else namespace_evidence(original, organization_id=800000+replica, bot_id=900000+replica)
    namespace_seconds = perf_counter()-start
    pin = STATE['pins'][did]
    scope = v1.RetrievalEntryScope(revision=b.source_graph.revision.identity, crawl_id=pin.crawl_id, crawl_version=pin.crawl_version)
    start = perf_counter()
    old = v1.build_retrieval_entries(b, scope=scope)
    old_seconds = perf_counter()-start
    start = perf_counter()
    new = v2.revise_heading_allocation(old, scope=scope)
    revision_seconds = perf_counter()-start
    assert new.evidence == old.evidence and new.atoms == old.atoms
    proxy = assert_reachability(new)
    first_hash = new.canonical_hash()
    repeated = None
    if scale == 1:
        repeated = v2.build_retrieval_entries(b, scope=scope).canonical_hash() == first_hash
        assert repeated
    info = psutil.Process().memory_info()
    return dict(document_id=did, replica=replica, scope_hash=scope.canonical_hash(),
        implementation_hash=v2._implementation_hash(),
        v1=metrics(old,STATE['tokens'][did]), v2=metrics(new,STATE['tokens'][did]),
        repeat_hash_equal=repeated, proxy_headings=proxy,
        standalone_headings=sum(a.disposition=='STANDALONE' for a in new.heading_allocations),
        namespace_seconds=namespace_seconds, v1_seconds=old_seconds, revision_seconds=revision_seconds,
        worker_pid=os.getpid(), worker_preparation_seconds=STATE['prep_seconds'],
        worker_peak_bytes=getattr(info,'peak_wset',info.rss),
        token_histogram=dict(Counter(e.token_count for e in new.entries)),
        fanout_histogram=dict(Counter(e.logical_child_count for e in new.entries)))


def saved(scale, workers):
    # IDs are a file inventory, not implementation branches. Do not read DB/env.
    raw = json.loads((ROOT/'.codex_real_corpus_v1/SOURCE_PRODUCTION_SNAPSHOT.json').read_text(encoding='utf-8'))
    ids = sorted(d['id'] for d in raw['documents'])
    del raw
    tasks = [(replica,did,scale) for replica in range(scale) for did in ids]
    frozen_v1 = {}
    baseline = ROOT/'.codex_structural_4_1l/saved_1x_final.json'
    if scale == 1:
        frozen_v1 = {r['document_id']:r['batch_hash'] for r in json.loads(baseline.read_text())['documents']}
    start = perf_counter(); rows=[]; scopes=set(); totals={'v1':Counter(),'v2':Counter()}
    hashes=[]; old_hashes=[]; tokens=Counter(); fanout=Counter(); workers_seen={}; max_maps=0
    timings=Counter(); allocations=Counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker) as pool:
        for i, row in enumerate(pool.map(one,tasks,chunksize=1),1):
            assert row['implementation_hash'] == v2._implementation_hash(), 'implementation changed during evaluation'
            if scale == 1:
                assert row['v1']['batch_hash'] == frozen_v1[row['document_id']], 'frozen v1 hash changed'
            assert row['scope_hash'] not in scopes
            scopes.add(row['scope_hash']); hashes.append(row['v2']['batch_hash']); old_hashes.append(row['v1']['batch_hash'])
            for mode in totals:
                totals[mode].update({k:row[mode][k] for k in ADDITIVE})
            tokens.update(row['token_histogram']);fanout.update(row['fanout_histogram'])
            max_maps=max(max_maps,row['v2']['max_mapping_count'])
            for k in ('namespace_seconds','v1_seconds','revision_seconds'): timings[k]+=row[k]
            allocations['contextual_only']+=row['proxy_headings'];allocations['standalone']+=row['standalone_headings']
            workers_seen[str(row['worker_pid'])]={'preparation_seconds':row['worker_preparation_seconds'],'peak_bytes':row['worker_peak_bytes']}
            if scale==1: rows.append(row)
            if i%len(ids)==0:print(json.dumps({'documents_complete':i,'total':len(tasks)}),flush=True)
    assert len(scopes) == len(tasks)
    assert totals['v2']['unaccounted_bytes'] == 0
    assert totals['v2']['admitted_node_bytes'] == totals['v2']['mapped_node_bytes']
    return dict(scale=scale,workers=workers,documents=rows,distinct_scopes=len(scopes),
        totals={k:dict(v) for k,v in totals.items()}, token_histogram=dict(tokens), fanout_histogram=dict(fanout),
        max_mapping_count=max_maps, timings=dict(timings), allocations=dict(allocations),worker_stats=workers_seen,
        identity_digest=sha256(''.join(hashes).encode()).hexdigest(),
        v1_identity_digest=sha256(''.join(old_hashes).encode()).hexdigest(),total_seconds=perf_counter()-start)


def document_scale():
    from scripts.evaluate_structural_text_adapter import parse_source
    rows=[]
    for label in ('Section','Clause','Chapter','Article','Module','Step','Version'):
        for size in (10,100,500,1000):
            text='# Guide\n\n'+'\n\n'.join(f'## {label} {i}\n\nAn ordinary passage remains exact.\n\n- First item\n- Second item' for i in range(size))
            start=perf_counter();b=serialize_structural_document(parse_source(text));prep=perf_counter()-start
            scope=v1.RetrievalEntryScope(revision=b.source_graph.revision.identity)
            start=perf_counter();old=v1.build_retrieval_entries(b,scope=scope);old_seconds=perf_counter()-start
            start=perf_counter();new=v2.revise_heading_allocation(old,scope=scope);revision_seconds=perf_counter()-start
            assert_reachability(new)
            rows.append(dict(label=label,sections=size,v1=metrics(old,count_tokens(text)),v2=metrics(new,count_tokens(text)),
                preparation_seconds=prep,v1_seconds=old_seconds,revision_seconds=revision_seconds,
                contextual_only=sum(a.disposition=='CONTEXTUAL_ONLY' for a in new.heading_allocations)))
            print(json.dumps({'label':label,'sections':size,'entries':len(new.entries)}),flush=True)
    return {'document_scale':rows}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--scale',type=int,choices=(1,10,100),default=1)
    p.add_argument('--workers',type=int,choices=(1,2),default=2)
    p.add_argument('--saved',action='store_true');p.add_argument('--document-scale',action='store_true')
    a=p.parse_args();network_denied()
    output=Path(a.output).resolve()
    if not output.is_relative_to((ROOT/'.codex_structural_4_1m').resolve()):raise ValueError('output must remain in ignored M directory')
    if a.saved==a.document_scale:raise ValueError('select exactly one evaluation')
    start=perf_counter()
    result=saved(a.scale,a.workers) if a.saved else document_scale()
    result['whole_process_seconds']=perf_counter()-start
    result['v2_implementation_hash']=v2._implementation_hash()
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('documents','document_scale','token_histogram','fanout_histogram')},indent=2))


if __name__=='__main__':main()
