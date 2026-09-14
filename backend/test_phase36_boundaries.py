"""Actual retrieval/selection/context boundaries, synthetic SQL only."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from types import SimpleNamespace as NS

from services import rag_service as rag
from services.resource_discovery import numeric_relation
from services.retrieval_contracts import HardKnowledgeScope
from test_required_evidence_retention import retrieve_fixture, fixture_database
from test_phase_l3_multi_entity_conversational_rag import document, chunk
from test_phase35_live_repair import contract, item
from services.requested_propositions import bind_field_obligations


class Boundaries(unittest.TestCase):
    def test_explicit_versions_years_alphanumeric_constraints(self):
        for asked,stored,expected in [
            ('Atlas 2025','Atlas 2026','conflict'),('Atlas','Atlas 2026','no_query_numeric_constraint'),
            ('Atlas X12','Atlas Y12','conflict'),('Atlas v3.1','Atlas v3.2','conflict'),
            ('Atlas 3','Atlas 3.1','partial_or_ambiguous'),('Atlas 3.1','Atlas 3','partial_or_ambiguous'),
            ('Atlas v3','Atlas','partial_or_ambiguous'),('Atlas 3 4','Atlas 4 3','conflict'),
            ('Atlas X12','Atlas X12','exact_match'),('Atlas 2026','Atlas 2026','exact_match')]:
            with self.subTest(asked=asked,stored=stored):self.assertEqual(numeric_relation(asked,stored),expected)

    def test_actual_sql_field_search_to_context_preserves_use_and_stage(self):
        docs=[document(1,'Cedar Adapter'),document(2,'Birch Adapter')]
        pairs=[]
        for d in docs:
            texts=['## How soon will I see results?\n\nProgress varies over time.',
                   'Take 1 unit 2–3 times daily with meals.',
                   '## What to Expect\n\n2–5 MONTHS',
                   '### Early comfort support\n\nComfort may improve with consistent use. Individual experiences vary.',
                   '## Other details\n\nOptional information.']
            for i,t in enumerate(texts):
                c=chunk(d.id*100+i,i,t);c.document_id=d.id;pairs.append((c,d))
        # The legacy fixture's unused with_trace path predates required trace
        # constructor arguments. Supply a real trace, without changing it.
        from services.observability_service import ChatTrace
        tr=ChatTrace(1,'phase36')
        with patch.object(rag,'ChatTrace',return_value=tr):
            rows,c,tr=retrieve_fixture(docs,pairs,'Compare Cedar Adapter and Birch Adapter on directions and results timelines',with_trace=True)
        for d in (1,2):
            ids={r['chunk'].id for r in rows if r['document'].id==d}
            self.assertTrue({d*100+1,d*100+2,d*100+3}<=ids)
            bundled=[b for r in rows if r['document'].id==d for b in r.get('evidence_bundles',[])]
            self.assertTrue(any(b['field']=='results_timeframe' and d*100+3 in b['chunk_ids'] for b in bundled))
        used,context,_,_=rag._bounded_generation_context(rows,c.original_query,3000,c.mode,c,tr)
        self.assertIn('2–5 MONTHS Early comfort support',context)
        self.assertIn('2–3 times daily with meals',context)
        self.assertLessEqual(len(context),3000)
        self.assertEqual({r['document'].id for r in used},{1,2})

    def test_cached_bundles_round_trip_without_aliasing(self):
        docs=[document(1,'Cedar Adapter')]
        source=item(1,101,'Directions: use daily.',['directions'])
        source['chunk'].embedding=[0.]
        source['evidence_bundles']=[dict(document_id=1,field='directions',primary_chunk_id=101,chunk_ids=[101],quality='field_value')]
        with fixture_database(docs,[(source['chunk'],docs[0])]) as db, patch.object(rag,'_RETRIEVAL_CACHE',{}), patch.object(rag,'retrieve_relevant_chunks',return_value=[source]) as retrieve:
            rag.retrieve_relevant_chunks_cached(db,1,'Cedar Adapter directions')
            result=rag.retrieve_relevant_chunks_cached(db,1,'Cedar Adapter directions')
            self.assertEqual(retrieve.call_count,1)
            self.assertEqual(result[0]['evidence_bundles'],source['evidence_bundles'])
            result[0]['evidence_bundles'][0]['chunk_ids'].append(777)
            self.assertEqual(source['evidence_bundles'][0]['chunk_ids'],[101])

    def test_obligation_matrix_never_exceeds_eight_by_twelve(self):
        c=contract(('price','directions'))
        c.resolved_entities=[replace(c.resolved_entities[0],document_id=n) for n in range(1,20)]
        c.requested_fields=['custom_'+str(n) for n in range(20)]
        bind_field_obligations(c)
        self.assertEqual(len(c.requested_propositions),96)

    def test_non_adjacent_foreign_document_cannot_join_section(self):
        d=document(1,'Cedar Adapter')
        a=chunk(1,0,'## What to expect\n\n2–5 months');a.document_id=1
        b=chunk(2,1,'### Early support\n\nUnsupported foreign body.');b.document_id=2
        self.assertNotIn(b,rag._select_complete_field_evidence([a,b],'results_timeframe',d))

    def test_refund_window_not_promoted_to_result_stage(self):
        d=document(1,'Cedar Adapter')
        a=chunk(1,0,'## Refund eligibility\n\n2–5 months');a.document_id=1
        b=chunk(2,1,'### Refund request\n\nRefund terms follow.');b.document_id=1
        self.assertEqual(rag._select_complete_field_evidence([a,b],'results_timeframe',d),[])

    def test_query_parameters_preserved_not_invented(self):
        row=item(1,1,'A booking resource.')
        url='https://fixture.test/book?slot=early&size=2'
        row['document'].canonical_url=url
        self.assertIn(url,rag._validate_answer_links('[Book]('+url+')',[row]))
        self.assertNotIn('https://',rag._validate_answer_links('[Book](https://fixture.test/book?slot=late&size=2)',[row]))

    def test_bare_unknown_url_removed_without_rewriting_fact(self):
        answer='Use daily. https://foreign.test/buy'
        self.assertEqual(rag._validate_answer_links(answer,[item(1,1,'Use daily.')]),'Use daily. ')

    def test_source_cards_follow_final_evidence_not_authorized_catalog(self):
        docs=[document(1,'Cedar Adapter'),document(2,'Birch Adapter'),document(3,'Willow Adapter')]
        pairs=[]
        for d in docs:
            c=chunk(d.id,0,'Directions: Take 1 unit daily.');c.document_id=d.id;pairs.append((c,d))
        rows,c,_=retrieve_fixture(docs,pairs,'Compare Cedar Adapter and Birch Adapter on directions')
        used,context=rag.compress_and_rerank_chunks(rows,c.original_query,3000,c.mode,c)
        self.assertEqual({s['document_id'] for s in rag._format_sources(used)},{1,2})
        self.assertNotIn('Willow Adapter',context)

    def test_policy_source_that_materially_supplies_context_is_not_hidden(self):
        rows=[item(1,1,'Directions: use daily.'),item(2,2,'Refund policy: eligible first purchase only.')]
        self.assertEqual({s['document_id'] for s in rag._format_sources(rows)},{1,2})

    def test_admitted_numeric_bundle_and_canonical_header_keep_field_support(self):
        from services.observability_service import ChatTrace
        from services.requested_propositions import update_support
        c=contract(('results_timeframe','directions','link'))
        rows=[]
        for d in (1,2):
            rows.extend([item(d,d*10,'## What to Expect\n\n2–5 MONTHS',['results_timeframe']),
                         item(d,d*10+1,'### Early comfort\n\nComfort may improve with consistent use.',['results_timeframe']),
                         item(d,d*10+2,'Directions: use 2 units daily with protective gloves.',['directions'])])
            for index,row in enumerate(rows[-3:]):row['chunk'].chunk_index=index
        bind_field_obligations(c)
        tr=ChatTrace(1,'phase36')
        for p in c.requested_propositions:
            refs=[[r['document'].id,r['chunk'].id] for r in rows
                  if r['document'].id==p.applicable_entity and (p.requested_field in r['required_fields'] or p.requested_field=='link')]
            tr.retrieval.reviewer_outcome.setdefault('proposition_support',[]).append(dict(
                proposition_id=p.id,support_state='supported',supporting_candidate_ids=refs,contradicting_candidate_ids=[]))
        update_support(c,rows,tr)
        used,context,_,_=rag._bounded_generation_context(rows,c.original_query,5000,c.mode,c,tr)
        self.assertIn('2–5 MONTHS Early comfort',context)
        self.assertTrue(all(p.support_state=='supported' for p in c.requested_propositions))
        self.assertTrue(all('context_field_evidence' in r for r in used))

    def test_omitted_field_cannot_be_certified_by_other_retained_field(self):
        from services.requested_propositions import RequestedProposition,proposition_matches
        row=item(1,1,'Directions: use daily. Features: durable.',['directions','features'])
        row['context_field_evidence']={'features':['Features: durable.']}
        p=RequestedProposition('field:1:directions','requested_field','directions',(0,10),applicable_entity=1,requested_field='directions')
        self.assertFalse(proposition_matches(p,row))

    def test_direction_conditions_are_not_satisfied_by_action_alone(self):
        for source,draft in [('Use 2 units daily with protective gloves.','Use 2 units daily.'),
                             ('Submit 1 form before installation.','Submit 1 form.'),
                             ('Apply 1 coat at room temperature.','Apply 1 coat.')]:
            with self.subTest(source=source):
                row=item(1,1,source,['directions'])
                row['context_field_evidence']={'directions':[source]}
                self.assertTrue(rag._direction_conditions_missing(draft,[row]))

    def test_direction_conditions_accept_retained_wording(self):
        source='Use 2 units daily with protective gloves.'
        row=item(1,1,source,['directions'])
        row['context_field_evidence']={'directions':[source]}
        self.assertEqual(rag._direction_conditions_missing(source,[row]),[])

    def test_unadmitted_direction_conditions_are_not_required(self):
        row=item(1,1,'Use 2 units with protective gloves.',['directions'])
        row['context_field_evidence']={'features':['Portable design.']}
        self.assertEqual(rag._direction_conditions_missing('Portable design.',[row]),[])

if __name__=='__main__':unittest.main()
