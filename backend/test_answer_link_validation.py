"""Destination validation preserves CommonMark boundaries and source identity."""
import pytest

from services import rag_service
from services.llama_rag.streaming import EvidenceStream


@pytest.fixture
def validate(monkeypatch):
    def run(answer, trusted=('https://example.test/manual.pdf',)):
        monkeypatch.setattr(rag_service, '_format_sources', lambda _: [
            {'source_url': url, 'cta_links': []} for url in trusted])
        return rag_service._validate_answer_links(answer, [])
    return run


@pytest.mark.parametrize('answer,url', [
    ('Read (including [manual](https://example.test/manual.pdf)).', 'https://example.test/manual.pdf'),
    ('Read [manual](https://example.test/manual.pdf "Detailed instructions").', 'https://example.test/manual.pdf'),
    ('Read [manual](<https://example.test/manual.pdf>).', 'https://example.test/manual.pdf'),
    ('Read [manual](https://example.test/manual(v2).pdf).', 'https://example.test/manual(v2).pdf'),
    (r'Read [manual](https://example.test/manual\(v2\).pdf).', 'https://example.test/manual(v2).pdf'),
    ('Read [manual [edition]](https://example.test/manual.pdf).', 'https://example.test/manual.pdf'),
    ('Read ![diagram](https://example.test/manual.pdf).', 'https://example.test/manual.pdf'),
    ('Read <https://example.test/manual(v2).pdf>.', 'https://example.test/manual(v2).pdf'),
    ('Read https://example.test/manual(v2).pdf.', 'https://example.test/manual(v2).pdf'),
    ('Read (https://example.test/manual.pdf).', 'https://example.test/manual.pdf'),
    ('Read [manual][ref].\n\n[ref]: https://example.test/manual.pdf "Instructions"', 'https://example.test/manual.pdf'),
    ('Read [manual][ref].\n\n[ref]:\n  <https://example.test/manual.pdf>', 'https://example.test/manual.pdf'),
    ('Read [manual].\n\n[manual]: https://example.test/manual.pdf', 'https://example.test/manual.pdf'),
    ('Read [manual](https://example.test/book?a=1&amp;b=2).', 'https://example.test/book?a=1&b=2'),
    ('Read https://example.test/trailing.', 'https://example.test/trailing.'),
])
def test_trusted_destinations_preserve_all_original_prose_and_formatting(validate, answer, url):
    assert validate(answer, (url,)) == answer


@pytest.mark.parametrize('answer', [
    '[manual](https://foreign.test/manual.pdf)',
    '[manual](https://example.test/manual.pdf?size=large)',
    '[manual](https://name:secret@example.test/manual.pdf)',
    '[manual](https://example.test.evil/manual.pdf)',
    '[manual](http://example.test/manual.pdf)',
    '[manual](javascript:alert(1))',
    '[manual](//foreign.test/manual.pdf)',
    '[manual](https://example.test/items/../manual.pdf)',
    '<https://foreign.test/manual.pdf>',
    '[manual][ref].\n\n[ref]: https://foreign.test/manual.pdf',
    '[manual][ref].\n\n[ref]: /other.pdf',
])
def test_untrusted_destinations_are_removed_without_losing_customer_claim(validate, answer):
    result = validate('The warranty is two years. ' + answer)
    assert result.startswith('The warranty is two years. ')
    for value in ('foreign.test', '?size=large', 'secret@', 'example.test.evil',
                  'http://example.test', 'javascript:', '/items/../', '/other.pdf'):
        assert value not in result


def test_unique_variant_changes_only_destination(validate):
    assert validate('Read (including [manual](/manual.pdf "Instructions")).') == (
        'Read (including [manual](https://example.test/manual.pdf "Instructions")).')


@pytest.mark.parametrize('answer', [
    'Example `https://foreign.test/manual.pdf` is literal code.',
    'Example:\n\n    [manual](https://foreign.test/manual.pdf)\n\nEnd.',
    'Example:\n\n```text\nhttps://foreign.test/manual.pdf\n```\n\nEnd.',
    '>     https://foreign.test/manual.pdf\n',
])
def test_literal_code_is_not_a_navigation_destination(validate, answer):
    assert validate(answer) == answer


def test_code_cannot_hide_active_destination_across_paragraph_boundary(validate):
    answer = '`not closed\n\nhttps://foreign.test/manual.pdf\n\nend`'
    assert 'foreign.test' not in validate(answer)


@pytest.mark.parametrize('answer', [
    'First paragraph.\n\nRead (including [manual](https://example.test/manual.pdf)).\n\nEnd.',
    'Read [manual][ref].\n\n[ref]: https://example.test/manual.pdf\n\nEnd.',
    'Read [manual][ref].\n\n[ref]: https://foreign.test/manual.pdf\n\nEnd.',
    'Example `https://foreign.test/manual.pdf`.\n\nReal <https://example.test/manual.pdf>.',
    '`not closed\n\nhttps://foreign.test/manual.pdf\n\nend`',
])
def test_all_stream_boundaries_match_final_validation(validate, answer):
    final = validate(answer)
    for boundary in range(len(answer) + 1):
        out = []
        stream = EvidenceStream(out.append, validate, lambda: None)
        stream.feed(answer[:boundary])
        stream.feed(answer[boundary:])
        stream.finish(final)
        assert ''.join(out) == final
