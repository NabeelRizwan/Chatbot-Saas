"""Offline span-aligned GOLD metrics and optional saved-source shadow summary.

No model/DB/application imports. GOLD is an evaluator input, never a parser input.
Only an explicitly requested ignored output file is written; no parsed structures.
"""
from collections import Counter
from hashlib import sha256
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
import tracemalloc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from scripts.structural_gold_v1 import fixture_specs, build_fixture
from services.structural_document import RevisionIdentity, SourceIdentity
from services.structural_text_adapter import LinkTarget, StructuralParseError, parse_structural_text


def parse_source(text,document_id=1,targets=()):
    identity=RevisionIdentity(source=SourceIdentity(organization_id=70001,bot_id=70002,
        document_id=document_id,document_version_id="offline-excerpt-v1",source_version=1,
        source_sha256=sha256(text.encode()).hexdigest()),structure_revision_id="adapter-evaluation-v1")
    return parse_structural_text(text,identity=identity,source_format="markdown",fidelity="extracted_markdown",link_targets=tuple(targets))


def bounds(node):
    r=node.provenance.spans[0].location.byte_range
    return r.start,r.end


def gold_bounds(spec,annotation):
    text=spec['source_text']
    return len(text[:annotation['start']].encode()),len(text[:annotation['end']].encode())


def encloses(outer,inner):
    return outer[0]<=inner[0] and outer[1]>=inner[1]


def fixture_result(spec):
    text=spec['source_text'];actual=parse_source(text,spec['document_id'])
    annotations={a['label']:a for a in spec['annotations']}
    gold=build_fixture(spec)
    gold_edges=[e for e in gold.edges if e.relation.value=='REFERS_TO']
    registry=[]
    # Explicit target authority is fixture-supplied, NOT inferred from nearby text.
    # External identities come from the frozen fixture. For local targets we align
    # exact byte intervals, not text similarity or target semantic descriptions.
    refs=[e for e in spec['edges'] if e['relation']=='REFERS_TO']
    for e in refs:
        evidence=annotations[e['evidence']]
        href=evidence['attributes']['link']['original_href']
        if 'to_source' in e:
            match=next(g for g in gold_edges if g.to_node.revision.source.document_id==e['to_source']['document_id'])
            endpoint=match.to_node
        else:
            interval=gold_bounds(spec,annotations[e['to']])
            matches=[n for n in actual.nodes if n.text and bounds(n)==interval]
            if len(matches)!=1: continue
            endpoint=matches[0].identity
        registry.append(LinkTarget(href,endpoint))
    actual=parse_source(text,spec['document_id'],registry)
    again=parse_source(text,spec['document_id'],registry)
    bykey={n.identity.node_key:n for n in actual.nodes}
    children={}
    for n in actual.nodes:
        if n.parent: children.setdefault(n.parent.node_key,[]).append(n)
    metrics={name:{'matched':0,'expected':0} for name in ('heading_body','full_list','review_target','timeline_stage','quantity','price_role','canonical_link','gold_text_retention')}
    def score(name,matched):
        metrics[name]['expected']+=1
        metrics[name]['matched']+=bool(matched)
    for a in spec['annotations']:
        if a['text']:
            interval=gold_bounds(spec,a)
            # Union of TEXT-bearing spans, not the document root's whole-source span.
            parts=sorted(bounds(n) for n in actual.nodes if n.text)
            cursor=interval[0]
            for start,end in parts:
                if start<=cursor: cursor=max(cursor,end)
            score('gold_text_retention',cursor>=interval[1])
        attrs=a['attributes']
        if attrs.get('list'):
            items=[x for x in spec['annotations'] if x['parent']==a['label'] and x['node_type']=='list_item']
            candidates=[n for n in actual.nodes if n.attributes.list and n.attributes.list.item_count==len(items)
                        and n.attributes.list.ordered==attrs['list']['ordered'] and n.attributes.list.source_block_complete]
            ok=False
            for n in candidates:
                actual_items=[c for c in children.get(n.identity.node_key,[]) if c.node_type.value=='list_item']
                if len(actual_items)==len(items) and all(encloses(bounds(c),gold_bounds(spec,g)) for c,g in zip(actual_items,items)):
                    ok=True
            score('full_list',ok)
        if attrs.get('commercial'):
            expected=next(n.attributes.commercial for n in gold.nodes if n.parser_path=='/'+a['label'])
            score('price_role',any(n.attributes.commercial==expected and encloses(gold_bounds(spec,a),bounds(n)) for n in actual.nodes))
        for q in next((n.attributes.quantities for n in gold.nodes if n.parser_path=='/'+a['label']),()):
            score('quantity',any(q in n.attributes.quantities and encloses(gold_bounds(spec,a),bounds(n)) for n in actual.nodes))
        if attrs.get('timeline'):
            expected=next(n.attributes.timeline for n in gold.nodes if n.parser_path=='/'+a['label'])
            descendants=[x for x in spec['annotations'] if x['parent']==a['label'] and x['text']]
            score('timeline_stage',any(n.attributes.timeline==expected and all(encloses(bounds(n),gold_bounds(spec,x)) for x in descendants) for n in actual.nodes))
        if attrs.get('link') and attrs['link']['safety']=='safe':
            expected=attrs['link']
            score('canonical_link',any(n.attributes.link and bounds(n)==gold_bounds(spec,a) and all(
                getattr(n.attributes.link,k)==expected.get(k) for k in ('original_href','anchor_text','fragment')) for n in actual.nodes))
    for e in spec['edges']:
        if e['relation']=='HEADING_FOR':
            a,b=gold_bounds(spec,annotations[e['from']]),gold_bounds(spec,annotations[e['to']])
            score('heading_body',any(x.relation.value=='HEADING_FOR' and bounds(bykey[x.from_node.node_key])==a and
                encloses(bounds(bykey[x.to_node.node_key]),b) for x in actual.edges))
        if e['relation']=='REFERS_TO':
            evidence=gold_bounds(spec,annotations[e['evidence']])
            wanted=next((r.node for r in registry if r.href==annotations[e['evidence']]['attributes']['link']['original_href']),None)
            # Same source-contained review and exact link evidence + pinned target.
            origin=gold_bounds(spec,annotations[e['from']])
            score('review_target',any(x.relation.value=='REFERS_TO' and x.to_node==wanted and
                (x.provenance.spans[0].location.byte_range.start,x.provenance.spans[0].location.byte_range.end)==evidence and
                encloses(bounds(bykey[x.from_node.node_key]),origin) for x in actual.edges))
    text_nodes=[n for n in actual.nodes if n.text]
    raw=text.encode()
    exact=sum(raw[bounds(n)[0]:bounds(n)[1]].decode()==n.text for n in text_nodes)
    emitted=sum(e.relation.value=='REFERS_TO' for e in actual.edges)
    return {'name':spec['name'],'category':spec['category'],'metrics':metrics,'review_edges_emitted':emitted,
        'provenance_exact':exact,'text_nodes':len(text_nodes),'deterministic':actual.canonical_json()==again.canonical_json(),
        'nodes':len(actual.nodes),'edges':len(actual.edges),'target_registry_supplied':len(registry)}


def evaluate_gold():
    rows=[fixture_result(s) for s in fixture_specs()]
    metrics={}
    for key in rows[0]['metrics']:
        matched=sum(r['metrics'][key]['matched'] for r in rows)
        expected=sum(r['metrics'][key]['expected'] for r in rows)
        metrics[key]={'matched':matched,'expected':expected,'recall':matched/expected if expected else None}
    emitted=sum(r['review_edges_emitted'] for r in rows)
    metrics['review_target'].update(emitted=emitted,precision=metrics['review_target']['matched']/emitted if emitted else None)
    return {'fixtures':len(rows),'metrics':metrics,'rows':rows,
        'provenance_exact':sum(r['provenance_exact'] for r in rows),'text_nodes':sum(r['text_nodes'] for r in rows),
        'deterministic':sum(r['deterministic'] for r in rows),
        'alignment':'exact excerpt UTF-8 intervals; containment for grouping, no semantic matching',
        'limitations':['Target registry is explicit fixture authority, not catalog discovery.',
            'Unmarked FAQ/table/header/quality annotations are not inferred from text.',
            'Additional unannotated source structures are counted, not scored as false positives.']}


def shadow(snapshot):
    payload=json.loads(snapshot.read_text(encoding='utf-8'))
    docs=payload['documents']
    rows=[]
    tracemalloc.start()
    start=perf_counter()
    for source in docs:
        text=source['raw_text']
        begin=perf_counter()
        try:
            d=parse_source(text,source['id'])
        except StructuralParseError as e:
            rows.append({'document_id':source['id'],'error':e.code})
            continue
        counts=Counter(n.node_type.value for n in d.nodes)
        depths={}
        spans=[]
        for n in d.nodes:
            depths[n.identity.node_key]=1+depths[n.parent.node_key] if n.parent else 0
            if n.text: spans.append(bounds(n))
        covered,cursor=0,0
        for a,b in sorted(spans):
            covered+=max(0,b-max(cursor,a));cursor=max(cursor,b)
        rows.append({'document_id':source['id'],'source_bytes':len(text.encode()),'nodes':len(d.nodes),
            'counts':dict(counts),'edges':len(d.edges),'review_groups':sum(n.semantic_role.value=='review' for n in d.nodes),
            'timeline_stages':sum(bool(n.attributes.timeline) for n in d.nodes),
            'unknown_roles':sum(n.semantic_role.value=='unknown' for n in d.nodes),
            'text_span_bytes':covered,'max_depth':max(depths.values()),'seconds':round(perf_counter()-begin,6),
            'source_quality':d.revision.quality.classification.value,'canonical_hash':d.canonical_hash()})
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    good=[r for r in rows if 'error' not in r]
    return {'documents':len(rows),'parsed':len(good),'errors':[r for r in rows if 'error' in r],
        'total_seconds':round(perf_counter()-start,6),'peak_traced_bytes_excluding_snapshot_load':peak,
        'source_bytes':sum(r['source_bytes'] for r in good),'text_span_bytes':sum(r['text_span_bytes'] for r in good),
        'nodes':sum(r['nodes'] for r in good),'edges':sum(r['edges'] for r in good),
        'counts':dict(sum((Counter(r['counts']) for r in good),Counter())),
        'review_groups':sum(r['review_groups'] for r in good),'timeline_stages':sum(r['timeline_stages'] for r in good),
        'unknown_roles':sum(r['unknown_roles'] for r in good),'max_depth':max((r['max_depth'] for r in good),default=0),
        'rows':rows,'scope':'local saved raw_text only; synthetic ownership, no target registry or DB writes'}


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--snapshot',type=Path)
    args.add_argument('--output',type=Path)
    options=args.parse_args()
    report={'gold':evaluate_gold()}
    if options.snapshot: report['shadow']=shadow(options.snapshot)
    encoded=json.dumps(report,sort_keys=True,indent=2)
    if options.output:
        root=Path(__file__).resolve().parents[2]/'.codex_structural_4_1c'
        path=options.output.resolve()
        if path.parent!=root.resolve(): raise ValueError('output must be the dedicated ignored evaluation directory')
        root.mkdir(exist_ok=True)
        path.write_text(encoded+'\n',encoding='utf-8')
    print(encoded)


if __name__=='__main__': main()
