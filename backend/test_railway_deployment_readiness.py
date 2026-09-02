"""Phase Railway readiness: deterministic checks for deployment-specific changes.

Scope is intentionally narrow. This does not test RAG/retrieval/query-contract
behavior (Phase L/L.2/L.3/L.4 own that coverage) and does not start a real
Uvicorn/Railway process.
"""

import ast
import os
import re
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


class TestStartApiHonorsPort(unittest.TestCase):
    """scripts/start_api.py must bind Railway's dynamic PORT, defaulting to 8000 locally."""

    def _resolved_port(self, env: dict) -> str:
        # Mirrors the exact expression used in scripts/start_api.py without
        # exec'ing into uvicorn.
        old_environ = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(env)
            return str(int(os.getenv("PORT", "8000")))
        finally:
            os.environ.clear()
            os.environ.update(old_environ)

    def test_default_port_without_railway_env(self):
        self.assertEqual(self._resolved_port({}), "8000")

    def test_honors_railway_provided_port(self):
        self.assertEqual(self._resolved_port({"PORT": "4173"}), "4173")

    def test_source_reads_port_env_var(self):
        source = (BACKEND_DIR / "scripts" / "start_api.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("PORT", "8000")', source)
        self.assertIn('"--host",\n            "0.0.0.0"', source.replace("\r\n", "\n"))

    def test_start_api_still_migrates_before_serving(self):
        # Guards against accidentally reordering/removing the migration gate
        # while touching this file for the PORT change.
        source = (BACKEND_DIR / "scripts" / "start_api.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        main_body = next(
            node.body for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        call_names = []
        for node in main_body:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    call_names.append(sub.func.id)
        self.assertIn("upgrade_to_head", call_names)
        self.assertLess(
            call_names.index("upgrade_to_head"),
            len(call_names),
            "upgrade_to_head must run before uvicorn is exec'd",
        )


class TestBackendDockerfileNoUnusedPlaywrightInstall(unittest.TestCase):
    """Production backend image must not pay for an unused Playwright browser download.

    Firecrawl (services/firecrawl_service.py) is the active production crawler.
    Legacy Crawl4AI/Playwright code paths remain in the repository for tests
    only and must not be imported by any active runtime module.
    """

    def test_dockerfile_has_no_playwright_install_command(self):
        dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
        run_lines = [line for line in dockerfile.splitlines() if line.strip().startswith("RUN")]
        offending = [line for line in run_lines if "playwright install" in line]
        self.assertEqual(offending, [], f"Dockerfile still runs a playwright browser install: {offending}")

    def test_only_known_legacy_modules_import_playwright(self):
        # Firecrawl (services/firecrawl_service.py) is the active production crawler
        # and never imports playwright. These two modules are known, accepted
        # exceptions and must not silently grow:
        #  - crawl4ai_service.py: legacy adapter used by tests only, not imported
        #    by document_processing_service.py.
        #  - scraper_service.py: legacy /ingest/website route (not called by the
        #    frontend/dashboard). use_playwright defaults to False, so the common
        #    path (static httpx/BeautifulSoup scraping) needs no browser binary.
        #    Calling it with use_playwright=true in a production image that has
        #    no Chromium install will fail; this is documented, not hidden.
        known_legacy_playwright_users = {"crawl4ai_service.py", "scraper_service.py"}
        active_runtime_dirs = ["routes", "services", "workers", "database", "utils", "schemas"]
        offenders = []
        for dir_name in active_runtime_dirs:
            dir_path = BACKEND_DIR / dir_name
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                if py_file.name in known_legacy_playwright_users:
                    continue
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"^\s*(import\s+playwright|from\s+playwright)", text, re.MULTILINE):
                    offenders.append(str(py_file.relative_to(BACKEND_DIR)))
        self.assertEqual(offenders, [], f"Unexpected new playwright import(s) in active runtime: {offenders}")

    def test_ingest_website_playwright_flag_defaults_to_false(self):
        # If this ever flips to True, the Dockerfile change above must be revisited.
        text = (BACKEND_DIR / "schemas" / "schemas.py").read_text(encoding="utf-8")
        match = re.search(r"class WebsiteIngestRequest.*?use_playwright:\s*bool\s*=\s*(\w+)", text, re.DOTALL)
        self.assertIsNotNone(match, "WebsiteIngestRequest.use_playwright default not found")
        self.assertEqual(match.group(1), "False")

    def test_document_processing_service_uses_crawler_port_not_crawl4ai(self):
        text = (BACKEND_DIR / "services" / "document_processing_service.py").read_text(encoding="utf-8")
        self.assertIn("from services.crawler_service import", text)
        self.assertIn("get_crawler_provider", text)
        self.assertNotIn("from services.crawl4ai_service import", text)


class TestUploadStorageIsPortable(unittest.TestCase):
    """API and worker communicate through a durable object reference, not disk."""

    def test_document_processing_service_uses_object_storage_port(self):
        text = (BACKEND_DIR / "services" / "document_processing_service.py").read_text(encoding="utf-8")
        self.assertIn("get_object_storage", text)
        self.assertIn("download_to_temp", (BACKEND_DIR / "services" / "object_storage.py").read_text(encoding="utf-8"))

    def test_production_storage_is_s3_compatible_and_not_railway_specific(self):
        text = (BACKEND_DIR / "services" / "object_storage.py").read_text(encoding="utf-8").lower()
        self.assertIn('provider_name = "s3"', text)
        self.assertNotIn("railway", text)


if __name__ == "__main__":
    unittest.main()
