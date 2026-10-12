"""Offline checks for optional role-span provenance and source trust boundaries."""
import copy
import atexit
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

os.environ['PYTHON_DOTENV_DISABLED'] = '1'
_temp = TemporaryDirectory(prefix='role-provenance-tests-')
atexit.register(_temp.cleanup)
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (Path(_temp.name) / 'bootstrap.sqlite').as_posix())
os.environ.setdefault('APP_ENV', 'development')
os.environ.setdefault('JWT_SECRET', 'isolated-role-provenance-test-secret')

import pytest

from services.llama_rag.knowledge import _validate_role_spans, document_record, render_context
from services.llama_rag.client import RetrievalError


def evidence():
    return {'citation_id': '1', 'source_id': '1', 'subject_source_id': '1', 'subject_title': 'Device',
            'title': 'Device', 'url': 'https://example.test/device', 'section': 'Specifications',
            'text': 'Width: 12 cm.', 'start_char': 0, 'end_char': 13, 'table_headers': [],
            'evidence_roles': ['PRIMARY'], 'core_node_ids': ['core'], 'expanded_node_ids': [],
            'evidence_role_spans': [{'node_id': 'core', 'start_char': 0, 'end_char': 13,
                                    'evidence_role': 'PRIMARY', 'evidence_role_basis': 'heading:Specifications'}]}


def test_valid_role_spans_are_diagnostic_only_and_do_not_change_prompt():
    item = evidence()
    _validate_role_spans(item)
    previous = copy.deepcopy(item)
    previous.pop('evidence_role_spans')
    _validate_role_spans(previous)
    assert render_context([item]) == render_context([previous])


@pytest.mark.parametrize('damage', [
    {'start_char': -1}, {'start_char': True}, {'end_char': 14}, {'end_char': 0},
    {'node_id': 'foreign'}, {'node_id': None}, {'evidence_role': 'REVIEW'},
    {'evidence_role': 'OFFICIAL'}, {'evidence_role': []}, {'evidence_role_basis': None},
])
def test_role_trace_cannot_claim_another_span_node_or_role(damage):
    item = evidence()
    item['evidence_role_spans'][0].update(damage)
    with pytest.raises(RetrievalError, match='evidence_role_integrity_failed'):
        _validate_role_spans(item)


@pytest.mark.parametrize('spans', [None, 'PRIMARY', [None], ['PRIMARY']])
def test_malformed_optional_trace_is_rejected(spans):
    item = evidence()
    item['evidence_role_spans'] = spans
    with pytest.raises(RetrievalError, match='evidence_role_integrity_failed'):
        _validate_role_spans(item)


def test_crawler_metadata_is_not_an_authenticated_source_role_declaration():
    doc = SimpleNamespace(id=1, title='Device', filename='Device', canonical_url=None,
        source_url='https://example.test/device', raw_text='Width: 12 cm.', version=1, crawl_id=None,
        metadata_json={'source_role': 'PRIMARY', 'author': 'official', 'trusted': True})
    record = document_record(doc)
    assert 'metadata' not in record and 'source_role' not in record
    assert record['text'] == doc.raw_text
