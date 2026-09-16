"""Frozen deterministic input recipes, not output-generated assertions."""
import json
from pathlib import Path

from scripts.evaluate_structural_text_adapter import parse_source
from services.structural_document import NodeAttributes, SemanticRole, StructuralDocument

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/structural_chunk_gold_v1/cases.json'


def specs():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']


def build(spec):
    shape, repeat = spec['shape'], spec['repeat']
    sentence = 'A workshop participant may use the quiet study room. '
    body = sentence * repeat
    sources = {
        'prose': '# Workshop\n\n'+body,
        'sentence': '# Workshop\n\n'+'uninterrupted '*repeat+'.',
        'list': '# Equipment\n\n'+'\n'.join('- Item '+str(i)+' includes a case and strap.' for i in range(repeat)),
        'huge_item': '# Equipment\n\n- '+body+'\n- Last item.',
        'nested_list':'# Equipment\n\n- Main kit\n  - Small pin\n  - Large pin\n- Case',
        'table':'# Rooms\n\n| Room | Capacity |\n| --- | --- |\n'+'\n'.join(f'| Room {i} | {i+2} guests |' for i in range(repeat)),
        'wide_table':'# Rooms\n\n| '+' | '.join('H'+str(i) for i in range(repeat))+' |\n| '+' | '.join('---' for _ in range(repeat))+' |\n| '+' | '.join('V'+str(i) for i in range(repeat))+' |',
        'faq':'# Workshop\n\n## How can I use the room?\n\n'+body,
        'review':'# Participant review\n\n'+body+'[Workshop](https://example.org/workshop)',
        'duplicate_headings':'# Guide\n\n## Details\n\nFirst room.\n\n## Details\n\nSecond room.',
        'repeated':'# Guide\n\nA quiet room.\n\nA quiet room.',
        'unicode':'# 世界\n\n'+'Café 👩🏽‍💻 漢字 e\u0301. '*repeat,
        'safe_link':'# Guide\n\nRead [the workshop](https://example.org/workshop#rooms) now.',
        'long_link':'# Guide\n\nRead [the workshop](https://example.org/'+('path123/'*repeat)+') now.',
        'unsafe_link':'# Guide\n\nRead [the workshop](javascript:alert) now.',
        'timeline':'# Schedule\n\n## Stage A\n\n'+body+'Results vary.\n\n## Stage B\n\nA later session may follow.',
        'warning':'# Guide\n\nPositive opening.\n\nWarning: ask the supervisor first.\n\nPositive ending.',
        'mixed':'# Guide\n\nFirst person report.\n\nUse one item daily.\n\nA general paragraph.',
        'deep':'\n\n'.join('#'*i+' Level '+str(i)+'\n\nBody '+str(i)+'.' for i in range(1,repeat+1)),
        'commercial':'# Tickets\n\nOne-time admission: $35.\n\nSubscription admission: $19 per month. Conditions apply.',
        'quantity':'# Use\n\nTake 2 capsules daily with 8 oz water. Do not exceed the stated amount.',
    }
    doc = parse_source(sources[shape])
    # These fixtures explicitly annotate roles; they do not assert C infers them.
    nodes = []
    stage = 0
    for n in doc.nodes:
        updates = {}
        if shape == 'review' and n.node_type.value == 'section':
            updates['semantic_role'] = 'review'
        if shape == 'timeline' and n.node_type.value == 'section' and n.parent and n.preorder > 2:
            stage += 1
            updates.update(semantic_role='timeline_stage', attributes=NodeAttributes.model_validate({
                'timeline': {'stage_order':stage, 'stage_label':f'Stage {stage}',
                             'qualifiers':['Results vary.'] if stage == 1 else []}}))
        if shape == 'warning' and n.text.startswith('Warning:'):
            updates['semantic_role'] = 'warning'
        if shape == 'mixed' and n.text.startswith('First person'):
            updates['semantic_role'] = 'review'
        if shape == 'mixed' and n.text.startswith('Use one'):
            updates['semantic_role'] = 'directions'
        if 'semantic_role' in updates:
            updates['semantic_role'] = SemanticRole(updates['semantic_role'])
        nodes.append(n.model_copy(update=updates))
    return StructuralDocument.model_validate_json(doc.model_copy(update={'nodes':tuple(nodes)}).canonical_json())
