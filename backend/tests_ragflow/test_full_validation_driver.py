"""Offline checks of the frozen one-shot runner; no quality queries or providers."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import pytest
from ragflow_derived.contracts import AuthorizedScope
from ragflow_dev.config import PROFILE, DIMENSION


@pytest.fixture
def driver(monkeypatch):
    folder = Path(__file__).resolve().parents[2] / 'dev' / 'ragflow'
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location('full_acceptance_test', folder / 'full_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_development_target_only(driver):
    with pytest.raises(RuntimeError, match='EXACT_DEVELOPMENT_TARGET_REQUIRED'):
        driver.BoundedClient('https://other.up.railway.app')


def test_deadline_stops_before_network_or_credentials(driver):
    client = driver.BoundedClient(driver.URL, maximum_seconds=-1)
    with pytest.raises(RuntimeError, match='VALIDATION_DEADLINE_EXCEEDED'):
        client.call('POST', '/ragflow-dev/retrieve', {'query': 'not transmitted'})


def test_expected_values_never_count_generated_text_as_original(driver):
    result = {'evidence': [{'source_id': 'one', 'text': 'Original sentence'}],
              'generated_artifacts': [{'text': 'Unsupported target'}]}
    assert driver.score(result, {'required_sources': ['one', 'two'],
                                 'required_text': ['original sentence', 'unsupported target']}) == {
        'required_source_hits': ['one'], 'required_source_count': 2,
        'support_hits': ['original sentence'], 'support_count': 2}


@pytest.mark.parametrize('change', ['scope', 'document', 'version', 'hash', 'generated', 'deleted'])
def test_advanced_evidence_fails_closed(driver, change):
    scope = AuthorizedScope('synthetic-org-a', 'synthetic-bot-a', 'native-v1', PROFILE, DIMENSION, ())
    row = {'generated': False, 'source_id': 'source', 'document_id': 'doc-source', 'version': '1',
           'generation': 'native-v1', 'scope_key': scope.key, 'text': 'Original',
           'text_sha256': hashlib.sha256(b'Original').hexdigest()}
    sources = {'source': {'document_id': 'doc-source', 'version': 1, 'state': 'ready'}}
    driver.validate_advanced({'evidence': [row]}, 'a', sources)
    if change == 'scope': row['scope_key'] = 'foreign'
    if change == 'document': row['document_id'] = 'foreign'
    if change == 'version': row['version'] = '0'
    if change == 'hash': row['text_sha256'] = 'bad'
    if change == 'generated': row['generated'] = True
    if change == 'deleted': sources['source']['state'] = 'deleted'
    with pytest.raises((AssertionError, RuntimeError)):
        driver.validate_advanced({'evidence': [row]}, 'a', sources)


def test_generated_lineage_source_version_is_validated(driver):
    scope = AuthorizedScope('synthetic-org-a', 'synthetic-bot-a', 'native-v1', PROFILE, DIMENSION, ())
    artifact = {'generated': True, 'organization_id': scope.organization_id, 'bot_id': scope.bot_id,
        'generation': scope.generation, 'scope_key': scope.key, 'source_chunk_ids': ['leaf'],
        'support_sources': [{'source_id': 'source', 'document_id': 'doc-source', 'version': '0'}]}
    with pytest.raises(AssertionError):
        driver.validate_advanced({'evidence': [], 'generated_artifacts': [artifact]}, 'a',
            {'source': {'document_id': 'doc-source', 'version': 1, 'state': 'ready'}})
