import unittest
from unittest.mock import MagicMock, patch
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from services.firecrawl_service import (
    FirecrawlError,
    Page,
    crawl_website,
    extract_title_from_markdown,
    get_firecrawl_config,
    validate_crawl_url,
)


class TestFirecrawlService(unittest.TestCase):

    def test_validate_crawl_url(self):
        # Valid URLs
        self.assertEqual(validate_crawl_url("https://example.com"), "https://example.com")
        self.assertEqual(validate_crawl_url("http://example.org/docs"), "http://example.org/docs")

        # Invalid URLs
        with self.assertRaises(FirecrawlError):
            validate_crawl_url("ftp://example.com")
        with self.assertRaises(FirecrawlError):
            validate_crawl_url("not-a-url")
        with self.assertRaises(FirecrawlError):
            validate_crawl_url("http://127.0.0.1")

    def test_extract_title_from_markdown(self):
        md = "# My Page Title\n\nSome paragraph text."
        self.assertEqual(extract_title_from_markdown(md, "Default"), "My Page Title")

        md_no_h1 = "Just paragraph text without h1 header."
        self.assertEqual(extract_title_from_markdown(md_no_h1, "Default"), "Default")

    def test_missing_api_key_raises_error(self):
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": ""}):
            with self.assertRaises(FirecrawlError) as ctx:
                crawl_website("https://example.com")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("FIRECRAWL_API_KEY", ctx.exception.message)

    @patch("services.firecrawl_service.httpx.Client")
    def test_mock_crawl_website_success(self, mock_client_cls):
        mock_post_res = MagicMock()
        mock_post_res.status_code = 200
        mock_post_res.json.return_value = {"success": True, "id": "job_12345"}

        mock_poll_res = MagicMock()
        mock_poll_res.status_code = 200
        mock_poll_res.json.return_value = {
            "status": "completed",
            "data": [
                {
                    "markdown": "# Home Page\n\nWelcome to example website.",
                    "metadata": {
                        "title": "Home Page",
                        "sourceURL": "https://example.com",
                        "statusCode": 200,
                    },
                },
                {
                    "markdown": "# About Us\n\nLearn more about us here.",
                    "metadata": {
                        "title": "About Us",
                        "sourceURL": "https://example.com/about",
                        "statusCode": 200,
                    },
                },
            ],
        }

        mock_client = MagicMock()
        mock_client.post.return_value = mock_post_res
        mock_client.get.return_value = mock_poll_res
        mock_client_cls.return_value.__enter__.return_value = mock_client

        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test-key-123"}):
            pages = crawl_website("https://example.com")

        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].url, "https://example.com")
        self.assertEqual(pages[0].title, "Home Page")
        self.assertIn("Welcome to example website.", pages[0].markdown)
        self.assertEqual(pages[1].url, "https://example.com/about")
        self.assertEqual(pages[1].title, "About Us")


if __name__ == "__main__":
    unittest.main()
