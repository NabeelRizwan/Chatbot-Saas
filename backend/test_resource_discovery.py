"""Phase 3 deterministic runtime/SQL contract tests. No network/customer data.

SQLite FTS/trigram functions below are explicit test surrogates, not production
backends and not PostgreSQL acceptance. Exact/metadata/hard predicates, batch
hydration, scorer, fusion, resolution and scope adapter execute actual runtime.
"""
from dataclasses import replace
import json
import re
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, literal_column, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, OperationalError

from database.connection import Base
from database.models import Customer, Organization, Bot, Document, Chunk, Website, WebsiteCrawl
from database.resource_models import KnowledgeResource as Resource, KnowledgeResourceTerm as Term, KnowledgeResourceDocument as Link
from services.retrieval_contracts import HardKnowledgeScope, ProfileIdentity, ScopeStrategy, SemanticScopeState
from services.resource_catalog import ResourceCatalogProjector, catalog_revision, safe_navigation_url
from services.resource_normalization import normalize_resource_text
from services.resource_channels import (SQLResourceChannel, ResourceProbe, ChannelBatch, CandidateSignal,
    FeatureUnavailable, term_statement, bounded_terms, CHANNEL_LIMIT)
from services.resource_discovery import (ResourceDiscoveryService, ResourceResolutionPolicy, ResolutionState,
                                        ResourceDiscoveryError, resource_discovery_enabled)
from services import rag_planning, rag_service
from services.resource_scope_adapter import apply_resource_discovery
from services.observability_service import ChatTrace


def trigrams(value):
    result = set()
    for word in value.split():
        padded = "  " + word + " "
        result.update(padded[i:i+3] for i in range(len(padded)-2))
    return result


def similarity(left, right):
    a, b = trigrams(left), trigrams(right)
    return len(a & b) / max(1, len(a | b))


class SQLiteTestChannel(SQLResourceChannel):
    """Test-only SQL scalar approximations, explicitly labeled in reports."""
    def statement(self, db, hard, probe, limit):
        if self.name not in {"fts", "trigram"}:
            return super().statement(db, hard, probe, limit)
        value = normalize_resource_text(probe.text)
        score = func.fixture_tokens(Term.normalized_term, value) if self.name == "fts" else func.fixture_trigram(Term.normalized_term, value)
        predicate = score == 1 if self.name == "fts" else score >= .25
        return bounded_terms(term_statement(db, hard, score).where(predicate, Term.term_kind != "resource_type"), limit)


def fixture_engine():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function("fixture_tokens", 2, lambda value, probe: float(bool(probe) and set(probe.split()) <= set(value.split())))
        connection.create_function("fixture_trigram", 2, similarity)
    Base.metadata.create_all(engine)
    return engine


def service():
    return ResourceDiscoveryService([SQLiteTestChannel(c) for c in ("exact", "fts", "trigram", "metadata")])


class ResourceFixture(unittest.TestCase):
    def setUp(self):
        self.engine = fixture_engine()
        self.addCleanup(self.engine.dispose)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.db.add(Customer(id=1, name="Synthetic", api_key="fixture-not-a-secret"))
        self.db.add(Organization(id=1, name="Synthetic", slug="synthetic"))
        self.db.flush()
        self.bot = Bot(id=1, organization_id=1, customer_id=1, name="Synthetic", capabilities={})
        self.db.add(self.bot)
        self.db.commit()
        self.hard = HardKnowledgeScope(1, 1, embedding_profile=ProfileIdentity("gemini", "gemini-embedding-001", 1, 768))
        self.service = service()

    def add(self, number, name="Silver Orchard Package", *, org=1, bot=1, aliases=None, kind="service", metadata=None, **changes):
        doc = Document(id=number, organization_id=org, bot_id=bot, title=name, filename="source.txt", source_type="txt",
                       canonical_url=f"https://synthetic.test/{number}", status="ready", processing_status="completed", version=1,
                       metadata_json={"aliases": aliases or [], "resource_type": kind, **(metadata or {})})
        for key, value in changes.items():
            setattr(doc, key, value)
        self.db.add(doc)
        self.db.flush()
        self.db.add(Chunk(id=number, organization_id=org, bot_id=bot, document_id=number, chunk_index=0,
                          content="Factual source directions only. No guarantee is stated.", embedding=[0.] * 768, status="ready"))
        self.db.flush()
        return doc

    def project(self, *ids):
        result = ResourceCatalogProjector().project(self.db, self.hard, ids)
        self.db.commit()
        return result

    def discover(self, *names, hard=None, provenance="explicit_user"):
        return self.service.discover(self.db, hard or self.hard, [ResourceProbe(n, provenance) for n in names])

    def contract(self, question, *, state=None):
        with patch.object(rag_planning, "plan_query", return_value=None), patch.dict("os.environ", {"RAG_RESOURCE_DISCOVERY": "off"}):
            c = rag_planning.prepare_query(self.db, self.bot, question, [], state or {}, rag_service._build_turn_query_contract)
        return apply_resource_discovery(self.db, c, state or {}, service=self.service)


class NormalizationTests(unittest.TestCase):
    def test_unicode_and_separators(self):
        cases = {"  Alpha   Beta ": "alpha beta", "ALPHA-Beta": "alpha beta", "Alpha–Beta—Gamma": "alpha beta gamma",
                 "Alpha(Beta)/Gamma": "alpha beta gamma", "L'été": "l été", "Café 東京 ２０２６": "café 東京 2026",
                 "e-book": "e book", "ebook": "ebook", "Δέλτα Журнал": "δέλτα журнал", "Straße": "strasse"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_resource_text(value), expected)
                self.assertEqual(normalize_resource_text(expected), expected)

    def test_empty_punctuation_digits_and_bounds(self):
        self.assertEqual(normalize_resource_text("%_/!' "), "")
        self.assertEqual(normalize_resource_text("X-300"), "x 300")
        with self.assertRaises(ValueError):
            normalize_resource_text("x" * 513)
        with self.assertRaises(ValueError):
            normalize_resource_text("\ufdfa" * 64)  # Short input, long NFKC expansion.

    def test_unsafe_urls_never_navigation(self):
        for value in ("javascript:alert(1)", "https://u:p@test/path", "https://test/?token=secret", "data:text/plain,x"):
            self.assertIsNone(safe_navigation_url(value))
        self.assertEqual(safe_navigation_url("https://test/path"), "https://test/path")


class CatalogTests(ResourceFixture):
    def test_projection_idempotent_and_dry_run(self):
        self.add(1, aliases=["Silver Package"])
        before = catalog_revision(self.db, self.hard)
        dry = ResourceCatalogProjector().project(self.db, self.hard, [1], dry_run=True)
        self.assertEqual((dry.changed, self.db.query(Resource).count(), catalog_revision(self.db, self.hard)), (1, 0, before))
        self.assertEqual(self.project(1).changed, 1)
        revision = catalog_revision(self.db, self.hard)
        self.assertGreater(revision, 0)
        self.assertEqual(self.project(1).changed, 0)
        self.assertEqual(catalog_revision(self.db, self.hard), revision)

    def test_alias_name_link_changes_revision_and_rollback(self):
        doc = self.add(1)
        self.project(1)
        before = catalog_revision(self.db, self.hard)
        doc.title = "Golden Meadow Service"
        doc.metadata_json = {"aliases": ["Meadow Desk"]}
        self.project(1)
        self.assertGreater(catalog_revision(self.db, self.hard), before)
        self.assertEqual(self.discover("Meadow Desk").resolutions[0].state, ResolutionState.RESOLVED)
        before = catalog_revision(self.db, self.hard)
        self.db.execute(text("UPDATE knowledge_resource_terms SET term_text='Changed' WHERE term_kind='alias'"))
        self.assertGreater(catalog_revision(self.db, self.hard), before)
        self.db.rollback()
        self.assertEqual(catalog_revision(self.db, self.hard), before)
        self.db.delete(self.db.query(Link).one())
        self.db.commit()
        self.assertGreater(catalog_revision(self.db, self.hard), before)

    def test_no_fuzzy_persistence_merge_and_shared_stable_identifier(self):
        self.add(1, "Linden Course")
        self.add(2, "Linden Course")
        self.project(1, 2)
        self.assertEqual(self.db.query(Resource).count(), 2)
        self.add(3, "Cedar Service", metadata={"resource_id": "shared"})
        self.add(4, "Cedar Service Details", metadata={"resource_id": "shared"})
        self.project(3, 4)
        self.assertEqual(self.db.query(Resource).count(), 3)
        resource = self.db.query(Resource).filter(Resource.source_key.like("explicit:%")).one()
        self.assertEqual(self.db.query(Link).filter(Link.resource_id == resource.id).count(), 2)

    def test_projector_does_not_project_ineligible_or_outside_scope(self):
        self.add(1, status="processing")
        self.assertEqual(self.project(1).changed, 0)
        with self.assertRaises(ValueError):
            ResourceCatalogProjector().project(self.db, replace(self.hard, authorized_document_ids=()), [1])

    def test_tenant_composite_foreign_keys(self):
        self.add(1)
        self.project(1)
        r = self.db.query(Resource).one()
        self.db.add(Term(resource_id=r.id, organization_id=2, bot_id=1, term_text="leak", normalized_term="leak",
                         term_kind="alias", term_source="admin"))
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()

    def test_metadata_summary_not_fact(self):
        self.add(1, "Admissions Form", kind="form", metadata={"summary": "90-day guarantee"})
        self.project(1)
        self.db.query(Resource).one().summary = "90-day guarantee"
        self.db.commit()
        result = self.discover("Admissions Form")
        self.assertNotIn("90-day", str(result))
        self.assertNotIn("90-day", json.dumps(result.trace()))
        self.assertTrue(result.resolutions[0].candidate.resource.url)
        self.assertEqual(self.db.query(Chunk).one().content, "Factual source directions only. No guarantee is stated.")


class DiscoveryTests(ResourceFixture):
    def test_content_only_legacy_identity_is_candidate_not_lost(self):
        self.add(1, "Generic Knowledge", kind="document")
        self.db.get(Chunk, 1).content = "The Azure Assistance Package includes priority email support."
        self.project(1)
        c = self.contract("Does the Azure Assistance Package include phone support?")
        self.assertEqual(c.permitted_document_ids, [1], c.to_debug_dict())
        self.assertTrue(any("legacy_identity" in candidate.match_sources for candidate in c.execution.soft_scope.resource_candidates))

    def test_exact_unique_and_collision(self):
        self.add(1, aliases=["Orchard Desk", "Pro"])
        self.project(1)
        for q in ("Silver Orchard Package", "Orchard Desk", "Pro"):
            self.assertEqual(self.discover(q).resolutions[0].state, ResolutionState.RESOLVED)
        self.add(2, "Amber Portal", aliases=["Pro", "Orchard Desk"])
        self.project(2)
        for q in ("Pro", "Orchard Desk"):
            self.assertEqual(self.discover(q).resolutions[0].state, ResolutionState.AMBIGUOUS)
        self.db.get(Document, 2).title = "Silver Orchard Package"
        self.project(2)
        self.assertEqual(self.discover("Silver Orchard Package").resolutions[0].state, ResolutionState.AMBIGUOUS)

    def test_reordered_partial_typo_and_punctuation(self):
        self.add(1, "Cedar Meridian Extended Service")
        self.project(1)
        for q in ("Meridian Cedar", "Cedar Meridian", "Cedar Meridan Extended Service", "CEDAR–MERIDIAN (Extended Service)"):
            with self.subTest(query=q):
                r = self.discover(q)
                self.assertTrue(r.candidates)
                self.assertEqual(r.resolutions[0].state, ResolutionState.RESOLVED, r)

    def test_generic_unrelated_and_adversarial_safe(self):
        self.add(1)
        self.project(1)
        for q in ("", " ", "?!", "a", "AI", "HR", "pro", "PDF", "service", "form", "plan", "course", "support",
                  "%%%%' OR 1=1 --", "unrelated orbital transmission", "Nonexistent Nimbus Teleporter"):
            with self.subTest(query=q):
                self.assertNotEqual(self.discover(q).resolutions[0].state, ResolutionState.RESOLVED)

    def test_metadata_type_category_and_url(self):
        self.add(1, "Marble Admissions", kind="form", canonical_url="https://fixture.test/admissions-portal", metadata={"breadcrumb": ["Admissions / Applications"]})
        self.project(1)
        for q in ("admissions portal", "admissions applications"):
            self.assertTrue(self.discover(q).candidates)
        result = self.discover("form", provenance="category")
        self.assertTrue(result.candidates)
        self.assertNotEqual(result.resolutions[0].state, ResolutionState.RESOLVED)

    def test_stale_anchor_and_profile(self):
        doc = self.add(1)
        self.project(1)
        for field, value in (("status", "deleted"), ("status", "error"), ("processing_status", "pending"), ("version", 2)):
            original = getattr(doc, field)
            setattr(doc, field, value)
            self.db.flush()
            self.assertFalse(self.discover("Silver Orchard Package").candidates, field)
            setattr(doc, field, original)
        self.db.flush()
        self.db.get(Chunk, 1).embedding_version = 9
        self.db.flush()
        self.assertFalse(self.discover("Silver Orchard Package").candidates)

    def test_mixed_links_only_authorized_source_terms(self):
        self.add(1, "Silver Orchard Package", metadata={"resource_id": "one"})
        self.add(2, "Private Special Addendum", metadata={"resource_id": "one"})
        self.project(1, 2)
        hard = replace(self.hard, authorized_document_ids=(1,))
        r = self.discover("Silver Orchard Package", hard=hard)
        self.assertEqual(r.resolutions[0].candidate.resource.document_ids, (1,))
        self.assertFalse(self.discover("Private Special Addendum", hard=hard).resolutions[0].candidate)
        self.assertNotIn("Private Special", json.dumps(r.trace()))

    def test_same_name_other_bot_org_never_enters_channels(self):
        self.add(1)
        self.db.add(Organization(id=2, name="Foreign", slug="foreign"))
        self.db.flush()
        self.db.add_all([Bot(id=2, organization_id=1, customer_id=1, name="Other"), Bot(id=3, organization_id=2, customer_id=1, name="Foreign")])
        self.db.flush()
        self.add(2, bot=2)
        self.add(3, bot=3, org=2)
        self.project(1)
        for hard, ids in ((HardKnowledgeScope(1, 2), [2]), (HardKnowledgeScope(2, 3), [3])):
            ResourceCatalogProjector().project(self.db, hard, ids)
        self.db.commit()
        r = self.discover("Silver Orchard Package")
        self.assertEqual({d for c in r.candidates for d in c.resource.document_ids}, {1})

    def test_fts_and_trigram_postgres_sql_parameterized(self):
        class Bind:
            dialect = postgresql.dialect()
        with patch.object(self.db, "get_bind", return_value=Bind()):
            for name in ("fts", "trigram"):
                stmt = SQLResourceChannel(name).statement(self.db, self.hard, ResourceProbe("Cedar' OR 1=1 --"), 32)
                compiled = stmt.compile(dialect=postgresql.dialect())
                sql = str(compiled)
                self.assertNotIn("Cedar", sql)
                for value in ("organization_id", "bot_id", "processing_status", "source_version", "document_version", "LIMIT"):
                    self.assertIn(value, sql)
                self.assertIn("simple", sql) if name == "fts" else self.assertIn("strict_word_similarity", sql)

    def test_query_count_and_bounded_hydration(self):
        self.add(1)
        self.project(1)
        statements = []
        def capture(_, __, sql, *rest):
            statements.append(sql)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            self.discover("Silver Orchard Package")
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 6)  # revision + four channels + one hydration
        self.assertFalse(any("chunks.content" in q or "embedding," in q or "summary" in q for q in statements))

    def test_feature_unavailable_and_programming_failure_distinct(self):
        self.add(1)
        self.project(1)
        r = ResourceDiscoveryService().discover(self.db, self.hard, [ResourceProbe("Silver Orchard Package")])
        self.assertEqual(r.resolutions[0].state, ResolutionState.RESOLVED)
        self.assertTrue(any(d["status"] == "feature_unavailable" for d in r.diagnostics))
        with patch.object(self.db, "execute", side_effect=OperationalError("secret SQL", {}, Exception("secret"))):
            with self.assertRaisesRegex(ResourceDiscoveryError, "technical failure"):
                self.discover("Silver Orchard Package")

    def test_cache_alias_edit_and_scope_identity(self):
        self.add(1)
        self.project(1)
        first = self.discover("Silver Orchard Package").cache_identity(self.hard)
        r = self.db.query(Resource).one()
        self.db.add(Term(resource_id=r.id, organization_id=1, bot_id=1, term_text="New Alias", normalized_term="new alias", term_kind="alias", term_source="admin"))
        self.db.commit()
        second = self.discover("Silver Orchard Package").cache_identity(self.hard)
        self.assertNotEqual(first, second)
        self.assertNotEqual(second["hard"], replace(self.hard, authorized_document_ids=()).identity())
        kind = self.discover("New Alias").trace()["resolutions"][0]["candidates"][0]["matched_term_kind"]
        self.assertEqual(kind, "alias")

    def test_runtime_single_multi_incomplete_and_exclusions(self):
        self.add(1, "Silver Orchard Package")
        self.add(2, "Amber Meridian Portal")
        self.project(1, 2)
        c = self.contract("Compare Silver Orchard Package and Amber Meridian Portal on price and directions")
        self.assertEqual(c.permitted_document_ids, [1, 2], c.to_debug_dict())
        c = self.contract("Compare Silver Orchard Package and Unknown Lunar Desk")
        self.assertIsNone(c.permitted_document_ids)
        self.assertEqual(c.execution.soft_scope.state, SemanticScopeState.INCOMPLETE_COMPARISON)
        c = self.contract("Exclude Silver Orchard Package and tell me about Amber Meridian Portal")
        self.assertNotIn(1, c.permitted_document_ids or [])

    def test_empty_catalog_flag_and_no_ai_call(self):
        self.add(1)
        with patch.dict("os.environ", {"RAG_RESOURCE_DISCOVERY": "on"}), patch.object(rag_planning, "plan_query", return_value=None) as call:
            c = rag_planning.prepare_query(self.db, self.bot, "Tell me about Silver Orchard Package", [], {}, rag_service._build_turn_query_contract)
        self.assertEqual(c.execution.resource_discovery["status"], "catalog_empty")
        self.assertEqual(c.permitted_document_ids, [1])
        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
