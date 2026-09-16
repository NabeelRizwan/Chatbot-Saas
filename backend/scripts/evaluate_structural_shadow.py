"""Offline integrated observer replay; source-only saved input, count/hash output.

No application models/database/provider imports. Does not change GOLD or source.
"""
from collections import Counter
from dataclasses import replace
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services import structural_shadow as shadow
from services.structural_text_adapter import parse_structural_text
from services.structural_chunking import count_tokens, serialize_structural_document


def replay(snapshot):
    payload=json.loads(snapshot.read_text(encoding='utf-8'))
    legacy={}
    for c in payload['chunks']:
        row=legacy.setdefault(c['document_id'],[0,0])
        row[0]+=1;row[1]+=count_tokens(c['content'])
    rows=[];start=perf_counter()
    for record in payload['documents']:
        old_count,old_tokens=legacy.get(record['id'],[0,0])
        # Offline synthetic ownership, never a configured tenant/DB.
        source=shadow.ShadowSource(70001,70002,record['id'],1,(record.get('raw_text') or '').encode(),
            'markdown','extracted_markdown',legacy_chunks=old_count,legacy_tokens=old_tokens)
        identity=shadow.revision_identity(source)
        integrated,times=shadow.build_shadow(source,identity=identity)
        direct_graph=parse_structural_text(source.artifact,identity=identity,source_format='markdown',fidelity='extracted_markdown')
        direct=serialize_structural_document(direct_graph)
        if direct.canonical_json()!=integrated.canonical_json():raise AssertionError('direct/integrated mismatch')
        row=shadow.summarize(source,integrated)
        row.update(document_id=record['id'],status='validated',direct_integrated_parity=True,**times)
        rows.append(row)
        print(json.dumps({'document_id':record['id'],'specs':row['prospective_chunks'],'tokens':row['prospective_tokens'],'parity':True}),flush=True)
    counts=Counter()
    for row in rows:counts.update(row['chunk_kinds'])
    result={'documents':rows,'aggregate':shadow.aggregate(rows),'chunk_kinds':dict(counts),
        'elapsed_seconds':perf_counter()-start}
    for metric in ('heading_only_specs','unknown_role_specs','tiny_specs','inherited_only_specs',
                   'navigation_furniture_specs','navigation_furniture_candidate_specs','excluded_navigation_furniture_nodes','adjacent_small_units_kept_separate',
                   'nodes','edges','source_bytes','node_text_bytes','represented_node_bytes','unaccounted_node_bytes'):
        result[metric]=sum(r[metric] for r in rows)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=replay(args.snapshot)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='documents'}),flush=True)
