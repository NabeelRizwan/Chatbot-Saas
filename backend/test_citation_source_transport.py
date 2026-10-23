"""Generic, offline citation URL and selected-sidecar transport regressions."""

from types import SimpleNamespace

import pytest

# Reuse only the isolated test environment, never live application data.
import test_llama_rag as support
from routes.public_routes import _public_stream_sources
from schemas.schemas import ChatSourceResponse, PublicChatResponse
from services.conversational_engine import _source_reference_url, admitted_reference_links
from services.rag_service import _format_sources
from services.source_urls import safe_source_url


@pytest.mark.parametrize('url', [
    'https://retail.example/products/desk', 'http://docs.example/guide',
    'HTTPS://DOCS.EXAMPLE/Manual', 'https://example.test:8443/path?q=blue#sizes',
    'https://example.test/caf%C3%A9', 'https://example.test/日本語',
    'https://[2001:db8::1]/guide',
])
def test_safe_navigation_preserves_exact_destination(url):
    assert safe_source_url(url) == url


@pytest.mark.parametrize('url', [
    None, 19, '', '//example.test/guide', '/guide', 'file:///private/report.pdf',
    'document://7', 'javascript:alert(1)', 'data:text/html,hello',
    'https://user:secret@example.test/guide', 'https://user@example.test/guide',
    'https://@example.test/guide', 'https://:secret@example.test/guide',
    'https://example.test\\@other.test/guide', 'https://example.test/a\\b',
    'https://example.test/line\nbreak', '\nhttps://example.test/guide',
    'https://exam\tple.test/guide', 'https://example.test/space here',
    ' https://example.test/guide', 'https://example.test/guide ',
    'https://example.test/\x00value', 'https://example.test/\x7fvalue',
    'https://example.test/\x85value', 'https://example.test:99999/guide',
    'https://example.test:invalid/guide', 'https://[invalid]/guide',
    'https:///guide', 'https://example.test/' + 'a' * 2048,
])
def test_unsafe_or_nonpublic_destinations_are_never_repaired(url):
    assert safe_source_url(url) is None


def item(*, canonical=None, source='https://example.test/original', metadata=None, text='Instructions.'):
    document = SimpleNamespace(id=7, filename='Operations guide.pdf', title='Operations guide',
        source_type='pdf', source_url=source, canonical_url=canonical, metadata_json={})
    chunk = SimpleNamespace(chunk_index=0, content=text, metadata_json=metadata or {})
    return {'document': document, 'chunk': chunk}


def test_formatter_retains_canonical_priority_and_does_not_invent_upload_links():
    row = item(canonical='https://example.test/canonical',
        metadata={'canonical_url': 'https://example.test/metadata'})
    assert _format_sources([row])[0]['source_url'] == 'https://example.test/canonical'
    row['document'].canonical_url = None
    assert _format_sources([row])[0]['source_url'] == 'https://example.test/metadata'
    row['chunk'].metadata_json = {}
    assert _format_sources([row])[0]['source_url'] == 'https://example.test/original'
    row['document'].canonical_url = 'https://secret@example.test/private'
    # Unsafe higher-priority identity is not silently replaced by a different page.
    assert _format_sources([row])[0]['source_url'] is None
    row = item(source=None)
    source = _format_sources([row])[0]
    assert source['source_url'] is None and source['title'] == 'Operations guide'
    assert 'attribution_scope' not in source


def test_formatter_uses_same_url_policy_for_headings_metadata_and_admitted_links():
    bad = 'https://secret@example.test/private'
    safe = 'https://example.test/operations-guide'
    row = item(text=f'## [Operations guide]({bad})\nInstructions.', metadata={
        'cta_links': [{'label': 'Operations guide', 'url': bad},
                      {'label': 'Operations guide', 'url': safe}]})
    row['context_field_evidence'] = {'policy': [f'Read [secret terms]({bad}).']}
    source = _format_sources([row])[0]
    assert source['cta_links'] == [{'label': 'Operations guide', 'url': safe}]


@pytest.mark.parametrize('url', [
    'https://example.test/terms?token=private', 'https://example.test/terms#private',
    'https://another.example/terms', 'http://example.test/terms',
    'https://example.test/terms\\private', 'https://example.test/ter\tms',
    'https://@example.test/terms',
])
def test_admitted_references_keep_unsigned_same_origin_boundary(url):
    row = item()
    assert _source_reference_url(url, row['document']) is None
    row['context_field_evidence'] = {'policy': [f'Read [terms]({url}).']}
    assert admitted_reference_links(row) == []


def test_literal_same_origin_reference_remains_available():
    row = item()
    url = 'https://example.test/terms'
    row['context_field_evidence'] = {'policy': [f'Read [terms]({url}).']}
    assert admitted_reference_links(row) == [{'label': 'terms', 'url': url}]


def test_public_sidecar_keeps_exact_selected_marker_without_internal_evidence():
    source = _format_sources([item()])[0]
    source.update(attribution_scope='selected', private_quote='internal evidence')
    public = _public_stream_sources([source])[0]
    assert public['attribution_scope'] == 'selected'
    assert public['source_url'] == source['source_url']
    assert not {'document_id', 'chunk_refs', 'private_quote'} & public.keys()
    serialized = PublicChatResponse(reply='Saved answer.', sources=[source]).model_dump()
    assert serialized['sources'][0]['attribution_scope'] == 'selected'


def test_unmarked_candidates_do_not_gain_selected_authority():
    source = _format_sources([item()])[0]
    assert 'attribution_scope' not in source
    assert 'attribution_scope' not in _public_stream_sources([source])[0]
    assert ChatSourceResponse.model_validate(source).attribution_scope is None
    source['attribution_scope'] = 'candidate'
    assert 'attribution_scope' not in _public_stream_sources([source])[0]


def test_selected_document_without_public_url_is_a_label_not_an_invented_link():
    source = _format_sources([item(source='file:///private/Operations.pdf')])[0]
    assert _public_stream_sources([source]) == []
    source['attribution_scope'] = 'selected'
    assert _public_stream_sources([source]) == [{
        'title': 'Operations guide', 'source_url': None, 'source_type': 'pdf',
        'cta_links': [], 'attribution_scope': 'selected'}]


def test_public_unsafe_destinations_cannot_be_reenabled_by_selected_marker():
    source = {'title': 'Operations guide', 'source_url': 'https://user:secret@example.test/guide',
        'attribution_scope': 'selected', 'cta_links': [
            {'label': 'bad', 'url': 'https://example.test\\@other.test/'},
            {'label': 'safe', 'url': 'https://example.test/guide'},
            {'label': 'duplicate', 'url': 'https://example.test/guide'}]}
    public = _public_stream_sources([source])[0]
    assert public['source_url'] is None
    assert public['cta_links'] == [{'label': 'safe', 'url': 'https://example.test/guide'}]


@pytest.fixture
def rag2_case():
    from test_rag2_source_map import SourceMapIntegrationTests
    case = SourceMapIntegrationTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()
        case.doCleanups()


def test_only_decoded_selected_rag2_references_receive_marker(rag2_case):
    result, _, _, _, _ = rag2_case.exercise()
    assert result[1] and all(s['attribution_scope'] == 'selected' for s in result[1])
    assert _public_stream_sources(result[1])[0]['attribution_scope'] == 'selected'
    invalid, _, _, _, _ = rag2_case.exercise(invalid=True)
    assert invalid[1] == []


def test_other_rag2_model_selected_sidecar_is_marked_without_changing_prompt(rag2_case):
    result, trace, _, _, _ = rag2_case.exercise(model='configured-model')
    assert result[0] == 'Existing answer.'
    assert result[1][0]['attribution_scope'] == 'selected'
    assert trace.diagnostics['answer_contract']['answer_method'] == 'existing'
