"""Context admission/terminal regressions: fixtures only, all model I/O mocked."""
import contextlib
import io
import json
import os
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services import rag_service as rag, rag_planning as planning
from services.conversational_engine import compress_and_rerank_chunks
from services.observability_service import ChatTrace
from services.provider_failure import TEMPORARY_SERVICE_REPLY
from services.requested_propositions import annotate_candidates, update_support
from services.retrieval_selection import POLICY
import test_phase_1_6_post_live_correctness as prior


HARD_QUERY = prior.HARD_QUERY
SHIPPING = 'All orders of $60 or more include Free Shipping across USA.'
GUARANTEE = 'The 60-day money-back guarantee covers only first-time customers purchasing a single bottle.'
REPEAT = 'Repeat purchases are not eligible for the money-back guarantee.'


class ContextBudgetTests(unittest.TestCase):
    setUp = prior.PostLiveCorrectnessTests.setUp
    tearDown = prior.PostLiveCorrectnessTests.tearDown
    add_document = prior.PostLiveCorrectnessTests.add_document
    contract = prior.PostLiveCorrectnessTests.contract
    retrieve = prior.PostLiveCorrectnessTests.retrieve

    def live_rows(self, contract):
        from database.models import Document
        for number in range(3, 11):
            if not self.db.get(Document, number):
                self.add_document(number, f'Offering {number}', text=['General description.'])
        self.db.commit()  # Isolated SQLite fixtures; never the configured DB.
        rows = []
        for index in range(48):
            doc = self.db.get(Document, index % 10 + 1)
            if index == 46:
                body = GUARANTEE
            elif index == 47:
                body = REPEAT
            else:
                body = SHIPPING + f' Shipping policy reference {index}. ' + ('Delivery applies to eligible orders. ' * 60)
            rows.append(dict(document=doc, chunk=SimpleNamespace(id=1000+index,
                chunk_index=index, content=body, metadata_json={}, token_count=0), score=1-index/100,
                required_fields=list(contract.requested_fields), evidence_priority=0.3))
        return annotate_candidates(contract, rows)

    def prepared(self):
        trace = ChatTrace(1, 'offline')
        with patch.object(planning, 'generate_auxiliary', side_effect=RuntimeError('provider unavailable')):
            contract = planning.prepare_query(self.db, self.bot, HARD_QUERY, [], {}, rag._build_turn_query_contract, trace)
        rows = self.live_rows(contract)
        with patch.object(planning, 'generate_auxiliary', side_effect=TimeoutError('offline reviewer timeout')):
            retained = planning.review_evidence(self.bot, contract, rows, trace)
        return contract, retained, trace

    def test_01_exact_live_shape_retains_factual_context(self):
        contract, retained, trace = self.prepared()
        self.assertEqual(len(contract.requested_propositions), 7)
        self.assertIsNone(contract.subject_document_id)
        self.assertEqual(contract.resolved_entities, [])
        self.assertEqual(len(retained), 48)
        self.assertEqual({e['stage'] for e in trace.retrieval.provider_errors}, {'planner', 'reviewer'})
        for proposition in contract.requested_propositions:
            if proposition.type in {'result_timeline', 'guaranteed_result', 'entity_applicability'}:
                self.assertEqual(proposition.support_state, 'applicability_unresolved')
        items, context = compress_and_rerank_chunks(retained, HARD_QUERY,
            max_context_chars=POLICY.default_context_chars, query_contract=contract, trace=trace)
        if not items:
            rag._no_evidence_reply(trace, 'empty_context_after_validation')
        self.assertTrue(items, f'REPRO: retained={len(retained)}, final_context={len(items)}, '
            f'context_chars={len(context)}, terminal={trace.retrieval.terminal_response_category}, text={context!r}')
        for fact in (SHIPPING, GUARANTEE, REPEAT):
            self.assertIn(fact, context)

    def test_02_exact_live_shape_reaches_generation(self):
        contract, retained, _ = self.prepared()
        trace = ChatTrace(1, 'widget')
        output = ('$33 is below the $60 free-shipping threshold. The 60-day money-back guarantee '
                  'covers first-time single-bottle purchases, not repeat purchases. '
                  'Which product do you mean for the results timeline?')
        with patch.object(rag, 'retrieve_relevant_chunks_cached', return_value=retained), \
             patch.object(rag, 'generate', return_value=output) as generation, \
             patch.object(rag, 'verify_answer', side_effect=lambda **kw: kw['draft_answer']), \
             contextlib.redirect_stdout(io.StringIO()):
            answer, sources, chunks = rag.answer_question(self.db, self.bot, HARD_QUERY, trace=trace)
        self.assertEqual(generation.call_count, 1,
            f'REPRO: terminal={trace.retrieval.terminal_response_category}, '
            f'context={trace.retrieval.stage_counts.get("final_context")}, answer={answer!r}')
        self.assertEqual(trace.retrieval.terminal_response_category, 'answer')
        self.assertTrue(sources)
        self.assertTrue(chunks)

    def admission(self, rows=None, budget=10000, contract=None, annotated=False):
        contract = contract or self.contract(HARD_QUERY)[0]
        rows = self.live_rows(contract) if rows is None else annotate_candidates(contract, rows)
        trace = ChatTrace(1, 'offline')
        update_support(contract, rows, trace)
        if annotated:
            items, context, _, _ = rag._bounded_generation_context(rows, contract.original_query,
                budget, contract.mode, contract, trace)
        else:
            items, context = compress_and_rerank_chunks(rows, contract.original_query,
                max_context_chars=budget, query_contract=contract, trace=trace)
        return items, context, trace, contract

    def row(self, index, body, fields=None, doc_id=1, score=1):
        from database.models import Document
        return dict(document=self.db.get(Document, doc_id), chunk=SimpleNamespace(id=2000+index,
            content=body, chunk_index=index, metadata_json={}, token_count=0),
            required_fields=fields or [], score=score)

    def run_answer(self, rows, *, error=None, strict=True, auxiliary=None):
        self.bot.capabilities = {} if strict else {'web_search': True}
        trace = ChatTrace(1, 'offline')
        with patch.object(rag, 'retrieve_relevant_chunks_cached', return_value=rows), \
             patch.object(planning, 'generate_auxiliary', side_effect=auxiliary or TimeoutError('offline')) as aux, \
             patch.object(rag, 'generate', return_value='$33 is below the $60 shipping threshold. Repeat purchases are not eligible.', side_effect=error) as gen, \
             patch.object(rag, 'verify_answer', side_effect=lambda **kw: kw['draft_answer']), \
             contextlib.redirect_stdout(io.StringIO()):
            result = rag.answer_question(self.db, self.bot, HARD_QUERY, trace=trace)
        return result, trace, gen, aux

    def test_03_shipping_survives(self):
        self.assertIn(SHIPPING, self.admission()[1])

    def test_04_first_purchase_guarantee_survives(self):
        self.assertIn(GUARANTEE, self.admission()[1])

    def test_05_repeat_exclusion_survives(self):
        self.assertIn(REPEAT, self.admission()[1])

    def test_06_shipping_duplicates_do_not_displace_guarantee(self):
        rows = [self.row(i, SHIPPING + ' ' + ('Shipping reference. ' * 25), ['shipping']) for i in range(40)]
        rows += [self.row(41, GUARANTEE, ['guarantee'], score=.01), self.row(42, REPEAT, ['guarantee'], score=.001)]
        _, text, _, _ = self.admission(rows, budget=1250)
        self.assertIn(GUARANTEE, text)
        self.assertIn(REPEAT, text)

    def test_07_guarantee_duplicates_do_not_displace_shipping(self):
        rows = [self.row(i, GUARANTEE + ' ' + ('Guarantee detail. ' * 25), ['guarantee']) for i in range(40)]
        rows += [self.row(41, SHIPPING, ['shipping'], score=.01)]
        self.assertIn(SHIPPING, self.admission(rows, budget=1250)[1])

    def test_08_timeline_remains_unresolved_after_admission(self):
        _, text, _, contract = self.admission(annotated=True)
        for p in contract.requested_propositions:
            if p.type in {'result_timeline', 'entity_applicability', 'guaranteed_result'}:
                self.assertEqual(p.support_state, 'applicability_unresolved')
                self.assertIsNone(p.applicable_entity)
        self.assertIn('applicability_unresolved', text)

    def test_09_amount_is_not_identity(self):
        _, _, _, c = self.admission(annotated=True)
        self.assertIsNone(c.subject_document_id)
        self.assertEqual(c.resolved_entities, [])

    def test_10_all_seven_propositions_remain(self):
        _, _, trace, c = self.admission(annotated=True)
        self.assertEqual(len(c.requested_propositions), 7)
        self.assertEqual(len(trace.retrieval.requested_propositions), 7)

    def test_11_auxiliary_failures_preserve_valid_sources(self):
        _, rows, _ = self.prepared()
        (answer, sources, chunks), trace, gen, aux = self.run_answer(rows)
        self.assertTrue(sources and chunks)
        self.assertNotEqual(answer, TEMPORARY_SERVICE_REPLY)
        self.assertEqual((gen.call_count, aux.call_count), (1, 2))
        self.assertEqual(trace.retrieval.terminal_reason, 'answer')
        self.assertIsNone(trace.retrieval.source_suppression_reason)

    def test_12_planner_failure_healthy_review_can_answer(self):
        rows = [self.row(1, SHIPPING, ['shipping'])]
        responses = iter([RuntimeError('offline planner error'), '{"ranked_candidates":[0]}'])
        def auxiliary(*args, **kwargs):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value
        _, trace, gen, _ = self.run_answer(rows, auxiliary=auxiliary)
        self.assertEqual(gen.call_count, 1)
        self.assertEqual(trace.retrieval.terminal_response_category, 'answer')
        self.assertEqual([v['stage'] for v in trace.retrieval.provider_errors], ['planner'])

    def test_13_reviewer_timeout_healthy_planner_can_answer(self):
        import test_scoped_rag_architecture as fixtures
        responses = iter([fixtures.plan().model_dump_json(), TimeoutError('offline reviewer')])
        def auxiliary(*args, **kwargs):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value
        _, trace, gen, _ = self.run_answer([self.row(1, SHIPPING)], auxiliary=auxiliary)
        self.assertEqual(gen.call_count, 1)
        self.assertEqual(trace.retrieval.terminal_response_category, 'answer')
        self.assertEqual([v['stage'] for v in trace.retrieval.provider_errors], ['reviewer'])

    def test_14_assembly_exception_is_technical_in_both_modes(self):
        for strict in (True, False):
            with self.subTest(strict=strict), patch.object(rag, 'compress_and_rerank_chunks', side_effect=RuntimeError('secret fixture error')):
                result, trace, gen, _ = self.run_answer([self.row(1, SHIPPING)], strict=strict)
            self.assertEqual(result, (TEMPORARY_SERVICE_REPLY, [], []))
            self.assertEqual(gen.call_count, 0)
            self.assertEqual(trace.retrieval.terminal_reason, 'context_assembly_error')
            self.assertNotIn('secret fixture error', json.dumps(trace.retrieval.to_dict()))

    def test_15_budget_exhaustion_is_not_genuine_absence(self):
        _, _, trace, _ = self.admission([self.row(1, SHIPPING)], budget=1, annotated=True)
        reply = rag._no_evidence_reply(trace, 'empty_context_after_validation')
        self.assertEqual(reply, (TEMPORARY_SERVICE_REPLY, [], []))
        self.assertNotEqual(trace.retrieval.terminal_response_category, 'missing_knowledge')

    def test_16_healthy_zero_evidence_even_with_planner_failure(self):
        result, trace, gen, aux = self.run_answer([])
        self.assertEqual(result, (rag.FRIENDLY_FALLBACK, [], []))
        self.assertEqual(trace.retrieval.terminal_response_category, 'missing_knowledge')
        self.assertEqual((gen.call_count, aux.call_count), (0, 1))

    def test_17_healthy_reviewer_oversized_pool_degrades(self):
        c = self.contract(HARD_QUERY)[0]
        rows = self.live_rows(c)
        trace = ChatTrace(1, 'offline')
        with patch.object(planning, 'generate_auxiliary', return_value='{"ranked_candidates":[0]}'):
            retained = planning.review_evidence(self.bot, c, rows, trace)
        self.assertEqual(len(retained), 48)
        items, text, _, _ = self.admission(retained)
        self.assertTrue(items)
        self.assertIn(GUARANTEE, text)

    def test_18_reject_all_is_not_reviewer_failure(self):
        c = self.contract(HARD_QUERY)[0]
        row = self.row(1, 'Irrelevant fixture description.')
        for failure in (False, True):
            trace = ChatTrace(1, 'offline')
            with patch.object(planning, 'generate_auxiliary', return_value='{"ranked_candidates":[],"reject_all":true}',
                              side_effect=TimeoutError('offline') if failure else None):
                result = planning.review_evidence(self.bot, c, [row], trace)
            self.assertEqual(bool(result), failure)
            self.assertEqual(trace.retrieval.reviewer_outcome['reject_all'], None if failure else True)

    def test_19_propositions_before_ordinary_depth(self):
        rows = [self.row(0, 'Ordinary detail. ' * 500, score=1000),
                self.row(1, SHIPPING, ['shipping']), self.row(2, GUARANTEE, ['guarantee']), self.row(3, REPEAT, ['guarantee'])]
        _, text, _, _ = self.admission(rows, budget=1200)
        for fact in (SHIPPING, GUARANTEE, REPEAT):
            self.assertIn(fact, text)

    def test_20_contradiction_before_duplicate_support(self):
        rows = [self.row(i, 'Shipping details are described in this policy. ' * 20, ['shipping'], score=10) for i in range(6)]
        rows += [self.row(9, SHIPPING, ['shipping'], score=.001)]
        _, text, trace, _ = self.admission(rows, budget=700)
        self.assertIn(SHIPPING, text)
        self.assertTrue(any(e['reason'] == 'admitted_required_proposition' for e in trace.retrieval.candidates[(1, 2009)].events))

    def test_21_final_context_including_annotations_is_capped(self):
        for budget in (0, 100, 1200, 4000, 7000, 10000):
            with self.subTest(budget=budget):
                items, text, trace, _ = self.admission(budget=budget, annotated=True)
                self.assertLessEqual(len(text), budget)
                self.assertEqual(trace.retrieval.context_assembly['context_budget_chars'], budget)
                if budget >= 4000:
                    self.assertTrue(items)

    def test_22_oversized_optional_does_not_evict_required(self):
        rows = [self.row(0, 'General detail. ' * 3000, score=100), self.row(1, SHIPPING, ['shipping'])]
        self.assertIn(SHIPPING, self.admission(rows, budget=500)[1])

    def test_23_whole_field_excerpt_retains_provenance(self):
        row = self.row(1, SHIPPING + '\n\n' + ('Unrelated body detail. ' * 1000), ['shipping'])
        items, text, trace, _ = self.admission([row], budget=600)
        self.assertEqual([i['chunk'].id for i in items], [2001])
        self.assertIn(SHIPPING, text)
        self.assertNotIn('Unrelated body detail', text)
        self.assertEqual(items[0]['document'].id, 1)
        self.assertEqual(items[0]['context_evidence_text'], SHIPPING)
        self.assertTrue(trace.retrieval.candidates[(1, 2001)].included_final_context)

    def test_24_single_atomic_condition_cannot_be_cut(self):
        row = self.row(1, SHIPPING + ' ' + ('Shipping conditions. ' * 1000) + ' However, repeat orders are excluded.', ['shipping'])
        items, text, trace, _ = self.admission([row], budget=200, annotated=True)
        self.assertEqual((items, text), ([], ''))
        self.assertEqual(rag._no_evidence_reply(trace, 'empty_context_after_validation'), (TEMPORARY_SERVICE_REPLY, [], []))

    def test_25_budget_terminal_suppresses_all_source_output(self):
        with patch.object(rag.POLICY.__class__, 'context_budget', return_value=1):
            result, trace, gen, _ = self.run_answer([self.row(1, SHIPPING)])
        self.assertEqual(result, (TEMPORARY_SERVICE_REPLY, [], []))
        self.assertEqual(trace.retrieval.source_suppression_reason, 'suppressed_context_failure')
        self.assertEqual(gen.call_count, 0)

    def test_26_partial_sources_only_reference_admitted_items(self):
        items, _, trace, _ = self.admission(annotated=True)
        sources, chunks = rag._format_sources(items), rag._format_retrieved_chunks(items)
        self.assertTrue(sources and chunks)
        self.assertEqual({c.chunk_id for c in trace.retrieval.candidates.values() if c.included_final_context},
                         {item['chunk'].id for item in items})

    def test_27_live_inventory_never_enters_context_assembly(self):
        with patch.object(rag, '_bounded_generation_context', side_effect=AssertionError('must not assemble')):
            result, trace, generate = prior.PostLiveCorrectnessTests.answer(self,
                'How many bottles of Turmeric Boost are in stock in your Mumbai warehouse right now?')
        self.assertEqual(result[1:], ([], []))
        self.assertEqual(trace.retrieval.terminal_response_category, 'live_data_unavailable')
        self.assertEqual(generate.call_count, 0)

    def test_28_monetary_annotations_keep_live_proven_roles(self):
        c = self.contract('Compare prices of Sea Essence Omega 3 and Turmeric Boost')[0]
        rows = [self.row(1, prior.SEA, ['price'], doc_id=1), self.row(2, prior.TURMERIC, ['price'], doc_id=2)]
        items, context, _, _ = self.admission(rows, contract=c, budget=9500, annotated=True)
        values = {(f.entity_document_id, f.price_type, f.value) for f in rag.collect_price_facts(items, c)}
        self.assertTrue({(1,'one_time','37.00'), (1,'subscription','35.15'), (1,'installment_payment','18.50'),
            (1,'per_day_cost','1.17'), (2,'one_time','33.00'), (2,'subscription','31.35'),
            (2,'per_day_cost','1.05'), (2,'financing_threshold','35.00')} <= values)
        self.assertNotIn((1,'subscription','18.50'), values)
        self.assertNotIn((2,'one_time','35.00'), values)
        self.assertLessEqual(len(context), 9500)

    def test_29_explicit_coa_identity_still_scoped(self):
        c = self.contract('What is the batch-specific certificate of analysis number for Sea Essence Omega 3?')[0]
        rows, _ = self.retrieve(c)
        items, _, _, _ = self.admission(rows, contract=c)
        self.assertEqual(c.permitted_document_ids, [1])
        self.assertTrue(items)
        self.assertEqual({i['document'].id for i in items}, {1})

    def test_30_final_provider_failure_remains_service_error(self):
        result, trace, gen, _ = self.run_answer([self.row(1, SHIPPING)], error=TimeoutError('offline'))
        self.assertEqual(result, (TEMPORARY_SERVICE_REPLY, [], []))
        self.assertEqual(trace.retrieval.terminal_reason, 'generation_provider_error')
        self.assertEqual(gen.call_count, 1)

    def test_31_foreign_tenant_and_bot_never_reach_admission(self):
        self.add_document(3, 'Foreign', org_id=99)
        self.add_document(4, 'Foreign bot', bot_id=99)
        self.db.commit()
        c = self.contract(HARD_QUERY)[0]
        with patch.object(rag, '_vector_candidate_ids', return_value=[(35,3,.1), (45,4,.1), (15,1,.2)]):
            rows, _ = self.retrieve(c)
        items, _, _, _ = self.admission(rows, contract=c)
        self.assertTrue(items)
        self.assertTrue(all(i['document'].organization_id == 1 and i['document'].bot_id == 1 for i in items))

    def test_32_lifecycle_and_profile_gates_precede_admission(self):
        from database.models import Chunk
        self.db.get(Chunk, 15).embedding_model = 'incompatible'
        self.db.get(Chunk, 25).status = 'processing'
        self.db.commit()
        c = self.contract(HARD_QUERY)[0]
        rows, _ = self.retrieve(c)
        items, _, _, _ = self.admission(rows, contract=c)
        self.assertTrue({15, 25}.isdisjoint(i['chunk'].id for i in items))

    def test_33_reviewer_bound_unchanged(self):
        c = self.contract(HARD_QUERY)[0]
        trace = ChatTrace(1, 'offline')
        with patch.object(planning, 'generate_auxiliary', side_effect=TimeoutError('offline')):
            retained = planning.review_evidence(self.bot, c, self.live_rows(c), trace)
        self.assertEqual(POLICY.reviewer_max, 48)
        self.assertEqual(trace.retrieval.stage_counts['reviewer_input'], 48)
        self.assertLessEqual(trace.retrieval.stage_counts['reviewer_visible'], 48)
        self.assertEqual(len(retained), 48)

    def test_34_exact_original_message_reaches_final_prompt(self):
        _, trace, gen, _ = self.run_answer([self.row(1, SHIPPING)])
        self.assertEqual(trace.retrieval.original_user_message, HARD_QUERY)
        self.assertIn('USER QUESTION\n' + HARD_QUERY, gen.call_args.kwargs['prompt'])

    def test_35_no_ai_io_inside_budget_assembly(self):
        c, rows, trace = self.prepared()
        with patch.object(planning, 'generate_auxiliary', side_effect=AssertionError('extra auxiliary')), \
             patch.object(rag, 'generate', side_effect=AssertionError('extra generation')), \
             patch.object(rag, 'generate_embedding', side_effect=AssertionError('extra embedding')):
            items, text, _, _ = rag._bounded_generation_context(rows, HARD_QUERY, 7000, c.mode, c, trace)
        self.assertTrue(items and text)

    def test_36_legacy_configuration_and_context_budget_unchanged(self):
        from services.hybrid_retrieval import hybrid_config
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(hybrid_config().lexical_backend, 'legacy')
        self.assertEqual((POLICY.default_context_chars, POLICY.comparison_context_chars), (10000, 9500))

    def test_37_phase2_neutral_admission_same_evidence(self):
        rows = [self.row(1, SHIPPING), self.row(2, GUARANTEE), self.row(3, REPEAT)]
        legacy = self.admission(rows, budget=1200)[1]
        fts = self.admission([dict(r, lexical_backend='postgres_fts') for r in rows], budget=1200)[1]
        for fact in (SHIPPING, GUARANTEE, REPEAT):
            self.assertIn(fact, legacy)
            self.assertIn(fact, fts)

    def test_38_cache_subject_and_amount_identity_preserved(self):
        c = self.contract(HARD_QUERY)[0]
        before = rag.semantic_cache_identity(self.bot, HARD_QUERY, [], c)
        self.admission(contract=c, annotated=True)
        self.assertEqual(before, rag.semantic_cache_identity(self.bot, HARD_QUERY, [], c))
        other = self.contract(HARD_QUERY.replace('$33', '$70'))[0]
        self.assertNotEqual(before, rag.semantic_cache_identity(self.bot, other.original_query, [], other))
        a, b = (self.contract(q)[0] for q in ('ingredients of Turmeric Boost', 'ingredients of Sea Essence Omega 3'))
        self.assertNotEqual(rag.semantic_cache_identity(self.bot, a.original_query, [], a),
                            rag.semantic_cache_identity(self.bot, b.original_query, [], b))

    def test_39_admission_order_is_deterministic(self):
        c, rows, _ = self.prepared()
        snapshots = []
        for _ in range(3):
            items, text, _, _ = self.admission(rows, contract=deepcopy(c), budget=7000, annotated=True)
            snapshots.append(([i['chunk'].id for i in items], text))
        self.assertEqual(snapshots, [snapshots[0]] * 3)

    def test_40_trace_admission_counts_and_reasons(self):
        items, _, trace, _ = self.admission(annotated=True)
        state = trace.retrieval.context_assembly
        self.assertEqual(state['retained_evidence_count_before_context'], 48)
        self.assertEqual(state['admitted_context_items'], len(items))
        self.assertEqual(state['excluded_context_items'], 48-len(items))
        self.assertTrue(state['evidence_existed_before_context'])
        self.assertEqual(state['context_assembly_status'], 'partial')
        self.assertTrue(state['context_budget_exhausted'])
        self.assertIsNone(state['context_assembly_failure_reason'])
        self.assertEqual(set(state['required_proposition_representatives_admitted']),
                         {'shipping_eligibility', 'guarantee_eligibility', 'repeat_purchase_condition'})
        self.assertEqual(state['required_proposition_representatives_excluded'], [])

    def test_41_no_caller_candidate_or_chunk_mutation(self):
        c, rows, _ = self.prepared()
        before = [(r['chunk'].content, dict(r.get('selection_signals', {})), list(r['required_fields'])) for r in rows]
        self.admission(rows, contract=c, annotated=True)
        self.assertEqual(before, [(r['chunk'].content, dict(r.get('selection_signals', {})), list(r['required_fields'])) for r in rows])

    def test_42_nonprice_multi_entity_fields_still_supplied(self):
        c = self.contract('Compare Sea Essence Omega 3 and Turmeric Boost on ingredients and directions')[0]
        rows = [self.row(1, 'Ingredients: Alpha and Beta.\n\nDirections: Take two capsules daily.', ['ingredients','directions'], doc_id=1),
                self.row(2, 'Ingredients: Gamma and Delta.\n\nDirections: Take one capsule daily.', ['ingredients','directions'], doc_id=2)]
        items, text, _, _ = self.admission(rows, contract=c, budget=1000)
        self.assertEqual({i['document'].id for i in items}, {1,2})
        for fact in ('Alpha and Beta', 'Gamma and Delta', 'two capsules daily', 'one capsule daily'):
            self.assertIn(fact, text)

    def test_43_trace_has_no_chunk_bodies_or_exception_text(self):
        _, _, trace, _ = self.admission()
        serialized = json.dumps(trace.retrieval.to_dict())
        self.assertNotIn(SHIPPING, serialized)
        self.assertNotIn(GUARANTEE, serialized)
        _, _, trace = self.prepared()
        self.assertEqual({v['stage'] for v in trace.retrieval.to_dict()['auxiliary_provider_failures']}, {'planner','reviewer'})

    def test_44_retrieval_exception_is_not_missing_knowledge(self):
        for reason in ('retrieval_provider_error', 'both_retrieval_channels_failed'):
            trace = ChatTrace(1, 'offline')
            self.assertEqual(rag._no_evidence_reply(trace, reason), (TEMPORARY_SERVICE_REPLY, [], []))
            self.assertEqual(trace.retrieval.terminal_response_category, 'temporary_service_failure')

    def test_45_active_crawl_boundary_remains(self):
        prior.PostLiveCorrectnessTests.test_63_active_crawl_scope_for_aliases(self)

    def test_46_model_call_counts_same_normal_path(self):
        with patch.object(planning, 'generate_auxiliary', side_effect=TimeoutError('offline')) as auxiliary, \
             patch.object(rag, 'generate_embedding', return_value=[0.0]*768) as embedding:
            _, _, generate = prior.PostLiveCorrectnessTests.answer(self, 'ingredients of Turmeric Boost')
        self.assertEqual((auxiliary.call_count, embedding.call_count, generate.call_count), (2,1,1))

    def test_47_both_modes_pass_bounded_context_to_generation(self):
        for strict in (True, False):
            with self.subTest(strict=strict), patch.object(rag.POLICY.__class__, 'context_budget', return_value=4000):
                _, trace, generate, _ = self.run_answer([self.row(1, SHIPPING), self.row(2, GUARANTEE)], strict=strict)
            self.assertEqual(generate.call_count, 1)
            context = generate.call_args.kwargs['prompt'].split('<untrusted_website_knowledge>\n', 1)[1].split('\n</untrusted_website_knowledge>', 1)[0]
            self.assertLessEqual(len(context), 4000)
            self.assertEqual(trace.retrieval.stage_counts['generation_context_chars'], len(context))

    def test_48_eligibility_mention_cannot_replace_explicit_contradiction(self):
        rows = [self.row(i, SHIPPING + f' Shipping region {i}.', ['shipping']) for i in range(10)]
        rows += [self.row(20, 'The guarantee covers first purchases only.\n\n' + REPEAT, ['guarantee'], score=.01)]
        _, text, _, _ = self.admission(rows, budget=350)
        self.assertIn(SHIPPING, text)
        self.assertIn(REPEAT, text)

    def test_49_omitted_clause_cannot_keep_full_chunk_reviewer_support(self):
        c = self.contract(HARD_QUERY)[0]
        row = self.row(1, SHIPPING + '\n\n' + GUARANTEE, ['shipping', 'guarantee'])
        trace = ChatTrace(1, 'offline')
        update_support(c, [row], trace)
        trace.retrieval.reviewer_outcome = {'proposition_support': [{
            'proposition_id': 'guarantee_eligibility', 'support_state': 'supported',
            'supporting_candidate_ids': [[1,2001]], 'contradicting_candidate_ids': []}]}
        supplied = dict(row, context_evidence_text=SHIPPING)
        rag._with_deterministic_facts(SHIPPING, [supplied], c, trace)
        p = next(p for p in c.requested_propositions if p.type == 'guarantee_eligibility')
        self.assertEqual(p.support_state, 'missing')
        self.assertEqual(p.unresolved_reason, 'context_budget_omitted_evidence')

    def test_50_optional_commercial_paragraph_never_character_sliced(self):
        from services.conversational_engine import _trim_evidence
        body = 'The offer costs $33. ' + ('Additional commercial conditions apply. ' * 50) + ' Repeat purchases are excluded.'
        self.assertEqual(_trim_evidence(body, 200), '')

    def compact_policy_rows(self):
        # Keep the original oversized reproduction unchanged. This additional
        # fixture supplies the compact policy paragraph reported in live Test 3
        # amid the same 48-item/10-document retained pool.
        c = self.contract(HARD_QUERY)[0]
        rows = self.live_rows(c)
        row = rows[45]
        rows[45] = dict(row, chunk=SimpleNamespace(**{**vars(row['chunk']),
            'content': SHIPPING + ' ' + GUARANTEE}))
        return rows

    def test_51_reported_policy_evidence_survives_actual_compound_budget(self):
        rows = self.compact_policy_rows()
        _, trace, generate, _ = self.run_answer(rows)
        self.assertEqual(trace.retrieval.context_assembly['context_budget_chars'], 3500)
        self.assertEqual(trace.retrieval.context_assembly['retained_evidence_count_before_context'], 48)
        context = generate.call_args.kwargs['prompt'].split('<untrusted_website_knowledge>\n', 1)[1].split('\n</untrusted_website_knowledge>', 1)[0]
        for fact in (SHIPPING, GUARANTEE, REPEAT):
            self.assertIn(fact, context)
        self.assertLessEqual(len(context), 3500)
        self.assertEqual(set(trace.retrieval.context_assembly['required_proposition_representatives_admitted']),
                         {'shipping_eligibility', 'guarantee_eligibility', 'repeat_purchase_condition'})


if __name__ == '__main__':
    unittest.main()
