"""Light structural/contract tests only; no models, APIs, or corpus fixtures."""
import ast
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest

from rag2.context_supplement import supplement_context, render_item


def encode(text):
    # Deliberately simple deterministic test tokenizer; real cost must use the
    # same context tokenizer as the service during replay.
    return text.split()


def node(node_id, source, text, start, end, *, section=None, subject=None, role='PRIMARY'):
    section = section or (0, len(text))
    return SimpleNamespace(node_id=node_id, text=text[start:end], start_char_idx=start,
                           end_char_idx=end, metadata={'source_id': source,
                           'subject_source_id': subject or source, 'subject_title': source,
                           'url': 'https://example.test/' + source, 'section': 'Specification',
                           'section_start_char_idx': section[0], 'section_end_char_idx': section[1],
                           'evidence_role': role, 'evidence_role_basis': 'heading:Specification'})


def scored(raw, score=1):
    return SimpleNamespace(node=deepcopy(raw), score=score)


def document(source, text):
    return {'title': source, 'text': text, 'url': 'https://example.test/' + source}


def empty():
    return {'context': '', 'evidence': [], 'audit': {}, 'context_tokens': 0}


def existing(source, text):
    item = {'citation_id': '1', 'node_id': 'context-original', 'source_id': source,
            'subject_source_id': source, 'subject_title': source, 'title': source,
            'url': 'https://example.test/' + source, 'section': 'Old section',
            'text': text, 'start_char': 0, 'end_char': len(text), 'score': 9,
            'source_sha256': sha256(text.encode()).hexdigest(),
            'core_node_ids': ['old'], 'expanded_node_ids': [], 'sections': ['Old section'],
            'table_headers': [], 'evidence_roles': ['PRIMARY'],
            'evidence_role_spans': [{'start_char': 0, 'end_char': len(text), 'node_id': 'old',
                                    'evidence_role': 'PRIMARY', 'evidence_role_basis': 'old'}]}
    return {'context': render_item(item), 'evidence': [item], 'audit': {'unchanged': True}}
