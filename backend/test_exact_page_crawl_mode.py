import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from routes import knowledge_routes
from schemas.schemas import KnowledgeCrawlRequest
from services.document_processing_service import _crawl_website_for_mode
from services.firecrawl_service import CrawlAuditReport, Page, scrape_single_page_with_audit


class TestExactPageCrawlMode(unittest.TestCase):
    def test_request_contract_defaults_to_existing_recursive_mode(self):
        default_request = KnowledgeCrawlRequest(bot_id=7, url="https://example.com/docs")
        exact_request = KnowledgeCrawlRequest(
            bot_id=7,
            url="https://example.com/docs",
            crawl_mode="single_page",
        )
        self.assertEqual(default_request.crawl_mode, "recursive")
        self.assertEqual(exact_request.crawl_mode, "single_page")
        with self.assertRaises(ValidationError):
            KnowledgeCrawlRequest(bot_id=7, url="https://example.com/docs", crawl_mode="broad")

    @patch("services.firecrawl_service.validate_crawl_url", return_value="https://example.com/catalog?page=1")
    @patch("services.firecrawl_service.httpx.Client")
    def test_single_page_uses_scrape_and_never_ingests_discovered_children(self, client_class, _validate):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "success": True,
            "data": {
                "markdown": "# Catalog\n\nUseful catalog copy. [Child](https://example.com/products/child)",
                "metadata": {
                    "title": "Catalog",
                    "sourceURL": "https://example.com/catalog?page=1",
                    "canonicalURL": "https://example.com/catalog",
                    "statusCode": 200,
                },
            },
        }
        client = MagicMock()
        client.post.return_value = response
        client_class.return_value.__enter__.return_value = client

        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            pages, audit = scrape_single_page_with_audit("https://example.com/catalog?page=1")

        self.assertEqual([page.url for page in pages], ["https://example.com/catalog?page=1"])
        self.assertEqual(pages[0].metadata["canonicalURL"], "https://example.com/catalog")
        self.assertEqual(audit.crawled_list, ["https://example.com/catalog?page=1"])
        self.assertEqual(audit.crawled_urls, 1)
        self.assertEqual(audit.eligible_urls, 1)
        self.assertEqual(audit.skipped_urls["https://example.com/products/child"], "single_page_mode")
        endpoint = client.post.call_args.args[0]
        self.assertTrue(endpoint.endswith("/v1/scrape"))
        self.assertEqual(client.post.call_args.kwargs["json"]["url"], "https://example.com/catalog?page=1")
        client.get.assert_not_called()

    def test_mode_dispatch_preserves_recursive_behavior(self):
        page = Page(url="https://example.com", title="Home", markdown="content")
        audit = CrawlAuditReport(seed_url=page.url, crawled_urls=1)
        cancel_check = lambda: False
        with patch("services.document_processing_service.scrape_single_page_with_audit", return_value=([page], audit)) as scrape, patch(
            "services.document_processing_service.crawl_website", return_value=([page], audit)
        ) as crawl:
            self.assertEqual(_crawl_website_for_mode(page.url, "single_page", cancel_check), ([page], audit))
            scrape.assert_called_once_with(page.url, cancel_check=cancel_check)
            crawl.assert_not_called()

        with patch("services.document_processing_service.scrape_single_page_with_audit") as scrape, patch(
            "services.document_processing_service.crawl_website", return_value=([page], audit)
        ) as crawl:
            self.assertEqual(_crawl_website_for_mode(page.url, "recursive", cancel_check), ([page], audit))
            crawl.assert_called_once_with(page.url, return_audit=True, cancel_check=cancel_check)
            scrape.assert_not_called()

    def test_route_keeps_tenant_rate_limit_and_quota_checks_and_forwards_mode(self):
        request = KnowledgeCrawlRequest(
            bot_id=674,
            url="https://example.com/product",
            crawl_mode="single_page",
        )
        user = object()
        db = object()
        bot = SimpleNamespace(id=674, organization_id=91)
        document = SimpleNamespace(id=22, website_id=None)
        job = SimpleNamespace(job_id="job-exact")
        with patch.object(knowledge_routes, "_ensure_bot", return_value=bot) as ensure_bot, patch.object(
            knowledge_routes, "enforce_rate_limit"
        ) as rate_limit, patch.object(knowledge_routes, "ensure_can_add_document") as quota, patch.object(
            knowledge_routes, "create_website_document", return_value=document
        ) as create_document, patch.object(knowledge_routes, "clear_retrieval_cache"), patch.object(
            knowledge_routes, "record_usage"
        ), patch.object(knowledge_routes, "enqueue_ingestion_job", return_value=job), patch.object(
            knowledge_routes, "serialize_document", return_value={"id": 22}
        ):
            result = knowledge_routes.crawl_website(request, BackgroundTasks(), user, db)

        ensure_bot.assert_called_once_with(db, 674, user, "admin")
        rate_limit.assert_called_once_with(scope="crawl", org_id=91, bot_id=674)
        quota.assert_called_once_with(db, 91)
        create_document.assert_called_once_with(
            db,
            bot_id=674,
            url="https://example.com/product",
            crawl_mode="single_page",
        )
        self.assertEqual(result["job_id"], "job-exact")

    def test_quota_rejection_stops_before_document_or_job_creation(self):
        request = KnowledgeCrawlRequest(bot_id=674, url="https://example.com/product", crawl_mode="single_page")
        bot = SimpleNamespace(id=674, organization_id=91)
        with patch.object(knowledge_routes, "_ensure_bot", return_value=bot), patch.object(
            knowledge_routes, "enforce_rate_limit"
        ), patch.object(
            knowledge_routes,
            "ensure_can_add_document",
            side_effect=HTTPException(status_code=402, detail="PLAN_QUOTA_EXCEEDED"),
        ), patch.object(knowledge_routes, "create_website_document") as create_document, patch.object(
            knowledge_routes, "enqueue_ingestion_job"
        ) as enqueue:
            with self.assertRaises(HTTPException):
                knowledge_routes.crawl_website(request, BackgroundTasks(), object(), object())
        create_document.assert_not_called()
        enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
