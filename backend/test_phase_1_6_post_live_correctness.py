"""Post-live regressions: isolated SQLite, deterministic model boundaries only."""
import contextlib
import io
import json
import time
from dataclasses import asdict
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from database import connection
from services import rag_service as rag, rag_planning as planning
from services.conversational_engine import _condense_primary_detail
from services.observability_service import ChatTrace
from services.query_contract import extract_requested_fields
from services.query_contract import extract_typed_prices_from_text, render_price_facts, compare_entity_prices
from services.requested_propositions import availability_subtype, update_support, annotate_candidates, proposition_instructions
from services.provider_failure import provider_failure, TEMPORARY_SERVICE_REPLY
from services.retrieval_selection import POLICY
from database.models import Chunk, Document, Website, WebsiteCrawl
import test_scoped_rag_architecture as fixtures


HARD_QUERY = ("If I buy one bottle for $33, will shipping be free, does the 60-day "
              "money-back guarantee cover repeat purchases, and are results within 4–8 weeks guaranteed?")
SEA = ("# Sea Essence Omega 3 Fish Oil\nSubscribe & Save More!\n\n"
       "$37.00$35.15$37.00 / bottle\n1 Bottle delivered every 1 monthJust $1.17/day\n"
       "Recurring5% OFF\nFree U.S. Shipping Over $60\nOR\nOne-time purchase\n\n$37.00\n"
       "You could save with a subscription\nPay in 2 interest-free installments of $18.50\n"
       "Add subscription\nProduct Description\nA daily formula.\nIngredients\nFish oil, EPA and DHA.")
TURMERIC = ("# Turmeric Boost\nSubscribe & Save More!\n\n$33.00$31.35$33.00 / bottle\n"
            "1 Bottle delivered every 1 monthJust $1.05/day\nRecurring5% OFF\n"
            "Free U.S. Shipping Over $60\nOR\nOne-time purchase\n$33.00\n"
            "You could save with a subscription\nPay over time for orders over $35.00\n"
            "Add subscription\nProduct Description\nA botanical formula.\nIngredients\nTurmeric and ginger.")


class PostLiveCorrectnessTests(unittest.TestCase):
    add_document = fixtures.ScopedRagTests.add_document
    contract = fixtures.ScopedRagTests.contract
    retrieve = fixtures.ScopedRagTests.retrieve

    def setUp(self):
        fixtures.ScopedRagTests.setUp(self)
        self.patches.enter_context(patch.object(connection.engine, "connect", side_effect=AssertionError("Real DB forbidden")))
        self.patches.enter_context(patch("httpx.Client.send", side_effect=AssertionError("Live HTTP forbidden")))
        self.patches.enter_context(patch("httpx.AsyncClient.send", side_effect=AssertionError("Live HTTP forbidden")))
        self.patches.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Live HTTP forbidden")))
        self.patches.enter_context(patch.object(rag.global_semantic_cache, "get", return_value=None))
        self.patches.enter_context(patch.object(rag.global_semantic_cache, "set"))
        self.patches.enter_context(patch.object(rag, "_RETRIEVAL_CACHE", {}))

    tearDown = fixtures.ScopedRagTests.tearDown

    def answer(self, question, output="A supported answer.", error=None):
        trace = ChatTrace(1, "widget")
        with patch.object(rag, "generate", return_value=output, side_effect=error) as generate, \
             patch.object(rag, "verify_answer", side_effect=lambda **kw: kw["draft_answer"]), \
             contextlib.redirect_stdout(io.StringIO()):
            result = rag.answer_question(self.db, self.bot, question, trace=trace)
        return result, trace, generate

    def test_01_monetary_condensation_never_relabels_installments(self):
        result = _condense_primary_detail(SEA, ["price"])
        self.assertNotIn("Subscription: $18.50", result)
        self.assertNotIn("One-Time Purchase: $18.50", result)

    def test_02_explicit_entity_survives_failed_planner(self):
        contract, _ = self.contract("What is the batch-specific certificate of analysis number for Sea Essence Omega 3?")
        self.assertEqual(contract.permitted_document_ids, [1])
        self.assertFalse(contract.requires_clarification)

    def test_03_compound_guarantee_field_is_additive(self):
        self.assertIn("guarantee", extract_requested_fields(HARD_QUERY))
        self.assertIn("shipping", extract_requested_fields(HARD_QUERY))

    def test_04_provider_failure_is_not_missing_knowledge_or_credential_advice(self):
        (answer, sources, chunks), trace, _ = self.answer("ingredients of Turmeric Boost", error=RuntimeError("429 RESOURCE_EXHAUSTED"))
        self.assertNotIn("API key", answer)
        self.assertNotIn("don't have information", answer)
        self.assertEqual(sources, [])
        self.assertEqual(chunks, [])
        self.assertEqual(trace.retrieval.fallback_reason, "generation_provider_error")

    def prices(self, text):
        return extract_typed_prices_from_text(text, entity_document_id=1, source_chunk_id=10, entity_name='Fixture')

    def role_values(self, text):
        return {(p.price_type, p.value) for p in self.prices(text) if p.verification_state == 'verified'}

    def test_05_sea_roles(self):
        roles = self.role_values(SEA)
        self.assertTrue({('one_time', '37.00'), ('subscription', '35.15'),
                         ('installment_payment', '18.50'), ('per_day_cost', '1.17')} <= roles, roles)

    def test_06_turmeric_roles(self):
        roles = self.role_values(TURMERIC)
        self.assertTrue({('one_time', '33.00'), ('subscription', '31.35'),
                         ('financing_threshold', '35.00'), ('per_day_cost', '1.05')} <= roles, roles)

    def test_07_no_false_comparison_options(self):
        self.assertTrue({('one_time', '18.50'), ('subscription', '18.50'), ('bundle_per_unit', '1.17')}.isdisjoint(self.role_values(SEA)))
        self.assertTrue({('one_time', '35.00'), ('subscription', '35.00')}.isdisjoint(self.role_values(TURMERIC)))

    def test_08_line_boundaries_stop_association(self):
        values = self.role_values('Subscription $20\nPay in installments of $10\nOne-time $25')
        self.assertEqual(values, {('subscription', '20.00'), ('installment_payment', '10.00'), ('one_time', '25.00')})

    def test_09_list_boundaries_stop_association(self):
        self.assertEqual(self.role_values('- Subscription $20\n- Shipping over $60\n- $9'),
                         {('subscription', '20.00'), ('shipping_threshold', '60.00')})

    def test_10_table_rows(self):
        self.assertEqual(self.role_values('| One-time | $22 |\n| Subscription | $20 |\n| Installment | $11 |'),
                         {('one_time', '22.00'), ('subscription', '20.00'), ('installment_payment', '11.00')})

    def test_11_ambiguous_amount_not_verified(self):
        values = self.prices('$20 $18 $20')
        self.assertTrue(values)
        self.assertTrue(all(v.verification_state == 'ambiguous' for v in values))
        self.assertEqual(render_price_facts(values), '')

    def test_12_unrelated_heading_breaks_pair(self):
        self.assertEqual(self.role_values('Subscription\n## Other details\n$10'), set())

    def test_13_explicit_label_value_pair(self):
        self.assertIn(('one_time', '21.00'), self.role_values('One-time purchase\n\n$21'))

    def test_14_offer_arithmetic_must_be_proven(self):
        corrupted = SEA.replace('Recurring5%', 'Recurring7%')
        self.assertNotIn(('subscription', '35.15'), self.role_values(corrupted))

    def test_15_text_provenance_exact_span(self):
        for fact in self.prices(SEA):
            self.assertEqual((fact.entity_document_id, fact.source_chunk_id), (1, 10))
            start, end = fact.source_span
            self.assertEqual(SEA[start:end], fact.original_value)
            self.assertTrue(fact.fragment_hash and fact.extraction_rule)

    def test_16_structured_provenance(self):
        self.db.get(Document, 1).metadata_json = {'og:price:amount': '37.00', 'og:price:currency': 'USD'}
        self.db.commit()
        c, _ = self.contract('price of Sea Essence Omega 3')
        rows, _ = self.retrieve(c)
        facts = rag.collect_price_facts(rows, c)
        structured = [f for f in facts if f.source == 'structured_metadata']
        self.assertTrue(structured)
        self.assertTrue(all(f.entity_document_id == 1 and f.source_chunk_id is not None and f.fragment_hash for f in structured))

    def test_17_thresholds_not_primary_comparison(self):
        self.assertIsNone(compare_entity_prices({'A': self.prices('Pay over time for orders over $35'),
                                                'B': self.prices('Installment $10')}, 'cheaper'))

    def test_18_shipping_refund_discount_roles(self):
        self.assertTrue({('shipping_threshold', '60.00'), ('refund_amount', '12.00'), ('discount', '5.00')} <=
                        self.role_values('Free shipping over $60\nRefund amount $12\nDiscount $5'))

    def test_19_absent_batch_fact_stays_entity_scoped(self):
        q = 'What is the batch-specific certificate of analysis number for Sea Essence Omega 3?'
        (answer, _, _), trace, generate = self.answer(q, 'I do not have the batch-specific certificate number for Sea Essence Omega 3.')
        self.assertNotIn('Which item', answer)
        self.assertEqual(trace.retrieval.selected_document_ids, [1])
        self.assertEqual(generate.call_count, 1)
        prompt = generate.call_args.kwargs['prompt']
        self.assertIn(q, prompt)
        self.assertNotIn('Turmeric Boost', prompt)

    def test_20_ambiguous_alias_clarifies(self):
        self.add_document(3, 'Sea Essence Omega 3 Liquid')
        self.db.commit()
        c, _ = self.contract('What is the batch number for Sea Essence Omega 3?')
        self.assertTrue(c.requires_clarification)
        self.assertIsNone(c.permitted_document_ids)

    def test_21_terminal_clarification_reason(self):
        (_, sources, _), trace, generate = self.answer('What are the ingredients?')
        self.assertEqual(generate.call_count, 0)
        self.assertEqual(trace.retrieval.fallback_reason, 'subject_clarification_required')
        self.assertIn(trace.retrieval.fallback_reason, trace.retrieval.fallback_events)
        self.assertEqual(trace.retrieval.terminal_response_category, 'clarification')
        self.assertEqual(sources, [])

    def test_22_all_seven_propositions(self):
        c, _ = self.contract(HARD_QUERY)
        self.assertEqual({p.type for p in c.requested_propositions}, {'purchase_condition', 'shipping_eligibility',
            'guarantee_eligibility', 'repeat_purchase_condition', 'result_timeline', 'guaranteed_result', 'entity_applicability'})
        self.assertFalse(c.requires_clarification)

    def test_23_price_cannot_choose_product(self):
        c, _ = self.contract(HARD_QUERY)
        self.assertIsNone(c.subject_document_id)
        self.assertEqual(c.resolved_entities, [])

    def compound_rows(self):
        self.db.get(Chunk, 15).content = 'Free shipping on orders over $60. The money-back guarantee covers eligible first-time single-bottle purchases. Repeat purchases are not eligible.'
        self.db.commit()  # make fixture writes visible to independent recall sessions
        c, _ = self.contract(HARD_QUERY)
        rows, trace = self.retrieve(c)
        update_support(c, rows, trace)
        return c, rows, trace

    def test_24_shipping_condition_contradicted(self):
        c, _, _ = self.compound_rows()
        p = next(p for p in c.requested_propositions if p.type == 'shipping_eligibility')
        self.assertEqual(p.support_state, 'contradicted')
        self.assertTrue(p.contradicting_candidate_ids)

    def test_25_repeat_exclusion_reserved(self):
        c, rows, _ = self.compound_rows()
        p = next(p for p in c.requested_propositions if p.type == 'repeat_purchase_condition')
        self.assertEqual(p.support_state, 'contradicted')
        self.assertTrue(any('Repeat purchases' in r['chunk'].content for r in rows))

    def test_26_shipping_duplicates_do_not_displace_guarantee(self):
        c, _ = self.contract(HARD_QUERY)
        doc = self.db.get(Document, 1)
        rows = [{'document': doc, 'chunk': SimpleNamespace(id=100+i, content=f'Free shipping over $60. Shipping option {i}.'), 'score': 1} for i in range(20)]
        rows.append({'document': doc, 'chunk': SimpleNamespace(id=999, content='Money-back guarantee excludes repeat purchases.'), 'score': 0.01})
        ranked = POLICY.select(annotate_candidates(c, rows), 3, 3)
        self.assertIn(999, [r['chunk'].id for r in ranked])

    def test_27_product_timeline_requires_applicability(self):
        c, _, _ = self.compound_rows()
        for p in c.requested_propositions:
            if p.type in {'result_timeline', 'entity_applicability', 'guaranteed_result'}:
                self.assertEqual(p.support_state, 'applicability_unresolved')

    def test_28_partial_answer_prompt_keeps_supported_clauses(self):
        self.compound_rows()
        output = '$33 is below the $60 free-shipping threshold. The guarantee excludes repeat purchases. Which product do you mean for the results timeline?'
        (answer, _, _), trace, call = self.answer(HARD_QUERY, output)
        self.assertEqual(answer.count('?'), 1)
        self.assertIn('$60', answer)
        self.assertIn('repeat purchases', answer)
        self.assertIn('Answer supported clauses', call.call_args.kwargs['prompt'])
        self.assertIn('applicability_unresolved', call.call_args.kwargs['prompt'])

    def test_29_compound_trace_all_support_states(self):
        _, _, trace = self.compound_rows()
        rows = trace.retrieval.to_dict()['requested_propositions']
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(row['support_state'] and 'supporting_candidate_ids' in row for row in rows))

    def test_30_geographic_is_not_stock(self):
        self.assertEqual(availability_subtype('Available in all states'), 'geographic_availability')

    def test_31_financing_is_not_stock(self):
        self.assertEqual(availability_subtype('Payment options might not be available in all states'), 'financing_availability')

    def test_32_live_warehouse_quantity_type(self):
        c, _ = self.contract('How many bottles of Turmeric Boost are in stock in your Mumbai warehouse right now?')
        self.assertEqual(c.availability_subtype, 'stock_quantity')
        self.assertEqual(c.permitted_document_ids, [2])

    def test_33_live_quantity_safe_no_cards(self):
        (answer, sources, chunks), trace, generate = self.answer('How many bottles of Turmeric Boost are in stock in your Mumbai warehouse right now?')
        self.assertIn("can't verify current stock", answer)
        self.assertEqual((sources, chunks), ([], []))
        self.assertEqual(generate.call_count, 0)
        self.assertTrue(trace.retrieval.availability['requires_live_data'])

    def test_34_availability_mismatch_trace(self):
        c, _ = self.contract('How many bottles of Turmeric Boost are in stock right now?')
        row = {'document': self.db.get(Document, 2), 'chunk': SimpleNamespace(id=999, content='Payment options may not be available in all states.')}
        trace = ChatTrace(1, 'widget')
        result = annotate_candidates(c, [row], trace)
        self.assertNotIn('availability', result[0].get('required_fields', []))
        self.assertEqual(trace.retrieval.availability['evidence'][0]['mismatch_reason'], 'non_inventory_availability')

    def provider_reply(self, error, category):
        (answer, sources, chunks), trace, call = self.answer('ingredients of Turmeric Boost', error=error)
        self.assertEqual(answer, TEMPORARY_SERVICE_REPLY)
        self.assertEqual((sources, chunks), ([], []))
        self.assertEqual(call.call_count, 1)
        self.assertEqual(trace.retrieval.provider_errors[-1]['category'], category)
        self.assertTrue(trace.retrieval.final_context_has_evidence)
        return trace

    def test_35_final_rate_limit(self):
        self.provider_reply(RuntimeError('429 RESOURCE_EXHAUSTED'), 'rate_limit')

    def test_36_final_daily_quota(self):
        self.provider_reply(RuntimeError('GenerateRequestsPerDay quota exhausted'), 'daily_quota')

    def test_37_final_minute_quota(self):
        self.provider_reply(RuntimeError('GenerateRequestsPerMinute quota'), 'minute_quota')

    def test_38_final_circuit_open(self):
        self.provider_reply(RuntimeError('circuit open'), 'circuit_open')

    def test_39_final_timeout(self):
        self.provider_reply(TimeoutError('timed out'), 'timeout')

    def test_40_final_authentication(self):
        error = RuntimeError('Do not expose this credential setup failure')
        error.status_code = 401
        self.provider_reply(error, 'authentication')

    def test_41_error_trace_retains_retrieval(self):
        trace = self.provider_reply(RuntimeError('429'), 'rate_limit')
        self.assertTrue(trace.retrieval.to_dict()['candidates'])
        self.assertEqual(trace.retrieval.source_suppression_reason, 'suppressed_provider_error')

    def test_42_healthy_missing_evidence(self):
        with patch.object(rag, 'retrieve_relevant_chunks_cached', return_value=[]):
            (answer, _, _), trace, generate = self.answer('ingredients of Turmeric Boost')
        self.assertEqual(answer, rag.FRIENDLY_FALLBACK)
        self.assertNotEqual(answer, TEMPORARY_SERVICE_REPLY)
        self.assertEqual(generate.call_count, 0)

    def test_43_empty_generation_distinct(self):
        (answer, sources, chunks), trace, _ = self.answer('ingredients of Turmeric Boost', output='')
        self.assertEqual(answer, TEMPORARY_SERVICE_REPLY)
        self.assertEqual((sources, chunks), ([], []))
        self.assertEqual(trace.retrieval.fallback_reason, 'empty_generation')
        self.assertEqual(trace.retrieval.provider_errors[-1]['category'], 'empty_generation')

    def test_44_planner_failure_category_and_entity(self):
        trace = ChatTrace(1, 'widget')
        with patch.object(planning, 'generate_auxiliary', side_effect=RuntimeError('429 daily quota')):
            c = planning.prepare_query(self.db, self.bot, 'batch number for Sea Essence Omega 3?', [], {}, rag._build_turn_query_contract, trace)
        self.assertEqual(c.permitted_document_ids, [1])
        self.assertEqual(trace.retrieval.provider_errors[0]['category'], 'daily_quota')

    def test_45_reviewer_failure_retains_and_continues(self):
        (answer, _, _), trace, call = self.answer('ingredients of Turmeric Boost', 'Turmeric Boost lists Ingredient Alpha and Ingredient Beta.')
        self.assertEqual(call.call_count, 1)
        self.assertIn('Ingredient Alpha', answer)
        self.assertIsNone(trace.retrieval.reviewer_found_supported_evidence)
        self.assertEqual(trace.retrieval.reviewer_outcome['failure_category'], 'timeout')

    def test_46_monetary_trace_serialized(self):
        (_, _, _), trace, _ = self.answer('price of Turmeric Boost', 'One-time $37.00; subscription $35.15.')
        records = trace.retrieval.to_dict()['monetary_evidence']
        self.assertTrue(records)
        self.assertTrue(all(r['source_chunk_id'] is not None and r['entity_document_id'] == 2 for r in records))

    def test_47_reviewer_missing_contradiction_serialized(self):
        c, _ = self.contract('price of Turmeric Boost')
        rows, _ = self.retrieve(c)
        trace = ChatTrace(1, 'widget')
        review = {'ranked_candidates': [0], 'missing_fields': ['guarantee'], 'contradictory_candidates': [1], 'reject_all': False}
        with patch.object(planning, 'generate_auxiliary', return_value=json.dumps(review)):
            planning.review_evidence(self.bot, c, rows, trace)
        outcome = trace.retrieval.to_dict()['reviewer_outcome']
        self.assertEqual(outcome['missing_fields'], ['guarantee'])
        self.assertTrue(outcome['contradictory_candidate_ids'])
        self.assertFalse(outcome['reject_all'])

    def test_48_entity_trace_serialized(self):
        (_, _, _), trace, _ = self.answer('batch number for Sea Essence Omega 3?', 'I do not have the batch number.')
        outcome = trace.retrieval.to_dict()['entity_resolution']
        self.assertEqual(outcome['selected_document_ids'], [1])
        self.assertTrue(outcome['planner_fallback_used'])
        self.assertIn(outcome['match_type'], ['canonical_prefix_in_question', 'exact_identity'])

    def test_49_error_category_sanitized(self):
        bot = SimpleNamespace(provider='gemini', model_name='gemini-2.5-flash')
        outcome = provider_failure(RuntimeError('429 secret=fake-secret project=private-project-id'), 'generation', bot)
        self.assertEqual(outcome['category'], 'rate_limit')
        self.assertNotIn('fake-secret', json.dumps(outcome))
        self.assertNotIn('private-project-id', json.dumps(outcome))

    def test_50_parallel_leg_timings_not_joined(self):
        c, _ = self.contract('ingredients of Turmeric Boost')
        def vector(*args):
            time.sleep(.015)
            return [(21, 2, .2)]
        def lexical(*args):
            time.sleep(.060)
            return [(21, 2)]
        with patch.object(rag, '_vector_candidate_ids', side_effect=vector), patch.object(rag, '_lexical_candidate_ids', side_effect=lexical):
            _, trace = self.retrieve(c)
        times = trace.timings_ms
        self.assertGreater(times['lexical_search_ms'], times['vector_search_ms'] + 20)
        self.assertGreaterEqual(times['parallel_retrieval_wall_ms'], times['lexical_search_ms'])
        self.assertIn('fusion_ms', times)

    def test_51_tenant_isolation_aliases(self):
        self.add_document(3, 'Sea Essence Omega 3 Private', org_id=99)
        self.db.commit()
        c, _ = self.contract('batch number for Sea Essence Omega 3?')
        self.assertEqual(c.permitted_document_ids, [1])
        self.assertNotIn(3, c.entity_resolution['candidate_document_ids'])

    def test_52_bot_isolation_aliases(self):
        self.add_document(3, 'Sea Essence Omega 3 Private', bot_id=99)
        self.db.commit()
        c, _ = self.contract('batch number for Sea Essence Omega 3?')
        self.assertEqual(c.permitted_document_ids, [1])

    def test_53_ready_boundary(self):
        doc = self.add_document(3, 'Sea Essence Omega 3 Old')
        doc.status = 'failed'
        self.db.commit()
        c, _ = self.contract('batch number for Sea Essence Omega 3?')
        self.assertEqual(c.permitted_document_ids, [1])

    def test_54_followup_continuity(self):
        _, state = self.contract('Tell me about Sea Essence Omega 3')
        for q in ['ingredients?', 'how to use it?', 'what about shipping?', 'does it have a guarantee?']:
            c, state = self.contract(q, state=state)
            self.assertEqual(c.permitted_document_ids, [1])
        _, state = self.contract('what about Turmeric Boost?', state=state)
        c, _ = self.contract('price?', state=state)
        self.assertEqual(c.permitted_document_ids, [2])

    def test_55_comparison_attribution(self):
        self.db.get(Chunk, 14).content = SEA
        self.db.get(Chunk, 24).content = TURMERIC
        self.db.commit()
        c, _ = self.contract('compare the prices of Sea Essence Omega 3 and Turmeric Boost')
        rows, _ = self.retrieve(c)
        facts = rag.collect_price_facts(rows, c)
        self.assertIn((1, 'one_time', '37.00'), {(f.entity_document_id, f.price_type, f.value) for f in facts})
        self.assertIn((2, 'one_time', '33.00'), {(f.entity_document_id, f.price_type, f.value) for f in facts})

    def test_56_original_question_unmodified(self):
        q = 'What is the batch-specific certificate of analysis number for Sea Essence Omega 3?'
        (_, _, _), trace, call = self.answer(q)
        self.assertEqual(trace.retrieval.original_user_message, q)
        self.assertIn(q, call.call_args.kwargs['prompt'])
        self.assertNotEqual(trace.retrieval.retrieval_query, q)

    def test_57_call_counts_bounded(self):
        with patch.object(planning, 'generate_auxiliary', side_effect=TimeoutError('offline')) as auxiliary, \
             patch.object(rag, 'generate_embedding', return_value=[0.0]*768) as embedding:
            (_, _, _), _, call = self.answer('ingredients of Turmeric Boost')
        self.assertEqual(auxiliary.call_count, 2)  # one planner, one reviewer
        self.assertEqual(embedding.call_count, 1)
        self.assertEqual(call.call_count, 1)

    def test_58_cache_includes_propositions_not_support_mutation(self):
        c, _ = self.contract(HARD_QUERY)
        before = c.cache_fragment()
        c.requested_propositions[0].support_state = 'contradicted'
        self.assertEqual(c.cache_fragment(), before)
        other, _ = self.contract(HARD_QUERY.replace('$33', '$70'))
        self.assertNotEqual(other.cache_fragment(), before)

    def test_59_non_price_condensation_unchanged(self):
        text = '# Fixture\nCheckout $20\nProduct Description\nIngredients: Alpha.\nDirections: Take daily.\nBenefits: Comfort.'
        self.assertEqual(_condense_primary_detail(text, ['ingredients']), '# Fixture\n\nProduct Description\nIngredients: Alpha.\nDirections: Take daily.\nBenefits: Comfort.')

    def test_60_multiple_categories_availability(self):
        for value, expected in [('Appointment availability', 'appointment_availability'),
                                ('Available for purchase', 'purchasing_availability'),
                                ('Available', 'generic_availability'), ('In stock', 'stock_status')]:
            self.assertEqual(availability_subtype(value), expected)

    def test_61_numeric_slug_cannot_infer_from_price(self):
        self.add_document(33, 'Unrelated Package')
        self.db.commit()
        c, _ = self.contract(HARD_QUERY)
        self.assertIsNone(c.subject_document_id)
        self.assertEqual(c.resolved_entities, [])

    def test_62_failed_profile_not_in_clause_reservation(self):
        self.db.get(Chunk, 15).embedding_model = 'incompatible'
        self.db.commit()
        c, _ = self.contract(HARD_QUERY)
        rows, trace = self.retrieve(c)
        self.assertNotIn(15, [row['chunk'].id for row in rows])
        rejected = trace.retrieval.candidates.get((1, 15))
        if rejected:
            self.assertNotIn('field_scan', rejected.channels)
            self.assertEqual(rejected.final_reason, 'excluded_embedding_profile')
            self.assertFalse(rejected.included_final_context)

    def test_63_active_crawl_scope_for_aliases(self):
        self.db.add(Website(id=1, bot_id=1, organization_id=1, root_url='https://fixture.test', domain='fixture.test', active_crawl_id=2, status='ready'))
        self.db.add_all([WebsiteCrawl(id=i, website_id=1, bot_id=1, organization_id=1, version=i, status='ready') for i in (1, 2)])
        for number in (1, 2):
            doc = self.db.get(Document, number)
            doc.source_type, doc.website_id, doc.crawl_id = 'website', 1, number
            for chunk in doc.chunks:
                chunk.website_id, chunk.crawl_id = 1, number
        self.db.commit()
        c, _ = self.contract('batch number for Sea Essence Omega 3?')
        self.assertNotIn(1, c.entity_resolution['selected_document_ids'])
        self.assertNotIn(1, c.entity_resolution['candidate_document_ids'])

    def test_64_bounded_field_recall_recovers_timeline_outside_channels(self):
        c, _ = self.contract(HARD_QUERY)
        with patch.object(rag, '_vector_candidate_ids', return_value=[(15, 1, .2)]), \
             patch.object(rag, '_lexical_candidate_ids', return_value=[(15, 1)]):
            rows, trace = self.retrieve(c)
        self.assertTrue(any('Results may appear' in row['chunk'].content for row in rows))
        self.assertLessEqual(len(rows), 48)
        self.assertLessEqual(trace.retrieval.stage_counts['field_scan'], 1500)
        update_support(c, rows, trace)
        self.assertEqual(next(p for p in c.requested_propositions if p.type == 'result_timeline').support_state, 'applicability_unresolved')

    def test_65_reviewer_reject_all_outcome(self):
        c, _ = self.contract('ingredients of Turmeric Boost')
        rows, _ = self.retrieve(c)
        trace = ChatTrace(1, 'widget')
        with patch.object(planning, 'generate_auxiliary', return_value='{"ranked_candidates":[],"reject_all":true}'):
            result = planning.review_evidence(self.bot, c, rows, trace)
        self.assertEqual(result, [])
        self.assertTrue(trace.retrieval.reviewer_outcome['reject_all'])
        self.assertTrue(trace.retrieval.reviewer_outcome['rejected_ids'])

    def test_66_reviewer_proposition_support_references(self):
        c, rows, trace = self.compound_rows()
        ref = next(i for i, row in enumerate(rows) if 'money-back guarantee' in row['chunk'].content)
        review = {'ranked_candidates': [ref], 'proposition_support': [{
            'proposition_id': 'guarantee_eligibility', 'support_state': 'supported', 'supporting_candidates': [ref]}]}
        with patch.object(planning, 'generate_auxiliary', return_value=json.dumps(review)):
            selected = planning.review_evidence(self.bot, c, rows, trace)
        update_support(c, selected, trace)
        p = next(p for p in c.requested_propositions if p.type == 'guarantee_eligibility')
        self.assertEqual(p.support_state, 'supported')
        self.assertTrue(p.supporting_candidate_ids)

    def test_67_reviewer_cannot_invent_proposition_reference(self):
        c, rows, trace = self.compound_rows()
        review = {'ranked_candidates': [0], 'proposition_support': [{
            'proposition_id': 'guarantee_eligibility', 'support_state': 'supported', 'supporting_candidates': [47]}]}
        with patch.object(planning, 'generate_auxiliary', return_value=json.dumps(review)):
            selected = planning.review_evidence(self.bot, c, rows, trace)
        self.assertEqual([v['chunk'].id for v in selected], [v['chunk'].id for v in rows])
        self.assertIsNone(trace.retrieval.reviewer_found_supported_evidence)

    def test_68_planner_cannot_drop_explicit_propositions(self):
        c, _ = self.contract(HARD_QUERY, response=fixtures.plan(requested_fields=['shipping']))
        self.assertEqual(len(c.requested_propositions), 7)
        self.assertIn('guarantee', c.requested_fields)

    def test_69_monetary_comparison_prompt_source_bound(self):
        self.db.get(Chunk, 14).content, self.db.get(Chunk, 24).content = SEA, TURMERIC
        self.db.commit()
        _, trace, call = self.answer('Compare prices of Sea Essence Omega 3 and Turmeric Boost',
                                    'Sea Essence is $37 one-time and $35.15 subscription. Turmeric Boost is $33 one-time and $31.35 subscription.')
        prompt = call.call_args.kwargs['prompt']
        self.assertNotIn('subscription | $18.50', prompt)
        self.assertNotIn('one_time | $35.00', prompt)
        self.assertIn('installment_payment', prompt)
        self.assertIn('financing_threshold', prompt)
        self.assertTrue(trace.retrieval.monetary_evidence)

    def test_70_unknown_quota_dimension_not_invented(self):
        from services.providers.base_provider import ProviderError, ProviderErrorKind
        error = ProviderError('quota exhausted', kind=ProviderErrorKind.QUOTA_EXHAUSTED)
        self.assertEqual(provider_failure(error, 'generation')['category'], 'rate_limit')

    def test_71_nested_typed_error_cause(self):
        from services.providers.base_provider import ProviderError, ProviderErrorKind
        outer = RuntimeError('safe router wrapper')
        outer.__cause__ = ProviderError('redacted', kind=ProviderErrorKind.INVALID_MODEL)
        self.assertEqual(provider_failure(outer, 'generation')['category'], 'invalid_model')

    def test_72_review_outcomes_do_not_leak_chunk_body(self):
        c, rows, trace = self.compound_rows()
        marker = 'PRIVATE FULL CHUNK BODY SHOULD NOT BE TRACED'
        rows[0] = dict(rows[0], chunk=SimpleNamespace(id=990, content=marker, metadata_json={}))
        with patch.object(planning, 'generate_auxiliary', return_value='{"ranked_candidates":[0]}'):
            planning.review_evidence(self.bot, c, rows, trace)
        self.assertNotIn(marker, json.dumps(trace.retrieval.to_dict()))

    def test_73_refund_negation_not_inverted(self):
        self.db.get(Chunk, 15).content = 'Repeat purchases are not excluded from the guarantee.'
        self.db.commit()
        c, _ = self.contract(HARD_QUERY)
        row = {'document': self.db.get(Document, 1), 'chunk': self.db.get(Chunk, 15)}
        update_support(c, [row])
        self.assertNotEqual(next(p for p in c.requested_propositions if p.type == 'repeat_purchase_condition').support_state, 'contradicted')

    def test_74_recurring_offer_currency_must_match(self):
        self.assertNotIn(('subscription', '35.15'), self.role_values(SEA.replace('$35.15', '€35.15')))

    def test_75_structured_financing_not_product_price(self):
        from services.query_contract import classify_price_role
        self.assertEqual(classify_price_role('price', 'financing.minimum_order.price'), 'financing_threshold')

    def test_76_bounded_price_annotations(self):
        facts = self.prices('\n'.join(f'One-time purchase ${i}' for i in range(1, 200)))
        rendered = render_price_facts(facts, max_chars=2000)
        self.assertLessEqual(len(rendered), 2000)
        self.assertTrue(all(line.startswith('- Fixture | one_time | $') for line in rendered.splitlines()[1:]))

    def test_77_other_provider_failure_categories(self):
        from services.providers.base_provider import ProviderError, ProviderErrorKind
        for kind, category in [(ProviderErrorKind.INVALID_MODEL, 'invalid_model'),
                               (ProviderErrorKind.UNAVAILABLE, 'provider_unavailable'),
                               (ProviderErrorKind.UNKNOWN, 'unknown_provider_error')]:
            error = ProviderError('redacted', status_code=400, kind=kind)
            self.assertEqual(provider_failure(error, 'generation')['category'], category)

    def test_78_bundle_total_and_per_unit_both_preserved(self):
        self.assertEqual(self.role_values('6-bottle pack $247.50. $41.25 / bottle.'),
                         {('bundle_total', '247.50'), ('bundle_per_unit', '41.25')})

    def test_79_conflicting_price_labels_remain_ambiguous(self):
        for source in ['Regular / sale: $40 / $35', 'One-time and subscription: $33 / $31']:
            self.assertEqual(self.role_values(source), set())


if __name__ == "__main__":
    unittest.main()
