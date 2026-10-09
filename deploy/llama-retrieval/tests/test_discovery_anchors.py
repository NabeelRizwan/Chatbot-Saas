import hashlib
import pytest
from llama_index.core.schema import IndexNode,TextNode
from retrieval_engine.discovery_anchors import source_anchor_nodes

def fixture():
    text='The shop sells tools and outdoor equipment.'
    node=TextNode(id_='raw',text=text,start_char_idx=0,end_char_idx=len(text),
        metadata={'source_id':'a','subject_source_id':'a','evidence_role':'UNKNOWN'})
    summary=IndexNode(index_id='a',text='Routing only',metadata={'source_id':'a',
        'discovery_only':True,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'discovery_witnesses':[{'kind':'prose','start_char':0,'end_char':len(text),'text':text}]})
    return summary,{'raw':node},{'raw':node},{'a':{'text':text}}

def test_anchor_is_original_indexed_node_not_summary():
    args=fixture()
    result=source_anchor_nodes(*args)
    assert result[0].node is args[2]['raw'] and result[0].score is None
    assert result[0].node.text!='Routing only'

def test_tampered_witness_is_rejected():
    args=fixture()
    args[0].metadata['discovery_witnesses'][0]['text']='Invented facts'
    with pytest.raises(ValueError,match='witness'): source_anchor_nodes(*args)

def test_review_cross_subject_and_unindexed_anchors_stay_out():
    args=fixture()
    args[1]['raw'].metadata['evidence_role']='REVIEW'
    assert source_anchor_nodes(*args)==[]
    args[1]['raw'].metadata.update(evidence_role='PRIMARY',subject_source_id='other')
    assert source_anchor_nodes(*args)==[]
    args[1]['raw'].metadata['subject_source_id']='a'
    args[2].clear()
    assert source_anchor_nodes(*args)==[]


def test_overview_roundrobin_is_bounded_and_cannot_inject_unscored_summary():
    from retrieval_engine.discovery_anchors import retain_overview_descriptions
    from llama_index.core.schema import NodeWithScore
    rows=[NodeWithScore(node=TextNode(id_=str(i),text='Exact original passage'),score=float(i)) for i in range(6)]
    result=retain_overview_descriptions(rows,rows[::-1],{'one':['0','1','summary'],'two':['2','3']},5)
    assert [r.node.node_id for r in result]==['0','2','1','3','5']
    assert result[0] is rows[0] and result[0].score==0
