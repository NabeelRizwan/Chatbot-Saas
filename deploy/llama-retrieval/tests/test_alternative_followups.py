import pytest

from retrieval_engine.adaptive_evidence import routing_hints
from retrieval_engine.query_constraints import query_hints, title_is_excluded


def docs(*titles):
    return [{'source_id':str(i), 'title':title} for i,title in enumerate(titles)]


@pytest.mark.parametrize('wording', [
    'What other compact home-office products can I consider',
    'Which additional space saving options are there',
    'Show alternative portable reading choices',
    'What different travel items can I buy',
    'What other lightweight weather-resistant models are available',
    'What else could I consider for a small apartment',
    'Is there anything else suitable for a small apartment',
    'I want something else for reading',
    'What can I consider for reading',
    'What could we choose for reading',
    'What should I try for reading',
    'Recommend an option for reading',
    'Which other weather-resistant lanterns can I consider',
    'Which other lightweight backpacks could we choose',
])
def test_alternatives_do_not_become_comparisons(wording):
    catalog = docs('Aurora Travel Mug', 'Harbor Desk Mat', 'Cedar Reading Lamp')
    question = wording + ' besides Aurora Travel Mug and Harbor Desk Mat?'
    hints = routing_hints(question, catalog)
    assert not hints.comparison_source_ids
    assert hints.broad_discovery
    assert title_is_excluded(catalog[0]['title'], hints)
    assert title_is_excluded(catalog[1]['title'], hints)
    assert not title_is_excluded(catalog[2]['title'], hints)
    assert 'Aurora' not in hints.retrieval_query and 'Harbor' not in hints.retrieval_query
    assert 'reading' in hints.retrieval_query or hints.retrieval_query == wording + '?'


def test_reordered_alias_and_linked_products_are_resolved_without_dataset_names():
    catalog = docs('Aurora Lightweight Travel Mug', 'Cedar Reading Lamp', 'Harbor Desk Mat')
    linked = ['Oak Storage Cabinet', 'Garden Chair with Adjustable Back']
    q = ('What other small-apartment products can I consider besides travel Aurora mug, '
         'Harbor Desk Mat, Oak Storage Cabinet and Garden Chair with Adjustable Back?')
    hints = routing_hints(q, catalog, exclusion_titles=linked)
    assert len(hints.excluded_title_terms) == 4
    assert not hints.comparison_source_ids
    assert hints.retrieval_query == 'What other small-apartment products can I consider?'
    assert not title_is_excluded('Cedar Reading Lamp', hints)


@pytest.mark.parametrize('phrase', ['Router Pro', 'portable lamp', 'mystery lamp', 'red reading lamp'])
def test_ambiguous_or_unknown_descriptors_are_not_guessed(phrase):
    catalog = docs('Router Pro 100', 'Router Pro 200', 'Portable Lamp Green',
                   'Portable Lamp White', 'Blue Reading Lamp')
    q = 'Which other products could I consider besides ' + phrase + '?'
    hints = query_hints(q, catalog)
    assert not hints.excluded_title_terms
    assert hints.retrieval_query == q


@pytest.mark.parametrize('q', [
    'What materials does Aurora Travel Mug use besides steel?',
    'Which other properties does Aurora Travel Mug have besides warmth?',
    'What does Aurora Travel Mug support besides Harbor Desk Mat?',
    'Is Aurora Travel Mug good for anything besides travel?',
])
def test_besides_in_property_questions_is_not_an_item_exclusion(q):
    catalog = docs('Aurora Travel Mug', 'Harbor Desk Mat', 'Steel', 'Warmth', 'Travel')
    hints = query_hints(q, catalog)
    assert hints.excluded_title_terms == ()
    assert hints.retrieval_query == q


def test_list_does_not_consume_positive_comparison_in_next_clause():
    catalog = docs('Aurora Travel Mug', 'Harbor Desk Mat', 'Cedar Reading Lamp', 'Willow Floor Lamp')
    q = ('Show other compact products besides Aurora Travel Mug and Harbor Desk Mat; '
         'compare Cedar Reading Lamp and Willow Floor Lamp for reading.')
    hints = routing_hints(q, catalog)
    assert set(hints.comparison_source_ids) == {'2', '3'}
    assert 'for reading' in hints.retrieval_query
    assert not title_is_excluded('Cedar Reading Lamp', hints)
    assert not title_is_excluded('Willow Floor Lamp', hints)


def test_unknown_constraint_is_preserved_alongside_known_exclusion():
    catalog = docs('Aurora Travel Mug', 'Cedar Reading Lamp')
    q = 'Suggest other compact products besides Aurora Travel Mug and unidentified red item?'
    hints = routing_hints(q, catalog)
    assert hints.retrieval_query == q
    assert title_is_excluded('Aurora Travel Mug', hints)
    assert not title_is_excluded('Cedar Reading Lamp', hints)
    assert not hints.comparison_source_ids
