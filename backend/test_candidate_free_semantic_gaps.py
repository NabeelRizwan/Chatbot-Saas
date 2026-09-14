"""Phase 3.4 frozen classifier fixture; EMPTY channel results are intentional.

192 cases, 12 domains, fixed 144/48 split created before runtime repair.
180 cases inject zero candidates; 12 collision cases use real authorized exact
SQL/hydration. This is NOT a pg_trgm/FTS approximation or PostgreSQL acceptance.
"""
from dataclasses import dataclass, replace
import json
import unittest
from unittest.mock import patch

from test_resource_discovery import ResourceFixture, SQLiteTestChannel
from services.resource_channels import ChannelBatch, ResourceProbe, FeatureUnavailable
from services.resource_discovery import ResourceDiscoveryService, ResolutionState


DOMAINS = (
    ("architecture", "design office interiors", "lighting and acoustics", "service for planning accessible buildings"),
    ("software", "develop mobile applications", "hosting and backups", "software plan for distributed teams"),
    ("education", "train laboratory assistants", "robotics and electronics", "course for learning advanced robotics"),
    ("healthcare_information", "schedule patient visits", "appointments and referrals", "guide for managing clinical appointments"),
    ("accounting", "prepare business taxes", "payroll and taxation", "form for reporting employee expenses"),
    ("legal", "review commercial leases", "contracts and licensing", "service for reviewing rental agreements"),
    ("repair", "repair gaming laptops", "batteries and screens", "appointment for replacing damaged keyboards"),
    ("logistics", "track freight shipments", "warehousing and distribution", "plan for managing overseas deliveries"),
    ("hospitality", "reserve conference rooms", "catering and accommodation", "form for booking group accommodation"),
    ("agriculture", "monitor irrigation systems", "soil and rainfall", "service for managing greenhouse irrigation"),
    ("arts", "restore antique paintings", "framing and conservation", "course for restoring historical sculptures"),
    ("custom_resources", "coordinate volunteer assignments", "rosters and availability", "permit for supervising community events"),
)


@dataclass(frozen=True)
class GapCase:
    key: str
    domain: str
    text: str
    family: str
    eligible: bool
    basis: str
    split: str


def cases():
    rows = []
    short = ("AI", "Pro", "PDF", "service", "plan", "form", "support", "HR", "x", "page", "guide", "contact")
    noise = ("", "  ", "?!", "...", "😀", "xx zz", "a b", "! @ #", "--", "1 2", "qz xx", "🙂🙂")
    for i, (domain, action, concepts, rich) in enumerate(DOMAINS):
        templates = (
            (action, "capability", True, "candidate_free_informative"),
            (f"Can you {action}?", "capability_wrapper", True, "candidate_free_informative"),
            (concepts, "multi_concept", True, "candidate_free_informative"),
            (rich, "rich_description", True, "candidate_free_informative"),
            (f"I'm looking for someone to {action}.", "current_request", True, "candidate_free_informative"),
            (f"Unlisted {domain} orbital research station", "descriptive_unknown", True, "candidate_free_informative"),
            (short[i], "short", False, "insufficient_input"),
            (f"Please show me the {short[i]}", "short_wrapper", False, "insufficient_input"),
            (noise[i], "noise", False, "insufficient_input"),
            ("could would please", "filler", False, "insufficient_input"),
            ("What services do you offer?", "category", False, "category"),
            (f"What comes between Bronze {domain} and Gold {domain}?", "relation", False, "structured_relation_required"),
            (f"Maple {domain} Advisory", "exact_collision", False, "ambiguity"),
            (action, "technical", False, "technical_failure"),
            (action, "hard_empty", False, "empty_hard_scope"),
            ("I just need something please", "uninformative_request", False, "insufficient_input"),
        )
        for j, (text, family, eligible, basis) in enumerate(templates):
            rows.append(GapCase(f"{domain}:{family}", domain, text, family, eligible, basis,
                                "heldout" if (i + j) % 4 == 0 else "development"))
    return tuple(rows)


class EmptyChannel:
    """Injected recorded channel outcome; never claims to emulate PostgreSQL."""
    def __init__(self, name, *, failure=False):
        self.name, self.failure = name, failure

    def search(self, db, hard, probe, limit):
        if self.failure:
            raise FeatureUnavailable("synthetic unavailable channel")
        return ChannelBatch()


def empty_service(*, failure=False):
    return ResourceDiscoveryService([EmptyChannel(n, failure=failure)
                                    for n in ("exact", "fts", "trigram", "metadata")])


def populate(f):
    f.add(900, "Unrelated Authorized Reference")
    ids = [900]
    for i, (domain, *_) in enumerate(DOMAINS):
        for n in (1000 + i*2, 1001 + i*2):
            f.add(n, f"Maple {domain} Advisory")
            ids.append(n)
    f.project(*ids)


def run_case(f, case):
    probe = ResourceProbe(case.text, original_span=case.text,
                          category_intent=case.family == "category",
                          relation_intent="structured_relation_required" if case.family == "relation" else "")
    hard = replace(f.hard, authorized_document_ids=()) if case.family == "hard_empty" else f.hard
    channels = [SQLiteTestChannel("exact")] if case.family == "exact_collision" else None
    svc = ResourceDiscoveryService(channels) if channels else empty_service(failure=case.family == "technical")
    result = svc.discover(f.db, hard, (probe,))
    r = result.resolutions[0]
    gap = getattr(r, "semantic_gap", None)
    expected_state = ResolutionState.AMBIGUOUS if case.family == "exact_collision" else ResolutionState.UNRESOLVED
    eligible = bool(gap and gap.eligible_for_optimizer)
    basis = gap.basis if gap else None
    correct = (eligible == case.eligible and basis == case.basis and r.state == expected_state and r.candidate is None)
    count_ok = len(r.alternatives) == (2 if case.family == "exact_collision" else 0)
    return dict(key=case.key, family=case.family, split=case.split, pass_=correct and count_ok,
                eligible=eligible, expected_eligible=case.eligible, basis=basis, state=r.state.value,
                candidates=len(r.alternatives), false_resolution=r.candidate is not None,
                leaks=sum(c.resource.organization_id != hard.organization_id or c.resource.bot_id != hard.bot_id
                          for c in result.candidates))


def evaluate(f, split):
    rows = [run_case(f, c) for c in cases() if c.split == split]
    return dict(split=split, count=len(rows), correct=sum(r['pass_'] for r in rows),
                eligibility_accuracy=sum(r['eligible'] == r['expected_eligible'] for r in rows)/len(rows),
                false_resolutions=sum(r['false_resolution'] for r in rows), leaks=sum(r['leaks'] for r in rows), rows=rows)


class CandidateFreeTests(ResourceFixture):
    def test_recorded_postgres_zero_candidate_probe(self):
        self.add(900, "Unrelated Authorized Reference"); self.project(900)
        result = empty_service().discover(self.db, self.hard, (ResourceProbe("build websites"),))
        row = result.resolutions[0]
        self.assertEqual(row.state, ResolutionState.UNRESOLVED)
        self.assertEqual(len(row.alternatives), 0)
        self.assertIsNone(row.candidate)
        self.assertIn("query_optimizer_eligible", row.reason_codes)

    def test_frozen_matrix(self):
        populate(self)
        self.assertEqual(len(cases()), 192)
        self.assertEqual(len({c.domain for c in cases()}), 12)
        for split in ("development", "heldout"):
            report = evaluate(self, split)
            self.assertEqual(report['correct'], report['count'], [r for r in report['rows'] if not r['pass_']])
            self.assertEqual(report['leaks'], 0)
            self.assertEqual(report['false_resolutions'], 0)

    def test_twenty_four_unrelated_same_class(self):
        populate(self)
        positives = [c for c in cases() if c.family == "capability"]
        negatives = [next(c for c in cases() if c.domain == domain and c.family == ("short", "category", "relation")[i % 3])
                     for i, (domain, *_) in enumerate(DOMAINS)]
        self.assertEqual(len(positives), 12); self.assertEqual(len(negatives), 12)
        for case in positives + negatives:
            with self.subTest(case=case.key): self.assertTrue(run_case(self, case)['pass_'])

    def test_next_plan_relation_is_not_a_candidate_free_opportunity(self):
        self.add(900, "Unrelated Authorized Reference"); self.project(900)
        self.service = empty_service()
        c = self.contract("What's your next plan after Starter?")
        self.assertNotIn("query_optimizer_eligible", c.execution.soft_scope.reason_codes)
        self.assertIn("structured_relation_required", c.execution.soft_scope.reason_codes)

    def test_candidate_free_comparison_preserves_hard_scope_and_known_member(self):
        self.add(1, "Cobalt Legal Advisory"); self.add(2, "Unrelated Authorized Reference"); self.project(1, 2)
        class MemberChannel:
            def __init__(self, name): self.name = name
            def search(self, db, hard, probe, limit):
                if probe.comparison_member_index == 0: return ChannelBatch()
                return SQLiteTestChannel(self.name).search(db, hard, probe, limit)
        self.service = ResourceDiscoveryService([MemberChannel(n) for n in ('exact', 'fts', 'trigram', 'metadata')])
        question = "Do you review commercial leases or mostly do Cobalt Legal Advisory?"
        c = self.contract(question)
        rows = c.execution.resource_discovery['resolutions']
        self.assertEqual(rows[0]['candidate_count'], 0)
        self.assertEqual(rows[0]['semantic_gap']['basis'], 'candidate_free_informative')
        self.assertEqual(rows[1]['selected_resource_id'], 'org:1:bot:1:resource:1')
        self.assertEqual(c.execution.soft_scope.state.value, 'incomplete_comparison')
        self.assertIsNone(c.permitted_document_ids)
        self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)
        self.assertEqual(c.original_query, question)
        self.assertIn(question, c.retrieval_query)
        self.assertEqual(c.execution.hard_scope.organization_id, 1)
        self.assertEqual(c.execution.hard_scope.bot_id, 1)

    def test_candidate_backed_ambiguity_keeps_clarification(self):
        self.add(1, 'Managed Lighting and Acoustics Service', kind='service')
        self.add(2, 'Express Lighting and Acoustics Service', kind='service'); self.project(1, 2)
        c = self.contract('Which service would I need if I want both lighting and acoustics?')
        row = c.execution.resource_discovery['resolutions'][0]
        self.assertEqual(row['semantic_gap']['basis'], 'candidate_backed_insufficient')
        self.assertTrue(row['semantic_gap']['eligible_for_optimizer'])
        self.assertGreater(row['candidate_count'], 0)
        self.assertTrue(c.requires_clarification)
        self.assertFalse(c.execution.scope_decision.exact_narrowing_applied)

    def test_category_parser_and_exact_category_name_precedence(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        self.service = empty_service()
        for question in ('What services do you offer?', 'What courses are available?'):
            c = self.contract(question)
            self.assertEqual(c.execution.resource_discovery['resolutions'][0]['semantic_gap']['basis'], 'category')
            self.assertNotIn('query_optimizer_eligible', c.execution.soft_scope.reason_codes)

    def test_current_language_only_not_history_or_planner(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        for provenance in ('conversation_state', 'planner_hint', 'full_query', 'wrapper_stripped'):
            r = empty_service().discover(self.db, self.hard, (ResourceProbe('repair gaming laptops', provenance),)).resolutions[0]
            self.assertFalse(r.semantic_gap.eligible_for_optimizer)
            self.assertFalse(r.semantic_gap.explicit_current_user_span)

    def test_restricted_and_empty_authorization_are_never_expanded(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        for ids in ((), (1,)):
            hard = replace(self.hard, authorized_document_ids=ids)
            result = empty_service().discover(self.db, hard, (ResourceProbe('prepare business taxes'),))
            self.assertEqual(hard.authorized_document_ids, ids)
            self.assertEqual(result.candidates, ())
            self.assertEqual(result.resolutions[0].semantic_gap.eligible_for_optimizer, bool(ids))
        with patch.object(self.db, 'execute', side_effect=AssertionError('empty scope must not query')):
            empty_service().discover(self.db, replace(self.hard, authorized_document_ids=()), (ResourceProbe('prepare business taxes'),))

    def test_partial_channel_failure_not_semantic_gap(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        for failed in ('exact', 'fts', 'trigram', 'metadata'):
            channels = [EmptyChannel(n, failure=n == failed) for n in ('exact', 'fts', 'trigram', 'metadata')]
            r = ResourceDiscoveryService(channels).discover(self.db, self.hard, (ResourceProbe('prepare business taxes'),)).resolutions[0]
            self.assertFalse(r.semantic_gap.eligible_for_optimizer)
            self.assertEqual(r.semantic_gap.basis, 'technical_failure')

    def test_assessment_does_not_change_resolution_candidates_or_database_work(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        svc = empty_service(); probes = (ResourceProbe('prepare business taxes'),)
        raw = svc._discover(self.db, self.hard, probes, ())
        with patch.object(self.db, 'execute', side_effect=AssertionError('classification must be pure')):
            result = svc._classify_gaps(raw, self.hard)
        self.assertIs(result.candidates, raw.candidates)
        self.assertIs(result.resolutions[0].alternatives, raw.resolutions[0].alternatives)
        self.assertEqual(result.resolutions[0].state, raw.resolutions[0].state)
        self.assertIs(result.resolutions[0].candidate, raw.resolutions[0].candidate)
        self.assertIsNone(raw.resolutions[0].semantic_gap)

    def test_cache_stable_and_separates_gap_state_scope_and_member(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        svc = empty_service(); probes = (ResourceProbe('prepare business taxes', comparison_group_id='current', comparison_member_index=0),)
        result = svc.discover(self.db, self.hard, probes)
        key = result.cache_identity(self.hard)
        self.assertEqual(key, replace(result, diagnostics=({'ms': 999},)).cache_identity(self.hard))
        r = result.resolutions[0]
        changed = replace(result, resolutions=(replace(r, semantic_gap=replace(r.semantic_gap, eligible_for_optimizer=False)),))
        self.assertNotEqual(key, changed.cache_identity(self.hard))
        self.assertNotEqual(key, result.cache_identity(replace(self.hard, authorized_document_ids=(1,))))
        other = svc.discover(self.db, self.hard, (replace(probes[0], comparison_member_index=1),))
        self.assertNotEqual(key, other.cache_identity(self.hard))
        self.assertNotIn('ms', json.dumps(key))

    def test_trace_has_no_resource_text_or_factual_metadata_in_assessment(self):
        self.add(1, 'Unrelated Authorized Reference', metadata={'summary': 'UNSUPPORTED FACT'}); self.project(1)
        result = empty_service().discover(self.db, self.hard, (ResourceProbe('prepare business taxes'),))
        gap = result.trace()['resolutions'][0]['semantic_gap']
        self.assertEqual(gap['candidate_count'], 0)
        self.assertEqual(gap['informative_token_count'], 3)
        self.assertTrue(gap['explicit_current_user_span'])
        self.assertNotIn('UNSUPPORTED FACT', json.dumps(gap))
        self.assertNotIn('prepare business taxes', json.dumps(gap))

    def test_bounded_input_no_truncation_and_generic_type_combinations(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        for text in ('web service', 'plan pro', 'show pdf', 'aaaa bbbb', 'just something', 'service plan form'):
            row = empty_service().discover(self.db, self.hard, (ResourceProbe(text),)).resolutions[0]
            self.assertFalse(row.semantic_gap.eligible_for_optimizer, text)
        p = ResourceProbe('prepare business taxes', original_span='prepare business taxes ' + 'x' * 512)
        self.assertFalse(empty_service().discover(self.db, self.hard, (p,)).resolutions[0].semantic_gap.eligible_for_optimizer)
        with self.assertRaises(ValueError):
            empty_service().discover(self.db, self.hard, (ResourceProbe('x' * 513),))

    def test_empty_catalog_does_not_become_found(self):
        row = empty_service().discover(self.db, self.hard, (ResourceProbe('prepare business taxes'),)).resolutions[0]
        self.assertFalse(row.semantic_gap.eligible_for_optimizer)
        self.assertIsNone(row.candidate)

    def test_no_attempted_channel_is_not_a_successful_empty_search(self):
        self.add(1, 'Unrelated Authorized Reference'); self.project(1)
        result = ResourceDiscoveryService([]).discover(self.db, self.hard, (ResourceProbe('prepare business taxes'),))
        self.assertFalse(result.resolutions[0].semantic_gap.eligible_for_optimizer)


if __name__ == "__main__":
    unittest.main()
