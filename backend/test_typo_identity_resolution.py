"""Offline typo-resolution regressions against real scoped query-contract SQL."""

import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import event
from database.models import Chunk, Document, Website, WebsiteCrawl
from services import rag_service as rag
from services.query_contract import explicit_identity_candidate, fuzzy_identity_match, FUZZY_IDENTITY_CHARS
import test_content_subject_resolution as content_fixture


class TypoIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = content_fixture.ContentSubjectResolutionTests()
        self.fixture.setUp()
        self.db, self.bot = self.fixture.db, self.fixture.bot
        self.db.add(Website(id=1, bot_id=1, organization_id=10, root_url="https://example.test",
                            domain="example.test", status="ready", active_crawl_id=11))
        self.db.add(WebsiteCrawl(id=11, website_id=1, bot_id=1, organization_id=10,
                                 version=1, status="ready"))
        self.set_identity("Turmeric Boost")

    def tearDown(self):
        self.fixture.tearDown()

    def set_identity(self, name):
        doc, row = self.db.get(Document, 1), self.db.get(Chunk, 1)
        doc.title = name
        doc.filename = "page.html"
        doc.source_type = "website"
        doc.canonical_url = "https://example.test/items/" + name.lower().replace(" ", "-")
        doc.website_id = row.website_id = 1
        doc.crawl_id = row.crawl_id = 11
        row.content = "Unrelated body content."
        self.db.flush()

    def contract(self, query, history=None):
        return self.fixture.contract(query, history)

    def test_production_typo_reaches_retrieval(self):
        self.fixture.assert_retrieval_handoff("how much is turmetic boost",
                                              subject="Turmeric Boost", fields=["price"])

    def test_correct_spelling_reaches_retrieval(self):
        with patch.object(rag, "fuzzy_identity_match") as fuzzy:
            self.fixture.assert_retrieval_handoff("how much is turmeric boost",
                                                  subject="Turmeric Boost", fields=["price"])
            fuzzy.assert_not_called()

    def test_realistic_typos_across_domains(self):
        for name, typo in (("Silver Workspace Plan", "silver workspase plan"),
                           ("Cedar Retreat Package", "cedar retreaf package"),
                           ("Indigo Foundations", "indigo foundatons"),
                           ("Amber Assistance Service", "amber assitance service")):
            with self.subTest(name=name):
                self.set_identity(name)
                result = self.contract("how much is " + typo)
                self.assertEqual(result.resolved_subject, name)
                self.assertEqual(result.subject_document_id, 1)
                self.assertFalse(result.requires_clarification)

    def test_canonical_query_cache_and_history_antecedent(self):
        typo = "how much is turmetic boost"
        corrected = "how much is turmeric boost"
        result = self.contract(typo)
        self.assertEqual(explicit_identity_candidate(typo), "turmetic boost")
        self.assertEqual(result.original_query, typo)
        self.assertEqual(result.resolved_query, corrected)
        self.assertEqual(rag.semantic_cache_identity(self.bot, typo, [], query_contract=result)["resolved_query"],
                         rag.semantic_cache_identity(self.bot, corrected, [], query_contract=self.contract(corrected))["resolved_query"])
        history = [{"role": "user", "content": typo}, {"role": "assistant", "content": "It is $30."}]
        before = deepcopy(history)
        followup = self.contract("What are its ingredients?", history)
        self.assertEqual(followup.subject_document_id, 1)
        self.assertEqual(followup.resolved_subject, "Turmeric Boost")
        self.assertIn("Turmeric Boost", followup.resolved_query)
        self.assertEqual(history, before)

    def second_document(self, name="Turmeric Booster", **kwargs):
        doc, row = self.fixture.add_knowledge(2, title=name, **kwargs)
        # Uploaded documents use the same tenant/READY boundary without a crawl.
        return doc, row

    def test_two_similar_candidates_fail_margin(self):
        self.second_document()
        result = self.contract("how much is turmetic boost")
        self.assertTrue(result.requires_clarification)
        self.assertIsNone(result.subject_document_id)

    def test_duplicate_high_confidence_identities_clarify(self):
        self.second_document("Turmeric Boost")
        self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)

    def test_short_and_unrelated_typos_clarify(self):
        for name, query in (("Cedar Pro", "how much is cedra pro"),
                            ("Turmeric Boost", "how much is distant planet"),
                            ("Turmeric Boost", "how much is it?")):
            with self.subTest(query=query):
                self.set_identity(name)
                with patch.object(rag, "generate") as generate, patch.object(rag, "retrieve_relevant_chunks_cached") as retrieve:
                    result = self.contract(query)
                    self.assertTrue(result.requires_clarification)
                    rag.answer_question(self.db, self.bot, query, knowledge_version=1)
                    retrieve.assert_not_called()
                    generate.assert_not_called()

    def test_short_ambiguous_names_fail_closed(self):
        self.set_identity("Blue Pro")
        self.second_document("Blue Plus")
        self.assertTrue(self.contract("how much is blie pro").requires_clarification)

    def test_cross_bot_identity_cannot_participate(self):
        self.second_document("Turmeric Boost", bot_id=2)
        self.assertEqual(self.contract("how much is turmetic boost").subject_document_id, 1)
        self.db.get(Chunk, 1).status = "failed"
        self.db.flush()
        self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)

    def test_cross_org_identity_cannot_participate(self):
        self.second_document("Turmeric Boost", org_id=20)
        self.assertEqual(self.contract("how much is turmetic boost").subject_document_id, 1)
        self.db.get(Chunk, 1).status = "failed"
        self.db.flush()
        self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)

    def test_non_ready_and_processing_identity_cannot_participate(self):
        for model, field, invalid in ((Document, "status", "stale"), (Document, "status", "failed"),
                                      (Document, "processing_status", "processing"), (Chunk, "status", "pending")):
            with self.subTest(model=model.__name__, field=field):
                target = self.db.get(model, 1)
                original = getattr(target, field)
                setattr(target, field, invalid)
                self.db.flush()
                self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)
                setattr(target, field, original)
                self.db.flush()

    def test_active_crawl_version_and_ownership_are_required(self):
        for model, row_id, field, value in ((Website, 1, "active_crawl_id", 12),
                                           (Website, 1, "organization_id", 20),
                                           (Website, 1, "bot_id", 2),
                                           (WebsiteCrawl, 11, "status", "processing"),
                                           (WebsiteCrawl, 11, "version", 2),
                                           (WebsiteCrawl, 11, "organization_id", 20),
                                           (Chunk, 1, "crawl_id", 12),
                                           (Chunk, 1, "organization_id", 20),
                                           (Chunk, 1, "bot_id", 2)):
            with self.subTest(model=model.__name__, field=field):
                target = self.db.get(model, row_id)
                original = getattr(target, field)
                setattr(target, field, value)
                self.db.flush()
                self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)
                setattr(target, field, original)
                self.db.flush()

    def test_missing_org_fails_closed(self):
        self.bot.organization_id = None
        self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)

    def test_only_primary_identity_fields_are_eligible(self):
        doc = self.db.get(Document, 1)
        for field, value, expected in (("title", "Turmeric Boost", "Turmeric Boost"),
                                       ("metadata_json", {"name": "Turmeric Boost"}, "Turmeric Boost"),
                                       ("metadata_json", {"og:title": "Turmeric Boost"}, "Turmeric Boost"),
                                       ("canonical_url", "https://example.test/turmeric-boost", "turmeric boost")):
            with self.subTest(field=field):
                doc.title, doc.canonical_url, doc.metadata_json = "page", None, {}
                setattr(doc, field, value)
                self.db.flush()
                self.assertEqual(self.contract("how much is turmetic boost").resolved_subject, expected)

    def test_meaningful_uploaded_filename_can_resolve(self):
        doc, row = self.db.get(Document, 1), self.db.get(Chunk, 1)
        doc.title, doc.canonical_url, doc.source_type = None, None, "pdf"
        doc.filename = "Silver Workspace Plan.pdf"
        doc.website_id = doc.crawl_id = row.website_id = row.crawl_id = None
        self.db.flush()
        self.assertEqual(self.contract("how much is silver workspase plan").resolved_subject, "Silver Workspace Plan")
        self.assertEqual(self.contract("how much is silver workspace plan").resolved_subject, "Silver Workspace Plan")
        history = [{"role": "user", "content": "how much is silver workspase plan"},
                   {"role": "assistant", "content": "It is $30."}]
        self.assertEqual(self.contract("What are its features?", history).resolved_subject, "Silver Workspace Plan")

    def test_body_and_nested_supplemental_metadata_cannot_supply_identity(self):
        doc, row = self.db.get(Document, 1), self.db.get(Chunk, 1)
        doc.title, doc.canonical_url = "Unrelated Page", None
        for label in ("reviews", "recommendations", "cross_sells", "navigation", "footer", "testimonials"):
            with self.subTest(label=label):
                doc.metadata_json = {label: {"name": "Turmeric Boost"}}
                doc.raw_text = "Turmeric Boost" * 30
                row.content = "Turmeric Boost" * 30
                row.metadata_json = {"name": "Turmeric Boost"}
                self.db.flush()
                self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)

    def test_exact_history_resolution_wins(self):
        history = [{"role": "user", "content": "Tell me about Turmeric Boost"}]
        with patch.object(rag, "fuzzy_identity_match") as fuzzy:
            self.assertEqual(self.contract("What is its price?", history).subject_document_id, 1)
            fuzzy.assert_not_called()

    def test_history_typo_is_not_revived_after_an_intervening_turn(self):
        history = [{"role": "user", "content": "how much is turmetic boost"},
                   {"role": "assistant", "content": "It is $30."},
                   {"role": "user", "content": "What about something else?"}]
        self.assertTrue(self.contract("What is its price?", history).requires_clarification)

    def test_catalog_filter_comparison_and_exclusions_do_not_invoke_fuzzy(self):
        with patch.object(rag, "fuzzy_identity_match") as fuzzy:
            for query in ("What turmetic products do you have?", "Which products support mobility?",
                          "Compare Turmetic Boost and Silver Workspace Plan", "Exclude Turmetic Boost. What is the price?"):
                self.contract(query)
            fuzzy.assert_not_called()

    def test_canonical_exclusion_cannot_become_a_positive_typo_subject(self):
        for query in ("how much is turmetic boost without Turmeric Boost",
                      "Tell me about Turmetic Boost without Turmeric Boost"):
            with self.subTest(query=query):
                result = self.contract(query)
                self.assertTrue(result.requires_clarification)
                self.assertIsNone(result.subject_document_id)
        history = [{"role": "user", "content": "how much is turmetic boost"}]
        with patch.object(rag, "fuzzy_identity_match") as fuzzy:
            self.contract("Exclude turmetic boost. How much is it?", history)
            fuzzy.assert_not_called()

    def test_multiple_edits_do_not_pass_on_a_long_name(self):
        self.set_identity("Silver Workspace Enterprise Plan")
        self.assertTrue(self.contract("how much is silver wurkspice enterprise plan").requires_clarification)

    def test_adjacent_transposition_is_supported(self):
        self.set_identity("Silver Workspace Plan")
        self.assertEqual(self.contract("how much is silver worskpace plan").subject_document_id, 1)

    def test_document_bound_does_not_claim_truncated_uniqueness(self):
        self.db.add_all([Document(id=i, bot_id=1, organization_id=10, filename=f"upload-{i}.txt",
                                 source_type="txt", status="ready") for i in range(2, 501)])
        self.db.flush()
        with patch("services.query_contract.SequenceMatcher") as compare:
            self.assertTrue(self.contract("how much is turmetic boost").requires_clarification)
            compare.assert_not_called()

    def test_bounded_identity_strings_and_candidate_set(self):
        doc = SimpleNamespace(id=1, title="x" * (FUZZY_IDENTITY_CHARS + 1), filename="",
                              metadata_json={"name": "x" * 10000}, canonical_url="https://example.test/" + "x" * 3000)
        with patch("services.query_contract.SequenceMatcher") as compare:
            self.assertIsNone(fuzzy_identity_match("turmetic boost", [doc]))
            compare.assert_not_called()
        self.assertIsNone(fuzzy_identity_match("x" * 97, [doc]))
        doc.title = "Turmeric Boost"
        self.assertIsNone(fuzzy_identity_match("turmetic boost", [doc] * 500))

    def test_typo_sql_does_not_load_chunk_text_or_embeddings(self):
        self.db.add_all([Chunk(id=i, document_id=1, bot_id=1, organization_id=10,
                               website_id=1, crawl_id=11, chunk_index=i, content="Unrelated " * 100,
                               embedding=[0.0], status="ready") for i in range(2, 1002)])
        self.db.flush()
        statements = []
        def capture(_conn, _cursor, sql, _params, _context, _many):
            statements.append(sql)
        event.listen(self.fixture.engine, "before_cursor_execute", capture)
        try:
            self.assertEqual(self.contract("how much is turmetic boost").subject_document_id, 1)
        finally:
            event.remove(self.fixture.engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 2)
        self.assertFalse(any("chunks.content" in sql or "embedding" in sql or " LIKE " in sql.upper() for sql in statements))


if __name__ == "__main__":
    unittest.main()
