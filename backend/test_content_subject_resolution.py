"""Offline content-identity regressions using an isolated in-memory database."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from database.models import Chunk, Document, Website
from services import rag_service as rag
from services.query_contract import extract_requested_fields, field_evidence_pattern


NAME = "Cobalt Access Bundle"
QUESTION = f"Does the {NAME} include phone support, and what is the response target?"
CONTENT = (
    f"The {NAME} includes priority email support and a response target of four business hours.\n\n"
    f"Customers may cancel the {NAME} before the next renewal date.\n\n"
    f"The {NAME} does not include phone support."
)


class ReachedRetrieval(BaseException):
    """Stop at the real retrieval handoff, before any embedding/provider call."""


class ContentSubjectResolutionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for model in (Document, Chunk, Website):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.bot = SimpleNamespace(id=1, organization_id=10, capabilities={},
                                   provider="fixture", model_name="fixture")
        self.add_knowledge(1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_knowledge(self, doc_id, *, content=CONTENT, bot_id=1, org_id=10,
                      title="upload-001.txt", doc_status="ready", chunk_status="ready",
                      metadata=None, chunk_bot_id=None, chunk_org_id=None,
                      website_id=None, crawl_id=None):
        doc = Document(id=doc_id, bot_id=bot_id, organization_id=org_id,
                       title=title, filename=f"upload-{doc_id:03}.txt", source_type="txt",
                       status=doc_status, processing_status="completed")
        row = Chunk(id=doc_id, document_id=doc_id,
                    bot_id=bot_id if chunk_bot_id is None else chunk_bot_id,
                    organization_id=org_id if chunk_org_id is None else chunk_org_id,
                    content=content, embedding=[0.0], status=chunk_status,
                    chunk_index=0, metadata_json=metadata or {},
                    website_id=website_id, crawl_id=crawl_id)
        self.db.add_all([doc, row])
        self.db.flush()
        return doc, row

    def contract(self, question=QUESTION, history=None):
        return rag._build_turn_query_contract(self.db, self.bot, question, history)

    def test_explicit_content_subject_resolves(self):
        result = self.contract()
        self.assertFalse(result.requires_clarification, result.clarification_prompt)
        self.assertEqual(result.subject_document_id, 1)
        self.assertEqual(result.resolved_subject.lower(), NAME.lower())

    def test_two_factual_fields_are_retained_not_benefits(self):
        self.assertEqual(self.contract().requested_fields, ["features", "response target"])

    def test_explicit_content_subject_reaches_retrieval(self):
        with patch.object(rag.global_semantic_cache, "get", return_value=None), \
             patch.object(rag, "generate") as generate, \
             patch.object(rag, "retrieve_relevant_chunks_cached", side_effect=ReachedRetrieval) as retrieve:
            try:
                answer, _, _ = rag.answer_question(self.db, self.bot, QUESTION, knowledge_version=1)
            except ReachedRetrieval:
                pass
            else:
                self.fail(f"Stopped before retrieval: {answer}")
            retrieve.assert_called_once()
            self.assertEqual(retrieve.call_args.kwargs["query_contract"].subject_document_id, 1)
            generate.assert_not_called()

    def test_subjectless_fields_still_clarify_without_retrieval(self):
        with patch.object(rag, "generate") as generate, \
             patch.object(rag, "_primary_content_subject_matches") as lookup, \
             patch.object(rag, "retrieve_relevant_chunks_cached") as retrieve:
            for query in ("What are the benefits?", "What is the price?", "What are the ingredients?"):
                with self.subTest(query=query):
                    self.assertTrue(self.contract(query).requires_clarification)
                    answer, sources, _ = rag.answer_question(self.db, self.bot, query, knowledge_version=1)
                    self.assertTrue(answer.startswith("Which"))
                    self.assertEqual(sources, [])
            retrieve.assert_not_called()
            generate.assert_not_called()
            lookup.assert_not_called()

    def test_duplicate_strong_documents_clarify_without_retrieval(self):
        self.add_knowledge(2)
        result = self.contract()
        self.assertTrue(result.requires_clarification)
        self.assertIsNone(result.subject_document_id)
        self.assertEqual(result.resolved_entities, [])
        with patch.object(rag, "retrieve_relevant_chunks_cached") as retrieve:
            rag.answer_question(self.db, self.bot, QUESTION, knowledge_version=1)
            retrieve.assert_not_called()

    def test_duplicate_content_is_not_misread_as_comparison(self):
        self.add_knowledge(2)
        result = self.contract(f"What are the benefits of {NAME}?")
        self.assertTrue(result.requires_clarification)
        self.assertEqual(result.comparison_entities, [])
        self.assertEqual(result.resolved_entities, [])

    def test_multiple_strong_chunks_in_one_document_are_unique(self):
        self.db.add(Chunk(id=2, document_id=1, bot_id=1, organization_id=10,
                          chunk_index=1, content=CONTENT, embedding=[0.0], status="ready"))
        self.db.flush()
        self.assertEqual(self.contract().subject_document_id, 1)

    def test_cross_bot_and_tenant_matches_do_not_create_ambiguity(self):
        for doc_id, kwargs in enumerate((
            {"bot_id": 2}, {"org_id": 20}, {"bot_id": 2, "org_id": 20},
            {"chunk_bot_id": 2}, {"chunk_org_id": 20},
        ), 2):
            self.add_knowledge(doc_id, **kwargs)
        self.assertEqual(self.contract().subject_document_id, 1)
        self.db.get(Chunk, 1).status = "pending"
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)
        self.assertIsNone(self.contract().subject_document_id)

    def test_missing_organization_fails_closed(self):
        self.bot.organization_id = None
        self.assertTrue(self.contract().requires_clarification)

    def test_non_ready_documents_and_chunks_cannot_resolve(self):
        doc, row = self.db.get(Document, 1), self.db.get(Chunk, 1)
        for status in ("pending", "failed", "deleting", "deleted"):
            for target in (doc, row):
                with self.subTest(status=status, model=type(target).__name__):
                    target.status = status
                    self.db.flush()
                    self.assertTrue(self.contract().requires_clarification)
                    target.status = "ready"
                    self.db.flush()

    def test_only_ready_active_crawl_can_resolve(self):
        website = Website(id=1, bot_id=1, organization_id=10,
                          root_url="https://example.test", domain="example.test",
                          status="ready", active_crawl_id=2)
        self.db.add(website)
        row = self.db.get(Chunk, 1)
        row.website_id, row.crawl_id = 1, 1
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)
        row.crawl_id = 2
        self.db.flush()
        self.assertEqual(self.contract().subject_document_id, 1)
        website.status = "disabled"
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)

    def test_weak_or_incidental_content_does_not_bind(self):
        row = self.db.get(Chunk, 1)
        for text in (
            f"Customers mentioned the {NAME} in passing.",
            f"Try another option instead of {NAME}.",
            f"[The {NAME}](https://example.test/other)",
            f"> The {NAME} includes assistance.",
            f"The {NAME} Extended includes assistance.",
            f"A different subject has details. The {NAME} includes assistance.",
        ):
            with self.subTest(text=text):
                row.content = text
                self.db.flush()
                self.assertTrue(self.contract().requires_clarification)

    def test_reviews_navigation_and_cross_sell_cannot_supply_identity(self):
        row = self.db.get(Chunk, 1)
        for label in ("Reviews", "Testimonials", "Navigation", "Footer", "Sidebar",
                      "Related", "Recommendations", "Cross-sell", "See also"):
            for kind in ("metadata", "markdown", "plain"):
                with self.subTest(label=label, kind=kind):
                    prefix = "## " if kind == "markdown" else ""
                    row.content = CONTENT if kind == "metadata" else f"{prefix}{label}\n\n{CONTENT}"
                    row.metadata_json = {"section": label} if kind == "metadata" else {}
                    self.db.flush()
                    self.assertTrue(self.contract().requires_clarification)

    def test_other_documents_incidental_mentions_do_not_block_unique_primary(self):
        self.add_knowledge(2, content=f"Someone mentioned {NAME}.")
        self.add_knowledge(3, metadata={"heading": "Customer reviews"})
        self.assertEqual(self.contract().subject_document_id, 1)

    def test_only_primary_heading_and_lead_can_resolve_not_later_heading(self):
        row = self.db.get(Chunk, 1)
        row.content = f"# {NAME}\n\nThe {NAME} includes assistance."
        self.db.flush()
        self.assertEqual(self.contract().subject_document_id, 1)
        row.chunk_index = 4
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)

    def test_no_strong_match_preserves_clarification(self):
        for query in (QUESTION.replace(NAME, "Missing Named Option"),
                      "What are the benefits of Missing Named Option?"):
            with self.subTest(query=query):
                self.assertTrue(self.contract(query).requires_clarification)

    def test_no_positive_content_scope_from_exclusions_or_catalog(self):
        with patch.object(rag, "_primary_content_subject_matches") as lookup:
            for query in (f"Exclude {NAME}. What are the benefits?",
                          f"What options do you have without {NAME}?",
                          "Which options qualify and how do they compare?"):
                with self.subTest(query=query):
                    result = self.contract(query)
                    self.assertIsNone(result.subject_document_id)
            lookup.assert_not_called()

    def test_title_filename_url_and_metadata_resolution_unchanged(self):
        doc = self.db.get(Document, 1)
        with patch.object(rag, "_primary_content_subject_matches") as lookup:
            for field, value in (("title", NAME), ("filename", NAME),
                                 ("canonical_url", "https://example.test/cobalt-access-bundle"),
                                 ("metadata_json", {"name": NAME})):
                with self.subTest(field=field):
                    old = getattr(doc, field)
                    setattr(doc, field, value)
                    self.db.flush()
                    self.assertEqual(self.contract().subject_document_id, 1)
                    setattr(doc, field, old)
                    self.db.flush()
            lookup.assert_not_called()

    def test_existing_followup_and_entity_switch_are_preserved(self):
        self.db.get(Document, 1).title = NAME
        self.add_knowledge(2, title="Amber Access Bundle", content="Other details.")
        history = [{"role": "user", "content": f"Tell me about {NAME}"}]
        self.assertEqual(self.contract("What is its price?", history).subject_document_id, 1)
        self.assertEqual(self.contract("What about Amber Access Bundle?", history).subject_document_id, 2)
        history.append({"role": "user", "content": "What about Amber Access Bundle?"})
        self.assertEqual(self.contract("What is its price?", history).subject_document_id, 2)

    def test_truncated_document_boundary_fails_closed_before_content_probe(self):
        for doc_id in range(2, 502):
            self.db.add(Document(id=doc_id, bot_id=1, organization_id=10,
                                 filename=f"upload-{doc_id}.txt", source_type="txt", status="ready"))
        self.add_knowledge(502)
        self.assertTrue(self.contract().requires_clarification)
        self.db.get(Chunk, 1).status = "pending"
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)

    def test_truncated_primary_candidate_set_does_not_load_text_or_claim_uniqueness(self):
        for doc_id in range(2, rag.PRIMARY_IDENTITY_LIMIT + 2):
            self.add_knowledge(doc_id)
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            self.assertTrue(self.contract().requires_clarification)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertFalse(any("chunks.content" in sql for sql in statements))

    def test_same_content_pattern_is_domain_independent(self):
        row = self.db.get(Chunk, 1)
        for name in ("Cobalt Support Bundle", "Cobalt Workspace", "Amber Retreat", "Indigo Foundations",
                     "Silver Assistance", "Copper Daily", "Violet Initiative"):
            with self.subTest(name=name):
                row.content = CONTENT.replace(NAME, name)
                self.db.flush()
                result = self.contract(QUESTION.replace(NAME, name))
                self.assertEqual(result.subject_document_id, 1)
                self.assertEqual(result.requested_fields, ["features", "response target"])

    def test_noun_support_in_name_or_inclusion_is_not_benefits(self):
        question = QUESTION.replace(NAME, "Cobalt Support Bundle")
        self.assertEqual(extract_requested_fields(question), ["features", "response target"])
        self.assertEqual(extract_requested_fields(question.replace(", and", " and")),
                         ["features", "response target"])
        self.assertIn("benefits", extract_requested_fields("How does it support mobility?"))

    def test_arbitrary_coordinated_factual_labels_and_evidence_are_retained(self):
        for label in ("response target", "renewal interval", "entry deadline"):
            with self.subTest(label=label):
                query = QUESTION.replace("response target", label)
                self.assertEqual(extract_requested_fields(query), ["features", label])
                self.assertRegex(f"The {label} is confirmed.", field_evidence_pattern(label))
        self.assertEqual(extract_requested_fields(QUESTION.replace(NAME, "Response")),
                         ["features", "response target"])

    def test_incidental_repeated_assertions_cannot_override_primary_identity(self):
        row = self.db.get(Chunk, 1)
        row.content = (
            "# Amber Portal\n\nThis article is about Amber Portal. "
            "For comparison, consider another offering.\n\n"
            f"The {NAME} includes email assistance. The {NAME} has a four-hour target.\n\n"
            "Amber Portal has different capabilities."
        )
        self.db.flush()
        result = self.contract()
        self.assertTrue(result.requires_clarification)
        self.assertIsNone(result.subject_document_id)

    def test_unlabelled_first_person_account_is_not_identity(self):
        row = self.db.get(Chunk, 1)
        row.content = (f"I tried {NAME} last month. The {NAME} includes email assistance. "
                       f"The {NAME} has a four-hour target. I liked it.")
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)

    def test_unlabelled_boilerplate_cannot_supply_lead_identity(self):
        row = self.db.get(Chunk, 1)
        row.content = f"The {NAME} includes assistance.\n\nCopyright Example. All rights reserved."
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)

    def test_conflicting_primary_metadata_rejects_body_candidate(self):
        row, doc = self.db.get(Chunk, 1), self.db.get(Document, 1)
        for metadata_key in ("heading", "section"):
            row.metadata_json = {metadata_key: "Amber Portal"}
            self.db.flush()
            self.assertTrue(self.contract().requires_clarification)
        row.metadata_json = {"heading": "General", "section": "General"}
        doc.metadata_json = {"name": "Amber Portal"}
        self.db.flush()
        self.assertTrue(self.contract().requires_clarification)
        doc.metadata_json = {}
        self.db.flush()
        self.assertEqual(self.contract().subject_document_id, 1)

    def test_field_candidates_never_erase_original_requested_fields(self):
        cases = {
            "What is the price for two years?": ["price", "duration"],
            "Tell me about the ingredients": ["ingredients"],
            "What does Amber Portal support?": ["benefits"],
            "What are the response target and renewal interval?": ["response target", "renewal interval"],
        }
        for query, fields in cases.items():
            with self.subTest(query=query):
                self.assertEqual(extract_requested_fields(query), fields)
                self.assertEqual(self.contract(query).requested_fields, fields)

    def test_service_noun_and_support_verb_are_distinct(self):
        for query in ("What support do you offer?", "Does it include phone support for customers?",
                      "What are the supported capabilities?", "Tell me about support"):
            with self.subTest(query=query):
                self.assertIn("features", extract_requested_fields(query))
                self.assertNotIn("benefits", extract_requested_fields(query))
        for query in ("How does it support mobility?", "Which options support comfort?",
                      "Which options are presented as supporting mobility?", "What does Amber Portal support?"):
            with self.subTest(query=query):
                self.assertIn("benefits", extract_requested_fields(query))

    def test_known_and_custom_fields_remain_additive(self):
        query = (f"Does {NAME} include phone support, and what are the price, "
                 "response target and renewal interval?")
        self.assertEqual(extract_requested_fields(query),
                         ["price", "features", "response target", "renewal interval"])
        self.assertEqual(extract_requested_fields("What support do you offer, and does it support mobility?"),
                         ["benefits", "features"])

    def test_explicit_subject_does_not_require_an_ontology_field(self):
        result = self.contract(f"Does {NAME} require approval?")
        self.assertEqual(result.requested_fields, [])
        self.assertEqual(result.subject_document_id, 1)
        self.assertFalse(result.requires_clarification)

    def test_thousands_of_non_primary_chunks_are_not_transferred_or_text_searched(self):
        self.db.add_all([
            Chunk(id=row_id, document_id=1, bot_id=1, organization_id=10,
                  chunk_index=row_id, content="Unrelated secondary detail. " * 40,
                  embedding=[0.0], status="ready")
            for row_id in range(2, 2002)
        ])
        self.db.flush()
        statements = []
        def capture(_conn, _cursor, statement, parameters, _context, _executemany):
            statements.append((statement, parameters))
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with patch.object(rag, "_has_primary_subject_identity", wraps=rag._has_primary_subject_identity) as check:
                self.assertEqual(self.contract().subject_document_id, 1)
                self.assertEqual(check.call_count, 1)
                self.assertLessEqual(len(check.call_args.args[0].content), rag.PRIMARY_IDENTITY_CHARS)
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 3)
        candidate_sql, parameters = statements[1]
        self.assertNotIn("chunks.content", candidate_sql)
        self.assertNotIn("embedding", candidate_sql)
        self.assertIn("LIMIT", candidate_sql)
        self.assertTrue(all(" LIKE " not in sql.upper() and " ILIKE " not in sql.upper() for sql, _ in statements))
        self.assertIn("substr(chunks.content", statements[2][0])
        self.assertIn("chunks.id IN", statements[2][0])
        plan = self.db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + candidate_sql, parameters).all()
        self.assertTrue(any("SEARCH chunks USING INDEX" in str(row) for row in plan), plan)

    def test_hydration_rechecks_lifecycle_after_candidate_selection(self):
        # Change only the isolated fixture between the two SELECTs.
        def change_status(conn, _cursor, statement, _parameters, _context, _executemany):
            if "substr(chunks.content" in statement:
                conn.exec_driver_sql("UPDATE chunks SET status = 'stale' WHERE id = 1")
        event.listen(self.engine, "before_cursor_execute", change_status)
        try:
            self.assertTrue(self.contract().requires_clarification)
        finally:
            event.remove(self.engine, "before_cursor_execute", change_status)


if __name__ == "__main__":
    unittest.main()
