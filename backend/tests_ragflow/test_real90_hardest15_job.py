"""Offline safety checks only; never execute a benchmark/provider question."""
import copy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

from .fixtures import TokenizerDouble, scope
from .test_answer_quality_job import FakeAuthorityClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/ragflow'))
try:
    spec = importlib.util.spec_from_file_location('real90_job', ROOT / 'dev/ragflow/real90_hardest15_once.py')
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
finally:
    sys.path.pop(0)


def test_exact_selection_modes_history_and_gold_separation():
    execution, corpus, _ = job.load_inputs()
    selected_raw = (ROOT / 'docs/RAGFLOW_REAL90_HARDEST15_SELECTION.json').read_bytes()
    selected = json.loads(selected_raw)
    assert job.digest(selected_raw) == execution['selection_sha256']
    assert [q['id'] for q in execution['questions']] == [q['id'] for q in selected['questions']]
    assert sum(q['mode'] == 'normal' for q in execution['questions']) == 2
    for q, expected in zip(execution['questions'], selected['questions']):
        assert q['question'] == expected['question']
        assert q['history'] == expected['history']
        assert q['mode'] == expected['mode']
        assert expected['historical_result'] == 'FAIL'
        assert expected['checklist']
    assert len(corpus['documents']) == 23
    assert sum(len(d['chunks']) for d in corpus['documents']) == 1092


def test_every_imported_chunk_stays_exact_without_parsing():
    from ragflow_derived.contracts import AuthorizedScope, SourceRef
    _, corpus, _ = job.load_inputs()
    s = AuthorizedScope('offline-org', 'offline-bot', 'v1', 'offline', 64,
        tuple(SourceRef(d['source'], d['id'], d['version']) for d in corpus['documents']))
    engine = SimpleNamespace(tokenizer=TokenizerDouble())
    for doc in corpus['documents']:
        rows = job.chunk_rows(engine, s, doc)
        assert len(rows) == len(doc['chunks'])
        for original, row in zip(doc['chunks'], rows):
            assert row['content_with_weight'] == original['text']
            assert row['content_sha_kwd'] == original['sha256']
            assert row['chunk_order_int'] == original['order']
            assert json.loads(row['structure_kwd']) == original['headings']
            assert row['doc_id'] == doc['id']
            assert row['url_kwd'] == doc['url']
            assert 'meta_fields_kwd' not in row
            assert 'important_kwd' not in row
            assert 'question_kwd' not in row


@pytest.mark.parametrize('change', ['organization_id', 'bot_id', 'generation', 'sources', 'revoke'])
def test_create_only_authority_and_foreign_scope_refusal(change):
    client, s = FakeAuthorityClient(), scope()
    auth = job.Authority(client, s, 'corpus')
    assert auth.authorized(s)
    if change == 'revoke':
        client.documents[job.MARKER]['state'] = 'revoked'
        other = s
    else:
        other = replace(s, **{change: () if change == 'sources' else 'foreign'})
    assert not auth.authorized(other)
    with pytest.raises(RuntimeError, match='conflict'):
        job.Authority(client, s, 'corpus')


def test_close_prevents_rerun():
    client, s = FakeAuthorityClient(), scope()
    auth = job.Authority(client, s, 'corpus')
    auth.finish()
    assert not auth.authorized(s)
    assert client.documents[job.MARKER]['state'] == 'closed_no_rerun'


def test_complete_observer_returns_identical_candidates_and_scores(monkeypatch):
    from ragflow_dev.runtime import TracedBackend
    from ragflow_derived.upstream.doc_store import OrderByExpr
    s = scope()
    doc = {'source': s.sources[0].source_id, 'title': 'Offline document', 'url': 'https://example.test/doc',
        'source_sha256': 'source', 'chunks': [{'order': 0, 'text': 'Exact test text',
            'sha256': job.digest('Exact test text'), 'headings': []}]}
    row = job.chunk_rows(SimpleNamespace(tokenizer=TokenizerDouble()), s, doc)[0]
    response = {'hits': {'total': {'value': 1}, 'hits': [{'_id': row['id'], '_source': row, '_score': 0.8123}]}}
    before = copy.deepcopy(response)
    def search(self, *args, **kw):
        self.trace.append({'hits': [], 'expressions': []})
        return response
    monkeypatch.setattr(TracedBackend, 'search', search)
    monkeypatch.setattr(TracedBackend, 'ready_sources', lambda self, scope: {x.key for x in scope.sources})
    trace = []
    backend = job.traced_backend(SimpleNamespace(), trace, s, lambda other: other == s)
    actual = backend.search([], [], {}, [], OrderByExpr(), 0, 64, [s.index], [s.bot_id])
    assert actual is response and actual == before
    assert trace[-1]['scope_verified'] and trace[-1]['candidate_count'] == 1
    response['hits']['hits'][0]['_source']['doc_id'] = 'foreign'
    with pytest.raises(Exception, match='UNAUTHORIZED_SCOPE'):
        backend.search([], [], {}, [], OrderByExpr(), 0, 64, [s.index], [s.bot_id])


def test_execution_code_has_no_gold_or_quality_overrides():
    code = Path(job.__file__).read_text()
    assert code.count('engine.research(') == 1
    assert "messages=q['history']" in code
    assert 'document_ids=' not in code
    assert 'EngineConfig(' not in code.replace('asdict(EngineConfig())', '')
    assert 'required_facts' not in code
    assert 'supporting_evidence' not in code
    assert 'selection.json' not in code
    assert 'Gemini' not in code
    assert '20' in code
    assert 'parse(' not in code


def test_frozen_runtime_and_harness_hashes():
    job.verify_files(ROOT, json.loads(job.FREEZE.read_text()))
