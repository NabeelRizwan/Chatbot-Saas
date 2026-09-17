"""Offline evaluator-only sidecar builder; never imported by canary retrieval.

Exact byte occurrence mapping is not semantic assignment of paraphrased GOLD
facts. Unproven field assignments stay AMBIGUOUS, with all 90 cases retained.
Prints JSON to stdout; no source, DB, provider, or GOLD mutation.
"""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.structural_descriptor_corpus import load_corpus
from services import structural_retrieval_entries_v2 as m
from services.structural_retrieval_entries import RetrievalEntryScope
from services.canary_representation import primary_routes
from services.structural_chunking import digest

ORIGINAL_GOLD_SHA='e7d0314bd79bd6279f5b404ee28a9c2211e2d0ddf0313d938e10370b3f19f5b1'


def build(root):
    folder=root/'.codex_real_corpus_v1'
    gold_file=folder/'REAL_CORPUS_V1_EVAL_V1.json'
    if hashlib.sha256(gold_file.read_bytes()).hexdigest()!=ORIGINAL_GOLD_SHA:
        raise ValueError('FROZEN_GOLD_CHANGED')
    gold=json.loads(gold_file.read_text(encoding='utf-8'))
    snapshot=json.loads((folder/'SOURCE_PRODUCTION_SNAPSHOT.json').read_text(encoding='utf-8'))
    raw={d['id']:d['raw_text'] for d in snapshot['documents']}
    chunks={c['id']:c for c in snapshot['chunks']}
    del snapshot  # includes historic vectors; never use them for this mapping
    batches,pins,_,_=load_corpus(root)
    representations={}
    for doc,batch in batches.items():
        pin=pins[doc]
        entries=m.build_retrieval_entries(batch,scope=RetrievalEntryScope(revision=pin.revision,
            crawl_id=pin.crawl_id,crawl_version=pin.crawl_version))
        representations[doc]=(entries,primary_routes(entries))
    by_id={c['id']:c for c in gold['cases']}
    rows=[]
    for case in gold['cases']:
        history=[]; previous=case.get('followup_to'); seen=set()
        while previous is not None and str(previous) in by_id and str(previous) not in seen:
            seen.add(str(previous)); parent=by_id[str(previous)]
            history.insert(0,{'id':parent['id'],'question':parent['question']})
            previous=parent.get('followup_to')
        support=[]
        for evidence in case.get('supporting_evidence',[]):
            doc=evidence['document_id']; chunk=chunks.get(evidence['chunk_id'])
            text=evidence['text']; interval=evidence['text_span']
            legacy_proven=bool(chunk and chunk['document_id']==doc and
                              chunk['content'][interval[0]:interval[1]]==text)
            location=raw.get(doc,'').find(text)
            unique=location>=0 and raw[doc].find(text,location+1)<0
            mapped=[]; source_span=None
            if unique and doc in representations:
                start=len(raw[doc][:location].encode()); end=start+len(text.encode())
                source_span=[start,end]
                batch,routes=representations[doc]
                nodes={n.identity:n for n in batch.evidence.source_graph.nodes}
                parts={p.chunk_key:p for p in batch.evidence.chunks}
                for atom in batch.atoms:
                    primary={s.mapping.node for key in atom.source_parts for s in parts[key].mappings if s.usage=='primary'}
                    intervals=[span.location.byte_range for node in sorted(primary,key=lambda n:n.node_key) for span in nodes[node].provenance.spans
                               if span.location.byte_range is not None]
                    if intervals and all(start<=r.start and r.end<=end for r in intervals):
                        mapped.append(dict(atom=atom.atom_key,route=routes[atom.atom_key],
                            node_source_spans=[[r.start,r.end] for r in intervals]))
            support.append(dict(source_document_id=doc,development_document_id=pins[doc].revision.source.document_id,
                source_pin=pins[doc].model_dump(mode='json'),legacy_chunk_id=evidence['chunk_id'],
                legacy_character_span=interval,legacy_exact=legacy_proven,evidence_text_hash=hashlib.sha256(text.encode()).hexdigest(),
                source_utf8_span=source_span,candidate_atoms=mapped,
                span_mapping='EXACT_UNIQUE_OCCURRENCE' if unique else 'COVERAGE_GAP',
                qualification_mapping='REVIEW_REQUIRED',
                note='Candidate primary spans only; this does not assign paraphrased required facts or prove companion coverage.'))
        obligations=[dict(text=f,alternative_acceptable_atom_sets=[],status='AMBIGUOUS_FIELD_ASSIGNMENT')
                     for f in case.get('required_facts',[])]
        rows.append(dict(case_id=case['id'],question_hash=hashlib.sha256(case['question'].encode()).hexdigest(),
            history_question_hash=digest(history),history_answer_hash=None,
            history_status='NO_GENERATED_HISTORY_USED',required_resources=case.get('expected_resources',[]),
            alternative_resources=case.get('acceptable_alternative_resources',[]),obligations=obligations,
            required_qualifiers=case.get('required_qualifications',[]),negative_resources=[],
            negatives_status='NOT_ANNOTATED_IN_ORIGINAL_GOLD',support=support,
            mapping_confidence='AMBIGUOUS' if obligations else 'NO_FACT_OBLIGATION',
            review_status='REQUIRES_HUMAN_FIELD_ASSOCIATION' if obligations else 'REFUSAL_OR_CLARIFICATION_REVIEW',
            refusal=bool(case.get('live_data_refusal_required') or case.get('lack_of_evidence_required'))))
    result=dict(version='canary-real-retrieval-gold-v1',original_gold_sha256=ORIGINAL_GOLD_SHA,
        implementation_hash=m._implementation_hash(),purpose='EVALUATOR_ONLY_NOT_RETRIEVER_INPUT',
        semantic_evaluation_authorized=False,
        representation_pins={str(doc):dict(batch_hash=batch.canonical_hash(),scope=batch.scope.model_dump(mode='json'))
                             for doc,(batch,_) in representations.items()},cases=rows)
    return result|{'sidecar_digest':digest(result)}


if __name__=='__main__':
    # ASCII transport avoids Windows console code-page conversion of Unicode GOLD.
    print(json.dumps(build(Path(__file__).resolve().parents[2]),ensure_ascii=True,sort_keys=True,separators=(',',':')))
