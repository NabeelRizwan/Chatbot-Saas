from retrieval_engine.query_constraints import query_hints

DOCS=[{'source_id':str(i),'title':t} for i,t in enumerate([
 'Acme Field Runner','Acme Field Runner Plus','Acme Sprint Slip On',
 'Acme Navigator','Acme City Cruiser','Acme Trail Sandal',
 'Materials','Returns','Care Guide','Shipping'])]

def scopes(q):return set(query_hints(q,DOCS).comparison_source_ids)

def test_shared_prefix_omission_preserves_two_named_items():
 assert scopes('Can Field Runner and Navigator both be washed?')=={'0','3'}

def test_nested_names_need_separate_mentions():
 assert scopes('Compare Field Runner Plus and Navigator on weight.')=={'1','3'}

def test_three_distinct_mentions_preserve_short_and_long_variant():
 assert scopes('Which is lighter: Navigator, Field Runner or Field Runner Plus?')=={'0','1','3'}

def test_common_brand_does_not_add_unmentioned_products():
 assert scopes('How does Acme Navigator compare with Acme City Cruiser?')=={'3','4'}

def test_comparison_inflection_recognized():
 assert scopes('How heavy is Navigator compared with City Cruiser?')=={'3','4'}

def test_single_product_or_generic_question_does_not_force_scopes():
 assert not scopes('Can I wash Field Runner?')
 assert not scopes('Which Acme products are light or washable?')

def test_numeric_variants_stay_distinct():
 docs=[{'source_id':'a','title':'Acme Router 100'}, {'source_id':'b','title':'Acme Router 200'}, {'source_id':'c','title':'Acme Beacon'}]
 assert set(query_hints('Compare Router 100 and Router 200.',docs).comparison_source_ids)=={'a','b'}
 assert not query_hints('Compare Router and Beacon.',docs).comparison_source_ids

def test_duplicate_titles_decline_the_literal_fast_path():
 from retrieval_engine.query_constraints import _literal_catalog_subjects
 docs=[{'source_id':'a','title':'Acme Navigator'}, {'source_id':'b','title':'Acme Navigator'}, {'source_id':'c','title':'Acme Beacon'}]
 assert not _literal_catalog_subjects('Compare Navigator and Beacon.',docs,())

def test_non_ascii_word_boundary_does_not_create_substring_subject():
 from retrieval_engine.query_constraints import _literal_catalog_subjects
 docs=[{'source_id':'a','title':'Acme Café'}, {'source_id':'b','title':'Acme Beacon'}, {'source_id':'c','title':'Acme Navigator'}]
 assert _literal_catalog_subjects('Compare Caféine and Beacon.',docs,())==('b',)

def test_shared_prefix_removed_from_each_compared_subject_query():
 from retrieval_engine.query_constraints import focused_query
 titles=['Acme Field Runner','Acme Navigator']
 question='Can the original Field Runner and classic Navigator both be washed?'
 query=focused_query(question,titles[1],titles)
 assert query.startswith('Acme Navigator.')
 assert 'Field Runner' not in query
 assert query.count('Navigator')==1
 assert 'washed' in query

def test_shared_prefix_short_name_can_route_implicit_comparison():
 from retrieval_engine.adaptive_evidence import routing_hints
 assert set(routing_hints('Are Navigator and Field Runner Plus made in the same country?',DOCS).comparison_source_ids)=={'3','1'}

def test_exact_website_brand_prefix_may_be_omitted():
 from retrieval_engine.query_constraints import _literal_catalog_subjects
 docs=[{'source_id':str(i),'title':t,'url':'https://lumen.example/products/item'} for i,t in enumerate([
  "Men's Field Runner", "Men's Field Runner Plus", "Men's Lumen Sandal", "Men's Navigator", "Men's Cruiser", "Men's Sprint", 'Care Guide','Returns'])]
 assert set(_literal_catalog_subjects('Compare Field Runner and Sandal.',docs,()))=={'0','2'}
 assert _literal_catalog_subjects('Compare Runner and Sandalwood.',docs,())==()

def test_unrelated_brand_words_are_not_stripped_from_titles():
 from retrieval_engine.query_constraints import _literal_catalog_subjects
 docs=[{'source_id':str(i),'title':t,'url':'https://other.example/p'} for i,t in enumerate(['Acme Road Sandal','Acme Navigator','Acme Field Runner'])]
 assert _literal_catalog_subjects('Compare Sandal and Navigator.',docs,())==('1',)

def test_invalid_source_url_does_not_break_catalog_matching():
 from retrieval_engine.query_constraints import _literal_catalog_subjects
 docs=[{**doc,'url':'https://['} for doc in DOCS]
 assert set(_literal_catalog_subjects('Compare Navigator and Field Runner.',docs,()))=={'3','0'}

def test_two_literal_subjects_do_not_require_comparison_keyword():
 from retrieval_engine.adaptive_evidence import routing_hints
 docs=[{'source_id':str(i),'title':t,'url':'https://lumen.example/products/item'} for i,t in enumerate([
  "Men's Field Runner", "Men's Field Runner Plus", "Men's Lumen Sandal", "Men's Navigator", "Men's Cruiser", "Men's Sprint", 'Care Guide','Returns'])]
 assert set(routing_hints('Should I choose my usual size for Field Runner and the Sandal?',docs).comparison_source_ids)=={'0','2'}
