"""Focused Phase 3.2 contract/grammar/security tests, offline only."""
from dataclasses import replace
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from services.resource_channels import ResourceProbe, ProbeVariant
from services.resource_probe_builder import build_resource_probes, strip_request, informative_tokens, MAX_VARIANTS, PROBE_VERSION
from services.resource_discovery import ResourceResolutionPolicy, ResolutionState
from services.retrieval_contracts import SoftSemanticScope, ResourceCandidate, KnowledgeResourceRef
from test_resource_discovery import ResourceFixture

def probes(q, members=(), state=None):
    c=SimpleNamespace(original_query=q, execution=SimpleNamespace(soft_scope=SoftSemanticScope(comparison_members=members)),
                      conversation_references=[],resolved_entities=[],mode="factual")
    return build_resource_probes(c,state or {})

def searches(p):
    return [v.text.casefold() for v in p.variants] or [p.text.casefold()]

class ProbeGrammarTests(unittest.TestCase):
    def test_wrapper_families(self):
        for prefix in ("Please show me the ", "Could you send me ", "Where can I find ",
                       "Where's your ", "I'm looking for ", "I think it was called ",
                       "I was looking for something called ", "How do I contact your "):
            with self.subTest(prefix=prefix):
                self.assertIn("silver mariner form",searches(probes(prefix+"Silver Mariner Form?")[0]))

    def test_identity_words_preserved(self):
        for noun in ("support","form","plan","program","policy"):
            self.assertEqual(strip_request("Customer "+noun+" Automation")[0],"Customer "+noun+" Automation")

    def test_original_span_preserved(self):
        q="  Could you send me Café-Mariné Form?!  "
        p=probes(q)[0]
        self.assertEqual(q,"  Could you send me Café-Mariné Form?!  ")
        self.assertIn("café",p.original_span.casefold())
        self.assertEqual(p.variants[0].priority,0)

    def test_one_not_globally_removed(self):
        self.assertIn("one frontier service", searches(probes("One Frontier Service")[0]))

    def test_comparison_inheritance_all_types(self):
        for kind in ("plan","service","course","form","program","document","location","permit"):
            with self.subTest(kind=kind):
                p=probes("",(f"Crimson Horizon {kind}","Golden Mariner one"))
                self.assertEqual(p[1].inherited_resource_type_hint,kind)
                self.assertEqual(p[1].text,"Golden Mariner one")
                self.assertIn(f"golden mariner {kind}",searches(p[1]))

    def test_conflicting_types_no_inheritance(self):
        p=probes("",("Crimson Plan","Golden Course","Silver one"))
        self.assertFalse(p[2].inherited_resource_type_hint)

    def test_category_vs_modified_name(self):
        for kind in ("service","plan","course","form","policy","location","document","department","certificate"):
            plural=kind[:-1]+"ies" if kind.endswith("y") else kind+"s"
            self.assertTrue(probes(f"What {plural} do you have?")[0].category_intent)
            self.assertFalse(probes(f"Show me your Mariner {kind}.")[0].category_intent)

    def test_x_for_y(self):
        for left,right in (("brochure","Silver Flight course"),("form","Mariner students"),("policy","returns")):
            p=probes(f"Can you send me the {left} for the {right}?")[0]
            self.assertIn((right+" "+left).casefold(),searches(p))
            self.assertEqual(p.explicit_resource_type_hint,left)

    def test_preposition_not_reordered_arbitrarily(self):
        p=probes("For Your Tomorrow")[0]
        self.assertNotIn("qualified_object", [v.provenance for v in p.variants])

    def test_no_synonym_invention(self):
        p=probes("Do you build websites?")[0]
        self.assertNotIn("development"," ".join(searches(p)))
        self.assertNotIn("automation"," ".join(searches(probes("automate customer support")[0])))

    def test_relation_does_not_invent_middle(self):
        for q in ("What is between Quartz Plan and Ruby Plan?", "Show me the next tier", "Which is cheapest?"):
            self.assertEqual(probes(q)[0].relation_intent,"structured_relation_required")

    def test_comparison_not_ordering(self):
        self.assertFalse(probes("What is the difference between Quartz and Ruby?")[0].relation_intent)

    def test_short_informative(self):
        self.assertEqual(informative_tokens("Oak Design service"),{"oak","design"})
        for q in ("AI","HR","Pro","PDF","Form","Plan"):
            self.assertFalse(informative_tokens(q))

    def test_numbers_unicode(self):
        self.assertEqual(informative_tokens("Café ２０２６"),{"café","2026"})

    def test_variant_limit(self):
        p=probes("Please could you send me the form for the Golden Horizon?")[0]
        self.assertLessEqual(len(p.variants),MAX_VARIANTS)

    def test_logical_limit(self):
        with self.assertRaises(ValueError):
            probes("",tuple("Entry "+str(i) for i in range(9)))

    def test_pathological_input(self):
        for q in ("x"*8193,"(" * 9000,"please "*2000):
            with self.assertRaises(ValueError):
                probes(q)

    def test_empty_query(self):
        p=probes("")[0]
        self.assertEqual(p.text,"")
        self.assertFalse(p.category_intent)

    def test_genuine_typed_followup(self):
        state={"active_subjects":[{"name":"Mariner Program","document_id":1}]}
        p=probes("What about this program?",state=state)[0]
        self.assertEqual(p.probe_kind,"conversation_reference")

    def test_explicit_switch_ignores_history(self):
        state={"active_subjects":[{"name":"Mariner Program","document_id":1}]}
        p=probes("Tell me about Stellar Course",state=state)[0]
        self.assertNotIn("mariner"," ".join(searches(p)))

    def test_other_one_is_not_the_only_active_resource(self):
        state={"active_subjects":[{"name":"Mariner Program","document_id":1}]}
        p=probes("What about the other one?",state=state)[0]
        self.assertNotIn("mariner"," ".join(searches(p)))

    def test_named_demonstrative_does_not_inherit(self):
        state={"active_subjects":[{"name":"Mariner Program","document_id":1}]}
        p=probes("Tell me about this Stellar",state=state)[0]
        self.assertNotIn("mariner"," ".join(searches(p)))

    def test_runtime_anti_overfit(self):
        from pathlib import Path
        root=Path(__file__).parent/"services"
        for name in ("resource_probe_builder.py","resource_channels.py","resource_discovery.py","resource_scope_adapter.py"):
            text=(root/name).read_text(encoding="utf-8").casefold()
            for banned in ("wowmd","turmeric","collagen","chocolate","refund policy","web development","professional one","5129","5134"):
                self.assertNotIn(banned,text,name)
            for number in range(3001,3023):
                self.assertNotIn(str(number),text,name)

class ProbeRuntimeTests(ResourceFixture):
    def seed(self):
        self.add(1,"Crimson Horizon plan",kind="plan",aliases=["Crimson"])
        self.add(2,"Golden Mariner plan",kind="plan",aliases=["Golden"])
        self.add(3,"Golden Mariner course",kind="course",aliases=["Golden"])
        self.project(1,2,3)

    def test_actual_type_ellipsis_disambiguates(self):
        self.seed()
        c=self.contract("Crimson Horizon plan or Golden Mariner one")
        self.assertEqual(c.permitted_document_ids,[1,2],c.to_debug_dict())

    def test_exclusion_unchanged(self):
        self.seed()
        c=self.contract("Exclude Crimson Horizon plan and tell me about Golden Mariner plan")
        self.assertEqual(c.permitted_document_ids,[2])

    def test_wrapper_exact_preserved(self):
        self.add(1,"Show Me Your Tomorrow",kind="service")
        self.add(2,"Tomorrow",kind="service")
        self.project(1,2)
        self.assertEqual(self.contract("Show Me Your Tomorrow").permitted_document_ids,[1])

    def test_exact_collision_not_cleaned_away(self):
        self.add(1,"Show Me Horizon")
        self.add(2,"Show Me Horizon")
        self.add(3,"Horizon")
        self.project(1,2,3)
        self.assertTrue(self.contract("Show Me Horizon").requires_clarification)

    def test_incomplete_comparison_stays_broad(self):
        self.seed()
        c=self.contract("Crimson Horizon plan or Unknown Lunar one")
        self.assertIsNone(c.permitted_document_ids)
        self.assertEqual(c.execution.soft_scope.state.value,"incomplete_comparison")

    def test_type_cannot_expand_empty_hard_scope(self):
        self.seed()
        result=self.service.discover(self.db,replace(self.hard,authorized_document_ids=()),
            probes("",("Crimson Horizon plan","Golden Mariner one")))
        self.assertFalse(result.candidates)

    def test_hard_document_scope(self):
        self.seed()
        result=self.service.discover(self.db,replace(self.hard,authorized_document_ids=(1,)),
            probes("Show me Golden Mariner plan"))
        self.assertFalse(result.candidates)

    def test_lifecycle_not_restored_by_wrapper(self):
        self.seed()
        from database.models import Document
        self.db.get(Document,1).status="deleted";self.db.commit()
        r=self.service.discover(self.db,self.hard,probes("Can you send me Crimson Horizon plan?"))
        self.assertFalse(any(1 in c.resource.document_ids for c in r.candidates))

    def test_navigation_not_factual_metadata(self):
        self.seed()
        from database.resource_models import KnowledgeResource
        self.db.query(KnowledgeResource).update({KnowledgeResource.summary:"UNSUPPORTED SECRET FACT"})
        self.db.commit()
        c=self.contract("Show me Crimson Horizon plan")
        self.assertEqual(c.permitted_document_ids,[1])
        self.assertNotIn("UNSUPPORTED",json.dumps(c.execution.resource_discovery))
        self.assertTrue(c.execution.soft_scope.resolved_resources[0].url)

    def test_variant_scores_not_added(self):
        self.seed()
        a=self.service.discover(self.db,self.hard,[ResourceProbe("Crimson Horizon plan")])
        p=ResourceProbe("Crimson Horizon plan",variants=(ProbeVariant("Crimson Horizon plan","explicit_user",0),)*4)
        b=self.service.discover(self.db,self.hard,[p])
        self.assertEqual(dict(a.resolutions[0].candidate.scores)["rrf"],dict(b.resolutions[0].candidate.scores)["rrf"])

    def test_trace_and_cache_hints(self):
        self.seed()
        p=probes("Please show me Golden Mariner plan")
        a=self.service.discover(self.db,self.hard,p)
        b=self.service.discover(self.db,self.hard,[replace(p[0],explicit_resource_type_hint="course")])
        self.assertNotEqual(a.cache_identity(self.hard),b.cache_identity(self.hard))
        trace=a.trace()["resolutions"][0]
        self.assertIn("original_span_sha256",trace)
        self.assertTrue(trace["variants"])
        self.assertEqual(a.cache_identity(self.hard)["probe_contract"],PROBE_VERSION)

    def test_one_token_fuzzy_never_certain(self):
        self.seed()
        self.assertFalse(self.service.discover(self.db,self.hard,probes("Mariner")).resolutions[0].candidate)

    def test_type_words_do_not_create_competing_identity(self):
        self.add(1,"Maple Stone appointment",kind="appointment")
        self.add(2,"Distant Stone booking appointment",kind="appointment")
        self.project(1,2)
        c=self.contract("Maplx Stone appointment")
        self.assertEqual(c.permitted_document_ids,[1])

    def test_specific_name_defeats_category_hypothesis(self):
        self.add(1,"Forms",kind="page")
        self.add(2,"Ocean Request",kind="form")
        self.project(1,2)
        c=self.contract("Show me Forms")
        self.assertEqual(c.permitted_document_ids,[1])

    def test_token_set_alone_cannot_resolve(self):
        from services.retrieval_contracts import KnowledgeResourceRef,ResourceCandidate
        c=ResourceCandidate(KnowledgeResourceRef("r",1,1,"Blue Ocean Star",document_ids=(1,)),
            scores=(("token_set",100),("token_coverage",1),("token_sort",70),("numeric_agreement",1)),
            reason_codes=("identity_term",))
        r=ResourceResolutionPolicy().resolve(ResourceProbe("Blue Ocean"),[c])
        self.assertNotEqual(r.state,ResolutionState.RESOLVED)

    def test_development_reordered_full_name_not_longer_qualified_name(self):
        for n,kind in enumerate(("service","form","guide"),1):
            self.add(n*10,f"Moss Cedar {kind}",kind=kind)
            self.add(n*10+1,f"Auxiliary Moss Cedar {kind}",kind=kind)
        self.project(10,11,20,21,30,31)
        for n,kind in enumerate(("service","form","guide"),1):
            c=self.contract(f"Cedar Moss {kind}")
            self.assertEqual(c.permitted_document_ids,[n*10])

    def test_development_competing_token_permutations_ambiguous(self):
        self.add(1,"Silver Birch Permit",kind="permit")
        self.add(2,"Birch Silver Permit",kind="permit")
        self.project(1,2)
        c=self.contract("Permit Birch Silver")
        self.assertTrue(c.requires_clarification)

    def test_development_reordering_preserves_digits(self):
        self.add(1,"Route Charter 45",kind="document")
        self.project(1)
        self.assertEqual(self.contract("45 Charter Route").permitted_document_ids,[1])
        self.assertIsNone(self.contract("46 Charter Route").permitted_document_ids)

    def test_development_distinctive_stem_with_explicit_type(self):
        self.add(1,"Enrollment Form",kind="form")
        self.add(2,"Certification Form",kind="form")
        self.project(1,2)
        self.assertEqual(self.contract("Enrolment form").permitted_document_ids,[1])
        self.assertIsNone(self.contract("HR form").permitted_document_ids)

    def test_development_nested_comparison_variants(self):
        self.add(1,"Silver Guide",kind="guide")
        self.add(2,"Golden Guide",kind="guide")
        self.project(1,2)
        c=self.contract("Do you have a Silver edition of this guide or only the Golden one?")
        self.assertEqual(c.permitted_document_ids,[1,2],c.to_debug_dict())

    def test_development_reported_name_with_request_tail(self):
        self.add(1,"Mariner Harbor",aliases=["Duo"])
        self.add(2,"Cobalt Vista",aliases=["Duo"])
        self.project(1,2)
        c=self.contract("I think the service was called Duo — could you show me the correct one?")
        self.assertTrue(c.requires_clarification,c.to_debug_dict())

    def test_open_ended_custom_type_category(self):
        self.add(1,"Silver Charter",kind="custom_registry")
        self.add(2,"Golden Charter",kind="custom_registry")
        self.project(1,2)
        c=self.contract("What custom registries do you have?")
        self.assertIsNone(c.permitted_document_ids)
        self.assertEqual({d for a in c.execution.soft_scope.resource_candidates for d in a.resource.document_ids},{1,2})

    def test_custom_type_inheritance_from_authorized_context(self):
        self.add(1,"Silver Horizon registry",kind="registry")
        self.add(2,"Golden Mariner registry",kind="registry")
        self.project(1,2)
        self.assertEqual(self.contract("Silver Horizon registry or Golden Mariner one").permitted_document_ids,[1,2])

    def test_no_new_model_call(self):
        self.seed()
        with patch("services.resource_scope_adapter.ResourceDiscoveryService", return_value=self.service), patch("services.rag_planning.plan_query",return_value=None) as planner:
            c=self.contract("Show me Crimson Horizon plan")
        self.assertEqual(c.permitted_document_ids,[1])
        self.assertLessEqual(planner.call_count,1)

if __name__=="__main__":
    unittest.main()
