import pytest

from retrieval_engine.query_constraints import (explicit_query_aspects, focused_query,
                                   query_hints, title_is_excluded)

DOCS = [
    {'source_id':'a','title':'Trail Runner Lightweight Shoes'},
    {'source_id':'b','title':'City Walker'},
    {'source_id':'c','title':'Walking Shoes'},
    {'source_id':'d','title':'Soft Sandals'},
]


@pytest.mark.parametrize('question,expected', [
    ('Compare Router Pro 100 and Beacon Switch.', {'a','c'}),
    ('Compare Router Pro 100 and Router Pro 200.', {'a','b'}),
    ('Compare Router Pro 100 and Beacon Switch for 200 clients.', {'a','c'}),
    ('Compare Router Pro and Beacon Switch.', set()),
])
def test_numeric_model_variants_do_not_alias_each_other(question,expected):
    docs=[{'source_id':'a','title':'Router Pro 100'},
          {'source_id':'b','title':'Router Pro 200'},
          {'source_id':'c','title':'Beacon Switch'}]
    assert set(query_hints(question,docs).comparison_source_ids)==expected


def test_unique_numeric_title_can_keep_unambiguous_short_alias():
    docs=[{'source_id':'a','title':'Beacon Omega 3 Lamp'},
          {'source_id':'b','title':'Trail Light'}]
    assert set(query_hints('Compare Beacon Omega and Trail Light.',docs).comparison_source_ids)=={'a','b'}


def test_comparison_titles_come_from_corpus():
    hints = query_hints('Compare Trail Runner and City Walker for rainy days.', DOCS)
    assert set(hints.comparison_source_ids) == {'a','b'}


def test_generic_query_never_becomes_single_title_scope():
    assert not query_hints('walking shoes products?', DOCS).comparison_source_ids


def test_exclusion_only_matches_title_vocabulary():
    hints = query_hints('Which options work for travel without being sandals?', DOCS)
    assert hints.excluded_title_terms == ('sandals',)
    assert 'sandals' not in hints.retrieval_query
    assert title_is_excluded('Soft Sandals', hints)
    assert not title_is_excluded('City Walker', hints)


def test_recognized_no_term_for_me_removes_the_entire_exclusion_phrase():
    question = 'No sandals for me: compare Trail Runner and City Walker on materials and care.'
    hints = query_hints(question, DOCS)
    assert hints.excluded_title_terms == ('sandals',)
    assert hints.retrieval_query == 'compare Trail Runner and City Walker on materials and care.'
    assert set(hints.comparison_source_ids) == {'a', 'b'}
    assert explicit_query_aspects(hints.retrieval_query, [DOCS[0]['title'], DOCS[1]['title']]) == ('materials', 'care')
    assert question.startswith('No sandals for me:')


@pytest.mark.parametrize('question', [
    'No wool for me: compare Trail Runner and City Walker on materials and care.',
    'No unknownmaterial, compare Trail Runner and City Walker.',
    'No sandals for men in this list?',
    'No sandals for meadows in this list?',
])
def test_unrecognized_or_unmatched_exclusions_remain_intact(question):
    hints = query_hints(question, DOCS)
    assert not hints.excluded_title_terms
    assert hints.retrieval_query == question


def test_does_not_infer_unstated_attribute_absence():
    hints = query_hints('Can I use these without wool?', DOCS)
    assert not hints.excluded_title_terms
    assert hints.retrieval_query == 'Can I use these without wool?'


def test_no_guarantee_question_not_misread_as_filter():
    assert not query_hints('Is there no guaranteed delivery date?', DOCS).excluded_title_terms


def test_property_question_does_not_filter_its_own_subject():
    docs = [{'source_id':'a','title':'Gluten Free Bread'}, {'source_id':'b','title':'Bread'}]
    hints = query_hints('Which bread is without gluten?', docs)
    assert not hints.excluded_title_terms
    hints = query_hints('Avoid gluten for me', docs)
    assert not title_is_excluded('Gluten Free Bread', hints)


def test_substrings_are_not_document_entities():
    docs = [{'source_id':'a','title':'Air'}, {'source_id':'b','title':'Pro'},
            {'source_id':'c','title':'Repair Policy'}]
    assert not query_hints('Compare repairs and protection plans.', docs).comparison_source_ids


def test_generic_collection_name_is_not_a_compared_item():
    docs = [{'source_id':'a','title':'Joint Support'}, {'source_id':'b','title':'Joint Supplements'},
            {'source_id':'c','title':'Motion Balance'}]
    assert set(query_hints('Compare Joint Support and Motion Balance.', docs).comparison_source_ids) == {'a','c'}


def test_focused_query_preserves_title_word_used_as_requested_property():
    titles = ['Micro SD Adapter', 'Device Pro']
    result = focused_query('Compare Micro SD Adapter and Device Pro on SD compatibility and daily use.', titles[0], titles)
    assert result == 'Micro SD Adapter. on SD compatibility and daily use.'


def test_focused_query_removes_one_name_mention_not_later_property_reference():
    titles = ['Basic Kit', 'Deluxe Kit']
    result = focused_query('Compare Basic Kit and Deluxe Kit on Basic Kit compatibility.', titles[1], titles)
    assert result == 'Deluxe Kit. on Basic Kit compatibility.'


def test_focused_query_preserves_property_conjunctions_and_exclusions():
    titles = ['Micro SD Adapter', 'Device Pro']
    result = focused_query('No batteries for me: compare Micro SD Adapter and Device Pro on SD compatibility or daily use without tools.', titles[0], titles)
    assert 'No batteries for me' in result
    assert 'SD compatibility or daily use without tools' in result
    assert 'Device Pro' not in result


def test_focused_query_longest_literal_shortened_names():
    titles = ['Portable Display Monitor', 'Travel Panel Screen']
    result = focused_query('Compare Portable Display and Travel Panel on display quality and panel weight.', titles[0], titles)
    assert result == 'Portable Display Monitor. on display quality and panel weight.'


def test_focused_query_prefers_name_alias_before_properties_to_full_title_after():
    titles = ['Micro SD Adapter', 'Device Pro']
    result = focused_query('Compare Micro SD and Device Pro on Micro SD Adapter compatibility.', titles[0], titles)
    assert result == 'Micro SD Adapter. on Micro SD Adapter compatibility.'


def test_focused_query_preserves_uncertain_shared_alias():
    titles = ['Basic Kit', 'Deluxe Kit']
    question = 'Compare kit compatibility and durability.'
    assert focused_query(question, titles[0], titles) == f'{titles[0]}. {question}'


def test_focused_query_preserves_substrings_and_predicates():
    question = 'Compare repairs and protection plans.'
    result = focused_query(question, 'Air', ['Air', 'Pro'])
    assert result == f'Air. {question}'


def test_focused_query_handles_preposition_inside_product_title():
    titles = ['Kit for Travel', 'Kit for Studio']
    result = focused_query('Compare Kit for Travel and Kit for Studio on travel compatibility.', titles[0], titles)
    assert result == 'Kit for Travel. on travel compatibility.'


def test_focused_query_does_not_remove_predicate_between_named_products():
    titles = ['Basic Kit', 'Deluxe Kit']
    result = focused_query('Is Basic Kit compatible with Deluxe Kit?', titles[0], titles)
    assert 'compatible with' in result


def test_focused_query_handles_with_connector_and_articles():
    titles = ['City Coat', 'Trail Coat']
    result = focused_query('Compare the City Coat with the Trail Coat on fabric and care.', titles[0], titles)
    assert result == 'City Coat. on fabric and care.'


@pytest.mark.parametrize(('question', 'titles', 'expected'), [
    ('Compare Micro SD Adapter and Device Pro on dimensions, materials and daily use.',
     ['Micro SD Adapter', 'Device Pro'], ('dimensions', 'materials', 'daily use')),
    ('How are Basic Kit and Deluxe Kit different in form and use?',
     ['Basic Kit', 'Deluxe Kit'], ('form', 'use')),
    ('Please compare Basic Kit and Deluxe Kit by Dimensions, Materials, and Daily Use.',
     ['Basic Kit', 'Deluxe Kit'], ('Dimensions', 'Materials', 'Daily Use')),
    ('Could you compare Basic Kit and Deluxe Kit for maintenance costs and repair options?',
     ['Basic Kit', 'Deluxe Kit'], ('maintenance costs', 'repair options')),
    ('How do Basic Kit and Deluxe Kit differ in size and weight?',
     ['Basic Kit', 'Deluxe Kit'], ('size', 'weight')),
    ('What is the difference between Basic Kit and Deluxe Kit in size and weight?',
     ['Basic Kit', 'Deluxe Kit'], ('size', 'weight')),
    ('Basic Kit versus Deluxe Kit on size and weight?',
     ['Basic Kit', 'Deluxe Kit'], ('size', 'weight')),
    ('Compare Tools and Parts Kit and Travel Kit on size and weight.',
     ['Tools and Parts Kit', 'Travel Kit'], ('size', 'weight')),
    ('Compare Kit for Travel and Kit for Studio on size and weight.',
     ['Kit for Travel', 'Kit for Studio'], ('size', 'weight')),
    ('Compare Do Not Disturb Lamp and Reading Lamp on dimensions and materials.',
     ['Do Not Disturb Lamp', 'Reading Lamp'], ('dimensions', 'materials')),
    ('Compare Portable Display and Travel Panel on display quality and panel weight.',
     ['Portable Display Monitor', 'Travel Panel Screen'], ('display quality', 'panel weight')),
    ('Compare City Coat with Trail Coat on size, fabric and care.',
     ['City Coat', 'Trail Coat'], ('size', 'fabric', 'care')),
    ('How are the lightweight tent and Family Tent different in form and use?',
     ['Lightweight Tent Solo Shelter', 'Family Tent'], ('form', 'use')),
    ('Compare the City Coat with the Trail Coat on fabric and care.',
     ['City Coat', 'Trail Coat'], ('fabric', 'care')),
])
def test_explicit_property_lists_are_literal(question, titles, expected):
    assert explicit_query_aspects(question, titles) == expected


@pytest.mark.parametrize('question', [
    'What are the dimensions and materials of Basic Kit?',
    'Basic Kit and Deluxe Kit are available in red and blue.',
    'Compare Basic Kit and Deluxe Kit on durability.',
    'Compare Basic Kit and Deluxe Kit on dimensions, materials, use and storage.',
    'Compare Basic Kit and Deluxe Kit on whether it fits and whether it lasts.',
    'Compare Basic Kit and Deluxe Kit on size and use without batteries.',
    'No batteries please: compare Basic Kit and Deluxe Kit on size and weight.',
    'Compare Basic Kit and Deluxe Kit only on size and weight.',
    'Compare Basic Kit and Deluxe Kit on size or weight.',
    'Compare Basic Kit and Deluxe Kit on size and weight if they fit.',
    'Compare Basic Kit and Deluxe Kit on size, which includes cables, and weight.',
    'Which is better, Basic Kit or Deluxe Kit, for size and durability?',
    'Compare Basic Kit and Deluxe Kit on form and use; also tell me shipping.',
    'Compare Basic Kit and Deluxe Kit on size and Size.',
    'Compare Basic Kit and Deluxe Kit on size and.',
    'Compare Basic Kit and Deluxe Kit on size and weight for my backpack.',
    'Compare Basic Kit and Deluxe Kit on durability and whether I can wash them.',
])
def test_unsafe_or_ambiguous_property_lists_keep_full_task(question):
    assert explicit_query_aspects(question, ['Basic Kit', 'Deluxe Kit']) == ()


def test_property_split_requires_two_distinct_named_subjects():
    question = 'Compare Basic Kit and Deluxe Kit on size and weight.'
    assert explicit_query_aspects(question, ['Basic Kit']) == ()
    assert explicit_query_aspects(question, ['Basic Kit', 'Basic Kit']) == ()
    assert explicit_query_aspects(question, ['Basic Kit', 'Missing Product']) == ()


def test_property_split_preserves_requested_negation_outside_entity_span():
    question = "Compare Basic Kit and Deluxe Kit on materials and maintenance that doesn't need tools."
    assert explicit_query_aspects(question, ['Basic Kit', 'Deluxe Kit']) == ()


FORM_DOCS = [
    {'source_id':'a','title':'Fruit Gummies'},
    {'source_id':'b','title':'Cocoa Powder'},
    {'source_id':'c','title':'Plain Capsules'},
    {'source_id':'d','title':'Soft Sandals'},
    {'source_id':'e','title':'Walking Shoes'},
    {'source_id':'f','title':'Travel Capsule Kit'},
]


@pytest.mark.parametrize('negative', [
    'I do not want gummies or drink powders.',
    "I don't want gummies and drink powders.",
    'I don’t want gummies, drink powders.',
    'Exclude gummies, or drink powders.',
    'Avoid gummies, and drink powders.',
    'No gummies or drink powders for me.',
])
def test_coordinated_exclusions_are_removed_as_one_complete_clause(negative):
    hints=query_hints('Which options are available? '+negative,FORM_DOCS)
    assert hints.excluded_title_terms == ('gummies','powder')
    assert hints.retrieval_query == 'Which options are available?'
    assert title_is_excluded('Fruit Gummies',hints)
    assert title_is_excluded('Cocoa Powder',hints)
    assert not title_is_excluded('Plain Capsules',hints)


def test_three_item_comma_list_and_regular_plural_aliases():
    hints=query_hints('Suggest options. I do not want gummy, powders, or capsules.',FORM_DOCS)
    assert hints.excluded_title_terms == ('gummies','powder','capsules')
    assert hints.retrieval_query == 'Suggest options.'
    assert title_is_excluded('Travel Capsule Kit',hints)
    assert title_is_excluded('Plain Capsules',hints)


@pytest.mark.parametrize('question,excluded,retained', [
    ('I do not want gummies or powders, but I prefer capsules.',('gummies','powder'),'I prefer capsules.'),
    ('I do not want gummies and powders; recommend capsules.',('gummies','powder'),'recommend capsules.'),
    ('No gummies, compare Cocoa Powder and Plain Capsules.',('gummies',),'compare Cocoa Powder and Plain Capsules.'),
    ('Not gummies but capsules for travel.',('gummies',),'capsules for travel.'),
    ('Avoid gummies and recommend capsules.',('gummies',),'recommend capsules.'),
    ('No gummies or powders for me: show capsules.',('gummies','powder'),'show capsules.'),
])
def test_exclusions_stop_before_positive_clauses(question,excluded,retained):
    hints=query_hints(question,FORM_DOCS)
    assert hints.excluded_title_terms == excluded
    assert hints.retrieval_query == retained
    assert not title_is_excluded('Plain Capsules',hints)


def test_exclusion_does_not_bleed_across_a_sentence_boundary():
    hints=query_hints('Show options. Avoid gummies. Cocoa Powder interests me.',FORM_DOCS)
    assert hints.excluded_title_terms == ('gummies',)
    assert hints.retrieval_query == 'Show options. Cocoa Powder interests me.'
    assert not title_is_excluded('Cocoa Powder',hints)


def test_unknown_coordinated_item_preserves_the_complete_negative_text():
    question='Suggest options. I do not want gummies or mystery fibre.'
    hints=query_hints(question,FORM_DOCS)
    assert hints.excluded_title_terms == ('gummies',)
    assert hints.retrieval_query == question


def test_descriptive_constraint_is_not_mistaken_for_a_noun_list():
    question='Suggest options. I do not want gummies or capsules that are blue.'
    hints=query_hints(question,FORM_DOCS)
    assert hints.excluded_title_terms == ('gummies',)
    assert hints.retrieval_query == question
    assert not title_is_excluded('Plain Capsules',hints)


def test_repeated_no_in_coordinated_list_does_not_leave_dangling_conjunction():
    hints=query_hints('Suggest options. No gummies and no powders.',FORM_DOCS)
    assert hints.excluded_title_terms == ('gummies','powder')
    assert hints.retrieval_query == 'Suggest options.'


def test_compound_title_filter_does_not_expand_to_every_head_noun():
    docs=FORM_DOCS+[{'source_id':'g','title':'Firm Sandals'}]
    hints=query_hints('Suggest options. Avoid soft sandals.',docs)
    assert hints.excluded_title_terms == ('soft sandals',)
    assert title_is_excluded('Soft Sandals',hints)
    assert not title_is_excluded('Firm Sandals',hints)


def test_unknown_colour_modifier_is_not_discarded():
    question='Suggest options. Avoid red shoes.'
    hints=query_hints(question,FORM_DOCS)
    assert hints.excluded_title_terms == ()
    assert hints.retrieval_query == question


@pytest.mark.parametrize('question', [
    'Are capsules not easy to take?',
    'Is this not Cocoa Powder?',
    'Which options have no guaranteed benefit?',
    'No sandals for men in this list?',
])
def test_property_questions_do_not_become_exclusions(question):
    hints=query_hints(question,FORM_DOCS)
    assert hints.excluded_title_terms == ()
    assert hints.retrieval_query == question


def test_no_positive_task_retains_original_instead_of_empty_query():
    question='I do not want gummies or drink powders.'
    hints=query_hints(question,FORM_DOCS)
    assert hints.retrieval_query == question
    assert hints.excluded_title_terms == ('gummies','powder')


def test_plural_exclusion_keeps_free_from_titles_available():
    docs=[{'source_id':'a','title':'Rubber Gloves'},{'source_id':'b','title':'Latex Gloves'},
          {'source_id':'c','title':'Latex Free Gloves'}]
    hints=query_hints('Find gloves. Avoid latex.',docs)
    assert title_is_excluded('Latex Gloves',hints)
    assert not title_is_excluded('Latex Free Gloves',hints)


def test_besides_six_verified_titles_including_linked_only_subjects():
    titles=['Aurora Travel Mug','Harbor Desk Mat','Meadow Blanket, Large',
            'Juniper Storage Box','Garden Chair with Adjustable Back',
            'Frost Light Portable Reading Lamp']
    docs=[{'source_id':str(index),'title':title} for index,title in enumerate(titles[:3])]
    question=('Which other products fit a small apartment besides "Aurora Travel Mug", '
              '"Harbor Desk Mat", "Meadow Blanket, Large", "Juniper Storage Box", '
              '"Garden Chair with Adjustable Back" and "Frost Light Portable Reading Lamp"?')
    hints=query_hints(question,docs,exclusion_titles=titles[3:])
    assert hints.retrieval_query == 'Which other products fit a small apartment?'
    assert len(hints.excluded_title_terms) == 6
    assert all(title_is_excluded(title,hints) for title in titles)
    assert not title_is_excluded('Cedar Travel Mug',hints)
    assert not hints.comparison_source_ids


def test_linked_title_vocabulary_never_creates_comparison_document_scopes():
    docs=[{'source_id':'real','title':'Aurora Travel Mug'}]
    hints=query_hints('Compare Aurora Travel Mug and Harbor Desk Mat.',docs,
                      exclusion_titles=['Harbor Desk Mat'])
    assert hints.comparison_source_ids == ()
    assert hints.excluded_title_terms == ()


def test_long_exact_title_is_checked_before_predicate_and_length_guards():
    title='Garden Chair with Adjustable Back and Arms'
    docs=[{'source_id':'a','title':title},{'source_id':'b','title':'Garden Stool'}]
    hints=query_hints('Suggest another option. Exclude '+title+'.',docs)
    assert hints.retrieval_query == 'Suggest another option.'
    assert hints.excluded_title_terms == ('garden chair with adjustable back and arms',)
    assert title_is_excluded(title,hints)
    assert not title_is_excluded('Garden Stool',hints)


def test_besides_unknown_subject_retains_complete_query_and_known_exclusions():
    docs=[{'source_id':'a','title':'Aurora Travel Mug'}]
    question='Which other products work for travel besides Aurora Travel Mug and Unlisted Mystery Item?'
    hints=query_hints(question,docs)
    assert hints.retrieval_query == question
    assert hints.excluded_title_terms == ('aurora travel mug',)


@pytest.mark.parametrize('question',[
    'What does Aurora Travel Mug support besides Harbor Desk Mat?',
    'What materials does Aurora Travel Mug use besides steel?',
    'Tell me its benefits besides warmth.',
    'Which other products work for travel besides mugs?',
])
def test_besides_positive_predicates_and_unverified_generic_terms_are_not_filters(question):
    docs=[{'source_id':'a','title':'Aurora Travel Mug'},
          {'source_id':'b','title':'Harbor Desk Mat'},
          {'source_id':'c','title':'Steel Mug'},
          {'source_id':'d','title':'Warmth'}]
    hints=query_hints(question,docs)
    assert hints.excluded_title_terms == ()
    assert hints.retrieval_query == question


def test_title_with_negative_word_remains_a_positive_entity_mention():
    docs=[{'source_id':'a','title':'No Limit Bag'}, {'source_id':'b','title':'Travel Pouch'}]
    hints=query_hints('Compare No Limit Bag and Travel Pouch.',docs)
    assert hints.excluded_title_terms == ()
    assert set(hints.comparison_source_ids)=={'a','b'}


def test_exact_excluded_numeric_title_does_not_filter_sibling_variant():
    docs=[{'source_id':'a','title':'Router Pro 100'},
          {'source_id':'b','title':'Router Pro 200'},
          {'source_id':'c','title':'Beacon Switch'}]
    hints=query_hints('Exclude Router Pro 200. Compare Router Pro 100 and Beacon Switch.',docs)
    assert hints.excluded_title_terms == ('router pro 200',)
    assert set(hints.comparison_source_ids)=={'a','c'}
    assert title_is_excluded('Router Pro 200',hints)
    assert not title_is_excluded('Router Pro 100',hints)


REFERENT_DOCS = [
    {'source_id': 'a', 'title': 'Widget A'},
    {'source_id': 'b', 'title': 'Widget B'},
    {'source_id': 'case', 'title': 'Storage Case'},
]


@pytest.mark.parametrize('prefix', ['What capsule options', 'Which travel products', 'What other options'])
def test_alternative_queries_resolve_verified_site_prefixes(prefix):
    docs = [{'source_id':'a','title':'Aurora Travel Mug','url':'https://auroraco.example/products/mug'},
            {'source_id':'b','title':'Harbor Desk Mat','url':'https://auroraco.example/products/mat'},
            {'source_id':'c','title':'Cedar Travel Mug','url':'https://auroraco.example/products/cedar'}]
    hints = query_hints(prefix + ' are available besides AuroraCo® Aurora Travel Mug and AuroraCo Harbor Desk Mat?', docs)
    assert hints.excluded_title_terms == ('aurora travel mug','harbor desk mat')
    assert hints.comparison_source_ids == ()
    assert hints.broad_discovery
    assert 'besides' not in hints.retrieval_query
    assert not title_is_excluded('Cedar Travel Mug', hints)


@pytest.mark.parametrize('name', ['Unknown Aurora Travel Mug', 'AuroraCo Travel Mug', 'AuroraCo Aurora Travel Mug 200'])
def test_unverified_prefix_short_name_or_model_variant_is_not_discarded(name):
    docs = [{'source_id':'a','title':'Aurora Travel Mug','url':'https://auroraco.example/products/mug'}]
    question = 'Which other options are available besides ' + name + '?'
    hints = query_hints(question, docs)
    assert hints.excluded_title_terms == ()
    assert hints.retrieval_query == question


def test_site_prefix_alias_cannot_override_a_real_catalog_title():
    docs = [{'source_id':'a','title':'Travel Mug','url':'https://auroraco.example/products/mug'},
            {'source_id':'b','title':'AuroraCo Travel Mug','url':'https://auroraco.example/products/special'}]
    hints = query_hints('What other options besides AuroraCo Travel Mug?', docs)
    assert hints.excluded_title_terms == ('auroraco travel mug',)
    assert not title_is_excluded('Travel Mug', hints)


@pytest.mark.parametrize('question', [
    'I bought Widget A and Widget B. Can I store both in a cool cupboard?',
    'I bought Widget A and Widget B. Is either suitable for outdoor use?',
    'Can I use either Widget A or Widget B outside?',
])
def test_both_and_either_scope_two_explicit_verified_products(question):
    hints = query_hints(question, REFERENT_DOCS)
    assert set(hints.comparison_source_ids) == {'a', 'b'}
    assert hints.retrieval_query == question
    assert not hints.excluded_title_terms
    assert not hints.broad_discovery


def test_both_storage_followup_keeps_complete_shared_predicate_in_each_scope():
    question = 'I bought Widget A and Widget B. Can I store both in a cool cupboard?'
    hints = query_hints(question, REFERENT_DOCS)
    titles = [doc['title'] for doc in REFERENT_DOCS if doc['source_id'] in hints.comparison_source_ids]
    assert len(titles) == 2
    for title in titles:
        query = focused_query(hints.retrieval_query, title, titles)
        assert query.startswith(title + '.')
        assert 'Can I store both in a cool cupboard?' in query


@pytest.mark.parametrize('question', [
    'Can Widget A be stored either upright or flat?',
    'Can I use Widget A on both desks?',
    'Both the battery and the switch are on Widget A. How do I clean it?',
    'Is either setting on Widget A suitable for outdoor use?',
])
def test_both_or_either_with_one_product_does_not_invent_second_scope(question):
    hints = query_hints(question, REFERENT_DOCS)
    assert hints.comparison_source_ids == ()
    assert hints.retrieval_query == question


@pytest.mark.parametrize('question', [
    'Can I store both in a cool cupboard?',
    'Either one is okay. How do I use it?',
    'Can I put both the charger and batteries in the bag?',
])
def test_implicit_both_or_either_without_named_products_never_guesses_scope(question):
    hints = query_hints(question, REFERENT_DOCS)
    assert hints.comparison_source_ids == ()
    assert hints.retrieval_query == question


def test_both_requires_real_documents_not_only_linked_card_subjects():
    question = 'I bought Widget A and Widget B. Can I store both in a cool cupboard?'
    hints = query_hints(question, REFERENT_DOCS[:1], exclusion_titles=['Widget B'])
    assert hints.comparison_source_ids == ()
    assert hints.retrieval_query == question
