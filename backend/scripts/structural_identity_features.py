"""Phase I offline heading features/sample, deliberately no answerability rules."""
from collections import Counter,defaultdict
import hashlib

from services.structural_chunking import count_tokens
from services.structural_selection_v2 import _Selection,SelectionPolicy,heading_label


def heading_features(batch):
    engine=_Selection(batch,SelectionPolicy());rows=[]
    for c in batch.chunks:
        if c.kind!='heading':continue
        nodes=[engine.nodes[k] for k in engine.roots[c.chunk_key]]
        followers=[d for d in batch.chunks if d.kind!='heading' and any(n.identity in d.heading_path for n in nodes)]
        text='\n'.join(n.text for n in nodes);label=heading_label(text)
        parent=nodes[0].parent if len(nodes)==1 else None
        direct=[n for n in engine.nodes.values() if n.parent==parent and n.node_type.value in {'paragraph','group','list','table'}] if parent else []
        rows.append({'document_id':c.revision.source.document_id,'spec_id':c.chunk_key,
            'node_keys':[n.identity.node_key for n in nodes],'text':text,'label':label,'depth':len(c.heading_path)+1,
            'tokens':count_tokens(text),'tiny':c.token_count<50,'question':'?' in text,
            'numeric':any(ch.isdigit() for ch in text),'body_descendants':len(followers),
            'direct_body_count':len(direct),'descendant_kinds':sorted({d.kind for d in followers}),
            'complete_descendant_witness':bool(engine.heading_targets(c))})
    return rows


def freeze_sample(rows):
    """Two lowest identity hashes per independent feature stratum, unioned.

    No answerability class/outcome is an input. Covers every represented document
    and axis value; sample size is data-determined rather than cherry-picked.
    """
    counts=Counter(r['label'] for r in rows);bins=defaultdict(list)
    for r in rows:
        r=dict(r,duplicate=counts[r['label']]>1,repeated_label_count=counts[r['label']])
        axes={'document':r['document_id'],'depth':r['depth'],'length':'short' if r['tokens']<10 else ('medium' if r['tokens']<50 else 'long'),
            'duplicate':r['duplicate'],'question':r['question'],'numeric':r['numeric'],'descendants':r['body_descendants']>0,
            'commercial_proximity':'price_block' in r['descendant_kinds'],'list_proximity':'list' in r['descendant_kinds'],
            'timeline_proximity':'timeline_stage' in r['descendant_kinds'],'tiny':r['tiny'],
            'label_frequency':'once' if counts[r['label']]==1 else ('few' if counts[r['label']]<5 else 'many')}
        for axis,value in axes.items():bins[(axis,str(value))].append(r)
    chosen={};strata=[]
    for (axis,value),items in sorted(bins.items()):
        items.sort(key=lambda r:hashlib.sha256((str(r['document_id'])+':'+r['spec_id']).encode()).hexdigest())
        picks=items[:2]
        for row in picks:chosen[row['spec_id']]=row
        strata.append({'axis':axis,'value':value,'population':len(items),'sample_ids':[r['spec_id'] for r in picks]})
    return {'version':'HEADING_SAMPLE_I_V1','rule':'two lowest SHA256(document:spec) per independent stratum; union',
        'population':len(rows),'sample':sorted(chosen.values(),key=lambda r:(r['document_id'],r['spec_id'])),'strata':strata}
