"""Isolated architecture regressions; no network, real accounts or embeddings."""
import contextlib
import io
import json
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from threading import Barrier, Event, get_ident
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from database.connection import Base
from database.models import Bot, Chunk, Document, ConversationMessage, ConversationSession, Website, WebsiteCrawl
from services import rag_service as rag, rag_planning as planning
from services.knowledge_scope import ready_chunks, identity_documents
from services.observability_service import ChatTrace, compact_chat_diagnostics
from services.query_contract import ResolvedEntity, QueryContract
from services.page_quality import validate_page_content


def plan(**changes):
    values = dict(resolved_user_meaning="Requested information", retrieval_query="Requested information",
                  intent="follow_up", active_subjects=[], subject_confidence=0.9,
                  requested_fields=[], scope_mode="uncertain", comparison_requested=False,
                  needs_global_discovery=False)
    values.update(changes)
    return planning.QueryPlan(**values)


class ScopedRagTests(unittest.TestCase):
    def setUp(self):
        # Each parallel recall session needs its own DBAPI transaction. StaticPool
        # shares one connection, so a worker close can roll back the request's work.
        self.database_dir = TemporaryDirectory(prefix="chatbot-scoped-rag-")
        self.addCleanup(self.database_dir.cleanup)
        self.engine = create_engine(
            URL.create("sqlite", database=str(Path(self.database_dir.name) / "fixture.sqlite3")),
            poolclass=QueuePool, connect_args={"check_same_thread": False},
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.bot = Bot(id=1, customer_id=1, organization_id=1, name="Fixture", provider="fixture", model_name="fixture", capabilities={})
        self.db.add(self.bot)
        self.add_document(1, "Sea Essence Omega 3 Fish Oil")
        self.add_document(2, "Turmeric Boost")
        self.db.commit()
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(planning, "generate_auxiliary", side_effect=TimeoutError("offline")))
        self.patches.enter_context(patch.object(rag, "SessionLocal", self.sessions))
        self.patches.enter_context(patch.object(rag, "resolve_active_embedding_profile", return_value=SimpleNamespace(provider="gemini", model="gemini-embedding-001", version=1, dimensions=768)))
        self.patches.enter_context(patch.object(rag, "generate_embedding", return_value=[0.0] * 768))
        self.scopes = []
        def vector(bot_id, org_id, embedding, limit, profile, document_ids=None):
            self.scopes.append(document_ids)
            with self.sessions() as db:
                rows = ready_chunks(db.query(Chunk.id, Document.id).join(Document, Chunk.document_id == Document.id), bot_id, org_id, document_ids).order_by(Chunk.id.desc()).limit(limit).all()
                return [(c, d, 0.02) for c, d in rows]
        self.patches.enter_context(patch.object(rag, "_vector_candidate_ids", side_effect=vector))

    def tearDown(self):
        self.patches.close()
        self.db.close()
        self.engine.dispose()

    def add_document(self, number, title, bot_id=1, org_id=1, text=None):
        doc = Document(id=number, bot_id=bot_id, organization_id=org_id,
                       title=title, filename=title, source_type="txt", status="ready", processing_status="completed",
                       source_url=f"https://fixture.test/{number}", canonical_url=f"https://fixture.test/{number}", version=1)
        self.db.add(doc)
        content = text or [
            f"# {title}\n## Overview\nFeatures include convenient use. Benefits support everyday activity.",
            f"[{title}]\n## Ingredients\n- Ingredient Alpha\n- Ingredient Beta",
            f"[{title}]\n- Ingredient Gamma\n- Ingredient Delta\nAdditional ingredients in the same section.",
            f"[{title}]\n## Directions\nTake two capsules daily with a meal.",
            f"[{title}]\n## Pricing\nOne-time purchase $37.00. Subscription $35.15.",
            f"[{title}]\n## Shipping and returns\nFree shipping on orders over $50. A 60-day money-back guarantee covers only first purchases.",
            f"[{title}]\n## Results timeframe\nResults may appear in 4–8 weeks; individual experiences vary and results are not guaranteed.",
        ]
        for index, body in enumerate(content):
            self.db.add(Chunk(id=number * 10 + index, document_id=number, bot_id=bot_id, organization_id=org_id,
                              content=body, embedding=[0.0] * 768, chunk_index=index, status="ready", metadata_json={}))
        self.db.flush()
        return doc

    def contract(self, question, history=None, state=None, response=None):
        trace = ChatTrace(1, "widget")
        with patch.object(planning, "plan_query", return_value=response):
            c = planning.prepare_query(self.db, self.bot, question, history or [], state or {}, rag._build_turn_query_contract, trace)
        return c, trace.conversation_state

    def retrieve(self, contract):
        trace = ChatTrace(1, "test")
        result = rag.retrieve_relevant_chunks(self.db, 1, contract.retrieval_query, query_contract=contract, trace=trace)
        return result, trace

    def test_explicit_price_and_followup_chain_and_switch(self):
        c, state = self.contract("price of turmeric boost")
        self.assertEqual(c.permitted_document_ids, [2])
        c, state = self.contract("tell me about Sea Essence Omega 3")
        self.assertEqual(c.permitted_document_ids, [1])
        for question in ["ingredients?", "how to use it?", "price?", "should i buy it?", "what about shipping?", "does it have a guarantee?", "what are the benefits?"]:
            with self.subTest(question=question):
                c, state = self.contract(question, state=state)
                self.assertEqual(c.permitted_document_ids, [1], c.to_debug_dict())
                rows, trace = self.retrieve(c)
                self.assertTrue(rows)
                self.assertEqual({r["document"].id for r in rows}, {1})
                self.assertEqual(trace.diagnostics["candidate_document_count"], 1)
        c, state = self.contract("what about Turmeric Boost?", state=state)
        c, state = self.contract("price?", state=state)
        self.assertEqual(c.permitted_document_ids, [2])
        c, state = self.contract("compare them", state=state)
        self.assertEqual(set(c.permitted_document_ids), {1, 2})

    def test_comparison_partial_aliases(self):
        c, _ = self.contract("compare Turmeric Boost and Sea Essence Omega 3")
        self.assertEqual(set(c.permitted_document_ids or []), {1, 2})
        rows, _ = self.retrieve(c)
        self.assertEqual({r["document"].id for r in rows}, {1, 2})

    def test_planner_schema_and_failures(self):
        documents = identity_documents(self.db, 1, 1)
        for raw in ["not json", "{}", json.dumps({**plan().model_dump(), "document_ids": [999]}),
                    json.dumps({**plan().model_dump(), "subject_confidence": 3}), " " * 12001]:
            with self.subTest(raw=raw[:50]), patch.object(planning, "generate_auxiliary", return_value=raw):
                self.assertIsNone(planning.plan_query(self.bot, "price?", [], {}, documents))
        with patch.object(planning, "generate_auxiliary", return_value=plan().model_dump_json()) as call:
            self.assertIsNotNone(planning.plan_query(self.bot, "price?", [], {}, documents))
            payload = json.loads(call.call_args.args[1])
            self.assertEqual(payload["original_user_message"], "price?")
            self.assertNotIn("document_id", json.dumps(payload))

    def test_planner_cannot_broaden_known_followup(self):
        _, state = self.contract("tell me about Sea Essence Omega 3")
        for response in [None, plan(scope_mode="catalog", needs_global_discovery=True, active_subjects=["Turmeric Boost"]),
                         plan(scope_mode="single_entity", active_subjects=["Turmeric Boost"]),
                         plan(intent="unsupported", scope_mode="global")]:
            c, _ = self.contract("price?", state=state, response=response)
            self.assertEqual(c.permitted_document_ids, [1])
            self.assertNotIn("Turmeric Boost", c.retrieval_query)
        c, _ = self.contract("should i buy it?", state=state, response=plan(intent="unsupported", scope_mode="global"))
        self.assertEqual(c.permitted_document_ids, [1])
        rows, _ = self.retrieve(c)
        self.assertTrue(rows)
        self.assertEqual({r["document"].id for r in rows}, {1})

    def test_structured_value_does_not_displace_supported_field_options(self):
        self.db.get(Document, 1).metadata_json = {"og:price:amount": "37.00", "og:price:currency": "USD"}
        c, _ = self.contract("price of Sea Essence Omega 3")
        rows, _ = self.retrieve(c)
        _, context = rag.compress_and_rerank_chunks(rows, c.original_query, query_contract=c)
        self.assertIn("$37.00", context)
        self.assertIn("$35.15", context)
        self.assertIn("Subscription", context)

    def test_parallel_recall_connections_are_independent(self):
        """Real lexical + fixture vector legs overlap without sharing a transaction."""
        c, _ = self.contract("price of Sea Essence Omega 3")
        request_connection = self.db.connection().connection.driver_connection
        request_thread = get_ident()
        rendezvous = Barrier(2)
        worker_connections = {}

        def before_select(conn, cursor, statement, parameters, context, executemany):
            thread = get_ident()
            if (thread != request_thread and thread not in worker_connections
                    and statement.lstrip().upper().startswith("SELECT")):
                worker_connections[thread] = conn.connection.driver_connection
                # Synchronization proves overlap; the timeout only prevents a hung test.
                rendezvous.wait(timeout=5)

        event.listen(self.engine, "before_cursor_execute", before_select)
        try:
            rows, trace = self.retrieve(c)
        finally:
            event.remove(self.engine, "before_cursor_execute", before_select)
        self.assertTrue(rows)
        self.assertEqual(len(worker_connections), 2)
        self.assertEqual(len({id(request_connection), *(id(conn) for conn in worker_connections.values())}), 3)
        self.assertIn("vector_search_ms", trace.timings_ms)
        self.assertIn("lexical_search_ms", trace.timings_ms)
        self.assertNotEqual(trace.retrieval.fallback_reason, "parallel_recall_failure_fallback_used")

    def test_parallel_recall_cleanup_preserves_request_transaction(self):
        """Closing either worker must not roll back the request's uncommitted write."""
        c, _ = self.contract("price of Sea Essence Omega 3")
        for iteration in range(20):
            with self.subTest(iteration=iteration):
                metadata = {"og:price:amount": "37.00", "og:price:currency": "USD",
                            "transaction_probe": iteration}
                self.db.get(Document, 1).metadata_json = metadata
                self.db.flush()
                connection = self.db.connection().connection.driver_connection
                self.assertTrue(connection.in_transaction)
                rows, trace = self.retrieve(c)
                self.assertIn("vector_search_ms", trace.timings_ms)
                self.assertIn("lexical_search_ms", trace.timings_ms)
                self.assertTrue(connection.in_transaction)
                self.db.expire_all()  # Check the database, not the ORM identity-map copy.
                self.assertEqual(self.db.get(Document, 1).metadata_json, metadata)
                _, context = rag.compress_and_rerank_chunks(rows, c.original_query, query_contract=c)
                self.assertIn("$37.00", context)
                self.assertIn("$35.15", context)
                self.assertIn("Subscription", context)
                self.db.commit()
                with self.sessions() as observer:
                    self.assertEqual(observer.get(Document, 1).metadata_json, metadata)

    def test_planner_cannot_invent_subject_from_sample_metadata(self):
        c, _ = self.contract("price?", response=plan(active_subjects=["Turmeric Boost"], scope_mode="single_entity"))
        self.assertIsNone(c.subject_document_id)
        self.assertIsNone(c.permitted_document_ids)
        _, state = self.contract("tell me about Sea Essence Omega 3")
        c, _ = self.contract("price?", state=state, response=plan(
            resolved_user_meaning="What is the price of Turmeric Boost?"))
        self.assertNotIn("Turmeric Boost", c.resolved_user_meaning)

    def test_planner_semantic_discovery_is_bounded_and_not_identity(self):
        c, _ = self.contract("I'd like to explore the range", response=plan(
            intent="catalog", scope_mode="catalog", needs_global_discovery=True))
        self.assertEqual(c.scope_mode, "catalog")
        self.assertIsNone(c.subject_document_id)
        self.assertFalse(c.requires_clarification)

    def test_discovery_finds_later_body_only_topic_before_chunk_recall(self):
        for number in range(3, 104):
            self.add_document(number, f"Offering {number}", text=[f"# Offering {number}\nGeneral overview."])
        self.db.get(Chunk, 1030).content = "# Offering 103\n## Overview\nIncludes wheelchair access and accessible facilities."
        self.db.commit()
        c, _ = self.contract("Which offerings include wheelchair access?")
        rows, trace = self.retrieve(c)
        self.assertIn(103, trace.diagnostics["permitted_document_ids"])
        self.assertLessEqual(trace.diagnostics["candidate_document_count"], 64)
        self.assertIn(103, {row["document"].id for row in rows})

    def test_unknown_switch_and_duplicate_name_remain_ambiguous(self):
        _, state = self.contract("tell me about Turmeric Boost")
        c, _ = self.contract("what about Unknown Access Bundle?", state=state,
                             response=plan(active_subjects=["Turmeric Boost"], scope_mode="single_entity"))
        self.assertIsNone(c.subject_document_id)
        self.add_document(3, "Turmeric Boost")
        c, _ = self.contract("price of Turmeric Boost")
        self.assertIsNone(c.subject_document_id)
        self.assertTrue(c.requires_clarification)
        c, _ = self.contract("What are the benefits?")
        self.assertTrue(c.requires_clarification)

    def test_tenant_and_lifecycle_constraints_precede_model(self):
        self.add_document(3, "Private Offering", bot_id=2, org_id=2)
        self.add_document(4, "Wrong Bot", bot_id=2, org_id=1)
        self.add_document(5, "Failed Offering")
        self.db.get(Document, 5).status = "failed"
        self.add_document(6, "Processing Offering")
        self.db.get(Document, 6).processing_status = "processing"
        self.db.commit()
        self.assertEqual({d.id for d in identity_documents(self.db, 1, 1)}, {1, 2})
        c, _ = self.contract("price of Private Offering", response=plan(active_subjects=["Private Offering"], scope_mode="single_entity"))
        self.assertIsNone(c.subject_document_id)
        c.permitted_document_ids = [3, 4, 5, 6]
        rows, _ = self.retrieve(c)
        self.assertEqual(rows, [])

    def test_active_crawl_only(self):
        self.db.add(Website(id=1, bot_id=1, organization_id=1, root_url="https://fixture.test", domain="fixture.test", active_crawl_id=2, status="ready"))
        self.db.add_all([WebsiteCrawl(id=i, website_id=1, bot_id=1, organization_id=1, version=i, status="ready") for i in (1, 2)])
        for number in (1, 2):
            doc = self.db.get(Document, number)
            doc.source_type, doc.website_id, doc.crawl_id, doc.version = "website", 1, number, number
            for chunk in doc.chunks:
                chunk.website_id, chunk.crawl_id = 1, number
        self.db.commit()
        self.assertEqual([d.id for d in identity_documents(self.db, 1, 1)], [2])

    def test_complete_section_and_multifield_context(self):
        c, state = self.contract("tell me about Sea Essence Omega 3")
        c, _ = self.contract("ingredients?", state=state)
        rows, _ = self.retrieve(c)
        _, context = rag.compress_and_rerank_chunks(rows, c.original_query, query_contract=c)
        for word in ["Ingredient Alpha", "Ingredient Beta", "Ingredient Gamma", "Ingredient Delta"]:
            self.assertIn(word, context)
        c, _ = self.contract("If I buy one bottle for $33, will shipping be free, does the 60-day money-back guarantee cover repeat purchases, and are results within 4–8 weeks guaranteed?", state=state,
                             response=plan(requested_fields=["price", "shipping", "returns", "results_timeframe"]))
        self.assertEqual(c.permitted_document_ids, [1])
        rows, _ = self.retrieve(c)
        _, context = rag.compress_and_rerank_chunks(rows, c.original_query, query_contract=c, max_context_chars=6000)
        for word in ["$37.00", "$35.15", "$50", "first purchases", "not guaranteed"]:
            self.assertIn(word, context)

    def test_reviewer_cannot_inject_candidates_or_drop_field_sections(self):
        c, state = self.contract("tell me about Sea Essence Omega 3")
        c, _ = self.contract("ingredients?", state=state)
        rows, _ = self.retrieve(c)
        for response in [json.dumps({"ranked_candidates": [47]}), "not json", json.dumps({"ranked_candidates": []})]:
            with patch.object(planning, "generate_auxiliary", return_value=response):
                reviewed = planning.review_evidence(self.bot, c, rows)
                required = {r["chunk"].id for r in rows if r.get("required_fields")}
                self.assertTrue(required <= {r["chunk"].id for r in reviewed})
                self.assertEqual({r["document"].id for r in reviewed}, {1})

    def test_original_user_message_reaches_real_generation_prompt(self):
        history = [{"role": "user", "content": "tell me about Sea Essence Omega 3"}]
        with patch.object(rag.global_semantic_cache, "get", return_value=None), patch.object(rag.global_semantic_cache, "set"), \
             patch.object(rag, "generate", return_value="One-time purchase is $37.00; subscription is $35.15.") as generate, \
             patch.object(rag, "verify_answer", side_effect=lambda **kwargs: kwargs["draft_answer"]), \
             patch.object(rag, "polish_answer", side_effect=lambda **kwargs: kwargs["answer"]), contextlib.redirect_stdout(io.StringIO()):
            answer, sources, chunks = rag.answer_question(self.db, self.bot, "price?", history=history, knowledge_version=1)
        self.assertIn("USER QUESTION\nprice?\n", generate.call_args.kwargs["prompt"])
        self.assertIn("Sea Essence Omega 3 Fish Oil", generate.call_args.kwargs["prompt"])
        self.assertNotIn("Turmeric Boost", generate.call_args.kwargs["prompt"])
        self.assertTrue(sources)
        self.assertEqual({c["document_id"] for c in chunks}, {1})

    def test_persistent_state_is_session_tenant_and_channel_scoped(self):
        _, state = self.contract("tell me about Sea Essence Omega 3")
        trace = ChatTrace(1, "widget", conversation_state=state)
        self.db.add(ConversationSession(id=1, bot_id=1, organization_id=1, session_id="one", channel="widget"))
        self.db.add(ConversationMessage(conversation_session_id=1, bot_id=1, organization_id=1, session_id="one", user_message="ingredients?", assistant_response="Listed ingredients.", token_usage=compact_chat_diagnostics(trace)))
        self.db.commit()
        history, loaded = planning.load_conversation(self.db, self.bot, "one", [])
        self.assertEqual(loaded["active_document_ids"], [1])
        self.assertTrue(history)
        self.assertEqual(planning.load_conversation(self.db, self.bot, "two", []), ([], {}))
        self.assertEqual(planning.load_conversation(self.db, self.bot, "one", [], "playground"), ([], {}))
        alien = SimpleNamespace(id=1, organization_id=2)
        self.assertEqual(planning.load_conversation(self.db, alien, "one", []), ([], {}))

    def test_cache_identity_separates_subjects_and_original_instruction(self):
        _, one = self.contract("tell me about Sea Essence Omega 3")
        _, two = self.contract("tell me about Turmeric Boost")
        first, _ = self.contract("price?", state=one)
        second, _ = self.contract("price?", state=two)
        a = rag.semantic_cache_identity(self.bot, "price?", [], first)
        b = rag.semantic_cache_identity(self.bot, "price?", [], second)
        self.assertNotEqual(a["config_fingerprint"], b["config_fingerprint"])
        self.assertNotEqual(a["resolved_query"], b["resolved_query"])

    def test_cache_identity_changes_on_non_max_version_and_lifecycle(self):
        first, _ = self.contract("price of Turmeric Boost")
        self.db.get(Document, 1).version = 99
        second, _ = self.contract("price of Turmeric Boost")
        self.db.get(Document, 2).version = 2
        third, _ = self.contract("price of Turmeric Boost")
        self.assertNotEqual(first.cache_fragment(), second.cache_fragment())
        self.assertNotEqual(second.cache_fragment(), third.cache_fragment())
        self.db.get(Document, 1).status = "failed"
        fourth, _ = self.contract("price of Turmeric Boost")
        self.assertNotEqual(third.cache_fragment(), fourth.cache_fragment())

    def test_unsupported_live_question_has_no_evidence_scope(self):
        _, state = self.contract("tell me about Sea Essence Omega 3")
        c, _ = self.contract("Is it raining in London right now?", state=state,
                             response=plan(intent="unsupported", scope_mode="global"))
        self.assertEqual(c.permitted_document_ids, [])
        rows, _ = self.retrieve(c)
        self.assertEqual(rows, [])

    def test_exclusion_and_qualifying_catalog_preserved(self):
        c, _ = self.contract("Exclude Turmeric Boost and tell me about Sea Essence Omega 3")
        self.assertNotIn(2, c.permitted_document_ids or [])
        c, _ = self.contract("Which options do you have and how do they compare?", response=plan(scope_mode="single_entity", active_subjects=["Turmeric Boost"]))
        self.assertIsNone(c.subject_document_id)
        self.assertIn(c.mode, {"catalog", "filter"})

    def test_scale_10_100_1000_document_scoping(self):
        last = 2
        for size in (10, 100, 1000):
            for number in range(last + 1, size + 1):
                self.add_document(number, f"Similar Offering {number}", text=[f"# Similar Offering {number}\nPrice $99. Ingredients: Generic. Usage: daily. Policy: refundable."])
            self.db.commit()
            last = size
            started = perf_counter()
            c, state = self.contract(f"tell me about Similar Offering {size}")
            self.assertEqual(c.permitted_document_ids, [size])
            for query in ["ingredients?", "price?", "what about shipping?"]:
                followup, state = self.contract(query, state=state)
                self.assertEqual(followup.permitted_document_ids, [size])
                rows, trace = self.retrieve(followup)
                self.assertEqual({r["document"].id for r in rows}, {size})
                self.assertEqual(trace.diagnostics["candidate_document_count"], 1)
                self.assertEqual(self.scopes[-1], [size])
            c, _ = self.contract(f"Compare Similar Offering {size} and Turmeric Boost")
            self.assertEqual(set(c.permitted_document_ids or []), {size, 2})
            rows, _ = self.retrieve(c)
            self.assertEqual({r["document"].id for r in rows}, {size, 2})
            c, _ = self.contract("What are the benefits?")
            self.assertTrue(c.requires_clarification)
            c, _ = self.contract("What offerings do you have?")
            self.assertIsNone(c.subject_document_id)
            rows, trace = self.retrieve(c)
            self.assertTrue(rows)
            self.assertLessEqual(trace.diagnostics["candidate_document_count"], min(size, 64))
            duplicate = self.add_document(size + 10000, f"Similar Offering {size}", text=["Duplicate identity."])
            ambiguous, _ = self.contract(f"price of Similar Offering {size}")
            self.assertTrue(ambiguous.requires_clarification)
            self.db.query(Chunk).filter(Chunk.document_id == duplicate.id).delete()
            self.db.delete(duplicate)
            self.db.commit()
            print(f"SCALE {size}: {(perf_counter()-started)*1000:.1f} ms; single-entity candidate documents=1")

    def test_blocked_page_cannot_reach_embedding_or_promotion(self):
        from services import document_processing_service as processing
        from services.firecrawl_service import Page
        doc = Document(id=3, bot_id=1, organization_id=1, filename="Web", source_type="website",
                       source_url="https://fixture.test/blocked", status="pending", processing_status="pending")
        self.db.add(doc)
        self.db.commit()
        page = Page(url=doc.source_url, title="Access denied", markdown="# Access denied\nRequest blocked.")
        with patch.object(processing, "_crawl_website_for_mode", return_value=[page]), \
             patch.object(processing, "_embed_in_cancellable_batches") as embed:
            result = processing.process_document(self.db, 3)
        embed.assert_not_called()
        self.assertEqual(result.status, "processing_failed")
        self.assertEqual(self.db.query(Chunk).filter(Chunk.document_id == 3).count(), 0)
        self.assertFalse(self.db.query(WebsiteCrawl).filter(WebsiteCrawl.status == "ready").count())


class PageQualityTests(unittest.TestCase):
    def test_blocks_http_and_soft_error_pages(self):
        for text, metadata in [("# Access denied\nRequest cannot be served.", {}),
                               ("www.example.test is blocked\n" * 500, {}),
                               ("# Verify you are human", {"statusCode": 200}),
                               ("Usable looking text", {"statusCode": 403}), ("", {})]:
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                validate_page_content(text, metadata)

    def test_support_pages_can_discuss_errors(self):
        validate_page_content("# Troubleshooting\nHow to resolve a blocked account.\nAn access denied error can occur.")
        validate_page_content("# Forbidden City tour\nDirections and admission details.")


class AuxiliaryModelTests(unittest.TestCase):
    def test_gemini_auxiliary_respects_server_minimum_without_changing_normal_generation(self):
        from services.providers.base_provider import auxiliary_budget
        from services.providers.gemini_provider import GeminiProvider
        provider = GeminiProvider()
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text="{}", usage_metadata=None)
        with patch.object(provider, "_client", return_value=client):
            token = auxiliary_budget.set({"timeout": 5.0, "tokens": 768})
            try:
                provider.generate_with_metadata("fixture", "gemini-2.5-flash", "{}")
            finally:
                auxiliary_budget.reset(token)
            config = client.models.generate_content.call_args.kwargs["config"]
            self.assertEqual(config.http_options.timeout, 10000)
            self.assertEqual(config.thinking_config.thinking_budget, 0)
            self.assertEqual(config.max_output_tokens, 768)
            provider.generate_with_metadata("fixture", "gemini-2.5-flash", "normal")
            config = client.models.generate_content.call_args.kwargs["config"]
            self.assertIsNone(config.http_options)
            self.assertIsNone(config.thinking_config)
            self.assertIsNone(config.max_output_tokens)

    def test_configured_provider_model_one_attempt_and_budget(self):
        from services import llm_router as router
        from services.providers.base_provider import auxiliary_budget
        bot = SimpleNamespace(provider="openai", model_name="configured-model", id=7, organization_id=11)
        seen = []
        def generate(**kwargs):
            seen.append((kwargs["model_name"], auxiliary_budget.get()))
            return SimpleNamespace(text="{}", usage=None)
        provider = SimpleNamespace(generate_with_metadata=generate)
        with patch.dict(router.PROVIDERS, {"openai": provider}), \
             patch.object(router, "_resolve_api_key", return_value=("fixture", False)), \
             patch.object(router, "execute_with_resilience", side_effect=lambda fn, *a, **kw: fn()) as resilient:
            self.assertEqual(router.generate_auxiliary(bot, "{}", "schema", timeout=1.0, tokens=128), "{}")
        self.assertEqual(seen, [("configured-model", {"timeout": 1.0, "tokens": 128})])
        self.assertEqual(resilient.call_args.kwargs["max_retries"], 0)
        self.assertIsNone(auxiliary_budget.get())

    def test_timeout_does_not_queue_unbounded_calls(self):
        from services import llm_router as router
        release = Event()
        finished = Event()
        def generate(**kwargs):
            try:
                release.wait(2)
                return SimpleNamespace(text="{}", usage=None)
            finally:
                finished.set()
        bot = SimpleNamespace(provider="openai", model_name="configured-model", id=7, organization_id=11)
        with patch.dict(router.PROVIDERS, {"openai": SimpleNamespace(generate_with_metadata=generate)}), \
             patch.object(router, "_resolve_api_key", return_value=("fixture", False)), \
             patch.object(router, "execute_with_resilience", side_effect=lambda fn, *a, **kw: fn()):
            try:
                with self.assertRaises(TimeoutError):
                    router.generate_auxiliary(bot, "{}", "schema", timeout=0.02)
            finally:
                release.set()
                self.assertTrue(finished.wait(2))


if __name__ == "__main__":
    unittest.main()
