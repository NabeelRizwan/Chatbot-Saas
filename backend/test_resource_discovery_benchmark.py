"""Frozen-membership generic benchmark, no historical names or customer corpus.

Run development first; freeze runtime hashes; then heldout. SQLite candidate
surrogates do not prove PostgreSQL FTS/pg_trgm performance or semantics.
"""
from dataclasses import dataclass
from collections import defaultdict
import hashlib
import json
import sys
import unittest

from database.resource_models import KnowledgeResource as Resource
from database.models import Organization, Bot
from services.resource_catalog import ResourceCatalogProjector
from services.retrieval_contracts import HardKnowledgeScope
from services import rag_planning
from services.resource_channels import ResourceProbe
from services.resource_discovery import ResolutionState, POLICY_VERSION, CHANNEL_WEIGHTS, RRF_K
from test_resource_discovery import ResourceFixture

SEEDS = (
    ("Cedar Meridian", "product", "ecommerce"), ("Linden Summit", "service", "professional"),
    ("Orchid Harbor", "plan", "saas"), ("Juniper Horizon", "course", "education"),
    ("Willow Beacon", "program", "education"), ("Marble Orchard", "form", "portal"),
    ("Copper Lantern", "page", "corporate"), ("Silver Compass", "page_section", "corporate"),
    ("Ivory Meadow", "document", "general"), ("Amber Galaxy", "pdf", "general"),
    ("Violet Cascade", "ebook", "education"), ("Quartz Valley", "policy", "policy"),
    ("Granite Prairie", "faq", "support"), ("Maple Riverside", "location", "locations"),
    ("Cobalt Harbor", "department", "corporate"), ("Saffron Terrace", "contact", "locations"),
    ("Sierra Wellness", "appointment", "healthcare_information"), ("Beryl Archive", "custom_certificate", "custom"),
)


@dataclass(frozen=True)
class Case:
    key: str
    kind: str
    domain: str
    category: str
    probes: tuple[str, ...]
    expected_docs: frozenset[int]
    expectation: str = "positive"
    provenance: str = "explicit_user"

    @property
    def split(self):
        return "development" if int(hashlib.sha256(self.key.encode()).hexdigest()[:8], 16) % 10 < 7 else "heldout"


def cases():
    result = []
    for i, (stem, kind, domain) in enumerate(SEEDS, 1):
        name = f"{stem} {kind.replace('_', ' ')}"
        alias = stem + " Desk"
        a, b = stem.split()
        n = i * 10
        next_i = i % len(SEEDS) + 1
        next_stem, next_type, _ = SEEDS[next_i - 1]
        other = f"{next_stem} {next_type.replace('_', ' ')}"
        rows = [
            ("exact", (name,), {n}, "exact"), ("alias", (alias,), {n}, "alias"),
            ("reordered", (f"{b} {a}",), {n}, "positive"), ("partial", (stem,), {n}, "positive"),
            ("extra", ("the " + stem + " information",), {n}, "positive"),
            ("typo", (name[:3] + "x" + name[4:],), {n}, "positive"),
            ("multi_typo", (a[:-1] + "x " + b[:-1] + "x " + kind,), {n}, "positive"),
            ("punctuation", (name.replace(" ", " / "),), {n}, "positive"),
            ("hyphens", (name.replace(" ", "–"),), {n}, "positive"),
            ("url", (f"{a}-{b}-portal",), {n}, "positive"),
            ("breadcrumb", (f"Directory {a} {b}",), {n}, "positive"),
            ("category", (kind,), {n, n+1}, "category"),
            ("short_alias", ("Pro",), set(), "ambiguous"),
            ("overlap", (f"{a} Common",), set(), "ambiguous"),
            ("duplicate_alias", ("Shared Desk",), set(), "ambiguous"),
            ("two_resource", (name, other), {n, next_i * 10}, "multi"),
            ("three_resource", (name, other, "Neutral Atlas Reference"), {n, next_i * 10, 999}, "multi"),
            ("unrelated", (f"Astral teleportation request {i}",), set(), "negative"),
            ("impossible", (f"nonexistent quasar apparatus {i}",), set(), "negative"),
            ("short_generic", ("AI",), set(), "negative"),
            ("unicode", (f"Café {a} 東京",), {n}, "alias"),
            ("numeric", (f"{a} Unit {2020+i}",), {n}, "alias"),
            ("case", (name.swapcase(),), {n}, "exact"),
            ("spaces", ("  " + name.replace(" ", "   ") + "  ",), {n}, "exact"),
            ("apostrophe", (name.replace(" ", "’"),), {n}, "positive"),
            ("parentheses", (f"{a} ({b}) {kind.replace('_',' ')}",), {n}, "positive"),
            ("extra_canonical", (f"{b} {a} {kind.replace('_',' ')}",), {n}, "positive"),
            ("digits_negative", (f"{a} Unit 90909",), set(), "negative"),
            ("plural_category", (kind[:-1] + "ies" if kind.endswith("y") else kind + "s",), {n, n+1}, "category"),
            ("same_name_bot", (name,), {n}, "exact"),
            ("same_name_org", (name,), {n}, "exact"),
            ("active_followup", (name,), {n}, "exact"),
            ("explicit_switch", (other, name), {n}, "exact"),
            ("requested_fields", (name, other), {n, next_i * 10}, "multi"),
        ]
        for category, probes, expected, expectation in rows:
            result.append(Case(f"{i:02d}-{category}", kind, domain, category, probes, frozenset(expected), expectation,
                               "category" if expectation == "category" else "explicit_user"))
    return tuple(result)


def populate(fixture):
    fixture.db.add(Organization(id=2, name="Foreign synthetic", slug="foreign-synthetic"))
    fixture.db.flush()
    fixture.db.add_all([Bot(id=2, organization_id=1, customer_id=1, name="Other bot"),
                        Bot(id=3, organization_id=2, customer_id=1, name="Foreign bot")])
    fixture.db.flush()
    for i, (stem, kind, _) in enumerate(SEEDS, 1):
        a, b = stem.split()
        fixture.add(i*10, f"{stem} {kind.replace('_',' ')}", kind=kind,
                    aliases=[stem + " Desk", "Pro", "Shared Desk", f"Café {a} 東京", f"{a} Unit {2020+i}"],
                    canonical_url=f"https://synthetic.test/{a}-{b}-portal",
                    metadata={"breadcrumb": [f"Directory {a} {b}"]})
        fixture.add(i*10+1, f"{a} Common Extended", kind=kind, aliases=[f"{a} Common"])
        fixture.add(i*10+2, f"{a} Common Compact", kind="other", aliases=[f"{a} Common"])
        fixture.add(10000+i, f"{stem} {kind.replace('_',' ')}", kind=kind, bot=2)
        fixture.add(20000+i, f"{stem} {kind.replace('_',' ')}", kind=kind, bot=3, org=2)
    fixture.add(999, "Neutral Atlas Reference", kind="custom")
    fixture.project(*[d for i in range(1, len(SEEDS)+1) for d in (i*10, i*10+1, i*10+2)], 999)
    for hard, ids in ((HardKnowledgeScope(1, 2), range(10001,10019)), (HardKnowledgeScope(2, 3), range(20001,20019))):
        ResourceCatalogProjector().project(fixture.db, hard, ids)
    fixture.db.commit()


def evaluate(fixture, split):
    selected = [c for c in cases() if c.split == split]
    records = []
    for case in selected:
        handoff_ok = True
        if case.category in {"active_followup", "explicit_switch", "requested_fields"}:
            if case.category == "requested_fields":
                contract = fixture.contract("Compare " + " and ".join(case.probes) + " on price and directions")
            else:
                previous = fixture.contract("Tell me about " + case.probes[0])
                state = rag_planning.next_state(previous, {})
                question = "How much is it?" if case.category == "active_followup" else "Tell me about " + case.probes[1]
                contract = fixture.contract(question, state=state)
            from services.resource_scope_adapter import discovery_probes
            probes = discovery_probes(contract, {})
            handoff_ok = set(contract.permitted_document_ids or ()) == case.expected_docs
        else:
            probes = tuple(ResourceProbe(p, case.provenance) for p in case.probes)
        result = fixture.service.discover(fixture.db, fixture.hard, probes)
        top1 = {d for r in result.resolutions for c in r.alternatives[:1] for d in c.resource.document_ids}
        top5 = {d for r in result.resolutions for c in r.alternatives[:5] for d in c.resource.document_ids}
        resolved = {d for r in result.resolutions if r.candidate for d in r.candidate.resource.document_ids}
        leakage = sum(c.resource.organization_id != 1 or c.resource.bot_id != 1 for c in result.candidates)
        # Wrong numeric identifier must never be inferred from a fuzzy neighbor.
        correct = not resolved - case.expected_docs
        ambiguous = all(r.state == ResolutionState.AMBIGUOUS for r in result.resolutions)
        records.append(dict(key=case.key, kind=case.kind, domain=case.domain, category=case.category,
            expectation=case.expectation, expected=len(case.expected_docs), r1=len(top1 & case.expected_docs),
            r5=len(top5 & case.expected_docs), resolved=len(resolved), correct_resolved=len(resolved & case.expected_docs),
            confident_correct=correct, ambiguous_correct=ambiguous, leakage=leakage,
            handoff_ok=handoff_ok, missing=sorted(case.expected_docs-top5), wrong=sorted(resolved-case.expected_docs)))
    def metrics(rows):
        expected = sum(r['expected'] for r in rows)
        resolved = sum(r['resolved'] for r in rows)
        ambiguous = [r for r in rows if r['expectation'] == 'ambiguous']
        negative = [r for r in rows if r['expectation'] == 'negative']
        multi = [r for r in rows if r['expectation'] == 'multi']
        return dict(cases=len(rows), candidate_recall_1=sum(r['r1'] for r in rows)/max(1, expected),
            candidate_recall_5=sum(r['r5'] for r in rows)/max(1, expected),
            resolution_precision=sum(r['correct_resolved'] for r in rows)/max(1, resolved),
            resolution_recall=sum(r['correct_resolved'] for r in rows)/max(1, expected),
            false_confident_rate=sum(not r['confident_correct'] for r in rows)/max(1, len(rows)),
            ambiguous_correctness=sum(r['ambiguous_correct'] for r in ambiguous)/max(1, len(ambiguous)),
            unresolved_correctness=sum(r['resolved']==0 for r in negative)/max(1, len(negative)),
            multi_member_recall_5=sum(r['r5'] for r in multi)/max(1, sum(r['expected'] for r in multi)),
            leakage=sum(r['leakage'] for r in rows))
    groups = {}
    for key in ('category', 'kind'):
        groups[key] = {value: metrics([r for r in records if r[key] == value]) for value in sorted({r[key] for r in records})}
    quality = [r for r in records if r['category'] in {'partial','reordered','typo','multi_typo','extra','extra_canonical'}]
    gates = dict(zero_leakage=all(r['leakage']==0 for r in records),
        runtime_handoff=all(r['handoff_ok'] for r in records),
        exact_alias=all(r['correct_resolved']==r['expected'] and r['confident_correct'] for r in records if r['expectation'] in {'exact','alias'}),
        protected_ambiguous=all(r['resolved']==0 and r['ambiguous_correct'] for r in records if r['expectation']=='ambiguous'),
        negative=all(r['resolved']==0 for r in records if r['expectation']=='negative'),
        multi=all(r['r5']==r['expected'] for r in records if r['expectation']=='multi'),
        fuzzy_recall_5=metrics(quality)['candidate_recall_5'] >= .95,
        precision=metrics(records)['resolution_precision'] >= .98)
    return dict(split=split, policy=POLICY_VERSION, weights=CHANNEL_WEIGHTS, rrf_k=RRF_K,
        fixture_total_cases=len(cases()), metrics=metrics(records), fuzzy_partial=metrics(quality), gates=gates,
        groups=groups, failures=[r for r in records if r['missing'] or r['wrong'] or not r['handoff_ok'] or (r['expectation']=='ambiguous' and not r['ambiguous_correct'])])


class GenericBenchmarkTests(ResourceFixture):
    def test_generic_matrix(self):
        populate(self)
        for split in ('development', 'heldout'):
            result = evaluate(self, split)
            self.assertTrue(all(result['gates'].values()), result)


if __name__ == '__main__':
    split = sys.argv[1]
    if split not in {'development', 'heldout'}:
        raise SystemExit('Choose development or heldout explicitly')
    fixture = ResourceFixture()
    fixture.setUp()
    try:
        populate(fixture)
        result = evaluate(fixture, split)
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if all(result['gates'].values()) else 1)
    finally:
        fixture.doCleanups()
